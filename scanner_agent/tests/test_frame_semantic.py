# ruff: noqa: E402
"""Diagnostic invariants and adversarial ambiguity; no claims about real accuracy."""

from copy import deepcopy

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from spectra_frame_evaluation.semantic import analyze, describe, fronts, sample
from spectra_frame_evaluation.semantic_validation import associate, register


def fixture():
    rgb = np.full((240, 200, 3), 180, np.uint8)
    physical = [[10, 10], [190, 10], [190, 230], [10, 230]]
    sides = [dict(index=i, candidates=[]) for i in range(4)]
    frames = []
    for k, inset in enumerate([20, 40]):
        corners = [
            [inset, inset],
            [200 - inset, inset],
            [200 - inset, 240 - inset],
            [inset, 240 - inset],
        ]
        ids = []
        for i in range(4):
            a, b = np.array(corners[i]), np.array(corners[(i + 1) % 4])
            d = b - a
            n = np.array([-d[1], d[0]], dtype=float)
            n /= np.linalg.norm(n)
            cid = f"candidate-{k}-{i}"
            ids.append(cid)
            sides[i]["candidates"].append(dict(id=cid, line_abc=[*n, -n @ a]))
        frames.append(
            dict(
                id=f"frame-{k}", candidate_ids=ids, corners_pixels=corners, geometrically_valid=True
            )
        )
    ev = dict(
        physical_corners_pixels=physical,
        sides=sides,
        status="review_required",
        configuration={"candidate_generation": {"corner_exclusion_fraction": 0.18}},
        frame_evaluation=dict(
            hypotheses=frames, search_truncated=False, selected_geometric_hypothesis_id=None
        ),
    )
    return rgb, ev


def test_pareto_conflicts_ties_and_dominance():
    def v(*a):
        return dict(
            zip(
                [
                    "continuity",
                    "collar_consistency",
                    "global_band_consistency",
                    "region_difference",
                ],
                a,
                strict=True,
            )
        )

    assert fronts([v(1, 1, 1, 1), v(0.5, 0.5, 0.5, 0.5), None]) == [1, 2, None]
    assert fronts([v(1, 0, 1, 0), v(0, 1, 0, 1)]) == [1, 1]
    assert fronts([v(1, 1, 1, 1), v(1, 1, 1, 1)]) == [1, 1]


def test_uniform_nested_artwork_abstains_and_has_no_outermost_preference():
    rgb, ev = fixture()
    result = analyze(rgb, ev)
    assert result["diagnostic_preference"] is None
    assert all(len(v) == 2 for v in result["leaders_by_view"].values())
    assert result["status"] == "review_required" and not result["automatic_acceptance"]


def test_order_id_and_reference_metadata_cannot_change_descriptors():
    rgb, ev = fixture()
    original = deepcopy(ev)
    a = analyze(rgb, ev)
    ev["manual_reference"] = {"preferred": "frame-1", "reference_error": 0}
    ev["frame_evaluation"]["hypotheses"].reverse()
    b = analyze(rgb, ev)
    assert {r["hypothesis_id"]: r["views"] for r in a["hypotheses"]} == {
        r["hypothesis_id"]: r["views"] for r in b["hypotheses"]
    }
    del ev["manual_reference"]
    ev["frame_evaluation"]["hypotheses"].reverse()
    assert ev == original


def test_original_report_and_pixels_immutable_deterministic():
    rgb, ev = fixture()
    before, pixels = deepcopy(ev), rgb.copy()
    assert analyze(rgb, ev) == analyze(rgb, ev)
    assert ev == before and np.array_equal(rgb, pixels)


def test_bilinear_domain_and_fractional_values():
    rgb = np.zeros((2, 2, 3), np.uint8)
    rgb[1, 1] = 100
    values, valid = sample(rgb, np.array([[0.5, 0.5], [-0.1, 0.5]]))
    assert values[0].tolist() == [25, 25, 25]
    assert valid.tolist() == [True, False]


def test_transition_direction_continuity_not_strength_or_index():
    out = np.full((96, 3, 3), 100.0)
    inside = out.copy() + 30
    raw = dict(
        outside=out,
        inside=inside,
        corridor=out,
        outside_valid=np.ones((96, 3), bool),
        inside_valid=np.ones((96, 3), bool),
        corridor_valid=np.ones((96, 3), bool),
    )
    continuous = describe(raw, slice(None))
    raw["inside"][::3] = 70
    interrupted = describe(raw, slice(None))
    assert continuous["continuity"] == pytest.approx(1)
    assert interrupted["continuity"] == pytest.approx(2 / 3)


@pytest.mark.parametrize("change", ["truncated", "invalid", "missing_line", "no_hypotheses"])
def test_failure_and_incomplete_search_never_preferred(change):
    rgb, ev = fixture()
    if change == "truncated":
        ev["frame_evaluation"]["search_truncated"] = True
    elif change == "invalid":
        for h in ev["frame_evaluation"]["hypotheses"]:
            h["geometrically_valid"] = False
    elif change == "missing_line":
        ev["sides"][0]["candidates"][0]["line_abc"] = None
    else:
        ev["frame_evaluation"]["hypotheses"] = []
    assert analyze(rgb, ev)["abstained"]


def test_inadequate_registration_explicitly_unavailable():
    rgb, ev = fixture()
    corners = np.array(ev["physical_corners_pixels"])
    result = register(rgb, rgb, corners, corners)
    assert not result["reliable"]
    assert associate(ev, ev, result) == []


def test_ambiguous_cross_capture_association_not_forced():
    _, ev = fixture()
    reg = dict(reliable=True, matrix=np.eye(3).tolist(), holdout_p95_px=1)
    target = deepcopy(ev)
    target["frame_evaluation"]["hypotheses"][1]["corners_pixels"] = target["frame_evaluation"][
        "hypotheses"
    ][0]["corners_pixels"]
    rows = associate(ev, target, reg)
    assert not rows[0]["reliable_match"]


def test_matched_geometry_and_large_mismatch():
    _, ev = fixture()
    reg = dict(reliable=True, matrix=np.eye(3).tolist(), holdout_p95_px=0.5)
    assert all(r["reliable_match"] for r in associate(ev, ev, reg))
    reg["matrix"][0][2] = 100
    assert not any(r["reliable_match"] for r in associate(ev, ev, reg))
