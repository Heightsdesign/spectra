"""Small grading workbench over the existing inspection sessions and findings."""

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import grading
from .session import Session
from .form_widgets import FormComboBox as QComboBox, FormDoubleSpinBox as QDoubleSpinBox, FormSpinBox as QSpinBox


class GradingDialog(QDialog):
    def __init__(self, workstation):
        super().__init__(workstation)
        self.workstation = workstation
        self.session = workstation.session
        self.setWindowTitle("SELBY V0.4 · human-supervised draft grading")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(1450, 950)
        root = QVBoxLayout(self)
        warning = QLabel(
            "Draft grading only · No commercial certification, release or automatic acceptance. "
            "Upstream review and blocked statuses remain unchanged."
        )
        warning.setWordWrap(True)
        root.addWidget(warning)
        self.operator = QLabel("Operator: " + self.session.data["operator"])
        root.addWidget(self.operator)
        bar = QHBoxLayout()
        self.card = QLineEdit()
        self.card.setPlaceholderText("Card / intake identity (same physical card on both faces)")
        bar.addWidget(self.card)
        for label, callback in [
            ("Create dossier", self.create),
            ("Attach current face", self.attach_current),
            ("Attach saved opposite/revised face", self.attach_saved),
            ("Inspect current image", self.inspect_current),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            bar.addWidget(button)
        root.addLayout(bar)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.summary)
        split = QSplitter()
        left = QWidget()
        layout = QVBoxLayout(left)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Face / category", "Finding / review", "Severity", "Penalty"]
        )
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(self.table.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self.select)
        layout.addWidget(self.table)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(165)
        layout.addWidget(self.detail)
        form = QFormLayout()
        self.severity = QSpinBox()
        self.severity.setRange(0, 5)
        self.warranted = QCheckBox("Operator warrants penalty")
        self.penalty = QDoubleSpinBox()
        self.penalty.setRange(0, 9)
        self.penalty.setSingleStep(0.5)
        self.penalty.setDecimals(1)
        self.damage = QLineEdit()
        self.damage.setPlaceholderText("Reuse the same ID for the same physical damage")
        self.structural = QComboBox()
        self.structural.addItem("No structural cap", None)
        form.addRow("Severity (0–5)", self.severity)
        form.addRow("Penalty decision", self.warranted)
        form.addRow("Penalty (default zero)", self.penalty)
        form.addRow("Physical damage group", self.damage)
        form.addRow("Confirmed structural damage", self.structural)
        layout.addLayout(form)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Specific explanation required for each submitted action")
        layout.addWidget(self.notes)
        button = QPushButton("Record / revise selected finding penalty and cap decision")
        button.clicked.connect(self.record_penalty)
        layout.addWidget(button)
        center = QHBoxLayout()
        self.face = QComboBox()
        self.face.addItems(grading.FACES)
        self.center_score = QDoubleSpinBox()
        self.center_score.setRange(1, 10)
        self.center_score.setValue(10)
        self.center_score.setSingleStep(0.5)
        self.center_score.setDecimals(1)
        center.addWidget(self.face)
        center.addWidget(self.center_score)
        button = QPushButton("Explicit centering review / score")
        button.clicked.connect(self.center_review)
        center.addWidget(button)
        layout.addLayout(center)
        layout.addWidget(
            QLabel("Back thresholds are undefined. Back centering always requires explicit review.")
        )
        override = QHBoxLayout()
        self.override_grade = QSpinBox()
        self.override_grade.setRange(1, 10)
        self.override_scope = QComboBox()
        self.override_scope.addItems(["grade", "structural_caps"])
        override.addWidget(self.override_grade)
        override.addWidget(self.override_scope)
        button = QPushButton("Authorized override (local allowlist)")
        button.clicked.connect(self.override)
        override.addWidget(button)
        layout.addLayout(override)
        self.attest = QCheckBox(
            "I verified front/back belong to this card and each physical damage is counted once"
        )
        layout.addWidget(self.attest)
        button = QPushButton("Human validate provisional grade")
        button.clicked.connect(self.validate)
        layout.addWidget(button)
        split.addWidget(left)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        split.addWidget(self.result)
        split.setSizes([760, 650])
        root.addWidget(split)
        footer = QHBoxLayout()
        for label, callback in [
            ("Undo", lambda: self.undo(-1)),
            ("Redo", lambda: self.undo(1)),
            ("Refresh", self.refresh),
            ("Save new version", workstation.choose_save),
            ("Export diagnostic", workstation.choose_export),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            footer.addWidget(button)
        root.addLayout(footer)
        self.refresh()

    def commit(self, callback):
        def action():
            self.workstation.sync_fields()
            callback()
            self.workstation.dirty = True
            self.workstation.refresh()
            self.workstation.autosave_now()
            self.refresh()

        return self.workstation.guard(action)

    def create(self):
        self.commit(lambda: grading.initialize(self.session, self.card.text()))

    def attach_current(self):
        self.commit(lambda: grading.attach_face(self.session, self.session, self.notes.text()))

    def attach_saved(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach inspected face session", "", "JSON (*.json)"
        )
        if path:
            self.commit(
                lambda: grading.attach_face(
                    self.session, Session.reopen(Path(path)), self.notes.text()
                )
            )

    def inspect_current(self):
        self.close()
        self.workstation.desktop.navigate("Inspection")
        self.workstation.open_condition()

    def selected_key(self):
        row = self.table.currentRow()
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 else None

    def select(self):
        key = self.selected_key()
        if key is None:
            return
        g = self.session.data["grading"]
        finding = grading.findings(g)[key]
        decision = g["working"].get("penalties", {}).get(key, {})
        self.severity.setValue(decision.get("severity", 0))
        self.warranted.setChecked(decision.get("warranted", False))
        self.penalty.setValue(decision.get("penalty", 0))
        self.damage.setText(decision.get("damage_id", key))
        self.structural.setCurrentIndex(
            max(0, self.structural.findData(decision.get("structural_type")))
        )
        self.notes.setText(decision.get("notes", ""))
        self.detail.setPlainText(json.dumps(finding, indent=2, ensure_ascii=False))

    def record_penalty(self):
        key = self.selected_key()
        if key:
            self.commit(
                lambda: grading.set_penalty(
                    self.session,
                    key,
                    self.severity.value(),
                    self.warranted.isChecked(),
                    self.penalty.value(),
                    self.notes.text(),
                    self.damage.text(),
                    self.structural.currentData(),
                )
            )

    def center_review(self):
        self.commit(
            lambda: grading.set_centering_review(
                self.session, self.face.currentText(), self.center_score.value(), self.notes.text()
            )
        )

    def override(self):
        self.commit(
            lambda: grading.record_override(
                self.session,
                self.override_grade.value(),
                self.override_scope.currentText(),
                self.notes.text(),
            )
        )

    def validate(self):
        self.commit(
            lambda: grading.human_validate(self.session, self.notes.text(), self.attest.isChecked())
        )

    def undo(self, delta):
        self.workstation.undo_redo(delta)
        self.refresh()

    def refresh(self):
        self.operator.setText("Operator: " + self.session.data["operator"])
        g = self.session.data.get("grading")
        if g:
            self.card.setText(g["working"].get("card_id", ""))
        self.structural.blockSignals(True)
        current_type = self.structural.currentData()
        self.structural.clear()
        self.structural.addItem("No structural cap", None)
        if g:
            for kind, maximum in g["policy"]["structural_caps"].items():
                self.structural.addItem(f"{kind} · draft maximum {maximum}", kind)
        self.structural.setCurrentIndex(max(0, self.structural.findData(current_type)))
        self.structural.blockSignals(False)
        selected = self.selected_key()
        self.table.blockSignals(True)
        current = grading.findings(g) if g else {}
        self.table.setRowCount(len(current))
        selected_row = -1
        for row, (key, finding) in enumerate(current.items()):
            decision = g["working"].get("penalties", {}).get(key, {})
            values = [
                finding["face"] + " / " + finding["category"],
                finding["type"] + " / " + finding["decision"],
                str(decision.get("severity", "unreviewed")),
                str(decision.get("penalty", 0)),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, key)
                self.table.setItem(row, column, item)
            if key == selected:
                selected_row = row
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        self.table.blockSignals(False)
        result = grading.evaluate(self.session)
        scores = result.get("subgrades", {})
        proposal = result.get("proposed_grade")
        caps = result.get("applicable_caps", [])
        self.summary.setText(
            f"State: {result['state']} · Policy: {result.get('policy_id', 'not selected')} "
            f"{result.get('policy_version', '')}\n"
            + " · ".join(
                f"{name.title()}: {scores.get(name) if scores.get(name) is not None else 'unresolved'}"
                for name in grading.SUBGRADES
            )
            + f"\nCalculated: {result['calculated_grade']} · Proposed: {proposal} · "
            f"Human-validated provisional grade: {result.get('final_grade')}\n"
            + "Front/back: "
            + str(result.get("completion", "not attached"))
            + "\nCaps: "
            + (", ".join(f"{c['type']} ≤{c['maximum']}" for c in caps) or "none confirmed")
            + "\n"
            + result.get("explanation", "Complete required inspections and operator decisions.")
            + "\n"
            + "\n".join(result.get("unresolved", [])[:3])
            + (
                "\nAdditional unresolved items appear in the diagnostic detail."
                if len(result.get("unresolved", [])) > 3
                else ""
            )
        )
        self.result.setPlainText(json.dumps(result, indent=2, ensure_ascii=False))
