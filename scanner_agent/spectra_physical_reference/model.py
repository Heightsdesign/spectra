from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import cv2
import numpy as np
from PIL import Image

from spectra_reference.geometry import line
from spectra_scanner.common import AgentError, utc_now
from spectra_scanner.storage import sha256_file

from . import NAMES, __version__


def read(path: Path) -> dict[str, Any]:
    def reject(value: str) -> Any:
        raise ValueError(f"Nonfinite JSON number: {value}")

    value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=reject)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def load_image(path: Path) -> tuple[Any, dict[str, Any]]:
    before = sha256_file(path)
    with Image.open(path) as image:
        if image.mode != "RGB" or getattr(image, "n_frames", 1) != 1:
            raise ValueError("A single-frame RGB original is required; no conversion is performed")
        image.load()
        rgb = np.asarray(image).copy()
        identity = {"sha256": before, "dimensions": list(image.size), "mode": "RGB"}
    if before != sha256_file(path):
        raise ValueError("Image changed while decoding")
    return rgb, identity


def load_report(path: Path, identity: dict[str, Any]) -> dict[str, Any]:
    value = read(path)
    if (
        value.get("kind") != "single_image"
        or value.get("schema_version") != 1
        or value.get("algorithm_version") not in {"0.2.0", "0.3.0-exp1"}
        or value.get("source", {}).get("sha256") != identity["sha256"]
        or value.get("original_hash_verified_after_analysis") is not True
    ):
        raise ValueError("Unverified, incompatible or cross-image detector report")
    frames = value.get("source", {}).get("image", {}).get("frames")
    if frames and (
        len(frames) != 1
        or [frames[0]["width"], frames[0]["height"]] != identity["dimensions"]
        or frames[0]["mode"] != "RGB"
    ):
        raise ValueError("Detector dimensions/channels differ from original")
    detection = value.get("baseline")
    if not isinstance(detection, dict):
        raise ValueError("Missing baseline detection")
    sides = detection.get("sides", [])
    if sides and (len(sides) != 4 or [s.get("index") for s in sides] != list(range(4))):
        raise ValueError("Expected four ordered detector sides")
    for side in sides:
        line(side["line_abc"])
        for layer in side.get("candidate_layers", []):
            line(layer["line_abc"])
    return value


def draft(identity: dict[str, Any], reports: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "physical_boundary_reference",
        "tool_version": __version__,
        "annotation_id": str(uuid4()),
        "annotation_version": str(uuid4()),
        "created_at_utc": utc_now(),
        "previous_annotation_sha256": None,
        "coordinate_system": "original_image_pixels_xy_right_down_v1",
        "image": identity,
        "reviewer": "",
        "independent_review_declared": False,
        "candidate_overlays_seen": False,
        "source_reports": reports,
        "sides": [
            {
                "index": i,
                "name": name,
                "status": "unreviewed",
                "endpoints": None,
                "line_abc": None,
                "uncertainty_pixels": None,
                "notes": "",
                "origin": "manual",
                "confirmed": False,
                "confirmed_at_utc": None,
                "reviewed": None,
            }
            for i, name in enumerate(NAMES)
        ],
    }


def side_line(side: dict[str, Any], size: list[int]) -> Any:
    points = np.asarray(side.get("endpoints"), dtype=float)
    if (
        points.shape != (2, 2)
        or not np.isfinite(points).all()
        or np.any(points < 0)
        or np.any(points >= np.asarray(size))
        or np.linalg.norm(points[1] - points[0]) < 1
    ):
        raise ValueError("Two distinct in-image endpoints required")
    coefficients = line(side.get("line_abc"))
    if np.max(np.abs(points @ coefficients[:2] + coefficients[2])) > 1e-6:
        raise ValueError("Line does not match its endpoints")
    if abs(coefficients[1 if side["index"] in (0, 2) else 0]) < 0.1:
        raise ValueError("Line orientation is incompatible with side identity")
    return coefficients


def intersections(lines: list[Any], size: list[int]) -> list[Any]:
    result: list[Any] = []
    for i in range(4):
        a, b = lines[(i - 1) % 4], lines[i]
        if a is None or b is None:
            result.append(None)
            continue
        pair = np.stack([a, b])
        if abs(np.linalg.det(pair[:, :2])) < 0.01:
            raise ValueError("Unstable adjacent-line intersections")
        point = np.linalg.solve(pair[:, :2], -pair[:, 2])
        if not np.isfinite(point).all() or np.any(point < 0) or np.any(point >= size):
            raise ValueError("Reference corner lies outside original image")
        result.append(point.tolist())
    if all(p is not None for p in result):
        quad = np.asarray(result, dtype=np.float32)
        if (
            not cv2.isContourConvex(quad)
            or cv2.contourArea(quad, oriented=True) <= 1
            or np.min(np.linalg.norm(np.roll(quad, -1, axis=0) - quad, axis=1)) < 1
            or not (
                quad[0:2, 1].mean() < quad[2:4, 1].mean()
                and quad[[1, 2], 0].mean() > quad[[0, 3], 0].mean()
            )
        ):
            raise ValueError("Nonconvex, crossed, degenerate or reordered reference geometry")
    return result


def validate(reference: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    required = set(draft(identity, []))
    if set(reference) != required or type(reference.get("schema_version")) is not int:
        raise ValueError("Reference schema fields differ from version 1")
    if (
        reference.get("schema_version") != 1
        or reference.get("kind") != "physical_boundary_reference"
        or reference.get("tool_version") != __version__
        or reference.get("coordinate_system") != "original_image_pixels_xy_right_down_v1"
        or reference.get("image") != identity
    ):
        raise ValueError("Incompatible reference or image identity mismatch")
    for key in ("annotation_id", "annotation_version"):
        if not isinstance(reference.get(key), str):
            raise ValueError("UUID strings required")
        UUID(reference[key])
    for key in ("created_at_utc",):
        if (
            not isinstance(reference.get(key), str)
            or datetime.fromisoformat(reference[key].replace("Z", "+00:00")).tzinfo is None
        ):
            raise ValueError("Creation timestamp requires timezone")
    previous = reference["previous_annotation_sha256"]
    if previous is not None and (
        not isinstance(previous, str) or not re.fullmatch(r"[a-f0-9]{64}", previous)
    ):
        raise ValueError("Previous annotation hash must be SHA-256 or null")
    if not isinstance(reference["source_reports"], list):
        raise ValueError("Source report provenance must be a list")
    for source in reference["source_reports"]:
        if (
            not isinstance(source, dict)
            or set(source) != {"path", "sha256"}
            or not isinstance(source["path"], str)
            or not isinstance(source["sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", source["sha256"])
        ):
            raise ValueError("Invalid source report provenance")
    if not isinstance(reference.get("reviewer"), str) or not reference["reviewer"].strip():
        raise ValueError("Reviewer identity required")
    if reference.get("independent_review_declared") is not True:
        raise ValueError("Explicit independent visual-review declaration required")
    if type(reference.get("candidate_overlays_seen")) is not bool:
        raise ValueError("Candidate exposure must be recorded")
    sides = reference.get("sides")
    if not isinstance(sides, list) or len(sides) != 4:
        raise ValueError("Exactly four side reviews required")
    lines: list[Any] = []
    for i, side in enumerate(sides):
        if not isinstance(side, dict) or set(side) != set(draft(identity, [])["sides"][0]):
            raise ValueError("Side fields differ from schema version 1")
        if (
            side.get("index") != i
            or side.get("name") != NAMES[i]
            or side.get("confirmed") is not True
        ):
            raise ValueError("Each ordered side requires explicit confirmation")
        status = side.get("status")
        if status not in {"certain", "uncertain", "indeterminate"}:
            raise ValueError("Unreviewed or unknown side status")
        if not isinstance(side["confirmed_at_utc"], str):
            raise ValueError("Review timestamp required")
        timestamp = datetime.fromisoformat(side["confirmed_at_utc"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Review time requires timezone")
        if side.get("origin") not in {"manual", "detector_seed"} or not isinstance(
            side.get("notes"), str
        ):
            raise ValueError("Side provenance and notes required")
        reviewed = {
            key: side.get(key)
            for key in ("status", "endpoints", "line_abc", "uncertainty_pixels", "notes", "origin")
        }
        if side.get("reviewed") != reviewed:
            raise ValueError("Side changed since explicit confirmation")
        width = side.get("uncertainty_pixels")
        if status == "uncertain":
            if (
                not isinstance(width, (int, float))
                or isinstance(width, bool)
                or not np.isfinite(width)
                or width <= 0
                or not side["notes"].strip()
            ):
                raise ValueError("Uncertain sides need a positive pixel band and explanation")
        elif width is not None:
            raise ValueError("Only uncertain sides carry a pixel uncertainty band")
        if status == "indeterminate":
            if (
                side.get("line_abc") is not None
                or side.get("endpoints") is not None
                or not side["notes"].strip()
            ):
                raise ValueError(
                    "Indeterminate sides require an explanation and no invented geometry"
                )
            lines.append(None)
        else:
            lines.append(side_line(side, identity["dimensions"]))
    corners = intersections(lines, identity["dimensions"])
    return {
        "lines": lines,
        "corners_pixels": corners,
        "complete_certain_reference": all(s["status"] == "certain" for s in sides),
        "independence_not_auditable": True,
    }


def safe_validate(reference: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    try:
        return validate(reference, identity)
    except (ValueError, TypeError, KeyError, AgentError) as exc:
        raise ValueError(f"Invalid physical reference: {exc}") from exc
