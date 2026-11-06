"""Windows Qt previews and PDF virtual printer only. Never submits to native hardware."""

import json
import sys
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QMarginsF, QSize, QSizeF, qVersion
from PySide6.QtGui import QImage, QPageLayout, QPageSize
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
from PySide6.QtWidgets import QApplication, QMessageBox

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from selby_workstation.labels_ui import LabelDialog
from selby_workstation.thermal_printing import native_printer, render_label, submit

APP = QApplication.instance() or QApplication([])
OUT = Path(__file__).resolve().parents[2] / "validation_artifacts" / "v05b"


def label(kind="physical_card", value="1"):
    ref = ("SP-" if kind == "order" else "PC-") + value * 32
    prefix = "SP:ORDER:1:" if kind == "order" else "SP:PC:1:"
    return dict(
        kind=kind,
        reference=ref,
        payload=prefix + ref,
        text="2 active physical cards"
        if kind == "order"
        else "Synthetic Pikachu\nBase Set\n58/102 / FR",
    )


def wait(widget):
    deadline = time.monotonic() + 5
    while widget.busy and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(0.01)
    assert not widget.busy


@pytest.mark.parametrize("item", [label("order"), label(value="2"), label(value="3")])
def test_preview_qr_readability(item):
    image = render_label(item)
    assert image.width() == 400 and image.height() == 240
    image = image.convertToFormat(image.Format.Format_RGB888)
    pixels = (
        np.frombuffer(image.bits(), dtype=np.uint8)
        .reshape(240, image.bytesPerLine())[:, :1200]
        .reshape(240, 400, 3)
    )
    decoded, points, _ = cv2.QRCodeDetector().detectAndDecode(pixels)
    assert decoded == item["payload"]
    OUT.mkdir(parents=True, exist_ok=True)
    assert image.save(str(OUT / (item["reference"] + ".png")))


def test_virtual_qt_print_dimensions_and_pages(tmp_path):
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    path = tmp_path / "virtual.pdf"
    printer.setOutputFileName(str(path))
    printer.setResolution(203)
    assert printer.setPageLayout(
        QPageLayout(
            QPageSize(QSizeF(50, 30), QPageSize.Unit.Millimeter),
            QPageLayout.Orientation.Portrait,
            QMarginsF(0, 0, 0, 0),
            QPageLayout.Unit.Millimeter,
        )
    )
    printer.setFullPage(True)
    submit(printer, [render_label(label(value="2")), render_label(label(value="3"))])
    assert path.stat().st_size > 1000
    # Qt PDF parser independently verifies physical media and number of pages.
    from PySide6.QtPdf import QPdfDocument

    document = QPdfDocument()
    document.load(str(path))
    assert document.pageCount() == 2
    size = document.pagePointSize(0)
    assert abs(size.width() * 25.4 / 72 - 50) < 0.3
    assert abs(size.height() * 25.4 / 72 - 30) < 0.3
    for index, value in enumerate(("2", "3")):
        rendered = document.render(index, QSize(400, 240)).convertToFormat(
            QImage.Format.Format_RGB888
        )
        pixels = (
            np.frombuffer(rendered.bits(), dtype=np.uint8)
            .reshape(240, rendered.bytesPerLine())[:, :1200]
            .reshape(240, 400, 3)
        )
        assert cv2.QRCodeDetector().detectAndDecode(pixels)[0] == label(value=value)["payload"]


def test_missing_and_unavailable_printer(monkeypatch):
    monkeypatch.setattr(QPrinterInfo, "availablePrinters", lambda: [])
    with pytest.raises(ValueError, match="missing"):
        native_printer("Munbyn ITPP941")
    fake = SimpleNamespace(
        printerName=lambda: "Munbyn ITPP941",
        isNull=lambda: False,
        state=lambda: QPrinter.PrinterState.Error,
    )
    monkeypatch.setattr(QPrinterInfo, "availablePrinters", lambda: [fake])
    with pytest.raises(ValueError, match="unavailable"):
        native_printer("Munbyn ITPP941")


@pytest.mark.parametrize("reject_layout,bad_size", [(True, False), (False, True)])
def test_wrong_dimensions(monkeypatch, reject_layout, bad_size):
    import selby_workstation.thermal_printing as module

    info = SimpleNamespace(
        printerName=lambda: "virtual",
        isNull=lambda: False,
        state=lambda: QPrinter.PrinterState.Idle,
    )
    monkeypatch.setattr(QPrinterInfo, "availablePrinters", lambda: [info])

    class Fake:
        OutputFormat = QPrinter.OutputFormat
        PrinterState = QPrinter.PrinterState
        PrinterMode = QPrinter.PrinterMode

        def __init__(self, *args):
            pass

        def isValid(self):
            return True

        def printerName(self):
            return "virtual"

        def __getattr__(self, name):
            return lambda *args: None

        def setPageLayout(self, layout):
            self.layout = layout
            return not reject_layout

        def pageLayout(self):
            if bad_size:
                return QPageLayout(
                    QPageSize(QPageSize.PageSizeId.A4),
                    QPageLayout.Orientation.Portrait,
                    QMarginsF(),
                )
            return self.layout

    monkeypatch.setattr(module, "QPrinter", Fake)
    with pytest.raises(ValueError, match="50 x 30|dimensions"):
        module.native_printer("virtual")


def test_dialog_preview_restart_reprint_and_uncertain_claim(tmp_path, monkeypatch):
    import selby_workstation.labels_ui as ui

    state = dict(
        reference=label("order")["reference"],
        actor=str(uuid4()),
        labels=[label("order"), label(value="2"), label(value="3")],
        print_eligible=True,
        blockers=[],
        history=[],
    )
    calls = []

    class Client:
        connection = SimpleNamespace(backend_origin="http://127.0.0.1:9999")

        def labels(self, sid):
            return deepcopy(state)

        def execute(self, operation):
            payload = operation["payload"]
            calls.append(payload)
            if payload["phase"] == "claimed" and self.uncertain:
                from selby_workstation.incoming import PreviewError

                raise PreviewError("Synthetic lost response")
            state["history"].append(
                dict(
                    id=payload["job_id"],
                    action="label_" + payload["phase"],
                    actor=state["actor"],
                    timestamp="2026-11-01T12:00:00Z",
                    data={
                        k: payload[k]
                        for k in ("references", "printer", "width_mm", "height_mm", "fingerprint")
                    },
                    reason=payload["reason"],
                )
            )
            return dict(accepted=True)

        uncertain = False

    client = Client()
    auth = SimpleNamespace(intake_client=lambda: client)
    monkeypatch.setattr(QPrinterInfo, "availablePrinterNames", lambda: ["Virtual test printer"])
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    spooled = []
    monkeypatch.setattr(ui, "native_printer", lambda name: SimpleNamespace(resolution=lambda: 203))
    monkeypatch.setattr(ui, "submit", lambda printer, images: spooled.append(len(images)))
    path = tmp_path / "desktop.ini"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "preview-environment.json").write_text(
        json.dumps(
            dict(
                platform=APP.platformName(),
                qt=qVersion(),
                physical_jobs_submitted=0,
                fixture="Synthetic order and two distinct physical cards; mocked authenticated client",
            ),
            indent=2,
        )
    )
    widget = LabelDialog(auth, str(uuid4()), settings_path=path)
    widget.show()
    wait(widget)
    assert not calls and not spooled  # Opening never prints.
    widget.printer.setCurrentIndex(1)
    for index, title in [(0, "order"), (1, "card-one"), (2, "card-two")]:
        widget.labels.clearSelection()
        widget.labels.item(index).setSelected(True)
        widget.show_preview()
        wait(widget)
        APP.processEvents()
        OUT.mkdir(parents=True, exist_ok=True)
        assert widget.grab().save(str(OUT / f"windows-preview-{title}.png"))
    widget.labels.clearSelection()
    widget.labels.item(1).setSelected(True)
    widget.labels.item(2).setSelected(True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    widget.print_selected()
    assert not spooled
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    widget.print_selected()
    widget.print_selected()  # Repeated click while worker is busy cannot create another job.
    wait(widget)
    assert spooled == [2] and "NOT verified" in widget.status.text()
    widget.print_all()
    assert "mandatory" in widget.status.text() and spooled == [2]
    widget.verify()
    wait(widget)
    assert widget.jobs.count() == 0
    widget.close()
    reopened = LabelDialog(auth, widget.sid, settings_path=path)
    reopened.show()
    wait(reopened)
    assert reopened.printer.currentData() == "Virtual test printer"
    reopened.labels.item(1).setSelected(True)
    reopened.reason.setText("Sleeve damaged; previous queue inspected")
    client.uncertain = True
    reopened.print_selected()
    wait(reopened)
    assert spooled == [2] and "lost response" in reopened.status.text()
    journal = [json.loads(line) for line in reopened.journal.read_text().splitlines()]
    assert any(e["event"]["phase"] == "claimed" and e["result"] == "intent" for e in journal)
    client.uncertain = False
    reopened.refresh()
    wait(reopened)
    reopened.labels.item(1).setSelected(True)

    def unavailable(name):
        raise ValueError("Synthetic unavailable printer")

    monkeypatch.setattr(ui, "native_printer", unavailable)
    claims_before = sum(e["phase"] == "claimed" for e in calls)
    reopened.print_selected()
    wait(reopened)
    assert spooled == [2]
    assert sum(e["phase"] == "claimed" for e in calls) == claims_before
    assert calls[-1]["phase"] == "failed" and "configuration" in calls[-1]["error"]
    reopened.close()
