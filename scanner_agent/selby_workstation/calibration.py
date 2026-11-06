"""Fixed diagnostic content and isolated local retry history. No backend dependency."""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .thermal_printing import render_label

DIAGNOSTIC_PAYLOAD = "SELBY:TEST:V1:CALIBRATION"
DIAGNOSTIC_REFERENCE = "CALIBRATION-V1"


def encode_diagnostic(identifier=DIAGNOSTIC_REFERENCE):
    if identifier != DIAGNOSTIC_REFERENCE:
        raise ValueError("Unsupported diagnostic identifier")
    return DIAGNOSTIC_PAYLOAD


def decode_diagnostic(value):
    if value != DIAGNOSTIC_PAYLOAD:
        raise ValueError("Unsupported diagnostic payload")
    return DIAGNOSTIC_REFERENCE


def render_diagnostic(dpi=203):
    return render_label(
        dict(
            kind="diagnostic",
            reference=DIAGNOSTIC_REFERENCE,
            payload=encode_diagnostic(),
            text="50 x 30 mm\nCalibration only",
        ),
        dpi=dpi,
    )


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class DiagnosticHistory:
    def __init__(self, path):
        self.path = Path(path)

    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=2)
        # Keep the pre-submission intent durable before calling the shared Qt engine.
        db.execute("PRAGMA synchronous=FULL")
        db.execute("""CREATE TABLE IF NOT EXISTS diagnostic_jobs (
            id TEXT PRIMARY KEY, printer TEXT NOT NULL, payload TEXT NOT NULL,
            created_at TEXT NOT NULL, outcome TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
            reviewed_at TEXT, finished_at TEXT)""")
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS diagnostic_pending ON diagnostic_jobs(printer) WHERE outcome IN ('submitting','uncertain') AND reviewed_at IS NULL"
        )
        db.commit()
        return db

    def reserve(self, printer):
        db = self.connection()
        try:
            db.execute("BEGIN IMMEDIATE")
            identifier = str(uuid4())
            db.execute(
                "INSERT INTO diagnostic_jobs(id,printer,payload,created_at,outcome) VALUES(?,?,?,?,?)",
                (identifier, printer, DIAGNOSTIC_PAYLOAD, timestamp(), "submitting"),
            )
            db.commit()
            return identifier
        except sqlite3.IntegrityError:
            db.rollback()
            raise ValueError(
                "An earlier diagnostic submission is uncertain. Inspect the Windows queue and physical output, then use Review uncertain diagnostic. No repeat job was sent."
            ) from None
        finally:
            db.close()

    def finish(self, identifier, outcome, error=""):
        if outcome not in ("submitted", "uncertain"):
            raise ValueError("Invalid diagnostic outcome")
        with closing(self.connection()) as db, db:
            changed = db.execute(
                "UPDATE diagnostic_jobs SET outcome=?, error=?, finished_at=? WHERE id=? AND outcome='submitting'",
                (outcome, error[:1000], timestamp(), identifier),
            ).rowcount
            if changed != 1:
                raise ValueError("Diagnostic job is already closed; no resubmission is permitted.")

    def review(self, printer):
        with closing(self.connection()) as db, db:
            return db.execute(
                "UPDATE diagnostic_jobs SET reviewed_at=? WHERE printer=? AND outcome IN ('submitting','uncertain') AND reviewed_at IS NULL",
                (timestamp(), printer),
            ).rowcount
