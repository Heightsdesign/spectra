"""Strict read-only adapter for frozen per-image S2.1 reports; does not run S2.1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from spectra_scanner.common import AgentError
from spectra_scanner.comparison import input_evidence
from spectra_scanner.storage import sha256_file


def finite_array(value: Any, shape: tuple[int, ...], name: str) -> Any:
    try:
        result = np.asarray(value, dtype=float)
    except (ValueError, TypeError) as exc:
        raise AgentError("invalid_geometry", f"Invalid {name}") from exc
    if result.shape != shape or not np.isfinite(result).all():
        raise AgentError("invalid_geometry", f"Invalid finite shape for {name}")
    return result


def reject_constant(value: str) -> None:
    raise ValueError(f"Nonfinite JSON constant {value}")


def read_inputs(image: Path, boundary_report: Path) -> tuple[Any, dict[str, Any]]:
    report_hash = sha256_file(boundary_report)
    try:
        upstream = json.loads(
            boundary_report.read_text(encoding="utf-8-sig"), parse_constant=reject_constant
        )
    except (OSError, ValueError) as exc:
        raise AgentError("invalid_boundary_report", str(exc)) from exc
    if (
        not isinstance(upstream, dict)
        or type(upstream.get("schema_version")) is not int
        or upstream.get("schema_version") != 1
        or upstream.get("kind") != "single_image"
        or upstream.get("algorithm_version") != "0.2.0"
    ):
        raise AgentError(
            "incompatible_boundary_report",
            "Requires per-image S2.1 schema 1, algorithm 0.2.0; index/repeat summaries are not accepted",
        )
    detection = upstream.get("baseline")
    if (
        upstream.get("status") not in {"success", "review_required"}
        or not isinstance(detection, dict)
        or detection.get("status") not in {"success", "review_required"}
    ):
        raise AgentError(
            "failed_upstream_analysis", "Upstream baseline must contain usable geometry"
        )
    if upstream.get("original_hash_verified_after_analysis") is not True:
        raise AgentError(
            "unverified_upstream_original", "S2.1 did not verify the original after analysis"
        )
    source = input_evidence(image)
    reported_source = upstream.get("source", {})
    if not isinstance(reported_source, dict) or reported_source.get("sha256") != source["sha256"]:
        raise AgentError(
            "cross_card_or_changed_input", "Original SHA-256 does not match S2.1 report"
        )
    frame = source["image"]["frames"][0]
    reported_frames = reported_source.get("image", {}).get("frames", [])
    if len(reported_frames) != 1 or any(
        reported_frames[0].get(key) != frame[key] for key in ("width", "height", "mode")
    ):
        raise AgentError("incompatible_image_geometry", "S2.1 image dimensions/channels disagree")
    geometry = detection.get("geometry", {})
    if not isinstance(geometry, dict):
        raise AgentError("invalid_geometry", "Missing geometry object")
    corners = finite_array(geometry.get("corners_pixels"), (4, 2), "physical corners")
    if (
        not cv2.isContourConvex(corners.astype(np.float32))
        or cv2.contourArea(corners.astype(np.float32), oriented=True) <= 100
    ):
        raise AgentError(
            "invalid_geometry",
            "Physical quadrilateral must be convex, nondegenerate and clockwise in image coordinates",
        )
    if (
        (corners < 0).any()
        or (corners[:, 0] >= frame["width"]).any()
        or (corners[:, 1] >= frame["height"]).any()
    ):
        raise AgentError("invalid_geometry", "Physical quadrilateral is outside the original")
    vectors = np.roll(corners, -1, axis=0) - corners
    lengths = np.linalg.norm(vectors, axis=1)
    if (lengths < 20).any():
        raise AgentError(
            "invalid_geometry", "Physical sides too short for this sampling experiment"
        )
    directions = vectors / lengths[:, None]
    if any(abs(np.dot(directions[i], directions[(i + 1) % 4])) > 0.18 for i in range(4)):
        raise AgentError("invalid_geometry", "Physical sides are not approximately perpendicular")
    sides = detection.get("sides")
    if (
        not isinstance(sides, list)
        or len(sides) != 4
        or any(not isinstance(s, dict) or s.get("index") != i for i, s in enumerate(sides))
    ):
        raise AgentError("invalid_geometry", "Requires four ordered selected physical sides")
    coefficients = []
    for index, side in enumerate(sides):
        line = finite_array(side.get("line_abc"), (3,), "physical line")
        norm = np.linalg.norm(line[:2])
        if norm < 1e-8:
            raise AgentError("invalid_geometry", "Degenerate physical side normal")
        line = line / norm
        if np.max(np.abs(corners[[index, (index + 1) % 4]] @ line[:2] + line[2])) > 0.1:
            raise AgentError(
                "inconsistent_geometry", "Selected physical lines and corner intersections disagree"
            )
        coefficients.append(line.tolist())
    validation = geometry.get("validation", {})
    required = (
        "convex_non_self_intersecting",
        "parallel",
        "perpendicular",
        "image_margin",
        "exactly_four_fitted_sides",
        "side_residuals",
        "side_support",
    )
    if not isinstance(validation, dict) or any(
        validation.get(flag) is not True for flag in required
    ):
        raise AgentError(
            "invalid_upstream_geometry",
            "Upstream pixel-geometry checks must pass; ambiguity alone may propagate for review",
        )
    with Image.open(image) as original:
        rgb = np.asarray(original).copy()
    if sha256_file(boundary_report) != report_hash:
        raise AgentError("source_changed", "Boundary report changed while reading")
    flags = []
    if upstream["status"] == "review_required" or detection["status"] == "review_required":
        flags.append("upstream_review_required")
    if any(side.get("ambiguous_parallel_edge") is True for side in sides):
        flags.append("upstream_physical_side_ambiguity")
    return rgb, {
        "source": source,
        "boundary_report": {
            "path": str(boundary_report.resolve()),
            "sha256": report_hash,
            "schema_version": 1,
            "algorithm_version": "0.2.0",
            "status": upstream["status"],
            "baseline_status": detection["status"],
            "selected_variant": "baseline",
            "review_flags": detection.get("flags_requiring_review", []),
            "side_evidence": sides,
        },
        "physical_corners_pixels": corners.tolist(),
        "physical_lines_abc": coefficients,
        "dpi": upstream.get("dpi"),
        "dpi_evidence": upstream.get("dpi_evidence"),
        "quality_flags": flags,
    }
