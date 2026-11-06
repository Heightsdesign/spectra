"""Synthetic traceability and workflow checks; no defect detection accuracy claim."""

from copy import deepcopy

import cv2
import numpy as np
import pytest
from test_selby_session import make
from test_selby_v02 import geometry

from selby_workstation.condition import (
    category_status,
    complete_category,
    current_findings,
    decide,
    indicators,
    manual_finding,
    map_points,
    regions,
    run_diagnostic,
)
from selby_workstation.inspection import History, autosave, export_report, recover, validate_group
from selby_workstation.session import Session
from spectra_scanner.storage import sha256_file


def prepared(tmp_path, angle=0):
    s, image, source = make(tmp_path)
    s.load_report(source)
    geometry(s, angle)
    validate_group(s, "physical")
    return s, image, source


@pytest.mark.parametrize("angle", [0, 11, -8])
def test_all_region_maps_rotate_without_downsampling(tmp_path, angle):
    s, _, _ = prepared(tmp_path, angle)
    for category in ("corners", "edges"):
        extracted = regions(s, category)
        assert len(extracted) == 4
        for region in extracted:
            matrix = np.array(region["metadata"]["patch_to_original"])
            assert matrix[:2, :2].T @ matrix[:2, :2] == pytest.approx(np.eye(2))
            size = region["metadata"]["dimensions"]
            patch = np.array([[size[0] / 2, size[1] / 2], [1.25, 3.75]])
            original = map_points(matrix, patch)
            assert map_points(np.linalg.inv(matrix), original) == pytest.approx(patch)
            x, y = np.rint(patch[0]).astype(int)
            point = map_points(matrix, [[x, y]])[0]
            expected = cv2.getRectSubPix(s.rgb, (1, 1), tuple(point.astype(float)))[0, 0]
            assert np.max(np.abs(region["rgb"][y, x].astype(int) - expected.astype(int))) <= 2
            assert region["rgb"].shape[:2] == (size[1], size[0])


@pytest.mark.parametrize("category", ["corners", "edges", "surface"])
def test_missing_uncertain_unvalidated_geometry_blocks_diagnostic(tmp_path, category):
    s, _, _ = make(tmp_path)
    with pytest.raises(ValueError, match="Validate"):
        regions(s, category)
    geometry(s)
    with pytest.raises(ValueError, match="Validate"):
        run_diagnostic(s, category)
    validate_group(s, "physical")
    s.set_notes("physical", 0, "edge uncertain")
    s.review("physical", 0, True)
    with pytest.raises(ValueError, match="Validate"):
        run_diagnostic(s, category)
    assert "condition" not in s.data


def test_manual_persistence_recovery_history_and_provenance(tmp_path):
    s, image, source = prepared(tmp_path, 7)
    hashes = [sha256_file(p) for p in (image, source)]
    s.data["inspection_face"] = "back"
    history = History(s)
    finding = manual_finding(
        s,
        "corners",
        [[120, 150], [130, 150], [130, 160], [120, 160]],
        "wear",
        "Visible small corner wear",
    )
    history.record()
    first = deepcopy(finding)
    decide(
        s,
        finding["id"],
        "reclassified",
        "artwork_or_texture",
        "Normal printed texture on closer inspection",
    )
    history.record()
    final = deepcopy(s.data["condition"])
    history.move(-1)
    assert s.data["condition"]["findings"] == [first]
    history.move(-1)
    assert "condition" not in s.data
    history.move(1)
    history.move(1)
    assert s.data["condition"] == final
    path = s.save(tmp_path / "versions")
    reopened = Session.reopen(path)
    assert reopened.data["condition"] == final and reopened.data["inspection_face"] == "back"
    draft = autosave(reopened, tmp_path / "drafts")
    assert recover(draft).data["condition"] == final
    report = export_report(reopened, tmp_path / "reports")
    assert "Condition inspection" in report.with_suffix(".md").read_text(encoding="utf-8")
    assert hashes == [sha256_file(p) for p in (image, source)]
    assert reopened.data["sources"][0]["status"] == "review_required"


def test_false_positives_remain_unreviewed_and_can_be_rejected(tmp_path):
    s, image, _ = prepared(tmp_path)
    # Add a synthetic printed bright square; diagnostic cannot infer its meaning.
    from PIL import Image

    rgb = np.array(Image.open(image))
    rgb[250:258, 200:208] = 255
    Image.fromarray(rgb).save(image)
    # Build a new image-specific record; never mutate an opened session's identity.
    s = Session(image)
    s.data["operator"] = "Test reviewer"
    geometry(s)
    validate_group(s, "physical")
    _, findings = run_diagnostic(s, "surface")
    assert findings and all(f["decision"] == "unreviewed" for f in findings)
    assert category_status(s, "surface") == "suggestions_pending"
    with pytest.raises(ValueError, match="Review all"):
        complete_category(s, "surface", "Visual review")
    for f in findings:
        decide(s, f["id"], "rejected", "artwork_or_texture", "Printed feature; not observed damage")
    complete_category(s, "surface", "All displayed suggestions are normal printed features")
    assert category_status(s, "surface") == "operator_reviewed"
    assert all(f["decision"] == "rejected" for f in current_findings(s, "surface"))
    assert not s.data["automatic_acceptance"]


def test_flat_region_has_no_visual_suggestions():
    region = dict(
        rgb=np.full((80, 80, 3), 180, np.uint8),
        valid=np.ones((80, 80), bool),
        metadata=dict(category="surface"),
    )
    assert indicators(region) == []


def test_geometry_change_invalidates_review_and_rerun_archives_old_findings(tmp_path):
    s, _, _ = prepared(tmp_path)
    run_diagnostic(s, "edges")
    for f in current_findings(s, "edges"):
        decide(s, f["id"], "rejected", f["type"], "Synthetic printed geometry")
    complete_category(s, "edges", "Reviewed all four strips")
    assert category_status(s, "edges") == "operator_reviewed"
    prior = deepcopy(s.data["condition"])
    points = np.array(s.data["physical"][0]["endpoints"]) + [0, 0.1]
    s.edit("physical", 0, points)
    assert category_status(s, "edges") == "geometry_changed_review_required"
    with pytest.raises(ValueError):
        complete_category(s, "edges", "review")
    s.review("physical", 0)
    validate_group(s, "physical")
    _, new = run_diagnostic(s, "edges")
    assert s.data["condition"]["runs"][0] == prior["runs"][0]
    assert current_findings(s, "edges") == new


@pytest.mark.parametrize("tamper", ["image", "source", "run_id", "polygon"])
def test_condition_provenance_mismatch_rejected(tmp_path, tamper):
    s, _, _ = prepared(tmp_path)
    run_diagnostic(s, "surface")
    run = s.data["condition"]["runs"][0]
    if tamper == "image":
        run["image"]["sha256"] = "0" * 64
    if tamper == "source":
        run["sources"][0]["status"] = "accepted"
    if tamper == "run_id":
        manual_finding(
            s, "surface", [[150, 150], [155, 150], [155, 155], [150, 155]], "other", "test"
        )
        s.data["condition"]["findings"][-1].update(
            origin="experimental_suggestion", run_id="missing"
        )
    if tamper == "polygon":
        manual_finding(
            s, "surface", [[150, 150], [155, 150], [155, 155], [150, 155]], "other", "test"
        )
        s.data["condition"]["findings"][-1]["polygon_original"][0][0] = -1
    with pytest.raises(ValueError):
        s.save(tmp_path / "versions")


def test_manual_surface_without_geometry_requires_explicit_evidence(tmp_path):
    s, _, _ = make(tmp_path)
    polygon = [[10, 10], [20, 10], [20, 20], [10, 20]]
    with pytest.raises(ValueError):
        manual_finding(s, "surface", polygon, "scratch", "")
    manual_finding(s, "surface", polygon, "scratch", "Operator observed scratch in original scan")
    complete_category(s, "surface", "Full scan manually inspected; geometry unavailable")
    assert category_status(s, "surface") == "operator_reviewed"
    assert category_status(s, "corners") == "not_inspected"
