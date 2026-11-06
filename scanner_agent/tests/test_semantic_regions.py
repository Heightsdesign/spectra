# ruff: noqa: E402
"""Region assignment mechanics and semantic false-positive/ambiguity controls."""

from copy import deepcopy

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from spectra_frame_evaluation.semantic_regions import analyze, appearance, fields, leader


def fixture(region="interior"):
    rgb = np.full((300, 220, 3), 180, np.uint8)
    rgb[40:270, 30:190] = [90, 55, 40]
    if region == "exterior":
        rgb[40:70, 30:190] = 180
    if region == "neutral":
        rgb[:] = 180
    sides = [dict(candidates=[]) for _ in range(4)]
    frames = []
    for k, y in enumerate((40, 70)):
        lines = [[0, 1, -y], [-1, 0, 190], [0, -1, 270], [1, 0, -30]]
        ids = []
        for i, line in enumerate(lines):
            cid = f"line-{k}-{i}"
            ids.append(cid)
            sides[i]["candidates"].append(dict(id=cid, line_abc=line))
        frames.append(dict(id=f"hypothesis-{k}", candidate_ids=ids, geometrically_valid=True))
    evaluation = dict(
        physical_corners_pixels=[[10, 10], [210, 10], [210, 290], [10, 290]],
        sides=sides,
        status="review_required",
        frame_evaluation=dict(hypotheses=frames, search_truncated=False),
    )
    v1 = {"leaders_by_view": {"0.0:full": [f["id"] for f in frames]}}
    return rgb, evaluation, v1


@pytest.mark.parametrize(
    "region,preferred",
    [("interior", "hypothesis-0"), ("exterior", "hypothesis-1"), ("neutral", None)],
)
def test_pixel_evidence_can_favor_either_boundary_or_abstain(region, preferred):
    rgb, ev, v1 = fixture(region)
    result = analyze(rgb, ev, v1)
    assert result["comparisons"][0]["preferred"] == preferred
    assert result["conditional_leader_v1_subset"] == preferred
    assert result["semantic_selection"] is None and result["abstained"]
    assert not result["automatic_acceptance"] and result["status"] == "review_required"


def test_side_geometry_not_candidate_ids_determines_changed_side():
    rgb, ev, v1 = fixture()
    # Same shared equations, distinct per-hypothesis candidate identifiers.
    result = analyze(rgb, ev, v1)
    assert result["comparisons"][0]["different_sides"] == [0]
    ev["frame_evaluation"]["hypotheses"].reverse()
    reverse = analyze(rgb, ev, v1)
    assert reverse["conditional_leader_v1_subset"] == result["conditional_leader_v1_subset"]


def test_candidate_renaming_and_reference_metadata_have_no_effect():
    rgb, ev, v1 = fixture()
    expected = analyze(rgb, ev, v1)
    for side in ev["sides"]:
        for c in side["candidates"]:
            c["id"] = "arbitrary-" + c["id"]
    for h in ev["frame_evaluation"]["hypotheses"]:
        h["candidate_ids"] = ["arbitrary-" + cid for cid in h["candidate_ids"]]
    ev["manual_reference"] = {"winner": "hypothesis-1"}
    assert analyze(rgb, ev, v1) == expected


def test_immutable_original_and_reports_deterministic():
    rgb, ev, v1 = fixture()
    before, pixels = deepcopy(ev), rgb.copy()
    assert analyze(rgb, ev, v1) == analyze(rgb, ev, v1)
    assert ev == before and np.array_equal(rgb, pixels)


def test_two_changed_sides_are_confounded():
    rgb, ev, v1 = fixture()
    cid = ev["frame_evaluation"]["hypotheses"][1]["candidate_ids"][2]
    next(c for c in ev["sides"][2]["candidates"] if c["id"] == cid)["line_abc"] = [0, -1, 260]
    result = analyze(rgb, ev, v1)
    assert not result["comparisons"][0]["available"]
    assert result["conditional_leader_all_hypotheses"] is None


def test_truncated_search_and_incomplete_pair_graph_withhold_leader():
    rgb, ev, v1 = fixture()
    ev["frame_evaluation"]["search_truncated"] = True
    assert analyze(rgb, ev, v1)["conditional_leader_all_hypotheses"] is None
    assert leader(["a", "b", "c"], [dict(hypotheses=["a", "b"], preferred="a")], False) is None
    assert leader(["a", "b"], [dict(hypotheses=["a", "b"], preferred="a")], True) is None


def test_empty_hypotheses_and_narrow_strip_are_unavailable():
    rgb, ev, v1 = fixture()
    ev["sides"][0]["candidates"][1]["line_abc"] = [0, 1, -40.5]
    assert not analyze(rgb, ev, v1)["comparisons"][0]["available"]
    ev["frame_evaluation"]["hypotheses"] = []
    result = analyze(rgb, ev, v1)
    assert result["hypotheses"] == [] and result["abstained"]


def test_native_texture_edge_orientation_on_known_vertical_stripes():
    rgb = np.zeros((80, 80, 3), np.uint8)
    rgb[:, ::8] = 255
    xy = np.stack(np.meshgrid(np.arange(4, 76), np.arange(4, 76)), axis=-1).reshape(-1, 2)
    result = appearance(rgb, fields(rgb), xy, np.array([1.0, 0.0]))
    assert result["edge_density"]["16"] > 0
    assert result["highpass_rms"] > 0
    # Edge tangents vertical relative to horizontal physical-side tangent.
    assert np.argmax(result["relative_edge_tangent_histogram_18"]) == 9


def test_conflicting_shared_context_and_cycles_abstain():
    rgb, ev, v1 = fixture()
    # Right interior collar now matches its exterior; the other two still differ.
    rgb[50:250, 181:190] = 180
    assert analyze(rgb, ev, v1)["comparisons"][0]["preferred"] is None
    cyclic = [
        dict(hypotheses=["a", "b"], preferred="a"),
        dict(hypotheses=["b", "c"], preferred="b"),
        dict(hypotheses=["c", "a"], preferred="c"),
    ]
    assert leader(["a", "b", "c"], cyclic, False) is None
