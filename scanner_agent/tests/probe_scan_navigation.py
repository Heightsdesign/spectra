# ruff: noqa: E402 -- real entrypoint probe imports after repository path setup
"""Native read-only live-backend acceptance. No physical scanner or printer automation."""

import hashlib
import json
import runpy
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scanner_agent"))
from selby_workstation import thermal_printing
from selby_workstation.desktop_auth import DesktopAuthService
from selby_workstation.intake_client import IntakeClient
from selby_workstation.label_mapping import mapped_orders

OUT = ROOT / "validation_artifacts/v05c"
OUT.mkdir(parents=True, exist_ok=True)
original_exec = QApplication.exec
started = time.monotonic()
state = 0
window = auth = context = before = backend_before = None
result = {
    "physical_scans": 0,
    "prints": 0,
    "business_posts": 0,
    "input": "manual software payload injection",
    "entrypoint": "selby_desktop.pyw",
}


def forbidden(*args, **kwargs):
    raise AssertionError("Business writes and printing forbidden by acceptance harness")


IntakeClient.execute = forbidden
thermal_printing.submit = forbidden


class MemoryStore:
    value = None

    def load(self):
        return self.value

    def save(self, value):
        self.value = value

    def delete(self):
        self.value = None


def registry_hash():
    import sqlite3

    with sqlite3.connect(window.orders_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        return hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()


def finish(error=None):
    if error:
        result["error"] = str(error)
    if window is not None and before is not None:
        result["registry_unchanged"] = before == registry_hash()
    if auth is not None:
        try:
            if backend_before is not None:
                result["backend_snapshot_unchanged"] = (
                    backend_before == auth.intake_client().production(context["sid"])
                )
            result["temporary_session_revoked"] = auth.sign_out()
        except Exception:
            result["cleanup"] = "Unable to verify live backend or revoke session"
    (OUT / "live-native-acceptance.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    if window is not None:
        window.desktop.scanner_dialog.hide() if hasattr(window.desktop, "scanner_dialog") else None
        window.hide()
    QApplication.instance().exit(1 if error else 0)


def tick():
    global state, window, auth, context, before, backend_before
    try:
        if time.monotonic() - started > 50:
            raise RuntimeError("Live acceptance timeout")
        if window is None:
            window = next(
                (w for w in QApplication.topLevelWidgets() if hasattr(w, "desktop")), None
            )
            if window is None:
                QTimer.singleShot(100, tick)
                return
            assert QApplication.platformName() == "windows"
            result["qt_platform"] = "windows"
            before = registry_hash()
            context = next(r for r in mapped_orders(window.orders_path) if r["confirmed"])
        incoming = window.desktop.pages["Incoming Submissions"]
        if state == 0:
            if incoming.busy:
                QTimer.singleShot(100, tick)
                return
            connection = incoming.auth.connection
            assert (
                connection.environment == "development"
                and connection.backend_origin == "http://127.0.0.1:8000"
            )
            auth = DesktopAuthService(connection, store=MemoryStore())
            incoming.auth = auth
            document = (ROOT / "SELBY_LOCAL_TEST_CREDENTIALS.md").read_text(encoding="utf-8-sig")
            row = [line for line in document.splitlines() if "| operator@selby.test |" in line][-1]
            incoming.email.setText("operator@selby.test")
            incoming.password.setText(row.split("|")[3].strip())
            incoming.connect_backend()
            state = 1
        elif state == 1:
            if incoming.busy:
                QTimer.singleShot(100, tick)
                return
            backend_before = auth.intake_client().production(context["sid"])
            window.desktop.navigate("Orders")
            window.desktop.open_scanner()
            dialog = window.desktop.scanner_dialog
            dialog.input.setText("SELBY:TEST:V1:CALIBRATION")
            dialog.submit()
            assert "Diagnostic recognized" in dialog.status.text()
            dialog.grab().save(str(OUT / "live-diagnostic.png"))
            result["diagnostic"] = dialog.status.text()
            dialog.input.setText("SP:PC:1:" + context["cards"][0]["pc"])
            dialog.submit()
            state = 2
        elif state == 2:
            dialog = window.desktop.scanner_dialog
            if dialog.busy:
                QTimer.singleShot(100, tick)
                return
            assert "BLOCKED" in dialog.status.text(), dialog.status.text()
            assert window.session is None
            result["card_result"] = dialog.status.text()
            dialog.grab().save(str(OUT / "live-unpaid-blocked.png"))
            dialog.input.setText("SP:PC:1:" + context["cards"][0]["pc"])
            dialog.submit()
            assert "Repeated scan ignored" in dialog.status.text()
            result["duplicate_suppressed"] = True
            dialog.close()
            window.desktop.navigate("Labels")
            state = 3
        elif state == 3:
            if window.desktop.pages["Labels"].busy:
                QTimer.singleShot(100, tick)
                return
            window.desktop.open_scanner()
            dialog = window.desktop.scanner_dialog
            dialog.input.setText("SELBY:TEST:V1:CALIBRATION")
            dialog.submit()
            assert "Diagnostic recognized" in dialog.status.text()
            window.grab().save(str(OUT / "live-labels.png"))
            result["orders_and_labels"] = True
            result["grading_session_created"] = window.session is not None
            finish()
            return
        QTimer.singleShot(100, tick)
    except Exception as exc:
        finish(exc)


def execute(app):
    QTimer.singleShot(100, tick)
    return original_exec(app)


QApplication.exec = execute
sys.argv = ["selby_desktop.pyw"]
runpy.run_path(str(ROOT / "scanner_agent/selby_desktop.pyw"), run_name="__main__")
