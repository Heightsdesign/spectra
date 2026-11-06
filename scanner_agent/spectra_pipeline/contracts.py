from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from spectra_scanner.common import AgentError
from spectra_scanner.comparison import input_evidence
from spectra_scanner.storage import sha256_file


def read_json(path: Path) -> dict[str, Any]:
    def invalid_constant(value: str) -> None:
        raise ValueError(f"Nonfinite JSON: {value}")

    value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise AgentError("malformed_report", "Expected a JSON object")
    return value


def artifact_paths(report: Path, value: Any) -> list[Path]:
    """Resolve only existing, contained diagnostic artifacts, never arbitrary HTML URLs."""
    result: set[Path] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)
        elif isinstance(item, str) and Path(item).suffix.lower() in {".png", ".json", ".txt"}:
            candidate = (report.parent / item).resolve()
            if not candidate.is_relative_to(report.parent.resolve()):
                raise AgentError("invalid_artifact_path", "Diagnostic escapes its report directory")
            if candidate.is_file():
                result.add(candidate)

    visit(value)
    return sorted(result)


def verify_source(image: Path) -> dict[str, Any]:
    evidence = input_evidence(image)
    if evidence["image"]["format"] != "BMP":
        raise AgentError(
            "unsupported_pipeline_original", "This R&D workflow requires a native original BMP"
        )
    return evidence


def physical_report(path: Path, image: Path) -> tuple[dict[str, Any], list[str]]:
    from spectra_boundary.config import load

    value = read_json(path)
    if (
        type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or value.get("kind") != "single_image"
        or value.get("algorithm_version") != "0.2.0"
    ):
        raise AgentError(
            "incompatible_physical_report",
            "Requires S2.1 schema 1 / algorithm 0.2.0 per-image report",
        )
    if value.get("source", {}).get("sha256") != sha256_file(image):
        raise AgentError("cross_card_report", "S2.1 report does not match this original")
    if value.get("configuration") != load(None):
        raise AgentError(
            "nondefault_analysis_configuration",
            "This first pipeline reuses only frozen default analysis settings",
        )
    status = value.get("status")
    if status not in {"success", "review_required", "failure"}:
        raise AgentError("malformed_report", "Unknown S2.1 status")
    if status == "failure":
        return value, ["s2_1_analysis_failed"]
    if value.get("original_hash_verified_after_analysis") is not True:
        raise AgentError("unverified_original", "S2.1 did not verify its original hash")
    observed = verify_source(image)["image"]["frames"][0]
    reported = value.get("source", {}).get("image", {}).get("frames", [])
    if len(reported) != 1 or any(
        reported[0].get(k) != observed[k] for k in ("width", "height", "mode")
    ):
        raise AgentError(
            "coordinate_mismatch", "Physical report dimensions/channels differ from original"
        )
    baseline = value.get("baseline")
    if not isinstance(baseline, dict) or baseline.get("status") not in {
        "success",
        "review_required",
    }:
        raise AgentError("malformed_report", "Missing usable baseline object")
    geometry = baseline.get("geometry")
    sides = baseline.get("sides")
    if (
        not isinstance(geometry, dict)
        or not isinstance(geometry.get("validation"), dict)
        or not geometry["validation"]
        or not isinstance(sides, list)
        or len(sides) != 4
    ):
        raise AgentError("malformed_report", "Missing four-side geometry validation")
    reasons = []
    if status != "success" or baseline["status"] != "success":
        reasons.append("s2_1_review_required")
    for key, passed in geometry["validation"].items():
        if type(passed) is not bool:
            raise AgentError("malformed_report", "Validation checks must be booleans")
        if not passed:
            reasons.append("invalid_geometry:" + key)
    for i, side in enumerate(sides):
        if (
            side.get("index") != i
            or type(side.get("coverage")) not in (float, int)
            or not 0 <= side["coverage"] <= 1
            or type(side.get("ambiguous_parallel_edge")) is not bool
        ):
            raise AgentError("malformed_report", "Invalid side metrics or ordering")
        if side["ambiguous_parallel_edge"]:
            reasons.append(f"ambiguous_side:{i}")
        if side["coverage"] < value["configuration"]["minimum_side_coverage"]:
            reasons.append(f"insufficient_coverage:{i}")
    if not reasons:
        # Reuse the existing geometry/identity contract. No duplicated detector or
        # alternate tolerance is used. Review-only reports are deliberately stricter.
        from spectra_centering.inputs import read_inputs

        read_inputs(image, path)
    return value, reasons


def frame_report(path: Path, image: Path, physical: Path, stage: str) -> dict[str, Any]:
    value = read_json(path)
    kind = "printed_frame_analysis" if stage == "s2_2a" else "printed_frame_candidate_evaluation"
    if (
        value.get("schema_version") != 1
        or value.get("kind") != kind
        or value.get("algorithm_version") != "0.1.0"
    ):
        raise AgentError("incompatible_frame_report", "Unexpected S2.2 kind/schema/algorithm")
    if value.get("status") not in {"review_required", "not_applicable", "analysis_failed"}:
        raise AgentError("malformed_report", "Unknown frame analysis status")
    if value.get("inputs", {}).get("image_sha256") != sha256_file(image) or value.get(
        "inputs", {}
    ).get("boundary_report_sha256") != sha256_file(physical):
        raise AgentError(
            "cross_card_report", "Frame report original or physical-report hash differs"
        )
    if value["status"] == "analysis_failed":
        return value
    if stage == "s2_2a":
        from spectra_centering.config import load as frame_defaults

        if value.get("configuration") != frame_defaults(None):
            raise AgentError("nondefault_analysis_configuration", "Unexpected S2.2a settings")
    else:
        from spectra_frame_evaluation.analysis import configuration

        if value.get("configuration") != configuration({}):
            raise AgentError("nondefault_analysis_configuration", "Unexpected S2.2b settings")
    if (
        value.get("automatic_acceptance") is not False
        or value.get("input_hashes_verified_after_analysis") is not True
        or not isinstance(value.get("sides"), list)
        or len(value["sides"]) != 4
    ):
        raise AgentError("malformed_report", "Missing verified non-acceptance frame evidence")
    if stage == "s2_2b":
        from spectra_reference.inputs import load_bundle

        load_bundle(image, path)
        evaluation = value.get("frame_evaluation", {})
        if (
            not isinstance(evaluation.get("hypotheses"), list)
            or type(evaluation.get("search_truncated")) is not bool
        ):
            raise AgentError("malformed_report", "Missing hypothesis evidence")
    return value


def resolve_resume(
    path: Path, capture_id: str | None = None
) -> tuple[Path, dict[str, Path], dict[str, Any] | None, list[Path]]:
    """Accept committed S1 metadata/reports, analysis reports or a previous run/checkpoint."""
    path = path.resolve()
    value = read_json(path)
    protected = [path]
    kind = value.get("kind")
    if kind == "rd_pipeline_run":
        if value.get("schema_version") != 1:
            raise AgentError("incompatible_resume", "Unknown pipeline schema")
        for name, digest in value.get("protected_files", {}).items():
            if sha256_file(Path(name)) != digest:
                raise AgentError("resume_integrity_error", f"Changed prior evidence: {name}")
        if not value.get("image", {}).get("path"):
            raise AgentError(
                "resume_requires_original", "No committed original; never automatically reacquire"
            )
        reports = {
            stage: Path(item["report"])
            for stage, item in value["stages"].items()
            if item.get("report") and item.get("status") != "analysis_failed"
        }
        return Path(value["image"]["path"]), reports, value, protected
    if value.get("complete") is True and value.get("original") == "original.bmp":
        image = path.parent / "original.bmp"
        if sha256_file(image) != value.get("sha256"):
            raise AgentError("source_integrity_error", "Acquisition metadata hash mismatch")
        return image, {}, None, protected
    if value.get("operation") == "acquire":
        if value.get("status") != "acquired":
            raise AgentError(
                "resume_requires_original",
                "Acquisition did not complete; no automatic reacquisition",
            )
        captures = value.get("captures", [])
        if capture_id:
            captures = [c for c in captures if c.get("capture_id") == capture_id]
        if len(captures) != 1:
            raise AgentError(
                "ambiguous_acquisition", "Select exactly one committed capture with --capture-id"
            )
        capture = captures[0]
        root = path.parent.parent.resolve()
        image = (root / capture["original"]).resolve()
        if not image.is_relative_to(root) or sha256_file(image) != capture["sha256"]:
            raise AgentError("source_integrity_error", "Acquisition capture path/hash mismatch")
        return image, {}, None, protected
    if kind == "analysis_index":
        child = (path.parent / value["analysis"]).resolve()
        if not child.is_relative_to(path.parent):
            raise AgentError("invalid_report_path", "Index escapes analysis directory")
        image, reports, previous, nested = resolve_resume(child)
        return image, reports, previous, protected + nested
    if kind == "single_image":
        return Path(value["source"]["path"]), {"s2_1": path}, None, protected
    if kind in {"printed_frame_analysis", "printed_frame_candidate_evaluation"}:
        physical = Path(value["inputs"]["boundary_report_path"])
        reports = {"s2_1": physical, "s2_2a" if kind == "printed_frame_analysis" else "s2_2b": path}
        return Path(value["inputs"]["image_path"]), reports, None, protected + [physical]
    raise AgentError(
        "unsupported_resume_report",
        "Use S1 metadata/acquisition, per-image S2.1/S2.2 or pipeline manifest/checkpoint",
    )
