"""Thermal label dialog: explicit selections, durable claims, bounded background I/O."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QSettings, Qt, QThreadPool, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtPrintSupport import QPrinterInfo
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from .form_widgets import FormComboBox
from .incoming import PreviewError
from .incoming_ui import Fetch
from .operational_style import apply_operational_style, visual_role
from .thermal_printing import native_printer, render_label, submit


class LabelProgress(QObject):
    message = Signal(str)


class LabelDialog(QDialog):
    busy_changed = Signal(bool)

    def __init__(self, auth, sid, parent=None, settings_path=None, mapping_context=None):
        super().__init__(parent)
        apply_operational_style(self)
        from .desktop import SETTINGS_PATH

        self.auth, self.sid = auth, sid
        self.mapping_context = mapping_context
        self.settings_path = Path(settings_path or SETTINGS_PATH)
        self.settings = QSettings(str(self.settings_path), QSettings.Format.IniFormat)
        self.journal = self.settings_path.with_name("label-print-journal.jsonl")
        self.state, self.busy = None, False
        self.operator = None
        self.progress = LabelProgress(self)
        self.setWindowTitle("SELBY V0.5b — Identification labels")
        self.resize(850, 830)
        root = QVBoxLayout(self)
        self.heading = QLabel("50 × 30 mm · order bag / physical-card sleeves")
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.heading)
        warning = QLabel(
            "Attach labels to sleeves or protective packaging, never directly to cards.\n"
            "Submitted means spooler acceptance only. Inspect the queue before any uncertain reprint."
        )
        warning.setWordWrap(True)
        root.addWidget(warning)
        self.printer = FormComboBox()
        self.printer.addItem("Select printer explicitly", "")
        saved = self.settings.value("labels/printer", "")
        names = QPrinterInfo.availablePrinterNames()
        for name in names:
            self.printer.addItem(name, name)
        if saved and saved not in names:
            self.printer.addItem(saved + " (missing)", saved)
        self.printer.setCurrentIndex(max(0, self.printer.findData(saved)))
        self.printer.currentIndexChanged.connect(self.save_printer)
        root.addWidget(self.printer)
        self.labels = QListWidget()
        self.labels.setMinimumHeight(100)
        self.labels.setMaximumHeight(140)
        self.labels.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.labels.setStyleSheet(
            "QListWidget { background: #171E28; border: 1px solid #344052; } QListWidget::item:selected { background: #285587; }"
        )
        root.addWidget(self.labels)
        self.preview = QLabel("Select one label to preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.preview)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Mandatory reason for every reprint")
        self.reason.setMaxLength(1000)
        root.addWidget(self.reason)
        self.buttons = []
        for title, action in [
            ("Refresh current backend state", self.refresh),
            ("Preview selected label", self.show_preview),
            ("Print selected labels…", self.print_selected),
            ("Print all eligible card labels…", self.print_all),
            ("Mark selected submitted job physically verified…", self.verify),
        ]:
            button = QPushButton(title)
            button.clicked.connect(action)
            root.addWidget(button)
            self.buttons.append(button)
        self.buttons[2].setProperty("actionRole", "primary")
        preview_actions = QHBoxLayout()
        for button in self.buttons[1:4]:
            root.removeWidget(button)
            preview_actions.addWidget(button)
        root.insertLayout(root.indexOf(self.preview), preview_actions)
        self.jobs = FormComboBox()
        root.addWidget(self.jobs)
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setMaximumHeight(170)
        root.addWidget(self.history)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.eligibility = QLabel("Checking current backend eligibility…")
        self.eligibility.setWordWrap(True)
        self.eligibility.setTextFormat(Qt.TextFormat.PlainText)
        root.insertWidget(1, self.eligibility)
        self.progress.message.connect(self.status.setText)
        visual_role(self.heading, "heading")
        visual_role(warning, "warning")
        self.labels.itemSelectionChanged.connect(self.update_controls)
        self.printer.currentIndexChanged.connect(self.update_controls)
        self.refresh()

    def update_controls(self):
        if self.busy:
            return
        available = bool(self.state and self.state["labels"])
        eligible = bool(self.state and self.state["print_eligible"])
        explanation = (
            "Select an exact printer."
            if eligible and not self.printer.currentData()
            else self.eligibility.text()
        )
        for button in self.buttons[2:4]:
            button.setEnabled(eligible and bool(self.printer.currentData()))
            button.setToolTip(explanation)
            button.setAccessibleDescription(explanation)
        self.buttons[1].setEnabled(available)
        self.buttons[1].setToolTip(
            "Select exactly one order or card label. Previewing does not submit a print job."
        )
        self.buttons[4].setEnabled(self.jobs.count() > 0)
        self.buttons[4].setToolTip(
            "A submitted job is required. Confirm only after physically inspecting and decoding its labels."
        )

    def load_labels(self):
        client = self.auth.intake_client()
        if self.mapping_context:
            from .label_mapping import checked_labels

            return checked_labels(self.mapping_context, client)
        return client.labels(self.sid)

    def save_printer(self):
        self.settings.setValue("labels/printer", self.printer.currentData())
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            self.status.setText("Printer preference could not be saved.")

    def persist(self, payload, result):
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        with self.journal.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    dict(
                        sid=self.sid,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        operator=self.operator,
                        origin=self.auth.intake_client().connection.backend_origin,
                        event=payload,
                        result=result,
                    )
                )
                + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())

    def record_event(self, payload):
        self.persist(payload, "intent")
        result = self.auth.intake_client().execute(
            dict(kind="label_event", sid=self.sid, payload=payload)
        )
        self.persist(payload, result)
        return result

    def work(self, callback, done=None):
        if self.busy:
            return
        self.busy = True
        self.busy_changed.emit(True)
        for widget in self.buttons + [self.labels, self.printer, self.reason, self.jobs]:
            widget.setEnabled(False)
        self.status.setText("Processing label request… Do not retry an uncertain job.")

        def complete(generation, value, error):
            self.busy = False
            self.job = None
            for widget in self.buttons + [self.labels, self.printer, self.reason, self.jobs]:
                widget.setEnabled(True)
            if error:
                self.state = None
                self.labels.clear()
                self.history.clear()
                self.jobs.clear()
                self.preview.clear()
                self.eligibility.setText(
                    "Eligibility unavailable. Refresh or sign in through Incoming orders; printing is disabled."
                )
                for button in self.buttons[1:]:
                    button.setEnabled(False)
                self.status.setText(
                    str(error)
                    + "\nRefresh and inspect history/Windows queue before reprinting. Local journal: "
                    + str(self.journal)
                )
            elif done:
                done(value)
            self.update_controls()
            self.busy_changed.emit(False)

        self.job = Fetch(0, callback)
        self.job.result.ready.connect(complete)
        QThreadPool.globalInstance().start(self.job)

    def refresh(self):
        self.work(self.load_labels, self.loaded)

    def loaded(self, state):
        self.state = state
        self.operator = state["actor"]
        self.buttons[2].setEnabled(state["print_eligible"])
        self.buttons[3].setEnabled(state["print_eligible"])
        self.labels.clear()
        self.jobs.clear()
        self.heading.setText(
            f"{(self.mapping_context['order_id'] + ' · ') if self.mapping_context else ''}{state['reference']} · 50 × 30 mm · {len(state['labels'])} available labels"
        )
        self.eligibility.setText(
            "Printing eligible — backend checks currently pass; explicit confirmation is still required."
            if state["print_eligible"]
            else "Printing blocked: "
            + ", ".join(state["blockers"])
            + (
                " — Independent payment verification is required. Previews remain available."
                if "payment_unverified" in state["blockers"]
                else " — Review the backend reconciliation, inspection and commercial checks."
            )
        )
        visual_role(self.eligibility, "success" if state["print_eligible"] else "warning")
        local = (
            {card["pc"]: card["card_id"] for card in self.mapping_context["cards"]}
            if self.mapping_context
            else {}
        )
        for label in state["labels"]:
            item = QListWidgetItem(
                label["kind"]
                + " · "
                + (local[label["reference"]] + " → " if label["reference"] in local else "")
                + label["reference"]
            )
            item.setData(Qt.ItemDataRole.UserRole, label)
            self.labels.addItem(item)
        self.history.setPlainText(
            "\n".join(
                f"{e['timestamp']} {e['actor']} {e['action']} {e['data']['printer']} {', '.join(e['data']['references'])} {e['reason'] or ''} {e['data'].get('error', '')}"
                for e in state["history"]
            )
        )
        verified = {e["id"] for e in state["history"] if e["action"] == "label_verified"}
        for e in state["history"]:
            if e["action"] == "label_submitted" and e["id"] not in verified:
                self.jobs.addItem(e["id"] + " · " + ", ".join(e["data"]["references"]), e)
        self.status.setText(
            "Ready for explicit printing."
            if state["print_eligible"]
            else "Printing blocked: " + ", ".join(state["blockers"])
        )
        self.preview.clear()
        self.update_controls()

    def selected(self):
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.labels.selectedItems()]

    def show_preview(self):
        labels = self.selected()
        if len(labels) != 1:
            self.status.setText("Select exactly one label for preview.")
            return
        label = labels[0]

        def render():
            state = self.load_labels()
            if label not in state["labels"]:
                raise PreviewError(
                    "Label content changed. Refresh and preview the current identity."
                )
            return render_label(label), state

        def rendered(value):
            image, state = value
            self.loaded(state)
            for index in range(self.labels.count()):
                if (
                    self.labels.item(index).data(Qt.ItemDataRole.UserRole)["reference"]
                    == label["reference"]
                ):
                    self.labels.item(index).setSelected(True)
            self.preview.setPixmap(QPixmap.fromImage(image))
            self.status.setText("Rendered preview only · 50 × 30 mm · QR: " + label["payload"])

        self.work(
            render,
            rendered,
        )

    def payload(self, labels):
        return dict(
            job_id=str(uuid4()),
            references=[label["reference"] for label in labels],
            fingerprint=hashlib.sha256(
                json.dumps(labels, sort_keys=True, ensure_ascii=True).encode()
            ).hexdigest(),
            printer=self.printer.currentData() or "(preview only)",
            reason=self.reason.text().strip(),
            width_mm=50,
            height_mm=30,
        )

    def print_all(self):
        if self.state:
            self.print_labels(
                [label for label in self.state["labels"] if label["kind"] == "physical_card"]
            )

    def print_selected(self):
        self.print_labels(self.selected())

    def print_labels(self, labels):
        if self.busy or not self.state or not labels:
            return
        if not self.printer.currentData():
            self.status.setText("Select a printer explicitly.")
            return
        if not self.state["print_eligible"]:
            self.status.setText(
                "Backend eligibility blocks printing: " + ", ".join(self.state["blockers"])
            )
            return
        payload = self.payload(labels)
        claimed = [
            e
            for e in self.state["history"]
            if e["action"] == "label_claimed"
            and set(e["data"]["references"]) & set(payload["references"])
        ]
        if claimed and not payload["reason"]:
            self.status.setText("A reprint reason is mandatory, including uncertain earlier jobs.")
            return
        if (
            QMessageBox.question(
                self,
                "Confirm label printing",
                f"Print {len(labels)} label(s) on {payload['printer']} at 50 × 30 mm?\n"
                + "\n".join(payload["references"])
                + "\nReprint reason: "
                + (payload["reason"] or "(first print)"),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        def printing():
            # Validate driver and render before obtaining the single-use backend claim.
            self.progress.message.emit(f"Rendering {len(labels)} label(s) at 50 × 30 mm…")
            try:
                images = [render_label(label) for label in labels]
            except Exception:
                self.record_event(
                    dict(payload, phase="failed", error="Rendering failed before submission")
                )
                raise PreviewError("Rendering failed; nothing submitted.") from None
            self.record_event(dict(payload, phase="rendered"))
            self.progress.message.emit("Checking selected printer and exact media dimensions…")
            try:
                printer = native_printer(payload["printer"])
                if printer.resolution() != 203:
                    images = [render_label(label, dpi=printer.resolution()) for label in labels]
            except Exception:
                self.record_event(
                    dict(
                        payload,
                        phase="failed",
                        error="Printer configuration failed before submission",
                    )
                )
                raise PreviewError("Printer configuration failed; nothing submitted.") from None
            self.progress.message.emit(
                "Checking current backend eligibility and claiming this job once…"
            )
            claim = self.record_event(dict(payload, phase="claimed"))
            if not claim.get("accepted"):
                raise PreviewError("Job already claimed. No repeat submission permitted.")
            try:
                self.progress.message.emit(
                    f"Submitting {len(labels)} label(s) to {payload['printer']}… Physical output unverified."
                )
                submit(printer, images)
            except Exception:
                self.persist(dict(payload, phase="failed"), "Printer outcome uncertain")
                self.record_event(
                    dict(
                        payload,
                        phase="failed",
                        error="Native submission failed; output may be partial. Inspect queue.",
                    )
                )
                raise PreviewError(
                    "Native submission failed; inspect queue and physical output before reprint."
                ) from None
            self.persist(
                dict(payload, phase="submitted"),
                "Native submission returned; physical output unverified",
            )
            self.record_event(dict(payload, phase="submitted"))
            return self.load_labels()

        self.work(
            printing,
            lambda state: (
                self.loaded(state),
                self.status.setText(
                    "Submitted to printer · physical output NOT verified. Check and decode each label."
                ),
            ),
        )

    def verify(self):
        event = self.jobs.currentData()
        if not event or self.busy:
            return
        if (
            QMessageBox.question(
                self,
                "Physical verification",
                "Have you physically inspected and decoded every label in this exact job?\n"
                + ", ".join(event["data"]["references"]),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        payload = {
            k: event["data"][k]
            for k in ("references", "printer", "width_mm", "height_mm", "fingerprint")
        }
        payload.update(job_id=event["id"], phase="verified", reason=event["reason"] or "")
        self.work(
            lambda: (self.record_event(payload), self.load_labels())[1],
            self.loaded,
        )

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)
