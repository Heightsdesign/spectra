from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

from spectra_scanner.common import AgentError, utc_now, write_json_new
from spectra_scanner.storage import sha256_file

from . import CONFIGURATION_VERSION, __version__
from .detector import detect, measurements
from .inputs import read_inputs


def diagnostics(rgb: Any, corners: Any, sides: list[dict[str, Any]], output: Path) -> list[str]:
    canvas = Image.fromarray(rgb)
    draw = ImageDraw.Draw(canvas)
    draw.line([tuple(p) for p in corners] + [tuple(corners[0])], fill="cyan", width=3)
    colors = ("magenta", "orange", "purple", "red", "blue", "yellow")
    for side in sides:
        for j, candidate in enumerate(side["candidates"]):
            points = candidate["support_points_pixels"]
            color = (
                "lime"
                if candidate["id"] == side["selected_candidate_id"]
                else colors[j % len(colors)]
            )
            for x, y in points:
                draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill=color)
            line = candidate["line_abc"]
            if line is not None:
                a, b, c = line
                tangent = np.array([-b, a])
                midpoint = (corners[side["index"]] + corners[(side["index"] + 1) % 4]) / 2
                midpoint -= (np.dot(midpoint, line[:2]) + c) * np.array(line[:2])
                length = (
                    np.linalg.norm(corners[(side["index"] + 1) % 4] - corners[side["index"]]) / 2
                )
                draw.line(
                    [tuple(midpoint - length * tangent), tuple(midpoint + length * tangent)],
                    fill=color,
                    width=2,
                )
                draw.text(
                    tuple(midpoint),
                    candidate["id"],
                    fill=color,
                    stroke_width=1,
                    stroke_fill="black",
                )
    with (output / "overlay.png").open("xb") as handle:
        canvas.save(handle, format="PNG")
    artifacts = ["overlay.png"]
    for side in sides:
        i = side["index"]
        ends = corners[[i, (i + 1) % 4]]
        padding = max(30, int(np.linalg.norm(corners[(i + 2) % 4] - corners[(i + 1) % 4]) * 0.15))
        box = (
            max(0, int(ends[:, 0].min() - padding)),
            max(0, int(ends[:, 1].min() - padding)),
            min(rgb.shape[1], int(ends[:, 0].max() + padding)),
            min(rgb.shape[0], int(ends[:, 1].max() + padding)),
        )
        crop = canvas.crop(box)
        panel = Image.new(
            "RGB", (max(crop.width, 700), crop.height + 80 + 22 * len(side["candidates"])), "white"
        )
        panel.paste(crop, (0, 0))
        text = ImageDraw.Draw(panel)
        text.text(
            (5, crop.height + 5),
            f"{side['name']} | physical: cyan | selected: lime | multiple eligible: ambiguous",
            fill="black",
        )
        for j, candidate in enumerate(side["candidates"]):
            text.text(
                (5, crop.height + 28 + 22 * j),
                f"{candidate['id']}: d={candidate['distance_pixels']:.2f}px support={candidate['support_fraction']:.3f} transition={candidate['transition_rgb_rms']:.1f} | {','.join(candidate['rejection_reasons']) or 'eligible'}",
                fill="black",
            )
        name = f"side-{side['name']}.png"
        with (output / name).open("xb") as handle:
            panel.save(handle, format="PNG")
        artifacts.append(name)
    return artifacts


def analyze(image: Path, upstream: Path, output: Path, config: dict[str, Any]) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {
        "schema_version": 1,
        "kind": "printed_frame_analysis",
        "algorithm_version": __version__,
        "configuration_version": CONFIGURATION_VERSION,
        "configuration": config,
        "software": {"opencv": cv2.__version__, "numpy": np.__version__},
        "inputs": {
            "image_path": str(image.resolve()),
            "boundary_report_path": str(upstream.resolve()),
        },
        "created_at_utc": utc_now(),
        "status": "analysis_failed",
        "automatic_acceptance": False,
        "physical_scan_performed": False,
        "quality_flags": ["experimental_uncalibrated"],
        "measurements": None,
        "artifacts": [],
        "coordinate_system": "Original pixels; card-local top/right/bottom/left follow ordered S2.1 corners, not printed upright orientation",
        "uncertainty": "Physical-boundary uncertainty and printed-frame uncertainty both contribute. Residuals and scores are not calibrated accuracy, probabilities or confidence intervals.",
    }
    try:
        report["inputs"]["image_sha256"] = sha256_file(image)
        report["inputs"]["boundary_report_sha256"] = sha256_file(upstream)
        rgb, evidence = read_inputs(image, upstream)
        if (
            report["inputs"]["image_sha256"] != evidence["source"]["sha256"]
            or report["inputs"]["boundary_report_sha256"] != evidence["boundary_report"]["sha256"]
        ):
            raise AgentError("source_changed", "Inputs changed during validation")
        report.update(evidence)
        report["quality_flags"] = ["experimental_uncalibrated"] + evidence["quality_flags"]
        corners = np.asarray(evidence["physical_corners_pixels"])
        transform = cv2.getPerspectiveTransform(
            corners.astype(np.float32), np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
        )
        report["original_pixels_to_card_unit_square"] = transform.tolist()
        report["card_unit_square_to_original_pixels"] = np.linalg.inv(transform).tolist()
        sides = detect(rgb, corners, config)
        report["sides"] = sides
        report["status"] = "review_required"
        if all(s["selected_candidate_id"] is not None for s in sides):
            colors = np.array([s["border_rgb"] for s in sides])
            difference = float(
                max(np.linalg.norm(a - b) / np.sqrt(3) for a in colors for b in colors)
            )
            report["cross_side_outer_band_difference_rgb"] = difference
            if difference <= config["maximum_cross_side_border_color_difference"]:
                report["measurements"] = measurements(corners, sides, evidence["dpi"], config)
                report["frame_evidence_status"] = "supported"
                report["quality_flags"].append("ratios_conditional_on_selected_physical_geometry")
            else:
                report["frame_evidence_status"] = "insufficient"
                report["quality_flags"].append("inconsistent_traditional_outer_frame_color")
        elif any(s["ambiguous"] for s in sides):
            report["frame_evidence_status"] = "ambiguous"
            report["quality_flags"].append("competing_printed_boundaries")
        else:
            report["status"] = "not_applicable"
            report["frame_evidence_status"] = "insufficient"
            report["quality_flags"].append(
                "traditional_frame_pattern_not_supported_not_proof_of_borderlessness"
            )
        report["artifacts"] = diagnostics(rgb, corners, sides, output)
        if (
            sha256_file(image) != evidence["source"]["sha256"]
            or sha256_file(upstream) != evidence["boundary_report"]["sha256"]
        ):
            raise AgentError("source_changed", "Input changed during analysis")
        report["input_hashes_verified_after_analysis"] = True
    except (AgentError, OSError, ValueError, TypeError, KeyError, AttributeError, cv2.error) as exc:
        report.update(
            status="analysis_failed",
            measurements=None,
            input_hashes_verified_after_analysis=False,
            error={
                "code": getattr(exc, "status", "invalid_input_or_geometry"),
                "message": str(exc),
            },
        )
    write_json_new(output / "report.json", report)
    return report
