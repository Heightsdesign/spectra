"""Acquisition checks only. No card boundary detection or grading."""

from __future__ import annotations

import math
from typing import Any

from .config import region_inches


def acquisition_checks(image: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    frames = image["frames"]
    checks: dict[str, Any] = {
        "decode": {"status": "pass", "evidence": "complete pixel stream decoded"},
        "nonempty": {
            "status": "pass",
            "scope": "nonzero file and pixel dimensions; not card content",
        },
        "rgb24": {
            "status": "pass"
            if image["frame_count"] == 1
            and all(f["mode"] == "RGB" and f["bits_per_pixel"] == 24 for f in frames)
            else "fail"
        },
        "content_variation": {
            "status": "fail" if any(f.get("uniform_pixel_content") for f in frames) else "pass",
            "scope": "Reject completely uniform images only; does not prove card presence or usable exposure",
        },
        "physical_card_margin": {
            "status": "pending_s2_1",
            "requested_mm": config["safety_margin_mm"],
            "reason": "Physical edges must be detected or reviewed; S1 does not detect boundaries",
        },
    }
    expected = config["expected_dimensions"]
    basis = "user_configured_dimensions"
    if expected is None and config["scan_region"] is not None:
        left, top, right, bottom = region_inches(config["scan_region"])
        expected = [round((right - left) * config["dpi"]), round((bottom - top) * config["dpi"])]
        basis = "user_requested_region_and_dpi"
    checks["dimensions"] = {
        "status": "pending",
        "reason": "No expected region/dimensions configured",
    }
    if expected is not None:
        checks["dimensions"] = {
            "status": "pass"
            if all(
                abs(f[k] - expected[i]) <= config["dimension_tolerance_pixels"]
                for f in frames
                for i, k in enumerate(("width", "height"))
            )
            else "fail",
            "expected": expected,
            "basis": basis,
            "tolerance_pixels": config["dimension_tolerance_pixels"],
        }
    dpi_values = [f["dpi_metadata"] for f in frames]
    checks["dpi"] = {"status": "pending", "reason": "DPI metadata absent"}
    if all(dpi_values):
        checks["dpi"] = {
            "status": "pass"
            if all(
                len(dpi) == 2
                and all(
                    math.isfinite(v) and abs(v - config["dpi"]) <= config["dpi_tolerance"]
                    for v in dpi
                )
                for dpi in dpi_values
            )
            else "fail",
            "basis": "embedded metadata compared with user request; not optical calibration",
            "observed": dpi_values,
            "requested": config["dpi"],
        }
    checks["orientation"] = {
        "status": "fail" if any(f.get("orientation_tag", 1) != 1 for f in frames) else "pass",
        "scope": "encoded orientation tag only; no rotation applied",
    }
    return {
        "status": "fail" if any(c["status"] == "fail" for c in checks.values()) else "pending",
        "checks": checks,
        "card_content_verified": False,
        "calibration_verified": False,
    }
