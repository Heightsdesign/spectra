"""Durable technical request intents; never a copy of custody business state.

One pending request per backend scope/submission, shared across local windows.
No cookies, tokens, passwords, local order IDs or grading data are accepted.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from .incoming import PreviewError

DEFAULT_JOURNAL = (
    Path(__file__).resolve().parents[1] / "local_data/selby_workstation/intake_requests.sqlite3"
)
FIELDS = {
    "parcel": {"carrier", "tracking", "notes"},
    "card": {"parcel_id", "notes"},
    "transition": {"action", "reason"},
    "match": {"entry_id", "reason"},
    "issue": {"kind", "entry_id", "card_id", "quantity", "notes"},
    "resolve": {"status", "reason"},
    "void": {"reason"},
}


class IntakeJournal:
    def __init__(self, path=DEFAULT_JOURNAL):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS pending (scope TEXT NOT NULL, sid TEXT NOT NULL, operation TEXT NOT NULL, PRIMARY KEY(scope,sid))"
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def pending(self, scope, sid):
        with self.connect() as db:
            row = db.execute(
                "SELECT operation FROM pending WHERE scope=? AND sid=?", (scope, str(UUID(sid)))
            ).fetchone()
        return json.loads(row[0]) if row else None

    def begin(self, scope, sid, kind, payload, target=None):
        if kind not in FIELDS or set(payload) - FIELDS[kind]:
            raise PreviewError("Unsupported intake intent fields.")
        sid = str(UUID(sid))
        operation = {
            "id": str(uuid4()),
            "sid": sid,
            "kind": kind,
            "payload": dict(payload),
            "target": str(UUID(target)) if target else None,
        }
        if kind in ("parcel", "card"):
            operation["payload"]["request_key"] = operation["id"]
        with self.connect() as db:
            try:
                db.execute(
                    "INSERT INTO pending VALUES (?,?,?)",
                    (scope, sid, json.dumps(operation, allow_nan=False)),
                )
            except sqlite3.IntegrityError:
                raise PreviewError(
                    "A pending operation already exists. Refresh and recover it before starting another receipt."
                ) from None
        return operation

    def finish(self, scope, operation):
        # Compare exact intent, so another window cannot clear a newer request.
        with self.connect() as db:
            row = db.execute(
                "SELECT operation FROM pending WHERE scope=? AND sid=?", (scope, operation["sid"])
            ).fetchone()
            if row and json.loads(row[0]) == operation:
                db.execute("DELETE FROM pending WHERE scope=? AND sid=?", (scope, operation["sid"]))

    def run(self, scope, operation, client):
        if self.pending(scope, operation["sid"]) != operation:
            raise PreviewError("Pending request changed in another window. Refresh before acting.")
        result = client.execute(operation)
        self.finish(scope, operation)
        return result

    def retry(self, scope, sid, client):
        operation = self.pending(scope, sid)
        if not operation or operation["kind"] not in ("parcel", "card", "void"):
            raise PreviewError(
                "Only parcel/card creation and void support replay. Refresh and review the audit for other operations."
            )
        return self.run(scope, operation, client)
