# ruff: noqa: E402
"""Synthetic references are test fixtures only, never manufactured real annotations."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
from test_centering import fixture

from reference_frames import main
from spectra_frame_evaluation.analysis import analyze, configuration
from spectra_reference import COORDINATES
from spectra_reference.comparison import compare, inventory
from spectra_reference.geometry import displacement
from spectra_reference.inputs import load_bundle, template, validate_annotation
from spectra_scanner.common import AgentError
from spectra_scanner.storage import sha256_file


def setup(tmp_path: Path) -> tuple:
    image, boundary = fixture(tmp_path)
    analyze(image, boundary, tmp_path / "b", configuration({}))
    report = tmp_path / "b/report.json"
    _, evaluation, provenance = load_bundle(image, report)
    annotation = template(provenance)
    annotation.update(annotation_id="synthetic-test-only", layout_status="supported")
    for side, candidates in zip(annotation["sides"], evaluation["sides"], strict=True):
        c = candidates["candidates"][0]
        side.update(
            status="annotated", definition="candidate", candidate_id=c["id"], line_abc=c["line_abc"]
        )
    return image, report, evaluation, provenance, annotation


def test_perfect_agreement_and_repeatable(tmp_path: Path) -> None:
    _, _, evaluation, provenance, reference = setup(tmp_path)
    result = compare(evaluation, reference, provenance)
    assert result == compare(evaluation, reference, provenance)
    row = result["hypotheses"][0]
    assert row["rank"] == 1
    assert row["aggregate"]["maximum_absolute_pixels"] == pytest.approx(0, abs=1e-10)
    assert result["status"] == "review_required"
    assert result["automatic_acceptance"] is False
    assert result["upstream_status"] == "review_required"


def test_parallel_displacement_and_millimeters(tmp_path: Path) -> None:
    _, _, evaluation, provenance, reference = setup(tmp_path)
    # Reference top is 5px exterior to the candidate, so displacement is +5 inward.
    reference["sides"][0].update(definition="manual", candidate_id=None, line_abc=[0, 1, -105])
    result = compare(evaluation, reference, provenance)
    side = result["hypotheses"][0]["per_side"]["top"]
    # S2.2a's synthetic fitted edge sits at y=109, not the pixel block boundary y=110.
    expected = (
        -(
            evaluation["sides"][0]["candidates"][0]["line_abc"][2]
            / evaluation["sides"][0]["candidates"][0]["line_abc"][1]
        )
        - 105
    )
    assert side["mean_signed_pixels"] == pytest.approx(expected, abs=0.01)
    assert side["mean_absolute_pixels"] == pytest.approx(abs(expected), abs=0.01)
    assert side["millimeters_from_reported_dpi"]["mean_absolute"] == pytest.approx(
        abs(expected) * 25.4 / 150, abs=0.01
    )


def test_tilted_line_and_span() -> None:
    corners = np.array([[0.0, 0.0], [400.0, 0.0], [400.0, 600.0], [0.0, 600.0]])
    # Candidate y=20+0.01*x, reference y=20; +4px displacement at x=400.
    signed, _, _, _ = displacement(
        corners, 0, [0, 1, -20], [-0.01, 1, -20], np.linspace(0.2, 0.8, 51)
    )
    assert signed.mean() == pytest.approx(2)
    assert signed.min() == pytest.approx(0.8)
    assert signed.max() == pytest.approx(3.2)
    changed, *_ = displacement(corners, 0, [0, 1, -20], [-0.01, 1, -20], np.linspace(0.4, 0.6, 51))
    assert changed.mean() == pytest.approx(2)
    assert changed.max() < signed.max()


def test_common_spans_and_duplicate_geometry(tmp_path: Path) -> None:
    _, _, evaluation, provenance, reference = setup(tmp_path)
    duplicate = deepcopy(evaluation["frame_evaluation"]["hypotheses"][0])
    duplicate["id"] = "duplicate-frame"
    c = deepcopy(evaluation["sides"][0]["candidates"][0])
    c["id"] = "duplicate-top"
    # Same line, less supported extent: both comparisons must use the shared interval.
    c["support_points_pixels"] = c["support_points_pixels"][30:-30]
    evaluation["sides"][0]["candidates"].append(c)
    duplicate["candidate_ids"][0] = c["id"]
    evaluation["frame_evaluation"]["hypotheses"].append(duplicate)
    result = compare(evaluation, reference, provenance)
    assert result["duplicate_inventory"]["unique_geometries"] == 1
    assert len(result["duplicate_inventory"]["geometry_groups"][0]["hypothesis_ids"]) == 2
    rows = result["hypotheses"]
    assert rows[0]["rank"] == rows[1]["rank"] == 1
    assert (
        rows[0]["per_side"]["top"]["span_fraction"] == rows[1]["per_side"]["top"]["span_fraction"]
    )
    assert rows[0]["per_side"]["top"]["span_fraction"][0] > 0.3


@pytest.mark.parametrize("status", ["ambiguous", "unannotated", "unannotatable"])
def test_missing_or_ambiguous_side_prevents_ranking(tmp_path: Path, status: str) -> None:
    _, _, evaluation, provenance, reference = setup(tmp_path)
    reference["sides"][0]["status"] = status
    if status != "ambiguous":
        reference["sides"][0]["line_abc"] = None
    result = compare(evaluation, reference, provenance)
    assert result["hypotheses"][0]["rank"] is None
    assert result["hypotheses"][0]["comparison_availability"] == "partial"
    assert result["status"] == "review_required"


@pytest.mark.parametrize("layout", ["unsupported", "ambiguous", "absent"])
def test_unsupported_layout(tmp_path: Path, layout: str) -> None:
    _, _, evaluation, provenance, reference = setup(tmp_path)
    reference["layout_status"] = layout
    result = compare(evaluation, reference, provenance)
    assert not result["ranked_hypothesis_ids"]
    assert result["hypotheses"][0]["comparison_availability"] == "none"


@pytest.mark.parametrize(
    "change", ["hash", "coordinates", "candidate", "span", "version", "timestamp"]
)
def test_annotation_guards(tmp_path: Path, change: str) -> None:
    _, _, evaluation, provenance, reference = setup(tmp_path)
    if change == "hash":
        reference["provenance"] = deepcopy(provenance)
        reference["provenance"]["image_sha256"] = "0" * 64
    if change == "coordinates":
        reference["coordinate_system"] = "rectified_pixels"
    if change == "candidate":
        reference["sides"][0]["line_abc"] = [0, 1, -400]
    if change == "span":
        reference["sides"][0]["valid_span_fraction"] = [0.9, 0.1]
    if change == "version":
        reference["schema_version"] = 99
    if change == "timestamp":
        reference["annotated_at_utc"] = "2026-10-17T12:00:00"
    with pytest.raises((AgentError, ValueError)):
        validate_annotation(reference, evaluation, provenance)


def test_invalid_reference_geometry_and_incomplete_hypotheses(tmp_path: Path) -> None:
    _, _, evaluation, provenance, reference = setup(tmp_path)
    incomplete = deepcopy(evaluation["frame_evaluation"]["hypotheses"][0])
    incomplete.update(id="incomplete", candidate_ids=incomplete["candidate_ids"][:3])
    evaluation["frame_evaluation"]["hypotheses"].append(incomplete)
    result = compare(evaluation, reference, provenance)
    assert result["hypotheses"][0]["rank"] == 1
    assert result["hypotheses"][1]["rank"] is None
    assert result["hypotheses"][1]["comparison_availability"] == "partial"
    assert result["hypotheses"][1]["aggregate"]["compared_sides"] == 3
    reference["sides"][0].update(definition="manual", candidate_id=None, line_abc=[0, 1, 100])
    result = compare(evaluation, reference, provenance)
    assert "inconsistent_reference_geometry" in result["reference_quality_flags"]
    assert not result["ranked_hypothesis_ids"]


def test_invalid_dpi_and_duplicate_combinations(tmp_path: Path) -> None:
    _, _, evaluation, provenance, reference = setup(tmp_path)
    provenance = deepcopy(provenance)
    provenance["dpi"] = [0, None]
    reference["provenance"] = provenance
    duplicate = deepcopy(evaluation["frame_evaluation"]["hypotheses"][0])
    duplicate["id"] = "same-combination"
    evaluation["frame_evaluation"]["hypotheses"].append(duplicate)
    result = compare(evaluation, reference, provenance)
    assert len(result["duplicate_inventory"]["duplicated_combinations"]) == 1
    assert result["hypotheses"][0]["per_side"]["top"]["millimeters_from_reported_dpi"] is None
    assert result["hypotheses"][0]["rank"] == result["hypotheses"][1]["rank"]


def test_cli_versions_and_input_immutability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import reference_frames

    image, report, evaluation, provenance, reference = setup(tmp_path)
    monkeypatch.setattr(reference_frames, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(reference_frames, "confined_data_dir", lambda path: path)
    downloaded = tmp_path / "download.json"
    downloaded.write_text(json.dumps(reference))
    inputs = [image, report, Path(provenance["s2_1"]["path"]), downloaded]
    before = [sha256_file(path) for path in inputs]
    paths = []
    for _ in range(2):
        assert main(["save", str(image), str(report), "--reference", str(downloaded)]) == 0
        paths.append(json.loads(capsys.readouterr().out)["reference"])
    assert paths[0] != paths[1]
    assert main(["prepare", str(image), str(report), "--reference", paths[0]]) == 0
    interface = Path(json.loads(capsys.readouterr().out)["interface"])
    assert "data:image/png;base64," in interface.read_text()
    assert COORDINATES in interface.read_text()
    assert main(["compare", str(image), str(report), "--reference", paths[0]]) == 2
    result_path = Path(json.loads(capsys.readouterr().out)["report"])
    result = json.loads(result_path.read_text())
    assert result["input_hashes_verified_after_analysis"]
    assert (result_path.parent / result["hypotheses"][0]["overlay"]).is_file()
    assert [sha256_file(path) for path in inputs] == before


def test_existing_tritox_structure_without_fabricating_reference() -> None:
    report = Path(
        "local_data/s2_2b_validation/20261017T202702_0892dd46243f4756a0076014efe3f13f/pair-000-b/report.json"
    )
    if not report.exists():
        pytest.skip("Local real-scan dataset is not distributed")
    evaluation = json.loads(report.read_text())
    image = Path(evaluation["inputs"]["image_path"])
    _, evaluation, provenance = load_bundle(image, report)
    result = inventory(evaluation)
    assert result["hypothesis_count"] == result["unique_geometries"] == 9
    assert not result["duplicated_combinations"]
    annotation = template(provenance)
    assert all(side["line_abc"] is None for side in annotation["sides"])


def test_offline_browser_interface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import os
    import shutil
    import subprocess

    from spectra_reference.artifacts import annotation_page

    chrome = os.environ.get("CHROME_PATH", "C:/Program Files/Google/Chrome/Application/chrome.exe")
    node = shutil.which("node")
    if not node or not Path(chrome).exists():
        pytest.skip("Optional Node/Chrome UI test unavailable")
    image, report, evaluation, provenance, _ = setup(tmp_path)
    from PIL import Image

    page = tmp_path / "annotate.html"
    annotation_page(np.asarray(Image.open(image)), evaluation, template(provenance), page)
    sources = [image, report, Path(provenance["s2_1"]["path"])]
    hashes = [sha256_file(path) for path in sources]
    result = subprocess.run(
        [node, str(Path(__file__).with_name("reference-browser.mjs")), str(page)],
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Offline annotation UI: passed" in result.stdout
    exported = json.loads(
        next(
            row.removeprefix("SYNTHETIC_EXPORT:")
            for row in result.stdout.splitlines()
            if row.startswith("SYNTHETIC_EXPORT:")
        )
    )
    assert validate_annotation(exported, evaluation, provenance) == []
    import reference_frames

    monkeypatch.setattr(reference_frames, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(reference_frames, "confined_data_dir", lambda path: path)
    downloaded = tmp_path / "browser-export.json"
    downloaded.write_text(json.dumps(exported))
    assert main(["save", str(image), str(report), "--reference", str(downloaded)]) == 0
    saved = json.loads(capsys.readouterr().out)["reference"]
    assert main(["compare", str(image), str(report), "--reference", saved]) == 2
    compared = Path(json.loads(capsys.readouterr().out)["report"])
    comparison = json.loads(compared.read_text())
    assert comparison["status"] == "review_required"
    assert comparison["automatic_acceptance"] is False
    assert not comparison["reference_quality_flags"]
    assert main(["prepare", str(image), str(report), "--reference", saved]) == 0
    reloaded = json.loads(capsys.readouterr().out)["interface"]
    roundtrip = subprocess.run(
        [node, str(Path(__file__).with_name("reference-browser.mjs")), reloaded, "roundtrip"],
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert roundtrip.returncode == 0, roundtrip.stdout + roundtrip.stderr
    imported = json.loads(
        next(
            row.removeprefix("SYNTHETIC_EXPORT:")
            for row in roundtrip.stdout.splitlines()
            if row.startswith("SYNTHETIC_EXPORT:")
        )
    )
    assert imported["sides"] == exported["sides"]
    assert validate_annotation(imported, evaluation, provenance) == []
    assert imported["previous_annotation_sha256"] == sha256_file(Path(saved))
    assert [sha256_file(path) for path in sources] == hashes


def test_editor_coordinate_core() -> None:
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("Optional Node geometry tests unavailable")
    result = subprocess.run(
        [node, str(Path(__file__).with_name("reference-editor-core.mjs"))],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Editor core: passed" in result.stdout
