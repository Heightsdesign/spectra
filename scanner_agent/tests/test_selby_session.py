# ruff: noqa: E402
"""Session persistence and source integrity; no hardware or grading decisions."""

from copy import deepcopy

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
from test_centering import fixture

from selby_workstation.session import Session, endpoint_line
from spectra_frame_evaluation.analysis import analyze, configuration
from spectra_scanner.common import AgentError, write_json_new
from spectra_scanner.storage import sha256_file


def make(tmp_path):
    image, physical = fixture(tmp_path)
    session = Session(image)
    session.data["operator"] = "Test reviewer"
    return session, image, physical


def test_fractional_geometry_version_chain_and_reopen(tmp_path):
    s, image, physical = make(tmp_path)
    hashes = [sha256_file(p) for p in (image, physical)]
    s.load_report(physical)
    points = [[92.123456789, 96.234567891], [450.987654321, 98.456789123]]
    s.edit("physical", 0, points)
    s.review("physical", 0)
    s.data["view"] = dict(zoom=3.125, center=[210.125, 330.75])
    first = s.save(tmp_path / "versions")
    first_hash = sha256_file(first)
    opened = Session.reopen(first)
    assert opened.data["physical"][0] == s.data["physical"][0]
    assert opened.data["view"] == s.data["view"]
    corrected = deepcopy(points)
    corrected[1][1] += 0.1
    opened.edit("physical", 0, corrected)
    assert opened.data["physical"][0]["status"] == "unannotated"
    second = opened.save(tmp_path / "versions")
    assert first != second and sha256_file(first) == first_hash
    assert opened.data["parent"] == dict(path=str(first.resolve()), sha256=first_hash)
    assert Session.reopen(second).data["physical"][0]["endpoints"] == corrected
    assert hashes == [sha256_file(p) for p in (image, physical)]


def test_manual_edit_resets_confirmation_and_retains_seed_basis(tmp_path):
    s, _, physical = make(tmp_path)
    s.load_report(physical)
    s.seed("physical", 0, s.predictions("physical", 0)[0])
    s.review("physical", 0)
    side = s.data["physical"][0]
    basis = deepcopy(side["basis"])
    points = np.array(side["endpoints"]) + [0, 0.1]
    s.edit("physical", 0, points)
    side = s.data["physical"][0]
    assert (
        side["basis"] == basis and side["definition"] == "manual" and side["candidate_id"] is None
    )
    assert side["reviewed"] is None and side["confirmed_at_utc"] is None
    assert side["status"] == "unannotated"
    s.save(tmp_path / "versions")


def test_note_change_invalidates_review_and_uncertainty_is_explicit(tmp_path):
    s, _, _ = make(tmp_path)
    s.edit("printed", 0, [[110, 120], [430, 120]])
    s.review("printed", 0)
    s.set_notes("printed", 0, "Two competing printed transitions")
    assert s.data["printed"][0]["status"] == "unannotated"
    s.review("printed", 0, True)
    saved = s.save(tmp_path / "versions")
    assert Session.reopen(saved).data["printed"][0]["status"] == "ambiguous"
    assert s.data["review_status"] == "review_required" and not s.data["automatic_acceptance"]


def test_uncertain_without_geometry_allowed_with_explanation(tmp_path):
    s, _, _ = make(tmp_path)
    with pytest.raises(ValueError, match="note"):
        s.review("physical", 2, True)
    s.set_notes("physical", 2, "Boundary not resolvable")
    s.review("physical", 2, True)
    assert Session.reopen(s.save(tmp_path / "versions")).data["physical"][2]["line_abc"] is None


@pytest.mark.parametrize("changed", ["image", "report", "prior_session"])
def test_changed_evidence_refused(tmp_path, changed):
    s, image, physical = make(tmp_path)
    s.load_report(physical)
    first = s.save(tmp_path / "versions")
    path = {"image": image, "report": physical, "prior_session": first}[changed]
    with path.open("ab") as stream:
        stream.write(b" ")
    if changed == "prior_session":
        with pytest.raises(ValueError, match="Previous session"):
            s.save(tmp_path / "versions")
    else:
        with pytest.raises(ValueError):
            Session.reopen(first)
        with pytest.raises(ValueError):
            s.save(tmp_path / "versions")


def test_stale_review_snapshot_rejected(tmp_path):
    s, _, _ = make(tmp_path)
    s.edit("physical", 0, [[100, 100], [440, 100]])
    s.review("physical", 0)
    s.data["physical"][0]["notes"] = "Edited behind reviewed snapshot"
    with pytest.raises(ValueError, match="changed after review"):
        s.save(tmp_path / "versions")


def test_upstream_states_and_printed_hypotheses_preserved(tmp_path):
    s, image, physical = make(tmp_path)
    report = tmp_path / "printed"
    baseline = analyze(image, physical, report, configuration({}))
    s.load_report(report / "report.json")
    assert len(s.data["sources"]) == 2
    assert all(source["status"] == "review_required" for source in s.data["sources"])
    assert baseline["frame_evaluation"]["valid_count"] == 1 and len(s.hypotheses()) == 1
    for i, p in enumerate(s.hypotheses()[0]["candidates"]):
        s.seed("printed", i, p)
    snapshot = deepcopy(s.data["sources"])
    path = s.save(tmp_path / "versions")
    opened = Session.reopen(path)
    assert opened.data["sources"] == snapshot
    assert opened.data["printed"] == s.data["printed"]
    assert not opened.data["automatic_acceptance"]


def test_cross_image_report_and_import_are_transactional(tmp_path):
    s, _, physical = make(tmp_path)
    import json

    value = json.loads(physical.read_text())
    value["source"]["sha256"] = "0" * 64
    other = tmp_path / "wrong.json"
    write_json_new(other, value)
    with pytest.raises(ValueError):
        s.load_report(other)
    assert s.data["sources"] == [] and s.reports == []


def test_provenance_and_candidate_claim_tampering_refused(tmp_path):
    s, _, physical = make(tmp_path)
    s.load_report(physical)
    s.seed("physical", 0, s.predictions("physical", 0)[0])
    s.data["physical"][0]["basis"]["report_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="provenance"):
        s.save(tmp_path / "versions")
    s.data["sources"][0]["status"] = "success"
    with pytest.raises(ValueError, match="status"):
        s.save(tmp_path / "versions")


@pytest.mark.parametrize(
    "points,index",
    [
        ([[0, 0], [0, 0]], 0),
        ([[0, 0], [1, 100]], 0),
        ([[-1, 10], [20, 10]], 0),
        ([[10, float("nan")], [20, 10]], 0),
    ],
)
def test_invalid_endpoint_geometry(points, index):
    with pytest.raises((AgentError, ValueError)):
        endpoint_line(points, index, [500, 700])


def test_operator_and_acceptance_guards(tmp_path):
    s, image, _ = make(tmp_path)
    s.data["operator"] = ""
    with pytest.raises(ValueError, match="Operator"):
        s.save(tmp_path / "versions")
    s.data["operator"] = "Reviewer"
    s.data["automatic_acceptance"] = True
    with pytest.raises(ValueError, match="acceptance"):
        s.save(tmp_path / "versions")
    assert image.is_file() and not (tmp_path / "versions").exists()


def test_original_encoding_guard_rejects_implicit_conversion(tmp_path):
    from PIL import Image

    image = tmp_path / "rgba.png"
    Image.new("RGBA", (100, 100), (10, 20, 30, 255)).save(image)
    original = sha256_file(image)
    with pytest.raises(ValueError, match="RGB24"):
        Session(image)
    assert sha256_file(image) == original
