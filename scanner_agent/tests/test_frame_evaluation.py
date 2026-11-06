# ruff: noqa: E402
"""Synthetic evidence tests, not real-card accuracy or physical repeatability."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
from PIL import Image
from test_centering import fixture

from spectra_centering.analysis import analyze as baseline_analyze
from spectra_centering.config import validate
from spectra_centering.detector import detect
from spectra_centering.inputs import read_inputs
from spectra_frame_evaluation.analysis import analyze, configuration
from spectra_frame_evaluation.evaluation import evaluate_candidates, hypotheses
from spectra_scanner.common import AgentError
from spectra_scanner.storage import sha256_file


def test_parallel_hypotheses_deterministic_and_immutable(tmp_path: Path) -> None:
    image, upstream = fixture(tmp_path, competing=True)
    hashes = [sha256_file(p) for p in (image, upstream)]
    results = [analyze(image, upstream, tmp_path / f"out-{i}", configuration({})) for i in range(2)]
    for result in results:
        assert result["status"] == "review_required"
        assert result["frame_evaluation"]["valid_count"] > 1
        assert result["frame_evaluation"]["selected_geometric_hypothesis_id"] is None
        assert result["measurements"] is None
        assert result["automatic_acceptance"] is False
        assert "upstream_review_required" in result["quality_flags"]
    assert results[0]["sides"] == results[1]["sides"]
    assert results[0]["frame_evaluation"] == results[1]["frame_evaluation"]
    assert [sha256_file(p) for p in (image, upstream)] == hashes
    for name in results[0]["artifacts"]:
        assert sha256_file(tmp_path / "out-0" / name) == sha256_file(tmp_path / "out-1" / name)
    with pytest.raises(FileExistsError):
        analyze(image, upstream, tmp_path / "out-0", configuration({}))


@pytest.mark.parametrize("angle", [0, 7, -8])
def test_asymmetric_borders(tmp_path: Path, angle: float) -> None:
    image, upstream = fixture(tmp_path, left=12, right=28, angle=angle)
    result = analyze(image, upstream, tmp_path / "out", configuration({}))
    frames = [f for f in result["frame_evaluation"]["hypotheses"] if f["geometrically_valid"]]
    assert len(frames) == 1
    margins = frames[0]["conditional_margins_pixels"]
    assert margins["left"]["mean_pixels"] == pytest.approx(12, abs=2)
    assert margins["right"]["mean_pixels"] == pytest.approx(28, abs=2)
    assert result["measurements"] is None


def test_heterogeneous_bands_provisionally_retained(tmp_path: Path) -> None:
    image, upstream = fixture(tmp_path, artwork=True)
    result = analyze(image, upstream, tmp_path / "out", configuration({}))
    provisional = [
        c for s in result["sides"] for c in s["candidates"] if c["retention"] == "provisional"
    ]
    assert provisional
    assert all(c["rejection_reasons"] == ["heterogeneous_outer_band"] for c in provisional)
    assert all(c["transition_evidence"]["p10_rgb_rms"] >= 12 for c in provisional)
    assert all(
        len(c["transition_evidence"]["exterior_band_evidence"]["rgb_std"]) == 3 for c in provisional
    )
    assert all(
        c["geometry_evidence"]["support_fraction"] == c["support_fraction"] for c in provisional
    )
    # Interior artwork can also form coherent rectangles. Never assert semantic truth.
    assert result["automatic_acceptance"] is False
    assert result["measurements"] is None
    assert "semantic_frame_identity_unverified" in result["quality_flags"]


def test_incomplete_frame_stays_not_applicable(tmp_path: Path) -> None:
    image, upstream = fixture(tmp_path)
    rgb = np.asarray(Image.open(image)).copy()
    rgb[90:180, 90:462] = 220
    Image.fromarray(rgb).save(image)
    value = json.loads(upstream.read_text())
    value["source"]["sha256"] = sha256_file(image)
    upstream.write_text(json.dumps(value))
    result = analyze(image, upstream, tmp_path / "out", configuration({}))
    assert result["status"] == "not_applicable"
    assert result["frame_evaluation"]["valid_count"] == 0
    assert result["measurements"] is None


def test_baseline_preserved_and_essential_failures_rejected(tmp_path: Path) -> None:
    image, upstream = fixture(tmp_path)
    rgb, evidence = read_inputs(image, upstream)
    corners = np.asarray(evidence["physical_corners_pixels"])
    config = configuration({})
    generated = detect(rgb, corners, config["candidate_generation"])
    before = deepcopy(generated)
    modified = deepcopy(generated)
    modified[0]["candidates"][0]["rejection_reasons"] += [
        "line_residuals",
        "heterogeneous_outer_band",
    ]
    evaluated = evaluate_candidates(
        rgb, corners, modified, config["candidate_generation"], config["evaluation"]
    )
    assert evaluated[0]["candidates"][0]["retention"] == "rejected"
    assert "line_residuals" in evaluated[0]["candidates"][0]["rejection_reasons"]
    analyze(image, upstream, tmp_path / "b", config)
    assert generated == before == detect(rgb, corners, config["candidate_generation"])
    baseline = baseline_analyze(image, upstream, tmp_path / "a", validate({}))
    assert baseline["frame_evidence_status"] == "supported"
    assert baseline["sides"] == before


def test_hypothesis_limit_prevents_unique_selection(tmp_path: Path) -> None:
    image, upstream = fixture(tmp_path, competing=True)
    result = analyze(
        image, upstream, tmp_path / "out", configuration({"evaluation": {"maximum_hypotheses": 1}})
    )
    evaluation = result["frame_evaluation"]
    assert evaluation["search_truncated"] is True
    assert evaluation["evaluated_count"] == 1
    assert evaluation["selected_geometric_hypothesis_id"] is None
    assert result["status"] == "review_required"


def test_candidate_generator_limit_propagates(tmp_path: Path) -> None:
    image, upstream = fixture(tmp_path, competing=True)
    result = analyze(
        image,
        upstream,
        tmp_path / "out",
        configuration({"candidate_generation": {"maximum_candidates_per_side": 1}}),
    )
    assert any(side["candidate_limit_reached"] for side in result["sides"])
    assert result["frame_evaluation"]["search_truncated"]
    assert result["frame_evaluation"]["selected_geometric_hypothesis_id"] is None
    assert result["measurements"] is None


def test_invalid_intersections_and_outside_frame(tmp_path: Path) -> None:
    image, upstream = fixture(tmp_path)
    rgb, evidence = read_inputs(image, upstream)
    corners = np.asarray(evidence["physical_corners_pixels"])
    config = configuration({})
    sides = evaluate_candidates(
        rgb,
        corners,
        detect(rgb, corners, config["candidate_generation"]),
        config["candidate_generation"],
        config["evaluation"],
    )
    sides[0]["candidates"][0]["line_abc"] = [0, 1, -20]  # outside physical top at y=90
    result = hypotheses(corners, sides, config["candidate_generation"], config["evaluation"])
    assert result["valid_count"] == 0
    assert result["hypotheses"][0]["rejection_reasons"]


@pytest.mark.parametrize(
    "value",
    [
        {"unknown": 1},
        {"evaluation": {"maximum_hypotheses": 5000}},
        {"evaluation": {"minimum_transition_p10_rgb": float("nan")}},
        {"evaluation": {"maximum_hypotheses": True}},
    ],
)
def test_configuration_guards(value: dict) -> None:
    with pytest.raises(AgentError):
        configuration(value)


def test_missing_and_cross_card_inputs_fail_closed(tmp_path: Path) -> None:
    image, upstream = fixture(tmp_path)
    value = json.loads(upstream.read_text())
    value["source"]["sha256"] = "0" * 64
    upstream.write_text(json.dumps(value))
    result = analyze(image, upstream, tmp_path / "cross", configuration({}))
    assert result["status"] == "analysis_failed"
    assert result["error"]["code"] == "cross_card_or_changed_input"
    result = analyze(tmp_path / "missing.bmp", upstream, tmp_path / "missing", configuration({}))
    assert result["status"] == "analysis_failed"
