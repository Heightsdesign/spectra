# ruff: noqa: E402
# S1-only environments skip optional analysis tests before importing OpenCV consumers.
import copy
import json

import pytest
from PIL import Image, ImageDraw

cv2 = pytest.importorskip("cv2", reason="Install requirements-analysis.txt for S2.1 tests")
np = pytest.importorskip("numpy")

from spectra_boundary.analysis import analyze
from spectra_boundary.cli import main
from spectra_boundary.config import configuration
from spectra_boundary.detector import detect, geometries, ordered
from spectra_boundary.preprocessing import working_gray
from spectra_boundary.repeatability import repeatability, rigid_to_reference
from spectra_scanner.common import AgentError
from spectra_scanner.storage import sha256_file


def synthetic(
    angle=0,
    center=(300, 400),
    size=(372, 520),
    radius=22,
    margin_shape=(600, 800),
    card_value=80,
    uneven=False,
    shadow=False,
):
    width, height = margin_shape
    image = Image.new("RGB", (width, height), (245, 245, 245))
    if uneven:
        background = np.zeros((height, width, 3), np.uint8)
        background[:] = np.linspace(215, 252, width).astype(np.uint8)[None, :, None]
        image = Image.fromarray(background)
    target = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(target)
    x, y = center
    w, h = size
    box = (x - w / 2, y - h / 2, x + w / 2, y + h / 2)
    if shadow:
        draw.rounded_rectangle(
            (box[0] + 6, box[1] + 6, box[2] + 8, box[3] + 8), radius, fill=(170, 170, 170, 255)
        )
    draw.rounded_rectangle(box, radius, fill=(card_value, card_value, card_value, 255))
    draw.rectangle((box[0] + 30, box[1] + 30, box[2] - 30, box[3] - 30), fill=(210, 130, 40, 255))
    # Rendering fixtures is separate from analyzing originals; rotation is known ground truth.
    target = target.rotate(angle, resample=Image.Resampling.BICUBIC, center=center)
    image.paste(target, (0, 0), target)
    return np.asarray(image).copy()


@pytest.mark.parametrize("angle", [0, 6, -8, 180, 90])
def test_rounded_physical_sides_and_rotations(angle):
    shape = (800, 800) if angle == 90 else (600, 800)
    image = synthetic(
        angle=angle, center=(400, 400) if angle == 90 else (300, 400), margin_shape=shape
    )
    report, _, accepted, _ = detect(image, [150, 150], configuration({}))
    assert report["status"] == "success", report
    assert len(report["sides"]) == 4
    assert len(accepted) > 500
    assert report["geometry"]["width_pixels"] == pytest.approx(372, abs=3)
    assert report["geometry"]["height_pixels"] == pytest.approx(520, abs=3)
    assert all(s["rms_pixels"] < 1 for s in report["sides"])
    assert all(report["geometry"]["validation"].values())


@pytest.mark.parametrize(
    "settings", [{"card_value": 100}, {"uneven": True}, {"center": (260, 380)}, {"radius": 35}]
)
def test_tone_backing_margin_and_rounded_corner_variation(settings):
    report, _, _, _ = detect(synthetic(**settings), [150, 150], configuration({}))
    assert report["status"] == "success", report


def test_shadow_needs_review_instead_of_unqualified_success():
    report, _, _, _ = detect(synthetic(shadow=True), [150, 150], configuration({}))
    assert report["status"] in {"review_required", "failure"}, report


@pytest.mark.parametrize(
    "image",
    [
        np.full((800, 600, 3), 245, np.uint8),
        synthetic(center=(100, 400)),
        synthetic(size=(480, 520)),
    ],
)
def test_missing_cropped_and_wrong_aspect_do_not_silently_succeed(image):
    report, _, _, _ = detect(image, [150, 150], configuration({}))
    assert report["status"] in {"failure", "review_required"}


def test_multiple_card_candidates_are_ambiguous():
    image = synthetic(center=(220, 400), margin_shape=(1200, 800))
    other = synthetic(center=(950, 400), margin_shape=(1200, 800))
    report, _, _, _ = detect(
        np.minimum(image, other),
        [150, 150],
        configuration({"minimum_candidate_area_fraction": 0.05}),
    )
    assert report["status"] == "review_required"
    assert "multiple_comparable_candidates" in report["flags_requiring_review"]


@pytest.mark.parametrize(
    "dpi", [None, [0, 150], [-1, 150], [float("nan"), 150], [float("inf"), 150]]
)
def test_invalid_dpi_preserves_pixels_but_requires_review(dpi):
    report, _, _, _ = detect(synthetic(), dpi, configuration({}))
    assert report["status"] == "review_required"
    assert not report["geometry"]["validation"]["valid_dpi"]
    assert report["geometry"]["millimeters_from_reported_dpi"] is None


def test_bow_tie_geometry_is_not_convex():
    result = geometries(
        np.array([[0, 0], [372, 520], [372, 0], [0, 520]], float),
        [150, 150],
        (800, 600, 3),
        configuration({}),
    )
    assert not result["validation"]["convex_non_self_intersecting"]


def test_preprocessing_is_global_and_original_coordinates_unchanged():
    rgb = synthetic(angle=4, card_value=140)
    original = rgb.copy()
    baseline = configuration({})
    enhanced = configuration({"preprocessing": {"normalize_percentiles": [1, 99], "contrast": 1.1}})
    a, _, _, _ = detect(rgb, [150, 150], baseline)
    b, _, _, _ = detect(rgb, [150, 150], enhanced)
    assert np.array_equal(rgb, original)
    assert working_gray(rgb, enhanced["preprocessing"]).shape == rgb.shape[:2]
    assert (
        np.max(np.abs(np.array(a["geometry"]["corners_pixels"]) - b["geometry"]["corners_pixels"]))
        < 2
    )


def test_single_image_diagnostics_and_immutable_original(tmp_path):
    image = tmp_path / "original.bmp"
    Image.fromarray(synthetic()).save(image, dpi=(150, 150))
    digest = sha256_file(image)
    output = tmp_path / "output"
    report = analyze(image, output, configuration({}), compare_preprocessing=True)
    assert report["status"] == "success"
    assert report["original_hash_verified_after_analysis"]
    assert report["source"]["sha256"] == digest == sha256_file(image)
    assert (output / "baseline-overlay.png").is_file()
    assert (output / "preprocessed-overlay.png").is_file()
    assert json.loads((output / "baseline-support.json").read_text(encoding="utf-8"))[
        "accepted_pixels"
    ]
    assert report["preprocessing_comparison"]["preferred_result"] is None
    with pytest.raises(FileExistsError):
        analyze(image, output, configuration({}))


def test_corrupt_input_has_explicit_failure(tmp_path):
    path = tmp_path / "corrupt.bmp"
    path.write_bytes(b"not an image")
    result = analyze(path, tmp_path / "output", configuration({}))
    assert result["status"] == "failure"
    assert result["reason"] == "invalid_image"
    assert result["source"]["sha256"] == sha256_file(path)
    assert result["diagnostic_overlay_unavailable"]


def fixture_analysis(corners, sha):
    geometry = geometries(corners, [150, 150], (800, 600, 3), configuration({}))
    return {
        "status": "success",
        "dpi": [150, 150],
        "source": {"sha256": sha, "image": {"frames": [{"width": 600, "height": 800}]}},
        "baseline": {"status": "success", "geometry": geometry},
    }


def test_repeatability_raw_shifts_and_rigid_registered_shape():
    base = np.array([[110, 140], [482, 140], [482, 660], [110, 660]], float)
    analyses = [
        fixture_analysis(base + [x, y], str(i))
        for i, (x, y) in enumerate(((0, 0), (3, -2), (-3, 2)))
    ]
    result = repeatability(analyses)
    assert result["status"] == "success"
    assert result["raw_image_coordinates"]["center_pixels"][
        "sample_standard_deviation"
    ] == pytest.approx([3, 2])
    assert (
        np.max(
            result["shape_only_rigid_registered"]["corner_coordinates_pixels"][
                "sample_standard_deviation"
            ]
        )
        < 1e-8
    )
    assert result["raw_image_coordinates"]["width_pixels"]["sample_standard_deviation"] == 0
    assert result["accuracy_calibration"] is False


def test_rigid_registration_cannot_hide_scale_changes():
    base = np.array([[0, 0], [372, 0], [372, 520], [0, 520]], float)
    aligned, transform = rigid_to_reference(base * 1.01 + [10, 20], base)
    assert np.linalg.norm(aligned - base) > 1
    assert transform["scale"] == 1
    theta = np.deg2rad(4)
    rotation = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    registered, _ = rigid_to_reference(base @ rotation + [3, 4], base)
    assert np.max(np.abs(registered - base)) < 1e-8


def test_repeat_rejects_duplicates_and_failed_detections():
    base = np.array([[110, 140], [482, 140], [482, 660], [110, 660]], float)
    one = fixture_analysis(base, "same")
    assert (
        repeatability([one, one, one])["reason"]
        == "duplicate_source_hashes_not_independent_evidence"
    )
    failed = copy.deepcopy(one)
    failed["source"]["sha256"] = "different"
    failed["baseline"] = {"status": "failure"}
    other = copy.deepcopy(one)
    other["source"]["sha256"] = "third"
    assert repeatability([one, failed, other])["status"] == "failure"


def test_repeat_cli_uses_three_images_and_unique_artifacts(tmp_path, monkeypatch):
    from spectra_boundary import cli
    from spectra_scanner import common

    root = tmp_path / "local_data"
    monkeypatch.setattr(cli, "DATA_ROOT", root)
    monkeypatch.setattr(common, "DATA_ROOT", root)
    paths = []
    for index, shift in enumerate((0, 2, -2)):
        image = tmp_path / f"scan-{index}.bmp"
        Image.fromarray(synthetic(center=(300 + shift, 400))).save(image, dpi=(150, 150))
        paths.append(str(image))
    assert main(["repeat", *paths]) == 0
    assert main(["repeat", *paths]) == 0
    assert len(list((root / "s2_1").glob("*/report.json"))) == 2
    assert main(["repeat", *paths[:2]]) == 3


@pytest.mark.parametrize(
    "value",
    [
        {"reference_width_mm": -1},
        {"minimum_side_coverage": 2},
        {"maximum_rms_pixels": float("nan")},
        {"preprocessing": {"contrast": 3}},
        {"preprocessing": {"normalize_percentiles": [99, 1]}},
        {"unknown": 1},
    ],
)
def test_configuration_validation(value):
    with pytest.raises(AgentError):
        configuration(value)


def test_nominal_format_is_configurable_not_a_universal_card_size():
    result, _, _, _ = detect(
        synthetic(size=(480, 520)),
        [150, 150],
        configuration({"reference_width_mm": 81.3, "reference_height_mm": 88}),
    )
    assert result["status"] == "success"


def test_margin_and_residual_limits_are_enforced():
    image = synthetic(center=(197, 272), margin_shape=(394, 544))
    conservative, _, _, _ = detect(image, [150, 150], configuration({}))
    permissive, _, _, _ = detect(image, [150, 150], configuration({"minimum_margin_pixels": 5}))
    assert conservative["status"] == "review_required"
    assert not conservative["geometry"]["validation"]["image_margin"]
    assert permissive["status"] == "success"
    tight, _, _, _ = detect(
        synthetic(angle=5), [150, 150], configuration({"maximum_rms_pixels": 0.01})
    )
    assert tight["status"] == "review_required"
    assert not tight["geometry"]["validation"]["side_residuals"]


def test_repeat_orientation_variation_and_acquisition_changes_are_visible():
    base = np.array([[110, 140], [482, 140], [482, 660], [110, 660]], float)
    center = base.mean(axis=0)
    analyses = []
    for index, degrees in enumerate((-2, 0, 2)):
        theta = np.deg2rad(degrees)
        rotation = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
        analyses.append(fixture_analysis((base - center) @ rotation + center, str(index)))
    report = repeatability(analyses)
    assert report["raw_image_coordinates"]["angle_degrees_unwrapped_modulo_180"][
        "sample_standard_deviation"
    ] == pytest.approx(2)
    assert (
        np.max(
            report["shape_only_rigid_registered"]["corner_coordinates_pixels"][
                "sample_standard_deviation"
            ]
        )
        < 1e-8
    )
    for index, analysis in enumerate(analyses):
        analysis["source"]["acquisition"] = {
            "transfer_time_settings": {"ICAP_GAMMA": {"current": 1.0 if index == 0 else 2.2}}
        }
    assert repeatability(analyses)["status"] == "review_required"
    assert repeatability(analyses)["reported_acquisition_control_differences"]["ICAP_GAMMA"] == [
        1.0,
        2.2,
        2.2,
    ]


def test_manifest_hash_mismatch_prevents_analysis(tmp_path):
    image = tmp_path / "original.bmp"
    Image.fromarray(synthetic()).save(image, dpi=(150, 150))
    (tmp_path / "metadata.json").write_text(
        json.dumps({"original": image.name, "complete": True, "sha256": "wrong"}), encoding="utf-8"
    )
    result = analyze(image, tmp_path / "output", configuration({}))
    assert result["status"] == "failure"
    assert result["reason"] == "storage_integrity_error"


def test_driver_and_embedded_dpi_disagreement_requires_review(tmp_path):
    image = tmp_path / "original.bmp"
    Image.fromarray(synthetic()).save(image, dpi=(150, 150))
    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "original": image.name,
                "complete": True,
                "sha256": sha256_file(image),
                "provenance": {"twain_image_info": {"XResolution": 155, "YResolution": 155}},
            }
        ),
        encoding="utf-8",
    )
    result = analyze(image, tmp_path / "output", configuration({}))
    assert result["status"] == "review_required"
    assert result["dpi_evidence"] == "S1_driver_image_info"
    assert result["dpi_flags"] == ["driver_and_file_dpi_disagree"]


def test_repeat_correspondence_does_not_flip_at_canonical_90_degree_boundary():
    base = np.array([[110, 140], [482, 140], [482, 660], [110, 660]], float)
    center = base.mean(axis=0)
    analyses = []
    for index, degrees in enumerate((89.8, 90, 90.2)):
        theta = np.deg2rad(degrees)
        rotation = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
        analyses.append(fixture_analysis(ordered((base - center) @ rotation + center), str(index)))
    report = repeatability(analyses)
    assert report["status"] == "success"
    assert (
        np.max(
            report["raw_image_coordinates"]["corner_coordinates_pixels"][
                "sample_standard_deviation"
            ]
        )
        < 2
    )
    assert report["raw_image_coordinates"]["angle_degrees_unwrapped_modulo_180"][
        "sample_standard_deviation"
    ] == pytest.approx(0.2)


def test_failed_top_level_analysis_cannot_contribute_successful_geometry():
    base = np.array([[110, 140], [482, 140], [482, 660], [110, 660]], float)
    analyses = [fixture_analysis(base + [i, 0], str(i)) for i in range(3)]
    analyses[0]["status"] = "failure"
    assert repeatability(analyses)["reason"] == "one_or_more_analyses_failed"


def test_preprocessing_failure_is_not_hidden_by_baseline_success(tmp_path, monkeypatch):
    from spectra_boundary import analysis

    image = tmp_path / "original.bmp"
    Image.fromarray(synthetic()).save(image, dpi=(150, 150))
    original = analysis.detect
    calls = 0

    def detector(rgb, dpi, config):
        nonlocal calls
        calls += 1
        result, gray, accepted, rejected = original(rgb, dpi, config)
        if calls == 2:
            result = {"status": "failure", "reason": "synthetic_preprocessing_boundary_loss"}
        return result, gray, accepted, rejected

    monkeypatch.setattr(analysis, "detect", detector)
    result = analysis.analyze(
        image, tmp_path / "output", configuration({}), compare_preprocessing=True
    )
    assert result["baseline"]["status"] == "success"
    assert result["preprocessed"]["status"] == "failure"
    assert result["status"] == "review_required"
    assert result["preprocessing_comparison"]["preferred_result"] is None
