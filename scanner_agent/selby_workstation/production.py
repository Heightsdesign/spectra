"""Durable production bridge. SQLite commits before remote confirmation."""

import sqlite3
from uuid import UUID, uuid4

from spectra_scanner.common import utc_now

from .orders import OrderStore, encode


class BridgeConflict(ValueError):
    pass


class ProductionStore(OrderStore):
    def __init__(self, path):
        super().__init__(path)
        with self.transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 2:
                return
            # Another connection reads the stable committed image while this
            # transaction excludes writers. backup() includes WAL contents.
            backup = self.path.with_name(self.path.name + f".v1-{uuid4().hex}.bak")
            with self.connection() as source:
                target = sqlite3.connect(backup)
                try:
                    source.backup(target)
                    if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise BridgeConflict("Registry backup failed integrity validation")
                finally:
                    target.close()
            statements = [
                "CREATE TABLE bridge_registry (singleton INTEGER PRIMARY KEY CHECK(singleton=1), id TEXT NOT NULL UNIQUE)",
                "CREATE UNIQUE INDEX bridge_card_parent ON cards(id,order_id)",
                """CREATE TABLE bridge_orders (
                    scope TEXT NOT NULL, sid TEXT NOT NULL, sp TEXT NOT NULL,
                    order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
                    mode TEXT NOT NULL CHECK(mode IN ('create','adopt')),
                    confirmed INTEGER NOT NULL DEFAULT 0 CHECK(confirmed IN (0,1)),
                    PRIMARY KEY(scope,sid), UNIQUE(scope,sid,order_id))""",
                """CREATE TABLE bridge_cards (
                    scope TEXT NOT NULL, sid TEXT NOT NULL, pc_id TEXT NOT NULL,
                    pc TEXT NOT NULL, order_id TEXT NOT NULL, card_id TEXT NOT NULL UNIQUE,
                    PRIMARY KEY(scope,pc_id), UNIQUE(scope,pc),
                    FOREIGN KEY(scope,sid,order_id) REFERENCES bridge_orders(scope,sid,order_id),
                    FOREIGN KEY(card_id,order_id) REFERENCES cards(id,order_id))""",
                """CREATE TRIGGER bridge_order_identity BEFORE UPDATE ON bridge_orders
                    WHEN OLD.scope!=NEW.scope OR OLD.sid!=NEW.sid OR OLD.sp!=NEW.sp
                    OR OLD.order_id!=NEW.order_id OR OLD.mode!=NEW.mode OR OLD.confirmed>NEW.confirmed
                    BEGIN SELECT RAISE(ABORT,'Immutable production mapping'); END""",
            ]
            for table in ("bridge_registry", "bridge_cards"):
                for action in ("UPDATE", "DELETE"):
                    statements.append(
                        f"CREATE TRIGGER keep_{table}_{action} BEFORE {action} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'Immutable production mapping'); END"
                    )
            statements.append(
                "CREATE TRIGGER keep_bridge_orders BEFORE DELETE ON bridge_orders "
                "BEGIN SELECT RAISE(ABORT,'Immutable production mapping'); END"
            )
            for statement in statements:
                db.execute(statement)
            db.execute("INSERT INTO bridge_registry VALUES(1,?)", (str(uuid4()),))
            db.execute("PRAGMA user_version=2")

    @property
    def registry_id(self):
        with self.connection() as db:
            return db.execute("SELECT id FROM bridge_registry WHERE singleton=1").fetchone()[0]

    def backup_bridge(self):
        """Preserve registry UUID and pending IDs before remote confirmation."""
        recovery = self.path.with_name(self.path.name + ".bridge-recovery.bak")
        temporary = self.path.with_name(self.path.name + f".bridge-{uuid4().hex}.tmp")
        with self.transaction(), self.connection() as source:
            target = sqlite3.connect(temporary)
            try:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise BridgeConflict("Production recovery backup failed integrity validation")
            finally:
                target.close()
            temporary.replace(recovery)
        return recovery

    @staticmethod
    def _mapping(db, scope, sid):
        row = db.execute(
            "SELECT * FROM bridge_orders WHERE scope=? AND sid=?", (scope, sid)
        ).fetchone()
        if row is None:
            return None
        return {
            **dict(row),
            "cards": {
                r["pc_id"]: r["card_id"]
                for r in db.execute(
                    "SELECT pc_id,card_id FROM bridge_cards WHERE scope=? AND sid=?", (scope, sid)
                )
            },
        }

    def mapping(self, scope, sid):
        with self.connection() as db:
            return self._mapping(db, scope, str(UUID(sid)))

    def unverified_orders(self):
        with self.connection() as db:
            return [
                r[0]
                for r in db.execute(
                    "SELECT id FROM orders WHERE id NOT IN (SELECT order_id FROM bridge_orders) ORDER BY number"
                )
            ]

    @staticmethod
    def validate(snapshot, sid):
        data = snapshot["submission"]
        if data["id"] != str(UUID(sid)) or snapshot["actor"]["role"] not in ("operator", "admin"):
            raise BridgeConflict("Invalid authoritative production response")
        if not snapshot["preparation"]["eligible"]:
            raise BridgeConflict(
                "Preparation blocked: " + ", ".join(snapshot["preparation"]["reasons"])
            )
        ids = [str(UUID(c["id"])) for c in data["cards"]]
        if any(c.get('status') == 'voided' for c in data['cards']):
            raise BridgeConflict('Voided historical identities cannot enter production')
        if not ids or len(set(ids)) != len(ids) or data["status"] != "reconciled":
            raise BridgeConflict("Invalid or unreconciled physical inventory")
        return data

    def _check(self, db, scope, snapshot, mode, adoption, distinct):
        data = self.validate(snapshot, snapshot["submission"]["id"])
        old = self._mapping(db, scope, data["id"])
        remote = snapshot["binding"]
        registry = db.execute("SELECT id FROM bridge_registry WHERE singleton=1").fetchone()[0]
        if remote and remote["registry_id"] != registry:
            raise BridgeConflict(
                "Owned by another registry. Open the original registry or restore its backup."
            )
        if old:
            if not remote:
                raise BridgeConflict(
                    "Backend reservation missing. Review server/registry restoration."
                )
            if old["mode"] != remote["mode"] or set(old["cards"]) != {
                c["id"] for c in data["cards"]
            }:
                raise BridgeConflict("Stored mapping conflicts with backend manifest")
            if remote["local_order_id"] and (
                remote["local_order_id"] != old["order_id"] or remote["cards"] != old["cards"]
            ):
                raise BridgeConflict(
                    "Backend and local identities differ. Restore the correct registry."
                )
            if (
                mode == "adopt"
                and adoption
                and (adoption["order_id"] != old["order_id"] or adoption["cards"] != old["cards"])
            ):
                raise BridgeConflict("Adoption conflicts with existing mapping")
            return old
        if remote and remote["local_order_id"]:
            raise BridgeConflict(
                "Backend already confirmed identities missing locally. Restore registry backup; do not recreate."
            )
        if remote and remote["mode"] != mode:
            raise BridgeConflict(
                "Existing reservation uses another mode; review it before continuing."
            )
        if mode == "adopt":
            if snapshot["actor"]["role"] != "admin":
                raise BridgeConflict("Adoption requires a backend administrator")
            if not adoption:
                raise BridgeConflict("Explicit ORD and every PC-to-SLB-C pair are required")
            order = self._get(db, "orders", adoption["order_id"])
            if order["status"] in ("cancelled", "shipped"):
                raise BridgeConflict("Cannot adopt a cancelled or shipped order")
            pairs = adoption["cards"]
            local = {
                r[0] for r in db.execute("SELECT id FROM cards WHERE order_id=?", (order["id"],))
            }
            if (
                set(pairs) != {c["id"] for c in data["cards"]}
                or set(pairs.values()) != local
                or len(local) != len(pairs)
            ):
                raise BridgeConflict(
                    "Adoption must pair every received PC and every card in the selected ORD exactly once"
                )
            if db.execute(
                "SELECT 1 FROM bridge_orders WHERE order_id=?", (order["id"],)
            ).fetchone():
                raise BridgeConflict("Local order is already mapped")
            for card in local:
                if self._get(db, "cards", card)["status"] == "cancelled":
                    raise BridgeConflict("Cannot adopt a cancelled card")
        elif (
            not distinct
            and db.execute(
                "SELECT 1 FROM orders WHERE id NOT IN (SELECT order_id FROM bridge_orders) LIMIT 1"
            ).fetchone()
        ):
            raise BridgeConflict(
                "Unverified local orders exist. Review them and explicitly adopt or confirm creation of a distinct order."
            )
        return None

    def preflight(self, scope, snapshot, mode="create", adoption=None, distinct=False):
        with self.transaction() as db:
            return self._check(db, scope, snapshot, mode, adoption, distinct)

    def apply(self, scope, snapshot, reason, mode="create", adoption=None, distinct=False):
        if not reason.strip():
            raise BridgeConflict("A production identity decision reason is required")
        data = snapshot["submission"]
        with self.transaction() as db:
            old = self._check(db, scope, snapshot, mode, adoption, distinct)
            if old:
                return old
            if not snapshot["binding"]:
                raise BridgeConflict("Backend reservation required before allocation")
            actor = snapshot["actor"]["id"]
            if mode == "adopt":
                order_id, pairs = adoption["order_id"], dict(adoption["cards"])
            else:
                now = utc_now()
                number = db.execute(
                    "INSERT INTO orders(customer_name,contact,external_reference,notes,created_at_utc,status,received_at_utc) "
                    "VALUES(?,?,?,'',?,'received',?)",
                    (
                        data.get("customer_name") or data["reference"],
                        "",
                        data["reference"],
                        now,
                        now,
                    ),
                ).lastrowid
                order_id = f"ORD-{number:06d}"
                db.execute("UPDATE orders SET id=? WHERE number=?", (order_id, number))
                pairs = {}
                entries = {e["id"]: e for e in data["entries"]}
                for position, card in enumerate(data["cards"], 1):
                    entry = entries[card["entry_id"]]
                    number = db.execute(
                        "INSERT INTO cards(order_id,position,metadata,status,created_at_utc,updated_at_utc) "
                        "VALUES(?,?,?,'registered',?,?)",
                        (order_id, position, encode({"description": entry["card_name"]}), now, now),
                    ).lastrowid
                    local = f"SLB-C-{number:06d}"
                    db.execute("UPDATE cards SET id=? WHERE number=?", (local, number))
                    pairs[card["id"]] = local
            db.execute(
                "INSERT INTO bridge_orders(scope,sid,sp,order_id,mode) VALUES(?,?,?,?,?)",
                (scope, data["id"], data["reference"], order_id, mode),
            )
            for card in data["cards"]:
                db.execute(
                    "INSERT INTO bridge_cards VALUES(?,?,?,?,?,?)",
                    (scope, data["id"], card["id"], card["reference"], order_id, pairs[card["id"]]),
                )
            mapped = self._mapping(db, scope, data["id"])
            self._event(db, order_id, "production_" + mode, actor, None, mapped, reason)
            for pc, local in pairs.items():
                self._event(
                    db,
                    local,
                    "production_identity_mapped",
                    actor,
                    None,
                    {
                        "scope": scope,
                        "sid": data["id"],
                        "pc_id": pc,
                        "card_id": local,
                        "order_id": order_id,
                    },
                    reason,
                )
            return mapped

    def confirm(self, scope, snapshot, reason):
        data, remote = snapshot["submission"], snapshot["binding"]
        with self.transaction() as db:
            old = self._mapping(db, scope, data["id"])
            registry = db.execute("SELECT id FROM bridge_registry WHERE singleton=1").fetchone()[0]
            if (
                not old
                or not remote
                or remote["registry_id"] != registry
                or (old["order_id"] != remote["local_order_id"] or old["cards"] != remote["cards"])
            ):
                raise BridgeConflict(
                    "Backend confirmation differs; pending identities retained for review"
                )
            if not old["confirmed"]:
                db.execute(
                    "UPDATE bridge_orders SET confirmed=1 WHERE scope=? AND sid=?",
                    (scope, data["id"]),
                )
                self._event(
                    db,
                    old["order_id"],
                    "production_confirmed",
                    snapshot["actor"]["id"],
                    old,
                    self._mapping(db, scope, data["id"]),
                    reason,
                )
        return self.mapping(scope, data["id"])


class ProductionService:
    def __init__(self, client, path):
        self.client, self.store = client, ProductionStore(path)
        self.scope = client.connection.backend_origin

    def load(self, sid):
        snapshot = self.client.production(sid)
        if snapshot["submission"]["id"] != str(UUID(sid)):
            raise BridgeConflict("Backend returned another submission")
        mapping = self.store.mapping(self.scope, sid)
        remote, registry = snapshot["binding"], self.store.registry_id
        conflict = None
        if remote and remote["registry_id"] != registry:
            conflict = (
                "Owned by another registry. Reopen its registry; do not allocate replacement IDs."
            )
        elif mapping and not remote:
            conflict = (
                "Local mapping has no backend reservation. Review server/registry restoration."
            )
        elif remote and remote["local_order_id"] and not mapping:
            conflict = "Backend-confirmed identities are missing locally. Restore the original registry backup."
        elif (
            mapping
            and remote
            and (
                mapping["mode"] != remote["mode"]
                or (
                    remote["local_order_id"]
                    and (
                        mapping["order_id"] != remote["local_order_id"]
                        or mapping["cards"] != remote["cards"]
                    )
                )
            )
        ):
            conflict = "Backend and local identities conflict. Review the recorded mapping; no links were replaced."
        state = (
            "conflict"
            if conflict
            else "confirmed"
            if mapping and mapping["confirmed"] and remote and remote["local_order_id"]
            else "pending confirmation"
            if mapping
            else "reserved"
            if remote
            else "unmapped"
        )
        return {
            "snapshot": snapshot,
            "mapping": mapping,
            "mapping_state": state,
            "conflict": conflict,
            "unverified": self.store.unverified_orders(),
            "registry_id": registry,
        }

    def prepare(self, sid, reason, mode="create", adoption=None, distinct=False):
        if not reason.strip():
            raise BridgeConflict("Enter an explicit production decision reason")
        snapshot = self.load(sid)["snapshot"]
        old = self.store.preflight(self.scope, snapshot, mode, adoption, distinct)
        if old:
            mode = old["mode"]
        remote = snapshot["binding"]
        if not remote or not remote["local_order_id"]:
            snapshot = self.client.execute(
                {
                    "kind": "production_reserve",
                    "sid": sid,
                    "payload": {
                        "registry_id": self.store.registry_id,
                        "mode": mode,
                        "reason": reason,
                    },
                }
            )
            old = self.store.apply(self.scope, snapshot, reason, mode, adoption, distinct)
            self.store.backup_bridge()
            snapshot = self.client.execute(
                {
                    "kind": "production_confirm",
                    "sid": sid,
                    "payload": {
                        "registry_id": self.store.registry_id,
                        "local_order_id": old["order_id"],
                        "cards": [
                            {"physical_card_id": pc, "local_card_id": local}
                            for pc, local in old["cards"].items()
                        ],
                        "reason": reason,
                    },
                }
            )
        self.store.confirm(self.scope, snapshot, reason)
        self.store.backup_bridge()
        return self.load(sid)
