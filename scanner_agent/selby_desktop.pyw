"""Console-free Windows entry point with visible startup errors."""

import ctypes
import traceback

try:
    from selby_workstation.__main__ import main

    result = main()
    if result:
        ctypes.windll.user32.MessageBoxW(None,
            "SELBY could not start. Check requirements-workstation.txt and the recorded evidence paths.\n"
            "For diagnostic output run .venv-analysis\\Scripts\\python.exe -B selby_workstation.py.",
            "SELBY startup failed", 0x10)
    raise SystemExit(result)
except Exception:
    ctypes.windll.user32.MessageBoxW(None, traceback.format_exc(), "SELBY startup failed", 0x10)
