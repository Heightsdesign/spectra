"""Read-only support/filter ablations; rejected fits never become detector output."""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

from spectra_boundary.controlled_layers import (
    MAXIMUM_ANCHOR_MOVEMENT,
    SUPPORT_RADIUS,
    quality,
    reassign,
)
from spectra_boundary.detector import line_fit
from spectra_boundary.layers import evidence, samples
from spectra_scanner.common import write_json_new
from spectra_scanner.storage import sha256_file

from .model import load_image, load_report


def investigate(
    image: Path, report_path: Path, output: Path, side_index: int = 2
) -> dict[str, Any]:
    protected = {
        p: sha256_file(p)
        for p in (image, report_path, image.parent / "metadata.json")
        if p.exists()
    }
    rgb, identity = load_image(image)
    report = load_report(report_path, identity)
    if report["algorithm_version"] != "0.2.0":
        raise ValueError("Refit investigation starts from frozen 0.2.0 evidence")
    config = report["configuration"]
    side = report["baseline"]["sides"][side_index]
    selected = next(layer for layer in side["candidate_layers"] if layer["selected"])
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    ys, xs = np.nonzero(cv2.Canny(gray, config["canny_low"], config["canny_high"]))
    all_points = np.column_stack([xs, ys]).astype(float)
    start, end = np.asarray(side["seed_start_pixels"]), np.asarray(side["seed_end_pixels"])
    vector = end - start
    length = np.linalg.norm(vector)
    tangent, normal = vector / length, np.asarray(side["inward_normal"])
    t = (all_points - start) @ tangent / length
    offset = (all_points - start) @ normal
    exclusion, band = config["corner_exclusion_fraction"], side["search_half_width_pixels"]
    domain = (t >= exclusion) & (t <= 1 - exclusion) & (np.abs(offset) <= band)
    points, offsets, ts = all_points[domain], offset[domain], t[domain]
    seed = np.abs(offsets - selected["density_peak_offset_inward_pixels"]) <= 2
    _, residual = line_fit(points[seed])
    original = np.zeros(len(points), bool)
    original[np.flatnonzero(seed)[residual <= max(1.5, config["maximum_rms_pixels"] * 2)]] = True
    reconstructed, _ = line_fit(points[original])
    if len(points[original]) != selected["support_count"] or not np.allclose(
        reconstructed, selected["line_abc"], atol=1e-9, rtol=0
    ):
        raise ValueError("Frozen candidate reconstruction failed")
    anchor = np.asarray(selected["line_abc"])
    distance = np.abs(points @ anchor[:2] + anchor[2])
    radius = distance <= SUPPORT_RADIUS
    ownership = np.ones(len(points), bool)
    competitors = []
    for other in side["candidate_layers"]:
        metric = other["raw_evidence"]
        if other["id"] == selected["id"] or not metric.get("available"):
            continue
        coherent = (
            metric["gradient_polarity_fraction"]
            >= config["physical_boundary"]["minimum_polarity_fraction"]
            and metric["signed_inward_drop_gray"] >= config["physical_boundary"]["minimum_raw_drop"]
        )
        other_line = np.asarray(other["line_abc"])
        mask = distance + 0.25 < np.abs(points @ other_line[:2] + other_line[2])
        competitors.append(
            {
                "id": other["id"],
                "coherent_darkening": coherent,
                "criterion_failures": other["criterion_failures"],
                "radius_points_vetoed": int(np.count_nonzero(radius & ~mask)) if coherent else 0,
            }
        )
        if coherent:
            ownership &= mask
    probes, valid = samples(
        gray, points[:, None, :] + np.array([-2, -1, 1, 2])[None, :, None] * normal
    )
    photometry = (
        valid.all(axis=1)
        & (probes[:, 0] - probes[:, 3] >= config["physical_boundary"]["minimum_raw_drop"])
        & (probes[:, 1] > probes[:, 2])
    )
    masks = {
        "original_seed_support": original,
        "radius_only": radius,
        "radius_and_ownership": radius & ownership,
        "radius_and_photometry": radius & photometry,
        "final_reassignment_proposal": radius & ownership & photometry,
    }
    centers = (
        start
        + np.linspace(exclusion, 1 - exclusion, config["physical_boundary"]["profile_samples"])[
            :, None
        ]
        * vector
    )
    raw_offsets = np.arange(-np.ceil(band) - 12, np.ceil(band) + 13)
    raw, valid = samples(gray, centers[:, None, :] + raw_offsets[None, :, None] * normal)
    background = np.array(
        [
            np.median(row[np.flatnonzero(ok)[:8]]) if ok.any() else np.nan
            for row, ok in zip(raw, valid, strict=True)
        ]
    )
    profile_centers = start + np.linspace(exclusion, 1 - exclusion, 401)[:, None] * vector

    def line_offsets(line: Any) -> Any:
        return -(profile_centers @ line[:2] + line[2]) / (normal @ line[:2])

    metrics = {}
    fitted = {}
    bin_ids = np.clip(np.floor((ts - exclusion) / (1 - 2 * exclusion) * 40), 0, 39).astype(int)
    for name, mask in masks.items():
        fit, residual = line_fit(points[mask])
        fitted[name] = fit
        counts = np.bincount(bin_ids[mask], minlength=40)
        coverage = np.count_nonzero(counts) / 40
        metric = evidence(
            gray,
            centers,
            normal,
            fit,
            background,
            config["physical_boundary"],
            max(48, int(2 * band + 16)),
        )
        rms = float(np.sqrt(np.mean(residual**2)))
        failures, _ = quality(metric, coverage, rms, config)
        displacement = line_offsets(fit) - line_offsets(anchor)
        # Signed orthogonal distance along anchor inward normal, separately from
        # the seed-normal offset used by the experiment's exact 0.5px guard.
        anchor_normal = anchor[:2].copy()
        if anchor_normal @ normal < 0:
            anchor_normal = -anchor_normal
        anchor_points = profile_centers + line_offsets(anchor)[:, None] * normal
        normal_delta = -(anchor_points @ fit[:2] + fit[2]) / (anchor_normal @ fit[:2])
        metrics[name] = {
            "line_abc": fit.tolist(),
            "support_count": int(mask.sum()),
            "coverage": float(coverage),
            "counts_40_bins": counts.tolist(),
            "rms_pixels": rms,
            "raw_evidence": metric,
            "criterion_failures": failures,
            "seed_normal_displacement_profile_pixels": displacement.tolist(),
            "orthogonal_displacement_profile_pixels": normal_delta.tolist(),
            "displacement_start_middle_end_pixels": displacement[[0, 200, 400]].tolist(),
            "maximum_movement_pixels": float(np.max(np.abs(displacement))),
            "original_overlap_count": int(np.count_nonzero(mask & original)),
            "new_points_count": int(np.count_nonzero(mask & ~original)),
            "removed_original_points": int(np.count_nonzero(original & ~mask)),
            "diagnostic_only_not_accepted": name != "original_seed_support",
        }
    check = deepcopy(selected)
    reassign(check, side["candidate_layers"], points, start, end, gray, config, line_fit, band)
    exact = check["support_reassignment"]
    final = metrics["final_reassignment_proposal"]
    if not np.isclose(
        final["maximum_movement_pixels"], exact["maximum_movement_pixels"], atol=1e-9
    ):
        raise ValueError("Diagnostic ablation differs from experiment")
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "kind": "physical_refit_displacement_investigation",
        "image": identity,
        "source_report_sha256": sha256_file(report_path),
        "side": side_index,
        "frozen_selected_candidate": selected,
        "candidates": competitors,
        "metrics": metrics,
        "span_fractions": np.linspace(exclusion, 1 - exclusion, 401).tolist(),
        "exact_experiment_decision": exact,
        "guard_unchanged_pixels": MAXIMUM_ANCHOR_MOVEMENT,
        "points_original_pixels": points.tolist(),
        "point_seed_offsets": offsets.tolist(),
        "point_memberships": {name: mask.tolist() for name, mask in masks.items()},
        "physical_reference_available": False,
        "geometry_installed": False,
    }
    write_json_new(output / "measurements.json", result)
    colors = {
        "original_seed_support": "green",
        "radius_only": "#888888",
        "radius_and_ownership": "#d08000",
        "radius_and_photometry": "#2050ef",
        "final_reassignment_proposal": "#d020b0",
    }
    chart = Image.new("RGB", (1450, 1000), "white")
    draw = ImageDraw.Draw(chart)
    for j, (name, mask) in enumerate(masks.items()):
        y0 = 35 + j * 190
        draw.text(
            (10, y0),
            f"{name}: {metrics[name]['support_count']} points; coverage={metrics[name]['coverage']}; diagnostic only",
            fill="black",
        )
        for lo in (-2, -1, 0, 1, 2):
            grid_y = y0 + 90 - lo * 25
            draw.line((70, grid_y, 1380, grid_y), fill="#dddddd")
            draw.text((10, grid_y), str(lo), fill="black")
        for p, u in zip(points[mask], ts[mask], strict=True):
            d = float((p @ anchor[:2] + anchor[2]) / (normal @ anchor[:2]))
            x, y = 70 + (u - exclusion) / (1 - 2 * exclusion) * 1310, y0 + 90 - d * 25
            draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill=colors[name])
    chart.save(output / "support-memberships.png")
    chart = Image.new("RGB", (1450, 650), "white")
    draw = ImageDraw.Draw(chart)
    draw.text(
        (15, 15),
        "Line displacement vs frozen L0 (seed inward normal); guard unchanged +/-0.5 px; all proposals diagnostic",
        fill="black",
    )
    for grid_value in (-1.0, -0.5, 0.0, 0.5, 1.0):
        at = 300 - grid_value * 200
        draw.line((60, at, 1380, at), fill="red" if abs(grid_value) == 0.5 else "#dddddd")
        draw.text((10, at), str(grid_value), fill="black")
    for j, (name, metric) in enumerate(metrics.items()):
        values = metric["seed_normal_displacement_profile_pixels"]
        draw.line(
            [(60 + i / 400 * 1320, 300 - v * 200) for i, v in enumerate(values)],
            fill=colors[name],
            width=2,
        )
        draw.text((60, 540 + j * 18), name, fill=colors[name])
    chart.save(output / "displacement-profiles.png")
    # Lossless original-pixel crop and separate marked overlay. Only derivatives
    # are magnified; the BMP and encoded metadata remain byte-identical.
    crop_points = start + np.array([exclusion, 1 - exclusion])[:, None] * vector
    crop_points += line_offsets(anchor)[[0, -1], None] * normal
    lo = np.maximum(0, np.floor(crop_points.min(axis=0) - 20).astype(int))
    hi = np.minimum(
        np.array(identity["dimensions"]), np.ceil(crop_points.max(axis=0) + 20).astype(int)
    )
    raw_crop = Image.fromarray(rgb[lo[1] : hi[1], lo[0] : hi[0]])
    raw_crop.resize((raw_crop.width * 4, raw_crop.height * 4), Image.Resampling.NEAREST).save(
        output / "original-crop-4x.png"
    )
    marked = raw_crop.copy()
    painter = ImageDraw.Draw(marked)
    for name in ("original_seed_support", "final_reassignment_proposal"):
        for p in points[masks[name]]:
            painter.point(tuple(p - lo), fill=colors[name])
    marked.resize((marked.width * 4, marked.height * 4), Image.Resampling.NEAREST).save(
        output / "support-overlay-4x.png"
    )
    changed = [str(p) for p, expected in protected.items() if sha256_file(p) != expected]
    write_json_new(
        output / "integrity.json",
        {"protected": {str(p): v for p, v in protected.items()}, "changed_files": changed},
    )
    if changed:
        raise ValueError("Protected investigation inputs changed")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--side", type=int, choices=range(4), default=2)
    args = parser.parse_args()
    investigate(args.image, args.report, args.output, args.side)
