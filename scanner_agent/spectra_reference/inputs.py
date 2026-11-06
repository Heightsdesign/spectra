from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from spectra_centering.inputs import read_inputs, reject_constant
from spectra_scanner.common import AgentError, identifier, utc_now
from spectra_scanner.storage import sha256_file

from . import COORDINATES, NAMES, __version__
from .geometry import line, points_on_reference, quad


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise AgentError("invalid_json", "Expected an object")
    return value


def load_bundle(image: Path, report: Path) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    digest = sha256_file(report)
    evaluation = read_json(report)
    if (
        evaluation.get("kind") != "printed_frame_candidate_evaluation"
        or evaluation.get("schema_version") != 1
        or evaluation.get("algorithm_version") != "0.1.0"
        or evaluation.get("status") not in {"review_required", "not_applicable"}
        or evaluation.get("input_hashes_verified_after_analysis") is not True
    ):
        raise AgentError(
            "incompatible_s2_2b_report", "Requires verified S2.2b schema 1 / algorithm 0.1.0 report"
        )
    boundary = Path(evaluation["boundary_report"]["path"])
    rgb, evidence = read_inputs(image, boundary)
    if (
        evidence["source"]["sha256"] != evaluation["source"]["sha256"]
        or evidence["source"]["sha256"] != evaluation["inputs"]["image_sha256"]
        or evidence["boundary_report"]["sha256"] != evaluation["boundary_report"]["sha256"]
    ):
        raise AgentError("source_mismatch", "S2.1/S2.2b/image provenance differs")
    if not np.allclose(
        evidence["physical_corners_pixels"],
        evaluation["physical_corners_pixels"],
        atol=1e-8,
        rtol=0,
    ):
        raise AgentError("coordinate_mismatch", "Physical coordinate geometry differs")
    corners = np.asarray(evidence["physical_corners_pixels"])
    sides = evaluation.get("sides", [])
    if len(sides) != 4 or any(
        side["index"] != i or side["name"] != NAMES[i] for i, side in enumerate(sides)
    ):
        raise AgentError("invalid_candidates", "Four ordered side lists required")
    ids = [c["id"] for side in sides for c in side["candidates"]]
    if len(ids) != len(set(ids)):
        raise AgentError(
            "duplicate_candidate_id",
            "Candidate identifiers must be unique; geometry duplicates are reported separately",
        )
    for side in sides:
        for candidate in side["candidates"]:
            if candidate["line_abc"] is not None:
                line(candidate["line_abc"])
    frames = evaluation["frame_evaluation"]["hypotheses"]
    if len(frames) > 4096 or len({f["id"] for f in frames}) != len(frames):
        raise AgentError("invalid_hypotheses", "Invalid hypothesis identifiers or count")
    lookup = candidate_lookup(evaluation)
    for frame in frames:
        if frame["geometrically_valid"] is True:
            try:
                candidates = resolve_candidates(frame, lookup)
                calculated = quad([c["line_abc"] for c in candidates], corners)
                if "corners_pixels" in frame and not np.allclose(
                    calculated, frame["corners_pixels"], atol=0.1, rtol=0
                ):
                    raise AgentError(
                        "inconsistent_hypothesis_geometry",
                        "Stored corners do not match candidate lines",
                    )
            except (AgentError, ValueError, TypeError) as exc:
                frame["s2_2c_input_exclusion"] = str(exc)
    if sha256_file(report) != digest:
        raise AgentError("source_changed", "S2.2b report changed while reading")
    acquisition = evidence["source"].get("acquisition") or {}
    frame = evidence["source"]["image"]["frames"][0]
    provenance = {
        "image_sha256": evidence["source"]["sha256"],
        "acquisition_id": acquisition.get("capture_id"),
        "image_dimensions": [frame["width"], frame["height"]],
        "dpi": evidence["dpi"],
        "dpi_evidence": evidence.get("dpi_evidence"),
        "s2_1": {
            "path": str(boundary.resolve()),
            "sha256": evidence["boundary_report"]["sha256"],
            "report_id": boundary.parent.parent.name + "/" + boundary.parent.name,
            "algorithm_version": "0.2.0",
            "status": evidence["boundary_report"]["status"],
        },
        "s2_2b": {
            "path": str(report.resolve()),
            "sha256": digest,
            "report_id": report.parent.name,
            "algorithm_version": "0.1.0",
            "candidate_generator_version": evaluation["candidate_generator_version"],
        },
    }
    return rgb, evaluation, provenance


def candidate_lookup(evaluation: dict[str, Any]) -> dict[str, tuple[int, dict[str, Any]]]:
    return {
        c["id"]: (i, c) for i, side in enumerate(evaluation["sides"]) for c in side["candidates"]
    }


def resolve_candidates(frame: dict[str, Any], lookup: dict[str, Any]) -> list[dict[str, Any]]:
    ids = frame.get("candidate_ids", [])
    if len(ids) != 4 or any(cid not in lookup or lookup[cid][0] != i for i, cid in enumerate(ids)):
        raise AgentError("incomplete_hypothesis", "Missing or incorrect side candidate identifiers")
    return [lookup[cid][1] for cid in ids]


def template(provenance: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "outer_printed_frame_reference",
        "tool_version": __version__,
        "coordinate_system": COORDINATES,
        "provenance": provenance,
        "annotation_id": "",
        "annotation_version": identifier(),
        "annotated_at_utc": utc_now(),
        "previous_annotation_sha256": None,
        "layout_status": "ambiguous",
        "operator_notes": "",
        "manual_reference_not_certified_ground_truth": True,
        "sides": [
            {
                "index": i,
                "name": name,
                "status": "unannotated",
                "definition": None,
                "candidate_id": None,
                "line_abc": None,
                "valid_span_fraction": [0.18, 0.82],
                "notes": "",
            }
            for i, name in enumerate(NAMES)
        ],
    }


def validate_annotation(
    value: dict[str, Any], evaluation: dict[str, Any], provenance: dict[str, Any]
) -> list[str]:
    if (
        value.get("schema_version") != 1
        or type(value.get("schema_version")) is not int
        or value.get("kind") != "outer_printed_frame_reference"
        or value.get("coordinate_system") != COORDINATES
        or value.get("tool_version") != __version__
    ):
        raise AgentError("incompatible_annotation", "Incorrect schema, kind or coordinate system")
    if value.get("provenance") != provenance:
        raise AgentError(
            "annotation_source_mismatch",
            "Annotation hashes, dimensions, DPI or report provenance differ",
        )
    if (
        not isinstance(value.get("annotation_id"), str)
        or not value["annotation_id"].strip()
        or len(value["annotation_id"]) > 200
    ):
        raise AgentError(
            "invalid_annotation_identifier",
            "Operator annotation identifier is required (1..200 characters)",
        )
    from datetime import datetime

    timestamp = datetime.fromisoformat(value["annotated_at_utc"].replace("Z", "+00:00"))
    offset = timestamp.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise AgentError("invalid_annotation_timestamp", "UTC annotation timestamp required")
    if not isinstance(value.get("annotation_version"), str) or not value["annotation_version"]:
        raise AgentError("invalid_annotation_version", "Version identifier required")
    parent = value.get("previous_annotation_sha256")
    if parent is not None and (
        not isinstance(parent, str) or re.fullmatch("[a-f0-9]{64}", parent) is None
    ):
        raise AgentError("invalid_parent_hash", "Previous version link must be a SHA-256 or null")
    if value.get("layout_status") not in {"supported", "ambiguous", "unsupported", "absent"}:
        raise AgentError("invalid_layout", "Explicit layout status required")
    if value.get("manual_reference_not_certified_ground_truth") is not True:
        raise AgentError("invalid_reference_claim", "Reference must explicitly remain uncertified")
    sides = value.get("sides", [])
    if len(sides) != 4:
        raise AgentError(
            "invalid_reference_sides",
            "Four side slots are required; missing sides must be explicit",
        )
    flags = []
    if value["layout_status"] != "supported":
        flags.append("reference_layout_" + value["layout_status"])
    corners = np.asarray(evaluation["physical_corners_pixels"])
    lookup = candidate_lookup(evaluation)
    for i, side in enumerate(sides):
        if (
            side.get("index") != i
            or side.get("name") != NAMES[i]
            or side.get("status") not in {"annotated", "ambiguous", "unannotatable", "unannotated"}
        ):
            raise AgentError("invalid_reference_side", "Invalid side identity/status")
        span = np.asarray(side.get("valid_span_fraction"), dtype=float)
        if span.shape != (2,) or not np.isfinite(span).all() or not 0 <= span[0] < span[1] <= 1:
            raise AgentError("invalid_reference_span", "Span must satisfy 0 <= start < end <= 1")
        if side["status"] != "annotated":
            flags.append(NAMES[i] + "_" + side["status"])
        if side.get("line_abc") is None:
            if side["status"] == "annotated":
                raise AgentError("missing_reference_line", "Annotated sides require a line")
            continue
        normalized = line(side["line_abc"])
        points = points_on_reference(corners, i, normalized, np.array([span[0], span[1]]))
        if any(
            cv2.pointPolygonTest(corners.astype(np.float32), tuple(map(float, p)), False) < 0
            for p in points
        ):
            flags.append(NAMES[i] + "_reference_span_outside_physical_contour")
        if side.get("definition") not in {"candidate", "manual"}:
            raise AgentError(
                "invalid_line_definition", "Reference source must be candidate or manual"
            )
        if side["definition"] == "candidate":
            cid = side.get("candidate_id")
            if (
                cid not in lookup
                or lookup[cid][0] != i
                or not np.allclose(normalized, line(lookup[cid][1]["line_abc"]), atol=1e-8, rtol=0)
            ):
                raise AgentError(
                    "candidate_reference_mismatch",
                    "Candidate selection must match that side's fitted line; adjusted lines must be manual",
                )
        elif side.get("candidate_id") is not None:
            raise AgentError(
                "manual_candidate_confusion",
                "Manual lines cannot assert candidate selection; use basis_candidate_id instead",
            )
    if all(s["status"] == "annotated" and s.get("line_abc") is not None for s in sides):
        try:
            quad([s["line_abc"] for s in sides], corners)
        except AgentError:
            flags.append("inconsistent_reference_geometry")
    return flags
