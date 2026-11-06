"""Workstation-only history, immutable recovery snapshots and centering adapter."""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import numpy as np

from spectra_centering.config import validate
from spectra_centering.detector import measurements
from spectra_physical_reference.model import intersections, read
from spectra_reference import NAMES
from spectra_scanner.common import utc_now, write_json_new
from spectra_scanner.storage import sha256_file


def group_valid(session, family):
    stamp = session.data.get("boundary_validation", {}).get(family)
    return bool(
        stamp
        and isinstance(stamp, dict)
        and stamp.get("sides") == session.data[family]
        and stamp.get("operator") == session.data["operator"]
        and isinstance(stamp.get("at_utc"), str)
        and all(s["status"] == "annotated" for s in session.data[family])
    )


def validate_group(session, family):
    if not session.data["operator"].strip():
        raise ValueError("Operator identity required")
    if not all(s["status"] == "annotated" for s in session.data[family]):
        raise ValueError("Confirm all four sides without unresolved uncertainty first")
    intersections([s["line_abc"] for s in session.data[family]], session.identity["dimensions"])
    session.data.setdefault("boundary_validation", {})[family] = dict(
        sides=deepcopy(session.data[family]), operator=session.data["operator"], at_utc=utc_now()
    )


def measure(session):
    result = dict(
        status="unavailable",
        coordinate_system=session.data["coordinate_system"],
        units="original image pixels",
        inspection_face=session.data.get("inspection_face", "unspecified"),
        limitations=[
            "Human geometry review does not certify metrological accuracy.",
            "Upstream review_required and grading gates remain unchanged.",
            "No calibrated physical units or uncertainty interval; ratios depend on chosen lines.",
        ],
        boundary_validation={f: group_valid(session, f) for f in ("physical", "printed")},
    )
    if any(s["line_abc"] is None for f in ("physical", "printed") for s in session.data[f]):
        result["limitations"].append("Missing boundaries; no geometry inferred.")
        return result
    try:
        corners = intersections(
            [s["line_abc"] for s in session.data["physical"]], session.identity["dimensions"]
        )
        sides = [
            dict(
                name=name,
                selected_candidate_id="manual-geometry",
                candidates=[
                    dict(id="manual-geometry", line_abc=session.data["printed"][i]["line_abc"])
                ],
            )
            for i, name in enumerate(NAMES)
        ]
        result.update(measurements(np.asarray(corners), sides, None, validate({})))
        result["physical_corners_pixels"] = corners
        result["status"] = (
            "human_geometry_validated"
            if all(result["boundary_validation"].values())
            else "provisional"
        )
        if result["status"] == "provisional":
            result["limitations"].append("Boundaries are unvalidated, unconfirmed or uncertain.")
    except Exception as exc:
        result["limitations"].append(f"Inconsistent geometry: {exc}")
    return result


class History:
    """Only editable decisions rewind; detector exposure and provenance never rewind."""

    def __init__(self, session):
        self.session = session
        self.states = [self.snapshot()]
        self.position = 0

    def snapshot(self):
        snapshot = deepcopy(
            {
                k: self.session.data.get(k)
                for k in (
                    "physical",
                    "printed",
                    "boundary_validation",
                    "inspection_face",
                    "condition",
                )
            }
        )
        snapshot["grading_working"] = deepcopy(
            self.session.data.get("grading", {}).get("working", {})
        )
        return snapshot

    def record(self):
        state = self.snapshot()
        if state != self.states[self.position]:
            self.states = self.states[: self.position + 1] + [state]
            self.position += 1

    def move(self, delta):
        target = self.position + delta
        if 0 <= target < len(self.states):
            if "grading" in self.session.data:
                from .grading import actor

                actor(self.session, "Undo/Redo grading working decisions")
            self.position = target
            for key, value in deepcopy(self.states[target]).items():
                if key == "grading_working":
                    if "grading" in self.session.data:
                        from .grading import audit

                        self.session.data["grading"]["working"] = value
                        audit(self.session, "undo_redo", "Restore grading working decisions")
                    continue
                if value is None:
                    self.session.data.pop(key, None)
                else:
                    self.session.data[key] = value


def autosave(session, directory):
    # Exclusive UUID snapshots, flushed/fsynced by the shared artifact writer.
    # A partial newest snapshot never destroys a prior complete generation.
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"draft-{session.data['session_id']}-{uuid4()}.json"
    write_json_new(
        path,
        dict(
            kind="selby_recovery_draft",
            schema_version=1,
            at_utc=utc_now(),
            session=deepcopy(session.data),
            saved_path=str(session.saved_path) if session.saved_path else None,
            saved_sha=session.saved_sha,
        ),
    )
    return path


def recover(path):
    from .session import Session

    before = sha256_file(path)
    value = read(path)
    if value.get("kind") != "selby_recovery_draft" or value.get("schema_version") != 1:
        raise ValueError("Not a workstation recovery draft")
    data = value["session"]
    session = Session(Path(data["image"]["path"]))
    if session.identity != {k: data["image"][k] for k in ("sha256", "dimensions", "mode")}:
        raise ValueError("Recovery image identity mismatch")
    for source in data["sources"]:
        session.load_report(Path(source["path"]))
    if session.data["sources"] != data["sources"]:
        raise ValueError("Recovery source provenance mismatch")
    session.data = data
    session.validate(require_operator=False)
    if value["saved_path"]:
        saved = Path(value["saved_path"])
        if sha256_file(saved) != value["saved_sha"]:
            raise ValueError("Saved recovery ancestor changed")
        session.saved_path, session.saved_sha = saved, value["saved_sha"]
    if sha256_file(path) != before:
        raise ValueError("Recovery draft changed while reading")
    return session


def export_report(session, directory):
    session.validate()
    from .grading import evaluate

    grading = evaluate(session) if session.data.get("grading") else None
    if session.saved_path and sha256_file(session.saved_path) != session.saved_sha:
        raise ValueError("Saved inspection ancestor changed")
    directory.mkdir(parents=True, exist_ok=True)
    version = str(uuid4())
    path = directory / f"inspection-{session.data['session_id']}-{version}.json"
    write_json_new(
        path,
        dict(
            kind="selby_inspection_diagnostic",
            schema_version=1,
            version_id=version,
            created_at_utc=utc_now(),
            inspection=deepcopy(session.data),
            saved_session=dict(path=str(session.saved_path), sha256=session.saved_sha)
            if session.saved_path
            else None,
            measurement=measure(session),
            grading=grading,
            review_status="review_required",
            automatic_acceptance=False,
        ),
    )
    diagnostic = measure(session)
    lines = [
        "# SELBY inspection diagnostic",
        "",
        f"Version: {version}",
        f"Image: {session.data['image']['path']}",
        f"SHA-256: {session.identity['sha256']}",
        f"Face: {session.data.get('inspection_face', 'unspecified')} (unpaired)",
        f"Operator: {session.data['operator']}",
        f"Measurement: {diagnostic['status']}; original image pixels.",
        "Inspection remains review_required. Draft grades do not authorize commercial release or automatic acceptance.",
        "",
    ]
    if "margins" in diagnostic:
        lines += ["| Side | Mean px | Min px | Max px |", "|---|---:|---:|---:|"]
        lines += [
            f"| {name} | {m['mean_pixels']:.6f} | {m['min_pixels']:.6f} | {m['max_pixels']:.6f} |"
            for name, m in diagnostic["margins"].items()
        ]
        c = diagnostic["centering_percent"]
        lines += [
            "",
            f"Horizontal L:R {c['left']:.6f}:{c['right']:.6f}; vertical T:B {c['top']:.6f}:{c['bottom']:.6f}.",
        ]
    lines += ["", "Limitations:", ""] + [f"- {item}" for item in diagnostic["limitations"]]
    lines += ["", "Sources (statuses preserved):", ""]
    lines += [
        f"- {source['path']} — SHA-256 {source['sha256']} — {source['status']}"
        for source in session.data["sources"]
    ]
    lines += ["", "Decisions in original (x, y) pixel coordinates:", ""]
    for family in ("physical", "printed"):
        for name, side in zip(NAMES, session.data[family], strict=True):
            lines += [
                f"- {family} {name}: {side['status']}; origin={side['definition']}; endpoints={side['endpoints']}; source basis={side['basis']}; notes={side['notes']}"
            ]
    from .condition import CATEGORIES, category_status

    if session.data.get("condition"):
        lines += ["", "Condition inspection (no score):", ""]
        lines += [f"- {c}: {category_status(session, c)}" for c in CATEGORIES]
        for finding in session.data["condition"]["findings"]:
            lines += [
                f"- {finding['category']} / {finding['type']}: {finding['decision']}; origin={finding['origin']}; original polygon={finding['polygon_original']}; evidence={finding['evidence']}; operator={finding['operator']}; notes={finding['notes']}"
            ]
    if grading:
        lines += ["", "Human-supervised draft grading:", "",
                  f"Policy: {grading.get('policy_id')} {grading.get('policy_version')}",
                  f"State: {grading['state']}",
                  f"Subgrades: {grading.get('subgrades')}",
                  f"Calculated grade: {grading['calculated_grade']}",
                  f"Proposed grade: {grading.get('proposed_grade')}",
                  f"Human-validated grade: {grading.get('final_grade')}",
                  grading.get('explanation', 'No grade: required information unresolved.'),
                  f"Applicable caps: {grading.get('applicable_caps')}",
                  f"Override: {grading.get('override')}",
                  f"Front/back completion: {grading.get('completion')}"]
        final = grading.get("operator_decision")
        if final:
            lines += [f"Final operator: {final['operator']}; at {final['at_utc']}; notes: {final['notes']}"]
        lines += [f"Pinned policy SHA-256: {session.data['grading']['policy_sha256']}"]
        for face, record in session.data["grading"]["working"].get("faces", {}).items():
            image = record["inspection"]["image"]
            lines += [f"- {face} image: {image['path']}; SHA-256 {image['sha256']}"]
            lines += [f"  - Source: {s['path']}; SHA-256 {s['sha256']}; status {s['status']}"
                      for s in record["inspection"]["sources"]]
            center = grading.get("centering", {}).get(face, {})
            lines += [f"- {face} centering: rule proposal={center.get('rule_proposal')}; "
                      f"effective score={center.get('score')}; explicit review={center.get('operator_review')}"]
        lines += [f"- {message}" for message in grading.get("unresolved", []) + grading["warnings"]]
        for key, penalty in session.data["grading"]["working"].get("penalties", {}).items():
            lines.append(f"- Finding {key}: {penalty}")
    with path.with_suffix(".md").open("x", encoding="utf-8") as output:
        output.write("\n".join(lines) + "\n")
    return path
