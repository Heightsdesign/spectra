# ruff: noqa: E402
import json
from copy import deepcopy

import numpy as np
import pytest
from test_selby_session import make

from selby_workstation.inspection import (
    History,
    autosave,
    export_report,
    measure,
    recover,
    validate_group,
)
from selby_workstation.session import Session
from spectra_scanner.storage import sha256_file


def geometry(s, angle=0, offset=(0, 0)):
    theta = np.deg2rad(angle)
    rotation = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    for family, corners in [
        ("physical", [[90, 90], [462, 90], [462, 610], [90, 610]]),
        ("printed", [[110, 120], [422, 120], [422, 560], [110, 560]]),
    ]:
        points = (np.array(corners) - [276, 350]) @ rotation.T + [276, 350] + offset
        for i in range(4):
            p, q = points[i], points[(i + 1) % 4]
            s.edit(family, i, [p + 0.2 * (q - p), p + 0.8 * (q - p)])
            s.review(family, i)


@pytest.mark.parametrize("angle,offset", [(0, (0, 0)), (8, (0, 0)), (-7, (8, -9))])
def test_reused_measurement_rotation_translation_and_validation(tmp_path, angle, offset):
    s, _, _ = make(tmp_path)
    geometry(s, angle, offset)
    r = measure(s)
    assert r["status"] == "provisional"
    assert [
        r["margins"][n]["mean_pixels"] for n in ("top", "right", "bottom", "left")
    ] == pytest.approx([30, 40, 50, 20])
    assert r["centering_percent"]["left"] == pytest.approx(100 / 3)
    assert r["centering_percent"]["top"] == pytest.approx(37.5)
    validate_group(s, "physical")
    assert measure(s)["status"] == "provisional"
    validate_group(s, "printed")
    assert measure(s)["status"] == "human_geometry_validated"
    p = s.save(tmp_path / "versions")
    assert measure(Session.reopen(p))["status"] == "human_geometry_validated"
    report = export_report(s, tmp_path / "reports")
    assert json.loads(report.read_text())["review_status"] == "review_required"
    s.set_notes("printed", 0, "uncertain edge")
    s.review("printed", 0, uncertain=True)
    assert measure(s)["status"] == "provisional"
    with pytest.raises(ValueError):
        validate_group(s, "printed")


def test_history_full_decision_roundtrip_and_sticky_exposure(tmp_path):
    s, _, source = make(tmp_path)
    s.load_report(source)
    h = History(s)
    before = deepcopy(s.data["physical"])
    s.seed("physical", 0, s.predictions("physical", 0)[0])
    h.record()
    s.review("physical", 0)
    h.record()
    reviewed = deepcopy(s.data["physical"])
    s.set_notes("physical", 0, "blur")
    h.record()
    s.review("physical", 0, True)
    h.record()
    h.move(-1)
    h.move(-1)
    assert s.data["physical"] == reviewed
    h.move(-1)
    h.move(-1)
    assert s.data["physical"] == before and s.data["prediction_exposure"]
    for _ in range(4):
        h.move(1)
    assert s.data["physical"][0]["status"] == "ambiguous"
    h.move(-1)
    s.edit("physical", 0, [[120, 120], [400, 120]])
    h.record()
    snapshot = deepcopy(s.data)
    h.move(1)
    assert s.data == snapshot


def test_recovery_without_operator_saved_ancestor_and_partial_snapshot(tmp_path):
    s, _, source = make(tmp_path)
    s.load_report(source)
    geometry(s)
    saved = s.save(tmp_path / "versions")
    saved_hash = sha256_file(saved)
    s.data["operator"] = ""
    s.edit("printed", 0, [[120.123, 125.456], [400.789, 125.456]])
    draft = autosave(s, tmp_path / "drafts")
    damaged = tmp_path / "drafts/partial.json"
    damaged.write_text('{"kind":')
    with pytest.raises((ValueError, OSError)):
        recover(damaged)
    restored = recover(draft)
    assert restored.data == s.data
    restored.data["operator"] = "Recovered reviewer"
    new = restored.save(tmp_path / "versions")
    assert new != saved and sha256_file(saved) == saved_hash
    assert restored.data["parent"]["sha256"] == saved_hash


@pytest.mark.parametrize("change", ["image", "source", "identity", "status"])
def test_recovery_rejects_provenance_mismatches(tmp_path, change):
    s, image, source = make(tmp_path)
    s.load_report(source)
    draft = autosave(s, tmp_path / "drafts")
    value = json.loads(draft.read_text())
    if change == "image":
        image.write_bytes(image.read_bytes() + b"changed")
    if change == "source":
        source.write_bytes(source.read_bytes() + b" ")
    if change == "identity":
        value["session"]["image"]["dimensions"][0] += 1
    if change == "status":
        value["session"]["sources"][0]["status"] = "accepted"
    draft.write_text(json.dumps(value))
    with pytest.raises((ValueError, OSError)):
        recover(draft)


def test_missing_inconsistent_and_operator_change(tmp_path):
    s, _, _ = make(tmp_path)
    assert measure(s)["status"] == "unavailable"
    geometry(s)
    for f in ("physical", "printed"):
        validate_group(s, f)
    s.data["operator"] = "Another operator"
    assert measure(s)["status"] == "provisional"
    s.edit("printed", 0, [[110, 70], [420, 70]])
    assert measure(s)["status"] == "unavailable"


def test_old_v01_reopens_without_validation_promotion(tmp_path):
    s, _, _ = make(tmp_path)
    geometry(s)
    s.data["tool_version"] = "0.1.0"
    path = s.save(tmp_path / "versions")
    assert measure(Session.reopen(path))["status"] == "provisional"
