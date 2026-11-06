"""Conservative straight, approximately uniform traditional-frame hypothesis search.

All sampling and distances remain in original pixels. Scores are evidence, not probabilities.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def axes(corners: Any, index: int) -> tuple[Any, Any, float]:
    vector = corners[(index + 1) % 4] - corners[index]
    tangent = vector / np.linalg.norm(vector)
    normal = np.array([-tangent[1], tangent[0]])
    span = float(np.dot(corners[(index + 2) % 4] - corners[index], normal))
    return tangent, normal, span


def detect(rgb: Any, corners: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    sides = []
    for index, name in enumerate(("top", "right", "bottom", "left")):
        _, normal, span = axes(corners, index)
        fraction = np.linspace(
            config["corner_exclusion_fraction"],
            1 - config["corner_exclusion_fraction"],
            config["profile_count"],
        )
        origins = corners[index] + fraction[:, None] * (corners[(index + 1) % 4] - corners[index])
        distances = np.arange(
            max(2, span * config["search_min_fraction"]), span * config["search_max_fraction"], 1.0
        )
        points = origins[:, None, :] + distances[None, :, None] * normal
        samples = cv2.remap(
            rgb,
            points[:, :, 0].astype(np.float32),
            points[:, :, 1].astype(np.float32),
            cv2.INTER_LINEAR,
        ).astype(float)
        # Four-pixel symmetric RGB transition, independent of brightness polarity.
        strength = np.zeros(samples.shape[:2])
        strength[:, 2:-2] = np.sqrt(np.mean((samples[:, 4:] - samples[:, :-4]) ** 2, axis=2))
        profile = np.median(strength, axis=0)
        profile = np.convolve(profile, [0.25, 0.5, 0.25], mode="same")
        peaks = [
            i
            for i in range(3, len(profile) - 3)
            if profile[i] >= config["minimum_color_transition"]
            and profile[i] >= profile[i - 1]
            and profile[i] > profile[i + 1]
        ]
        retained: list[int] = []
        for peak in sorted(peaks, key=lambda p: -profile[p]):
            if all(abs(peak - p) >= config["candidate_separation_pixels"] for p in retained):
                retained.append(peak)
        truncated = len(retained) > config["maximum_candidates_per_side"]
        candidates = []
        anchor = np.median(samples[:, :3], axis=1)
        border_color = np.median(anchor, axis=0)
        for rank, peak in enumerate(sorted(retained[: config["maximum_candidates_per_side"]])):
            local = np.argmax(strength[:, peak - 2 : peak + 3], axis=1) + peak - 2
            values = strength[np.arange(len(local)), local]
            support = values >= config["minimum_color_transition"]
            selected = points[np.arange(len(local)), local]
            flags = []
            line = None
            rms = None
            angle = None
            if support.sum() >= 4:
                vx, vy, x, y = cv2.fitLine(
                    selected[support].astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01
                ).ravel()
                coefficients = np.array([-vy, vx, vy * x - vx * y], dtype=float)
                residuals = selected @ coefficients[:2] + coefficients[2]
                support &= np.abs(residuals) <= 3
                rms = float(np.sqrt(np.mean(residuals[support] ** 2))) if support.any() else None
                angle = float(
                    np.degrees(np.arccos(np.clip(abs(np.dot(coefficients[:2], normal)), 0, 1)))
                )
                line = coefficients.tolist()
            continuity = float(np.mean(support))
            corridor = samples[:, : max(1, peak - 3)]
            deviation = np.sqrt(np.mean((corridor - anchor[:, None, :]) ** 2, axis=2))
            # Both across-ray and along-ray evidence matter: artwork outside a candidate
            # should not be mistaken for a continuous homogeneous printed outer frame.
            band_deviation = float(
                max(
                    np.percentile(deviation, 90),
                    np.percentile(np.sqrt(np.mean((anchor - border_color) ** 2, axis=1)), 90),
                )
            )
            if continuity < config["minimum_support_fraction"]:
                flags.append("insufficient_continuity")
            if rms is None or rms > config["maximum_fit_rms_pixels"]:
                flags.append("line_residuals")
            if angle is None or angle > config["maximum_angle_difference_degrees"]:
                flags.append("line_orientation")
            if band_deviation > config["maximum_outer_band_color_deviation"]:
                flags.append("heterogeneous_outer_band")
            candidates.append(
                {
                    "id": f"{name}-{rank}",
                    "distance_pixels": float(distances[peak]),
                    "line_abc": line,
                    "transition_rgb_rms": float(profile[peak]),
                    "support_fraction": continuity,
                    "outer_band_deviation_rgb": band_deviation,
                    "fit_rms_pixels": rms,
                    "angle_difference_degrees": angle,
                    "rejection_reasons": flags,
                    "support_points_pixels": selected[support].tolist(),
                    "eligible": not flags,
                }
            )
        eligible = [c for c in candidates if c["eligible"]]
        selected_id = eligible[0]["id"] if len(eligible) == 1 and not truncated else None
        sides.append(
            {
                "index": index,
                "name": name,
                "candidates": candidates,
                "selected_candidate_id": selected_id,
                "ambiguous": len(eligible) > 1 or truncated,
                "candidate_limit_reached": truncated,
                "border_rgb": border_color.tolist(),
                "profile": {
                    "distance_pixels": distances.tolist(),
                    "transition_rgb_rms": profile.tolist(),
                },
            }
        )
    return sides


def measurements(
    corners: Any, sides: list[dict[str, Any]], dpi: Any, config: dict[str, Any]
) -> dict[str, Any]:
    lines = [
        next(c["line_abc"] for c in s["candidates"] if c["id"] == s["selected_candidate_id"])
        for s in sides
    ]
    intersections = []
    for i in range(4):
        pair = np.asarray([lines[(i - 1) % 4], lines[i]])
        if abs(np.linalg.det(pair[:, :2])) < 0.01:
            raise ValueError("Degenerate printed quadrilateral")
        intersections.append(np.linalg.solve(pair[:, :2], -pair[:, 2]))
    quad = np.asarray(intersections)
    if (
        not cv2.isContourConvex(quad.astype(np.float32))
        or cv2.contourArea(quad.astype(np.float32), oriented=True) <= 0
    ):
        raise ValueError("Invalid printed quadrilateral")
    if any(
        cv2.pointPolygonTest(corners.astype(np.float32), tuple(map(float, p)), False) <= 0
        for p in quad
    ):
        raise ValueError("Printed frame must be strictly inside physical quadrilateral")
    valid_dpi = (
        isinstance(dpi, list)
        and len(dpi) == 2
        and all(type(d) in (float, int) and np.isfinite(d) and d > 0 for d in dpi)
    )
    margins = {}
    for i, side in enumerate(sides):
        _, normal, _ = axes(corners, i)
        ts = np.linspace(
            config["corner_exclusion_fraction"],
            1 - config["corner_exclusion_fraction"],
            config["margin_sample_count"],
        )
        origins = corners[i] + ts[:, None] * (corners[(i + 1) % 4] - corners[i])
        line = np.asarray(lines[i])
        distances = -(origins @ line[:2] + line[2]) / np.dot(line[:2], normal)
        if not np.isfinite(distances).all() or (distances <= 0).any():
            raise ValueError("Invalid margin intersections")
        scale = float(np.linalg.norm(normal * 25.4 / np.asarray(dpi))) if valid_dpi else None
        margins[side["name"]] = {
            "sample_positions_pixels": origins.tolist(),
            "distances_pixels": distances.tolist(),
            "mean_pixels": float(np.mean(distances)),
            "min_pixels": float(np.min(distances)),
            "max_pixels": float(np.max(distances)),
            "std_pixels": float(np.std(distances)),
            "mean_mm_from_reported_dpi": float(np.mean(distances) * scale) if scale else None,
        }
    left, right, top, bottom = [
        margins[k]["mean_pixels"] for k in ("left", "right", "top", "bottom")
    ]
    return {
        "printed_corners_pixels": quad.tolist(),
        "margins": margins,
        "centering_percent": {
            "left": 100 * left / (left + right),
            "right": 100 * right / (left + right),
            "top": 100 * top / (top + bottom),
            "bottom": 100 * bottom / (top + bottom),
        },
        "measurement_basis": "Multiple original-pixel rays perpendicular to each physical side; conditional on selected upstream geometry",
    }
