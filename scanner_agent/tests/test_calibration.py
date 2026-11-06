"""Calibration regression: native Windows UI, mock devices and PDF output only."""

import importlib.util
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QMarginsF, QSize, QSizeF
from PySide6.QtGui import QImage, QPageLayout, QPageSize
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
from PySide6.QtWidgets import QApplication, QMessageBox
from test_thermal_labels import wait

from selby_workstation.calibration import (
    DIAGNOSTIC_PAYLOAD,
    DIAGNOSTIC_REFERENCE,
    DiagnosticHistory,
    decode_diagnostic,
    encode_diagnostic,
    render_diagnostic,
)
from selby_workstation.calibration_ui import CalibrationDialog
from selby_workstation.thermal_printing import submit


def decode_image(image):
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    pixels = (
        np.frombuffer(image.bits(), dtype=np.uint8)
        .reshape(image.height(), image.bytesPerLine())[:, : image.width() * 3]
        .reshape(image.height(), image.width(), 3)
    )
    return cv2.QRCodeDetector().detectAndDecode(pixels)[0], pixels.copy()


def test_codec_and_production_rejection():
    assert decode_diagnostic(encode_diagnostic()) == DIAGNOSTIC_REFERENCE
    assert encode_diagnostic(decode_diagnostic(DIAGNOSTIC_PAYLOAD)) == DIAGNOSTIC_PAYLOAD
    for value in [DIAGNOSTIC_PAYLOAD.lower(), DIAGNOSTIC_PAYLOAD + "X", "SP:PC:1:PC-" + "1" * 32]:
        with pytest.raises(ValueError):
            decode_diagnostic(value)
    with pytest.raises(ValueError):
        encode_diagnostic("PC-" + "1" * 32)
    path = Path(__file__).resolve().parents[2] / "backend/app/physical_identity.py"
    spec = importlib.util.spec_from_file_location("production_identity_calibration_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for decoder in (module.decode_label, module.parse_scan, module.normalize_reference):
        with pytest.raises(ValueError):
            decoder(DIAGNOSTIC_PAYLOAD)


@pytest.mark.parametrize("dpi", [203, 300])
def test_preview_and_quiet_boundaries(dpi):
    image = render_diagnostic(dpi)
    assert image.width() == round(50 * dpi / 25.4) and image.height() == round(30 * dpi / 25.4)
    decoded, pixels = decode_image(image)
    assert decoded == DIAGNOSTIC_PAYLOAD
    inset = int(2 * dpi / 25.4)
    assert (pixels[:inset] == 255).all() and (pixels[-inset:] == 255).all()
    assert (pixels[:, :inset] == 255).all() and (pixels[:, -inset:] == 255).all()


def test_pdf_page_dimensions_and_decode(tmp_path):
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    path = tmp_path / "diagnostic.pdf"
    printer.setOutputFileName(str(path))
    printer.setResolution(203)
    assert printer.setPageLayout(
        QPageLayout(
            QPageSize(QSizeF(50, 30), QPageSize.Unit.Millimeter),
            QPageLayout.Orientation.Portrait,
            QMarginsF(),
            QPageLayout.Unit.Millimeter,
        )
    )
    printer.setFullPage(True)
    submit(printer, [render_diagnostic()])
    from PySide6.QtPdf import QPdfDocument

    document = QPdfDocument()
    document.load(str(path))
    assert document.pageCount() == 1
    size = document.pagePointSize(0)
    assert abs(size.width() * 25.4 / 72 - 50) < 0.2 and abs(size.height() * 25.4 / 72 - 30) < 0.2
    assert decode_image(document.render(0, QSize(400, 240)))[0] == DIAGNOSTIC_PAYLOAD


@pytest.fixture
def dialog(tmp_path, monkeypatch):
    from selby_workstation.desktop_auth import AuthTransport
    from selby_workstation.incoming import PreviewClient
    from selby_workstation.intake_client import IntakeClient

    def forbidden(*args, **kwargs):
        pytest.fail("Calibration called a backend API")

    monkeypatch.setattr(IntakeClient, "execute", forbidden)
    monkeypatch.setattr(PreviewClient, "_get", forbidden)
    monkeypatch.setattr(AuthTransport, "request", forbidden)
    monkeypatch.setattr(
        QPrinterInfo, "availablePrinterNames", lambda: ["Virtual diagnostic printer"]
    )
    d = CalibrationDialog(tmp_path / "desktop.ini")
    d.show()
    QApplication.processEvents()
    yield d
    wait(d)
    d.close()
    QApplication.processEvents()


def test_preview_no_printer_no_history_no_backend(dialog, monkeypatch):
    import selby_workstation.calibration_ui as ui

    monkeypatch.setattr(ui, "native_printer", lambda *a: pytest.fail("Preview opened printer"))
    monkeypatch.setattr(ui, "submit", lambda *a: pytest.fail("Preview submitted job"))
    assert not dialog.print_button.isEnabled()
    assert not dialog.history.path.exists()
    dialog.preview_button.click()
    wait(dialog)
    assert decode_image(dialog.preview.pixmap().toImage())[0] == DIAGNOSTIC_PAYLOAD
    assert not dialog.history.path.exists()


def test_cancel_and_nested_repeated_click(dialog, monkeypatch):
    import selby_workstation.calibration_ui as ui

    dialog.printer.setCurrentIndex(1)
    monkeypatch.setattr(
        ui, "native_printer", lambda *a: pytest.fail("Cancelled print opened printer")
    )
    confirmations = []

    def cancel(*args):
        confirmations.append(args)
        assert dialog.busy
        dialog.print_test()  # Nested event loop / rapid activation cannot open another confirmation.
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", cancel)
    dialog.print_test()
    assert len(confirmations) == 1 and not dialog.history.path.exists() and not dialog.busy
    assert "cancelled" in dialog.status.text()


def test_mock_submission_repeated_click_and_preference(dialog, monkeypatch):
    import selby_workstation.calibration_ui as ui

    calls = []
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(ui, "native_printer", lambda name: SimpleNamespace(resolution=lambda: 203))

    def mock_submit(printer, images):
        calls.append(decode_image(images[0])[0])
        started.set()
        assert release.wait(3)

    monkeypatch.setattr(ui, "submit", mock_submit)
    dialog.printer.setCurrentIndex(1)
    dialog.print_test()
    try:
        assert started.wait(2)
        dialog.print_test()
        dialog.close()
        assert dialog.isVisible() and dialog.busy
    finally:
        release.set()
    wait(dialog)
    assert calls == [DIAGNOSTIC_PAYLOAD] and "NOT verified" in dialog.status.text()
    with sqlite3.connect(dialog.history.path) as db:
        assert db.execute("SELECT payload,outcome FROM diagnostic_jobs").fetchall() == [
            (DIAGNOSTIC_PAYLOAD, "submitted")
        ]
    reopened = CalibrationDialog(dialog.settings.fileName())
    assert reopened.printer.currentData() == "Virtual diagnostic printer"
    assert reopened.settings.value("labels/printer") is None
    reopened.close()


@pytest.mark.parametrize(
    "message",
    [
        "Selected printer is unavailable.",
        "Incorrect label dimensions; configure the Windows driver.",
    ],
)
def test_driver_errors_before_submission(dialog, monkeypatch, message):
    import selby_workstation.calibration_ui as ui

    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)

    def fail(name):
        raise ValueError(message)

    monkeypatch.setattr(ui, "native_printer", fail)
    monkeypatch.setattr(ui, "submit", lambda *a: pytest.fail("Invalid driver submitted job"))
    dialog.printer.setCurrentIndex(1)
    dialog.print_test()
    wait(dialog)
    assert message in dialog.status.text() and not dialog.history.path.exists()


def test_uncertain_submission_blocks_retry_until_review(dialog, monkeypatch):
    import selby_workstation.calibration_ui as ui

    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(ui, "native_printer", lambda name: SimpleNamespace(resolution=lambda: 203))
    calls = []

    def fail(*args):
        calls.append(1)
        raise ValueError("Synthetic uncertain response")

    monkeypatch.setattr(ui, "submit", fail)
    dialog.printer.setCurrentIndex(1)
    dialog.print_test()
    wait(dialog)
    dialog.print_test()
    wait(dialog)
    assert calls == [1] and "earlier diagnostic" in dialog.status.text()
    dialog.review()
    wait(dialog)
    assert "Review recorded for 1" in dialog.status.text()
    with sqlite3.connect(dialog.history.path) as db:
        outcome, reviewed = db.execute("SELECT outcome,reviewed_at FROM diagnostic_jobs").fetchone()
    assert outcome == "uncertain" and reviewed


def test_restart_pending_and_atomic_concurrent_guard(tmp_path):
    history = DiagnosticHistory(tmp_path / "diagnostics.sqlite3")
    original = history.reserve("Virtual")
    reopened = DiagnosticHistory(history.path)
    with pytest.raises(ValueError, match="earlier diagnostic"):
        reopened.reserve("Virtual")
    assert reopened.review("Virtual") == 1
    second = reopened.reserve("Virtual")
    assert second != original
    reopened.finish(second, "submitted")


def test_real_native_confirmation_is_explicit_and_cancelable(dialog, monkeypatch):
    from PySide6.QtCore import QTimer

    import selby_workstation.calibration_ui as ui

    dialog.printer.setCurrentIndex(1)
    monkeypatch.setattr(
        ui, "native_printer", lambda *a: pytest.fail("Cancelled confirmation opened printer")
    )
    observed = []

    def cancel():
        box = QApplication.activeModalWidget()
        if isinstance(box, QMessageBox):
            observed.append(box.text())
            box.button(QMessageBox.StandardButton.Cancel).click()

    QTimer.singleShot(100, cancel)
    dialog.print_test()
    assert len(observed) == 1 and "ONE TEST / NOT VALID" in observed[0]
    assert "50 × 30 mm" in observed[0] and not dialog.history.path.exists()


def test_concurrent_diagnostic_intents_are_serialized(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "diagnostics.sqlite3"
    DiagnosticHistory(path).connection().close()

    def reserve():
        try:
            return DiagnosticHistory(path).reserve("Virtual")
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(), range(2)))
    assert sum(result is not None for result in results) == 1


def test_preview_with_no_available_devices_and_missing_saved_printer(dialog, monkeypatch):
    dialog.printer.setCurrentIndex(1)
    monkeypatch.setattr(QPrinterInfo, "availablePrinterNames", lambda: [])
    reopened = CalibrationDialog(dialog.settings.fileName())
    reopened.show()
    assert reopened.printer.currentData() == "Virtual diagnostic printer"
    assert "(missing)" in reopened.printer.currentText()
    reopened.show_preview()
    wait(reopened)
    assert decode_image(reopened.preview.pixmap().toImage())[0] == DIAGNOSTIC_PAYLOAD
    assert not reopened.history.path.exists()
    reopened.close()
