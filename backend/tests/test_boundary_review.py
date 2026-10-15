import json
import io
from uuid import UUID, uuid4

import cv2
import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.main import app
from app.models import CardImage


HEADERS = {"X-Spectra-Review": "1"}
BASE = "/internal/boundary"


@pytest.fixture
def review_api(api, tmp_path):
    _, session, settings = api
    settings.boundary_review_enabled = True
    settings.boundary_output_dir = tmp_path / "diagnostics"
    settings.max_image_size_bytes = 2_000_000
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        card = client.post("/api/cards", json={"card_name": "Test", "set_name": "Validation", "collector_number": "1"}).json()
        image = np.full((760, 760, 3), 35, np.uint8)
        rng = np.random.default_rng(42)
        image[160:513, 240:493] = rng.integers(180, 235, (353, 253, 3), dtype=np.uint8)
        ok, encoded = cv2.imencode(".png", image)
        assert ok
        source = encoded.tobytes()
        uploaded = client.post(f"/api/cards/{card['id']}/images", data={"side": "front"}, files={"file": ("photo.png", source, "image/png")})
        assert uploaded.status_code == 201
        image_id = uploaded.json()["id"]
        yield client, settings, session, image_id, source


def analyze(fixture):
    client, _, _, image_id, _ = fixture
    response = client.post(f"{BASE}/images/{image_id}/analyses", headers=HEADERS)
    assert response.status_code == 201, response.text
    return response.json()


def test_analysis_diagnostics_and_original_preservation(review_api):
    client, settings, session, image_id, source = review_api
    original = session.get(CardImage, UUID(image_id))
    path = settings.card_image_dir / original.storage_key
    before = path.stat().st_mtime_ns
    first, second = analyze(review_api), analyze(review_api)
    assert first["run_id"] != second["run_id"]
    assert first["result"]["status"] == "detected"
    assert first["result"]["corners"]
    assert first["result"]["metrics"]
    assert first["result"]["warnings"]
    assert first["source_sha256"] == original.sha256
    assert "storage_key" not in json.dumps(first)
    assert str(settings.card_image_dir) not in json.dumps(first)
    for name, url in first["images"].items():
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "no-store"
        decoded = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
        assert decoded is not None
        if name == "normalized":
            assert decoded.shape == (880, 630, 3)
    assert path.read_bytes() == source
    assert path.stat().st_mtime_ns == before
    assert len(client.get(BASE + "/runs").json()) == 2
    assert client.get(f"{BASE}/runs/{first['run_id']}").json() == first
    page = client.get(BASE + "/review")
    assert page.status_code == 200
    assert "Reviewer assessment" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


def test_review_history_survives_new_client(review_api):
    client, settings, _, _, _ = review_api
    run = analyze(review_api)
    url = f"{BASE}/runs/{run['run_id']}/reviews"
    for label in ("correct", "incorrect", "uncertain"):
        response = client.post(url, headers=HEADERS, json={"label": label, "notes": "Physical edge <script>alert(1)</script>"})
        assert response.status_code == 201
        record = response.json()
        assert record["source_sha256"] == run["source_sha256"]
        assert record["image_id"] == run["image_id"]
        assert record["analysis_reference"] == UUID(run["run_id"]).hex + "/result.json"
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50100)) as other:
        saved = other.get(f"{BASE}/runs/{run['run_id']}").json()["reviews"]
    assert [item["label"] for item in saved] == ["correct", "incorrect", "uncertain"]
    files = list((settings.boundary_output_dir / UUID(run["run_id"]).hex).glob("review-*.json"))
    assert len(files) == 3
    assert {json.loads(path.read_text())["review_id"] for path in files} == {item["review_id"] for item in saved}


@pytest.mark.parametrize("payload", [{"label": "approved"}, {"label": "correct", "path": "C:/secret"}, {"label": "correct", "notes": "x" * 4001}])
def test_invalid_review_payload(review_api, payload):
    run = analyze(review_api)
    assert review_api[0].post(f"{BASE}/runs/{run['run_id']}/reviews", headers=HEADERS, json=payload).status_code == 422


@pytest.mark.parametrize("identifier,status", [("not-a-uuid", 422), (str(uuid4()), 404)])
def test_invalid_identifiers(review_api, identifier, status):
    client = review_api[0]
    assert client.post(f"{BASE}/images/{identifier}/analyses", headers=HEADERS).status_code == status
    assert client.get(f"{BASE}/images/{identifier}/preview").status_code == status
    assert client.get(f"{BASE}/runs/{identifier}").status_code == status
    assert client.get(f"{BASE}/runs/{identifier}/diagnostics/overlay").status_code == status
    assert client.post(f"{BASE}/runs/{identifier}/reviews", headers=HEADERS, json={"label": "correct"}).status_code == status


def test_access_guards(review_api):
    client, settings, _, image_id, _ = review_api
    url = f"{BASE}/images/{image_id}/analyses"
    assert client.post(url).status_code == 403
    assert client.post(url, headers={**HEADERS, "Origin": "https://evil.example"}).status_code == 403
    assert client.get(BASE + "/review", headers={"Host": "evil.example"}).status_code == 403
    with TestClient(app, base_url="http://localhost", client=("192.0.2.5", 50000)) as remote:
        assert remote.get(BASE + "/runs").status_code == 403
    settings.boundary_review_enabled = False
    for url in (BASE + "/review", BASE + "/runs", f"{BASE}/images/{image_id}/preview"):
        assert client.get(url).status_code == 404
    assert client.post(f"{BASE}/images/{image_id}/analyses", headers=HEADERS).status_code == 404


def test_only_allowlisted_diagnostics_are_served(review_api):
    client = review_api[0]
    run = analyze(review_api)
    for name in ("result.json", "original", "review", "C:%5Csecret", "%2e%2e%5Cresult.json"):
        assert client.get(f"{BASE}/runs/{run['run_id']}/diagnostics/{name}").status_code == 422
    assert client.get(f"{BASE}/runs/{run['run_id']}/diagnostics/%2e%2e%2fresult.json").status_code == 404
    assert client.get("/data/card_images/anything").status_code == 404


def test_corrupt_original_rejection_and_missing_diagnostics(review_api):
    client, settings, session, image_id, _ = review_api
    original = session.get(CardImage, UUID(image_id))
    (settings.card_image_dir / original.storage_key).write_bytes(b"corrupted")
    run = analyze(review_api)
    assert run["result"]["failure_reason"] == "original_integrity_mismatch"
    assert "normalized" not in run["images"]
    assert client.get(f"{BASE}/runs/{run['run_id']}/diagnostics/normalized").status_code == 404
    assert client.get(run["images"]["original"]).status_code == 409
    assert client.post(f"{BASE}/runs/{run['run_id']}/reviews", headers=HEADERS, json={"label": "uncertain"}).status_code == 201


def test_storage_overlap_is_rejected(review_api):
    client, settings, _, image_id, _ = review_api
    settings.boundary_output_dir = settings.card_image_dir / "diagnostics"
    assert client.post(f"{BASE}/images/{image_id}/analyses", headers=HEADERS).status_code == 503
    assert client.get(f"{BASE}/images/{image_id}/preview").status_code == 503


def test_generated_storage_key_cannot_escape(review_api):
    client, _, session, image_id, _ = review_api
    original = session.get(CardImage, UUID(image_id))
    original.storage_key = "../secret"
    assert client.get(f"{BASE}/images/{image_id}/preview").status_code == 404
    assert client.post(f"{BASE}/images/{image_id}/analyses", headers=HEADERS).status_code == 503


def test_diagnostic_symlink_cannot_escape(review_api, tmp_path):
    client, settings, _, _, _ = review_api
    run = analyze(review_api)
    path = settings.boundary_output_dir / UUID(run["run_id"]).hex / "overlay.png"
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    path.unlink()
    try:
        path.symlink_to(secret)
    except OSError:
        # Windows may prohibit symlink creation; test the same containment guard
        # without requiring elevated filesystem privileges.
        from pathlib import Path
        from unittest.mock import patch
        original = Path.is_symlink
        with patch.object(Path, "is_symlink", lambda value: value == path or original(value)):
            assert client.get(f"{BASE}/runs/{run['run_id']}/diagnostics/overlay").status_code == 404
    else:
        assert client.get(f"{BASE}/runs/{run['run_id']}/diagnostics/overlay").status_code == 404


def test_analysis_io_failure_is_safe(review_api, monkeypatch):
    def fail(*args):
        raise OSError("secret filesystem path")
    monkeypatch.setattr("app.boundary_review.analyze_original", fail)
    response = review_api[0].post(f"{BASE}/images/{review_api[3]}/analyses", headers=HEADERS)
    assert response.status_code == 503
    assert "secret" not in response.text


@pytest.mark.parametrize("format", ["PNG", "JPEG", "TIFF"])
def test_preview_formats_and_rejected_analysis(review_api, format):
    client, _, _, _, _ = review_api
    buffer = io.BytesIO()
    Image.new("RGB", (100, 100), "gray").save(buffer, format=format)
    card = client.post("/api/cards", json={"card_name": "Negative", "set_name": "Validation", "collector_number": "2"}).json()
    response = client.post(f"/api/cards/{card['id']}/images", data={"side": "front"}, files={"file": ("negative." + format.lower(), buffer.getvalue(), "application/octet-stream")})
    assert response.status_code == 201
    image_id = response.json()["id"]
    preview = client.get(f"{BASE}/images/{image_id}/preview")
    assert preview.status_code == 200
    assert cv2.imdecode(np.frombuffer(preview.content, np.uint8), cv2.IMREAD_COLOR).shape == (100, 100, 3)
    run = client.post(f"{BASE}/images/{image_id}/analyses", headers=HEADERS).json()
    assert run["result"]["status"] == "rejected"
    assert run["result"]["failure_reason"] == "no_card_outline"
    assert "normalized" not in run["images"]


def test_review_write_failure_leaves_no_partial_review(review_api, monkeypatch):
    client, settings, _, _, _ = review_api
    run = analyze(review_api)
    def fail(*args):
        raise OSError("private path")
    monkeypatch.setattr("app.boundary_review.os.fsync", fail)
    response = client.post(f"{BASE}/runs/{run['run_id']}/reviews", headers=HEADERS, json={"label": "correct"})
    assert response.status_code == 503
    assert "private" not in response.text
    directory = settings.boundary_output_dir / UUID(run["run_id"]).hex
    assert not list(directory.glob("review-*"))
    assert client.get(f"{BASE}/runs/{run['run_id']}").json()["reviews"] == []


def test_analysis_rejects_client_paths(review_api):
    client, settings, _, image_id, _ = review_api
    response = client.post(f"{BASE}/images/{image_id}/analyses", headers=HEADERS, json={"path": "C:/secret.png"})
    assert response.status_code == 422
    assert not settings.boundary_output_dir.exists()


def test_run_directory_symlink_is_rejected(review_api, monkeypatch):
    client, settings, _, _, _ = review_api
    run = analyze(review_api)
    directory = settings.boundary_output_dir / UUID(run["run_id"]).hex
    from pathlib import Path
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda value: value == directory or original(value))
    assert client.get(f"{BASE}/runs/{run['run_id']}").status_code == 404
    assert client.post(f"{BASE}/runs/{run['run_id']}/reviews", headers=HEADERS, json={"label": "correct"}).status_code == 404


def test_workflow_defaults_to_disabled():
    from app.config import Settings
    assert Settings.model_fields["boundary_review_enabled"].default is False
