"""Conservative silhouette detection. Coordinates refer to decoded, unrotated pixels."""

from dataclasses import asdict, dataclass, field
from typing import Literal

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator


class BoundaryConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    background_distance: float = Field(default=18, gt=0, le=255)
    max_background_variation: float = Field(default=12, ge=0, le=255)
    min_area_fraction: float = Field(default=0.10, gt=0, lt=1)
    min_ambiguity_area_fraction: float = Field(default=0.01, gt=0, lt=1)
    min_aspect_ratio: float = Field(default=0.58, gt=0, lt=1)
    max_aspect_ratio: float = Field(default=0.86, gt=0, lt=1)
    min_solidity: float = Field(default=0.97, gt=0, le=1)
    min_foreground_fill: float = Field(default=0.90, gt=0, le=1)
    max_polygon_area_error: float = Field(default=0.04, gt=0, lt=1)
    approximation_fraction: float = Field(default=0.015, gt=0, lt=0.05)
    min_corner_angle: float = Field(default=50, gt=0, lt=90)
    max_opposite_side_ratio: float = Field(default=1.8, ge=1)
    border_margin_pixels: int = Field(default=4, ge=1)
    min_side_pixels: float = Field(default=30, gt=0)
    min_sharpness: float = Field(default=20, ge=0)
    max_input_pixels: int = Field(default=24_000_000, gt=0)
    normalized_width: int = Field(default=630, ge=32, le=4096)
    normalized_height: int = Field(default=880, ge=32, le=4096)
    max_transform_condition: float = Field(default=10_000, gt=1)

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.min_aspect_ratio >= self.max_aspect_ratio:
            raise ValueError("Aspect ratio bounds must be increasing")
        if self.max_background_variation >= self.background_distance:
            raise ValueError("Background variation must be below segmentation distance")
        if self.min_ambiguity_area_fraction > self.min_area_fraction:
            raise ValueError("Ambiguity area must not exceed minimum card area")
        return self


@dataclass
class BoundaryResult:
    status: Literal["detected", "rejected"] = "rejected"
    corners: list[list[float]] | None = None
    image_dimensions: dict[str, int] = field(default_factory=dict)
    normalized_dimensions: dict[str, int] | None = None
    metrics: dict[str, float | int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    failure_reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BoundaryDetection:
    result: BoundaryResult
    normalized_image: np.ndarray | None = None
    foreground_mask: np.ndarray | None = None
    overlay: np.ndarray | None = None
    transform: np.ndarray | None = None


def order_corners(points: np.ndarray) -> np.ndarray:
    """Clockwise in image coordinates, starting at the upper-left diagonal.

    This is image-relative, not the semantic orientation of the card artwork.
    At a diamond tie, the uppermost point wins, then the leftmost point.
    """
    points = np.asarray(points, dtype=np.float32)
    if points.shape != (4, 2) or not np.isfinite(points).all() or len(np.unique(points, axis=0)) != 4:
        raise ValueError("Four distinct finite points are required")
    center = points.mean(axis=0)
    ordered = points[np.argsort(np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0]))]
    start = min(range(4), key=lambda i: (float(ordered[i].sum()), float(ordered[i, 1]), float(ordered[i, 0])))
    ordered = np.roll(ordered, -start, axis=0)
    if not cv2.isContourConvex(ordered.reshape(-1, 1, 2)):
        raise ValueError("Corners must form a convex quadrilateral")
    return ordered


def quadrilateral_metrics(points: np.ndarray, image_area: int) -> dict[str, float]:
    edges = np.roll(points, -1, axis=0) - points
    lengths = np.linalg.norm(edges, axis=1)
    angles = []
    for i in range(4):
        a, b = -edges[i - 1], edges[i]
        cosine = np.clip(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)), -1, 1)
        angles.append(float(np.degrees(np.arccos(cosine))))
    width = (lengths[0] + lengths[2]) / 2
    height = (lengths[1] + lengths[3]) / 2
    return {
        "area_fraction": float(cv2.contourArea(points) / image_area),
        "aspect_ratio": float(min(width, height) / max(width, height)),
        "min_side_pixels": float(lengths.min()),
        "min_corner_angle": min(angles),
        "max_corner_angle": max(angles),
        "opposite_side_ratio": float(max(lengths[0] / lengths[2], lengths[2] / lengths[0], lengths[1] / lengths[3], lengths[3] / lengths[1])),
    }


def detect_boundary(image: np.ndarray, config: BoundaryConfig | None = None) -> BoundaryDetection:
    """Analyze an 8-bit BGR image without mutating it or extrapolating corners."""
    config = config or BoundaryConfig()
    result = BoundaryResult(warnings=[
        "Heuristic silhouette detection; physical edges require visual review.",
        "Artwork orientation is not determined; portrait rotation is geometric only.",
    ])
    output = BoundaryDetection(result)

    def reject(reason: str):
        result.failure_reason = reason
        return output

    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) < 32:
        return reject("invalid_image")
    height, width = image.shape[:2]
    result.image_dimensions = {"width": width, "height": height}
    if width * height > config.max_input_pixels:
        return reject("image_too_large")
    output.overlay = image.copy()
    lab = cv2.cvtColor(cv2.GaussianBlur(image, (3, 3), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    # The perimeter is evidence for the acquisition background, not card artwork.
    perimeter = np.concatenate((lab[0], lab[-1], lab[1:-1, 0], lab[1:-1, -1]))
    background = np.median(perimeter, axis=0)
    variation = float(np.percentile(np.linalg.norm(perimeter - background, axis=1), 95))
    result.metrics["background_variation"] = variation
    if variation > config.max_background_variation:
        return reject("nonuniform_background_or_clipping")
    distance = np.linalg.norm(lab - background, axis=2)
    mask = (distance >= config.background_distance).astype(np.uint8) * 255
    output.foreground_mask = mask
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    rejected = []
    significant = 0
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < width * height * config.min_ambiguity_area_fraction:
            continue
        significant += 1
        x, y, w, h = cv2.boundingRect(contour)
        margin = config.border_margin_pixels
        if x < margin or y < margin or x + w > width - margin or y + h > height - margin:
            rejected.append("clipped_boundary")
            continue
        approx = cv2.approxPolyDP(contour, config.approximation_fraction * cv2.arcLength(contour, True), True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            rejected.append("not_convex_quadrilateral")
            continue
        points = order_corners(approx.reshape(4, 2))
        metrics = quadrilateral_metrics(points, width * height)
        metrics["solidity"] = float(area / cv2.contourArea(cv2.convexHull(contour)))
        metrics["polygon_area_error"] = float(abs(cv2.contourArea(points) - area) / area)
        filled = np.zeros((height, width), np.uint8)
        cv2.drawContours(filled, [contour], -1, 255, cv2.FILLED)
        metrics["foreground_fill_fraction"] = float(np.count_nonzero(mask[filled != 0]) / np.count_nonzero(filled))
        result.metrics.update(metrics)
        if not config.min_aspect_ratio <= metrics["aspect_ratio"] <= config.max_aspect_ratio:
            rejected.append("implausible_aspect_ratio")
            continue
        if metrics["area_fraction"] < config.min_area_fraction or metrics["min_side_pixels"] < config.min_side_pixels or metrics["solidity"] < config.min_solidity or metrics["polygon_area_error"] > config.max_polygon_area_error or metrics["min_corner_angle"] < config.min_corner_angle or metrics["max_corner_angle"] > 180 - config.min_corner_angle or metrics["opposite_side_ratio"] > config.max_opposite_side_ratio:
            rejected.append("invalid_geometry")
            continue
        if metrics["foreground_fill_fraction"] < config.min_foreground_fill:
            rejected.append("insufficient_silhouette_support")
            continue
        candidates.append((points, metrics, contour))
    result.metrics["significant_contours"] = significant
    result.metrics["candidate_count"] = len(candidates)
    # Never select an arbitrary largest object when another substantial silhouette exists.
    if significant > 1:
        return reject("ambiguous_foreground")
    if not candidates:
        return reject(rejected[0] if rejected else "no_card_outline")
    points, metrics, contour = candidates[0]
    result.metrics.update(metrics)
    interior = np.zeros((height, width), np.uint8)
    cv2.drawContours(interior, [contour], -1, 255, cv2.FILLED)
    interior = cv2.erode(interior, np.ones((7, 7), np.uint8))
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    sharpness = float(laplacian[interior != 0].var()) if np.any(interior) else 0.0
    result.metrics["interior_laplacian_variance"] = sharpness
    cv2.polylines(output.overlay, [points.astype(np.int32)], True, (0, 255, 0), 2)
    if sharpness < config.min_sharpness:
        return reject("insufficient_sharpness_or_texture")
    # Canonical portrait output. Rotating the corner cycle does not infer artwork orientation.
    lengths = np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1)
    rotation = int(lengths[0] + lengths[2] > lengths[1] + lengths[3])
    result.metrics["normalization_corner_rotation"] = rotation
    source = np.roll(points, -rotation, axis=0)
    nw, nh = config.normalized_width, config.normalized_height
    target = np.array([[0, 0], [nw - 1, 0], [nw - 1, nh - 1], [0, nh - 1]], np.float32)
    try:
        transform = cv2.getPerspectiveTransform(source, target)
        # Unit coordinates prevent image size/translation from dominating conditioning.
        unit = cv2.getPerspectiveTransform(source / np.array([width, height], np.float32), np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32))
        condition = float(np.linalg.cond(unit))
    except (cv2.error, np.linalg.LinAlgError):
        return reject("invalid_perspective_transform")
    if np.isfinite(condition):
        result.metrics["transform_condition"] = condition
    if not np.isfinite(transform).all() or not np.isfinite(condition) or condition > config.max_transform_condition or abs(np.linalg.det(unit)) < 1e-8:
        return reject("invalid_perspective_transform")
    try:
        inverse = np.linalg.inv(transform)
    except np.linalg.LinAlgError:
        return reject("invalid_perspective_transform")
    sample = np.vstack((target, target.mean(axis=0))).reshape(-1, 1, 2)
    mapped = cv2.perspectiveTransform(sample, inverse).reshape(-1, 2)
    denominators = np.column_stack((sample.reshape(-1, 2), np.ones(5))) @ inverse[2]
    if not np.isfinite(mapped).all() or np.any(np.abs(denominators) < 1e-8) or not (np.all(denominators > 0) or np.all(denominators < 0)) or np.any(mapped < 0) or np.any(mapped[:, 0] > width - 1) or np.any(mapped[:, 1] > height - 1):
        return reject("invalid_perspective_transform")
    try:
        output.normalized_image = cv2.warpPerspective(image, transform, (nw, nh), flags=cv2.INTER_LINEAR)
    except cv2.error:
        return reject("invalid_perspective_transform")
    output.transform = transform
    result.status = "detected"
    result.corners = points.astype(float).tolist()
    result.normalized_dimensions = {"width": nw, "height": nh}
    return output
