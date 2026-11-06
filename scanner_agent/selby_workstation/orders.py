"""Local production identity registry. Never writes grading evidence."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from spectra_scanner.common import utc_now
from spectra_scanner.storage import sha256_file

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "local_data/selby_workstation/orders.sqlite3"
AUTHORIZATION_PATH = Path(__file__).with_name("orders_authorization.json")
ORDER_TRANSITIONS = {
    "draft": ("received", "cancelled"),
    "received": ("processing", "cancelled"),
    "processing": ("completed", "cancelled"),
    "completed": ("shipped",), "shipped": (), "cancelled": (),
}
CARD_TRANSITIONS = {
    "registered": ("processing", "cancelled"),
    "processing": ("completed", "cancelled"),
    "completed": (), "cancelled": (),
}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class OrderStore:
    def __init__(self, path=DEFAULT_PATH, authorization_path=AUTHORIZATION_PATH):
        self.path = Path(path)
        self.authorization_path = Path(authorization_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 2:
                return  # Bridge migration is additive; never reset its schema version.
            if version not in (0, 1):
                raise ValueError("Unsupported orders schema; no automatic migration")
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS orders (
                    number INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT UNIQUE,
                    customer_name TEXT NOT NULL CHECK(length(trim(customer_name)) > 0),
                    contact TEXT NOT NULL,
                    external_reference TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    received_at_utc TEXT,
                    status TEXT NOT NULL CHECK(status IN
                        ('draft','received','processing','completed','shipped','cancelled'))
                );
                CREATE TABLE IF NOT EXISTS cards (
                    number INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT UNIQUE,
                    order_id TEXT NOT NULL REFERENCES orders(id),
                    position INTEGER NOT NULL CHECK(position > 0),
                    metadata TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                        ('registered','processing','completed','cancelled')),
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    session_reference TEXT,
                    session_id TEXT UNIQUE,
                    certification_reference TEXT CHECK(certification_reference IS NULL),
                    UNIQUE(order_id, position)
                );
                CREATE TABLE IF NOT EXISTS audit (
                    number INTEGER PRIMARY KEY AUTOINCREMENT,
                    at_utc TEXT NOT NULL, entity TEXT NOT NULL,
                    operation TEXT NOT NULL, operator TEXT NOT NULL,
                    before_json TEXT NOT NULL, after_json TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS order_identity BEFORE UPDATE OF id,number ON orders
                    WHEN OLD.id IS NOT NULL
                    BEGIN SELECT RAISE(ABORT, 'Immutable order identity'); END;
                CREATE TRIGGER IF NOT EXISTS card_identity
                    BEFORE UPDATE OF id,number,order_id,position ON cards
                    WHEN OLD.id IS NOT NULL
                    BEGIN SELECT RAISE(ABORT, 'Immutable card identity and order position'); END;
                CREATE TRIGGER IF NOT EXISTS keep_orders BEFORE DELETE ON orders
                    BEGIN SELECT RAISE(ABORT, 'Orders cannot be deleted'); END;
                CREATE TRIGGER IF NOT EXISTS keep_cards BEFORE DELETE ON cards
                    BEGIN SELECT RAISE(ABORT, 'Cards cannot be deleted'); END;
                CREATE TRIGGER IF NOT EXISTS keep_audit_update BEFORE UPDATE ON audit
                    BEGIN SELECT RAISE(ABORT, 'Audit is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS keep_audit_delete BEFORE DELETE ON audit
                    BEGIN SELECT RAISE(ABORT, 'Audit is append-only'); END;
                PRAGMA user_version=1;
                COMMIT;
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _event(self, db, entity, operation, operator, before, after, reason=""):
        db.execute("INSERT INTO audit(at_utc,entity,operation,operator,before_json,after_json,reason) "
                   "VALUES(?,?,?,?,?,?,?)", (utc_now(), entity, operation, operator.strip(),
                                             encode(before), encode(after), reason))

    @staticmethod
    def _get(db, table, identity):
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown {table} identity: {identity}")
        result = dict(row)
        if table == "cards":
            result["metadata"] = json.loads(result["metadata"])
            result["session_reference"] = json.loads(result["session_reference"] or "null")
        else:
            result["card_count"] = db.execute(
                "SELECT count(*) FROM cards WHERE order_id=?", (identity,)).fetchone()[0]
        return result

    def get_order(self, identity):
        with self.connection() as db:
            return self._get(db, "orders", identity)

    def get_card(self, identity):
        with self.connection() as db:
            return self._get(db, "cards", identity)

    def search_orders(self, query=""):
        with self.connection() as db:
            rows = db.execute("SELECT id FROM orders WHERE instr(lower(id),lower(?)) > 0 "
                              "OR instr(lower(customer_name),lower(?)) > 0 ORDER BY number DESC",
                              (query.strip(), query.strip()))
            return [self._get(db, "orders", row[0]) for row in rows]

    def search_card(self, identity):
        return self.get_card(identity.strip().upper())

    def cards(self, order_id):
        with self.connection() as db:
            self._get(db, "orders", order_id)
            return [self._get(db, "cards", row[0]) for row in db.execute(
                "SELECT id FROM cards WHERE order_id=? ORDER BY position", (order_id,))]

    def history(self, identity):
        with self.connection() as db:
            return [dict(row, before=json.loads(row["before_json"]),
                         after=json.loads(row["after_json"])) for row in db.execute(
                             "SELECT * FROM audit WHERE entity=? ORDER BY number", (identity,))]

    def create_order(self, customer_name, contact="", external_reference="", notes="", operator=""):
        with self.transaction() as db:
            number = db.execute(
                "INSERT INTO orders(customer_name,contact,external_reference,notes,created_at_utc,"
                "status) VALUES(?,?,?,?,?,'draft')",
                (customer_name.strip(), contact, external_reference, notes, utc_now())).lastrowid
            identity = f"ORD-{number:06d}"
            db.execute("UPDATE orders SET id=? WHERE number=?", (identity, number))
            self._event(db, identity, "order_created", operator, None,
                        self._get(db, "orders", identity))
        return self.get_order(identity)

    def update_customer(self, identity, customer_name, contact="", external_reference="",
                        notes="", operator=""):
        with self.transaction() as db:
            before = self._get(db, "orders", identity)
            db.execute("UPDATE orders SET customer_name=?,contact=?,external_reference=?,notes=? "
                       "WHERE id=?", (customer_name.strip(), contact, external_reference, notes,
                                      identity))
            self._event(db, identity, "customer_updated", operator, before,
                        self._get(db, "orders", identity))

    def add_cards(self, order_id, count=1, metadata=None, position=None, operator=""):
        if type(count) is not int or not 1 <= count <= 1000:
            raise ValueError("Add between 1 and 1000 cards per transaction")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("Card metadata must be an object")
        if position is not None and (type(position) is not int or position < 1):
            raise ValueError("Position must be a positive integer")
        identities = []
        with self.transaction() as db:
            order = self._get(db, "orders", order_id)
            if db.execute("PRAGMA user_version").fetchone()[0] == 2 and db.execute(
                "SELECT 1 FROM bridge_orders WHERE order_id=?", (order_id,)
            ).fetchone():
                raise ValueError("Mapped production orders receive cards only through the backend identity bridge")
            if order["status"] not in ("draft", "received"):
                raise ValueError("Cards can only be added to draft or received orders")
            start = position if position is not None else db.execute(
                "SELECT coalesce(max(position),0)+1 FROM cards WHERE order_id=?",
                (order_id,)).fetchone()[0]
            for offset in range(count):
                now = utc_now()
                number = db.execute(
                    "INSERT INTO cards(order_id,position,metadata,status,created_at_utc,"
                    "updated_at_utc) VALUES(?,?,?,'registered',?,?)",
                    (order_id, start + offset, encode(metadata or {}), now, now)).lastrowid
                identity = f"SLB-C-{number:06d}"
                db.execute("UPDATE cards SET id=? WHERE number=?", (identity, number))
                self._event(db, identity, "card_created", operator, None,
                            self._get(db, "cards", identity))
                identities.append(identity)
        return [self.get_card(identity) for identity in identities]

    def _authorize(self, operator, reason):
        if not operator.strip() or not reason.strip():
            raise ValueError("Correction requires operator identity and a reason")
        allowed = json.loads(self.authorization_path.read_text(encoding="utf-8"))
        if operator not in allowed.get("authorized_operators", []):
            raise ValueError("Operator is not authorized for identity/status corrections")

    def transition(self, identity, status, operator="", reason="", correction=False):
        table, transitions = (("orders", ORDER_TRANSITIONS) if identity.startswith("ORD-")
                              else ("cards", CARD_TRANSITIONS))
        with self.transaction() as db:
            before = self._get(db, table, identity)
            if status not in transitions or status == before["status"]:
                raise ValueError("Unknown or unchanged status")
            if correction:
                self._authorize(operator, reason)
            elif status not in transitions[before["status"]]:
                raise ValueError("Invalid status transition; authorized correction required")
            if table == "cards" and not correction:
                parent = self._get(db, "orders", before["order_id"])
                if parent["status"] in ("cancelled", "shipped"):
                    raise ValueError("Parent order is cancelled or shipped")
            db.execute(f"UPDATE {table} SET status=? WHERE id=?", (status, identity))
            if table == "cards":
                db.execute("UPDATE cards SET updated_at_utc=? WHERE id=?", (utc_now(), identity))
            elif status == "received" and before["received_at_utc"] is None:
                db.execute("UPDATE orders SET received_at_utc=? WHERE id=?", (utc_now(), identity))
            self._event(db, identity, "status_corrected" if correction else "status_changed",
                        operator, before, self._get(db, table, identity), reason)

    def associate_session(self, identity, path, operator, reason):
        """Explicit external link, pinned to a saved V0.4 dossier, never a JSON edit."""
        from .session import Session

        if not operator.strip() or not reason.strip():
            raise ValueError("Session association requires operator and pairing explanation")
        path = Path(path).resolve()
        session = Session.reopen(path)  # Reuses all original/source/parent validation.
        working = session.data.get("grading", {}).get("working")
        if not working:
            raise ValueError("Select a saved grading dossier, not an inspection-only session")
        declared = working["card_id"]
        if declared.startswith("SLB-C-") and declared != identity:
            raise ValueError("Grading dossier declares another internal card identity")
        reference = dict(path=str(path), sha256=session.saved_sha,
                         session_id=session.data["session_id"],
                         version_id=session.data["version_id"], declared_card_id=declared,
                         mode="explicit_external_association")
        with self.transaction() as db:
            before = self._get(db, "cards", identity)
            if before["session_reference"] == reference:
                raise ValueError("This saved version is already associated")
            if before["session_reference"]:
                self._authorize(operator, reason)
            if sha256_file(path) != reference["sha256"]:
                raise ValueError("Session changed during association")
            db.execute("UPDATE cards SET session_reference=?,session_id=?,updated_at_utc=? "
                       "WHERE id=?", (encode(reference), reference["session_id"], utc_now(), identity))
            self._event(db, identity, "session_associated", operator, before,
                        self._get(db, "cards", identity), reason)

    def unlink_session(self, identity, operator, reason):
        with self.transaction() as db:
            self._authorize(operator, reason)
            before = self._get(db, "cards", identity)
            if before["session_reference"] is None:
                raise ValueError("No session association to correct")
            db.execute("UPDATE cards SET session_reference=NULL,session_id=NULL,updated_at_utc=? "
                       "WHERE id=?", (utc_now(), identity))
            self._event(db, identity, "session_unlinked", operator, before,
                        self._get(db, "cards", identity), reason)

    def verify_association(self, identity):
        from .session import Session

        reference = self.get_card(identity)["session_reference"]
        if not reference:
            raise ValueError("Card has no associated grading session")
        if sha256_file(Path(reference["path"])) != reference["sha256"]:
            raise ValueError("Associated session changed")
        session = Session.reopen(Path(reference["path"]))
        if session.saved_sha != reference["sha256"]:
            raise ValueError("Associated session changed during verification")
        return reference
