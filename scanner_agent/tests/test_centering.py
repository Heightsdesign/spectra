# ruff: noqa: E402
"""Synthetic correctness only: not scanner accuracy or card-design validation."""

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
from PIL import Image

from spectra_centering.analysis import analyze
from spectra_centering.config import validate
from spectra_scanner.storage import sha256_file


def fixture(
    tmp_path: Path,
    *,
    left: int = 20,
    right: int = 20,
    angle: float = 0,
    contrast: int = 110,
    missing: bool = False,
    artwork: bool = False,
    competing: bool = False,
) -> tuple[Path, Path]:
    rgb = np.full((720, 560, 3), 250, dtype=np.uint8)
    rgb[90:610, 90:462] = 220
    if not missing:
        rgb[110:590, 90 + left : 462 - right] = [
            contrast,
            80 if contrast < 200 else contrast,
            60 if contrast < 200 else contrast,
        ]
    if competing:
        rgb[118:582, 90 + left + 8 : 462 - right - 8] = [80, 40, 30]
    if artwork:
        for y in range(90, 610, 6):
            rgb[y : y + 3, 90:462] = 150
        rgb[140:560, 140:412] = [80, 40, 30]
    corners = np.array([[90.0, 90.0], [462.0, 90.0], [462.0, 610.0], [90.0, 610.0]])
    if angle:
        rotation = cv2.getRotationMatrix2D((280, 350), angle, 1)
        rgb = cv2.warpAffine(rgb, rotation, (560, 720), borderValue=(250, 250, 250))
        corners = np.c_[corners, np.ones(4)] @ rotation.T
    image = tmp_path / "source.bmp"
    Image.fromarray(rgb).save(image, dpi=(150, 150))
    sides = []
    for i in range(4):
        p, q = corners[i], corners[(i + 1) % 4]
        n = np.array([-(q - p)[1], (q - p)[0]])
        n /= np.linalg.norm(n)
        sides.append(
            {"index": i, "line_abc": [*n, float(-np.dot(n, p))], "ambiguous_parallel_edge": False}
        )
    report = tmp_path / "boundary.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "single_image",
                "algorithm_version": "0.2.0",
                "status": "review_required",
                "original_hash_verified_after_analysis": True,
                "source": {
                    "sha256": sha256_file(image),
                    "image": {"frames": [{"width": 560, "height": 720, "mode": "RGB"}]},
                },
                "dpi": [150, 150],
                "baseline": {
                    "status": "review_required",
                    "sides": sides,
                    "geometry": {
                        "corners_pixels": corners.tolist(),
                        "validation": dict.fromkeys(
                            (
                                "convex_non_self_intersecting",
                                "parallel",
                                "perpendicular",
                                "image_margin",
                                "exactly_four_fitted_sides",
                                "side_residuals",
                                "side_support",
                            ),
                            True,
                        ),
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return image, report


@pytest.mark.parametrize("angle", [0, 7, -8, 180])
def test_centered_and_rotated(tmp_path: Path, angle: float) -> None:
    image, upstream = fixture(tmp_path, angle=angle)
    before = (sha256_file(image), sha256_file(upstream))
    result = analyze(image, upstream, tmp_path / "out", validate({}))
    assert result["frame_evidence_status"] == "supported", result
    assert result["status"] == "review_required"
    assert result["automatic_acceptance"] is False
    assert "upstream_review_required" in result["quality_flags"]
    assert result["measurements"]["centering_percent"]["left"] == pytest.approx(50, abs=2)
    assert len(result["measurements"]["margins"]["left"]["distances_pixels"]) == 21
    assert (sha256_file(image), sha256_file(upstream)) == before
    assert len(result["artifacts"]) == 5
    with pytest.raises(FileExistsError):
        analyze(image, upstream, tmp_path / "out", validate({}))


def test_off_center(tmp_path: Path) -> None:
    image, upstream = fixture(tmp_path, left=12, right=28)
    result = analyze(image, upstream, tmp_path / "out", validate({}))
    assert result["measurements"]["centering_percent"]["left"] == pytest.approx(30, abs=3)


@pytest.mark.parametrize("options", [{"missing": True}, {"contrast": 216}, {"artwork": True}])
def test_insufficient_evidence(tmp_path: Path, options: dict) -> None:
    image, upstream = fixture(tmp_path, **options)
    result = analyze(image, upstream, tmp_path / "out", validate({}))
    assert result["measurements"] is None
    assert result["status"] in {"review_required", "not_applicable"}


def test_competing_candidates_preserved(tmp_path: Path) -> None:
    image, upstream = fixture(tmp_path, competing=True)
    result = analyze(
        image, upstream, tmp_path / "out", validate({"maximum_outer_band_color_deviation": 250})
    )
    assert result["frame_evidence_status"] == "ambiguous"
    assert result["measurements"] is None
    assert all(len(side["candidates"]) >= 2 for side in result["sides"])


@pytest.mark.parametrize("change", ["hash", "version", "geometry", "index", "dpi"])
def test_input_guards(tmp_path: Path, change: str) -> None:
    image, upstream = fixture(tmp_path)
    value = json.loads(upstream.read_text())
    if change == "hash":
        value["source"]["sha256"] = "0" * 64
    if change == "version":
        value["algorithm_version"] = "0.1.0"
    if change == "geometry":
        value["baseline"]["geometry"]["corners_pixels"][0] = [5000, 0]
    if change == "index":
        value["kind"] = "analysis_index"
    if change == "dpi":
        value["dpi"] = [0, None]
    upstream.write_text(json.dumps(value), encoding="utf-8")
    result = analyze(image, upstream, tmp_path / "out", validate({}))
    if change == "dpi":
        assert result["measurements"]["margins"]["top"]["mean_mm_from_reported_dpi"] is None
    else:
        assert result["status"] == "analysis_failed"
        assert result["measurements"] is None


def test_corrupt_and_missing(tmp_path: Path) -> None:
    image, upstream = fixture(tmp_path)
    image.write_bytes(b"corrupt")
    assert analyze(image, upstream, tmp_path / "out", validate({}))["status"] == "analysis_failed"
    assert (
        analyze(image, tmp_path / "missing.json", tmp_path / "out2", validate({}))["status"]
        == "analysis_failed"
    )


def test_configuration_rejects_unknown_and_nonfinite() -> None:
    from spectra_scanner.common import AgentError

    for config in (
        {"unknown": 1},
        {"minimum_color_transition": float("nan")},
        {"mode": "borderless"},
    ):
        with pytest.raises(AgentError):
            validate(config)


def test_nonparallel_margin_distribution(tmp_path: Path) -> None:
    from spectra_centering.detector import measurements

    corners = np.array([[0.0, 0.0], [400.0, 0.0], [400.0, 600.0], [0.0, 600.0]])
    # Left printed side tilts: x=20 + y/100. Multi-position samples must retain variation.
    lines = [[0, 1, -20], [1, 0, -380], [0, 1, -580], [1, -0.01, -20]]
    sides = [
        {
            "name": name,
            "selected_candidate_id": name,
            "candidates": [{"id": name, "line_abc": line}],
        }
        for name, line in zip(("top", "right", "bottom", "left"), lines, strict=True)
    ]
    result = measurements(corners, sides, [600, 600], validate({}))
    left = result["margins"]["left"]
    assert left["mean_pixels"] == pytest.approx(23)
    assert left["max_pixels"] - left["min_pixels"] > 3
    assert left["std_pixels"] > 0


def test_cli_reports_failure_and_unique_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from spectra_centering import cli

    monkeypatch.setattr(cli, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(cli, "confined_data_dir", lambda path: path)
    args = [str(tmp_path / "missing.bmp"), str(tmp_path / "missing.json")]
    reports = []
    for _ in range(2):
        assert cli.main(args) == 3
        reports.append(json.loads(capsys.readouterr().out)["report"])
    assert reports[0] != reports[1]
    for path in reports:
        report = json.loads(Path(path).read_text())
        assert report["status"] == "analysis_failed"
        assert report["input_hashes_verified_after_analysis"] is False
