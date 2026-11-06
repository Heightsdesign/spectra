import json

import pytest
from PIL import Image

from spectra_scanner import cli, common
from spectra_scanner.common import AgentError
from spectra_scanner.config import load_config, region_inches, validate_config
from spectra_scanner.exports import FolderImporter
from spectra_scanner.storage import ArtifactStore, sha256_file


def test_default_config_is_manual_validated_profile_not_hardware_evidence():
    config = load_config(None)
    assert config["dpi"] == 600
    assert config["manual_profile"] == "SPECTRA_CARD_600DPI"
    assert config["scan_region"] is None
    assert config["preferred_format"] == "PNG"
    assert config["automatic_rotation"] is False


@pytest.mark.parametrize(
    "value",
    [
        {"dpi": float("nan")},
        {"dpi": True},
        {"enhancement": True},
        {"deskew": 0},
        {"unexpected": 1},
        {"expected_dimensions": [0, 20]},
        {"expected_dimensions": [True, 20]},
        {"safety_margin_mm": -1},
        {"scan_region": {"x": 1, "y": 2, "width": 0, "height": 3, "units": "mm"}},
        {"scan_region": {"x": 1, "y": 2, "width": 3, "height": 4, "units": "pixels"}},
    ],
)
def test_invalid_config_rejected(value):
    with pytest.raises(AgentError) as error:
        validate_config(value)
    assert error.value.status == "invalid_config"


def test_mm_conversion_does_not_discard_origin():
    assert region_inches(
        {"x": 25.4, "y": 50.8, "width": 76.2, "height": 101.6, "units": "mm"}
    ) == pytest.approx((1, 2, 4, 6))


@pytest.mark.parametrize(
    "mode,dpi,size,expected",
    [
        ("RGB", 600, (20, 30), "pending"),
        ("RGB", 300, (20, 30), "fail"),
        ("L", 600, (20, 30), "fail"),
        ("RGB", 600, (22, 30), "fail"),
    ],
)
def test_quality_evidence_and_unchanged_original(tmp_path, mode, dpi, size, expected):
    source = tmp_path / "source.png"
    image = Image.new(mode, size)
    image.putpixel((0, 0), (255, 255, 255) if mode == "RGB" else 255)
    image.save(source, dpi=(dpi, dpi))
    original_bytes = source.read_bytes()
    store = ArtifactStore(
        tmp_path / "output", {"expected_dimensions": [20, 30], "dimension_tolerance_pixels": 0}
    )
    result = store.commit(source, {"method": "epson_export_folder", "source_filename": source.name})
    metadata = json.loads((store.root / result["metadata"]).read_text(encoding="utf-8"))
    assert result["quality_control"]["status"] == expected
    assert metadata["quality_control"]["checks"]["physical_card_margin"]["status"] == "pending_s2_1"
    assert metadata["acquisition"]["device_reported"]["settings"] is None
    assert metadata["acquisition"]["acquired_at_utc"] is None
    assert metadata["acquisition"]["software"]["agent_version"] == "0.2.2"
    assert metadata["acquisition"]["user_configured"]["dpi"] == 600
    assert (store.root / result["original"]).read_bytes() == original_bytes
    assert sha256_file(source) == result["sha256"]
    assert metadata["pixel_transformations"] == []
    assert metadata["derived_images"] == []


def test_region_expected_dimensions_without_card_dimensions(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (600, 1200)).save(source)
    config = {"scan_region": {"x": 25.4, "y": 50.8, "width": 25.4, "height": 50.8, "units": "mm"}}
    result = ArtifactStore(tmp_path / "output", config).commit(source, {})
    checks = result["quality_control"]["checks"]
    assert checks["dimensions"]["expected"] == [600, 1200]
    assert checks["dimensions"]["status"] == "pass"
    assert checks["dpi"]["status"] == "pending"


def test_actual_export_pipeline_retains_profile_as_user_evidence_and_deduplicates(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    source = inbox / "manual.png"
    Image.new("RGB", (20, 30)).save(source, dpi=(600, 600))
    original = source.read_bytes()
    store = ArtifactStore(tmp_path / "output", {"expected_dimensions": [20, 30]})
    importer = FolderImporter(inbox, store, 1)
    assert importer.poll(0) == []
    result = importer.poll(1)[0]
    assert result["status"] == "stored"
    metadata = json.loads((store.root / result["metadata"]).read_text(encoding="utf-8"))
    assert metadata["acquisition"]["source_filename"] == "manual.png"
    assert metadata["acquisition"]["user_configured"]["manual_profile"] == "SPECTRA_CARD_600DPI"
    assert metadata["acquisition"]["device_reported"]["identity"] is None
    assert metadata["provenance"]["acquired_at_utc"] is None
    assert metadata["acquisition"]["observed_at_utc"]
    assert source.read_bytes() == original
    restarted = FolderImporter(inbox, store, 1)
    restarted.poll(10)
    assert restarted.poll(11)[0]["status"] == "duplicate"
    assert len(list(store.captures.iterdir())) == 1


def test_cli_config_reaches_worker_without_path_objects(tmp_path, monkeypatch):
    root = tmp_path / "local_data"
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"dpi": 600, "expected_dimensions": [20, 30]}), encoding="utf-8")
    monkeypatch.setattr(cli, "DATA_ROOT", root)
    monkeypatch.setattr(common, "DATA_ROOT", root)

    def supervised(job, timeout):
        assert job["configuration"]["dpi"] == 600
        assert job["configuration"]["expected_dimensions"] == [20, 30]
        json.dumps(job)
        return {"status": "discovered"}

    monkeypatch.setattr(cli, "supervise", supervised)
    assert cli.main(["discover", "--config", str(config)]) == 0


def test_invalid_config_is_machine_readable(tmp_path, monkeypatch):
    root = tmp_path / "local_data"
    config = tmp_path / "invalid.json"
    config.write_text('{"dpi": NaN}', encoding="utf-8")
    monkeypatch.setattr(cli, "DATA_ROOT", root)
    monkeypatch.setattr(common, "DATA_ROOT", root)
    assert cli.main(["discover", "--config", str(config)]) == 2
    report = json.loads(next(root.glob("reports/*.json")).read_text(encoding="utf-8"))
    assert report["status"] == "invalid_config"


def test_blank_image_is_preserved_but_fails_quality(tmp_path):
    source = tmp_path / "blank.png"
    Image.new("RGB", (20, 30), "white").save(source, dpi=(600, 600))
    result = ArtifactStore(tmp_path / "output").commit(source, {})
    assert result["status"] == "stored"
    assert result["quality_control"]["status"] == "fail"
    assert result["quality_control"]["checks"]["content_variation"]["status"] == "fail"


def test_watcher_reports_qc_failures_without_discarding_evidence(tmp_path, monkeypatch):
    from argparse import Namespace

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    Image.new("RGB", (20, 30), "white").save(inbox / "blank.png", dpi=(300, 300))
    clock = iter((0, 0, 0, 2, 2))
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    args = Namespace(
        inbox=inbox,
        stable_seconds=1,
        poll_seconds=1,
        once=True,
        duration=None,
        configuration=validate_config({}),
    )
    root = tmp_path / "output"
    report = cli.watch(args, root)
    assert report["status"] == "imported_with_qc_failures"
    assert report["counts"]["stored"] == 1
    assert report["counts"]["quality_failed"] == 1
    assert len(list(root.glob("captures/*/original.png"))) == 1
