"""V2 conditional region-appearance assignment; additive diagnostics, never a gate."""

from __future__ import annotations

from itertools import combinations
from typing import Any

import cv2
import numpy as np

from .semantic import distance, histogram

VERSION = "0.1.0-semantic-region-exp2"
SETTINGS = [(trim, span) for trim in (1, 2, 3) for span in ((0.18, 0.82), (0.22, 0.78))]


def normalized(line: Any, normal: Any) -> Any:
    result = np.asarray(line, dtype=float)
    if result.shape != (3,) or not np.isfinite(result).all() or np.linalg.norm(result[:2]) < 1e-8:
        raise ValueError("Invalid candidate line")
    result = result / np.linalg.norm(result[:2])
    return result if result[:2] @ normal >= 0 else -result


def axes(physical: Any, index: int) -> tuple[Any, Any, float]:
    vector = physical[(index + 1) % 4] - physical[index]
    length = float(np.linalg.norm(vector))
    tangent = vector / length
    return tangent, np.array([-tangent[1], tangent[0]]), length


def raster(
    physical: Any, index: int, lines: list, span: tuple, shape: tuple, collar: tuple | None = None
) -> tuple[Any, Any, Any]:
    """Bounded native-pixel ROI; no rectification/resizing/interpolation."""
    tangent, normal, length = axes(physical, index)
    points: list[Any] = []
    for line in lines:
        for fraction in span:
            origin = physical[index] + fraction * length * tangent
            denominator = line[:2] @ normal
            if abs(denominator) < 0.1:
                raise ValueError("Candidate incompatible with physical-side rays")
            point = origin - (line[:2] @ origin + line[2]) / denominator * normal
            if collar:
                points.extend(point + d / denominator * normal for d in collar)
            else:
                points.append(point)
    vertices = np.asarray(points)
    lo = np.maximum(np.floor(vertices.min(axis=0)).astype(int) - 2, 0)
    hi = np.minimum(np.ceil(vertices.max(axis=0)).astype(int) + 3, [shape[1], shape[0]])
    yy, xx = np.mgrid[lo[1] : hi[1], lo[0] : hi[0]]
    xy = np.stack([xx, yy], axis=-1)
    fraction = ((xy - physical[index]) @ tangent) / length
    mask = (fraction >= span[0]) & (fraction <= span[1])
    return xy, fraction, mask


def collar_histograms(
    rgb: Any, physical: Any, index: int, line: Any, span: tuple
) -> tuple[Any, Any]:
    _, normal, _ = axes(physical, index)
    line = normalized(line, normal)
    histograms = []
    for bounds in ((-8, -2), (2, 8)):
        xy, _, valid = raster(physical, index, [line], span, rgb.shape, bounds)
        signed = xy @ line[:2] + line[2]
        mask = valid & (signed >= bounds[0]) & (signed <= bounds[1])
        if mask.sum() < 48:
            raise ValueError("Insufficient native collar pixels")
        coords = xy[mask]
        histograms.append(histogram(rgb[coords[:, 1], coords[:, 0]]))
    return histograms[0], histograms[1]


def fields(rgb: Any) -> dict:
    lum = np.asarray(rgb, dtype=np.float32) @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    dx = cv2.Sobel(lum, cv2.CV_32F, 1, 0, ksize=3, scale=1 / 8)
    dy = cv2.Sobel(lum, cv2.CV_32F, 0, 1, ksize=3, scale=1 / 8)
    return dict(luminance=lum, highpass=lum - cv2.GaussianBlur(lum, (0, 0), 1), dx=dx, dy=dy)


def appearance(rgb: Any, derived: dict, coords: Any, tangent: Any) -> dict:
    x, y = coords[:, 0], coords[:, 1]
    values = rgb[y, x]
    lum, hp, dx, dy = [derived[k][y, x] for k in ("luminance", "highpass", "dx", "dy")]
    magnitude = np.hypot(dx, dy)
    # Edge tangents, not gradient normals; modulo pi, relative to physical side.
    angles = np.mod(np.arctan2(dy, dx) + np.pi / 2 - np.arctan2(tangent[1], tangent[0]), np.pi)
    edge = magnitude >= 16
    orientation = np.histogram(angles[edge], bins=18, range=(0, np.pi))[0]
    orientation = orientation / max(1, orientation.sum())
    return dict(
        native_pixel_count=len(coords),
        rgb_p10_p50_p90=np.percentile(values, [10, 50, 90], axis=0).tolist(),
        rgb_std=values.std(axis=0).tolist(),
        rgb_histogram=histogram(values).tolist(),
        luminance_p10_p50_p90=np.percentile(lum, [10, 50, 90]).tolist(),
        luminance_histogram=np.histogram(lum, bins=32, range=(0, 256))[0]
        .astype(float)
        .__truediv__(len(lum))
        .tolist(),
        luminance_std=float(lum.std()),
        highpass_rms=float(np.sqrt(np.mean(hp**2))),
        gradient_p50_p90=np.percentile(magnitude, [50, 90]).tolist(),
        edge_density={str(t): float(np.mean(magnitude >= t)) for t in (8, 16, 32)},
        relative_edge_tangent_histogram_18=orientation.tolist(),
    )


def pair(rgb: Any, evaluation: dict, a: dict, b: dict, derived: dict, cache: dict) -> dict:
    physical = np.array(evaluation["physical_corners_pixels"])
    lookup = {c["id"]: c for s in evaluation["sides"] for c in s["candidates"]}
    la, lb = [], []
    for index in range(4):
        _, n, _ = axes(physical, index)
        la.append(normalized(lookup[a["candidate_ids"][index]]["line_abc"], n))
        lb.append(normalized(lookup[b["candidate_ids"][index]]["line_abc"], n))
    different = [i for i in range(4) if not np.allclose(la[i], lb[i], atol=1e-8, rtol=0)]
    result: dict[str, Any] = dict(
        hypotheses=[a["id"], b["id"]],
        different_sides=different,
        preferred=None,
        available=False,
        reason="requires_exactly_one_differing_side",
        views=[],
    )
    if len(different) != 1:
        return result
    index = different[0]
    tangent, normal, length = axes(physical, index)
    origin = physical[index] + 0.5 * length * tangent
    shifts = [
        -(origin @ line[:2] + line[2]) / (line[:2] @ normal) for line in (la[index], lb[index])
    ]
    inside_hypothesis = a["id"] if shifts[0] < shifts[1] else b["id"]
    outside_hypothesis = b["id"] if shifts[0] < shifts[1] else a["id"]
    result.update(
        region_inside_hypothesis=inside_hypothesis,
        region_outside_hypothesis=outside_hypothesis,
        midpoint_separation_px=float(abs(shifts[0] - shifts[1])),
    )
    try:
        for trim, span in SETTINGS:
            xy, fraction, valid = raster(physical, index, [la[index], lb[index]], span, rgb.shape)
            da, db = [xy @ line[:2] + line[2] for line in (la[index], lb[index])]
            mask = valid & (da * db < 0) & (np.abs(da) > trim) & (np.abs(db) > trim)
            for common in set(range(4)) - {index}:
                mask &= xy @ la[common][:2] + la[common][2] >= 0
            coords = xy[mask]
            fs = fraction[mask]
            if not len(coords):
                raise ValueError("Empty disputed region after trim")
            block_histograms = []
            block_descriptors = []
            for k in range(12):
                lo, hi = (
                    span[0] + (span[1] - span[0]) * k / 12,
                    span[0] + (span[1] - span[0]) * (k + 1) / 12,
                )
                keep = (fs >= lo) & (fs <= hi if k == 11 else fs < hi)
                if keep.sum() < 16:
                    raise ValueError("Insufficient native pixels in an along-side block")
                subset = coords[keep]
                block_histograms.append(histogram(rgb[subset[:, 1], subset[:, 0]]))
                if trim == 2 and span == (0.18, 0.82):
                    block_descriptors.append(appearance(rgb, derived, subset, tangent))
            contextual = []
            signs = []
            for common in sorted(set(range(4)) - {index}):
                key = (common, tuple(la[common]), span)
                if key not in cache:
                    cache[key] = collar_histograms(rgb, physical, common, la[common], span)
                exterior, interior = cache[key]
                de = np.array([distance(h, exterior) for h in block_histograms])
                di = np.array([distance(h, interior) for h in block_histograms])
                margin = de - di
                jackknife = [float(np.median(np.delete(margin, j))) for j in range(12)]
                sign = 1 if min(jackknife) > 1e-10 else -1 if max(jackknife) < -1e-10 else 0
                signs.append(sign)
                contextual.append(
                    dict(
                        context_side=common,
                        distance_to_exterior=de.tolist(),
                        distance_to_interior=di.tolist(),
                        block_margins=margin.tolist(),
                        leave_one_block_out_median_range=[min(jackknife), max(jackknife)],
                        sign=sign,
                    )
                )
            sign = signs[0] if len(set(signs)) == 1 else 0
            view = dict(
                trim_px=trim,
                span=list(span),
                native_pixel_count=len(coords),
                contextual_evidence=contextual,
                region_assignment_sign=sign,
            )
            if trim == 2 and span == (0.18, 0.82):
                view.update(
                    appearance=appearance(rgb, derived, coords, tangent),
                    along_side_blocks=block_descriptors,
                )
                result["region_span_endpoint_sample_pixels"] = [
                    xy[mask][np.argmin(fs)].tolist(),
                    xy[mask][np.argmax(fs)].tolist(),
                ]
            result["views"].append(view)
        signs = [v["region_assignment_sign"] for v in result["views"]]
        sign = signs[0] if len(set(signs)) == 1 else 0
        result.update(
            available=True,
            preferred=inside_hypothesis
            if sign == 1
            else outside_hypothesis
            if sign == -1
            else None,
            reason="stable_contextual_appearance_assignment"
            if sign
            else "mixed_or_neutral_contextual_evidence",
        )
    except ValueError as exc:
        result["reason"] = str(exc)
    return result


def leader(ids: list[str], pairs: list[dict], truncated: bool) -> str | None:
    if truncated or len(ids) < 2:
        return None
    winners = [
        h
        for h in ids
        if all(
            any(set(p["hypotheses"]) == {h, other} and p["preferred"] == h for p in pairs)
            for other in ids
            if other != h
        )
    ]
    return winners[0] if len(winners) == 1 else None


def analyze(rgb: Any, evaluation: dict, v1: dict) -> dict:
    frames = [h for h in evaluation["frame_evaluation"]["hypotheses"] if h["geometrically_valid"]]
    derived = fields(rgb) if frames else {}
    cache: dict = {}
    comparisons = [pair(rgb, evaluation, a, b, derived, cache) for a, b in combinations(frames, 2)]
    ids = [h["id"] for h in frames]
    subset = [h for h in v1["leaders_by_view"]["0.0:full"] if h in ids]
    truncated = evaluation["frame_evaluation"]["search_truncated"]
    return dict(
        kind="competing_frame_region_diagnostics",
        algorithm_version=VERSION,
        schema_version=1,
        status="review_required",
        automatic_acceptance=False,
        manual_reference_used=False,
        existing_search_truncated=truncated,
        existing_status=evaluation["status"],
        comparisons=comparisons,
        v1_leader_subset=subset,
        conditional_leader_all_hypotheses=leader(ids, comparisons, truncated),
        conditional_leader_v1_subset=leader(subset, comparisons, truncated),
        semantic_selection=None,
        abstained=True,
        hypotheses=[
            dict(
                hypothesis_id=h,
                pairwise_wins=sum(p["preferred"] == h for p in comparisons),
                pairwise_losses=sum(
                    p["preferred"] is not None and h in p["hypotheses"] and p["preferred"] != h
                    for p in comparisons
                ),
                unresolved_or_unavailable=sum(
                    h in p["hypotheses"] and p["preferred"] is None for p in comparisons
                ),
            )
            for h in ids
        ],
        interpretation="Conditional region appearance assignment, not OCR, design identity, semantic acceptance, confidence or grading.",
    )
