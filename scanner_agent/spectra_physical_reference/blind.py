"""Blind preparation, exclusive first-pass freezing and read-only comparison.

No detector or previous reference is accepted by prepare/freeze. The existing
annotation schema is unchanged; session and exposure records are separate.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from PIL import Image

from spectra_scanner.common import utc_now
from spectra_scanner.storage import sha256_file

from .comparison import compare
from .model import draft, load_image, read, safe_validate


def write(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)


def prepare(image: Path, output: Path) -> dict[str, Any]:
    rgb, identity = load_image(image)
    reference = draft(identity, [])
    session = {
        "schema_version": 1,
        "kind": "blind_physical_session",
        "session_id": str(uuid4()),
        "created_at_utc": utc_now(),
        "image_path": str(image.resolve()),
        "image": identity,
        "annotation_id": reference["annotation_id"],
        "annotation_version": reference["annotation_version"],
    }
    template = page_content(rgb, reference, session["session_id"])
    if sha256_file(image) != identity["sha256"]:
        raise ValueError("Original changed during preparation")
    output.mkdir(parents=True, exist_ok=False)
    write(output / "session.json", session)
    with (output / "editor.html").open("x", encoding="utf-8") as handle:
        handle.write(template)
    return session


def page_content(rgb: Any, reference: dict[str, Any], session_id: str) -> str:
    """Render the shared manual-only page without comparison inputs."""
    buffer = io.BytesIO()
    Image.fromarray(rgb).save(buffer, format="PNG")
    payload = {
        "image": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(),
        "reference": reference,
        "session_id": session_id,
    }
    root = Path(__file__).parent
    template = (root / "blind.html").read_text(encoding="utf-8")
    encoded = json.dumps(payload, allow_nan=False).replace("<", "\\u003c")
    for marker, content in {
        "__DATA__": encoded,
        "__CORE__": (root.parent / "spectra_reference/editor-core.js").read_text(encoding="utf-8"),
        "__MODEL__": (root / "reference-core.js").read_text(encoding="utf-8"),
        "__EDITOR__": (root / "blind.js").read_text(encoding="utf-8"),
    }.items():
        template = template.replace(marker, content)
    return template


def refresh_editor(directory: Path) -> None:
    """Refresh only an empty prepared page, preserving payload/session identity."""
    if (directory / "first-pass").exists():
        raise ValueError("Cannot refresh a session with a first-pass reservation")
    session = read(directory / "session.json")
    identity = session_identity(session)
    path = directory / "editor.html"
    html = path.read_text(encoding="utf-8")
    payload = json.loads(
        html.split('<script id="blind-data" type="application/json">')[1].split("</script>")[0]
    )
    reference = payload["reference"]
    blank = draft(identity, [])
    for key in ("annotation_id", "annotation_version", "created_at_utc"):
        blank[key] = reference[key]
    if (
        reference != blank
        or payload["session_id"] != session["session_id"]
        or any(reference[k] != session[k] for k in ("annotation_id", "annotation_version"))
    ):
        raise ValueError("Only empty, unconfirmed prepared pages may be refreshed")
    rgb, _ = load_image(Path(session["image_path"]))
    content = page_content(rgb, reference, session["session_id"])
    session_identity(session)
    path.write_text(content, encoding="utf-8")


def session_identity(session: dict[str, Any]) -> dict[str, Any]:
    _, identity = load_image(Path(session["image_path"]))
    if identity != session["image"]:
        raise ValueError("Session original image identity changed")
    return identity


def freeze(directory: Path, export: Path) -> dict[str, Any]:
    session = read(directory / "session.json")
    identity = session_identity(session)
    bundle_bytes = export.read_bytes()
    bundle = json.loads(bundle_bytes)
    if (
        bundle.get("schema_version") != 1
        or bundle.get("kind") != "blind_first_pass_export"
        or bundle.get("session_id") != session["session_id"]
        or bundle.get("blind_review_declared") is not True
        or bundle.get("prior_detector_exposure") not in {"none", "exposed", "unknown"}
    ):
        raise ValueError("Invalid session binding or exposure declaration")
    raw = bundle["reference_json"].encode("utf-8")
    exported = datetime.fromisoformat(bundle["exported_at_utc"].replace("Z", "+00:00"))
    if exported.tzinfo is None:
        raise ValueError("Timezone-aware export timestamp required")
    if hashlib.sha256(raw).hexdigest() != bundle.get("reference_sha256"):
        raise ValueError("Export reference SHA-256 mismatch")
    reference = json.loads(raw)
    safe_validate(reference, identity)
    if any(reference[k] != session[k] for k in ("annotation_id", "annotation_version")):
        raise ValueError("Annotation does not belong to prepared session")
    if (
        reference["source_reports"]
        or reference["candidate_overlays_seen"]
        or reference["previous_annotation_sha256"] is not None
        or any(s["origin"] != "manual" for s in reference["sides"])
    ):
        raise ValueError("First pass must contain exclusively manual, unexposed geometry")
    manifest = {
        "schema_version": 1,
        "kind": "frozen_blind_first_pass",
        "session_id": session["session_id"],
        "image": identity,
        "annotation_id": reference["annotation_id"],
        "annotation_version": reference["annotation_version"],
        "reviewer": reference["reviewer"],
        "reference_file": "reference.json",
        "reference_sha256": hashlib.sha256(raw).hexdigest(),
        "export_file": "export.json",
        "export_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        "frozen_at_utc": utc_now(),
        "exported_at_utc": bundle["exported_at_utc"],
        "prior_detector_exposure": bundle["prior_detector_exposure"],
        "blind_review_declared": True,
        "eligible_blind_declaration": bundle["prior_detector_exposure"] == "none",
        "limitation": "Self-declared exposure; local hashes are not tamper-proof storage.",
    }
    # Reserve before writing. A failed/partial freeze cannot be silently reused.
    frozen = directory / "first-pass"
    frozen.mkdir(exist_ok=False)
    with (frozen / "reference.json").open("xb") as handle:
        handle.write(raw)
    with (frozen / "export.json").open("xb") as handle:
        handle.write(bundle_bytes)
    write(frozen / "manifest.json", manifest)
    return manifest


def verified_first_pass(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    session = read(directory / "session.json")
    identity = session_identity(session)
    frozen = directory / "first-pass"
    manifest = read(frozen / "manifest.json")
    if (
        manifest.get("kind") != "frozen_blind_first_pass"
        or manifest.get("schema_version") != 1
        or manifest["session_id"] != session["session_id"]
        or manifest["image"] != identity
    ):
        raise ValueError("Frozen manifest identity mismatch")
    for name, key in (("reference.json", "reference_sha256"), ("export.json", "export_sha256")):
        if sha256_file(frozen / name) != manifest[key]:
            raise ValueError("Frozen first-pass integrity failure")
    reference = read(frozen / "reference.json")
    safe_validate(reference, identity)
    bundle = read(frozen / "export.json")
    if (
        bundle["session_id"] != session["session_id"]
        or bundle["reference_json"].encode() != (frozen / "reference.json").read_bytes()
        or bundle["reference_sha256"] != manifest["reference_sha256"]
        or bundle["prior_detector_exposure"] != manifest["prior_detector_exposure"]
        or bundle["blind_review_declared"] is not True
        or manifest["blind_review_declared"] is not True
        or manifest["eligible_blind_declaration"] != (bundle["prior_detector_exposure"] == "none")
        or manifest["exported_at_utc"] != bundle["exported_at_utc"]
        or reference["previous_annotation_sha256"] is not None
        or reference["candidate_overlays_seen"]
        or reference["source_reports"]
        or any(s["origin"] != "manual" for s in reference["sides"])
        or any(reference[k] != session[k] for k in ("annotation_id", "annotation_version"))
    ):
        raise ValueError("Frozen first-pass provenance mismatch")
    return reference, manifest


def previous_comparison(reference: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    """Same 101-point inward-normal convention as the existing detector utility."""
    identity = reference["image"]
    a = safe_validate(reference, identity)
    b = safe_validate(previous, identity)
    sides = []
    for i, side in enumerate(reference["sides"]):
        row: dict[str, Any] = {
            "index": i,
            "available": False,
            "statuses": [side["status"], previous["sides"][i]["status"]],
            "uncertainty_pixels": [
                side["uncertainty_pixels"],
                previous["sides"][i]["uncertainty_pixels"],
            ],
        }
        if a["lines"][i] is not None and b["lines"][i] is not None:
            normal = a["lines"][i][:2].copy()
            if normal @ np.array(((0, 1), (-1, 0), (0, -1), (1, 0))[i]) < 0:
                normal = -normal
            target = b["lines"][i]
            denominator = target[:2] @ normal
            if abs(denominator) >= 0.1:
                p, q = np.asarray(side["endpoints"])
                points = p + np.linspace(0, 1, 101)[:, None] * (q - p)
                signed = -(points @ target[:2] + target[2]) / denominator
                row.update(
                    available=True,
                    start_middle_end_pixels=signed[[0, 50, 100]].tolist(),
                    signed_normal_displacement_pixels=signed.tolist(),
                    mean_absolute_pixels=float(abs(signed).mean()),
                    maximum_absolute_pixels=float(abs(signed).max()),
                    eligible_for_certain_reference_agreement=all(
                        status == "certain" for status in row["statuses"]
                    ),
                )
        sides.append(row)
    corners = []
    for name, p, q in zip(
        ("TL", "TR", "BR", "BL"), a["corners_pixels"], b["corners_pixels"], strict=True
    ):
        corners.append(
            {
                "name": name,
                "distance_pixels": None
                if p is None or q is None
                else float(np.linalg.norm(np.asarray(q) - p)),
                "delta_xy_pixels": None if p is None or q is None else (np.asarray(q) - p).tolist(),
            }
        )
    return {
        "annotation_id": previous["annotation_id"],
        "annotation_version": previous["annotation_version"],
        "candidate_overlays_seen": previous["candidate_overlays_seen"],
        "side_origins": [s["origin"] for s in previous["sides"]],
        "source_reports": previous["source_reports"],
        "reviewer": previous["reviewer"],
        "potential_anchor_bias": previous["candidate_overlays_seen"]
        or any(s["origin"] == "detector_seed" for s in previous["sides"]),
        "per_side": sides,
        "corners": corners,
        "accuracy_score": None,
    }


def post_compare(directory: Path, reports: list[Path], previous: list[Path]) -> Path:
    # Validate frozen checkpoint BEFORE reading any comparison inputs.
    reference, manifest = verified_first_pass(directory)
    protected = {
        p: sha256_file(p)
        for p in [
            directory / "session.json",
            *(directory / "first-pass").iterdir(),
            *reports,
            *previous,
        ]
    }
    result = compare(reference, reference["image"], reports)
    result["first_pass"] = manifest
    result["previous_references"] = [
        {
            "path": str(p.resolve()),
            "sha256": protected[p],
            **previous_comparison(reference, read(p)),
        }
        for p in previous
    ]
    if any(sha256_file(p) != digest for p, digest in protected.items()):
        raise ValueError("Input changed during comparison")
    verified_first_pass(directory)
    output = directory / "comparisons" / str(uuid4())
    output.mkdir(parents=True, exist_ok=False)
    write(output / "comparison.json", result)
    write(output / "integrity.json", {str(p.resolve()): h for p, h in protected.items()})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("image", type=Path)
    prepare_parser.add_argument("--output", type=Path, required=True)
    freeze_parser = sub.add_parser("freeze")
    freeze_parser.add_argument("session", type=Path)
    freeze_parser.add_argument("--export", dest="export_path", type=Path, required=True)
    comparison_parser = sub.add_parser("compare")
    comparison_parser.add_argument("session", type=Path)
    comparison_parser.add_argument("--report", type=Path, action="append", default=[])
    comparison_parser.add_argument("--previous-reference", type=Path, action="append", default=[])
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args.image, args.output)
            print(args.output / "editor.html")
        elif args.command == "freeze":
            freeze(args.session, args.export_path)
            print(args.session / "first-pass/manifest.json")
        else:
            print(post_compare(args.session, args.report, args.previous_reference))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"Blind workflow refused: {exc}\n")
