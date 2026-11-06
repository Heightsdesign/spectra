from __future__ import annotations

import argparse
import json
from pathlib import Path

from spectra_scanner.common import (
    DATA_ROOT,
    AgentError,
    confined_data_dir,
    identifier,
    utc_now,
    write_json_new,
)

from . import __version__
from .analysis import analyze
from .config import load
from .repeatability import repeatability


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S2.1 existing-image geometry only; never scans")
    parser.add_argument("operation", choices=("analyze", "repeat"))
    parser.add_argument("images", type=Path, nargs="+")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--dpi", type=float, help="Explicit operator DPI override, not calibration")
    parser.add_argument("--compare-preprocessing", action="store_true")
    args = parser.parse_args(argv)
    try:
        if (args.operation == "analyze" and len(args.images) != 1) or (
            args.operation == "repeat" and len(args.images) < 3
        ):
            raise AgentError(
                "invalid_input", "analyze takes one image; repeat requires at least three"
            )
        config = load(args.config)
        output_root = confined_data_dir(DATA_ROOT / "s2_1")
        output_root.mkdir(parents=True, exist_ok=True)
        output = output_root / identifier()
        output.mkdir()
        analyses = [
            analyze(path, output / f"scan-{index:03}", config, args.dpi, args.compare_preprocessing)
            for index, path in enumerate(args.images)
        ]
        if args.operation == "repeat":
            result = repeatability(analyses)
            result.update(
                schema_version=1,
                kind="repeatability",
                algorithm_version=__version__,
                configuration=config,
                source_sha256=[a.get("source", {}).get("sha256") for a in analyses],
                physical_scan_performed=False,
                created_at_utc=utc_now(),
                analyses=[f"scan-{i:03}/report.json" for i in range(len(analyses))],
            )
            # An analysis-level preprocessing disagreement is not silently discarded.
            if result["status"] == "success" and any(a["status"] != "success" for a in analyses):
                result["status"] = "review_required"
        else:
            result = {
                "schema_version": 1,
                "kind": "analysis_index",
                "status": analyses[0]["status"],
                "analysis": "scan-000/report.json",
            }
        result["analysis_id"] = output.name
        write_json_new(output / "report.json", result)
        print(json.dumps({"status": result["status"], "report": str(output / "report.json")}))
        return {"success": 0, "review_required": 2}.get(result["status"], 3)
    except (AgentError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "failure",
                    "reason": getattr(exc, "status", "analysis_error"),
                    "message": str(exc),
                }
            )
        )
        return 3
