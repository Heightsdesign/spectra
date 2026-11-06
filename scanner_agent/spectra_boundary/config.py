from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from spectra_scanner.common import AgentError

DEFAULTS: dict[str, Any] = {
    "reference_width_mm": 63.0,
    "reference_height_mm": 88.0,
    "dimension_tolerance_fraction": 0.10,
    "aspect_tolerance_fraction": 0.08,
    "minimum_margin_pixels": 12,
    "maximum_angle_error_degrees": 4.0,
    "maximum_rms_pixels": 2.0,
    "minimum_side_coverage": 0.65,
    "corner_exclusion_fraction": 0.18,
    "side_search_fraction": 0.025,
    "minimum_candidate_area_fraction": 0.08,
    "ambiguity_area_ratio": 0.60,
    "canny_low": 30,
    "canny_high": 90,
    "preprocessing": {"normalize_percentiles": None, "contrast": 1.0},
    "physical_boundary": {
        "profile_samples": 160,
        "minimum_raw_drop": 20.0,
        "minimum_polarity_fraction": 0.75,
        "minimum_sharpness_ratio": 1.15,
        "maximum_exterior_deficit_fraction": 0.35,
        "maximum_clear_exterior_deficit_fraction": 0.15,
    },
}


def configuration(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.keys() - DEFAULTS.keys():
        raise AgentError("invalid_config", "Unknown S2.1 configuration keys")
    result = {**deepcopy(DEFAULTS), **deepcopy(value)}
    for key in DEFAULTS.keys() - {"preprocessing", "physical_boundary"}:
        v = result[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
            raise AgentError("invalid_config", f"{key} must be finite and positive")
    for key in (
        "dimension_tolerance_fraction",
        "aspect_tolerance_fraction",
        "minimum_side_coverage",
        "side_search_fraction",
        "minimum_candidate_area_fraction",
        "ambiguity_area_ratio",
    ):
        if result[key] >= 1:
            raise AgentError("invalid_config", f"{key} must be less than one")
    if result["reference_width_mm"] >= result["reference_height_mm"]:
        raise AgentError("invalid_config", "Reference width must be the shorter dimension")
    if not 0 < result["corner_exclusion_fraction"] < 0.4:
        raise AgentError("invalid_config", "Corner exclusion must be between 0 and 0.4")
    if not result["canny_low"] < result["canny_high"] <= 255:
        raise AgentError("invalid_config", "Invalid Canny thresholds")
    prep = result["preprocessing"]
    if not isinstance(prep, dict) or prep.keys() - {"normalize_percentiles", "contrast"}:
        raise AgentError("invalid_config", "Unknown preprocessing settings")
    prep = {"normalize_percentiles": None, "contrast": 1.0, **prep}
    contrast = prep["contrast"]
    if (
        isinstance(contrast, bool)
        or not isinstance(contrast, (int, float))
        or not math.isfinite(contrast)
        or not 0.25 <= contrast <= 2
    ):
        raise AgentError("invalid_config", "Working-image contrast must be between 0.25 and 2")
    limits = prep["normalize_percentiles"]
    if limits is not None and (
        not isinstance(limits, list)
        or len(limits) != 2
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in limits)
        or not 0 <= limits[0] < limits[1] <= 100
    ):
        raise AgentError("invalid_config", "Normalization requires [low, high] percentiles")
    result["preprocessing"] = prep
    physical = result["physical_boundary"]
    if not isinstance(physical, dict) or physical.keys() - DEFAULTS["physical_boundary"].keys():
        raise AgentError("invalid_config", "Unknown physical-boundary criteria")
    physical = {**DEFAULTS["physical_boundary"], **physical}
    for key, v in physical.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
            raise AgentError("invalid_config", f"Invalid physical_boundary.{key}")
    if (
        type(physical["profile_samples"]) is not int
        or not 40 <= physical["profile_samples"] <= 2000
    ):
        raise AgentError(
            "invalid_config", "Profile sample count must be an integer from 40 to 2000"
        )
    if (
        not physical["maximum_clear_exterior_deficit_fraction"]
        <= physical["maximum_exterior_deficit_fraction"]
        < 1
        or physical["minimum_polarity_fraction"] > 1
    ):
        raise AgentError("invalid_config", "Invalid physical-boundary fractions")
    result["physical_boundary"] = physical
    return result


def load(path: Path | None) -> dict[str, Any]:
    if path is None:
        return configuration({})
    try:
        return configuration(json.loads(path.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError) as exc:
        raise AgentError("invalid_config", str(exc)) from exc
