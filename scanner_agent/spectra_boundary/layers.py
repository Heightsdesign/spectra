"""Parallel layer evidence in original grayscale, independent of working-image tonality."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import cv2
import numpy as np


def samples(gray: Any, positions: Any) -> tuple[Any, Any]:
    valid = (
        (positions[..., 0] >= 0)
        & (positions[..., 0] <= gray.shape[1] - 1)
        & (positions[..., 1] >= 0)
        & (positions[..., 1] <= gray.shape[0] - 1)
    )
    values = cv2.remap(
        gray,
        positions[..., 0].astype(np.float32),
        positions[..., 1].astype(np.float32),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
    ).astype(float)
    return values, valid


def evidence(
    gray: Any,
    centers: Any,
    normal: Any,
    line: Any,
    background: Any,
    options: dict[str, Any],
    exterior_reach_pixels: int = 48,
) -> dict[str, Any]:
    offsets = -(centers @ line[:2] + line[2]) / (normal @ line[:2])
    locations = centers + offsets[:, None] * normal
    probe_offsets = np.array([-8, -4, -2, -1, 0, 1, 2, 4, 8], float)
    values, valid = samples(gray, locations[:, None, :] + probe_offsets[None, :, None] * normal)
    usable = valid.all(axis=1) & np.isfinite(background)
    if not usable.any():
        return {"available": False}
    v, bg = values[usable], background[usable]
    drop = v[:, 2] - v[:, 6]
    slope = (v[:, 3] - v[:, 5]) / 2
    broad = (v[:, 0] - v[:, 8]) / 16
    full_drop = bg - v[:, 8]
    deficit = (bg - v[:, 1]) / np.maximum(full_drop, 1)
    distances = np.arange(1, exterior_reach_pixels + 1, dtype=float)
    exterior, exterior_valid = samples(
        gray, locations[usable, None, :] - distances[None, :, None] * normal
    )
    close = (
        np.abs(exterior - bg[:, None]) <= np.maximum(4, np.maximum(full_drop, 0) * 0.05)[:, None]
    ) & exterior_valid
    plateau = close[:, :-2] & close[:, 1:-1] & close[:, 2:]
    found = plateau.any(axis=1)
    plateau_distance = np.argmax(plateau, axis=1) + 1
    darkest_exterior = np.min(np.where(exterior_valid[:, 3:], exterior[:, 3:], np.inf), axis=1)
    path_deficit = (bg - darkest_exterior) / np.maximum(full_drop, 1)
    return {
        "available": True,
        "valid_profile_fraction": float(usable.mean()),
        "exterior_reference_gray": float(np.median(bg)),
        "raw_probe_offsets_pixels": probe_offsets.tolist(),
        "raw_median_gray": np.median(v, axis=0).tolist(),
        "signed_inward_drop_gray": float(np.median(drop)),
        "drop_p10_p90_gray": np.percentile(drop, [10, 90]).tolist(),
        "gradient_polarity_fraction": float(np.mean(slope > 0)),
        "strong_transition_fraction": float(np.mean(drop >= options["minimum_raw_drop"])),
        "raw_signed_slope_gray_per_pixel": float(np.median(slope)),
        "sharpness_ratio": float(np.median(slope) / max(float(np.median(broad)), 1)),
        "background_to_inside_drop_gray": float(np.median(full_drop)),
        "exterior_deficit_fraction": float(np.median(deficit)),
        "exterior_path_deficit_fraction": float(np.median(path_deficit)),
        "exterior_path_reach_pixels": exterior_reach_pixels,
        "exterior_plateau_distance_median_pixels": float(np.median(plateau_distance[found]))
        if found.any()
        else None,
        "exterior_plateau_observed_fraction": float(found.mean()),
        "offset_at_profile_median_inward_pixels": float(np.median(offsets)),
    }


def select_layers(
    points: Any,
    indexes: Any,
    offsets: Any,
    start: Any,
    end: Any,
    band: float,
    original_gray: Any,
    working: Any,
    config: dict[str, Any],
    fit_line: Callable[[Any], tuple[Any, Any]],
) -> tuple[dict[str, Any], Any, Any]:
    options = config["physical_boundary"]
    vector = end - start
    length = float(np.linalg.norm(vector))
    tangent = vector / length
    normal = np.array([-tangent[1], tangent[0]])  # clockwise image quad -> inward
    exclusion = config["corner_exclusion_fraction"]
    centers = (
        start
        + np.linspace(exclusion, 1 - exclusion, int(options["profile_samples"]))[:, None] * vector
    )
    profile_offsets = np.arange(-np.ceil(band) - 12, np.ceil(band) + 13)
    locations = centers[:, None, :] + profile_offsets[None, :, None] * normal
    raw, valid = samples(original_gray, locations)
    enhanced, _ = samples(working, locations)
    background = np.array(
        [
            np.median(row[np.flatnonzero(mask)[:8]]) if mask.any() else np.nan
            for row, mask in zip(raw, valid, strict=True)
        ]
    )
    profile = []
    for j, offset in enumerate(profile_offsets):
        values = raw[valid[:, j], j]
        profile.append(
            {
                "offset_inward_pixels": float(offset),
                "raw_median_gray": float(np.median(values)) if len(values) else None,
                "raw_p10_p90_gray": np.percentile(values, [10, 90]).tolist()
                if len(values)
                else None,
                "working_median_gray": float(np.median(enhanced[valid[:, j], j]))
                if len(values)
                else None,
                "valid_fraction": float(valid[:, j].mean()),
            }
        )
    bins = np.floor(offsets).astype(int)
    minimum = int(bins.min())
    histogram = np.bincount(bins - minimum)
    dominant = int(np.argmax(histogram))
    away = np.ones(len(histogram), bool)
    away[max(0, dominant - 3) : dominant + 4] = False
    # Preserve the old safety condition exactly; no threshold is relaxed.
    density_ambiguity = bool(histogram[away].max(initial=0) > 0.35 * histogram[dominant])
    peaks: list[int] = []
    for peak in np.argsort(-histogram, kind="stable"):
        if histogram[peak] < 10 or any(abs(int(peak) - p) <= 3 for p in peaks):
            continue
        peaks.append(int(peak))
    layers: list[dict[str, Any]] = []
    supports: list[Any] = []
    ids: list[Any] = []
    for peak in sorted(peaks):
        peak_offset = peak + minimum + 0.5
        select = np.abs(offsets - peak_offset) <= 2
        candidate = points[select]
        if len(candidate) < 20:
            continue
        line, residual = fit_line(candidate)
        inliers = residual <= max(1.5, config["maximum_rms_pixels"] * 2)
        if inliers.sum() < 20:
            continue
        support = candidate[inliers]
        line, residual = fit_line(support)
        if abs(normal @ line[:2]) < 0.9:
            continue
        along = (support - start) @ tangent / length
        coverage = (
            len(np.unique(np.clip(np.floor((along - exclusion) / (1 - 2 * exclusion) * 40), 0, 39)))
            / 40
        )
        metric = evidence(
            original_gray, centers, normal, line, background, options, max(48, int(2 * band + 16))
        )
        rms = float(np.sqrt(np.mean(residual**2)))
        failures = []
        if not metric["available"]:
            failures.append("raw_profiles_unavailable")
        else:
            for check, passed in (
                ("profile_domain", metric["valid_profile_fraction"] >= 0.9),
                (
                    "inward_darkening_polarity",
                    metric["gradient_polarity_fraction"] >= options["minimum_polarity_fraction"],
                ),
                (
                    "strong_continuous_transition",
                    metric["strong_transition_fraction"] >= options["minimum_polarity_fraction"],
                ),
                (
                    "raw_local_contrast",
                    metric["signed_inward_drop_gray"] >= options["minimum_raw_drop"],
                ),
                (
                    "localized_not_broad_gradient",
                    metric["sharpness_ratio"] >= options["minimum_sharpness_ratio"],
                ),
                (
                    "exterior_background_path",
                    metric["exterior_path_deficit_fraction"]
                    <= options["maximum_exterior_deficit_fraction"],
                ),
                ("side_coverage", coverage >= config["minimum_side_coverage"]),
                ("side_residual", rms <= config["maximum_rms_pixels"]),
            ):
                if not passed:
                    failures.append(check)
        score = 0.0
        if metric["available"]:
            score = (
                max(metric["signed_inward_drop_gray"], 0)
                * metric["strong_transition_fraction"]
                * coverage
                / ((1 + rms) * (1 + max(metric["exterior_path_deficit_fraction"], 0) * 3))
            )
        layer = {
            "id": f"L{len(layers)}",
            "line_abc": line.tolist(),
            "density_peak_offset_inward_pixels": float(peak_offset),
            "fitted_midpoint_offset_inward_pixels": metric.get(
                "offset_at_profile_median_inward_pixels"
            ),
            "density_peak_count": int(histogram[peak]),
            "legacy_density_winner": peak == dominant,
            "support_count": len(support),
            "support_sample_pixels": support[:: max(1, len(support) // 64)].tolist(),
            "rms_pixels": rms,
            "p95_residual_pixels": float(np.percentile(residual, 95)),
            "coverage": coverage,
            "raw_evidence": metric,
            "support_score": score,
            "physical_criterion_passed": not failures,
            "criterion_failures": failures,
        }
        layers.append(layer)
        supports.append(support)
        ids.append(indexes[select][inliers])
    if not layers:
        return {"reason": "no_fittable_parallel_layers"}, np.empty((0, 2)), np.array([], int)
    eligible = [i for i, layer in enumerate(layers) if layer["physical_criterion_passed"]]
    selected = max(eligible or list(range(len(layers))), key=lambda i: layers[i]["support_score"])
    chosen = layers[selected]
    reasons = []
    if density_ambiguity:
        reasons.append("legacy_density_competition_retained")
    if not eligible:
        reasons.append("no_candidate_satisfies_physical_criterion")
    if len(eligible) > 1:
        reasons.append("multiple_candidates_satisfy_physical_criterion")
    if (
        chosen["raw_evidence"].get("exterior_deficit_fraction", 1)
        > options["maximum_clear_exterior_deficit_fraction"]
    ):
        reasons.append("non_plateau_exterior_approach_blur_or_shadow")
    for i, layer in enumerate(layers):
        layer["selected"] = i == selected
        layer["disposition"] = (
            "provisional_selected"
            if i == selected
            else "rejected_by_criterion"
            if layer["criterion_failures"]
            else "eligible_alternative_unresolved"
        )
        metric = layer["raw_evidence"]
        if (
            i != selected
            and metric.get("gradient_polarity_fraction", 0) >= options["minimum_polarity_fraction"]
            and metric.get("signed_inward_drop_gray", 0) >= options["minimum_raw_drop"]
        ):
            reasons.append("other_coherent_darkening_layer_shadow_or_print_not_resolved")
    result = {
        "selected_layer_id": chosen["id"],
        "candidate_layers": layers,
        "density_ambiguity_detected": density_ambiguity,
        "physical_selection_resolved": not reasons,
        "ambiguity_reasons": sorted(set(reasons)),
        "seed_start_pixels": start.tolist(),
        "seed_end_pixels": end.tolist(),
        "inward_normal": normal.tolist(),
        "search_half_width_pixels": band,
        "offset_histogram": [[int(i + minimum), int(n)] for i, n in enumerate(histogram)],
        "normal_profile": profile,
        "selection_criterion": "continuous localized inward darkening connected to exterior backing; original grayscale evidence; no outermost or nominal-size preference",
    }
    return result, supports[selected], ids[selected]
