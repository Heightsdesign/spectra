"""Read-only encoded-RGB comparisons of manually corresponding regions. No color correction."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image

from .common import AgentError, confined_data_dir, environment, identifier, utc_now, write_json_new
from .storage import inspect_image, sha256_file


def channel_statistics(histogram: list[int]) -> dict[str, Any]:
    count = sum(histogram)
    mean = sum(value * n for value, n in enumerate(histogram)) / count
    variance = sum(n * (value - mean) ** 2 for value, n in enumerate(histogram)) / count
    percentiles = {}
    for percentile in (1, 5, 25, 50, 75, 95, 99):
        target = math.ceil(count * percentile / 100)
        cumulative = 0
        for value, n in enumerate(histogram):
            cumulative += n
            if cumulative >= target:
                percentiles[str(percentile)] = value
                break
    occupied = [value for value, n in enumerate(histogram) if n]
    return {
        "histogram_256": histogram,
        "pixel_count": count,
        "mean": mean,
        "stddev": math.sqrt(variance),
        "min": min(occupied),
        "max": max(occupied),
        "percentiles": percentiles,
        "fraction_at_0": histogram[0] / count,
        "fraction_at_255": histogram[255] / count,
        "percentile_spread_p95_p5": percentiles["95"] - percentiles["5"],
        "interquartile_range": percentiles["75"] - percentiles["25"],
        "tonal_fractions": {
            "shadows_0_63": sum(histogram[:64]) / count,
            "midtones_64_191": sum(histogram[64:192]) / count,
            "highlights_192_255": sum(histogram[192:]) / count,
        },
    }


def distribution_deltas(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Code-value distribution changes; no optical contrast or sharpening inference."""
    output = {}
    for channel in "RGB":
        before, after = a[channel], b[channel]
        output[channel] = {
            key: after[key] - before[key]
            for key in (
                "stddev",
                "percentile_spread_p95_p5",
                "interquartile_range",
                "fraction_at_0",
                "fraction_at_255",
            )
        }
        output[channel]["percentile_deltas"] = {
            key: after["percentiles"][key] - before["percentiles"][key]
            for key in before["percentiles"]
        }
        output[channel]["tonal_fraction_deltas"] = {
            key: after["tonal_fractions"][key] - before["tonal_fractions"][key]
            for key in before["tonal_fractions"]
        }
    return output


def statistics(image: Any) -> dict[str, Any]:
    histogram = image.histogram()
    return {
        channel: channel_statistics(histogram[index * 256 : (index + 1) * 256])
        for index, channel in enumerate("RGB")
    }


def rectangle(value: Any, size: tuple[int, int]) -> tuple[int, int, int, int]:
    if not isinstance(value, list) or len(value) != 4 or any(type(v) is not int for v in value):
        raise AgentError("invalid_roi", "ROI requires integer [left, top, right, bottom] pixels")
    left, top, right, bottom = value
    if not (0 <= left < right <= size[0] and 0 <= top < bottom <= size[1]):
        raise AgentError("invalid_roi", "ROI must be a nonempty rectangle inside its image")
    return left, top, right, bottom


def acquisition_evidence(path: Path, digest: str) -> dict[str, Any] | None:
    manifest = path.parent / "metadata.json"
    if not manifest.is_file():
        return None
    value = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AgentError("invalid_manifest", "Adjacent metadata must be an object")
    if value.get("original") != path.name:
        return None  # Do not associate arbitrary adjacent images with another original.
    if value.get("complete") is not True or value.get("sha256") != digest:
        raise AgentError("storage_integrity_error", "Input original does not match its manifest")
    provenance = value.get("provenance", {})
    if not isinstance(provenance, dict):
        raise AgentError("invalid_manifest", "Original provenance must be an object")
    return {
        "manifest": str(manifest),
        "capture_id": value.get("capture_id"),
        "requested_settings": provenance.get("requested_profile"),
        "negotiation": provenance.get("capture_settings"),
        "transfer_time_settings": provenance.get("transfer_time_settings"),
        "confirmed_region": provenance.get("confirmed_region"),
        "device_identity": provenance.get("device_identity"),
    }


def input_evidence(path: Path) -> dict[str, Any]:
    digest = sha256_file(path)
    image = inspect_image(path)
    frame = image["frames"][0]
    if (
        image["frame_count"] != 1
        or frame["mode"] != "RGB"
        or frame["bits_per_pixel"] != 24
        or frame.get("orientation_tag", 1) != 1
    ):
        raise AgentError(
            "unsupported_image", "Comparison requires single-frame RGB24, orientation 1"
        )
    with Image.open(path) as source:
        icc = source.info.get("icc_profile")
        import hashlib

        metadata = {
            "embedded_gamma": source.info.get("gamma"),
            "srgb_rendering_intent": source.info.get("srgb"),
            "icc_sha256": hashlib.sha256(icc).hexdigest() if icc else None,
        }
    return {
        "path": str(path.resolve()),
        "sha256": digest,
        "image": image,
        "color_metadata": metadata,
        "acquisition": acquisition_evidence(path, digest),
    }


def compare(a: Path, b: Path, rois: Any) -> dict[str, Any]:
    if not isinstance(rois, dict) or not {"white_background", "card"} <= rois.keys():
        raise AgentError("invalid_roi", "Select corresponding white_background and card ROIs")
    if "whole_image" in rois:
        raise AgentError("invalid_roi", "whole_image is reserved for complete-image statistics")
    inputs = {"a": input_evidence(a), "b": input_evidence(b)}
    output: dict[str, Any] = {
        "schema_version": 2,
        "operation": "encoded_rgb_comparison",
        "created_at_utc": utc_now(),
        "software": environment(),
        "inputs": inputs,
        "roi_definition": rois,
        "regions": {},
        "analysis_space": "stored 8-bit RGB code values, no ICC/gamma conversion",
        "alignment_verified": False,
        "colorimetric_accuracy_verified": False,
        "physical_scan_performed_by_comparison": False,
        "interpretation": "Manual ROIs; no boundaries/registration. Distribution similarity does not prove color accuracy.",
        "contrast_interpretation": "Encoded channel spreads are descriptive. Gamma, sharpening, color processing and ROI content can also change them; causal attribution requires controlled acquisition.",
        "tonal_band_definition": "Fixed encoded 8-bit bands, not linear-light shadows/midtones/highlights or optical measurements",
    }
    with Image.open(a) as first, Image.open(b) as second:
        first.load()
        second.load()
        selections = {"whole_image": {"a": [0, 0, *first.size], "b": [0, 0, *second.size]}, **rois}
        for name, pair in selections.items():
            if not isinstance(pair, dict) or set(pair) != {"a", "b"}:
                raise AgentError(
                    "invalid_roi", "Each named ROI requires separate a and b rectangles"
                )
            box_a, box_b = rectangle(pair["a"], first.size), rectangle(pair["b"], second.size)
            with first.crop(box_a) as roi_a, second.crop(box_b) as roi_b:
                stats_a, stats_b = statistics(roi_a), statistics(roi_b)
                output["regions"][name] = {
                    "a_box": box_a,
                    "b_box": box_b,
                    "a": stats_a,
                    "b": stats_b,
                    "mean_rgb_delta_b_minus_a": {
                        channel: stats_b[channel]["mean"] - stats_a[channel]["mean"]
                        for channel in "RGB"
                    },
                    "distribution_deltas_b_minus_a": distribution_deltas(stats_a, stats_b),
                    "channel_balance": {
                        label: {
                            "mean_r_minus_g": stats["R"]["mean"] - stats["G"]["mean"],
                            "mean_g_minus_b": stats["G"]["mean"] - stats["B"]["mean"],
                        }
                        for label, stats in (("a", stats_a), ("b", stats_b))
                    },
                    "correspondence": "operator_selected_regions; no pixel registration assumed",
                }
    for label, path in (("a", a), ("b", b)):
        if sha256_file(path) != inputs[label]["sha256"]:
            raise AgentError("source_changed", "Input changed during comparison; discard analysis")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only S1 RGB/gamma experiment comparison")
    parser.add_argument("--a", required=True, type=Path)
    parser.add_argument("--b", required=True, type=Path)
    parser.add_argument("--rois", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New JSON file under local_data")
    args = parser.parse_args(argv)
    try:
        parent = confined_data_dir(args.output.parent)
        output = parent / args.output.name
        if output.exists() or output.resolve() in {
            args.a.resolve(),
            args.b.resolve(),
            args.rois.resolve(),
        }:
            raise AgentError("invalid_path", "Comparison output must be a new separate JSON file")
        result = compare(args.a, args.b, json.loads(args.rois.read_text(encoding="utf-8-sig")))
        result["comparison_id"] = identifier()
        write_json_new(output, result)
        print(json.dumps({"status": "compared", "report": str(output)}))
        return 0
    except (AgentError, OSError, ValueError) as exc:
        print(
            json.dumps({"status": getattr(exc, "status", "comparison_error"), "message": str(exc)})
        )
        return 2
