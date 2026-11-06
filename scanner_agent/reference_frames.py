"""S2.2c offline annotation preparation, immutable version storage and agreement CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from spectra_reference import __version__
from spectra_reference.artifacts import annotation_page, overlays
from spectra_reference.comparison import compare, inventory
from spectra_reference.inputs import load_bundle, read_json, template, validate_annotation
from spectra_scanner.common import (
    DATA_ROOT,
    AgentError,
    confined_data_dir,
    identifier,
    utc_now,
    write_json_new,
)
from spectra_scanner.storage import sha256_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="S2.2c experimental manual reference agreement; never grades or scans"
    )
    parser.add_argument("operation", choices=("prepare", "save", "compare", "inspect"))
    parser.add_argument("image", type=Path)
    parser.add_argument("report", type=Path, help="Existing S2.2b per-image report")
    parser.add_argument(
        "--reference", type=Path, help="Downloaded or previously saved reference JSON"
    )
    args = parser.parse_args(argv)
    try:
        rgb, evaluation, provenance = load_bundle(args.image, args.report)
        source_hashes = {
            args.image: provenance["image_sha256"],
            args.report: provenance["s2_2b"]["sha256"],
            Path(provenance["s2_1"]["path"]): provenance["s2_1"]["sha256"],
        }
        reference = template(provenance)
        if args.reference:
            source_hashes[args.reference] = sha256_file(args.reference)
            reference = read_json(args.reference)
            validate_annotation(reference, evaluation, provenance)
        if args.operation in {"save", "compare"} and not args.reference:
            raise AgentError(
                "missing_reference", "save/compare require an operator-provided --reference"
            )
        output = confined_data_dir(DATA_ROOT / "s2_2c" / args.operation / identifier())
        output.mkdir(parents=True, exist_ok=False)
        if args.operation == "prepare":
            if args.reference:
                reference["previous_annotation_sha256"] = source_hashes[args.reference]
            annotation_page(rgb, evaluation, reference, output / "annotate.html")
            write_json_new(output / "inventory.json", inventory(evaluation))
            result: dict = {
                "status": "awaiting_operator_annotation",
                "interface": str(output / "annotate.html"),
                "inventory": str(output / "inventory.json"),
            }
        elif args.operation == "save":
            write_json_new(output / "reference.json", reference)
            write_json_new(
                output / "storage.json",
                {
                    "imported_at_utc": utc_now(),
                    "download_sha256": source_hashes[args.reference],
                    "reference_sha256": sha256_file(output / "reference.json"),
                    "previous_annotation_sha256": reference.get("previous_annotation_sha256"),
                },
            )
            result = {
                "status": "reference_version_saved",
                "reference": str(output / "reference.json"),
            }
        elif args.operation == "inspect":
            write_json_new(output / "inventory.json", inventory(evaluation))
            result = {"status": "review_required", "inventory": str(output / "inventory.json")}
        else:
            comparison = compare(evaluation, reference, provenance)
            comparison.update(
                schema_version=1,
                kind="manual_frame_reference_comparison",
                algorithm_version=__version__,
                created_at_utc=utc_now(),
                provenance=provenance,
                reference_sha256=source_hashes[args.reference],
                annotation_id=reference["annotation_id"],
                annotation_version=reference["annotation_version"],
                coordinate_system=reference["coordinate_system"],
                physical_scan_performed=False,
            )
            comparison["artifacts"] = overlays(rgb, evaluation, reference, comparison, output)
            result = {"status": "review_required", "report": str(output / "report.json")}
        if any(sha256_file(path) != digest for path, digest in source_hashes.items()):
            raise AgentError(
                "source_changed", "An input changed during processing; outputs must not be used"
            )
        if args.operation == "compare":
            comparison["input_hashes_verified_after_analysis"] = True
            write_json_new(output / "report.json", comparison)
        print(json.dumps(result))
        return 2 if result["status"] == "review_required" else 0
    except (AgentError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(
            json.dumps(
                {
                    "status": "analysis_failed",
                    "error": {"code": getattr(exc, "status", "invalid_input"), "message": str(exc)},
                }
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
