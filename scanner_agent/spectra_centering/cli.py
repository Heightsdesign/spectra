from __future__ import annotations

import argparse
import json
from pathlib import Path

from spectra_scanner.common import DATA_ROOT, AgentError, confined_data_dir, identifier

from .analysis import analyze
from .config import load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="S2.2a traditional printed frame diagnostic; never scans or grades"
    )
    parser.add_argument("image", type=Path)
    parser.add_argument(
        "boundary_report", type=Path, help="Frozen S2.1 0.2.0 per-image scan-000/report.json"
    )
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    try:
        configuration = load(args.config)
        output = confined_data_dir(DATA_ROOT / "s2_2a" / identifier())
        result = analyze(args.image, args.boundary_report, output, configuration)
        print(json.dumps({"status": result["status"], "report": str(output / "report.json")}))
        return 3 if result["status"] == "analysis_failed" else 2
    except (AgentError, OSError, ValueError) as exc:
        print(json.dumps({"status": "analysis_failed", "error": str(exc)}))
        return 3
