"""Isolated 0.3.0-exp1 fork; frozen detector and downstream contracts stay unchanged."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np

from .controlled_layers import select_layers
from .preprocessing import working_gray


def ordered(points: Any) -> Any:
    points = np.asarray(points, dtype=np.float64)
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    points = points[np.argsort(angles)]
    lengths = np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1)
    shortest = int(np.argmin(lengths))
    opposite = (shortest + 2) % 4
    index = min(
        (shortest, opposite), key=lambda i: tuple(((points[i] + points[(i + 1) % 4]) / 2)[::-1])
    )
    return np.roll(points, -index, axis=0)


def line_fit(points: Any) -> tuple[Any, Any]:
    vx, vy, x, y = np.asarray(
        cv2.fitLine(points.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01)
    ).reshape(-1)
    normal = np.array([-float(vy), float(vx)])
    coefficients = np.array([*normal, -normal @ np.array([x, y])])
    distances = np.abs(points @ coefficients[:2] + coefficients[2])
    return coefficients, distances


def intersection(first: Any, second: Any) -> Any:
    return np.linalg.solve(np.stack((first[:2], second[:2])), -np.array([first[2], second[2]]))


def geometries(
    corners: Any, dpi: Any, shape: tuple[int, ...], config: dict[str, Any]
) -> dict[str, Any]:
    lengths = np.linalg.norm(np.roll(corners, -1, axis=0) - corners, axis=1)
    vectors = np.roll(corners, -1, axis=0) - corners
    unit = vectors / lengths[:, None]
    adjacent = [
        abs(90 - math.degrees(math.acos(float(np.clip(unit[i] @ unit[(i + 1) % 4], -1, 1)))))
        for i in range(4)
    ]
    parallel = [
        math.degrees(math.acos(float(np.clip(abs(unit[i] @ unit[i + 2]), -1, 1)))) for i in range(2)
    ]
    width, height = float((lengths[0] + lengths[2]) / 2), float((lengths[1] + lengths[3]) / 2)
    ratio = width / height
    margin = float(
        min(
            corners[:, 0].min(),
            corners[:, 1].min(),
            shape[1] - 1 - corners[:, 0].max(),
            shape[0] - 1 - corners[:, 1].max(),
        )
    )
    flags = {
        "convex_non_self_intersecting": bool(cv2.isContourConvex(corners.astype(np.float32))),
        "parallel": max(parallel) <= config["maximum_angle_error_degrees"],
        "perpendicular": max(adjacent) <= config["maximum_angle_error_degrees"],
        "aspect_ratio": abs(
            ratio / (config["reference_width_mm"] / config["reference_height_mm"]) - 1
        )
        <= config["aspect_tolerance_fraction"],
        "image_margin": margin >= config["minimum_margin_pixels"],
    }
    valid_dpi = (
        isinstance(dpi, (list, tuple))
        and len(dpi) == 2
        and all(
            isinstance(v, (int, float))
            and not isinstance(v, bool)
            and math.isfinite(v)
            and 50 <= v <= 9600
            for v in dpi
        )
    )
    flags["valid_dpi"] = valid_dpi
    mm = None
    if valid_dpi:
        scaled = corners * np.array([25.4 / dpi[0], 25.4 / dpi[1]])
        mm_lengths = np.linalg.norm(np.roll(scaled, -1, axis=0) - scaled, axis=1)
        mm = {
            "width": float((mm_lengths[0] + mm_lengths[2]) / 2),
            "height": float((mm_lengths[1] + mm_lengths[3]) / 2),
        }
        flags["nominal_dimensions_plausible"] = all(
            abs(mm[key] / config[reference] - 1) <= config["dimension_tolerance_fraction"]
            for key, reference in (
                ("width", "reference_width_mm"),
                ("height", "reference_height_mm"),
            )
        )
    else:
        flags["nominal_dimensions_plausible"] = False
    angle = (math.degrees(math.atan2(vectors[0, 1], vectors[0, 0])) + 90) % 180 - 90
    return {
        "corners_pixels": corners.tolist(),
        "width_pixels": width,
        "height_pixels": height,
        "center_pixels": corners.mean(axis=0).tolist(),
        "angle_degrees_modulo_180": angle,
        "millimeters_from_reported_dpi": mm,
        "aspect_ratio": ratio,
        "minimum_margin_pixels": margin,
        "adjacent_angle_error_degrees": adjacent,
        "opposite_parallel_error_degrees": parallel,
        "validation": flags,
    }


def fit_candidate(
    contour: Any,
    edges: Any,
    rgb: Any,
    dpi: Any,
    config: dict[str, Any],
    layer_selector: Callable[..., Any] = select_layers,
) -> tuple[dict[str, Any], Any, Any]:
    original_gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    working = working_gray(rgb, config["preprocessing"])
    seed = ordered(cv2.boxPoints(cv2.minAreaRect(contour)))
    # minAreaRect seeds search strips only; none of its corners are final evidence.
    ys, xs = np.nonzero(edges)
    edge_points = np.column_stack((xs, ys)).astype(np.float64)
    minimum = min(np.linalg.norm(np.roll(seed, -1, axis=0) - seed, axis=1))
    band = max(3.0, minimum * config["side_search_fraction"])
    sides, accepted, coefficients = [], [], []
    used = np.zeros(len(edge_points), dtype=bool)
    for index in range(4):
        start, end = seed[index], seed[(index + 1) % 4]
        vector = end - start
        length = np.linalg.norm(vector)
        direction = vector / length
        normal = np.array([-direction[1], direction[0]])
        relative = edge_points - start
        t, offset = relative @ direction / length, relative @ normal
        exclusion = config["corner_exclusion_fraction"]
        select = (t >= exclusion) & (t <= 1 - exclusion) & (np.abs(offset) <= band)
        selected = edge_points[select]
        if len(selected) < 20:
            return (
                {"status": "failure", "reason": "insufficient_straight_side_points", "side": index},
                np.empty((0, 2)),
                edge_points,
            )
        layer_evidence, support, support_indexes = layer_selector(
            selected,
            np.flatnonzero(select),
            offset[select],
            start,
            end,
            band,
            original_gray,
            working,
            config,
            line_fit,
        )
        if not len(support):
            return (
                {"status": "failure", "reason": layer_evidence["reason"], "side": index},
                np.empty((0, 2)),
                edge_points,
            )
        selected_layer = next(
            layer for layer in layer_evidence["candidate_layers"] if layer["selected"]
        )
        line = np.asarray(selected_layer["line_abc"])
        sides.append(
            {
                "index": index,
                "line_abc": line.tolist(),
                "support_count": len(support),
                "candidate_count": len(selected),
                "rms_pixels": selected_layer["rms_pixels"],
                "p95_residual_pixels": selected_layer["p95_residual_pixels"],
                "coverage": selected_layer["coverage"],
                "ambiguous_parallel_edge": bool(layer_evidence["ambiguity_reasons"]),
                **layer_evidence,
            }
        )
        coefficients.append(line)
        accepted.append(support)
        used[support_indexes] = True
    try:
        corners = np.array(
            [intersection(coefficients[(i - 1) % 4], coefficients[i]) for i in range(4)]
        )
    except np.linalg.LinAlgError:
        return (
            {"status": "failure", "reason": "parallel_adjacent_fits"},
            np.concatenate(accepted),
            edge_points[~used],
        )
    if not np.isfinite(corners).all() or np.max(np.abs(corners)) > 1e6:
        return (
            {"status": "failure", "reason": "invalid_intersections"},
            np.concatenate(accepted),
            edge_points[~used],
        )
    if (
        np.min(np.linalg.norm(np.roll(corners, -1, axis=0) - corners, axis=1)) <= 1
        or abs(cv2.contourArea(corners.astype(np.float32))) < 1
    ):
        return (
            {"status": "failure", "reason": "degenerate_quadrilateral"},
            np.concatenate(accepted),
            edge_points[~used],
        )
    geometry = geometries(corners, dpi, rgb.shape, config)
    flags = geometry["validation"]
    flags.update(
        exactly_four_fitted_sides=True,
        side_residuals=all(s["rms_pixels"] <= config["maximum_rms_pixels"] for s in sides),
        side_support=all(s["coverage"] >= config["minimum_side_coverage"] for s in sides),
        unambiguous_side_layers=not any(s["ambiguous_parallel_edge"] for s in sides),
    )
    score = min(s["coverage"] for s in sides) * math.exp(
        -max(s["rms_pixels"] for s in sides) / config["maximum_rms_pixels"]
    )
    return (
        {
            "status": "success" if all(flags.values()) else "review_required",
            "sides": sides,
            "geometry": geometry,
            "confidence": {"heuristic_support_score": score, "calibrated_probability": False},
            "flags_requiring_review": [k for k, v in flags.items() if not v],
        },
        np.concatenate(accepted),
        edge_points[~used],
    )


def detect(
    rgb: Any,
    dpi: Any,
    config: dict[str, Any],
    *,
    layer_selector: Callable[..., Any] = select_layers,
) -> tuple[dict[str, Any], Any, Any, Any]:
    gray = working_gray(rgb, config["preprocessing"])
    threshold, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    minimum = rgb.shape[0] * rgb.shape[1] * config["minimum_candidate_area_fraction"]
    candidates = sorted(
        (c for c in contours if cv2.contourArea(c) >= minimum), key=cv2.contourArea, reverse=True
    )
    edges = cv2.Canny(gray, config["canny_low"], config["canny_high"])
    if not candidates:
        return (
            {"status": "failure", "reason": "no_candidate_boundary", "candidate_count": 0},
            gray,
            np.empty((0, 2)),
            np.column_stack(np.nonzero(edges)[::-1]),
        )
    report, accepted, rejected = fit_candidate(
        candidates[0], edges, rgb, dpi, config, layer_selector
    )
    report["candidate_count"] = len(candidates)
    report["otsu_threshold"] = threshold
    if (
        len(candidates) > 1
        and cv2.contourArea(candidates[1]) / cv2.contourArea(candidates[0])
        >= config["ambiguity_area_ratio"]
    ):
        report["status"] = "review_required"
        report.setdefault("flags_requiring_review", []).append("multiple_comparable_candidates")
    return report, gray, accepted, rejected
