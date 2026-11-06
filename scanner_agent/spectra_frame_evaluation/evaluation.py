from __future__ import annotations

from copy import deepcopy
from itertools import islice, product
from math import prod
from typing import Any

import cv2
import numpy as np

from spectra_centering.detector import axes, measurements

# Evidence limits are experimental, independent of nominal card dimensions or grades.
DEFAULTS: dict[str, Any] = {
    "minimum_transition_p10_rgb": 12.0,
    "maximum_transition_coefficient_of_variation": 0.75,
    "minimum_transition_direction_fraction": 0.8,
    "maximum_opposite_angle_degrees": 6.0,
    "maximum_adjacent_deviation_degrees": 6.0,
    "maximum_hypotheses": 256,
}


def transition_evidence(
    rgb: Any, corners: Any, index: int, candidate: dict[str, Any], detector_config: dict[str, Any]
) -> dict[str, Any]:
    _, normal, _ = axes(corners, index)
    count = detector_config["profile_count"]
    ts = np.linspace(
        detector_config["corner_exclusion_fraction"],
        1 - detector_config["corner_exclusion_fraction"],
        count,
    )
    origins = corners[index] + ts[:, None] * (corners[(index + 1) % 4] - corners[index])
    line = np.asarray(candidate["line_abc"], dtype=float)
    if line.shape != (3,) or not np.isfinite(line).all() or np.linalg.norm(line[:2]) < 1e-8:
        raise ValueError("Invalid candidate line")
    denominator = np.dot(line[:2], normal)
    if abs(denominator) < 0.1:
        raise ValueError("Invalid candidate orientation")
    distances = -(origins @ line[:2] + line[2]) / denominator
    points = origins + distances[:, None] * normal
    locations = points[:, None, :] + np.array([-2.0, 2.0])[None, :, None] * normal
    samples = cv2.remap(
        rgb,
        locations[:, :, 0].astype(np.float32),
        locations[:, :, 1].astype(np.float32),
        cv2.INTER_LINEAR,
    ).astype(float)
    delta = samples[:, 1] - samples[:, 0]
    strengths = np.sqrt(np.mean(delta**2, axis=1))
    median_delta = np.median(delta, axis=0)
    lengths = np.linalg.norm(delta, axis=1) * np.linalg.norm(median_delta)
    cosines = np.divide(delta @ median_delta, lengths, out=np.zeros(count), where=lengths > 1e-8)
    mean = float(np.mean(strengths))
    # Separate descriptive color spread and spatial variation from transition evidence.
    # A fixed 48-position corridor is sampled without interpreting texture as a veto.
    corridor_distances = 2 + (distances[:, None] - 5) * np.linspace(0, 1, 48)[None, :]
    corridor_locations = origins[:, None, :] + corridor_distances[:, :, None] * normal
    corridor = cv2.remap(
        rgb,
        corridor_locations[:, :, 0].astype(np.float32),
        corridor_locations[:, :, 1].astype(np.float32),
        cv2.INTER_LINEAR,
    ).astype(float)
    exterior = {
        "rgb_mean": np.mean(corridor, axis=(0, 1)).tolist(),
        "rgb_std": np.std(corridor, axis=(0, 1)).tolist(),
        "along_side_sample_difference_rgb_rms": float(
            np.sqrt(np.mean(np.diff(corridor, axis=0) ** 2))
        ),
        "inward_sample_difference_rgb_rms": float(np.sqrt(np.mean(np.diff(corridor, axis=1) ** 2))),
        "sampling": "48 equally spaced normal positions from 2px inside physical side to 3px outside candidate; spatial differences depend on sampling scale, not calibrated texture",
    }
    return {
        "profile_positions_fraction": ts.tolist(),
        "transition_rgb_vectors": delta.tolist(),
        "strengths_rgb_rms": strengths.tolist(),
        "mean_rgb_rms": mean,
        "p10_rgb_rms": float(np.percentile(strengths, 10)),
        "median_rgb_rms": float(np.median(strengths)),
        "p90_rgb_rms": float(np.percentile(strengths, 90)),
        "std_rgb_rms": float(np.std(strengths)),
        "coefficient_of_variation": float(np.std(strengths) / mean) if mean > 0 else None,
        "direction_consistent_fraction": float(np.mean(cosines >= 0.5)),
        "normal_distances_pixels": distances.tolist(),
        "exterior_band_evidence": exterior,
    }


def evaluate_candidates(
    rgb: Any,
    corners: Any,
    detected: list[dict[str, Any]],
    detector_config: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    sides = deepcopy(detected)
    for side in sides:
        # S2.2a's selected_candidate_id is evidence, never a downstream selection.
        side["s2_2a_selected_candidate_id"] = side.pop("selected_candidate_id")
        for candidate in side["candidates"]:
            reasons = list(candidate["rejection_reasons"])
            candidate["retention"] = "rejected"
            candidate["additional_rejection_reasons"] = []
            candidate["transition_evidence"] = None
            candidate["heterogeneity_is_independent_of_geometry"] = True
            candidate["geometry_evidence"] = {
                "support_fraction": candidate["support_fraction"],
                "support_point_count": len(candidate["support_points_pixels"]),
                "total_profile_count": detector_config["profile_count"],
                "fit_rms_pixels": candidate["fit_rms_pixels"],
                "angle_difference_degrees": candidate["angle_difference_degrees"],
                "support_definition": "S2.2a gradient-supported points within 3px of fitted line, divided by all profiles; independent of band heterogeneity, not independent of gradient strength",
            }
            if candidate["line_abc"] is None:
                candidate["additional_rejection_reasons"].append("missing_line")
                continue
            try:
                evidence = transition_evidence(
                    rgb, corners, side["index"], candidate, detector_config
                )
                candidate["transition_evidence"] = evidence
                if evidence["p10_rgb_rms"] < config["minimum_transition_p10_rgb"]:
                    candidate["additional_rejection_reasons"].append("weak_transition_p10")
                if (
                    evidence["coefficient_of_variation"] is None
                    or evidence["coefficient_of_variation"]
                    > config["maximum_transition_coefficient_of_variation"]
                ):
                    candidate["additional_rejection_reasons"].append("unstable_transition_strength")
                if (
                    evidence["direction_consistent_fraction"]
                    < config["minimum_transition_direction_fraction"]
                ):
                    candidate["additional_rejection_reasons"].append(
                        "unstable_transition_direction"
                    )
                if min(evidence["normal_distances_pixels"]) <= 0:
                    candidate["additional_rejection_reasons"].append("nonpositive_border")
            except ValueError as exc:
                candidate["additional_rejection_reasons"].append(str(exc))
            essential = set(reasons) - {"heterogeneous_outer_band"}
            if not essential and not candidate["additional_rejection_reasons"]:
                candidate["retention"] = "provisional" if reasons else "retained"
    return sides


def angle_between(a: Any, b: Any) -> float:
    return float(
        np.degrees(
            np.arccos(np.clip(abs(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))), 0, 1))
        )
    )


def evaluate_hypothesis(
    corners: Any,
    combination: Any,
    detector_config: dict[str, Any],
    config: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": f"frame-{index:04}",
        "candidate_ids": [c["id"] for c in combination],
        "contains_provisional_candidates": any(
            c["retention"] == "provisional" for c in combination
        ),
        "rejection_reasons": [],
        "geometrically_valid": False,
        "complete_four_sides": len(combination) == 4,
    }
    normals = np.array([c["line_abc"][:2] for c in combination])
    opposite = [angle_between(normals[i], normals[i + 2]) for i in range(2)]
    adjacent = [abs(90 - angle_between(normals[i], normals[(i + 1) % 4])) for i in range(4)]
    result.update(opposite_angle_degrees=opposite, adjacent_deviation_degrees=adjacent)
    if max(opposite) > config["maximum_opposite_angle_degrees"]:
        result["rejection_reasons"].append("opposite_parallelism")
    if max(adjacent) > config["maximum_adjacent_deviation_degrees"]:
        result["rejection_reasons"].append("adjacent_compatibility")
    sides = [
        {"name": name, "selected_candidate_id": c["id"], "candidates": [c]}
        for name, c in zip(("top", "right", "bottom", "left"), combination, strict=True)
    ]
    try:
        geometry = measurements(corners, sides, None, detector_config)
        # Intentionally no centering ratios: geometric plausibility does not identify
        # the intended printed frame or justify reporting a centering measurement.
        result["corners_pixels"] = geometry["printed_corners_pixels"]
        result["conditional_margins_pixels"] = {
            name: {
                key: value for key, value in margin.items() if key != "mean_mm_from_reported_dpi"
            }
            for name, margin in geometry["margins"].items()
        }
        result["geometrically_valid"] = not result["rejection_reasons"]
    except (ValueError, np.linalg.LinAlgError) as exc:
        result["rejection_reasons"].append(str(exc))
    return result


def hypotheses(
    corners: Any,
    sides: list[dict[str, Any]],
    detector_config: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    pools = [[c for c in side["candidates"] if c["retention"] != "rejected"] for side in sides]
    total = prod(len(pool) for pool in pools)
    frames = [
        evaluate_hypothesis(corners, combination, detector_config, config, index)
        for index, combination in enumerate(islice(product(*pools), config["maximum_hypotheses"]))
    ]
    truncated = total > len(frames) or any(s["candidate_limit_reached"] for s in sides)
    valid = [f for f in frames if f["geometrically_valid"]]
    selected = valid[0]["id"] if len(valid) == 1 and not truncated else None
    comparisons = []
    if valid:
        reference = np.array(valid[0]["corners_pixels"])
        for frame in valid:
            displacement = np.array(frame["corners_pixels"]) - reference
            comparisons.append(
                {
                    "hypothesis_id": frame["id"],
                    "reference_hypothesis_id": valid[0]["id"],
                    "corner_displacements_pixels": displacement.tolist(),
                    "maximum_corner_displacement_pixels": float(
                        np.linalg.norm(displacement, axis=1).max()
                    ),
                }
            )
    return {
        "candidate_pool_sizes": [len(pool) for pool in pools],
        "possible_combinations": total,
        "evaluated_count": len(frames),
        "search_truncated": truncated,
        "hypotheses": frames,
        "valid_count": len(valid),
        "selected_geometric_hypothesis_id": selected,
        "competing_hypotheses_unresolved": len(valid) > 1,
        "comparisons": comparisons,
        "selection_policy": "All geometrically valid hypotheses remain similarly plausible; no brightness, symmetry or outermost-edge ranking establishes semantic frame identity.",
    }
