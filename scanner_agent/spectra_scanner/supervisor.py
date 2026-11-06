from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .common import AGENT_ROOT, environment, identifier, utc_now


def supervise(
    job: dict[str, Any], timeout: float, *, command: list[str] | None = None
) -> dict[str, Any]:
    root = Path(job["data_dir"])
    work = root / ".work"
    if not work.resolve().is_relative_to(root.resolve()):
        from .common import AgentError

        raise AgentError("invalid_path", "Worker directory must remain in S1 storage")
    work.mkdir(parents=True, exist_ok=True)
    base = {
        "schema_version": 1,
        "operation": job["operation"],
        "started_at_utc": utc_now(),
        **environment(),
    }
    folder = work / identifier()
    folder.mkdir()
    result = Path(folder) / "result.json"
    log = Path(folder) / "driver.log"
    args = command or [sys.executable, "-m", "spectra_scanner.worker", "--result", str(result)]
    status = None
    with log.open("xb") as output:
        process = subprocess.Popen(
            args,
            cwd=AGENT_ROOT,
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=output,
            text=True,
            encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        from .windows import process_job

        try:
            containment = process_job(process.pid) if os.name == "nt" else contextlib.nullcontext()
            # The worker waits for stdin; containment is established before any DSM call.
            with containment:
                try:
                    process.communicate(json.dumps(job), timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    status = "timeout"
                except KeyboardInterrupt:
                    process.kill()
                    process.communicate()
                    status = "canceled"
        except Exception:
            if process.poll() is None:
                process.kill()
            process.communicate()
            raise
    with log.open("rb") as recorded:
        recorded.seek(max(0, log.stat().st_size - 8192))
        tail = recorded.read().decode("utf-8", errors="replace")
    base.update(
        finished_at_utc=utc_now(),
        worker_exit_code=process.returncode,
        worker_artifacts=str(folder.relative_to(root)),
    )
    partial: dict[str, Any] = {}
    for checkpoint in sorted(folder.glob("checkpoint_*.json"), reverse=True):
        try:
            partial = json.loads(checkpoint.read_text(encoding="utf-8"))
            break
        except (ValueError, OSError):
            continue
    physical = (
        False
        if job["operation"] == "discover"
        else (
            True if partial.get("physical_scan_performed") is True else "unknown_worker_interrupted"
        )
    )
    if status:
        return {
            **base,
            **partial,
            "status": status,
            "message": "Worker stopped; inspect device and incomplete captures before retrying",
            "driver_log_tail": tail,
            "physical_scan_performed": physical,
        }
    if process.returncode != 0 or not result.is_file():
        return {
            **base,
            **partial,
            "status": "driver_crash",
            "message": "Native worker exited without a valid result",
            "driver_log_tail": tail,
            "physical_scan_performed": physical,
        }
    try:
        value = json.loads(result.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("status"), str):
            raise ValueError("Invalid worker result")
    except (OSError, ValueError) as exc:
        return {**base, "status": "driver_error", "message": str(exc), "driver_log_tail": tail}
    return {**base, **value, "worker_exit_code": process.returncode, "driver_log_tail": tail}
