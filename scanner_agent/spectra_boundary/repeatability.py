from __future__ import annotations

from typing import Any

import numpy as np


def summary(values: Any) -> dict[str, Any]:
    array = np.asarray(values, dtype=np.float64)
    mean = array.mean(axis=0)
    return {
        "mean": mean.tolist(),
        "sample_standard_deviation": array.std(axis=0, ddof=1).tolist(),
        "maximum_absolute_deviation_from_mean": np.max(np.abs(array - mean), axis=0).tolist(),
    }


def rigid_to_reference(points: Any, reference: Any) -> tuple[Any, dict[str, Any]]:
    center, target = points.mean(axis=0), reference.mean(axis=0)
    u, _, vt = np.linalg.svd((points - center).T @ (reference - target))
    correction = np.eye(2)
    correction[-1, -1] = np.linalg.det(u @ vt)
    rotation = u @ correction @ vt
    translation = target - center @ rotation
    aligned = points @ rotation + translation
    return aligned, {
        "row_vector_rotation_matrix": rotation.tolist(),
        "translation_pixels": translation.tolist(),
        "scale": 1,
        "reflection": False,
        "coordinate_only_no_image_resampling": True,
    }


def side_offsets(corners: Any, reference: Any) -> Any:
    values = []
    for i in range(4):
        start, end = corners[i], corners[(i + 1) % 4]
        direction = end - start
        normal = np.array([-direction[1], direction[0]]) / np.linalg.norm(direction)
        anchor = (reference[i] + reference[(i + 1) % 4]) / 2
        values.append(float((start - anchor) @ normal))
    return values


def repeatability(analyses: list[dict[str, Any]]) -> dict[str, Any]:
    if len(analyses) < 3:
        return {"status": "failure", "reason": "at_least_three_images_required"}
    if any(a.get("status") == "failure" for a in analyses):
        return {"status": "failure", "reason": "one_or_more_analyses_failed"}
    hashes = [a.get("source", {}).get("sha256") for a in analyses]
    if len(set(hashes)) != len(hashes):
        return {"status": "failure", "reason": "duplicate_source_hashes_not_independent_evidence"}
    detections = [a.get("baseline", {}) for a in analyses]
    if any("geometry" not in d for d in detections):
        return {"status": "failure", "reason": "one_or_more_images_have_no_four_side_geometry"}
    corners = np.asarray([d["geometry"]["corners_pixels"] for d in detections])
    reference = corners[0]
    # Two short sides are geometrically interchangeable. Keep correspondence
    # continuous near the +/-90-degree canonical-label boundary using only cyclic
    # relabeling, not alignment or coordinate changes in raw statistics.
    correspondence_shifts = []
    centered_reference = reference - reference.mean(axis=0)
    for index, points in enumerate(corners.copy()):
        shift = min(
            (0, 2),
            key=lambda n: float(
                np.linalg.norm(
                    np.roll(points, n, axis=0) - points.mean(axis=0) - centered_reference
                )
            ),
        )
        corners[index] = np.roll(points, shift, axis=0)
        correspondence_shifts.append(shift)
    aligned, transforms = [], []
    for points in corners:
        points_aligned, transform = rigid_to_reference(points, reference)
        aligned.append(points_aligned)
        transforms.append(transform)
    angles = np.array([d["geometry"]["angle_degrees_modulo_180"] for d in detections])
    angles = np.rad2deg(np.unwrap(np.deg2rad(angles) * 2) / 2)
    small_pose_changes = bool(np.max(np.abs(angles - angles[0])) < 45)
    raw = {
        "corner_coordinates_pixels": summary(corners),
        "corner_radial_maximum_deviation_from_mean_pixels": np.linalg.norm(
            corners - corners.mean(axis=0), axis=2
        )
        .max(axis=0)
        .tolist(),
        "signed_side_offsets_at_reference_midpoints_pixels": summary(
            [side_offsets(p, reference) for p in corners]
        ),
        "width_pixels": summary([d["geometry"]["width_pixels"] for d in detections]),
        "height_pixels": summary([d["geometry"]["height_pixels"] for d in detections]),
        "angle_degrees_unwrapped_modulo_180": summary(angles),
        "center_pixels": summary([d["geometry"]["center_pixels"] for d in detections]),
    }
    millimeters = [d["geometry"]["millimeters_from_reported_dpi"] for d in detections]
    raw["width_millimeters_from_reported_dpi"] = (
        summary([m["width"] for m in millimeters]) if all(millimeters) else None
    )
    raw["height_millimeters_from_reported_dpi"] = (
        summary([m["height"] for m in millimeters]) if all(millimeters) else None
    )
    aligned_array = np.asarray(aligned)
    review = any(d["status"] != "success" for d in detections)
    same_dimensions = (
        len(
            {
                tuple((a["source"]["image"]["frames"][0][k] for k in ("width", "height")))
                for a in analyses
            }
        )
        == 1
    )
    dpi_values = [a.get("dpi") for a in analyses]
    same_dpi = all(isinstance(dpi, (list, tuple)) and len(dpi) == 2 for dpi in dpi_values)
    if same_dpi:
        try:
            dpi_array = np.asarray(dpi_values, dtype=float)
            same_dpi = bool(np.isfinite(dpi_array).all() and np.max(np.ptp(dpi_array, axis=0)) <= 1)
        except (TypeError, ValueError):
            same_dpi = False
    control_differences = {}
    controls_unavailable = []
    for name in (
        "ICAP_XRESOLUTION",
        "ICAP_YRESOLUTION",
        "ICAP_PIXELTYPE",
        "ICAP_BITDEPTH",
        "ICAP_GAMMA",
        "ICAP_CONTRAST",
        "ICAP_BRIGHTNESS",
    ):
        values = [
            ((a.get("source", {}).get("acquisition") or {}).get("transfer_time_settings") or {})
            .get(name, {})
            .get("current")
            for a in analyses
        ]
        if any(v is None for v in values):
            controls_unavailable.append(name)
        elif any(v != values[0] for v in values[1:]):
            control_differences[name] = values
    return {
        "status": "review_required"
        if review
        or not same_dimensions
        or not same_dpi
        or control_differences
        or not small_pose_changes
        else "success",
        "sample_count": len(analyses),
        "same_image_dimensions": same_dimensions,
        "consistent_reported_dpi": same_dpi,
        "corner_correspondence_cyclic_shifts": correspondence_shifts,
        "correspondence_pose_change_below_45_degrees": small_pose_changes,
        "reported_acquisition_control_differences": control_differences,
        "acquisition_controls_unavailable_for_comparison": controls_unavailable,
        "independence": "Distinct hashes checked; separate acquisitions and stationary card are operator assertions, not proven",
        "raw_image_coordinates": raw,
        "shape_only_rigid_registered": {
            "reference_scan": 0,
            "method": "Least-squares proper 2D rigid transform of corresponding theoretical corners; no scale or reflection",
            "transforms": transforms,
            "corner_coordinates_pixels": summary(aligned_array),
            "signed_side_offsets_at_reference_midpoints_pixels": summary(
                [side_offsets(p, reference) for p in aligned_array]
            ),
            "corner_radial_maximum_deviation_from_mean_pixels": np.linalg.norm(
                aligned_array - aligned_array.mean(axis=0), axis=2
            )
            .max(axis=0)
            .tolist(),
        },
        "interpretation": "Registration removes global translation/rotation, including possible origin shifts; cannot distinguish scanner origin movement from card movement. Shape-derived registration can absorb detector errors.",
        "accuracy_calibration": False,
        "physical_identity_or_print_orientation_verified": False,
    }
