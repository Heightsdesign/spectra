# ruff: noqa: E402
import copy
import json
from functools import partial
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
from PIL import Image
from test_boundary import synthetic
from test_boundary_layers import printed_image, shadow_image

from spectra_boundary.config import DEFAULTS, configuration
from spectra_boundary.controlled_detector import detect
from spectra_boundary.controlled_layers import classify, quality, reassign, select_layers
from spectra_boundary.detector import detect as frozen_detect
from spectra_boundary.detector import line_fit


def candidate(name, failures=()):
    return {
        "id": name,
        "physical_criterion_passed": not failures,
        "criterion_failures": list(failures),
        "support_score": 1,
        "raw_evidence": {"exterior_deficit_fraction": 0},
    }


@pytest.mark.parametrize(
    "failures",
    [
        ("inward_darkening_polarity",),
        ("strong_continuous_transition",),
        ("raw_local_contrast",),
        ("exterior_background_path",),
        ("side_coverage",),
        ("side_residual",),
    ],
)
def test_density_competitor_exclusion_records_actual_failure(failures):
    result = {
        "candidate_layers": [candidate("a"), candidate("b", failures)],
        "density_ambiguity_detected": True,
    }
    classify(result, DEFAULTS["physical_boundary"])
    assert result["physical_selection_resolved"]
    assert result["density_ambiguity_detected"]
    assert result["candidate_layers"][1]["ambiguity_decision"]["criterion_failures"] == list(
        failures
    )


def test_multiple_admissible_tracks_remain_unresolved_regardless_of_rank():
    result = {"candidate_layers": [candidate("a"), candidate("b")]}
    result["candidate_layers"][1]["support_score"] = 1000
    classify(result, DEFAULTS["physical_boundary"])
    assert result["selected_layer_id"] == "b"
    assert result["ambiguity_reasons"] == ["multiple_candidates_satisfy_physical_criterion"]


def test_zero_admissible_and_shadow_caution_remain_blocked():
    result = {"candidate_layers": [candidate("a", ["side_coverage"])]}
    classify(result, DEFAULTS["physical_boundary"])
    assert not result["physical_selection_resolved"]
    result["candidate_layers"] = [candidate("a")]
    result["candidate_layers"][0]["raw_evidence"]["exterior_deficit_fraction"] = 0.151
    classify(result, DEFAULTS["physical_boundary"])
    assert result["ambiguity_reasons"] == ["non_plateau_exterior_approach_blur_or_shadow"]


@pytest.mark.parametrize(
    "image", [synthetic(), printed_image(), shadow_image(170), shadow_image(210)]
)
def test_phase1_preserves_geometry_evidence_and_frozen_implementation(image):
    config = configuration({})
    original = copy.deepcopy(config)
    a = frozen_detect(image, [150, 150], config)[0]
    b = detect(image, [150, 150], config)[0]
    assert config == original
    for before, after in zip(a["sides"], b["sides"], strict=True):
        assert all(before[key] == value for key, value in after["frozen_selection"].items())
        assert before["line_abc"] == after["line_abc"]
        assert all(
            x == y["original_candidate"]
            for x, y in zip(before["candidate_layers"], after["candidate_layers"], strict=True)
        )
        assert set(before["ambiguity_reasons"]) - {"legacy_density_competition_retained"} <= set(
            after["ambiguity_reasons"]
        )


def local_report(card):
    root = Path(__file__).resolve().parents[1]
    relative = (
        "s2_1/20261018T064802_eb96edb7068246a08de3c26b30106c7a/scan-000/report.json"
        if card == "D"
        else "s2_1/20261018T065520_6315ee20d1cc4f08957eed0129710672/scan-000/report.json"
    )
    path = root / "local_data" / relative
    if not path.exists():
        pytest.skip("Local historical card evidence unavailable")
    return json.loads(path.read_text())


def test_card_e_bottom_phase1_without_geometry_change():
    original = local_report("E")["baseline"]["sides"][2]
    result = copy.deepcopy(original)
    classify(result, DEFAULTS["physical_boundary"])
    assert original["ambiguity_reasons"] == ["legacy_density_competition_retained"]
    assert result["ambiguity_reasons"] == []
    assert result["selected_layer_id"] == "L1"
    assert result["candidate_layers"][2]["ambiguity_decision"]["retained"] is False


@pytest.mark.parametrize("card", ["D", "E"])
def test_historical_cards_do_not_pass_or_change_defaults(card):
    report = local_report(card)
    before = copy.deepcopy(DEFAULTS)
    with Image.open(report["source"]["path"]) as image:
        rgb = np.asarray(image).copy()
    result = detect(
        rgb,
        report["dpi"],
        configuration({}),
        layer_selector=partial(select_layers, support_reassignment=True),
    )[0]
    assert result["status"] == "review_required"
    assert DEFAULTS == before
    bottom = result["sides"][2]
    if card == "D":
        chosen = next(x for x in bottom["candidate_layers"] if x["selected"])
        assert chosen["original_candidate"]["coverage"] == 0.625
        assert chosen["support_reassignment"]["status"] == "rejected"
        assert chosen["support_reassignment"]["reason"] == "anchor_or_residual_guard"
        assert bottom["line_abc"] == report["baseline"]["sides"][2]["line_abc"]
        assert bottom["coverage"] == 0.625
    else:
        assert bottom["coverage"] == 1
        assert not bottom["ambiguous_parallel_edge"]


def test_quality_matches_frozen_criteria_for_all_card_e_candidates():
    for side in local_report("E")["baseline"]["sides"]:
        for layer in side["candidate_layers"]:
            failures, score = quality(
                layer["raw_evidence"], layer["coverage"], layer["rms_pixels"], DEFAULTS
            )
            assert failures == layer["criterion_failures"]
            assert score == layer["support_score"]


@pytest.mark.parametrize("slope,phase", [(0.002, 0), (0.004, 0.3), (-0.004, 0.7)])
def test_bounded_tilted_track_support_and_neighbor_guard(slope, phase):
    # Actual darkening track and a parallel printed transition. Reassignment
    # must stay near its immutable original line.
    yy, xx = np.indices((140, 700))
    edge = 55 + slope * (xx - 350) + phase
    gray = np.where(yy < edge, 245, np.where(yy < edge + 7, 150, 60)).astype(np.uint8)
    x = np.arange(100, 601, dtype=float)
    y = 55 + slope * (x - 350) + phase
    points = np.concatenate([np.column_stack([x, y]), np.column_stack([x, y + 7])])
    anchor, _ = line_fit(points[: len(x)])
    layer = candidate("a", ["side_coverage"])
    layer.update(line_abc=anchor.tolist())
    neighbor = candidate("b")
    other, _ = line_fit(points[len(x) :])
    neighbor.update(
        line_abc=other.tolist(),
        raw_evidence={
            "available": True,
            "gradient_polarity_fraction": 1,
            "signed_inward_drop_gray": 90,
        },
    )
    support, _ = reassign(
        layer,
        [layer, neighbor],
        points,
        np.array([0.0, 55.0]),
        np.array([699.0, 55.0]),
        gray,
        configuration({}),
        line_fit,
        20,
    )
    assert support is not None
    assert layer["support_reassignment"]["status"] == "applied"
    assert np.max(np.abs(support @ anchor[:2] + anchor[2])) < 1e-4
    assert layer["support_reassignment"]["maximum_movement_pixels"] <= 0.5
    assert layer["coverage"] == 1
    assert layer["criterion_failures"] == []


def test_reassignment_refuses_photometric_failures():
    layer = candidate("a", ["side_coverage", "strong_continuous_transition"])
    support, _ = reassign(layer, [layer], None, None, None, None, DEFAULTS, None, 10)
    assert support is None
    assert layer["support_reassignment"]["reason"] == "requires_coverage_only_failure"


@pytest.mark.parametrize("case", ["weak", "brightening", "occluded", "neighbor_owned"])
def test_nearby_edges_cannot_manufacture_physical_support(case):
    yy, _ = np.indices((140, 700))
    gray = np.where(yy < 55, 245, 150).astype(np.uint8)
    x = np.arange(140, 560, dtype=float)
    points = np.column_stack([x, np.full_like(x, 55)])
    layer = candidate("a", ["side_coverage"])
    layer.update(line_abc=[0.0, 1.0, -55.0])
    layers = [layer]
    if case == "weak":
        gray = np.where(yy < 55, 245, 235).astype(np.uint8)
    if case == "brightening":
        gray = np.where(yy < 55, 150, 245).astype(np.uint8)
    if case == "occluded":
        gray[:, :400] = 245
    if case == "neighbor_owned":
        layer["line_abc"] = [0.0, 1.0, -54.0]
        neighbor = candidate("b")
        neighbor.update(
            line_abc=[0.0, 1.0, -55.0],
            raw_evidence={
                "available": True,
                "gradient_polarity_fraction": 1.0,
                "signed_inward_drop_gray": 95.0,
            },
        )
        layers.append(neighbor)
    original = copy.deepcopy(layer)
    support, _ = reassign(
        layer,
        layers,
        points,
        np.array([0.0, 55.0]),
        np.array([699.0, 55.0]),
        gray,
        configuration({}),
        line_fit,
        20,
    )
    assert support is None
    assert layer["support_reassignment"]["status"] == "rejected"
    assert layer["line_abc"] == original["line_abc"]
    assert layer["criterion_failures"] == original["criterion_failures"]


def test_original_candidates_preserved_and_phase2_deterministic():
    image = synthetic()
    config = configuration({})
    run = partial(
        detect,
        image,
        [150, 150],
        config,
        layer_selector=partial(select_layers, support_reassignment=True),
    )
    a, b = run()[0], run()[0]
    assert a == b
    frozen = frozen_detect(image, [150, 150], config)[0]
    for side, prior in zip(a["sides"], frozen["sides"], strict=True):
        assert [layer["original_candidate"] for layer in side["candidate_layers"]] == prior[
            "candidate_layers"
        ]


def test_experimental_version_is_refused_by_pipeline(tmp_path):
    from spectra_boundary.controlled_layers import VERSION
    from spectra_pipeline.contracts import physical_report
    from spectra_scanner.common import AgentError

    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "single_image",
                "algorithm_version": VERSION,
                "status": "success",
            }
        )
    )
    with pytest.raises(AgentError) as caught:
        physical_report(report, tmp_path / "never-read.bmp")
    assert caught.value.status == "incompatible_physical_report"
