from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from spectra_scanner.common import AgentError, utc_now, write_json_new
from spectra_scanner.comparison import input_evidence
from spectra_scanner.storage import sha256_file

from . import __version__
from .detector import detect
from .diagnostics import write_zooms
from .displacement import compare_layers


def save_png(path: Path, rgb: Any) -> None:
    with path.open("xb") as stream:
        Image.fromarray(rgb).save(stream, format="PNG")


def overlay(rgb: Any, detection: dict[str, Any], accepted: Any, rejected: Any) -> Any:
    canvas = rgb.copy()
    # Full support coordinates are in JSON; overlay sampling keeps markings legible.
    for points, color in ((rejected, (230, 80, 80)), (accepted, (30, 220, 100))):
        for x, y in points[:: max(1, len(points) // 12000)]:
            cv2.circle(canvas, (round(float(x)), round(float(y))), 1, color, -1)
    if "geometry" in detection:
        corners = np.array(detection["geometry"]["corners_pixels"])
        for i, point in enumerate(corners):
            a, b = (
                tuple(np.rint(point).astype(int)),
                tuple(np.rint(corners[(i + 1) % 4]).astype(int)),
            )
            cv2.line(canvas, a, b, (30, 180, 255), 2, cv2.LINE_AA)
            cv2.circle(canvas, a, 6, (255, 40, 220), 2)
            cv2.putText(canvas, str(i), a, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 40, 220), 2)
    cv2.putText(
        canvas, detection["status"], (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 20, 200), 2
    )
    return canvas


def reported_dpi(source: dict[str, Any], override: float | None) -> tuple[Any, str, list[str]]:
    if override is not None:
        return [override, override], "explicit_operator_override_not_calibration", []
    embedded = source["image"]["frames"][0].get("dpi_metadata")
    acquisition = source.get("acquisition") or {}
    # File metadata is reported evidence, not optical calibration. The S1 manifest
    # also records driver image-info inside original provenance; verify consistency.
    manifest_path = acquisition.get("manifest")
    if manifest_path:
        import json

        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        info = manifest.get("provenance", {}).get("twain_image_info", {})
        driver = [info.get("XResolution"), info.get("YResolution")]
        if all(isinstance(v, (int, float)) and math.isfinite(v) for v in driver):
            flags = []
            if embedded and any(
                not math.isfinite(v) or abs(v - w) > 1
                for v, w in zip(embedded, driver, strict=True)
            ):
                flags.append("driver_and_file_dpi_disagree")
            return driver, "S1_driver_image_info", flags
    return embedded, "embedded_file_dpi_not_calibration", []


def analyze(
    path: Path,
    folder: Path,
    config: dict[str, Any],
    dpi_override: float | None = None,
    compare_preprocessing: bool = False,
) -> dict[str, Any]:
    folder.mkdir()  # A scan output directory is never reused.
    report: dict[str, Any] = {
        "schema_version": 1,
        "kind": "single_image",
        "analysis_id": f"{folder.parent.name}/{folder.name}",
        "status": "failure",
        "algorithm_version": __version__,
        "algorithm": "contour_seeded_physical_transition_layer_fits_v2",
        "created_at_utc": utc_now(),
        "configuration": config,
        "software": {"opencv": cv2.__version__, "numpy": np.__version__},
        "coordinate_system": "original image pixels; x right, y down; no spatial transform",
        "physical_scan_performed": False,
        "metrological_accuracy_validated": False,
        "artifacts": {},
    }
    try:
        report["source"] = {"path": str(path.resolve()), "sha256": sha256_file(path)}
        source = input_evidence(path)
        report["source"] = source
        with Image.open(path) as original:
            rgb = np.asarray(original).copy()
        dpi, dpi_source, dpi_flags = reported_dpi(source, dpi_override)
        report.update(dpi=dpi, dpi_evidence=dpi_source, dpi_flags=dpi_flags)
        baseline = copy.deepcopy(config)
        baseline["preprocessing"] = {"normalize_percentiles": None, "contrast": 1.0}
        modes = [("baseline", baseline)]
        if compare_preprocessing:
            modes.append(("preprocessed", config))
        for name, settings in modes:
            detection, gray, accepted, rejected = detect(rgb, dpi, settings)
            detection["preprocessing"] = settings["preprocessing"]
            if dpi_flags and detection["status"] == "success":
                detection["status"] = "review_required"
                detection.setdefault("flags_requiring_review", []).extend(dpi_flags)
            report[name] = detection
            save_png(folder / f"{name}-overlay.png", overlay(rgb, detection, accepted, rejected))
            save_png(folder / f"{name}-working.png", gray)
            # Complete point evidence is separate to keep the main report readable.
            write_json_new(
                folder / f"{name}-support.json",
                {"accepted_pixels": accepted.tolist(), "rejected_edge_pixels": rejected.tolist()},
            )
            report["artifacts"][name] = {
                "overlay": f"{name}-overlay.png",
                "working_image": f"{name}-working.png",
                "support": f"{name}-support.json",
                "zooms": write_zooms(rgb, detection, folder, name),
            }
        report["status"] = report["baseline"]["status"]
        if compare_preprocessing:
            report["preprocessing_comparison"] = {
                "baseline_status": report["baseline"]["status"],
                "preprocessed_status": report["preprocessed"]["status"],
                "preferred_result": None,
                "parallel_layers": compare_layers(report["baseline"], report["preprocessed"]),
            }
            write_json_new(
                folder / "parallel-layer-comparison.json",
                report["preprocessing_comparison"]["parallel_layers"],
            )
            report["artifacts"]["parallel_layer_comparison"] = "parallel-layer-comparison.json"
            if report["preprocessed"]["status"] != report["baseline"]["status"]:
                report["status"] = "review_required"
            if "geometry" in report["baseline"] and "geometry" in report["preprocessed"]:
                delta = np.asarray(
                    report["preprocessed"]["geometry"]["corners_pixels"]
                ) - np.asarray(report["baseline"]["geometry"]["corners_pixels"])
                report["preprocessing_comparison"]["corner_deltas_pixels"] = delta.tolist()
                report["preprocessing_comparison"]["corner_displacement_norm_pixels"] = (
                    np.linalg.norm(delta, axis=1).tolist()
                )
                if (
                    np.linalg.norm(delta, axis=1).max() > config["maximum_rms_pixels"]
                    or report["preprocessed"]["status"] != report["baseline"]["status"]
                ):
                    report["status"] = "review_required"
        if sha256_file(path) != source["sha256"]:
            raise AgentError("source_changed", "Source changed during analysis")
        report["original_hash_verified_after_analysis"] = True
    except (AgentError, OSError, ValueError, cv2.error) as exc:
        report.update(
            status="failure", reason=getattr(exc, "status", "analysis_error"), message=str(exc)
        )
        report["diagnostic_overlay_unavailable"] = (
            "Input could not be safely decoded or analysis did not finish"
        )
    write_json_new(folder / "report.json", report)
    return report
