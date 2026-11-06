from __future__ import annotations

import argparse
import json
from pathlib import Path

from spectra_scanner.common import AgentError, identifier, utc_now, write_json_new
from spectra_scanner.storage import sha256_file

from .comparison import compare
from .editor import page
from .model import draft, load_image, load_report, read, safe_validate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline S2.1 physical-boundary R&D references; never grades or scans"
    )
    parser.add_argument("operation", choices=("prepare", "save", "compare"))
    parser.add_argument("image", type=Path)
    parser.add_argument("--report", type=Path, action="append", default=[])
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.operation in {"save", "compare"} and not args.reference:
            raise ValueError("save/compare require a reviewer-exported --reference")
        if args.operation == "compare" and not args.report:
            raise ValueError("compare requires at least one --report")
        inputs = [args.image, *args.report] + ([args.reference] if args.reference else [])
        protected = {str(p.resolve()): sha256_file(p) for p in inputs}
        rgb, identity = load_image(args.image)
        reports = [load_report(p, identity) for p in args.report]
        sources = [{"path": str(p.resolve()), "sha256": sha256_file(p)} for p in args.report]
        reference = draft(identity, sources)
        if args.reference:
            prior = read(args.reference)
            safe_validate(prior, identity)
            if args.operation == "prepare":
                # New review, new identifiers, no inherited human confirmations.
                reference["previous_annotation_sha256"] = sha256_file(args.reference)
                for side, previous in zip(reference["sides"], prior["sides"], strict=True):
                    for key in ("endpoints", "line_abc", "uncertainty_pixels", "notes", "origin"):
                        side[key] = previous[key]
                    side["status"] = previous["status"]
            else:
                reference = prior
        output = (
            args.output
            or Path(__file__).resolve().parents[1]
            / "local_data/physical_reference"
            / args.operation
            / identifier()
        )
        output.mkdir(parents=True, exist_ok=False)
        if args.operation == "prepare":
            page(rgb, reference, reports, output / "annotate.html")
            # A draft is explicitly not a human reference; avoid a reference.json filename.
            write_json_new(output / "unconfirmed-draft.json", reference)
            result = {
                "status": "awaiting_human_review",
                "editor": str((output / "annotate.html").resolve()),
            }
        elif args.operation == "save":
            safe_validate(reference, identity)
            write_json_new(output / "reference.json", reference)
            result = {
                "status": "human_reference_saved",
                "reference": str((output / "reference.json").resolve()),
            }
        else:
            report = compare(reference, identity, args.report)
            report["reference_sha256"] = sha256_file(args.reference)
            write_json_new(output / "comparison.json", report)
            result = {
                "status": "agreement_only",
                "comparison": str((output / "comparison.json").resolve()),
            }
        changed = [p for p, expected in protected.items() if sha256_file(Path(p)) != expected]
        if changed:
            raise ValueError(f"Input changed; discard outputs: {changed}")
        write_json_new(
            output / "integrity.json",
            {
                "created_at_utc": utc_now(),
                "protected_sha256": protected,
                "changed_files": changed,
                "verified": True,
            },
        )
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, TypeError, KeyError, AgentError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 2
