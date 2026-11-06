# ruff: noqa: E402
import copy
import json

import pytest
from PIL import Image, ImageDraw

cv2 = pytest.importorskip("cv2", reason="Install requirements-analysis.txt for S2.1 tests")
np = pytest.importorskip("numpy")

from test_boundary import synthetic

from spectra_boundary.analysis import analyze
from spectra_boundary.config import configuration
from spectra_boundary.detector import detect
from spectra_boundary.displacement import compare_layers
from spectra_scanner.common import AgentError
from spectra_scanner.storage import sha256_file


def right_side(report):
    return max(
        report["sides"],
        key=lambda side: (side["seed_start_pixels"][0] + side["seed_end_pixels"][0]) / 2,
    )


def chosen(side):
    return next(layer for layer in side["candidate_layers"] if layer["selected"])


def printed_image():
    image = Image.fromarray(synthetic())
    draw = ImageDraw.Draw(image)
    # A white printed inset can resemble the backing at a single probe; the whole
    # exterior corridor must still cross the dark physical border before reaching it.
    draw.rounded_rectangle((119, 145, 481, 655), 18, fill=(245, 245, 245))
    draw.rounded_rectangle((128, 154, 472, 646), 16, fill=(40, 40, 40))
    return np.asarray(image).copy()


def test_printed_border_is_rejected_by_exterior_path_not_nominal_size():
    config = configuration({"side_search_fraction": 0.05})
    report, _, _, _ = detect(printed_image(), [150, 150], config)
    side = right_side(report)
    selected = chosen(side)
    x = -selected["line_abc"][2] / selected["line_abc"][0]
    assert x == pytest.approx(486, abs=1)
    inner = [
        layer
        for layer in side["candidate_layers"]
        if layer["raw_evidence"].get("signed_inward_drop_gray", 0) > 100
        and layer["raw_evidence"].get("exterior_path_deficit_fraction", 0) > 0.35
        and layer["raw_evidence"].get("exterior_deficit_fraction", 1) < 0.1
    ]
    assert inner
    assert all("exterior_background_path" in layer["criterion_failures"] for layer in inner)
    assert report["status"] == "review_required"
    assert side["density_ambiguity_detected"] and side["ambiguous_parallel_edge"]


def test_wrong_gradient_polarity_is_preserved_and_rejected():
    report, _, _, _ = detect(
        printed_image(), [150, 150], configuration({"side_search_fraction": 0.05})
    )
    layers = right_side(report)["candidate_layers"]
    brightening = [
        layer for layer in layers if layer["raw_evidence"].get("signed_inward_drop_gray", 0) < -20
    ]
    assert brightening
    assert all("inward_darkening_polarity" in layer["criterion_failures"] for layer in brightening)
    assert all(not layer["selected"] for layer in brightening)


def shadow_image(value):
    image = Image.new("RGB", (600, 800), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((106, 132, 494, 668), 24, fill=(value, value, value))
    draw.rounded_rectangle((114, 140, 486, 660), 22, fill=(80, 80, 80))
    draw.rectangle((144, 170, 456, 630), fill=(210, 130, 40))
    return np.asarray(image).copy()


def test_exterior_shadow_does_not_force_outermost_edge_selection():
    report, _, _, _ = detect(shadow_image(210), [150, 150], configuration({}))
    side = right_side(report)
    selected = chosen(side)
    x = -selected["line_abc"][2] / selected["line_abc"][0]
    assert x == pytest.approx(486, abs=1)
    assert any(
        layer["density_peak_offset_inward_pixels"]
        < selected["density_peak_offset_inward_pixels"] - 4
        for layer in side["candidate_layers"]
    )
    assert report["status"] == "review_required"
    assert not side["physical_selection_resolved"]


def test_strong_shadow_remains_explicitly_ambiguous():
    report, _, _, _ = detect(shadow_image(170), [150, 150], configuration({}))
    assert report["status"] == "review_required"
    side = right_side(report)
    assert side["ambiguity_reasons"]
    assert not side["physical_selection_resolved"]
    assert sum(layer["selected"] for layer in side["candidate_layers"]) == 1
    assert all(
        layer["disposition"] == "provisional_selected"
        for layer in side["candidate_layers"]
        if layer["selected"]
    )


@pytest.mark.parametrize("normalization,contrast", [([1, 99], 1.05), ([5, 95], 0.9), (None, 1.1)])
def test_small_tonal_preprocessing_does_not_choose_internal_printed_edge(normalization, contrast):
    image = printed_image()
    base = configuration({"side_search_fraction": 0.05})
    enhanced = configuration(
        {
            "side_search_fraction": 0.05,
            "preprocessing": {"normalize_percentiles": normalization, "contrast": contrast},
        }
    )
    a, _, _, _ = detect(image, [150, 150], base)
    b, _, _, _ = detect(image, [150, 150], enhanced)
    comparison = compare_layers(a, b)
    right = comparison["right_side_comparison"]
    assert max(abs(v) for v in right["selected_normal_displacement_pixels_start_mid_end"]) < 1
    assert right["candidate_matches"]
    assert all(chosen(right_side(result))["physical_criterion_passed"] for result in (a, b))


@pytest.mark.parametrize("shift", [-3, 3])
def test_small_source_tonal_changes_keep_candidate_position(shift):
    source = printed_image()
    other = np.clip(source.astype(float) + shift, 0, 255).astype(np.uint8)
    config = configuration({"side_search_fraction": 0.05})
    a, _, _, _ = detect(source, [150, 150], config)
    b, _, _, _ = detect(other, [150, 150], config)
    comparison = compare_layers(a, b)["right_side_comparison"]
    assert max(abs(v) for v in comparison["selected_normal_displacement_pixels_start_mid_end"]) < 1


def test_zoom_artifacts_all_sides_corners_and_immutable_reports(tmp_path):
    image = tmp_path / "original.bmp"
    Image.fromarray(printed_image()).save(image, dpi=(150, 150))
    before = image.read_bytes()
    output = tmp_path / "new"
    result = analyze(
        image, output, configuration({"side_search_fraction": 0.05}), compare_preprocessing=True
    )
    assert image.read_bytes() == before
    assert result["source"]["sha256"] == sha256_file(image)
    for mode in ("baseline", "preprocessed"):
        zooms = result["artifacts"][mode]["zooms"]
        assert len(zooms["side_zooms"]) == len(zooms["corner_zooms"]) == 4
        for artifact in zooms["side_zooms"] + zooms["corner_zooms"]:
            assert (output / artifact["path"]).is_file()
            assert artifact["magnification"] == 4
    comparison = json.loads((output / "parallel-layer-comparison.json").read_text(encoding="utf-8"))
    assert comparison["right_side_comparison"]["baseline_candidates"]
    prior = (output / "report.json").read_bytes()
    with pytest.raises(FileExistsError):
        analyze(image, output, configuration({}))
    assert (output / "report.json").read_bytes() == prior


def test_candidate_correspondence_uses_geometry_not_local_ids():
    base, _, _, _ = detect(synthetic(), [150, 150], configuration({}))
    enhanced = copy.deepcopy(base)
    for side in enhanced["sides"]:
        for layer in side["candidate_layers"]:
            layer["id"] = "different-" + layer["id"]
        side["selected_layer_id"] = "different-" + side["selected_layer_id"]
    result = compare_layers(base, enhanced)
    assert all(
        max(abs(v) for v in s["selected_normal_displacement_pixels_start_mid_end"]) < 1e-6
        for s in result["side_comparisons"]
    )
    assert result["right_side_comparison"]["candidate_matches"][0][
        "preprocessed_layer_id"
    ].startswith("different-")


@pytest.mark.parametrize(
    "options",
    [
        {"profile_samples": 39},
        {"profile_samples": 80.5},
        {"minimum_raw_drop": float("nan")},
        {"unknown": 1},
        {"maximum_clear_exterior_deficit_fraction": 0.7},
        {"minimum_polarity_fraction": 2},
    ],
)
def test_physical_criterion_configuration_validated(options):
    with pytest.raises(AgentError):
        configuration({"physical_boundary": options})
