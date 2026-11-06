# ruff: noqa: E402
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("cv2")
from test_physical_reference import detector_report, fixture, stamp

from spectra_physical_reference.blind import (
    freeze,
    post_compare,
    prepare,
    refresh_editor,
    verified_first_pass,
)


def setup_session(tmp_path):
    image, _, _, reference, _ = fixture(tmp_path)
    directory = tmp_path / "session"
    session = prepare(image, directory)
    for key in ("annotation_id", "annotation_version"):
        reference[key] = session[key]
    return directory, session, reference


def export_bundle(tmp_path, session, reference, exposure="none"):
    raw = json.dumps(reference, indent=3) + "\n"
    bundle = dict(
        schema_version=1,
        kind="blind_first_pass_export",
        session_id=session["session_id"],
        blind_review_declared=True,
        prior_detector_exposure=exposure,
        exported_at_utc=reference["created_at_utc"],
        reference_json=raw,
        reference_sha256=hashlib.sha256(raw.encode()).hexdigest(),
    )
    path = tmp_path / "download.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path, raw


def test_blind_payload_has_no_geometry_or_comparison_inputs(tmp_path):
    directory, _, _ = setup_session(tmp_path)
    html = (directory / "editor.html").read_text(encoding="utf-8")
    data = json.loads(
        html.split('<script id="blind-data" type="application/json">')[1].split("</script>")[0]
    )
    assert set(data) == {"image", "reference", "session_id"}
    assert data["reference"]["source_reports"] == []
    assert all(
        s["endpoints"] is None and not s["confirmed"] and s["origin"] == "manual"
        for s in data["reference"]["sides"]
    )
    for forbidden in [
        "candidate_layers",
        "0.2.0",
        "0.3.0",
        "L0",
        "detector_seed",
        'type="file"',
        "__DATA__",
    ]:
        assert forbidden not in html


@pytest.mark.parametrize("status", ["certain", "uncertain", "indeterminate"])
def test_freeze_statuses_exact_bytes_and_exclusive_first_pass(tmp_path, status):
    directory, session, reference = setup_session(tmp_path)
    side = reference["sides"][0]
    side["status"] = status
    if status == "uncertain":
        side.update(uncertainty_pixels=1.5, notes="SYNTHETIC blurred edge")
    if status == "indeterminate":
        side.update(endpoints=None, line_abc=None, notes="SYNTHETIC invisible edge")
    stamp(side)
    export, raw = export_bundle(tmp_path, session, reference)
    manifest = freeze(directory, export)
    assert (directory / "first-pass/reference.json").read_bytes() == raw.encode()
    assert (directory / "first-pass/export.json").read_bytes() == export.read_bytes()
    assert manifest["eligible_blind_declaration"]
    verified_first_pass(directory)
    with pytest.raises(FileExistsError):
        freeze(directory, export)


@pytest.mark.parametrize(
    "defect", ["unconfirmed", "seed", "exposure", "identity", "uncertain", "geometry"]
)
def test_reject_invalid_exports(tmp_path, defect):
    directory, session, reference = setup_session(tmp_path)
    side = reference["sides"][0]
    if defect == "unconfirmed":
        side["confirmed"] = False
    elif defect == "seed":
        side["origin"] = "detector_seed"
    elif defect == "exposure":
        reference["candidate_overlays_seen"] = True
    elif defect == "identity":
        reference["image"]["sha256"] = "0" * 64
    elif defect == "uncertain":
        side["status"] = "uncertain"
    else:
        side["line_abc"] = [0, 1, 999]
    stamp(side)
    export, _ = export_bundle(tmp_path, session, reference)
    with pytest.raises(ValueError):
        freeze(directory, export)
    assert not (directory / "first-pass").exists()


def test_checkpoint_comparison_and_tamper_detection(tmp_path):
    directory, session, reference = setup_session(tmp_path)
    report = tmp_path / "report.json"
    detector_report(report, reference)
    with pytest.raises(FileNotFoundError):
        post_compare(directory, [Path("NEVER_READ")], [])
    export, _ = export_bundle(tmp_path, session, reference, "exposed")
    assert not freeze(directory, export)["eligible_blind_declaration"]
    previous = tmp_path / "previous.json"
    previous.write_text(json.dumps(reference))
    result = json.loads(
        (post_compare(directory, [report], [previous]) / "comparison.json").read_text()
    )
    assert result["results"][0]["per_side"][0]["mean_absolute_pixels"] == pytest.approx(2)
    assert result["previous_references"][0]["corners"][0]["distance_pixels"] == 0
    frozen = directory / "first-pass/reference.json"
    frozen.write_bytes(frozen.read_bytes() + b" ")
    with pytest.raises(ValueError, match="integrity"):
        post_compare(directory, [report], [])


def test_export_hash_and_original_integrity(tmp_path):
    directory, session, reference = setup_session(tmp_path)
    export, _ = export_bundle(tmp_path, session, reference)
    value = json.loads(export.read_text())
    value["reference_sha256"] = "0" * 64
    export.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="SHA-256"):
        freeze(directory, export)
    Path(session["image_path"]).write_bytes(b"changed")
    with pytest.raises((ValueError, OSError)):
        freeze(directory, export)


def test_blind_browser_manual_synthetic_only(tmp_path):
    chrome = os.environ.get("CHROME_PATH", "C:/Program Files/Google/Chrome/Application/chrome.exe")
    node = shutil.which("node")
    if not node or not Path(chrome).exists():
        pytest.skip("Optional Chrome/Node unavailable")
    directory, _, _ = setup_session(tmp_path)
    result = subprocess.run(
        [
            node,
            str(Path(__file__).with_name("blind-reference-browser.mjs")),
            str(directory / "editor.html"),
        ],
        capture_output=True,
        text=True,
        timeout=50,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_refresh_preserves_identity_and_empty_payload(tmp_path):
    directory, session, _ = setup_session(tmp_path)
    session_bytes = (directory / "session.json").read_bytes()
    html = (directory / "editor.html").read_text(encoding="utf-8")
    payload = html.split('<script id="blind-data" type="application/json">')[1].split("</script>")[
        0
    ]
    refresh_editor(directory)
    assert (directory / "session.json").read_bytes() == session_bytes
    assert payload in (directory / "editor.html").read_text(encoding="utf-8")
    assert json.loads(payload)["session_id"] == session["session_id"]
    (directory / "first-pass").mkdir()
    with pytest.raises(ValueError, match="first-pass"):
        refresh_editor(directory)


def test_refresh_refuses_nonempty_page(tmp_path):
    directory, _, _ = setup_session(tmp_path)
    path = directory / "editor.html"
    html = path.read_text(encoding="utf-8")
    prefix = '<script id="blind-data" type="application/json">'
    payload = html.split(prefix)[1].split("</script>")[0]
    data = json.loads(payload)
    data["reference"]["sides"][0]["endpoints"] = [[10, 10], [20, 10]]
    path.write_text(html.replace(payload, json.dumps(data)), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="empty"):
        refresh_editor(directory)
    assert path.read_bytes() == before
