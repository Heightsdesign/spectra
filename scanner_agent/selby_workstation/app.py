"""Qt Widgets inspection surface; original pixels remain the model coordinate system."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from spectra_reference import NAMES

from .form_widgets import FormComboBox as QComboBox
from .inspection import History, autosave, export_report, measure, recover, validate_group
from .session import Session, decision


class Canvas(QGraphicsView):
    edited = Signal(str, int, object)
    selected = Signal(str, int)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#111722"))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.active = ("physical", 0)
        self.lines = {}
        self.ghosts = []
        self.overlays = []
        self.mode = "edit"
        self.fine = False
        self.pending = []
        self.gesture = None
        self.pan = None
        self.image_size = (0, 0)
        self.endpoint_selection = None

    def image(self, rgb):
        self.scene().clear()
        self.overlays = []
        self.lines = {}
        self.ghosts = []
        self.pending = []
        self.gesture = None
        h, w = rgb.shape[:2]
        self.image_size = (w, h)
        image = QImage(rgb.data, w, h, int(rgb.strides[0]), QImage.Format.Format_RGB888).copy()
        self.scene().addPixmap(QPixmap.fromImage(image)).setZValue(-10)
        self.scene().setSceneRect(0, 0, w, h)
        self.fit()

    def fit(self):
        if self.image_size[0]:
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def zoom(self, factor):
        current = self.transform().m11()
        target = max(0.01, min(64, current * factor))
        self.scale(target / current, target / current)

    def wheelEvent(self, event):
        self.zoom(1.2 if event.angleDelta().y() > 0 else 1 / 1.2)
        event.accept()

    def original(self, point):
        mapped = self.viewportTransform().inverted()[0].map(point)
        return np.array([mapped.x(), mapped.y()])

    def screen(self, point):
        p = self.viewportTransform().map(QPointF(*point))
        return np.array([p.x(), p.y()])

    def redraw(self):
        for item in self.overlays:
            self.scene().removeItem(item)
        self.overlays = []

        def stroke(points, color, dashed=False, width=2):
            pen = QPen(QColor(color), width)
            pen.setCosmetic(True)
            if dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
            a, b = points
            self.overlays.append(self.scene().addLine(*a, *b, pen))

        for points, color in self.ghosts:
            stroke(points, color, True, 1)
        for key, record in self.lines.items():
            points, status = record
            if points is None:
                continue
            if self.gesture and key == self.gesture["key"]:
                points = self.gesture["preview"]
            stroke(
                points,
                "#55e0bd" if key[0] == "physical" else "#ffc85b",
                status != "annotated",
                3 if key == self.active else 2,
            )
            if key == self.active:
                for p in points:
                    pen = QPen(QColor("white"), 1)
                    pen.setCosmetic(True)
                    handle = self.scene().addEllipse(-5, -5, 10, 10, pen, QColor("#ef8c32"))
                    handle.setFlag(handle.GraphicsItemFlag.ItemIgnoresTransformations)
                    handle.setPos(QPointF(*p))
                    self.overlays.append(handle)
        for p in self.pending:
            pen = QPen(QColor("white"), 1)
            pen.setCosmetic(True)
            dot = self.scene().addEllipse(-4, -4, 8, 8, pen, QColor("#fff"))
            dot.setFlag(dot.GraphicsItemFlag.ItemIgnoresTransformations)
            dot.setPos(QPointF(*p))
            self.overlays.append(dot)

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton) or (
            event.button() == Qt.MouseButton.LeftButton and self.mode == "pan"
        ):
            self.pan = (
                event.position(),
                self.horizontalScrollBar().value(),
                self.verticalScrollBar().value(),
            )
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton or not self.image_size[0]:
            super().mousePressEvent(event)
            return
        point = self.original(event.position())
        if self.mode == "draw":
            if np.any(point < 0) or np.any(point >= self.image_size):
                return
            self.pending.append(point.tolist())
            if len(self.pending) == 2:
                points = self.pending
                self.pending = []
                self.edited.emit(*self.active, points)
            self.redraw()
            return
        # Select a line/endpoint in display pixels; edit in original-pixel doubles.
        click = np.array([event.position().x(), event.position().y()])
        keys = [self.active] + [key for key in self.lines if key != self.active]
        for key in keys:
            points, _ = self.lines.get(key, (None, None))
            if points is None:
                continue
            screen = np.array([self.screen(p) for p in points])
            dist = np.linalg.norm(screen - click, axis=1)
            endpoint = int(np.argmin(dist)) if min(dist) < 12 else None
            vector = screen[1] - screen[0]
            t = np.clip((click - screen[0]) @ vector / max(1e-12, vector @ vector), 0, 1)
            if endpoint is not None or np.linalg.norm(click - screen[0] - t * vector) < 8:
                self.active = key
                self.selected.emit(*key)
                self.endpoint_selection = endpoint
                self.gesture = dict(
                    key=key,
                    start=point,
                    base=np.array(points),
                    preview=deepcopy(points),
                    endpoint=endpoint,
                )
                self.redraw()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.pan:
            point, x, y = self.pan
            delta = event.position() - point
            self.horizontalScrollBar().setValue(x - round(delta.x()))
            self.verticalScrollBar().setValue(y - round(delta.y()))
            return
        if self.gesture:
            g = self.gesture
            delta = (self.original(event.position()) - g["start"]) * (
                0.1 if self.fine or event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            )
            points = g["base"].copy()
            if g["endpoint"] is None:
                points += delta
            else:
                points[g["endpoint"]] += delta
            g["preview"] = points.tolist()
            self.redraw()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.pan:
            self.pan = None
            return
        if self.gesture:
            g = self.gesture
            self.gesture = None
            if not np.array_equal(g["base"], g["preview"]):
                self.edited.emit(*g["key"], g["preview"])
            self.redraw()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.pending = []
            self.gesture = None
            self.redraw()
            return
        directions = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if event.key() in directions and self.lines.get(self.active, (None, None))[0] is not None:
            points = np.array(self.lines[self.active][0])
            delta = np.array(directions[event.key()]) * (
                0.1 if self.fine or event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            )
            if self.endpoint_selection is None:
                points += delta
            else:
                points[self.endpoint_selection] += delta
            self.edited.emit(*self.active, points.tolist())
            return
        super().keyPressEvent(event)

    def view_state(self):
        p = self.original(QPointF(self.viewport().width() / 2, self.viewport().height() / 2))
        return dict(zoom=self.transform().m11(), center=p.tolist())

    def restore(self, state):
        self.resetTransform()
        self.scale(state["zoom"], state["zoom"])
        self.centerOn(*state["center"])


class Workstation(QMainWindow):
    def __init__(self, settings_path=None):
        super().__init__()
        self.setWindowTitle("SELBY · Workstation V0.5c.1")
        self.resize(1460, 950)
        self.session = None
        self.history = None
        self.draft_directory = (
            Path(__file__).resolve().parents[1] / "local_data/selby_workstation/drafts"
        )
        self.last_draft_state = None
        from .orders import DEFAULT_PATH

        self.orders_path = DEFAULT_PATH
        self.dirty = False
        self.loading = False
        self.canvas = Canvas()
        self.canvas.edited.connect(self.apply_edit)
        self.canvas.selected.connect(self.select)
        self.operator = QLineEdit()
        self.operator.setPlaceholderText("Operator / session identity")
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(70)
        self.side_notes = QLineEdit()
        self.side_notes.setPlaceholderText("Required when marking uncertainty")
        self.family = QComboBox()
        self.family.addItems(["Physical", "Printed"])
        self.side = QComboBox()
        self.side.addItems(list(NAMES))
        self.candidate = QComboBox()
        self.hypothesis = QComboBox()
        self.predictions = QCheckBox("Show source predictions")
        self.predictions.setChecked(True)
        self.status = QLabel("Open an original scan to begin.")
        self.status.setWordWrap(True)
        self.table = QTableWidget(8, 2)
        self.table.setHorizontalHeaderLabels(["Side", "Decision"])
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setMaximumHeight(285)
        self.table.horizontalHeader().setStretchLastSection(True)
        panel = QWidget()
        panel.setMinimumWidth(360)
        layout = QVBoxLayout(panel)
        title = QLabel("SELBY  /  INSPECTION")
        title.setStyleSheet("font-size:20px;font-weight:600")
        layout.addWidget(title)
        warning = QLabel(
            "Review required · Draft grading requires human validation\nNo commercial certification or automatic acceptance."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        form = QFormLayout()
        self.face = QComboBox()
        self.face.addItems(["unspecified", "front", "back"])
        self.face.currentTextChanged.connect(self.change_face)
        form.addRow("Image face (unpaired)", self.face)
        form.addRow("Operator", self.operator)
        form.addRow("Session notes", self.notes)
        form.addRow("Geometry", self.family)
        form.addRow("Side", self.side)
        form.addRow("Source line", self.candidate)
        layout.addLayout(form)
        self.button(layout, "Use source line · unconfirmed", self.use_candidate)
        layout.addWidget(self.predictions)
        layout.addWidget(QLabel("Printed hypothesis preview"))
        layout.addWidget(self.hypothesis)
        self.button(layout, "Use hypothesis · four unconfirmed lines", self.use_hypothesis)
        layout.addWidget(self.table)
        layout.addWidget(self.side_notes)
        self.button(layout, "Confirm reviewed side", lambda: self.review(False))
        self.button(layout, "Mark side uncertain", lambda: self.review(True))
        self.button(layout, "Clear active draft line", self.clear_side)
        layout.addWidget(
            QLabel(
                "Dashed = unconfirmed / uncertain\nGreen = physical edits · gold = printed edits\nCyan / magenta = source predictions"
            )
        )
        self.button(
            layout, "Validate four physical sides", lambda: self.validate_family("physical")
        )
        self.button(layout, "Validate four printed sides", lambda: self.validate_family("printed"))
        self.measurement = QLabel()
        self.measurement.setWordWrap(True)
        self.measurement.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.measurement)
        layout.addWidget(self.status)
        layout.addStretch()
        splitter = QSplitter()
        splitter.addWidget(self.canvas)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(380)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 1)
        self.setCentralWidget(splitter)
        toolbar = self.addToolBar("Inspection")
        for label, callback in [
            ("Open scan", self.choose_image),
            ("Load report", self.choose_report),
            ("Open session", self.choose_session),
            ("Save new version", self.choose_save),
            ("Fit", self.canvas.fit),
            (
                "1:1",
                lambda: self.canvas.restore(
                    dict(zoom=1, center=self.canvas.view_state()["center"])
                ),
            ),
        ]:
            action = QAction(label, self)
            action.triggered.connect(callback)
            toolbar.addAction(action)
        for label, shortcut, callback in [
            ("Undo", "Ctrl+Z", lambda: self.undo_redo(-1)),
            ("Redo", "Ctrl+Y", lambda: self.undo_redo(1)),
            ("Recover draft", "", self.choose_recovery),
            ("Export diagnostic", "", self.choose_export),
        ]:
            action = QAction(label, self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(callback)
            toolbar.addAction(action)
        modes = QActionGroup(self)
        modes.setExclusive(True)
        for label, mode in [("Edit lines", "edit"), ("Draw two points", "draw"), ("Pan", "pan")]:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(mode == "edit")
            action.triggered.connect(lambda checked, m=mode: self.set_mode(m))
            modes.addAction(action)
            toolbar.addAction(action)
        fine = QCheckBox("Fine")
        fine.toggled.connect(lambda checked: setattr(self.canvas, "fine", checked))
        toolbar.addWidget(fine)
        self.family.currentIndexChanged.connect(self.selection_changed)
        self.side.currentIndexChanged.connect(self.selection_changed)
        self.hypothesis.currentIndexChanged.connect(self.redraw)
        self.predictions.toggled.connect(self.redraw)
        self.table.cellClicked.connect(
            lambda row, col: self.select("physical" if row < 4 else "printed", row % 4)
        )
        self.operator.textEdited.connect(self.mark_dirty)
        self.notes.textChanged.connect(self.mark_dirty)
        self.side_notes.textEdited.connect(self.edit_notes)
        condition_toolbar = self.addToolBar("Condition")
        action = QAction("Condition inspection", self)
        action.triggered.connect(self.open_condition)
        condition_toolbar.addAction(action)
        action = QAction("Grading", self)
        action.triggered.connect(self.open_grading)
        condition_toolbar.addAction(action)
        action = QAction("Orders", self)
        action.triggered.connect(self.open_orders)
        condition_toolbar.addAction(action)
        self.inspection_toolbars = [toolbar, condition_toolbar]
        from .desktop import DesktopShell

        inspection = self.takeCentralWidget()
        self.desktop = DesktopShell(self, inspection, settings_path)
        self.setCentralWidget(self.desktop)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.autosave_now)
        self.timer.start()
        self.refresh()

    @staticmethod
    def button(layout, label, callback):
        button = QPushButton(label)
        button.clicked.connect(callback)
        layout.addWidget(button)

    def mark_dirty(self, *args):
        if not self.loading and self.session:
            self.dirty = True
            self.sync_fields()
            self.show_measurement()

    def guard(self, callback):
        try:
            return callback()
        except Exception as exc:
            QMessageBox.warning(self, "SELBY action could not complete",
                                f"{exc}\n\nCheck the selected record and file paths. "
                                "Missing evidence must be restored at its recorded path; it is never silently relinked.")
            return None

    def discard_allowed(self):
        return (
            not self.dirty
            or QMessageBox.question(
                self,
                "Unsaved inspection",
                "Discard unsaved changes?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Discard
        )

    def choose_image(self):
        if not self.discard_allowed():
            return
        name, _ = QFileDialog.getOpenFileName(
            self, "Open immutable original", "", "Scans (*.bmp *.png *.tif *.tiff);;All files (*)"
        )
        if name:
            self.guard(lambda: self.open_image(Path(name)))

    def open_image(self, path):
        candidate = Session(path)
        self.session = candidate
        self.history = History(candidate)
        self.last_draft_state = None
        self.loading = True
        self.canvas.image(candidate.rgb)
        self.operator.setText("")
        self.notes.setPlainText("")
        self.loading = False
        self.dirty = False
        self.refresh()
        self.desktop.session_changed()

    def choose_report(self):
        if not self.session:
            return
        name, _ = QFileDialog.getOpenFileName(
            self, "Load existing per-image S2.1 / S2.2 report", "", "JSON (*.json)"
        )
        if name:
            self.guard(lambda: self.load_source(Path(name)))

    def load_source(self, path):
        self.session.load_report(path)
        self.dirty = True
        self.refresh()

    def choose_session(self):
        if not self.discard_allowed():
            return
        name, _ = QFileDialog.getOpenFileName(
            self, "Reopen inspection version", "", "JSON (*.json)"
        )
        if name:
            self.guard(lambda: self.open_session(Path(name)))

    def open_session(self, path):
        candidate = Session.reopen(path)
        self.session = candidate
        self.history = History(candidate)
        self.last_draft_state = None
        self.loading = True
        self.operator.setText(candidate.data["operator"])
        self.notes.setPlainText(candidate.data["notes"])
        self.loading = False
        self.canvas.image(candidate.rgb)
        self.canvas.restore(candidate.data["view"])
        self.dirty = False
        self.refresh()
        self.desktop.session_changed()

    def choose_save(self):
        if not self.session:
            return
        default = Path(__file__).resolve().parents[1] / "local_data/selby_workstation/sessions"
        default.mkdir(parents=True, exist_ok=True)
        name = QFileDialog.getExistingDirectory(
            self, "Choose inspection-artifact directory", str(default)
        )
        if name:
            self.guard(lambda: self.save_version(Path(name)))

    def save_version(self, directory):
        self.require_finished_gesture()
        self.session.data.update(
            operator=self.operator.text().strip(),
            notes=self.notes.toPlainText(),
            view=self.canvas.view_state(),
        )
        result = self.session.save(directory)
        self.dirty = False
        self.statusBar().showMessage(f"Saved new version: {result}", 20000)
        self.refresh()
        return result

    def active(self):
        return (
            "physical" if self.family.currentIndex() == 0 else "printed",
            self.side.currentIndex(),
        )

    def select(self, family, index):
        self.loading = True
        self.family.setCurrentIndex(0 if family == "physical" else 1)
        self.side.setCurrentIndex(index)
        self.loading = False
        self.canvas.endpoint_selection = None
        self.selection_changed()

    def selection_changed(self, *args):
        if self.loading:
            return
        self.canvas.pending = []
        self.canvas.gesture = None
        self.canvas.active = self.active()
        self.refresh()

    def set_mode(self, mode):
        self.canvas.mode = mode
        self.canvas.pending = []
        self.canvas.gesture = None
        self.canvas.redraw()
        self.statusBar().showMessage(
            "Draw: click two points. Edit: drag line or endpoint; arrows nudge. Shift/Fine = 0.1 px. Right-drag pans.",
            15000,
        )

    def edit_notes(self, text):
        if self.session and not self.loading:
            self.session.set_notes(*self.active(), text)
            self.dirty = True
            self.refresh()

    def apply_edit(self, family, index, points):
        def action():
            self.session.edit(family, index, points)
            self.dirty = True
            self.refresh()

        self.guard(action)

    def use_candidate(self):
        prediction = self.candidate.currentData()
        if self.session and prediction:
            self.guard(lambda: self.seed(prediction))

    def seed(self, prediction):
        self.session.seed(*self.active(), prediction)
        self.canvas.pending = []
        self.canvas.gesture = None
        self.dirty = True
        self.refresh()

    def use_hypothesis(self):
        hypothesis = self.hypothesis.currentData()
        if not self.session or not hypothesis:
            return
        if any(s["line_abc"] is not None for s in self.session.data["printed"]):
            if (
                QMessageBox.question(
                    self,
                    "Replace printed draft",
                    "Replace all four printed draft lines? Prior saved versions remain unchanged.",
                )
                != QMessageBox.StandardButton.Yes
            ):
                return

        def action():
            # Stage all four updates so invalid predictions do not partly replace edits.
            before = deepcopy(self.session.data)
            try:
                for i, prediction in enumerate(hypothesis["candidates"]):
                    self.session.seed("printed", i, prediction)
            except Exception:
                self.session.data = before
                raise
            self.canvas.pending = []
            self.canvas.gesture = None
            self.dirty = True
            self.refresh()

        self.guard(action)

    def review(self, uncertain):
        if not self.session:
            return

        def action():
            self.require_finished_gesture()
            self.session.review(*self.active(), uncertain)
            self.dirty = True
            self.refresh()

        self.guard(action)

    def require_finished_gesture(self):
        if self.canvas.pending or self.canvas.gesture:
            raise ValueError("Finish drawing the line or press Escape before saving or confirming.")

    def clear_side(self):
        if self.session:
            family, index = self.active()
            self.session.data[family][index] = decision()
            self.canvas.pending = []
            self.canvas.gesture = None
            self.dirty = True
            self.refresh()

    def refresh(self):
        if self.history:
            self.history.record()
        self.loading = True
        family, index = self.active()
        self.canvas.active = (family, index)
        for row in range(8):
            f = "physical" if row < 4 else "printed"
            i = row % 4
            self.table.setItem(row, 0, QTableWidgetItem(f"{f.title()} · {NAMES[i]}"))
            self.table.setItem(
                row,
                1,
                QTableWidgetItem(
                    self.session.data[f][i]["status"] if self.session else "unannotated"
                ),
            )
        self.table.selectRow(index + (0 if family == "physical" else 4))
        self.candidate.clear()
        self.candidate.addItem("No source line selected", None)
        old = self.hypothesis.currentText()
        self.hypothesis.clear()
        self.hypothesis.addItem("No hypothesis preview", None)
        if self.session:
            for p in self.session.predictions(family, index):
                self.candidate.addItem(p["label"], p)
            for h in self.session.hypotheses():
                self.hypothesis.addItem(h["label"], h)
            restore = self.hypothesis.findText(old)
            if restore >= 0:
                self.hypothesis.setCurrentIndex(restore)
            self.face.setCurrentText(self.session.data.get("inspection_face", "unspecified"))
            self.side_notes.setText(self.session.data[family][index]["notes"])
            self.show_measurement()
            statuses = (
                "\n".join(f"{s['kind']}: {s['status']}" for s in self.session.data["sources"])
                or "No source reports loaded."
            )
            self.status.setText(
                statuses
                + "\n"
                + ("\n".join(self.session.geometry_warnings()))
                + "\nInspection remains review_required."
            )
            self.setWindowTitle(
                f"SELBY · {Path(self.session.data['image']['path']).name} · review_required"
            )
        self.loading = False
        self.redraw()

    def redraw(self, *args):
        if self.loading or not self.session:
            return
        self.canvas.lines = {
            (f, i): (s["endpoints"], s["status"])
            for f in ("physical", "printed")
            for i, s in enumerate(self.session.data[f])
        }
        ghosts = []
        if self.predictions.isChecked() and self.session.reports:
            self.session.data["prediction_exposure"] = True
            for i in range(4):
                predictions = self.session.predictions("physical", i)
                if predictions:
                    try:
                        ghosts.append(
                            (self.session.endpoints(predictions[0]["line_abc"], i), "#3db8dd")
                        )
                    except ValueError:
                        pass
            h = self.hypothesis.currentData()
            if h:
                for i, p in enumerate(h["candidates"]):
                    ghosts.append((self.session.endpoints(p["line_abc"], i), "#e477d8"))
        self.canvas.ghosts = ghosts
        self.canvas.redraw()

    def open_condition(self):
        if not self.session:
            return

        def action():
            self.require_finished_gesture()
            self.sync_fields()
            from .condition_ui import ConditionDialog

            self.condition_dialog = ConditionDialog(self)
            self.condition_dialog.show()

        self.guard(action)

    def open_grading(self):
        if not self.session:
            self.desktop.activate("Grading")
            return

        def action():
            self.require_finished_gesture()
            self.sync_fields()
            from .grading_ui import GradingDialog

            if not hasattr(self, "grading_dialog"):
                self.grading_dialog = GradingDialog(self)
            else:
                self.grading_dialog.refresh()
            self.desktop.install("Grading", self.grading_dialog)

        self.guard(action)

    def open_orders(self):
        def action():
            from .orders_ui import OrdersDialog

            if (not hasattr(self, "orders_dialog") or
                    self.orders_dialog.store.path != self.orders_path):
                if hasattr(self, "orders_dialog"):
                    self.orders_dialog.deleteLater()
                self.orders_dialog = OrdersDialog(self, self.orders_path)
            if self.orders_dialog.isHidden():
                self.orders_dialog.search.clear()
            self.orders_dialog.refresh()
            self.desktop.install("Orders", self.orders_dialog)

        self.guard(action)

    def sync_fields(self):
        self.session.data.update(
            operator=self.operator.text().strip(),
            notes=self.notes.toPlainText(),
            view=self.canvas.view_state(),
        )

    def autosave_now(self):
        if not self.session or self.loading or self.canvas.pending or self.canvas.gesture:
            return
        self.sync_fields()
        if self.session.data == self.last_draft_state:
            return
        try:
            path = autosave(self.session, self.draft_directory)
            self.last_draft_state = deepcopy(self.session.data)
            self.statusBar().showMessage(f"Recovery snapshot: {path.name}", 3000)
        except Exception as exc:
            self.statusBar().showMessage(f"DRAFT AUTOSAVE FAILED: {exc}")

    def change_face(self, text):
        if self.session and not self.loading:
            self.session.data["inspection_face"] = text
            self.dirty = True
            self.refresh()

    def undo_redo(self, delta):
        if not self.history:
            return

        def action():
            self.require_finished_gesture()
            self.history.move(delta)
            self.dirty = True
            self.refresh()

        self.guard(action)

    def validate_family(self, family):
        if not self.session:
            return

        def action():
            self.require_finished_gesture()
            self.sync_fields()
            validate_group(self.session, family)
            self.dirty = True
            self.refresh()

        self.guard(action)

    def show_measurement(self):
        result = measure(self.session)
        text = [
            "Centering: " + result["status"],
            "Original image coordinates (x, y), pixels; unpaired " + result["inspection_face"],
            "Four-side validation: " + str(result["boundary_validation"]),
        ]
        if "margins" in result:
            text += [
                f"{name.title()}: {m['mean_pixels']:.3f} px (range {m['min_pixels']:.3f}?{m['max_pixels']:.3f})"
                for name, m in result["margins"].items()
            ]
            c = result["centering_percent"]
            text += [
                f"Horizontal L:R {c['left']:.2f}:{c['right']:.2f}",
                f"Vertical T:B {c['top']:.2f}:{c['bottom']:.2f}",
            ]
        family, index = self.active()
        side = self.session.data[family][index]
        text += [
            "Active endpoints: " + str(side["endpoints"]),
            "Line origin: " + str(side["definition"]),
            "Source basis: " + str(side["basis"]),
        ]
        text += result["limitations"]
        self.measurement.setText("\n".join(text))

    def choose_recovery(self):
        if not self.discard_allowed():
            return
        name, _ = QFileDialog.getOpenFileName(
            self,
            "Recover immutable draft (choose newest complete snapshot)",
            str(self.draft_directory),
            "JSON (*.json)",
        )
        if name:
            self.guard(lambda: self.open_recovery(Path(name)))

    def open_recovery(self, path):
        candidate = recover(path)
        self.session = candidate
        self.history = History(candidate)
        self.loading = True
        self.operator.setText(candidate.data["operator"])
        self.notes.setPlainText(candidate.data["notes"])
        self.canvas.image(candidate.rgb)
        self.canvas.restore(candidate.data["view"])
        self.loading = False
        self.dirty = True
        self.last_draft_state = None
        self.refresh()
        self.desktop.session_changed()

    def choose_export(self):
        if not self.session:
            return
        directory = QFileDialog.getExistingDirectory(self, "Export diagnostic to directory")
        if directory:

            def action():
                self.require_finished_gesture()
                self.sync_fields()
                path = export_report(self.session, Path(directory))
                self.statusBar().showMessage(f"Diagnostic exported: {path}", 20000)

            self.guard(action)

    def closeEvent(self, event):
        scanner = getattr(self.desktop, "scanner_dialog", None)
        if scanner and scanner.busy:
            event.ignore()
            return
        labels = self.desktop.pages.get('Labels')
        if labels and (labels.busy or (labels.dialog and labels.dialog.busy) or
                       (labels.calibration_dialog and labels.calibration_dialog.busy)):
            event.ignore()
            return
        self.autosave_now()
        if self.discard_allowed():
            self.desktop.pages["Incoming Submissions"].disconnect()
            event.accept()
        else:
            event.ignore()
