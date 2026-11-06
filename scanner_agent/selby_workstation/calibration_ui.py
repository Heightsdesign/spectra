"""Standalone hardware diagnostics. This dialog has no order, auth or API client."""

import sqlite3
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThreadPool, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtPrintSupport import QPrinterInfo
from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QPushButton, QVBoxLayout

from .calibration import DiagnosticHistory, encode_diagnostic, render_diagnostic
from .form_widgets import FormComboBox
from .incoming import PreviewError
from .incoming_ui import Fetch
from .operational_style import action_state, apply_operational_style, visual_role
from .thermal_printing import native_printer, submit


class CalibrationDialog(QDialog):
    busy_changed = Signal(bool)

    def __init__(self, settings_path, parent=None):
        super().__init__(parent)
        apply_operational_style(self)
        self.setWindowTitle("SELBY V0.5b.1 — Printer calibration")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(720, 600)
        self.busy = False
        self.settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
        self.history = DiagnosticHistory(
            Path(settings_path).with_name("printer-calibration.sqlite3")
        )
        root = QVBoxLayout(self)
        title = QLabel("Printer calibration · 50 × 30 mm")
        visual_role(title, "heading")
        root.addWidget(title)
        warning = QLabel(
            "TEST / NOT VALID — hardware diagnostic only.\nNo order, quote, payment or production mapping is required. This cannot print customer identities."
        )
        warning.setWordWrap(True)
        visual_role(warning, "warning")
        root.addWidget(warning)
        self.printer = FormComboBox()
        self.printer.addItem("Select printer explicitly", "")
        names = QPrinterInfo.availablePrinterNames()
        saved = self.settings.value("calibration/printer", "")
        for name in names:
            self.printer.addItem(name, name)
        if saved and saved not in names:
            self.printer.addItem(saved + " (missing)", saved)
        self.printer.setCurrentIndex(max(0, self.printer.findData(saved)))
        root.addWidget(self.printer)
        self.profile = QLabel(
            "50 × 30 mm · 203 DPI target · 1 test label · corner marks inside 2 mm margins"
        )
        self.profile.setWordWrap(True)
        root.addWidget(self.profile)
        self.payload = QLabel("Diagnostic QR: " + encode_diagnostic())
        root.addWidget(self.payload)
        self.preview = QLabel("Preview is available without a printer connected.")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.preview, 1)
        self.preview_button = QPushButton("Preview test label")
        self.print_button = QPushButton("Print test label…")
        self.print_button.setProperty("actionRole", "primary")
        self.review_button = QPushButton("Review uncertain diagnostic…")
        for button in (self.preview_button, self.print_button, self.review_button):
            button.setAutoDefault(False)
            root.addWidget(button)
        self.status = QLabel("Diagnostic only. Nothing is printed on opening or preview.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.status)
        self.printer.currentIndexChanged.connect(self.save_printer)
        self.preview_button.clicked.connect(self.show_preview)
        self.print_button.clicked.connect(self.print_test)
        self.review_button.clicked.connect(self.review)
        self.controls()

    def controls(self):
        self.printer.setEnabled(not self.busy)
        self.preview_button.setEnabled(not self.busy)
        explanation = (
            "Wait for the current diagnostic operation."
            if self.busy
            else "Select an exact printer; printing requires explicit confirmation."
        )
        for button in (self.print_button, self.review_button):
            action_state(button, not self.busy and bool(self.printer.currentData()), explanation)

    def set_busy(self, value):
        self.busy = value
        self.controls()
        self.busy_changed.emit(value)

    def save_printer(self):
        self.settings.setValue("calibration/printer", self.printer.currentData())
        self.settings.sync()
        self.controls()
        if self.settings.status() != QSettings.Status.NoError:
            self.status.setText(
                "Printer preference could not be saved; check desktop.ini permissions."
            )

    def work(self, callback, done, already_busy=False):
        if self.busy and not already_busy:
            return
        self.set_busy(True)

        def guarded():
            try:
                return callback()
            except (ValueError, OSError, sqlite3.Error) as exc:
                raise PreviewError(
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "Local diagnostic history could not be saved. Inspect the printer queue before retrying."
                ) from None

        def complete(generation, value, error):
            self.job = None
            self.set_busy(False)
            if error:
                self.status.setText(str(error))
            else:
                done(value)

        self.job = Fetch(0, guarded)
        self.job.result.ready.connect(complete)
        QThreadPool.globalInstance().start(self.job)

    def show_preview(self):
        self.work(
            render_diagnostic,
            lambda image: (
                self.preview.setPixmap(QPixmap.fromImage(image)),
                self.status.setText(
                    "Rendered diagnostic preview only · "
                    + encode_diagnostic()
                    + ". No print job submitted."
                ),
            ),
        )

    def print_test(self):
        if self.busy or not self.printer.currentData():
            return
        name = self.printer.currentData()
        # Guard before opening a nested confirmation event loop, not just before work.
        self.set_busy(True)
        if (
            QMessageBox.question(
                self,
                "Print one diagnostic label?",
                f"Print exactly ONE TEST / NOT VALID diagnostic on {name}?\n50 × 30 mm · 203 DPI target\nQR: {encode_diagnostic()}\nCheck loaded media and the Windows queue first. This is not a production label.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            self.set_busy(False)
            self.status.setText("Diagnostic printing cancelled; nothing submitted.")
            return
        self.status.setText(
            "Checking selected driver and 50 × 30 mm media before one diagnostic submission…"
        )

        def printing():
            printer = native_printer(name)
            image = render_diagnostic(printer.resolution())
            identifier = self.history.reserve(name)
            try:
                submit(printer, [image])
            except Exception:
                self.history.finish(
                    identifier,
                    "uncertain",
                    "Native diagnostic submission failed; physical output may be partial or absent.",
                )
                raise ValueError(
                    "Diagnostic submission failed or is uncertain. Inspect the Windows queue and physical output; no automatic retry. Use Review uncertain diagnostic before another attempt."
                ) from None
            self.history.finish(identifier, "submitted")
            return identifier

        self.work(
            printing,
            lambda identifier: self.status.setText(
                "Diagnostic submitted to "
                + name
                + ". Physical output NOT verified. Measure and decode the test label. Diagnostic job: "
                + identifier
            ),
            already_busy=True,
        )

    def review(self):
        if self.busy or not self.printer.currentData():
            return
        name = self.printer.currentData()
        self.set_busy(True)
        if (
            QMessageBox.question(
                self,
                "Review diagnostic queue",
                "Have you inspected the Windows queue and physical output for "
                + name
                + " and confirmed no earlier diagnostic is still pending?\nThis acknowledges only the local diagnostic retry blocker. It does not print or change production history.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            self.set_busy(False)
            return
        self.work(
            lambda: self.history.review(name),
            lambda count: self.status.setText(
                f"Review recorded for {count} uncertain diagnostic attempt(s). Nothing printed; another test requires a new confirmation."
            ),
            already_busy=True,
        )

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)
