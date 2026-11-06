from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from spectra_centering.detector import axes
from spectra_centering.inputs import finite_array
from spectra_scanner.common import AgentError


def line(value: Any) -> Any:
    result = finite_array(value, (3,), "line_abc")
    length = np.hypot(result[0], result[1])
    if length < 1e-10:
        raise AgentError("invalid_line", "Degenerate normal")
    result = result / length
    if result[np.argmax(np.abs(result[:2]))] < 0:
        result = -result
    return result


def points_on_reference(corners: Any, index: int, reference: Any, ts: Any) -> Any:
    _, normal, _ = axes(corners, index)
    origins = corners[index] + ts[:, None] * (corners[(index + 1) % 4] - corners[index])
    denominator = np.dot(reference[:2], normal)
    if abs(denominator) < 0.1:
        raise AgentError(
            "invalid_reference_orientation", "Reference does not correspond to its physical side"
        )
    return origins - ((origins @ reference[:2] + reference[2]) / denominator)[:, None] * normal


def displacement(
    corners: Any, index: int, reference: Any, candidate: Any, ts: Any
) -> tuple[Any, Any, Any, Any]:
    reference, candidate = line(reference), line(candidate)
    _, inward, _ = axes(corners, index)
    normal = reference[:2].copy()
    if np.dot(normal, inward) < 0:
        normal = -normal
    denominator = np.dot(candidate[:2], normal)
    if abs(denominator) < 0.1:
        raise AgentError(
            "incompatible_lines", "Near-parallel comparison rays cannot intersect candidate safely"
        )
    origins = points_on_reference(corners, index, reference, ts)
    signed = -(origins @ candidate[:2] + candidate[2]) / denominator
    return signed, origins, origins + signed[:, None] * normal, normal


def quad(lines: list[Any], physical: Any) -> Any:
    result = []
    normalized = [line(value) for value in lines]
    for i in range(4):
        pair = np.array([normalized[(i - 1) % 4], normalized[i]])
        if abs(np.linalg.det(pair[:, :2])) < 0.01:
            raise AgentError("invalid_reference_geometry", "Unstable intersections")
        result.append(np.linalg.solve(pair[:, :2], -pair[:, 2]))
    corners = np.asarray(result)
    if (
        not cv2.isContourConvex(corners.astype(np.float32))
        or cv2.contourArea(corners.astype(np.float32), oriented=True) <= 0
    ):
        raise AgentError("invalid_reference_geometry", "Nonconvex or crossed quadrilateral")
    if any(
        cv2.pointPolygonTest(physical.astype(np.float32), tuple(map(float, p)), False) <= 0
        for p in corners
    ):
        raise AgentError(
            "invalid_reference_geometry", "Printed frame must be inside physical contour"
        )
    return corners


def supported_span(
    corners: Any, index: int, reference: Any, candidate: dict[str, Any], configured: list[float]
) -> list[float]:
    points = np.asarray(candidate.get("support_points_pixels"), dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2 or not np.isfinite(points).all():
        raise AgentError("missing_candidate_support", "Cannot establish candidate evaluation span")
    edge = corners[(index + 1) % 4] - corners[index]
    fractions = (points - corners[index]) @ edge / np.dot(edge, edge)
    lo, hi = max(float(fractions.min()), configured[0]), min(float(fractions.max()), configured[1])
    _, _, projected, _ = displacement(
        corners, index, reference, candidate["line_abc"], np.array([0.0, 1.0])
    )
    projected_t = (projected - corners[index]) @ edge / np.dot(edge, edge)
    slope = projected_t[1] - projected_t[0]
    if slope <= 1e-8:
        raise AgentError("invalid_support_span", "Reversed or degenerate correspondence")
    return [(lo - projected_t[0]) / slope, (hi - projected_t[0]) / slope]


def dpi_scale(dpi: Any, normal: Any) -> float | None:
    if (
        not isinstance(dpi, list)
        or len(dpi) != 2
        or not all(type(v) in (int, float) and np.isfinite(v) and v > 0 for v in dpi)
    ):
        return None
    return float(np.linalg.norm(normal * 25.4 / np.array(dpi)))
