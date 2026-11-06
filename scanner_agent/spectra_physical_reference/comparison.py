from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from spectra_reference.geometry import line
from spectra_scanner.storage import sha256_file

from .model import intersections, load_report, safe_validate


def compare(
    reference: dict[str, Any], identity: dict[str, Any], paths: list[Path]
) -> dict[str, Any]:
    validated = safe_validate(reference, identity)
    rows = []
    for path in paths:
        report = load_report(path, identity)
        detection = report["baseline"]
        sides = detection.get("sides", [])
        row: dict[str, Any] = {
            "report": str(path.resolve()),
            "report_sha256": sha256_file(path),
            "algorithm_version": report["algorithm_version"],
            "phase": report.get("experimental_phase"),
            "detector_status_unchanged": detection.get("status"),
            "detector_validation": detection.get("geometry", {}).get("validation"),
            "per_side": [],
            "accuracy_score": None,
        }
        for i, side in enumerate(reference["sides"]):
            result: dict[str, Any] = {
                "index": i,
                "reference_status": side["status"],
                "available": False,
                "uncertainty_pixels": side["uncertainty_pixels"],
            }
            row["per_side"].append(result)
            if side["status"] == "indeterminate" or len(sides) != 4:
                result["reason"] = (
                    "indeterminate_reference"
                    if side["status"] == "indeterminate"
                    else "no_detector_geometry"
                )
                continue
            target = line(sides[i]["line_abc"])
            normal = validated["lines"][i][:2].copy()
            inward = np.array(((0, 1), (-1, 0), (0, -1), (1, 0))[i])
            if normal @ inward < 0:
                normal = -normal
            denominator = target[:2] @ normal
            if abs(denominator) < 0.1:
                result["reason"] = "incompatible_detector_side_orientation"
                continue
            a, b = np.asarray(side["endpoints"])
            positions = a + np.linspace(0, 1, 101)[:, None] * (b - a)
            signed = -(positions @ target[:2] + target[2]) / denominator
            result.update(
                available=True,
                signed_normal_displacement_pixels=signed.tolist(),
                sample_points_pixels=positions.tolist(),
                start_middle_end_pixels=signed[[0, 50, 100]].tolist(),
                mean_absolute_pixels=float(np.abs(signed).mean()),
                maximum_absolute_pixels=float(np.abs(signed).max()),
                eligible_for_certain_reference_agreement=side["status"] == "certain",
                interpretation="descriptive agreement; no calibrated accuracy claim",
            )
            if side["status"] == "uncertain":
                width = side["uncertainty_pixels"]
                result.update(
                    distance_beyond_uncertainty_band_pixels=np.maximum(
                        np.abs(signed) - width, 0
                    ).tolist(),
                    reason="uncertain_reference_excluded_from_definitive_accuracy",
                )
        corners = validated["corners_pixels"]
        row["corners"] = []
        try:
            predicted = (
                intersections([line(s["line_abc"]) for s in sides], identity["dimensions"])
                if len(sides) == 4
                else None
            )
        except ValueError as exc:
            predicted = None
            row["detector_contour_error"] = str(exc)
        for i, corner in enumerate(corners):
            certain = all(reference["sides"][j]["status"] == "certain" for j in ((i - 1) % 4, i))
            result = {
                "index": i,
                "available": corner is not None and predicted is not None,
                "adjacent_references_certain": certain,
                "extrapolated_line_intersection": True,
            }
            if corner is not None and predicted is not None:
                delta = np.asarray(predicted[i]) - corner
                result.update(
                    delta_xy_pixels=delta.tolist(), distance_pixels=float(np.linalg.norm(delta))
                )
            row["corners"].append(result)
        row["whole_contour"] = {
            "available": all(p is not None for p in corners) and predicted is not None,
            "reference_complete_and_certain": validated["complete_certain_reference"],
        }
        if row["whole_contour"]["available"]:
            for name, points in (("reference", corners), ("detector", predicted)):
                polygon = np.asarray(points, dtype=np.float32)
                lengths = np.linalg.norm(np.roll(polygon, -1, axis=0) - polygon, axis=1)
                row["whole_contour"][name] = {
                    "corners_pixels": points,
                    "convex": bool(cv2.isContourConvex(polygon)),
                    "area_pixels_squared": float(cv2.contourArea(polygon)),
                    "perimeter_pixels": float(lengths.sum()),
                    "side_lengths_pixels": lengths.tolist(),
                }
                directions = (np.roll(polygon, -1, axis=0) - polygon) / lengths[:, None]
                row["whole_contour"][name]["adjacent_angle_error_degrees"] = [
                    float(
                        abs(
                            90
                            - np.degrees(
                                np.arccos(np.clip(directions[i] @ directions[(i + 1) % 4], -1, 1))
                            )
                        )
                    )
                    for i in range(4)
                ]
                row["whole_contour"][name]["opposite_parallel_error_degrees"] = [
                    float(
                        np.degrees(
                            np.arccos(np.clip(abs(directions[i] @ directions[i + 2]), -1, 1))
                        )
                    )
                    for i in range(2)
                ]
        rows.append(row)
    return {
        "schema_version": 1,
        "kind": "physical_boundary_reference_comparison",
        "image": identity,
        "annotation_id": reference["annotation_id"],
        "annotation_version": reference["annotation_version"],
        "results": rows,
        "reference_complete_and_certain": validated["complete_certain_reference"],
        "accuracy_score": None,
        "physical_accuracy_verified": False,
        "interpretation": "Human-reference agreement only. Uncertain/indeterminate sides preclude definitive accuracy. No status or downstream gate is changed.",
    }
