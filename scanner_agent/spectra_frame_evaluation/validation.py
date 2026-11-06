"""Explicit local report-pair regression runner. Never scans or overwrites reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from spectra_centering.analysis import analyze as baseline_analyze
from spectra_scanner.common import DATA_ROOT, confined_data_dir, identifier, write_json_new

from .analysis import analyze, configuration


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare S2.2a/b for explicit local S2.1 reports")
    parser.add_argument("reports", type=Path, nargs="+")
    args = parser.parse_args()
    output = confined_data_dir(DATA_ROOT / "s2_2b_validation" / identifier())
    output.mkdir(parents=True, exist_ok=False)
    config = configuration({})
    rows = []
    for i, path in enumerate(args.reports):
        upstream = confined_data_dir(path)
        source = json.loads(upstream.read_text(encoding="utf-8-sig"))["source"]
        image = confined_data_dir(Path(source["path"]))
        baseline = baseline_analyze(
            image, upstream, output / f"pair-{i:03}-a", config["candidate_generation"]
        )
        result = analyze(image, upstream, output / f"pair-{i:03}-b", config)
        evaluation = result.get("frame_evaluation", {})
        rows.append(
            {
                "image": str(image),
                "boundary_report": str(upstream),
                "sha256": source["sha256"],
                "s2_2a_status": baseline["status"],
                "s2_2b_status": result["status"],
                "valid_hypotheses": evaluation.get("valid_count"),
                "search_truncated": evaluation.get("search_truncated"),
                "provisional_candidates": sum(
                    c["retention"] == "provisional"
                    for s in result.get("sides", [])
                    for c in s["candidates"]
                ),
                "hashes_verified": baseline.get("input_hashes_verified_after_analysis") is True
                and result["input_hashes_verified_after_analysis"],
                "s2_2a_report": f"pair-{i:03}-a/report.json",
                "s2_2b_report": f"pair-{i:03}-b/report.json",
            }
        )
        print(json.dumps(rows[-1]))
    write_json_new(
        output / "comparison.json",
        {"pairs": rows, "physical_scan_performed": False, "configuration": config},
    )
    print(json.dumps({"comparison": str(output / "comparison.json"), "count": len(rows)}))
    return (
        3
        if any(
            row["s2_2a_status"] == "analysis_failed"
            or row["s2_2b_status"] == "analysis_failed"
            or not row["hashes_verified"]
            for row in rows
        )
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
