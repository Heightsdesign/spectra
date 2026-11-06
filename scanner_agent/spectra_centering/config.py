from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from spectra_scanner.common import AgentError

DEFAULTS: dict[str, Any] = {
    "mode": "traditional_frame",
    "search_min_fraction": 0.008,
    "search_max_fraction": 0.12,
    "corner_exclusion_fraction": 0.18,
    "profile_count": 120,
    "minimum_color_transition": 12.0,
    "minimum_support_fraction": 0.80,
    "maximum_fit_rms_pixels": 1.5,
    "maximum_angle_difference_degrees": 3.0,
    "maximum_outer_band_color_deviation": 22.0,
    "maximum_cross_side_border_color_difference": 35.0,
    "candidate_separation_pixels": 5,
    "maximum_candidates_per_side": 12,
    "margin_sample_count": 21,
}


def validate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.keys() - DEFAULTS.keys():
        raise AgentError("invalid_configuration", "Unknown printed-frame configuration keys")
    result = {**deepcopy(DEFAULTS), **deepcopy(value)}
    if result["mode"] != "traditional_frame":
        raise AgentError("unsupported_mode", "Only traditional_frame is supported")
    for key in result.keys() - {"mode"}:
        v = result[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
            raise AgentError("invalid_configuration", f"{key} must be finite and positive")
    if not 0 < result["search_min_fraction"] < result["search_max_fraction"] <= 0.25:
        raise AgentError(
            "invalid_configuration", "Search fractions must satisfy 0 < min < max <= 0.25"
        )
    if not 0 < result["corner_exclusion_fraction"] < 0.4 or result["minimum_support_fraction"] > 1:
        raise AgentError("invalid_configuration", "Invalid support or corner-exclusion fraction")
    for key, low, high in (
        ("profile_count", 40, 1000),
        ("candidate_separation_pixels", 3, 30),
        ("maximum_candidates_per_side", 1, 30),
        ("margin_sample_count", 5, 101),
    ):
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise AgentError("invalid_configuration", f"Invalid integer {key}")
    return result


def load(path: Path | None) -> dict[str, Any]:
    if path is None:
        return validate({})
    try:
        return validate(json.loads(path.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError) as exc:
        raise AgentError("invalid_configuration", str(exc)) from exc
