from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

from spectra_centering.analysis import diagnostics
from spectra_centering.config import validate as detector_configuration
from spectra_centering.detector import detect
from spectra_centering.inputs import read_inputs
from spectra_scanner.common import AgentError, utc_now, write_json_new
from spectra_scanner.storage import sha256_file

from . import __version__
from .evaluation import DEFAULTS, evaluate_candidates, hypotheses


def configuration(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.keys() - {"candidate_generation", "evaluation"}:
        raise AgentError(
            "invalid_configuration", "Expected candidate_generation and evaluation sections"
        )
    evaluation = value.get("evaluation", {})
    if not isinstance(evaluation, dict) or evaluation.keys() - DEFAULTS.keys():
        raise AgentError("invalid_configuration", "Unknown evaluation parameter")
    evaluation = {**DEFAULTS, **evaluation}
    for key, number in evaluation.items():
        if type(number) not in (int, float) or not math.isfinite(number) or number <= 0:
            raise AgentError("invalid_configuration", f"Invalid {key}")
    if type(evaluation["maximum_hypotheses"]) is not int or evaluation["maximum_hypotheses"] > 4096:
        raise AgentError(
            "invalid_configuration", "maximum_hypotheses must be an integer in 1..4096"
        )
    if (
        evaluation["minimum_transition_direction_fraction"] > 1
        or max(
            evaluation["maximum_opposite_angle_degrees"],
            evaluation["maximum_adjacent_deviation_degrees"],
        )
        >= 45
    ):
        raise AgentError("invalid_configuration", "Invalid geometric or direction limit")
    return {
        "candidate_generation": detector_configuration(value.get("candidate_generation", {})),
        "evaluation": evaluation,
    }


def comparison_image(
    rgb: Any, corners: Any, evaluation: dict[str, Any], output: Path
) -> dict[str, Any]:
    frames = evaluation["hypotheses"]
    # Prefer valid hypotheses, but show rejected geometry if none is valid.
    shown = ([f for f in frames if f["geometrically_valid"]] or frames)[:12]
    width, height = 400, 560
    panel = Image.new("RGB", (width * 3, height * max(1, math.ceil(len(shown) / 3))), "white")
    for index, frame in enumerate(shown):
        tile = Image.fromarray(rgb)
        draw = ImageDraw.Draw(tile)
        draw.line([tuple(p) for p in corners] + [tuple(corners[0])], fill="cyan", width=4)
        points = frame.get("corners_pixels")
        if points:
            draw.line([tuple(p) for p in points] + [tuple(points[0])], fill="magenta", width=4)
        tile.thumbnail((width, height - 90))
        x, y = (index % 3) * width, (index // 3) * height
        panel.paste(tile, (x, y))
        text = ImageDraw.Draw(panel)
        text.text(
            (x + 4, y + height - 85),
            f"{frame['id']} | geometry={frame['geometrically_valid']}\nprovisional={frame['contains_provisional_candidates']}\n"
            + ", ".join(frame["candidate_ids"])
            + "\n"
            + ", ".join(frame["rejection_reasons"]),
            fill="black",
        )
    if not shown:
        ImageDraw.Draw(panel).text(
            (10, 10), "No complete retained four-sided combination", fill="black"
        )
    with (output / "hypotheses.png").open("xb") as handle:
        panel.save(handle, format="PNG")
    return {
        "file": "hypotheses.png",
        "shown_ids": [f["id"] for f in shown],
        "visualization_limited": len(shown) < len(frames),
        "legend": "cyan physical sides; magenta candidate printed frame; geometry is not semantic validation",
    }


def analyze(image: Path, upstream: Path, output: Path, config: dict[str, Any]) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    result: dict[str, Any] = {
        "schema_version": 1,
        "kind": "printed_frame_candidate_evaluation",
        "algorithm_version": __version__,
        "candidate_generator_version": "spectra_centering 0.1.0",
        "configuration_version": 1,
        "configuration": config,
        "created_at_utc": utc_now(),
        "software": {"numpy": np.__version__, "opencv": cv2.__version__},
        "status": "analysis_failed",
        "automatic_acceptance": False,
        "measurements": None,
        "physical_scan_performed": False,
        "input_hashes_verified_after_analysis": False,
        "inputs": {
            "image_path": str(image.resolve()),
            "boundary_report_path": str(upstream.resolve()),
        },
        "quality_flags": ["experimental_uncalibrated", "semantic_frame_identity_unverified"],
        "artifacts": [],
        "uncertainty": "Physical-boundary and printed-frame uncertainties both contribute; geometric evidence is not accuracy, calibrated probability or a confidence interval. Conditional hypothesis margins are original pixels, not accepted centering measurements.",
    }
    try:
        result["inputs"].update(
            image_sha256=sha256_file(image), boundary_report_sha256=sha256_file(upstream)
        )
        rgb, evidence = read_inputs(image, upstream)
        if (
            evidence["source"]["sha256"] != result["inputs"]["image_sha256"]
            or evidence["boundary_report"]["sha256"] != result["inputs"]["boundary_report_sha256"]
        ):
            raise AgentError("source_changed", "Inputs changed during validation")
        flags = result["quality_flags"] + evidence["quality_flags"]
        result.update(evidence)
        result["quality_flags"] = flags
        corners = np.asarray(evidence["physical_corners_pixels"])
        generated = detect(rgb, corners, config["candidate_generation"])
        sides = evaluate_candidates(
            rgb, corners, generated, config["candidate_generation"], config["evaluation"]
        )
        evaluation = hypotheses(
            corners, sides, config["candidate_generation"], config["evaluation"]
        )
        result.update(sides=sides, frame_evaluation=evaluation)
        if evaluation["search_truncated"]:
            result["status"] = "review_required"
            result["quality_flags"].append("search_truncated_selection_withheld")
            explanation = "Candidate or hypothesis search was truncated. Selection is withheld even if an explored combination appears unique."
        elif evaluation["valid_count"] == 0:
            result["status"] = "not_applicable"
            explanation = "No valid complete four-sided frame exists among retained candidates. Provisional retention alone does not justify a measurement; this is not proof of borderlessness."
        elif evaluation["valid_count"] > 1:
            result["status"] = "review_required"
            result["quality_flags"].append("competing_frame_hypotheses")
            explanation = f"{evaluation['valid_count']} geometrically plausible frames remain unresolved. Geometry cannot identify the intended printed border. No centering measurement is emitted."
        else:
            result["status"] = "review_required"
            explanation = "One complete geometric hypothesis remains. It is an investigation candidate, not a verified printed frame. Provisional rejection reasons and upstream uncertainty remain; no centering measurement is emitted."
        result["explanation"] = explanation
        decorated = deepcopy(sides)
        for side in decorated:
            side["selected_candidate_id"] = None
            for candidate in side["candidates"]:
                # Put status first in both overlay labels and per-side tables, so
                # long original rejection lists cannot clip the provisional label.
                candidate["id"] += "[" + candidate["retention"] + "]"
                candidate["rejection_reasons"] += candidate["additional_rejection_reasons"] + [
                    "S2.2b_" + candidate["retention"]
                ]
        result["artifacts"] = diagnostics(rgb, corners, decorated, output)
        result["hypothesis_visualization"] = comparison_image(rgb, corners, evaluation, output)
        result["artifacts"] += ["hypotheses.png", "explanation.txt"]
        with (output / "explanation.txt").open("x", encoding="utf-8") as handle:
            handle.write(explanation + "\n" + "\n".join(flags) + "\n")
        if (
            sha256_file(image) != result["inputs"]["image_sha256"]
            or sha256_file(upstream) != result["inputs"]["boundary_report_sha256"]
        ):
            raise AgentError("source_changed", "Input changed during analysis")
        result["input_hashes_verified_after_analysis"] = True
    except (AgentError, OSError, ValueError, TypeError, KeyError, AttributeError, cv2.error) as exc:
        result.update(
            status="analysis_failed",
            measurements=None,
            input_hashes_verified_after_analysis=False,
            error={
                "code": getattr(exc, "status", "invalid_input_or_geometry"),
                "message": str(exc),
            },
        )
    write_json_new(output / "report.json", result)
    return result


def load(path: Path | None) -> dict[str, Any]:
    return configuration(json.loads(path.read_text(encoding="utf-8-sig")) if path else {})
