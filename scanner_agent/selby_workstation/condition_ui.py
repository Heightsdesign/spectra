"""Condition workbench using the workstation's original Qt pixel viewer."""

import json

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .app import Canvas
from .form_widgets import FormComboBox as QComboBox
from .condition import (
    CATEGORIES,
    LIMITATION,
    TYPES,
    category_status,
    complete_category,
    current_findings,
    decide,
    manual_finding,
    map_points,
    regions,
    run_diagnostic,
)


class ConditionCanvas(Canvas):
    box_drawn = Signal(object)
    navigated = Signal(object)

    def __init__(self):
        super().__init__()
        self.mode = "pan"
        self.marking = False
        self.box_start = None
        self.findings = []
        self.show_findings = True
        self.matrix = np.eye(3)
        self.selected_id = None

    def redraw(self):
        super().redraw()
        if not self.show_findings:
            return
        inverse = np.linalg.inv(self.matrix)
        for finding in self.findings:
            if finding["decision"] == "rejected":
                continue
            points = map_points(inverse, finding["polygon_original"])
            color = "#66e4a4" if finding["decision"] == "confirmed" else "#ffbf47"
            pen = QPen(QColor(color), 3 if finding["id"] == self.selected_id else 1)
            pen.setCosmetic(True)
            if finding["decision"] != "confirmed":
                pen.setStyle(Qt.PenStyle.DashLine)
            for a, b in zip(points, np.roll(points, -1, axis=0), strict=True):
                self.overlays.append(self.scene().addLine(*a, *b, pen))

    def wheelEvent(self, event):
        super().wheelEvent(event)
        self.navigated.emit(self)

    def mousePressEvent(self, event):
        if self.marking and event.button() == Qt.MouseButton.LeftButton:
            self.box_start = self.original(event.position())
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self.pan:
            self.navigated.emit(self)

    def mouseReleaseEvent(self, event):
        if (
            self.marking
            and event.button() == Qt.MouseButton.LeftButton
            and self.box_start is not None
        ):
            end = self.original(event.position())
            start = self.box_start
            self.box_start = None
            low = np.minimum(start, end)
            high = np.maximum(start, end)
            if (high - low).min() < 1:
                return
            polygon = map_points(
                self.matrix, [[*low], [high[0], low[1]], [*high], [low[0], high[1]]]
            )
            self.box_drawn.emit(polygon.tolist())
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.box_start = None
            return
        # Preserve Qt navigation; condition regions never edit boundary lines.
        if event.key() not in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            super().keyPressEvent(event)


class ConditionDialog(QDialog):
    def __init__(self, workstation):
        super().__init__(workstation)
        self.workstation = workstation
        self.session = workstation.session
        self.setWindowTitle("SELBY V0.3 · assisted condition inspection · no scores")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(1500, 970)
        self.geometry_key = None
        self.views = {c: [] for c in CATEGORIES}
        self.grids = {}
        root = QVBoxLayout(self)
        header = QLabel(
            LIMITATION
            + "\nImage: "
            + self.session.data["image"]["path"]
            + "\nSHA-256: "
            + self.session.identity["sha256"]
            + " · face: "
            + self.session.data.get("inspection_face", "unspecified")
            + " (unpaired)"
        )
        header.setWordWrap(True)
        root.addWidget(header)
        toolbar = QHBoxLayout()
        for title, callback in [
            ("Run category diagnostic", self.run),
            ("Undo", lambda: self.undo(-1)),
            ("Redo", lambda: self.undo(1)),
            ("Fit views", self.fit),
            ("1:1 pixels", self.one_to_one),
            ("Save new version", workstation.choose_save),
            ("Export diagnostic", workstation.choose_export),
        ]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        self.overlay = QCheckBox("Suggestion overlay")
        self.overlay.setChecked(True)
        self.overlay.toggled.connect(self.refresh)
        toolbar.addWidget(self.overlay)
        self.sync = QCheckBox("Sync zoom / pan")
        self.sync.setChecked(True)
        toolbar.addWidget(self.sync)
        self.draw = QCheckBox("Draw manual defect (drag box)")
        self.draw.toggled.connect(self.set_marking)
        toolbar.addWidget(self.draw)
        root.addLayout(toolbar)
        self.tabs = QTabWidget()
        for category in CATEGORIES:
            page = QWidget()
            grid = QGridLayout(page)
            self.grids[category] = grid
            self.tabs.addTab(page, category.title())
        surface = ConditionCanvas()
        surface.image(self.session.rgb)
        self.views["surface"] = [surface]
        self.grids["surface"].addWidget(surface)
        surface.box_drawn.connect(self.add_manual)
        panel = QWidget()
        controls = QVBoxLayout(panel)
        self.status = QLabel()
        self.status.setWordWrap(True)
        controls.addWidget(self.status)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Region / type", "Decision", "Origin"])
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(self.table.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self.selection)
        controls.addWidget(self.table)
        self.kind = QComboBox()
        self.kind.addItems(TYPES)
        controls.addWidget(self.kind)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Evidence / reason (required for each decision)")
        controls.addWidget(self.notes)
        for label, decision in [
            ("Confirm defect", "confirmed"),
            ("Reject suggestion", "rejected"),
            ("Reclassify (does not confirm)", "reclassified"),
        ]:
            b = QPushButton(label)
            b.clicked.connect(lambda checked=False, d=decision: self.review(d))
            controls.addWidget(b)
        b = QPushButton("Complete category review")
        b.clicked.connect(self.complete)
        controls.addWidget(b)
        navigation = QHBoxLayout()
        for label, callback in [
            ("Locate selected", self.locate),
            ("Next pending", self.next_pending),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            navigation.addWidget(button)
        controls.addLayout(navigation)
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        self.evidence.setMaximumHeight(200)
        controls.addWidget(self.evidence)
        split = QSplitter()
        split.addWidget(self.tabs)
        split.addWidget(panel)
        split.setStretchFactor(0, 1)
        panel.setMinimumWidth(390)
        root.addWidget(split)
        self.tabs.currentChanged.connect(self.refresh)
        self.refresh()

    def category(self):
        return CATEGORIES[self.tabs.currentIndex()]

    def commit(self, callback):
        def action():
            self.workstation.sync_fields()
            result = callback()
            self.workstation.dirty = True
            self.workstation.refresh()
            self.refresh()
            self.workstation.autosave_now()
            return result

        return self.workstation.guard(action)

    def run(self):
        self.commit(lambda: run_diagnostic(self.session, self.category()))

    def undo(self, delta):
        self.workstation.undo_redo(delta)
        self.refresh()

    def selected(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return next(
            (
                f
                for f in self.session.data.get("condition", {}).get("findings", [])
                if f["id"] == item.data(Qt.ItemDataRole.UserRole)
            ),
            None,
        )

    def selection(self):
        finding = self.selected()
        if finding:
            self.kind.setCurrentText(finding["type"])
            self.evidence.setPlainText(
                "Original polygon (x,y) pixels: "
                + str(finding["polygon_original"])
                + "\nEvidence: "
                + json.dumps(finding["evidence"], ensure_ascii=False)
                + "\nDecision: "
                + finding["decision"]
                + " · operator: "
                + str(finding["operator"])
                + "\nNotes: "
                + finding["notes"]
            )
        else:
            self.evidence.setPlainText(
                "Select a suggestion to inspect its original coordinates and evidence."
            )
        for view in self.views[self.category()]:
            view.selected_id = finding["id"] if finding else None
            view.redraw()

    def review(self, decision):
        finding = self.selected()
        if finding:
            self.commit(
                lambda: decide(
                    self.session,
                    finding["id"],
                    decision,
                    self.kind.currentText(),
                    self.notes.text(),
                )
            )

    def next_pending(self):
        for offset in range(1, self.table.rowCount() + 1):
            row = (self.table.currentRow() + offset) % self.table.rowCount()
            if self.table.item(row, 1).text() == "unreviewed":
                self.table.selectRow(row)
                self.locate()
                return

    def locate(self):
        finding = self.selected()
        if not finding:
            return
        for view in self.views[self.category()]:
            points = map_points(np.linalg.inv(view.matrix), finding["polygon_original"])
            center = points.mean(axis=0)
            if (center >= 0).all() and (center < view.image_size).all():
                span = np.maximum(np.ptp(points, axis=0), 4)
                zoom = min(
                    32.0,
                    max(
                        1.0,
                        min(view.viewport().width() / span[0], view.viewport().height() / span[1])
                        * 0.4,
                    ),
                )
                view.restore(dict(zoom=zoom, center=center.tolist()))

    def add_manual(self, polygon):
        # Reject out-of-image gestures rather than silently relocating observations.
        self.commit(
            lambda: manual_finding(
                self.session, self.category(), polygon, self.kind.currentText(), self.notes.text()
            )
        )

    def complete(self):
        self.commit(lambda: complete_category(self.session, self.category(), self.notes.text()))

    def set_marking(self, checked):
        for views in self.views.values():
            for view in views:
                view.marking = checked
                view.box_start = None

    def synchronize(self, source):
        if not self.sync.isChecked():
            return
        state = source.view_state()
        normalized = np.asarray(state["center"]) / source.image_size
        for view in self.views[self.category()]:
            if view is not source:
                view.restore(
                    dict(zoom=state["zoom"], center=(normalized * view.image_size).tolist())
                )

    def fit(self):
        for view in self.views[self.category()]:
            view.fit()

    def one_to_one(self):
        for view in self.views[self.category()]:
            view.restore(dict(zoom=1, center=view.view_state()["center"]))

    def refresh(self, *args):
        key = json.dumps(
            [
                self.session.data["physical"],
                self.session.data.get("boundary_validation"),
                self.session.data["operator"],
            ],
            sort_keys=True,
        )
        blocked = None
        if key != self.geometry_key:
            self.geometry_key = key
            for category in ("corners", "edges"):
                grid = self.grids[category]
                while grid.count():
                    widget = grid.takeAt(0).widget()
                    if widget:
                        widget.deleteLater()
                self.views[category] = []
                try:
                    for i, region in enumerate(regions(self.session, category)):
                        box = QWidget()
                        layout = QVBoxLayout(box)
                        layout.addWidget(
                            QLabel(
                                region["metadata"]["name"]
                                + " · 1 patch px = 1 original px along axes"
                            )
                        )
                        view = ConditionCanvas()
                        view.image(region["rgb"])
                        view.matrix = np.asarray(region["metadata"]["patch_to_original"])
                        view.box_drawn.connect(self.add_manual)
                        view.navigated.connect(self.synchronize)
                        layout.addWidget(view)
                        grid.addWidget(box, i // 2, i % 2)
                        self.views[category].append(view)
                except ValueError as exc:
                    blocked = str(exc)
                    grid.addWidget(QLabel(blocked))
        category = self.category()
        statuses = "\n".join(c + ": " + category_status(self.session, c) for c in CATEGORIES)
        self.status.setText(
            statuses
            + "\n"
            + (blocked or "All upstream review / blocked statuses remain unchanged.")
        )
        selected = self.selected()
        selected_id = selected["id"] if selected else None
        findings = current_findings(self.session, category)
        self.table.blockSignals(True)
        self.table.setRowCount(len(findings))
        selected_row = -1
        for i, f in enumerate(findings):
            for j, value in enumerate(
                [f["region"] + " / " + f["type"], f["decision"], f["origin"]]
            ):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, f["id"])
                self.table.setItem(i, j, item)
            if f["id"] == selected_id:
                selected_row = i
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        self.table.blockSignals(False)
        for c, views in self.views.items():
            for view in views:
                view.findings = current_findings(self.session, c)
                view.show_findings = self.overlay.isChecked()
                view.marking = self.draw.isChecked()
                view.redraw()
        self.selection()
