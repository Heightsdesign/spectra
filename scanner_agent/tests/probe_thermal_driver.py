"""Manual, non-printing driver probe. This file is not collected by pytest."""

import json
import sys
from pathlib import Path

from PySide6.QtGui import QPageLayout
from PySide6.QtPrintSupport import QPrinterInfo
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from selby_workstation.thermal_printing import native_printer

app = QApplication([])
result = dict(
    platform=app.platformName(),
    printers=QPrinterInfo.availablePrinterNames(),
    physical_jobs_submitted=0,
)
try:
    printer = native_printer("Munbyn ITPP941")
    rect = printer.pageLayout().fullRect(QPageLayout.Unit.Millimeter)
    result.update(
        selected=printer.printerName(),
        width_mm=rect.width(),
        height_mm=rect.height(),
        dpi=printer.resolution(),
        orientation=str(printer.pageLayout().orientation()),
        full_page=printer.fullPage(),
        copies=printer.copyCount(),
        result="configured_without_submission",
    )
except ValueError as exc:
    result.update(result="rejected", error=str(exc))
output = (
    Path(__file__).resolve().parents[2]
    / "validation_artifacts"
    / "v05b"
    / "windows-driver-probe.json"
)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
