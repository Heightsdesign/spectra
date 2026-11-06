# ruff: noqa: E402
import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
from PIL import Image

from spectra_physical_reference.cli import main
from spectra_physical_reference.comparison import compare
from spectra_physical_reference.editor import page
from spectra_physical_reference.model import draft, load_image, load_report, safe_validate
from spectra_physical_reference.refit_investigation import investigate
from spectra_scanner.common import utc_now
from spectra_scanner.storage import sha256_file


def fixture(tmp_path):
    image = tmp_path / "SYNTHETIC-original.bmp"
    pixels = np.full((400, 320, 3), 245, np.uint8)
    pixels[80:320, 60:260] = [100, 130, 160]
    Image.fromarray(pixels).save(image, dpi=(150, 150))
    _, identity = load_image(image)
    reference = draft(identity, [])
    reference.update(reviewer="SYNTHETIC TEST ONLY", independent_review_declared=True)
    corners = np.array([[60.0, 80.0], [260.0, 80.0], [260.0, 320.0], [60.0, 320.0]])
    for i, side in enumerate(reference["sides"]):
        points = corners[i] + np.array([0.18, 0.82])[:, None] * (corners[(i + 1) % 4] - corners[i])
        a, b = points
        abc = np.cross([*a, 1.0], [*b, 1.0])
        abc /= np.linalg.norm(abc[:2])
        side.update(
            status="certain",
            endpoints=points.tolist(),
            line_abc=abc.tolist(),
            confirmed=True,
            confirmed_at_utc=utc_now(),
        )
        stamp(side)
    return image, pixels, identity, reference, corners


def stamp(side):
    side["reviewed"] = {
        key: copy.deepcopy(side[key])
        for key in ("status", "endpoints", "line_abc", "uncertainty_pixels", "notes", "origin")
    }


def detector_report(path, reference, shift=2.0, version="0.2.0"):
    sides = []
    for i, side in enumerate(reference["sides"]):
        abc = np.asarray(side["line_abc"])
        # These synthetic endpoint lines are oriented with inward normals.
        abc[2] -= shift
        sides.append(
            {
                "index": i,
                "line_abc": abc.tolist(),
                "candidate_layers": [{"id": "L0", "line_abc": abc.tolist(), "selected": True}],
            }
        )
    value = {
        "schema_version": 1,
        "kind": "single_image",
        "algorithm_version": version,
        "source": {"sha256": reference["image"]["sha256"]},
        "original_hash_verified_after_analysis": True,
        "status": "review_required",
        "baseline": {
            "status": "review_required",
            "sides": sides,
            "geometry": {
                "corners_pixels": [[60, 80], [260, 80], [260, 320], [60, 320]],
                "validation": {"unambiguous_side_layers": False},
            },
        },
    }
    path.write_text(json.dumps(value))
    return value


def test_manual_reference_geometry_and_schema(tmp_path):
    _, _, identity, reference, corners = fixture(tmp_path)
    valid = safe_validate(reference, identity)
    assert valid["complete_certain_reference"]
    assert np.allclose(valid["corners_pixels"], corners)
    schema = json.loads(
        (
            Path(__file__).parents[1] / "experiments/physical_reference/reference.schema.json"
        ).read_text()
    )
    assert schema["properties"]["kind"]["const"] == "physical_boundary_reference"
    assert set(schema["required"]) == set(reference)


@pytest.mark.parametrize(
    "defect",
    [
        "hash",
        "size",
        "kind",
        "uuid",
        "missing",
        "stale",
        "order",
        "parallel",
        "outside",
        "reverse",
        "reviewer",
        "declaration",
        "nan",
        "uncertainty",
        "indeterminate_geometry",
        "line_mismatch",
    ],
)
def test_invalid_or_cross_image_annotations_are_rejected(tmp_path, defect):
    _, _, identity, ref, _ = fixture(tmp_path)
    s = ref["sides"][0]
    if defect == "hash":
        ref["image"]["sha256"] = "0" * 64
    if defect == "size":
        ref["image"]["dimensions"][0] += 1
    if defect == "kind":
        ref["kind"] = "outer_printed_frame_reference"
    if defect == "uuid":
        ref["annotation_id"] = "card-d"
    if defect == "missing":
        s["confirmed"] = False
    if defect == "stale":
        s["notes"] = "edited after confirmation"
    if defect == "order":
        ref["sides"][0], ref["sides"][1] = ref["sides"][1], ref["sides"][0]
    if defect == "parallel":
        s.update(line_abc=[1.0, 0.0, -60.0], endpoints=[[60.0, 80.0], [60.0, 300.0]])
    if defect == "outside":
        s.update(line_abc=[0.0, 1.0, 3.0], endpoints=[[60.0, -3.0], [260.0, -3.0]])
    if defect == "reverse":
        ref["sides"][0]["endpoints"], ref["sides"][2]["endpoints"] = (
            ref["sides"][2]["endpoints"],
            ref["sides"][0]["endpoints"],
        )
        ref["sides"][0]["line_abc"], ref["sides"][2]["line_abc"] = (
            ref["sides"][2]["line_abc"],
            ref["sides"][0]["line_abc"],
        )
    if defect == "reviewer":
        ref["reviewer"] = " "
    if defect == "declaration":
        ref["independent_review_declared"] = False
    if defect == "nan":
        s["line_abc"][0] = float("nan")
    if defect == "uncertainty":
        s.update(status="uncertain", uncertainty_pixels=0)
    if defect == "indeterminate_geometry":
        s.update(status="indeterminate", notes="unknown edge")
    if defect == "line_mismatch":
        s["line_abc"][2] += 2
    if defect not in {"stale", "missing"}:
        for side in ref["sides"]:
            stamp(side)
    expected = copy.deepcopy(identity)
    if defect == "hash":
        expected["sha256"] = "1" * 64
    if defect == "size":
        expected["dimensions"][0] -= 1
    with pytest.raises(ValueError):
        safe_validate(ref, expected)


def test_comparison_known_normal_offsets_corners_and_no_promotion(tmp_path):
    _, _, identity, ref, _ = fixture(tmp_path)
    paths = [tmp_path / "frozen.json", tmp_path / "experiment.json"]
    detector_report(paths[0], ref, 2)
    detector_report(paths[1], ref, 1, "0.3.0-exp1")
    result = compare(ref, identity, paths)
    for expected, row in zip((2, 1), result["results"], strict=True):
        assert all(s["mean_absolute_pixels"] == pytest.approx(expected) for s in row["per_side"])
        assert all(
            c["distance_pixels"] == pytest.approx(np.sqrt(2) * expected) for c in row["corners"]
        )
        assert row["whole_contour"]["available"]
        assert row["detector_status_unchanged"] == "review_required"
    assert result["accuracy_score"] is None


@pytest.mark.parametrize("status", ["uncertain", "indeterminate"])
def test_uncertain_references_do_not_produce_definitive_accuracy(tmp_path, status):
    _, _, identity, ref, _ = fixture(tmp_path)
    path = tmp_path / "detector.json"
    detector_report(path, ref)
    s = ref["sides"][0]
    s.update(
        status=status,
        notes="SYNTHETIC uncertainty",
        uncertainty_pixels=3 if status == "uncertain" else None,
    )
    if status == "indeterminate":
        s.update(endpoints=None, line_abc=None)
    stamp(s)
    result = compare(ref, identity, [path])
    side = result["results"][0]["per_side"][0]
    assert result["accuracy_score"] is None and not result["reference_complete_and_certain"]
    if status == "uncertain":
        assert not side["eligible_for_certain_reference_agreement"]
        assert max(side["distance_beyond_uncertainty_band_pixels"]) == 0
    else:
        assert not side["available"]
        assert not result["results"][0]["whole_contour"]["available"]


def test_unconfirmed_editor_and_lossless_embedded_pixels(tmp_path):
    import base64
    import io
    import re

    image, pixels, identity, ref, _ = fixture(tmp_path)
    before = sha256_file(image)
    output = tmp_path / "editor.html"
    reference = draft(identity, [])
    reference["reviewer"] = '</script><script>alert("bad")</script>'
    page(pixels, reference, [], output)
    content = output.read_text(encoding="utf-8")
    payload = re.search(
        r'<script id="payload" type="application/json">(.*?)</script>', content
    ).group(1)
    value = json.loads(payload)
    encoded = value["image"].split(",")[1]
    assert np.array_equal(np.asarray(Image.open(io.BytesIO(base64.b64decode(encoded)))), pixels)
    assert not any(s["confirmed"] or s["line_abc"] for s in value["reference"]["sides"])
    assert "</script><script>alert" not in content
    assert sha256_file(image) == before
    with pytest.raises(FileExistsError):
        page(pixels, ref, [], output)


def test_cli_immutable_storage_identity_checks_and_new_review(tmp_path, capsys):
    image, _, _, ref, _ = fixture(tmp_path)
    report = tmp_path / "detector.json"
    detector_report(report, ref)
    annotation = tmp_path / "SYNTHETIC-reviewed.json"
    annotation.write_text(json.dumps(ref))
    before = {p: sha256_file(p) for p in (image, report, annotation)}
    for operation in ("save", "compare", "prepare"):
        out = tmp_path / operation
        args = [
            operation,
            str(image),
            "--report",
            str(report),
            "--reference",
            str(annotation),
            "--output",
            str(out),
        ]
        assert main(args) == 0, capsys.readouterr().out
        assert main(args) == 2
    new = json.loads((tmp_path / "prepare/unconfirmed-draft.json").read_text())
    assert new["annotation_id"] != ref["annotation_id"]
    assert all(not s["confirmed"] for s in new["sides"])
    assert not new["independent_review_declared"]
    assert new["previous_annotation_sha256"] == sha256_file(annotation)
    assert all(sha256_file(p) == digest for p, digest in before.items())


def test_cross_card_detector_report_refused(tmp_path):
    _, _, identity, ref, _ = fixture(tmp_path)
    path = tmp_path / "wrong-card.json"
    value = detector_report(path, ref)
    value["source"]["sha256"] = "0" * 64
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        load_report(path, identity)


def test_card_d_exact_refit_reconstruction_without_changing_guard(tmp_path):
    root = Path(__file__).parents[1]
    report = (
        root / "local_data/controlled-boundary/20261018T140407/evaluation/capture-021/frozen.json"
    )
    if not report.exists():
        pytest.skip("Local Card D evidence unavailable")
    original = (
        root
        / "local_data/s2_2c_validation/card-d/captures/20261018T061725_b599c7bc84654c2b9db6506a6ec92287/original.bmp"
    )
    result = investigate(original, report, tmp_path / "refit")
    final = result["metrics"]["final_reassignment_proposal"]
    assert final["support_count"] == 579
    assert final["coverage"] == 0.8
    assert final["maximum_movement_pixels"] == pytest.approx(0.9257337713602873, abs=1e-9)
    assert result["guard_unchanged_pixels"] == 0.5
    assert result["exact_experiment_decision"]["status"] == "rejected"
    assert not result["geometry_installed"]


def test_physical_editor_real_browser_on_synthetic_image(tmp_path):
    chrome = os.environ.get("CHROME_PATH", "C:/Program Files/Google/Chrome/Application/chrome.exe")
    node = shutil.which("node")
    if not node or not Path(chrome).exists():
        pytest.skip("Optional Chrome/Node unavailable")
    image, pixels, identity, ref, _ = fixture(tmp_path)
    report = tmp_path / "synthetic-report.json"
    value = detector_report(report, ref)
    output = tmp_path / "editor.html"
    experimental = copy.deepcopy(value)
    experimental.update(algorithm_version="0.3.0-exp1", experimental_phase="phase2")
    value["experimental_phase"] = "frozen"
    for detection in (value, experimental):
        for side in detection["baseline"]["sides"]:
            selected = side["candidate_layers"][0]
            selected.update(
                coverage=0.9,
                support_score=12.345,
                criterion_failures=[],
                physical_criterion_passed=True,
                disposition="provisional_selected",
            )
            side.update(selected_layer_id="L0", ambiguity_reasons=["synthetic_ambiguity"])
            for number in (1, 2):
                other = copy.deepcopy(selected)
                other.update(
                    id=f"L{number}",
                    selected=False,
                    coverage=0.625,
                    support_score=1.25,
                    criterion_failures=["side_coverage"],
                    physical_criterion_passed=False,
                    disposition="rejected_by_criterion",
                )
                other["line_abc"][2] += number * 3
                side["candidate_layers"].append(other)
    page(pixels, draft(identity, []), [value, experimental], output)
    result = subprocess.run(
        [node, str(Path(__file__).with_name("physical-reference-browser.mjs")), str(output)],
        capture_output=True,
        text=True,
        timeout=50,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # The browser exports only this synthetic fixture, never a real-card reference.
    exported = json.loads(result.stdout.strip().splitlines()[-1])
    safe_validate(exported, identity)
