"""Controlled transition experiment; never changes the frozen 0.2.0 selector.

Density is detection evidence, admissibility precedes ranking, and shadow caution
is independent of competitor admissibility. Support updates are single-shot and
anchored to the original fit, with tighter bounds than the original inlier cutoff.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np

from .layers import evidence, samples
from .layers import select_layers as frozen_select

VERSION = "0.3.0-exp1"
SUPPORT_RADIUS = 1.5
MAXIMUM_ANCHOR_MOVEMENT = 0.5


def classify(result: dict[str, Any], options: dict[str, Any]) -> None:
    layers = result["candidate_layers"]
    eligible = [layer for layer in layers if layer["physical_criterion_passed"]]
    chosen = max(eligible or layers, key=lambda layer: layer["support_score"])
    reasons = []
    if not eligible:
        reasons.append("no_candidate_satisfies_physical_criterion")
    if len(eligible) > 1:
        reasons.append("multiple_candidates_satisfy_physical_criterion")
    if (
        chosen["raw_evidence"].get("exterior_deficit_fraction", 1)
        > options["maximum_clear_exterior_deficit_fraction"]
    ):
        reasons.append("non_plateau_exterior_approach_blur_or_shadow")
    for layer in layers:
        metric = layer["raw_evidence"]
        coherent_alternative = (
            layer is not chosen
            and metric.get("gradient_polarity_fraction", 0) >= options["minimum_polarity_fraction"]
            and metric.get("signed_inward_drop_gray", 0) >= options["minimum_raw_drop"]
        )
        if coherent_alternative:
            reasons.append("other_coherent_darkening_layer_shadow_or_print_not_resolved")
        layer["selected"] = layer is chosen
        layer["disposition"] = (
            "provisional_selected"
            if layer is chosen
            else "eligible_alternative_unresolved"
            if layer["physical_criterion_passed"]
            else "rejected_by_criterion"
        )
        layer["ambiguity_decision"] = {
            "retained": layer["physical_criterion_passed"] or coherent_alternative,
            "role": "selected" if layer is chosen else "competitor",
            "reason": "all_physical_criteria_passed"
            if layer["physical_criterion_passed"]
            else "coherent_darkening_safety_caution"
            if coherent_alternative
            else "excluded_by_physical_criteria",
            "criterion_failures": list(layer["criterion_failures"]),
        }
    result.update(
        selected_layer_id=chosen["id"],
        ambiguity_reasons=sorted(set(reasons)),
        physical_selection_resolved=not reasons,
        ambiguity_policy="admissible_transition_candidates_v1",
    )


def quality(
    metric: dict[str, Any], coverage: float, rms: float, config: dict[str, Any]
) -> tuple[list[str], float]:
    options = config["physical_boundary"]
    if not metric["available"]:
        return ["raw_profiles_unavailable"], 0.0
    checks = {
        "profile_domain": metric["valid_profile_fraction"] >= 0.9,
        "inward_darkening_polarity": metric["gradient_polarity_fraction"]
        >= options["minimum_polarity_fraction"],
        "strong_continuous_transition": metric["strong_transition_fraction"]
        >= options["minimum_polarity_fraction"],
        "raw_local_contrast": metric["signed_inward_drop_gray"] >= options["minimum_raw_drop"],
        "localized_not_broad_gradient": metric["sharpness_ratio"]
        >= options["minimum_sharpness_ratio"],
        "exterior_background_path": metric["exterior_path_deficit_fraction"]
        <= options["maximum_exterior_deficit_fraction"],
        "side_coverage": coverage >= config["minimum_side_coverage"],
        "side_residual": rms <= config["maximum_rms_pixels"],
    }
    score = (
        max(metric["signed_inward_drop_gray"], 0)
        * metric["strong_transition_fraction"]
        * coverage
        / ((1 + rms) * (1 + max(metric["exterior_path_deficit_fraction"], 0) * 3))
    )
    return [key for key, passed in checks.items() if not passed], score


def reassign(
    layer: dict[str, Any],
    layers: list[dict[str, Any]],
    points: Any,
    start: Any,
    end: Any,
    gray: Any,
    config: dict[str, Any],
    fit_line: Any,
    band: float,
) -> tuple[Any, Any]:
    """Try only coverage-only failures; refuse photometric or identity uncertainty.

    Never iterate toward a neighboring track. Each point must darken inward and
    be closer to this original line than every other coherent-darkening line.
    All profile criteria are recomputed after fitting; unsafe proposals roll back.
    """
    log: dict[str, Any] = {
        "status": "not_attempted",
        "radius_pixels": SUPPORT_RADIUS,
        "maximum_anchor_movement_pixels": MAXIMUM_ANCHOR_MOVEMENT,
    }
    layer["support_reassignment"] = log
    if layer["criterion_failures"] != ["side_coverage"]:
        log["reason"] = "requires_coverage_only_failure"
        return None, None
    anchor = np.asarray(layer["line_abc"])
    vector = end - start
    length = np.linalg.norm(vector)
    tangent = vector / length
    normal = np.array([-tangent[1], tangent[0]])
    exclusion = config["corner_exclusion_fraction"]
    centers = (
        start
        + np.linspace(exclusion, 1 - exclusion, config["physical_boundary"]["profile_samples"])[
            :, None
        ]
        * vector
    )
    distance = np.abs(points @ anchor[:2] + anchor[2])
    allowed = distance <= SUPPORT_RADIUS
    for other in layers:
        m = other["raw_evidence"]
        if other["id"] == layer["id"] or not m.get("available"):
            continue
        if (
            m["gradient_polarity_fraction"]
            >= config["physical_boundary"]["minimum_polarity_fraction"]
            and m["signed_inward_drop_gray"] >= config["physical_boundary"]["minimum_raw_drop"]
        ):
            line = np.asarray(other["line_abc"])
            allowed &= distance + 0.25 < np.abs(points @ line[:2] + line[2])
    probes, valid = samples(
        gray, points[:, None, :] + np.array([-2, -1, 1, 2])[None, :, None] * normal
    )
    allowed &= (
        valid.all(axis=1)
        & (probes[:, 0] - probes[:, 3] >= config["physical_boundary"]["minimum_raw_drop"])
        & (probes[:, 1] > probes[:, 2])
    )
    support = points[allowed]
    log.update(status="rejected", input_points=len(points), admitted_points=len(support))
    if len(support) < 20:
        log["reason"] = "insufficient_physical_support"
        return None, None
    line, residual = fit_line(support)
    if abs(normal @ line[:2]) < 0.9:
        log["reason"] = "orientation_guard"
        return None, None

    def offset(coeff: Any) -> Any:
        return -(centers @ coeff[:2] + coeff[2]) / (normal @ coeff[:2])

    movement = float(np.max(np.abs(offset(line) - offset(anchor))))
    log["maximum_movement_pixels"] = movement
    if movement > MAXIMUM_ANCHOR_MOVEMENT or residual.max() > SUPPORT_RADIUS:
        log["reason"] = "anchor_or_residual_guard"
        return None, None
    raw_offsets = np.arange(-np.ceil(band) - 12, np.ceil(band) + 13)
    raw, domain = samples(gray, centers[:, None, :] + raw_offsets[None, :, None] * normal)
    background = np.array(
        [
            np.median(row[np.flatnonzero(mask)[:8]]) if mask.any() else np.nan
            for row, mask in zip(raw, domain, strict=True)
        ]
    )
    metric = evidence(
        gray,
        centers,
        normal,
        line,
        background,
        config["physical_boundary"],
        max(48, int(2 * band + 16)),
    )
    along = (support - start) @ tangent / length
    coverage = (
        len(np.unique(np.clip(np.floor((along - exclusion) / (1 - 2 * exclusion) * 40), 0, 39)))
        / 40
    )
    rms = float(np.sqrt(np.mean(residual**2)))
    failures, score = quality(metric, coverage, rms, config)
    log["proposal"] = {
        "line_abc": line.tolist(),
        "coverage": coverage,
        "raw_evidence": metric,
        "criterion_failures": failures,
        "rms_pixels": rms,
    }
    if (
        failures
        or metric.get("exterior_deficit_fraction", 1)
        > config["physical_boundary"]["maximum_clear_exterior_deficit_fraction"]
    ):
        log["reason"] = "recomputed_physical_or_clear_exterior_criteria_failed"
        return None, None
    log.update(status="applied", reason="bounded_photometrically_supported_refit")
    layer.update(
        line_abc=line.tolist(),
        coverage=coverage,
        rms_pixels=rms,
        p95_residual_pixels=float(np.percentile(residual, 95)),
        support_count=len(support),
        support_sample_pixels=support[:: max(1, len(support) // 64)].tolist(),
        raw_evidence=metric,
        support_score=score,
        criterion_failures=failures,
        physical_criterion_passed=True,
        fitted_midpoint_offset_inward_pixels=metric["offset_at_profile_median_inward_pixels"],
    )
    return support, allowed


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
    fit_line: Any,
    *,
    support_reassignment: bool = False,
) -> tuple[dict[str, Any], Any, Any]:
    result, support, selected_indexes = frozen_select(
        points, indexes, offsets, start, end, band, original_gray, working, config, fit_line
    )
    if "candidate_layers" not in result:
        return result, support, selected_indexes
    result["frozen_selection"] = deepcopy(result)
    original_layers = deepcopy(result["candidate_layers"])
    replacements = {}
    for layer in result["candidate_layers"]:
        layer["original_candidate"] = deepcopy(layer)
        if support_reassignment:
            new_support, mask = reassign(
                layer, original_layers, points, start, end, original_gray, config, fit_line, band
            )
            if new_support is not None:
                replacements[layer["id"]] = (new_support, indexes[mask])
    classify(result, config["physical_boundary"])
    selected = result["selected_layer_id"]
    if selected in replacements:
        support, selected_indexes = replacements[selected]
    elif selected != result["frozen_selection"]["selected_layer_id"]:
        # Classification alone does not change admissibility or ranking. An
        # unchanged alternative selected after a refit must use its own support.
        layer = next(x for x in original_layers if x["id"] == selected)
        mask = np.abs(offsets - layer["density_peak_offset_inward_pixels"]) <= 2
        _, residual = fit_line(points[mask])
        inside = residual <= max(1.5, config["maximum_rms_pixels"] * 2)
        support, selected_indexes = points[mask][inside], indexes[mask][inside]
    return result, support, selected_indexes
