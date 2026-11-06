from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="SELBY V0.5c.1 unified desktop workstation")
    parser.add_argument("--image", type=Path)
    parser.add_argument("--physical", type=Path)
    parser.add_argument("--printed", type=Path)
    parser.add_argument("--session", type=Path)
    parser.add_argument("--orders", action="store_true", help="Open the orders registry")
    parser.add_argument("--orders-store", type=Path, help="Explicit local orders SQLite path")
    parser.add_argument("--grading", action="store_true", help="Open draft grading workbench")
    parser.add_argument(
        "--condition", action="store_true", help="Open the assisted condition workbench"
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Show window, process events, then exit without saving",
    )
    parser.add_argument(
        "--screenshot", type=Path, help="New screenshot file for smoke verification"
    )
    args = parser.parse_args()
    if args.condition and not (args.image or args.session):
        parser.error("--condition requires --image or --session")
    if args.grading and not (args.image or args.session):
        parser.error("--grading requires --image or --session")
    if args.grading and args.condition:
        parser.error("Choose --grading or --condition as the initial workbench")
    if args.orders and (args.grading or args.condition):
        parser.error("Choose --orders, --grading or --condition as the initial workbench")
    if args.session and any((args.image, args.physical, args.printed)):
        parser.error("--session reopens exact recorded sources; do not combine with new inputs")
    if (args.physical or args.printed) and not args.image:
        parser.error("--image is required with report inputs")
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QMessageBox

        from .app import Workstation
    except ImportError as exc:
        print(
            f"Missing workstation dependency: {exc}\nInstall with: .\\.venv-analysis\\Scripts\\python.exe -m pip install -r requirements-workstation.txt",
            file=sys.stderr,
        )
        return 3
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("SELBY")
    window = Workstation()
    if args.orders_store:
        window.orders_path = args.orders_store
    window.show()
    result = 0

    def initialize():
        nonlocal result
        try:
            if args.session:
                window.open_session(args.session)
            elif args.image:
                window.open_image(args.image)
                for p in (args.physical, args.printed):
                    if p:
                        window.load_source(p)
            if args.condition:
                window.open_condition()
            if args.grading:
                window.open_grading()
            if args.orders:
                window.open_orders()
            if args.smoke_test:

                def finish():
                    nonlocal result
                    try:
                        if args.screenshot:
                            if args.screenshot.exists():
                                raise FileExistsError(args.screenshot)
                            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                            target = window.condition_dialog if args.condition else window
                            if not target.grab().save(str(args.screenshot)):
                                raise OSError("Could not save screenshot")
                        print(
                            json.dumps(
                                dict(
                                    status="launched",
                                    platform=sys.platform,
                                    image_loaded=window.session is not None,
                                    report_count=len(window.session.reports)
                                    if window.session
                                    else 0,
                                    automatic_acceptance=False,
                                    condition_loaded=hasattr(window, "condition_dialog"),
                                    grading_loaded=hasattr(window, "grading_dialog"),
                                    orders_loaded=hasattr(window, "orders_dialog"),
                                    current_module=window.desktop.current,
                                )
                            )
                        )
                    except Exception as exc:
                        print(str(exc), file=sys.stderr)
                        result = 3
                    window.dirty = False
                    app.quit()

                QTimer.singleShot(600, finish)
        except Exception as exc:
            result = 3
            if args.smoke_test:
                print(str(exc), file=sys.stderr)
                app.quit()
            else:
                QMessageBox.critical(window, "Could not open inspection", str(exc))

    QTimer.singleShot(0, initialize)
    app.exec()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
