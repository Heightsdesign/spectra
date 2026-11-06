"""Read-only S2.2b CLI; no acquisition or production integration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from spectra_frame_evaluation.analysis import analyze, load
from spectra_scanner.common import DATA_ROOT, AgentError, confined_data_dir, identifier


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S2.2b experimental frame-hypothesis evaluation")
    parser.add_argument("image", type=Path)
    parser.add_argument("boundary_report", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    try:
        config = load(args.config)
        output = confined_data_dir(DATA_ROOT / "s2_2b" / identifier())
        result = analyze(args.image, args.boundary_report, output, config)
        print(json.dumps({"status": result["status"], "report": str(output / "report.json")}))
        return 3 if result["status"] == "analysis_failed" else 2
    except (AgentError, OSError, ValueError) as exc:
        print(json.dumps({"status": "analysis_failed", "error": str(exc)}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
