"""Read-only native acceptance through the real .pyw entry point; run manually, never by pytest."""

import hashlib
import json
import runpy
import sqlite3
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from selby_workstation import thermal_printing
from selby_workstation.intake_client import IntakeClient
from selby_workstation.label_mapping import mapped_orders

calibration_mode = "--calibration" in sys.argv
OUT = (
    Path(__file__).resolve().parents[2]
    / "validation_artifacts"
    / ("v05b1" if calibration_mode else "v05b-navigation")
)
OUT.mkdir(parents=True, exist_ok=True)
result = dict(
    physical_jobs_submitted=0,
    backend_business_posts=0,
    entrypoint="scanner_agent/selby_desktop.pyw",
)
original_exec = QApplication.exec
stage = 0
window = None
baseline = None
backend_baseline = None
context = None
preview_index = 0
fixture_login = "--local-fixture-login" in sys.argv
login_started = False
temporary_auth = None
finished = False
calibration_stage = 0
native_configure_only = thermal_printing.native_printer


def forbidden(*args, **kwargs):
    raise AssertionError("Acceptance harness forbids hardware and backend business writes")


thermal_printing.native_printer = forbidden
thermal_printing.submit = forbidden
IntakeClient.execute = forbidden


def registry_digest(path):
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as db:
        return hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def finish(error=None):
    global finished
    if finished:
        return
    finished = True
    if error:
        result["error"] = str(error)
    if window is not None:
        result["registry_unchanged"] = baseline == registry_digest(window.orders_path)
    if temporary_auth is not None:
        temporary_auth.sign_out()
    (OUT / "native-acceptance.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)
    QApplication.instance().exit(1 if error else 0)


def tick():
    global \
        stage, \
        window, \
        baseline, \
        backend_baseline, \
        context, \
        preview_index, \
        login_started, \
        temporary_auth
    global calibration_stage
    try:
        app = QApplication.instance()
        if window is None:
            window = next((w for w in app.topLevelWidgets() if hasattr(w, "desktop")), None)
            if window is None:
                QTimer.singleShot(100, tick)
                return
            result["platform"] = app.platformName()
            assert result["platform"] == "windows"
            baseline = registry_digest(window.orders_path)
            context = next(
                row for row in mapped_orders(window.orders_path) if row["order_id"] == "ORD-000001"
            )
            result["order"] = context["order_id"]
            result["sp"] = context["sp"]
            result["cards"] = context["cards"]
        incoming = window.desktop.pages["Incoming Submissions"]
        page = window.desktop.pages["Labels"]
        if calibration_mode and calibration_stage < 4:
            if calibration_stage == 0:
                result["production_printer_before"] = window.desktop.settings.value(
                    "labels/printer", ""
                )
                window.desktop.buttons["Labels"].click()
                calibration_stage = 1
            elif calibration_stage == 1:
                if page.busy:
                    QTimer.singleShot(100, tick)
                    return
                assert window.grab().save(str(OUT / "windows-calibration-section.png"))
                page.calibration_button.click()
                assert page.calibration_dialog is not None
                page.calibration_dialog.preview_button.click()
                calibration_stage = 2
            elif calibration_stage == 2:
                calibration = page.calibration_dialog
                if calibration.busy:
                    QTimer.singleShot(100, tick)
                    return
                import cv2
                import numpy as np
                from PySide6.QtGui import QImage, QPageLayout

                from selby_workstation.calibration import DIAGNOSTIC_PAYLOAD

                image = (
                    calibration.preview.pixmap()
                    .toImage()
                    .convertToFormat(QImage.Format.Format_RGB888)
                )
                pixels = (
                    np.frombuffer(image.bits(), dtype=np.uint8)
                    .reshape(image.height(), image.bytesPerLine())[:, : image.width() * 3]
                    .reshape(image.height(), image.width(), 3)
                )
                assert cv2.QRCodeDetector().detectAndDecode(pixels)[0] == DIAGNOSTIC_PAYLOAD
                assert not calibration.history.path.exists(), (
                    "Preview unexpectedly created a diagnostic job"
                )
                index = calibration.printer.findData("Munbyn ITPP941")
                assert index > 0
                calibration.printer.setCurrentIndex(index)
                # Configure only: no painter or submission, no Print button activation.
                printer = native_configure_only("Munbyn ITPP941")
                rect = printer.pageLayout().fullRect(QPageLayout.Unit.Millimeter)
                result["calibration"] = dict(
                    payload=DIAGNOSTIC_PAYLOAD,
                    width_pixels=image.width(),
                    height_pixels=image.height(),
                    selected=printer.printerName(),
                    width_mm=rect.width(),
                    height_mm=rect.height(),
                    dpi=printer.resolution(),
                    diagnostic_jobs_created=0,
                    print_button_activated=False,
                )
                assert calibration.grab().save(str(OUT / "windows-calibration-preview.png"))
                assert image.save(str(OUT / "diagnostic-label.png"))
                calibration.close()
                result["production_printer_after"] = window.desktop.settings.value(
                    "labels/printer", ""
                )
                assert result["production_printer_before"] == result["production_printer_after"]
                calibration_stage = 4
            QTimer.singleShot(100, tick)
            return
        if stage == 0:
            if incoming.busy:
                QTimer.singleShot(100, tick)
                return
            if fixture_login and not login_started:
                from selby_workstation.desktop_auth import DesktopAuthService

                connection = incoming.auth.connection
                assert (
                    connection.environment == "development"
                    and connection.backend_origin == "http://127.0.0.1:8000"
                )

                class MemoryStore:
                    value = None

                    def load(self):
                        return self.value

                    def save(self, value):
                        self.value = value

                    def delete(self):
                        self.value = None

                temporary_auth = DesktopAuthService(connection, store=MemoryStore())
                incoming.auth = temporary_auth
                document = (OUT.parents[1] / "SELBY_LOCAL_TEST_CREDENTIALS.md").read_text(
                    encoding="utf-8-sig"
                )
                row = [line for line in document.splitlines() if "| operator@selby.test |" in line][
                    -1
                ]
                password = row.split("|")[3].strip()
                assert "Not generated" not in password
                incoming.email.setText("operator@selby.test")
                incoming.password.setText(password)
                incoming.connect_backend()
                login_started = True
                result["authentication"] = (
                    "Existing local operator fixture; temporary in-memory session; revoked on exit"
                )
                QTimer.singleShot(100, tick)
                return
            client = incoming.auth.intake_client()
            backend_baseline = digest(client.production(context["sid"])["submission"])
            assert window.desktop.buttons["Labels"].isEnabled()
            window.desktop.buttons["Labels"].click()
            stage = 1
        elif stage == 1:
            if page.busy:
                QTimer.singleShot(100, tick)
                return
            index = next(
                i
                for i in range(1, page.orders.count())
                if page.orders.itemData(i)["order_id"] == "ORD-000001"
            )
            page.orders.setCurrentIndex(index)
            page.open_button.click()
            stage = 2
        elif stage == 2:
            dialog = page.dialog
            if dialog.busy:
                QTimer.singleShot(100, tick)
                return
            if not dialog.state:
                raise AssertionError(dialog.status.text())
            assert len(dialog.state["labels"]) == 3
            assert "payment_unverified" in dialog.state["blockers"]
            assert not dialog.buttons[2].isEnabled() and not dialog.buttons[3].isEnabled()
            assert {card["card_id"] for card in context["cards"]} == {
                "SLB-C-000001",
                "SLB-C-000002",
            }
            dialog.labels.clearSelection()
            dialog.labels.item(preview_index).setSelected(True)
            dialog.labels.scrollToItem(dialog.labels.item(preview_index))
            dialog.show_preview()
            stage = 3
        elif stage == 3:
            dialog = page.dialog
            if dialog.busy:
                QTimer.singleShot(100, tick)
                return
            assert dialog.state and not dialog.preview.pixmap().isNull(), dialog.status.text()
            import cv2
            import numpy as np
            from PySide6.QtGui import QImage

            image = dialog.preview.pixmap().toImage().convertToFormat(QImage.Format.Format_RGB888)
            pixels = (
                np.frombuffer(image.bits(), dtype=np.uint8)
                .reshape(image.height(), image.bytesPerLine())[:, : image.width() * 3]
                .reshape(image.height(), image.width(), 3)
            )
            decoded = cv2.QRCodeDetector().detectAndDecode(pixels)[0]
            assert decoded == dialog.state["labels"][preview_index]["payload"]
            result.setdefault("decoded_payloads", []).append(decoded)
            assert not dialog.buttons[2].isEnabled() and not dialog.buttons[3].isEnabled()
            assert "payment_unverified" in dialog.eligibility.text()
            assert window.grab().save(str(OUT / f"windows-labels-preview-{preview_index}.png"))
            preview_index += 1
            if preview_index < 3:
                stage = 2
            else:
                client = incoming.auth.intake_client()
                result.update(
                    previews=3,
                    blockers=dialog.state["blockers"],
                    print_buttons_disabled=True,
                    backend_order_unchanged=backend_baseline
                    == digest(client.production(context["sid"])["submission"]),
                    label_payloads=[label["payload"] for label in dialog.state["labels"]],
                    registry_before=baseline,
                    registry_after=registry_digest(window.orders_path),
                )
                finish()
                return
        QTimer.singleShot(100, tick)
    except Exception as exc:
        finish(exc)


def instrumented_exec(app):
    QTimer.singleShot(100, tick)
    QTimer.singleShot(45000, lambda: finish("Native acceptance timed out"))
    return original_exec(app)


QApplication.exec = instrumented_exec
sys.argv = [str(Path(__file__).resolve().parents[1] / "selby_desktop.pyw")]
runpy.run_path(sys.argv[0], run_name="__main__")
