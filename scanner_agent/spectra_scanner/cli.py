from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .common import (
    DATA_ROOT,
    AgentError,
    agent_lock,
    confined_data_dir,
    environment,
    identifier,
    utc_now,
    write_json_new,
)
from .config import load_config
from .exports import FolderImporter
from .storage import ArtifactStore
from .supervisor import supervise

SUCCESS = {"devices_listed", "discovered", "acquired", "imported", "watch_finished"}


def save_report(root: Path, report: dict[str, Any]) -> Path:
    folder = root / "reports"
    if not folder.resolve().is_relative_to(root.resolve()):
        raise AgentError("invalid_path", "Reports directory must not redirect outside S1 storage")
    path = folder / (identifier() + ".json")
    write_json_new(path, report)
    return path


def watch(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    importer = FolderImporter(
        args.inbox, ArtifactStore(root, args.configuration), args.stable_seconds
    )
    counts: Counter[str] = Counter()
    started = time.monotonic()
    report = {
        "schema_version": 1,
        "operation": "watch_exports",
        "started_at_utc": utc_now(),
        "stable_seconds": args.stable_seconds,
        "requested_configuration": args.configuration,
        **environment(),
    }
    try:
        while True:
            events = importer.poll(time.monotonic())
            for event in events:
                counts[event["status"]] += 1
                if event.get("quality_control", {}).get("status") == "fail":
                    counts["quality_failed"] += 1
                event_report = {
                    "schema_version": 1,
                    "operation": "folder_import",
                    "timestamp_utc": utc_now(),
                    **event,
                }
                path = save_report(root, event_report)
                print(json.dumps({"event": event["status"], "report": str(path)}), flush=True)
            elapsed = time.monotonic() - started
            if args.once and elapsed >= args.stable_seconds + args.poll_seconds:
                break
            if args.duration is not None and elapsed >= args.duration:
                break
            time.sleep(args.poll_seconds)
        report["status"] = (
            "imported" if counts["stored"] or counts["duplicate"] else "no_stable_files"
        )
        if counts["quality_failed"]:
            report["status"] = "imported_with_qc_failures"
    except KeyboardInterrupt:
        report["status"] = "watch_finished"
        report["stop_reason"] = "operator_interrupt"
    report["counts"] = dict(counts)
    report["finished_at_utc"] = utc_now()
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="SPECTRA S1 local scanner experiment. No production integration."
    )
    commands = result.add_subparsers(dest="operation", required=True)
    for operation in ("discover", "acquire", "watch"):
        command = commands.add_parser(operation)
        command.add_argument("--config", type=Path, help="JSON acquisition configuration")
        command.add_argument(
            "--data-dir",
            type=Path,
            default=DATA_ROOT,
            help="Artifact subdirectory beneath scanner_agent/local_data",
        )
        if operation != "watch":
            command.add_argument("--device", help="Exact enumerated TWAIN source name")
            command.add_argument(
                "--dsm", help="Absolute trusted DSM DLL path (must match Python bitness)"
            )
            command.add_argument(
                "--timeout", type=float, default=300 if operation == "acquire" else 60
            )
        if operation == "acquire":
            command.add_argument(
                "--show-ui",
                action="store_true",
                help="Allow Epson UI; actual transferred profile is still checked",
            )
            command.add_argument(
                "--strict-options",
                action="store_true",
                help="Do not scan if any standard option/layout is unverified",
            )
        if operation == "discover":
            command.add_argument(
                "--list-only",
                action="store_true",
                help="Enumerate sources without opening a driver",
            )
        if operation == "watch":
            command.add_argument("--inbox", type=Path, required=True)
            command.add_argument("--stable-seconds", type=float, default=3)
            command.add_argument("--poll-seconds", type=float, default=1)
            duration = command.add_mutually_exclusive_group()
            duration.add_argument("--once", action="store_true")
            duration.add_argument("--duration", type=float)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = DATA_ROOT
    report: dict[str, Any] = {
        "schema_version": 1,
        "operation": args.operation,
        "started_at_utc": utc_now(),
        **environment(),
    }
    try:
        root = confined_data_dir(args.data_dir)
        args.configuration = load_config(args.config)
        if args.operation != "watch" and not 0 < args.timeout <= 1800:
            raise AgentError("invalid_input", "Timeout must be between 0 and 1800 seconds")
        if args.operation == "watch" and (
            not 0 < args.poll_seconds <= 60
            or args.stable_seconds < 1
            or not math.isfinite(args.stable_seconds)
            or (
                args.duration is not None
                and (not math.isfinite(args.duration) or args.duration <= 0)
            )
        ):
            raise AgentError("invalid_input", "Invalid polling, stability or duration interval")
        with agent_lock(DATA_ROOT):
            if args.operation == "watch":
                report = watch(args, root)
            else:
                job = vars(args).copy()
                job.pop("config", None)
                job["data_dir"] = str(root)
                report = supervise(job, args.timeout)
    except KeyboardInterrupt:
        report.update(status="canceled", message="Operator interrupted the command")
    except (AgentError, OSError) as exc:
        report.update(
            status=exc.status if isinstance(exc, AgentError) else "file_error", message=str(exc)
        )
    except Exception as exc:
        report.update(status="agent_error", error_type=type(exc).__name__, message=str(exc))
    report["finished_at_utc"] = utc_now()
    try:
        path = save_report(root, report)
        print(json.dumps({"status": report["status"], "report": str(path)}))
    except (AgentError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "report_error", "message": str(exc), "diagnostic": report}, default=str
            )
        )
        return 1
    if report["status"] in SUCCESS:
        return 0
    if report["status"] == "canceled":
        return 130
    return 3 if report["status"] in {"timeout", "driver_crash"} else 2
