"""Explicit physical custody workflow; all network work runs outside the Qt thread."""

from PySide6.QtCore import Qt, QThreadPool, Slot
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .form_widgets import FormComboBox as QComboBox
from .form_widgets import FormSpinBox as QSpinBox
from .incoming_ui import Fetch, IncomingSubmissions
from .intake_journal import IntakeJournal
from .operational_style import action_state, apply_operational_style, visual_role

VOID_EXPLANATIONS = {
    "card_not_unidentified": "Matched or questionable PC protected; select the unidentified registration.",
    "begin_reconciliation_required": "Voiding is available only during active reconciliation.",
    "grading_link_exists": "Existing grading link protects this PC.",
    "production_link_exists": "Existing production reservation or mapping protects this PC.",
    "inspection_link_exists": "Existing inspection/custody record protects this PC.",
    "discrepancy_history_exists": "Existing discrepancy history protects this PC.",
    "custody_history_exists": "Prior matching or custody history protects this PC.",
    "card_voided": "Already VOIDED; identity retained for history only.",
}


class PhysicalIntake(QDialog):
    def __init__(self, auth, sid, parent=None, journal=None):
        super().__init__(parent)
        self.setWindowTitle("SELBY — Physical intake and reconciliation")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(1100, 850)
        apply_operational_style(self)
        self.auth, self.sid = auth, sid
        self.journal = journal if journal is not None else IntakeJournal()
        self.scope = auth.connection.credential_target
        self.data, self.actor, self.busy, self.fresh = None, {}, False, False
        self.pending = self.journal.pending(self.scope, sid)
        self.job = None
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(9)
        eyebrow = QLabel("SELBY  /  PHYSICAL RECEPTION")
        visual_role(eyebrow, "eyebrow")
        root.addWidget(eyebrow)
        header = QHBoxLayout()
        self.stage = QLabel("Loading authoritative state")
        visual_role(self.stage, "stage")
        header.addWidget(self.stage, 1)
        self.refresh_button = QPushButton("Refresh backend state")
        header.addWidget(self.refresh_button)
        root.addLayout(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        split = QSplitter()
        split.addWidget(scroll)
        self.review_tabs = QTabWidget()
        split.addWidget(self.review_tabs)
        split.setSizes([470, 600])
        root.addWidget(split, 1)
        layout = QVBoxLayout(content)
        self.heading = QLabel("Loading backend intake…")
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setWordWrap(True)
        visual_role(self.heading, "heading")
        root.insertWidget(2, self.heading)
        warning = QLabel(
            "Custody only · Payment, inspection and production preparation remain independently restricted. Verify each physical copy explicitly."
        )
        warning.setWordWrap(True)
        visual_role(warning, "muted")
        root.insertWidget(3, warning)
        self.status = QLabel("Authentication required")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        visual_role(self.status, "muted")
        root.insertWidget(4, self.status)

        def review_table(title, labels):
            page = QWidget()
            table = IncomingSubmissions.table(QVBoxLayout(page), labels)
            table.setAlternatingRowColors(True)
            self.review_tabs.addTab(page, title)
            return table

        self.expected = review_table(
            "Declared cards",
            [
                "Declared entry",
                "Quantity declared",
                "Physical copies matched",
                "Quantity not yet matched",
            ],
        )
        self.inventory = review_table(
            "Physical inventory",
            [
                "Received PC reference",
                "Parcel",
                "Declared entry",
                "Lifecycle / match status",
                "Void reason",
            ],
        )
        self.issues = review_table(
            "Discrepancies",
            ["Issue ID", "Kind", "Quantity", "Status", "Observations", "Resolution"],
        )
        self.review_tabs.setCurrentIndex(1)
        self.inventory.setColumnHidden(1, True)  # Parcel is explicit in the form.
        self.inventory.horizontalHeader().moveSection(3, 1)
        form = QFormLayout()
        self.parcel = QComboBox()
        self.card = QComboBox()
        self.entry = QComboBox()
        self.issue = QComboBox()
        self.kind = QComboBox()
        self.kind.addItems(["missing", "unexpected", "mismatch", "damaged", "unresolved"])
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 10000)
        self.carrier = QLineEdit()
        self.carrier.setMaxLength(100)
        self.tracking = QLineEdit()
        self.tracking.setMaxLength(200)
        self.notes = QLineEdit()
        self.notes.setMaxLength(2000)
        self.reason = QLineEdit()
        self.reason.setMaxLength(1000)
        self.resolution = QComboBox()
        self.resolution.addItems(["resolved", "acknowledged"])
        for label, widget in [
            ("Parcel for physical card", self.parcel),
            ("Received physical card", self.card),
            ("Verified declared entry", self.entry),
            ("Discrepancy to close", self.issue),
            ("New discrepancy kind", self.kind),
            ("Missing quantity", self.quantity),
            ("Parcel carrier (optional)", self.carrier),
            ("Parcel tracking (optional)", self.tracking),
            ("Receipt / discrepancy observations", self.notes),
            ("Decision reason (required)", self.reason),
            ("Discrepancy decision", self.resolution),
        ]:
            form.addRow(label, widget)
        layout.addLayout(form)
        layout.addSpacing(120)  # Keep the last field navigable above the scroll edge.
        self.selected_card = QLabel(
            "Select a specific active PC to review its identity and lifecycle."
        )
        self.selected_card.setTextFormat(Qt.TextFormat.PlainText)
        self.selected_card.setWordWrap(True)
        visual_role(self.selected_card, "muted")
        layout.insertWidget(0, self.selected_card)
        self.void_hint = QLabel()
        self.void_hint.setTextFormat(Qt.TextFormat.PlainText)
        self.void_hint.setWordWrap(True)
        visual_role(self.void_hint, "muted")
        root.addWidget(self.void_hint)
        actions = QGridLayout()
        roles = {
            "card": "primary",
            "match": "primary",
            "complete": "success",
            "issue": "warning",
            "override": "warning",
            "void": "destructive",
        }
        self.buttons = {}
        for key, label in [
            ("parcel", "Record parcel arrival"),
            ("override", "Admin: authorize custody reconciliation"),
            ("begin", "Begin / resume reconciliation"),
            ("card", "Register ONE physical copy"),
            ("match", "Apply explicit declared-entry match"),
            ("void", "Void erroneous registration"),
            ("issue", "Record discrepancy"),
            ("resolve", "Close selected discrepancy"),
            ("hold", "Put intake on hold"),
            ("resume", "Resume held intake"),
            ("complete", "Complete reconciliation"),
        ]:
            button = QPushButton(label)
            self.buttons[key] = button
            button.setProperty("actionRole", roles.get(key, "neutral"))
            button.setAutoDefault(False)
            button.clicked.connect(lambda checked=False, k=key: self.act(k))
        for row, keys in enumerate(
            (
                ("card", "match", "complete", "void"),
                ("parcel", "begin", "issue", "resolve"),
                ("override", "hold", "resume"),
            )
        ):
            for column, key in enumerate(keys):
                actions.addWidget(self.buttons[key], row, column)
        root.addLayout(actions)
        self.recovery = QLabel()
        self.recovery.setWordWrap(True)
        self.recovery.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.recovery)
        self.retry_button = QPushButton("Retry preserved receipt / void request — same identity")
        self.review_button = QPushButton(
            "I reviewed backend inventory/audit — clear pending intent"
        )
        self.review_button.setProperty("actionRole", "warning")
        recovery_actions = QHBoxLayout()
        recovery_actions.addWidget(self.retry_button)
        recovery_actions.addWidget(self.review_button)
        root.addLayout(recovery_actions)
        self.events = review_table("Audit history", ["Audit time", "Action", "Entity", "Reason"])
        self.refresh_button.clicked.connect(self.refresh)
        self.retry_button.clicked.connect(self.retry)
        self.review_button.clicked.connect(self.review_pending)
        for selector in (self.parcel, self.card, self.entry, self.issue):
            selector.currentIndexChanged.connect(self.controls)
        self.controls()
        self.refresh()

    def controls(self, *args):
        state = self.data["status"] if self.data else None
        available = self.fresh and not self.busy and self.pending is None
        reconcile = available and state == "reconciliation_pending"
        pending_action = (
            self.pending.get("payload", {}).get("action", self.pending["kind"])
            if self.pending
            else None
        )
        local_block = (
            "Backend request in progress; wait for the authoritative response."
            if self.busy
            else f"Pending {self.pending['kind']} '{pending_action}' request blocks all custody changes. Review the backend audit before clearing its local intent; transitions must not be replayed."
            if self.pending
            else "Refresh backend state before acting."
            if not self.fresh
            else ""
        )
        selected = (
            next((c for c in self.data["cards"] if c["id"] == self.card.currentData()), None)
            if self.data
            else None
        )
        eligibility = (
            (
                "eligible"
                if selected.get("void_eligible")
                else ", ".join(selected.get("void_blockers", [])) or "unavailable"
            )
            if selected
            else ""
        )
        if selected and "void_eligible" not in selected:
            void_reason = "Backend response lacks V0.5a.6 void eligibility. Verify the connected API and refresh."
        elif not selected:
            void_reason = "Select the exact unidentified PC to review void eligibility."
        elif selected.get("void_eligible"):
            void_reason = "Backend eligible: this unidentified registration has no protected links or custody history."
        else:
            void_reason = (
                " ".join(
                    VOID_EXPLANATIONS.get(code, code) for code in selected.get("void_blockers", [])
                )
                or "Backend does not permit voiding this PC."
            )
        self.void_hint.setText(
            "Void registration · "
            + void_reason
            + ("\nLocal safety block · " + local_block if local_block else "")
        )
        visual_role(self.void_hint, "warning" if self.pending else "muted")
        stage_name = {
            "awaiting_receipt": "Awaiting parcel receipt",
            "partially_received": "Parcel received · begin reconciliation",
            "reconciliation_pending": "Reconciliation in progress",
            "reconciled": "Custody reconciliation confirmed",
            "on_hold": "Reception on hold",
        }.get(state, "Loading authoritative state")
        self.stage.setText(
            stage_name + (" · Pending intent requires review" if self.pending else "")
        )
        visual_role(
            self.stage,
            "warning" if self.pending else "success" if state == "reconciled" else "stage",
        )
        self.selected_card.setText(
            f"PC: {selected['reference']}\nLifecycle: {selected['status']} · Declared entry: {selected.get('entry_id') or 'unidentified'}\nVoid eligibility: {eligibility}"
            if selected
            else "Select a specific active PC. Voided identities remain in the historical inventory only."
        )
        for key, button in self.buttons.items():
            enabled = available
            if key == "parcel":
                enabled = available and state not in ("reconciled", "on_hold")
            elif key == "override":
                enabled = available and state != "reconciled" and self.actor.get("role") == "admin"
            elif key == "begin":
                enabled = available and state == "partially_received"
            elif key == "hold":
                enabled = available and state not in ("reconciled", "on_hold")
            elif key == "resume":
                enabled = available and state == "on_hold"
            elif key == "card":
                enabled = reconcile and self.parcel.currentData() is not None
            elif key == "match":
                enabled = reconcile and self.card.currentData() is not None
            elif key == "void":
                enabled = (
                    reconcile and selected is not None and selected.get("void_eligible", False)
                )
            elif key == "resolve":
                enabled = reconcile and self.issue.currentData() is not None
            else:
                enabled = reconcile
            reason = {
                "parcel": "Record a genuinely arrived parcel before terminal reconciliation.",
                "override": "Administrator permission is required for custody authorization.",
                "begin": "Record a parcel first; reconciliation begins from partially received state.",
                "hold": "A reconciled or already held order cannot be put on hold.",
                "resume": "Only an order on hold can be resumed.",
                "card": "Begin reconciliation and select the actual parcel first.",
                "match": "Begin reconciliation and select an active physical PC first.",
                "void": void_reason
                if not (selected and selected.get("void_eligible"))
                else "Active reconciliation is required.",
                "resolve": "Select an open discrepancy during active reconciliation.",
                "issue": "Discrepancies can be recorded during active reconciliation.",
                "complete": "Only active reconciliation can be completed; the backend validates all quantities and discrepancies.",
            }[key]
            help_text = (
                "Enter a reason, verify the full PC reference and confirm that no physical object exists."
                if key == "void"
                else "Explicit confirmation required. " + reason
            )
            action_state(button, enabled, help_text if enabled else local_block or reason)
        self.buttons["void"].setVisible(True)
        self.refresh_button.setEnabled(not self.busy)
        self.retry_button.setEnabled(
            self.pending is not None
            and self.pending["kind"] in ("parcel", "card", "void")
            and not self.busy
            and (
                self.pending["kind"] != "void"
                or self.fresh
                and self.data is not None
                and any(c["id"] == self.pending["target"] for c in self.data["cards"])
            )
        )
        self.review_button.setEnabled(
            self.pending is not None
            and self.pending["kind"] not in ("parcel", "card")
            and self.fresh
            and not self.busy
        )
        self.retry_button.setVisible(self.pending is not None)
        self.review_button.setVisible(self.pending is not None)
        self.retry_button.setToolTip(
            "Replay only the preserved creation/void target. Transitions cannot be replayed."
            if not self.retry_button.isEnabled()
            else "Confirm the exact preserved identity before retrying."
        )
        self.review_button.setProperty("actionRole", "warning")
        self.review_button.setToolTip(
            "Load fresh backend state and audit, determine the outcome, then explicitly clear only the local technical intent. No backend operation is undone."
        )
        visual_role(self.recovery, "warning" if self.pending else "muted")
        self.recovery.setText(
            "Pending "
            + self.pending["kind"]
            + " → "
            + str(pending_action)
            + " · request "
            + self.pending["id"]
            + ". Do not receive the same object again. Receipt creation and void can replay safely; other operations require a fresh inventory/audit review."
            if self.pending
            else "No pending request. Server audit is authoritative. Production preparation is a separate action."
        )

    def work(self, callback, receive):
        if self.busy:
            return
        self.busy = True
        self.fresh = False
        self.receive = receive
        self.status.setText("Contacting backend… no offline receipt is recorded.")
        self.controls()
        self.job = Fetch(0, callback)
        self.job.result.ready.connect(self.completed)
        QThreadPool.globalInstance().start(self.job)

    @Slot(int, object, object)
    def completed(self, generation, value, error):
        self.busy = False
        self.job = None
        self.pending = self.journal.pending(self.scope, self.sid)
        if error:
            visual_role(self.status, "warning")
            self.status.setText(str(error))
            if error.disconnect:
                self.data = None
                for table in (self.expected, self.inventory, self.issues, self.events):
                    IncomingSubmissions.fill(table, [])
                for combo in (self.parcel, self.card, self.entry, self.issue):
                    combo.clear()
                for field in (self.notes, self.reason, self.carrier, self.tracking):
                    field.clear()
                self.heading.setText(
                    "Session expired or permission denied. Close this window and sign in again."
                )
        else:
            visual_role(self.status, "muted")
            try:
                self.receive(value)
            except (KeyError, TypeError, ValueError):
                self.data = None
                self.status.setText(
                    "Backend returned incomplete intake detail. Refresh before acting; no local production identity was created."
                )
            else:
                self.status.setText(
                    "Backend state loaded. Actions require explicit confirmation; inspection remains separately restricted."
                )
                self.fresh = True
        self.controls()

    def refresh(self):
        self.work(lambda: self.auth.intake_client().load(self.sid), self.loaded)

    def loaded(self, result):
        self.actor, data = result
        self.render(data)

    @staticmethod
    def choices(combo, rows, empty=None):
        selected = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        if empty:
            combo.addItem(empty, None)
        for label, identifier in rows:
            combo.addItem(label, identifier)
        index = combo.findData(selected)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def render(self, data):
        self.data = data
        entries = {e["id"]: e for e in data["entries"]}
        names = {
            eid: f"{e.get('card_name', '')} / {e.get('expansion', '')} / {e.get('card_number', '')} / {e.get('language', '')} [{eid[:8]}]"
            for eid, e in entries.items()
        }
        active = [c for c in data["cards"] if c.get("status") != "voided"]
        matches = {eid: sum(c.get("entry_id") == eid for c in active) for eid in entries}
        open_count = sum(d["status"] == "open" for d in data["discrepancies"])
        unidentified = sum(c.get("entry_id") is None for c in active)
        stage = (
            "Custody reconciled (may include acknowledged exceptions). Use the separate production bridge; inspection clearance not granted."
            if data["status"] == "reconciled"
            else "Custody reconciliation is not complete."
        )
        self.heading.setText(
            f"{data['reference']} · {data['status']}\nDeclared {data['declared_quantity']} · Received {data['received_quantity']} · Matched {sum(matches.values())} · Unidentified {unidentified} · Open discrepancies {open_count}\n{stage}\nPayment: {data.get('payment_status', 'unknown')}"
        )
        IncomingSubmissions.fill(
            self.expected,
            [
                (names[eid], e["quantity"], matches[eid], e["quantity"] - matches[eid])
                for eid, e in entries.items()
            ],
        )
        parcels = {p["id"]: p["reference"] for p in data["parcels"]}
        IncomingSubmissions.fill(
            self.inventory,
            [
                (
                    c["reference"],
                    parcels.get(c["parcel_id"]),
                    names.get(c.get("entry_id"), "Unidentified"),
                    c["status"].upper() if c["status"] == "voided" else c["status"],
                    (c.get("void") or {}).get("reason", ""),
                )
                for c in data["cards"]
            ],
        )
        IncomingSubmissions.fill(
            self.issues,
            [
                (
                    d["id"],
                    d["kind"],
                    d["quantity"],
                    d["status"],
                    d.get("notes"),
                    d.get("resolution"),
                )
                for d in data["discrepancies"]
            ],
        )
        IncomingSubmissions.fill(
            self.events,
            [
                (e.get("created_at"), e["action"], e.get("entity_id"), e.get("reason"))
                for e in data.get("events", [])
            ],
        )
        self.choices(
            self.parcel, [(p["reference"] + " · " + p["status"], p["id"]) for p in data["parcels"]]
        )
        previous = self.card.currentData()
        self.choices(self.card, [(c["reference"] + " · " + c["status"], c["id"]) for c in active])
        if previous and previous not in {c["id"] for c in active}:
            self.card.setCurrentIndex(-1)  # Never silently select a different object after a void.
        self.choices(
            self.entry, [(name, eid) for eid, name in names.items()], "Unidentified / remove match"
        )
        self.choices(
            self.issue,
            [
                (d["kind"] + " · " + d["id"][:8], d["id"])
                for d in data["discrepancies"]
                if d["status"] == "open"
            ],
        )

    def act(self, kind):
        if not self.buttons[kind].isEnabled():
            return
        reason, notes = self.reason.text().strip(), self.notes.text().strip()
        target = None
        if kind == "parcel":
            payload = {
                "carrier": self.carrier.text(),
                "tracking": self.tracking.text(),
                "notes": notes,
            }
        elif kind == "card":
            payload = {"parcel_id": self.parcel.currentData(), "notes": notes}
        elif kind == "match":
            target = self.card.currentData()
            payload = {"entry_id": self.entry.currentData(), "reason": reason}
        elif kind == "void":
            target = self.card.currentData()
            payload = {"reason": reason}
        elif kind == "issue":
            missing = self.kind.currentText() == "missing"
            if (
                (missing and not self.entry.currentData())
                or (not missing and not self.card.currentData())
                or not notes
            ):
                self.status.setText(
                    "Missing requires a declared entry; other discrepancy kinds require a physical card. Observations are required."
                )
                return
            payload = {
                "kind": self.kind.currentText(),
                "entry_id": self.entry.currentData(),
                "card_id": None if missing else self.card.currentData(),
                "quantity": self.quantity.value() if missing else 1,
                "notes": notes,
            }
        elif kind == "resolve":
            target = self.issue.currentData()
            payload = {"status": self.resolution.currentText(), "reason": reason}
        else:
            payload = {"action": kind, "reason": reason}
        if kind not in ("parcel", "card", "issue") and not reason:
            self.status.setText("Enter an explicit decision reason before continuing.")
            return
        details = self.buttons[kind].text()
        if kind == "card":
            details += (
                "\nParcel: "
                + self.parcel.currentText()
                + "\nConfirm this is an additional physical copy, not one already registered. Matching is a separate explicit step."
            )
        if kind == "parcel":
            details += "\nConfirm this is a newly arrived parcel, not one already registered."
        if kind == "match":
            details += (
                "\nPhysical: " + self.card.currentText() + "\nDeclared: " + self.entry.currentText()
            )
        if kind == "resolve":
            details += "\n" + self.issue.currentText() + " → " + self.resolution.currentText()
        if kind == "void":
            details += (
                "\nPC: "
                + self.card.currentText()
                + "\nReason: "
                + reason
                + "\nConfirm this registration is a mistake and represents NO physical object. Its identity and audit will be retained permanently."
            )
        if (
            QMessageBox.question(
                self,
                "Confirm backend custody operation",
                details
                + "\nThis writes the backend audit. It does not grant payment or inspection clearance.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        operation_kind = (
            kind
            if kind in ("parcel", "card", "match", "issue", "resolve", "void")
            else "transition"
        )

        def execute():
            client = self.auth.intake_client()
            operation = self.journal.begin(self.scope, self.sid, operation_kind, payload, target)
            return self.journal.run(self.scope, operation, client)

        self.work(execute, self.render)

    def retry(self):
        if not self.retry_button.isEnabled():
            return
        details = "Retry the preserved receipt creation with its original request key? Never use this for a different physical object."
        if self.pending["kind"] == "void":
            card = next(c for c in self.data["cards"] if c["id"] == self.pending["target"])
            details = f"Retry void for PC: {card['reference']}\nReason: {self.pending['payload']['reason']}\nConfirm this registration represents no physical object. An already recorded void will not create another event."
        if (
            QMessageBox.question(
                self,
                "Replay preserved request",
                details,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.work(
            lambda: self.journal.retry(self.scope, self.sid, self.auth.intake_client()), self.render
        )

    def review_pending(self):
        if not self.review_button.isEnabled():
            return
        if (
            QMessageBox.question(
                self,
                "Confirm manual outcome review",
                "Have you checked the freshly loaded inventory and audit to determine whether this operation already occurred? Clearing the local intent does NOT undo backend receipt. Reuse any existing PC identity; do not receive the object again.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.journal.finish(self.scope, self.pending)
        self.pending = self.journal.pending(self.scope, self.sid)
        self.controls()

    def reject(self):
        # Escape calls reject() directly and bypasses closeEvent(). Keep the
        # dialog alive until its worker has delivered the authoritative result.
        if self.busy:
            self.status.setText("Wait for the backend request to finish before closing.")
            return
        super().reject()

    def closeEvent(self, event):
        if self.busy:
            self.status.setText(
                "Wait for the bounded backend request to finish before closing. An interrupted request is recoverable from its journal."
            )
            event.ignore()
        else:
            super().closeEvent(event)
