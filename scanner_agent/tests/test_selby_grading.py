"""Synthetic draft-policy and audit tests; no grading accuracy claim."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image
from test_selby_session import make
from test_selby_v02 import geometry

from selby_workstation import grading as g
from selby_workstation.condition import (
    complete_category,
    current_findings,
    decide,
    manual_finding,
    run_diagnostic,
)
from selby_workstation.inspection import History, autosave, export_report, recover, validate_group
from selby_workstation.session import Session
from spectra_scanner.storage import sha256_file


def face_session(path, face):
    path.mkdir()
    s, image, report = make(path)
    if face == "back":
        rgb = s.rgb.copy()
        rgb[300:310, 300:310] = [50, 60, 70]
        new_image = path / "back.bmp"
        Image.fromarray(rgb).save(new_image)
        s = Session(new_image)
        s.data["operator"] = "Test reviewer"
    else:
        s.load_report(report)
    s.data["inspection_face"] = face
    geometry(s)
    # Exact balanced synthetic front geometry, compatible with the 10 threshold.
    for i, points in enumerate(
        [
            [[110, 110], [442, 110]],
            [[442, 110], [442, 590]],
            [[442, 590], [110, 590]],
            [[110, 590], [110, 110]],
        ]
    ):
        s.edit("printed", i, points)
        s.review("printed", i)
    for family in ("physical", "printed"):
        validate_group(s, family)
    for c in g.CATEGORIES:
        complete_category(s, c, "Synthetic full-category visual review")
    return s


@pytest.fixture
def pair(tmp_path):
    front = face_session(tmp_path / "front", "front")
    back = face_session(tmp_path / "back", "back")
    g.initialize(front, "SYNTHETIC-CARD-1")
    g.attach_face(front, front, "Front identity verified")
    g.attach_face(front, back, "Back belongs to synthetic card 1")
    g.set_centering_review(
        front, "back", 10, "Explicit synthetic back centering assessment; no thresholds"
    )
    return front, back


def add_finding(front, category="corners", decision="confirmed"):
    f = manual_finding(
        front,
        category,
        [[120, 140], [125, 140], [125, 145], [120, 145]],
        "wear",
        "Synthetic wear observation",
    )
    if decision != "confirmed":
        decide(front, f["id"], decision, "artwork_or_texture", "Synthetic classification review")
    complete_category(front, category, "Reviewed synthetic observation")
    g.attach_face(front, front, "Updated inspected front")
    return "front:" + f["id"]


def test_ten_candidate_requires_both_faces_and_human_validation(pair):
    front, _ = pair
    result = g.evaluate(front)
    assert result["state"] == "Ready for operator review"
    assert result["subgrades"] == dict.fromkeys(g.SUBGRADES, 10)
    assert result["calculated_grade"] == 10 and result["final_grade"] is None
    with pytest.raises(ValueError, match="attest"):
        g.human_validate(front, "Looks good")
    g.human_validate(front, "Both faces examined; physical damage deduplicated", True)
    assert g.evaluate(front)["state"] == "Human validated"
    assert g.evaluate(front)["final_grade"] == 10
    assert front.data["review_status"] == "review_required"
    assert not front.data["automatic_acceptance"]
    assert front.data["sources"][0]["status"] == "review_required"


def test_penalty_application_removal_and_history(pair):
    front, _ = pair
    key = add_finding(front)
    assert g.evaluate(front)["calculated_grade"] is None
    g.set_penalty(front, key, 4, True, 4.5, "Operator warrants wear penalty", "damage-a")
    result = g.evaluate(front)
    assert result["subgrades"]["corners"] == 5.5
    assert result["calculated_grade"] == 6
    g.set_penalty(front, key, 4, False, 0, "Closer examination: no penalty warranted", "damage-a")
    assert g.evaluate(front)["calculated_grade"] == 10
    events = front.data["grading"]["events"]
    assert events[-2]["working"]["penalties"][key]["penalty"] == 4.5
    assert events[-1]["working"]["penalties"][key]["penalty"] == 0


def test_no_automatic_penalty_and_no_approval_of_unreviewed_suggestions(pair):
    front, _ = pair
    run_diagnostic(front, "surface")
    g.attach_face(front, front, "Diagnostic produced new unreviewed information")
    assert g.evaluate(front)["calculated_grade"] is None
    assert not front.data["grading"]["working"]["penalties"]
    for finding in current_findings(front, "surface"):
        decide(front, finding["id"], "rejected", "artwork_or_texture", "Synthetic printed feature")
    key = add_finding(front, "surface", "rejected")
    with pytest.raises(ValueError, match="confirmed"):
        g.set_penalty(front, key, 2, True, 1, "Invalid rejected penalty", "x")


@pytest.mark.parametrize(
    "grades,expected",
    [
        ([10, 10, 10, 10], 10),
        ([10, 10, 10, 5], 6),
        ([9.5, 9.5, 9.5, 9.5], 9),
        ([1, 10, 10, 10], 2),
        ([1, 1, 1, 1], 1),
        ([8.5, 9, 10, 10], 9),
    ],
)
def test_mean_weakest_ceiling_floor_and_bounds(grades, expected):
    p = json.loads(g.POLICY_PATH.read_text())
    assert (
        g.calculate(dict(zip(g.SUBGRADES, grades, strict=True)), [], p)["calculated_grade"]
        == expected
    )


@pytest.mark.parametrize(
    "kind,maximum",
    [
        ("severely_crushed_corner", 6),
        ("minor_localized_crease", 6),
        ("pronounced_crease", 4),
        ("tear", 3),
        ("significant_delamination", 3),
        ("severe_overall_alteration", 2),
    ],
)
def test_confirmed_structural_caps_even_with_zero_penalty(pair, kind, maximum):
    front, _ = pair
    key = add_finding(front)
    g.set_penalty(
        front, key, 5, False, 0, "Confirmed synthetic structural type", "structural-a", kind
    )
    result = g.evaluate(front)
    assert result["subgrades"]["corners"] == 10
    assert result["calculated_grade"] == maximum


def test_multiple_defects_caps_and_duplicate_damage(pair):
    front, back = pair
    a = add_finding(front)
    b = add_finding(front, "edges")
    g.set_penalty(front, a, 3, True, 0.5, "First damage", "one", "minor_localized_crease")
    g.set_penalty(front, b, 5, True, 1, "Second damage", "two", "tear")
    assert g.evaluate(front)["calculated_grade"] == 3
    assert g.evaluate(front)["penalty_totals"] == dict(corners=0.5, edges=1, surface=0)
    g.set_penalty(front, b, 5, True, 1, "Actually same damage", "one", "tear")
    assert g.evaluate(front)["calculated_grade"] is None
    assert any("Double counting" in x for x in g.evaluate(front)["unresolved"])
    g.set_penalty(
        front, b, 5, False, 0, "Duplicate evidence only; primary finding owns penalty/cap", "one"
    )
    assert g.evaluate(front)["calculated_grade"] == 6
    f = manual_finding(
        back, "corners", [[120, 140], [125, 140], [125, 145], [120, 145]], "wear", "Back wear"
    )
    complete_category(back, "corners", "Reviewed back wear")
    g.attach_face(front, back, "Updated back observation")
    key = "back:" + f["id"]
    g.set_penalty(front, key, 2, True, 0.5, "Separate back damage", "back-damage")
    assert g.evaluate(front)["penalty_totals"]["corners"] == 1


def test_override_authorization_audit_and_immutable_calculation(pair, tmp_path, monkeypatch):
    front, _ = pair
    key = add_finding(front)
    g.set_penalty(
        front, key, 5, False, 0, "Confirmed severe alteration", "x", "severe_overall_alteration"
    )
    with pytest.raises(ValueError, match="allowlist"):
        g.record_override(front, 8, "grade", "Attempt without authority")
    auth = tmp_path / "authorization.json"
    auth.write_text(json.dumps(dict(authorized_operators=[front.data["operator"]])))
    monkeypatch.setattr(g, "AUTHORIZATION_PATH", auth)
    with pytest.raises(ValueError, match="explanation"):
        g.record_override(front, 8, "grade", " ")
    g.record_override(
        front, 8, "structural_caps", "Authorized exception to provisional alteration cap"
    )
    r = g.evaluate(front)
    assert r["calculated_grade"] == 2 and r["proposed_grade"] == 8
    g.human_validate(front, "Explicit provisional exception, not release", True)
    assert g.evaluate(front)["final_grade"] == 8
    original = deepcopy(front.data["grading"]["decisions"])
    g.record_override(front, 7, "grade", "Revised authorized exception")
    assert g.evaluate(front)["state"] == "Ready for operator review"
    assert front.data["grading"]["decisions"] == original
    assert len(front.data["grading"]["overrides"]) == 2
    g.validate_grading(front)


def test_incomplete_uncertain_and_no_silent_back_thresholds(pair):
    front, back = pair
    proposal, _, warning = g.centering_proposal(
        g.inspection_snapshot(back), front.data["grading"]["policy"]
    )
    assert proposal is None and "No back" in warning
    back.set_notes("physical", 0, "Uncertain boundary")
    back.review("physical", 0, True)
    g.attach_face(front, back, "Back geometry now uncertain")
    result = g.evaluate(front)
    assert result["calculated_grade"] is None
    assert any("uncertain" in warning for warning in result["warnings"])
    with pytest.raises(ValueError, match="Resolve"):
        g.human_validate(front, "Cannot approve missing information", True)


@pytest.mark.parametrize(
    "imbalance,score",
    [
        (50, 10),
        (55, 10),
        (55.01, 9.5),
        (57, 9.5),
        (60, 9),
        (62, 8.5),
        (65, 8),
        (70, 7),
        (75, 6),
        (80, 5),
        (80.01, None),
    ],
)
def test_front_threshold_boundaries(pair, monkeypatch, imbalance, score):
    front, _ = pair
    snapshot = g.inspection_snapshot(front)
    monkeypatch.setattr(
        g,
        "measure",
        lambda s: dict(
            status="human_geometry_validated",
            centering_percent=dict(left=imbalance, right=100 - imbalance, top=50, bottom=50),
        ),
    )
    assert g.centering_proposal(snapshot, front.data["grading"]["policy"])[0] == score


def test_persistence_recovery_undo_redo_and_policy_reproducibility(pair, tmp_path, monkeypatch):
    front, _ = pair
    key = add_finding(front)
    h = History(front)
    g.set_penalty(front, key, 2, True, 2, "Operator wear penalty", "x")
    h.record()
    old_events = deepcopy(front.data["grading"]["events"])
    h.move(-1)
    assert key not in front.data["grading"]["working"]["penalties"]
    assert front.data["grading"]["events"][: len(old_events)] == old_events
    h.move(1)
    assert front.data["grading"]["working"]["penalties"][key]["penalty"] == 2
    g.validate_grading(front)
    g.human_validate(front, "Reviewed both faces and deduplication", True)
    path = front.save(tmp_path / "sessions")
    saved_hash = sha256_file(path)
    reopened = Session.reopen(path)
    assert g.evaluate(reopened)["final_grade"] == 9
    assert (
        recover(autosave(reopened, tmp_path / "drafts")).data["grading"] == reopened.data["grading"]
    )
    # Installed policy changes cannot silently change an existing pinned dossier.
    replacement = tmp_path / "policy.json"
    p = deepcopy(reopened.data["grading"]["policy"])
    p["version"] = "future-draft"
    p["weakest_plus"] = 0
    replacement.write_text(json.dumps(p))
    monkeypatch.setattr(g, "POLICY_PATH", replacement)
    assert g.evaluate(reopened)["policy_version"] == "0.4.0"
    assert g.evaluate(reopened)["calculated_grade"] == 9
    report = export_report(reopened, tmp_path / "exports")
    data = json.loads(report.read_text())
    assert data["grading"]["final_grade"] == 9
    assert "Mean" in report.with_suffix(".md").read_text(encoding="utf-8")
    assert sha256_file(path) == saved_hash


def test_stale_current_face_and_changed_evidence_fail_closed(pair, tmp_path):
    front, back = pair
    saved_back = back.save(tmp_path / "back-versions")
    g.attach_face(front, back, "Pin saved back version")
    before = deepcopy(front.data["grading"])
    front.data["notes"] = "Unrelated session note"
    assert g.evaluate(front)["calculated_grade"] == 10
    front.set_notes("physical", 0, "Geometry reconsidered")
    assert g.evaluate(front)["calculated_grade"] is None
    front.data["grading"] = before
    saved_back.write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        front.save(tmp_path / "sessions")


def test_same_image_missing_faces_and_tampered_history(pair, tmp_path):
    front, _ = pair
    other = Session(Path(front.data["image"]["path"]))
    other.data["operator"] = front.data["operator"]
    other.data["inspection_face"] = "back"
    with pytest.raises(ValueError, match="different"):
        g.attach_face(front, other, "Invalid pairing")
    front.data["grading"]["working"]["penalties"]["forged"] = dict(penalty=9)
    with pytest.raises(ValueError, match="history"):
        front.save(tmp_path / "sessions")


@pytest.mark.parametrize("invalid", [-0.5, 0.25, 9.5, float("nan"), True])
def test_invalid_penalty_values_rejected(pair, invalid):
    front, _ = pair
    key = add_finding(front)
    with pytest.raises(ValueError):
        g.set_penalty(front, key, 2, True, invalid, "Invalid half-point penalty", "x")


def test_missing_opposite_face_and_explicit_uncertain_front_resolution(pair):
    front, back = pair
    g.initialize(back, "SINGLE-FACE")
    g.attach_face(back, back, "Only back available")
    g.set_centering_review(back, "back", 10, "Explicit back assessment")
    assert g.evaluate(back)["calculated_grade"] is None
    assert "front inspection missing" in g.evaluate(back)["unresolved"]
    front.set_notes("printed", 0, "Tentative printed frame")
    front.review("printed", 0, True)
    g.attach_face(front, front, "Record uncertain front geometry")
    assert g.evaluate(front)["centering"]["front"]["score"] is None
    g.set_centering_review(
        front,
        "front",
        8.5,
        "Explicit provisional assessment after manual review of uncertain frame",
    )
    result = g.evaluate(front)
    assert result["subgrades"]["centering"] == 8.5
    assert any("uncertain" in warning for warning in result["warnings"])
    assert result["commercial_release_authorized"] is False


def test_initialization_undo_preserves_history_and_can_restart(tmp_path):
    s = face_session(tmp_path / "face", "front")
    h = History(s)
    g.initialize(s, "FIRST")
    h.record()
    h.move(-1)
    assert g.evaluate(s)["state"] == "Draft"
    assert len(s.data["grading"]["events"]) == 2
    g.initialize(s, "SECOND")
    assert s.data["grading"]["working"]["card_id"] == "SECOND"
    assert s.data["grading"]["events"][0]["working"]["card_id"] == "FIRST"
    g.validate_grading(s)


def test_resolved_front_score_cannot_be_changed_by_regular_review(pair):
    front, _ = pair
    with pytest.raises(ValueError, match="authorized"):
        g.set_centering_review(front, "front", 9, "Attempt to change rule-derived score")
    g.set_centering_review(front, "front", 10, "Confirm the resolved rule proposal")
    assert g.evaluate(front)["centering"]["front"]["rule_proposal"] == 10


def test_blocked_source_status_retained_in_provisional_grading(tmp_path):
    s = face_session(tmp_path / "blocked", "front")
    # New synthetic report, never rewrite the existing evidence source.
    original = s.data["sources"][0]
    value = json.loads(Path(original["path"]).read_text())
    value["status"] = "blocked"
    blocked = tmp_path / "synthetic-blocked-report.json"
    blocked.write_text(json.dumps(value))
    fresh = Session(Path(s.data["image"]["path"]))
    fresh.data["operator"] = "Test reviewer"
    fresh.load_report(blocked)
    s.data["sources"] = deepcopy(fresh.data["sources"])
    s.reports = fresh.reports
    g.initialize(s, "BLOCKED-CARD")
    g.attach_face(s, s, "Independent manual inspection with blocked source preserved")
    result = g.evaluate(s)
    assert result["source_provenance"]["front"][0]["status"] == "blocked"
    assert any("blocked" in warning for warning in result["warnings"])
    assert not result["commercial_release_authorized"]
    assert not result["automatic_acceptance"]
    assert result["calculated_grade"] is None
