import hashlib
import io
import json

import pytest
from PIL import Image

from spectra_scanner.common import AgentError, write_json_new
from spectra_scanner.storage import ArtifactStore, inspect_image, sha256_file


def image_bytes(fmt="PNG", **kwargs):
    output = io.BytesIO()
    Image.new("RGB", (20, 30), (17, 88, 201)).save(output, format=fmt, **kwargs)
    return output.getvalue()


@pytest.mark.parametrize("fmt", ["PNG", "BMP", "TIFF"])
def test_original_bytes_and_metadata_preserved(tmp_path, fmt):
    data = image_bytes(fmt, dpi=(1200, 1200))
    source = tmp_path / "snapshot"
    source.write_bytes(data)
    store = ArtifactStore(tmp_path / "artifacts")
    result = store.commit(source, {"acquired_at_utc": "2026-10-17T10:00:00+00:00"})
    original = store.root / result["original"]
    metadata = json.loads((store.root / result["metadata"]).read_text())
    assert original.read_bytes() == data
    assert result["sha256"] == hashlib.sha256(data).hexdigest() == sha256_file(original)
    assert metadata["image"]["frames"][0]["width"] == 20
    assert metadata["image"]["frames"][0]["height"] == 30
    assert metadata["image"]["frames"][0]["mode"] == "RGB"
    assert metadata["image"]["frames"][0]["dpi_metadata"][0] == pytest.approx(1200, abs=1)
    assert metadata["pixel_transformations"] == []
    assert metadata["calibration_verified"] is False
    assert metadata["storage_namespace"] == "S1_local_test"
    assert metadata["production_card_association"] is None


def test_capture_collision_never_overwrites(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.write_bytes(image_bytes())
    store = ArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr("spectra_scanner.storage.identifier", lambda: "same-id")
    first = store.commit(source, {})
    original = (store.root / first["original"]).read_bytes()
    with pytest.raises(FileExistsError):
        store.commit(source, {})
    assert (store.root / first["original"]).read_bytes() == original


def test_deduplication_survives_restart_and_detects_tampering(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(image_bytes())
    root = tmp_path / "artifacts"
    first = ArtifactStore(root).commit(source, {}, deduplicate=True)
    second = ArtifactStore(root).commit(source, {}, deduplicate=True)
    assert second["status"] == "duplicate"
    assert first["capture_id"] == second["capture_id"]
    (root / first["original"]).write_bytes(b"tampered outside the agent")
    with pytest.raises(AgentError, match="SHA-256"):
        ArtifactStore(root).commit(source, {}, deduplicate=True)


@pytest.mark.parametrize("data", [b"", b"not an image", image_bytes("JPEG"), image_bytes()[:30]])
def test_invalid_or_lossy_original_rejected(tmp_path, data):
    source = tmp_path / "invalid"
    source.write_bytes(data)
    store = ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(AgentError):
        store.commit(source, {})
    assert list(store.captures.iterdir()) == []


def test_lossy_tiff_not_misrepresented_as_lossless(tmp_path):
    source = tmp_path / "source.tiff"
    source.write_bytes(image_bytes("TIFF", compression="jpeg"))
    with pytest.raises(AgentError, match="compression"):
        inspect_image(source)


def test_tiff_orientation_preserves_encoded_geometry_and_original(tmp_path):
    data = image_bytes("TIFF", tiffinfo={274: 6})
    source = tmp_path / "oriented.tiff"
    source.write_bytes(data)
    store = ArtifactStore(tmp_path / "artifacts")
    result = store.commit(source, {})
    frame = result["image"]["frames"][0]
    assert (frame["width"], frame["height"]) == (20, 30)
    assert frame["orientation_tag"] == 6
    assert (store.root / result["original"]).read_bytes() == data


def test_manifest_committed_last_and_never_overwritten(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.write_bytes(image_bytes())
    store = ArtifactStore(tmp_path / "artifacts")

    def fail(*args):
        raise OSError("synthetic storage failure")

    monkeypatch.setattr("spectra_scanner.storage.write_json_new", fail)
    with pytest.raises(OSError):
        store.commit(source, {})
    directory = next(store.captures.iterdir())
    assert (directory / "original.png").read_bytes() == source.read_bytes()
    assert not (directory / "metadata.json").exists()
    report = tmp_path / "report.json"
    write_json_new(report, {"complete": True})
    with pytest.raises(FileExistsError):
        write_json_new(report, {"complete": False})
    assert json.loads(report.read_text())["complete"] is True
