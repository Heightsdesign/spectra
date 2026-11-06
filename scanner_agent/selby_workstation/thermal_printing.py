"""Exact-size bitmap rendering and native Qt output; no fallback printer."""

import math

import segno
from PySide6.QtCore import QMarginsF, QPoint, QRectF, QSizeF, Qt
from PySide6.QtGui import QFont, QImage, QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo


def render_label(label, dpi=203):
    width, height = round(50 * dpi / 25.4), round(30 * dpi / 25.4)
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    p = QPainter(image)
    try:
        p.setPen(Qt.GlobalColor.black)
        matrix = list(
            segno.make_qr(label["payload"], error="q", boost_error=False).matrix_iter(border=4)
        )
        module = math.floor(19 * dpi / 25.4 / len(matrix))
        if module < 3:
            raise ValueError("QR resolution too low")
        x0, y0 = round(2 * dpi / 25.4), round(3 * dpi / 25.4)
        for y, row in enumerate(matrix):
            for x, dark in enumerate(row):
                if dark:
                    p.fillRect(
                        x0 + x * module, y0 + y * module, module, module, Qt.GlobalColor.black
                    )

        def text(value, x, y, w, h, pixels, bold=False, lines=3):
            font = QFont("Arial")
            font.setPixelSize(pixels)
            font.setBold(bold)
            p.setFont(font)
            rect = QRectF(x * dpi / 25.4, y * dpi / 25.4, w * dpi / 25.4, h * dpi / 25.4)
            p.drawText(
                rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                p.fontMetrics().elidedText(
                    value, Qt.TextElideMode.ElideRight, int(rect.width() * lines)
                ),
            )

        text("SELBY", 23, 3, 25, 4, round(9 * dpi / 72), True)
        diagnostic = label["kind"] == "diagnostic"
        text(
            "TEST / NOT VALID"
            if diagnostic
            else ("Order bag" if label["kind"] == "order" else "Physical card"),
            23,
            8,
            25,
            4,
            round((7.5 if diagnostic else 6) * dpi / 72),
            bold=diagnostic,
            lines=1 if diagnostic else 3,
        )
        parts = label["text"].split("\n")
        if label["kind"] == "physical_card" and len(parts) == 3:
            for index, part in enumerate(parts):
                text(part, 23, 12 + index * 3.3, 25, 3.3, round(6 * dpi / 72), lines=1)
        else:
            text(label["text"], 23, 12, 25, 10, round(6 * dpi / 72))
        font = QFont("Consolas")
        font.setPixelSize(round(5.5 * dpi / 72))
        p.setFont(font)
        ref = label["reference"]
        if p.fontMetrics().horizontalAdvance(ref) > width - 2 * x0:
            raise ValueError("Full reference does not fit")
        p.drawText(
            QRectF(x0, height - 5 * dpi / 25.4, width - 2 * x0, 4 * dpi / 25.4),
            Qt.AlignmentFlag.AlignLeft,
            ref,
        )
        if diagnostic:
            # Integer-dot corner marks strictly inside the shared 2 mm margin.
            # Top marks stop before the QR's four-module quiet-zone rectangle.
            inset = math.ceil(2 * dpi / 25.4) + 1
            length = max(1, round(0.6 * dpi / 25.4))
            for x, direction_x in ((inset, 1), (width - inset - 1, -1)):
                for y, direction_y in ((inset, 1), (height - inset - 1, -1)):
                    p.fillRect(
                        min(x, x + direction_x * length), y, length + 1, 1, Qt.GlobalColor.black
                    )
                    p.fillRect(
                        x, min(y, y + direction_y * length), 1, length + 1, Qt.GlobalColor.black
                    )
    finally:
        p.end()
    return image


def native_printer(name):
    info = next((p for p in QPrinterInfo.availablePrinters() if p.printerName() == name), None)
    if info is None or info.isNull():
        raise ValueError("Selected printer is missing; choose it explicitly.")
    if info.state() == QPrinter.PrinterState.Error:
        raise ValueError("Selected printer is unavailable.")
    printer = QPrinter(info, QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.NativeFormat)
    printer.setPrinterName(name)
    if not printer.isValid() or printer.printerName() != name:
        raise ValueError("Selected printer could not be opened; fallback printing is forbidden.")
    printer.setResolution(203)
    layout = QPageLayout(
        QPageSize(
            QSizeF(50, 30),
            QPageSize.Unit.Millimeter,
            "SELBY 50x30",
            QPageSize.SizeMatchPolicy.ExactMatch,
        ),
        QPageLayout.Orientation.Portrait,
        QMarginsF(0, 0, 0, 0),
        QPageLayout.Unit.Millimeter,
    )
    if not printer.setPageLayout(layout):
        raise ValueError("Driver rejected 50 x 30 mm.")
    printer.setFullPage(True)
    printer.setCopyCount(1)
    size = printer.pageLayout().fullRect(QPageLayout.Unit.Millimeter).size()
    if abs(size.width() - 50) > 0.2 or abs(size.height() - 30) > 0.2:
        raise ValueError("Incorrect label dimensions; configure the Windows driver.")
    margins = printer.pageLayout().minimumMargins()
    if max(margins.left(), margins.right(), margins.top(), margins.bottom()) > 2:
        raise ValueError("Printer margins would clip the label.")
    return printer


def submit(printer, images):
    dpi = printer.resolution()
    if not images or any(
        image.width() != round(50 * dpi / 25.4) or image.height() != round(30 * dpi / 25.4)
        for image in images
    ):
        raise ValueError("Rendered label dimensions do not match printer resolution.")
    painter = QPainter()
    if not painter.begin(printer):
        raise ValueError(
            "Printer could not start; outcome uncertain. Inspect queue before reprint."
        )
    try:
        for index, image in enumerate(images):
            if index and not printer.newPage():
                raise ValueError("Printer page failed; some labels may have been submitted.")
            # Physical coordinates, no fit-to-page transformation. QR image uses integer modules.
            painter.drawImage(QPoint(0, 0), image)
        if not painter.end() or printer.printerState() == QPrinter.PrinterState.Error:
            raise ValueError("Printer submission uncertain. Inspect queue before reprint.")
    finally:
        if painter.isActive():
            painter.end()
