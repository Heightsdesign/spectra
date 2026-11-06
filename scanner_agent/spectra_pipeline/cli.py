from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path

from spectra_scanner.common import AgentError, confined_data_dir

from .dashboard import batch_dashboard
from .engine import ROOT, execute, token


def identifier_argument(value: str) -> str:
    try:
        return token(value)
    except AgentError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="SPECTRA isolated R&D pipeline; never grades or approves. Existing acquisition/detector/editor CLIs are reused."
    )
    operations = result.add_subparsers(dest="operation", required=True)
    for name in ("scan-and-analyze", "analyze-existing", "resume", "dashboard"):
        command = operations.add_parser(name)
        command.add_argument("--batch", default="cross-card", type=identifier_argument)
        if name == "dashboard":
            command.add_argument(
                "--cards", nargs="+", type=identifier_argument, default=["D", "E", "F", "G", "H"]
            )
            continue
        command.add_argument(
            "--card",
            required=True,
            type=identifier_argument,
            help="Operator-supplied physical-card experiment identifier",
        )
        command.add_argument(
            "--timeout", type=float, default=300, help="Per-analysis subprocess timeout, seconds"
        )
        if name == "analyze-existing":
            command.add_argument("--image", type=Path, required=True)
        elif name == "resume":
            command.add_argument(
                "--from",
                type=Path,
                required=True,
                help="S1 metadata/acquisition, S2.1/S2.2 report, or pipeline manifest/checkpoint",
            )
            command.add_argument(
                "--capture-id", help="Required if an acquisition report contains several captures"
            )
        else:
            command.add_argument(
                "--acquire-config",
                type=Path,
                required=True,
                help="Existing verified local acquisition settings; no region is invented",
            )
            command.add_argument(
                "--acquisition-python",
                help="Optional compatible local Python executable for the TWAIN driver",
            )
            command.add_argument("--device")
            command.add_argument("--dsm")
            command.add_argument("--scan-timeout", type=float, default=300)
            command.add_argument("--show-ui", action="store_true")
            command.add_argument("--strict-options", action="store_true")
            command.add_argument(
                "--capture-id", help="Select one capture if the scanner returns several"
            )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.operation == "dashboard":
            output = batch_dashboard(confined_data_dir(ROOT), args.batch, args.cards)
            result = {
                "status": "completed",
                "execution_status": "completed",
                "dashboard": str(output),
                "automatic_acceptance": False,
            }
        else:
            for name in ("timeout", "scan_timeout"):
                value = getattr(args, name, 300)
                if not math.isfinite(value) or not 0 < value <= 1800:
                    raise AgentError("invalid_timeout", "Timeouts must be finite in (0, 1800]")
            if any(importlib.util.find_spec(name) is None for name in ("cv2", "numpy")):
                raise AgentError(
                    "missing_analysis_dependencies",
                    "Use the scanner_agent analysis environment before acquisition or analysis",
                )
            result = execute(vars(args))
        print(json.dumps(result))
        return (
            0
            if result["status"] == "completed"
            else 3
            if result["status"] == "analysis_failed"
            else 2
        )
    except (AgentError, OSError, ValueError, TypeError, KeyError) as exc:
        print(
            json.dumps(
                {
                    "status": "analysis_failed",
                    "automatic_acceptance": False,
                    "error": {
                        "code": getattr(exc, "status", "pipeline_error"),
                        "message": str(exc),
                    },
                }
            )
        )
        return 3
