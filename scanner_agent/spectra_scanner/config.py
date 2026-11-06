"""Explicit user configuration; these values are requests, never device evidence."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from .common import AgentError

DEFAULTS: dict[str, Any] = {
    "device_model": "Epson Perfection V39 II",
    "manual_profile": "SPECTRA_CARD_600DPI",
    "dpi": 600,
    "gamma": 1.0,
    "contrast": 0.0,
    "color_mode": "RGB",
    "bits_per_pixel": 24,
    "preferred_format": "PNG",
    "enhancement": False,
    "deskew": False,
    "automatic_crop": False,
    "automatic_rotation": False,
    "scan_region": None,
    "expected_dimensions": None,
    "dimension_tolerance_pixels": 2,
    "dpi_tolerance": 1.0,
    "safety_margin_mm": 2.0,
}


def number(value: Any, name: str, minimum: float, *, positive: bool = False) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < minimum
        or (positive and value == 0)
    ):
        raise AgentError("invalid_config", f"{name} must be a finite valid number")
    return float(value)


def validate_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.keys() - DEFAULTS.keys():
        raise AgentError("invalid_config", "Configuration must contain only documented keys")
    config = {**deepcopy(DEFAULTS), **deepcopy(value)}
    for key in ("device_model", "manual_profile"):
        if not isinstance(config[key], str) or not config[key].strip():
            raise AgentError("invalid_config", f"{key} must be a nonempty string")
    number(config["dpi"], "dpi", 1)
    gamma = number(config["gamma"], "gamma", 0.5)
    if gamma > 3.0:
        raise AgentError("invalid_config", "S1 experimental gamma must be between 0.5 and 3.0")
    contrast = number(config["contrast"], "contrast", -1000)
    if contrast > 1000:
        raise AgentError("invalid_config", "TWAIN contrast must be between -1000 and 1000")
    if config["dpi"] > 4800:
        raise AgentError("invalid_config", "DPI exceeds the S1 safety limit of 4800")
    for key, expected in (
        ("color_mode", "RGB"),
        ("bits_per_pixel", 24),
        ("preferred_format", "PNG"),
        ("enhancement", False),
        ("deskew", False),
        ("automatic_crop", False),
        ("automatic_rotation", False),
    ):
        if config[key] != expected or type(config[key]) is not type(expected):
            raise AgentError("invalid_config", f"S1 requires {key}={expected!r}")
    for key in ("dimension_tolerance_pixels", "dpi_tolerance", "safety_margin_mm"):
        number(config[key], key, 0)
    region = config["scan_region"]
    if region is not None:
        if not isinstance(region, dict) or set(region) != {"x", "y", "width", "height", "units"}:
            raise AgentError("invalid_config", "Region requires x, y, width, height, units")
        if region["units"] not in ("mm", "inches"):
            raise AgentError("invalid_config", "Region units must be mm or inches")
        for key in ("x", "y", "width", "height"):
            # Origins may be signed; only driver-reported bounds establish their validity.
            number(
                region[key],
                f"scan_region.{key}",
                -1e6 if key in {"x", "y"} else 0,
                positive=key in {"width", "height"},
            )
    dimensions = config["expected_dimensions"]
    if dimensions is not None and (
        not isinstance(dimensions, list)
        or len(dimensions) != 2
        or any(type(v) is not int or v <= 0 for v in dimensions)
    ):
        raise AgentError("invalid_config", "expected_dimensions must be [positive width, height]")
    return config


def load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return validate_config({})
    try:
        return validate_config(json.loads(path.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError) as exc:
        raise AgentError("invalid_config", f"Cannot read configuration: {exc}") from exc


def region_inches(region: dict[str, Any]) -> tuple[float, float, float, float]:
    divisor = 25.4 if region["units"] == "mm" else 1.0
    x, y, width, height = (float(region[k]) / divisor for k in ("x", "y", "width", "height"))
    return x, y, x + width, y + height
