"""Explicit production pairing, using workers for every backend request."""

import json
import sqlite3

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from .incoming import PreviewError
from .incoming_ui import Fetch, IncomingSubmissions
from .production import ProductionService


class ProductionDialog(QDialog):
    def __init__(self, auth, sid, path, parent=None, open_order=None):
        super().__init__(parent)
        self.auth, self.sid, self.path, self.open_order = auth, sid, path, open_order
        self.busy, self.value = False, None
        self.setWindowTitle("SELBY V0.5a.6 — Production identity bridge")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(1050, 800)
        root = QVBoxLayout(self)
        self.heading = QLabel("Loading authoritative production state…")
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setWordWrap(True)
        root.addWidget(self.heading)
        warning = QLabel(
            "Identity preparation does not grant payment, inspection or grading clearance. Existing grading evidence and links remain unchanged."
        )
        warning.setWordWrap(True)
        root.addWidget(warning)
        self.table = IncomingSubmissions.table(
            root, ["Backend PC", "Local SLB-C", "Mapping", "Inspection start eligibility"]
        )
        self.conflicts = QPlainTextEdit()
        self.conflicts.setReadOnly(True)
        root.addWidget(self.conflicts)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItem("Create / resume explicit production mapping", "create")
        self.mode.addItem("Administrator: adopt verified existing identities", "adopt")
        self.order = QLineEdit()
        self.order.setPlaceholderText("Exact existing ORD-000001 (adoption only)")
        self.pairs = QPlainTextEdit()
        self.pairs.setPlaceholderText(
            'Adoption JSON: {"full-PC-UUID": "SLB-C-000001", ...}\nExplicitly verify every physical copy; never pair by row position.'
        )
        self.pairs.setMaximumHeight(110)
        self.distinct = QCheckBox(
            "I reviewed unverified local orders; create a distinct order without adopting them"
        )
        self.reason = QLineEdit()
        self.reason.setMaxLength(1000)
        for label, widget in [
            ("Action", self.mode),
            ("Existing local order", self.order),
            ("Verified PC UUID → SLB-C pairs", self.pairs),
            ("Conflict decision", self.distinct),
            ("Decision reason", self.reason),
        ]:
            form.addRow(label, widget)
        root.addLayout(form)
        self.refresh_button = QPushButton("Refresh authoritative state")
        self.prepare_button = QPushButton("Prepare order for production")
        self.open_button = QPushButton("Reopen mapped order in local Orders")
        for button in (self.refresh_button, self.prepare_button, self.open_button):
            root.addWidget(button)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.refresh_button.clicked.connect(self.refresh)
        self.prepare_button.clicked.connect(self.prepare)
        self.open_button.clicked.connect(self.reopen)
        self.refresh()

    def controls(self):
        self.refresh_button.setEnabled(not self.busy)
        self.prepare_button.setEnabled(
            not self.busy
            and self.value is not None
            and not self.value.get("conflict")
            and self.value["snapshot"]["preparation"]["eligible"]
        )
        mapping = self.value["mapping"] if self.value else None
        self.open_button.setEnabled(
            not self.busy
            and mapping is not None
            and bool(mapping["confirmed"])
            and self.value.get("mapping_state") == "confirmed"
            and self.open_order is not None
        )
        for field in (self.mode, self.order, self.pairs, self.distinct, self.reason):
            field.setEnabled(not self.busy)

    def work(self, callback):
        if self.busy:
            return
        self.busy = True
        self.controls()
        self.status.setText(
            "Contacting backend; interrupted preparation retains the original identities."
        )

        def guarded():
            try:
                return callback()
            except ValueError as exc:
                raise PreviewError(str(exc)) from None
            except (sqlite3.Error, OSError):
                raise PreviewError(
                    "Local persistence failed. Check registry/backup permissions and disk space, then refresh and retry the same mapping. Pending identities are retained."
                ) from None

        self.job = Fetch(0, guarded)
        self.job.result.ready.connect(self.completed)
        QThreadPool.globalInstance().start(self.job)

    def service(self):
        return ProductionService(self.auth.intake_client(), self.path)

    def refresh(self):
        self.work(lambda: self.service().load(self.sid))

    def completed(self, generation, value, error):
        self.busy = False
        self.job = None
        if error:
            self.value = None
            self.heading.setText("Preparation not confirmed. Refresh to inspect preserved state.")
            self.table.setRowCount(0)
            self.conflicts.clear()
            self.status.setText(str(error))
        else:
            self.value = value
            snapshot, mapping = value["snapshot"], value["mapping"]
            data, remote = snapshot["submission"], snapshot["binding"]
            state = value["mapping_state"]
            self.heading.setText(
                f"SP: {data['reference']}\nORD: {mapping['order_id'] if mapping else 'not allocated'} · Mapping: {state}\nReconciliation: {data['status']} · Payment: {data.get('payment_status', 'unknown')}\nRegistry: {value['registry_id']}"
            )
            IncomingSubmissions.fill(
                self.table,
                [
                    (
                        c["reference"],
                        mapping["cards"].get(c["id"], "unmapped") if mapping else "unmapped",
                        state,
                        "eligible"
                        if snapshot["inspection"][c["id"]]["eligible"]
                        else ", ".join(
                            r["code"] for r in snapshot["inspection"][c["id"]]["reasons"]
                        ),
                    )
                    for c in data["cards"]
                ],
            )
            self.conflicts.setPlainText(
                json.dumps(
                    {
                        "preparation": snapshot["preparation"],
                        "mapping_conflict": value.get("conflict"),
                        "backend_binding": remote,
                        "unverified_local_orders_not_automatically_adopted": value["unverified"],
                        "physical_UUIDs_for_explicit_pairing": {
                            c["reference"]: c["id"] for c in data["cards"]
                        },
                    },
                    indent=2,
                )
            )
            self.status.setText(
                "Current backend state loaded. Review mappings and independent eligibility."
            )
        self.controls()

    def prepare(self):
        if not self.prepare_button.isEnabled():
            return
        reason, mode = self.reason.text().strip(), self.mode.currentData()
        if not reason:
            self.status.setText("Enter a production decision reason.")
            return
        adoption = None
        if mode == "adopt":
            try:

                def unique_pairs(items):
                    result = {}
                    for key, value in items:
                        if key in result:
                            raise ValueError("Duplicate PC UUID")
                        result[key] = value
                    return result

                pairs = json.loads(self.pairs.toPlainText(), object_pairs_hook=unique_pairs)
                if not isinstance(pairs, dict) or not all(
                    isinstance(k, str) and isinstance(v, str) for k, v in pairs.items()
                ):
                    raise ValueError()
                adoption = {"order_id": self.order.text().strip(), "cards": pairs}
            except ValueError:
                self.status.setText(
                    "Supply a JSON object with unique full PC UUID keys and exact SLB-C values."
                )
                return
        if (
            QMessageBox.question(
                self,
                "Confirm permanent production identity mapping",
                f"{self.value['snapshot']['submission']['reference']}\nMode: {mode}\n"
                f"Adoption: {json.dumps(adoption) if adoption else 'none'}\nReason: {reason}\n"
                "Persist these identities and audit records? This does not authorize grading.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        distinct = self.distinct.isChecked()
        self.work(lambda: self.service().prepare(self.sid, reason, mode, adoption, distinct))

    def reopen(self):
        if self.open_button.isEnabled():
            identity = self.value["mapping"]["order_id"]
            self.accept()
            self.open_order(identity)

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)
