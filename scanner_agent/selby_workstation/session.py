"""Original-pixel inspection decisions with exclusive, versioned persistence."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np

from spectra_centering.inputs import read_inputs
from spectra_physical_reference.model import intersections, load_image, load_report, read, side_line
from spectra_reference import COORDINATES
from spectra_reference.geometry import line, points_on_reference, quad
from spectra_reference.inputs import load_bundle
from spectra_scanner.common import AgentError, utc_now, write_json_new
from spectra_scanner.storage import inspect_image, sha256_file

from . import __version__


def endpoint_line(points: Any, index: int, size: list[int]) -> list[float]:
    array = np.asarray(points, dtype=float)
    if array.shape != (2, 2) or not np.isfinite(array).all():
        raise ValueError("Two finite original-pixel points are required")
    abc = line(np.cross(np.r_[array[0], 1.0], np.r_[array[1], 1.0])).tolist()
    side_line(dict(index=index, endpoints=array.tolist(), line_abc=abc), size)
    return abc


def decision() -> dict:
    return dict(
        status="unannotated",
        definition=None,
        candidate_id=None,
        basis=None,
        endpoints=None,
        line_abc=None,
        notes="",
        confirmed_at_utc=None,
        reviewed=None,
    )


def reviewed(side: dict) -> dict:
    return {
        k: deepcopy(side[k])
        for k in ("status", "definition", "candidate_id", "basis", "endpoints", "line_abc", "notes")
    }


def report_data(path: Path, image: Path, identity: dict) -> tuple[dict, dict, list[Path]]:
    """Reuse existing adapters; imports predictions, never runs a detector/gate override."""
    path = path.resolve()
    before = sha256_file(path)
    data = read(path)
    kind = data.get("kind")
    dependencies = []
    if kind == "single_image":
        if data.get("algorithm_version") != "0.2.0":
            raise ValueError("Physical predictions require frozen S2.1 0.2.0")
        data = load_report(path, identity)
    elif kind == "printed_frame_candidate_evaluation":
        _, data, provenance = load_bundle(image, path)
        dependencies = [Path(provenance["s2_1"]["path"])]
    elif kind == "printed_frame_analysis":
        if (
            data.get("schema_version") != 1
            or data.get("algorithm_version") != "0.1.0"
            or not data.get("input_hashes_verified_after_analysis")
        ):
            raise ValueError("Requires a verified S2.2a 0.1.0 per-image report")
        physical = Path(data["boundary_report"]["path"])
        _, evidence = read_inputs(image, physical)
        if (
            data["inputs"]["image_sha256"] != identity["sha256"]
            or data["boundary_report"]["sha256"] != evidence["boundary_report"]["sha256"]
        ):
            raise ValueError("S2.2a image/report provenance mismatch")
        dependencies = [physical]
    else:
        raise ValueError(
            "Load a per-image S2.1, S2.2a or S2.2b report (not a summary or reference)"
        )
    if before != sha256_file(path):
        raise ValueError("Report changed during loading")
    metadata = dict(
        path=str(path),
        sha256=before,
        kind=kind,
        algorithm_version=data["algorithm_version"],
        status=data.get("status"),
        baseline_status=data.get("baseline", {}).get("status"),
        flags=deepcopy(
            data.get("quality_flags", data.get("baseline", {}).get("flags_requiring_review", []))
        ),
    )
    return data, metadata, dependencies


class Session:
    def __init__(self, image: Path):
        before = sha256_file(image)
        self.encoding = inspect_image(image)
        frame = self.encoding["frames"][0]
        if (
            self.encoding["frame_count"] != 1
            or frame["mode"] != "RGB"
            or frame["bits_per_pixel"] != 24
            or frame.get("orientation_tag", 1) != 1
        ):
            raise ValueError("V0.1 requires a single RGB24 BMP/PNG/TIFF with stored orientation 1")
        self.rgb, identity = load_image(image)
        if before != identity["sha256"] or identity["dimensions"] != [
            frame["width"],
            frame["height"],
        ]:
            raise ValueError("Original changed or encoded/decoded geometry differs")
        self.data: dict[str, Any] = dict(
            schema_version=1,
            kind="selby_inspection_session",
            tool_version=__version__,
            coordinate_system=COORDINATES,
            session_id=str(uuid4()),
            version_id=None,
            created_at_utc=utc_now(),
            parent=None,
            image=dict(path=str(image.resolve()), **identity),
            image_encoding=deepcopy(self.encoding),
            operator="",
            notes="",
            sources=[],
            prediction_exposure=False,
            physical=[decision() for _ in range(4)],
            printed=[decision() for _ in range(4)],
            review_status="review_required",
            automatic_acceptance=False,
            human_confirmation_is_not_certified_ground_truth=True,
            view=dict(
                zoom=1.0, center=[identity["dimensions"][0] / 2, identity["dimensions"][1] / 2]
            ),
        )
        self.reports: list[tuple[dict, dict]] = []
        self.saved_path: Path | None = None
        self.saved_sha: str | None = None

    @property
    def identity(self) -> dict:
        return {k: self.data["image"][k] for k in ("sha256", "dimensions", "mode")}

    def load_report(self, path: Path) -> None:
        if path.resolve() in [Path(s["path"]) for s in self.data["sources"]]:
            return
        # Validate the entire import before changing the session.
        records: list[tuple[dict, dict]] = []

        def collect(candidate: Path) -> None:
            candidate = candidate.resolve()
            if candidate in [Path(s["path"]) for s in self.data["sources"]] or candidate in [
                Path(m["path"]) for _, m in records
            ]:
                return
            value, meta, deps = report_data(
                candidate, Path(self.data["image"]["path"]), self.identity
            )
            for dep in deps:
                collect(dep)
            records.append((value, meta))

        collect(path)
        self.reports.extend(records)
        self.data["sources"].extend(meta for _, meta in records)

    def physical_corners(self) -> Any:
        for value, _ in self.reports:
            corners = value.get("baseline", {}).get("geometry", {}).get("corners_pixels")
            if corners is not None:
                return np.asarray(corners, dtype=float)
        width, height = self.identity["dimensions"]
        return np.array(
            [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=float
        )

    def predictions(self, family: str, index: int) -> list[dict]:
        candidates = []
        for value, metadata in self.reports:
            if family == "physical" and metadata["kind"] == "single_image":
                for side in value.get("baseline", {}).get("sides", []):
                    if side["index"] == index:
                        candidates.append(
                            dict(
                                label=f"{Path(metadata['path']).parent.name}: selected",
                                line_abc=side["line_abc"],
                                source=metadata,
                                candidate_id=side.get("selected_layer_id", "baseline"),
                            )
                        )
                        for candidate in side.get("candidate_layers", []):
                            candidates.append(
                                dict(
                                    label=f"{Path(metadata['path']).parent.name}: {candidate['id']}",
                                    line_abc=candidate["line_abc"],
                                    source=metadata,
                                    candidate_id=candidate["id"],
                                )
                            )
            elif family == "printed" and metadata["kind"] in (
                "printed_frame_analysis",
                "printed_frame_candidate_evaluation",
            ):
                for side in value.get("sides", []):
                    if side["index"] == index:
                        for candidate in side["candidates"]:
                            if candidate.get("line_abc") is not None:
                                candidates.append(
                                    dict(
                                        label=f"{Path(metadata['path']).parent.name}: {candidate['id']}",
                                        line_abc=candidate["line_abc"],
                                        source=metadata,
                                        candidate_id=candidate["id"],
                                    )
                                )
        return candidates

    def hypotheses(self) -> list[dict]:
        result = []
        for value, meta in self.reports:
            lookup = {c["id"]: c for s in value.get("sides", []) for c in s.get("candidates", [])}
            for frame in value.get("frame_evaluation", {}).get("hypotheses", []):
                if frame.get("geometrically_valid") and not frame.get("s2_2c_input_exclusion"):
                    result.append(
                        dict(
                            label=f"{Path(meta['path']).parent.name}: {frame['id']}",
                            candidates=[
                                dict(
                                    line_abc=lookup[cid]["line_abc"], source=meta, candidate_id=cid
                                )
                                for cid in frame["candidate_ids"]
                            ],
                        )
                    )
        return result

    def endpoints(self, abc: Any, index: int) -> list:
        points = points_on_reference(
            self.physical_corners(), index, line(abc), np.array([0.18, 0.82])
        )
        # Same original-pixel endpoint contract as the existing physical-reference tool.
        endpoint_line(points, index, self.identity["dimensions"])
        return points.tolist()

    def edit(self, family: str, index: int, points: Any, basis: dict | None = None) -> None:
        abc = endpoint_line(points, index, self.identity["dimensions"])
        old = self.data[family][index]
        new = decision()
        new.update(
            endpoints=np.asarray(points, dtype=float).tolist(),
            line_abc=abc,
            definition="candidate" if basis else "manual",
            candidate_id=basis["candidate_id"] if basis else None,
            basis=deepcopy(basis or old["basis"]),
            notes=old["notes"],
        )
        self.data[family][index] = new

    def seed(self, family: str, index: int, prediction: dict) -> None:
        basis = dict(
            report_path=prediction["source"]["path"],
            report_sha256=prediction["source"]["sha256"],
            candidate_id=prediction["candidate_id"],
        )
        self.edit(family, index, self.endpoints(prediction["line_abc"], index), basis)
        self.data["prediction_exposure"] = True

    def set_notes(self, family: str, index: int, notes: str) -> None:
        side = self.data[family][index]
        if side["notes"] != notes:
            side.update(notes=notes, status="unannotated", reviewed=None, confirmed_at_utc=None)

    def review(self, family: str, index: int, uncertain: bool = False) -> None:
        side = self.data[family][index]
        if uncertain and not side["notes"].strip():
            raise ValueError("Record a side note explaining the uncertainty")
        if not uncertain and side["line_abc"] is None:
            raise ValueError("Draw or select a line before confirming")
        side["status"] = "ambiguous" if uncertain else "annotated"
        side["confirmed_at_utc"] = utc_now()
        side["reviewed"] = reviewed(side)

    def geometry_warnings(self) -> list[str]:
        warnings = []
        try:
            physical = intersections(
                [s["line_abc"] for s in self.data["physical"]], self.identity["dimensions"]
            )
            if all(p is not None for p in physical) and all(
                s["line_abc"] is not None for s in self.data["printed"]
            ):
                quad([s["line_abc"] for s in self.data["printed"]], np.asarray(physical))
        except (AgentError, ValueError, RuntimeError) as exc:
            warnings.append(str(exc))
        return warnings

    def validate(self, require_operator: bool = True) -> None:
        d = self.data
        if (
            d.get("schema_version") != 1
            or d.get("kind") != "selby_inspection_session"
            or d.get("tool_version") not in ("0.1.0", "0.2.0", "0.3.0", "0.4.0")
            or d.get("coordinate_system") != COORDINATES
        ):
            raise ValueError("Incompatible workstation session")
        UUID(d["session_id"])
        if (
            d["image"]["dimensions"] != [self.rgb.shape[1], self.rgb.shape[0]]
            or d["image"]["mode"] != "RGB"
        ):
            raise ValueError("Image identity differs from decoded original")
        if d.get("inspection_face", "unspecified") not in ("unspecified", "front", "back"):
            raise ValueError("Invalid image-specific inspection face")
        validations = d.get("boundary_validation", {})
        if not isinstance(validations, dict) or validations.keys() - {"physical", "printed"}:
            raise ValueError("Invalid boundary validation records")
        for stamp in validations.values():
            if (
                not isinstance(stamp, dict)
                or set(stamp) != {"sides", "operator", "at_utc"}
                or not isinstance(stamp["sides"], list)
                or len(stamp["sides"]) != 4
                or not isinstance(stamp["operator"], str)
                or not isinstance(stamp["at_utc"], str)
            ):
                raise ValueError("Invalid boundary validation snapshot")
        if (
            d.get("review_status") != "review_required"
            or d.get("automatic_acceptance") is not False
            or d.get("human_confirmation_is_not_certified_ground_truth") is not True
        ):
            raise ValueError("Session cannot clear review or grant acceptance")
        if any(key in d for key in ("score", "grade", "grading_score", "accepted")):
            raise ValueError("Top-level grades/acceptance are forbidden; use the supervised grading dossier")
        if not isinstance(d["operator"], str) or (require_operator and not d["operator"].strip()):
            raise ValueError("Operator identity is required to save")
        if not isinstance(d["notes"], str) or type(d["prediction_exposure"]) is not bool:
            raise ValueError("Invalid notes/exposure provenance")
        if d["image_encoding"] != self.encoding:
            raise ValueError("Encoded-image provenance differs")
        image = Path(d["image"]["path"])
        if sha256_file(image) != d["image"]["sha256"]:
            raise ValueError("Original image changed")
        for source in d["sources"]:
            if sha256_file(Path(source["path"])) != source["sha256"]:
                raise ValueError("Source report changed or unavailable")
            _, current, _ = report_data(Path(source["path"]), image, self.identity)
            if source != current:
                raise ValueError("Source provenance/status was modified")
        for family in ("physical", "printed"):
            if len(d[family]) != 4:
                raise ValueError("Four ordered side slots required per family")
            for index, side in enumerate(d[family]):
                if set(side) != set(decision()):
                    raise ValueError("Side schema differs from workstation V0.1")
                if side["status"] not in ("unannotated", "annotated", "ambiguous"):
                    raise ValueError("Unknown side decision")
                if side["line_abc"] is not None:
                    side_line(dict(side, index=index), self.identity["dimensions"])
                    if side["definition"] not in ("manual", "candidate"):
                        raise ValueError("Invalid line origin")
                    if side["definition"] == "manual" and side["candidate_id"] is not None:
                        raise ValueError("Manual edits cannot claim exact candidate selection")
                    basis = side["basis"]
                    if basis:
                        matches = [
                            p
                            for p in self.predictions(family, index)
                            if p["source"]["path"] == basis.get("report_path")
                            and p["source"]["sha256"] == basis.get("report_sha256")
                            and p["candidate_id"] == basis.get("candidate_id")
                        ]
                        if not matches:
                            raise ValueError("Line basis does not match source provenance")
                        if side["definition"] == "candidate" and (
                            side["candidate_id"] != basis["candidate_id"]
                            or not np.allclose(
                                line(side["line_abc"]),
                                line(matches[0]["line_abc"]),
                                rtol=0,
                                atol=1e-8,
                            )
                        ):
                            raise ValueError(
                                "Selected candidate geometry changed without manual attribution"
                            )
                    elif side["definition"] == "candidate":
                        raise ValueError("Candidate line requires exact source provenance")
                elif side["endpoints"] is not None or side["status"] == "annotated":
                    raise ValueError("Missing reviewed line")
                if side["status"] in ("annotated", "ambiguous"):
                    if side["reviewed"] != reviewed(side) or not side["confirmed_at_utc"]:
                        raise ValueError("Geometry/decision changed after review")
                    if side["status"] == "ambiguous" and not side["notes"].strip():
                        raise ValueError("Uncertain side requires an explanation")
        from .condition import validate_condition

        validate_condition(self)
        from .grading import validate_grading

        validate_grading(self)
        view = d["view"]
        if (
            not np.isfinite(view["zoom"])
            or not 0.01 <= view["zoom"] <= 64
            or np.asarray(view["center"]).shape != (2,)
            or not np.isfinite(view["center"]).all()
        ):
            raise ValueError("Invalid original-pixel view state")

    def save(self, directory: Path) -> Path:
        self.validate()
        if self.saved_path and sha256_file(self.saved_path) != self.saved_sha:
            raise ValueError("Previous session version changed")
        version = deepcopy(self.data)
        if "grading" in self.data:
            from .grading import evaluate

            version["saved_grading_diagnostic"] = evaluate(self)
        version.update(
            tool_version=__version__,
            version_id=str(uuid4()),
            saved_at_utc=utc_now(),
            parent=dict(path=str(self.saved_path), sha256=self.saved_sha)
            if self.saved_path
            else None,
            geometry_warnings=self.geometry_warnings(),
        )
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"inspection-{version['session_id']}-{version['version_id']}.json"
        write_json_new(path, version)
        self.saved_path, self.saved_sha = path.resolve(), sha256_file(path)
        self.data = version
        return path

    @classmethod
    def reopen(cls, path: Path) -> Session:
        before = sha256_file(path)
        value = read(path)
        obj = cls(Path(value["image"]["path"]))
        if obj.identity != {k: value["image"][k] for k in ("sha256", "dimensions", "mode")}:
            raise ValueError("Session image identity differs from decoded original")
        for source in value["sources"]:
            obj.load_report(Path(source["path"]))
        if obj.data["sources"] != value["sources"]:
            raise ValueError("Session report provenance differs")
        obj.data = value
        obj.validate()
        UUID(value["version_id"])
        parent = value.get("parent")
        if parent and sha256_file(Path(parent["path"])) != parent["sha256"]:
            raise ValueError("Previous session version missing or changed")
        if sha256_file(path) != before:
            raise ValueError("Session changed while reading")
        obj.saved_path, obj.saved_sha = path.resolve(), before
        return obj
