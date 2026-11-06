"""Disposable process boundary for native DSM/driver code. Not a server."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import AgentError, confined_data_dir, environment, utc_now, write_json_new
from .twain_driver import classify_error, run_job


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    report = {"schema_version": 1, "started_at_utc": utc_now(), **environment()}
    sequence = 0

    def checkpoint() -> None:
        nonlocal sequence
        sequence += 1
        write_json_new(args.result.parent / f"checkpoint_{sequence:04}.json", report)

    try:
        job = json.load(sys.stdin)
        if not isinstance(job, dict) or job.get("operation") not in {"discover", "acquire"}:
            raise AgentError(
                "invalid_input", "Worker accepts only discovery or explicit acquisition"
            )
        job["data_dir"] = str(confined_data_dir(Path(job["data_dir"])))
        report["operation"] = job["operation"]
        run_job(job, report, checkpoint)
    except KeyboardInterrupt:
        report.update(status="canceled", message="Operator canceled acquisition")
    except Exception as exc:
        status = classify_error(exc)
        message = str(exc) or {
            "device_absent": "The source is unavailable/offline. Check USB/power, close other scan apps and retry.",
            "busy": "The device is in use. Close Epson Scan 2/other scanner clients and retry.",
            "canceled": "Acquisition was canceled; no completed original is asserted.",
        }.get(status, "TWAIN operation failed; inspect error_type and the driver log")
        report.update(status=status, error_type=type(exc).__name__, message=message)
        report.setdefault("capabilities_status", "unavailable_" + status)
    finally:
        report["finished_at_utc"] = utc_now()
        write_json_new(args.result, report)
    return 0  # Supervisor evaluates the structured status, not an opaque native exception.


if __name__ == "__main__":
    raise SystemExit(main())
