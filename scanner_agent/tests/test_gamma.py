import json
from pathlib import Path

import pytest
from PIL import Image
from test_twain import CONFIG, FakeSource, binding

from spectra_scanner.common import AgentError
from spectra_scanner.comparison import channel_statistics, compare, main
from spectra_scanner.config import validate_config
from spectra_scanner.storage import sha256_file
from spectra_scanner.twain_driver import capability_matches, configure_test


@pytest.mark.parametrize("gamma", [True, 0, 0.49, 3.01, "2.2", float("nan"), float("inf")])
def test_invalid_gamma_rejected(gamma):
    with pytest.raises(AgentError):
        validate_config({"gamma": gamma})


def test_gamma_quantization_does_not_accept_another_curve():
    assert capability_matches("ICAP_GAMMA", 2.1999969482421875, 2.2)
    assert not capability_matches("ICAP_GAMMA", 2.19, 2.2)
    assert not capability_matches("ICAP_GAMMA", 1.0, 2.2)
    assert not capability_matches("ICAP_GAMMA", None, 2.2)
    assert not capability_matches("ICAP_XRESOLUTION", 599.99999, 600)


def test_gamma_must_be_read_back_even_without_strict_mode():
    twain = binding()
    source = FakeSource(twain)
    source.unsupported.add(twain.ICAP_GAMMA)
    with pytest.raises(AgentError):
        configure_test(source, twain, {}, False, CONFIG)


def test_experiment_configurations_differ_only_in_gamma():
    folder = Path(__file__).resolve().parents[1] / "experiments" / "gamma"
    a, b = [
        validate_config(
            json.loads((folder / f"acquisition.gamma-{g}.json").read_text(encoding="utf-8"))
        )
        for g in ("1.0", "2.2")
    ]
    assert [key for key in a if a[key] != b[key]] == ["gamma"]
    assert a["dpi"] == b["dpi"] == 600


def images(tmp_path):
    a, b = tmp_path / "a.bmp", tmp_path / "b.png"
    Image.new("RGB", (4, 6), (64, 128, 255)).save(a, dpi=(600, 600))
    Image.new("RGB", (4, 6), (128, 192, 255)).save(b, dpi=(600, 600))
    rois = {
        "white_background": {"a": [0, 0, 2, 2], "b": [0, 0, 2, 2]},
        "card": {"a": [1, 2, 4, 6], "b": [1, 2, 4, 6]},
    }
    return a, b, rois


def test_comparison_histograms_distributions_white_card_and_exact_sources(tmp_path):
    a, b, rois = images(tmp_path)
    hashes = [sha256_file(a), sha256_file(b)]
    report = compare(a, b, rois)
    assert report["regions"]["whole_image"]["a"]["R"]["histogram_256"][64] == 24
    assert report["regions"]["white_background"]["a"]["G"]["mean"] == 128
    assert report["regions"]["card"]["mean_rgb_delta_b_minus_a"] == {"R": 64, "G": 64, "B": 0}
    assert report["regions"]["card"]["a"]["B"]["fraction_at_255"] == 1
    assert report["regions"]["card"]["a"]["R"]["percentiles"]["50"] == 64
    assert report["alignment_verified"] is False
    assert report["colorimetric_accuracy_verified"] is False
    assert [sha256_file(a), sha256_file(b)] == hashes


@pytest.mark.parametrize("box", [[-1, 0, 2, 2], [0, 0, 5, 2], [0, 0, 0, 2], [0.1, 0, 2, 2]])
def test_invalid_rois_rejected(tmp_path, box):
    a, b, rois = images(tmp_path)
    rois["card"]["a"] = box
    with pytest.raises(AgentError):
        compare(a, b, rois)


def test_manifest_hash_mismatch_rejected(tmp_path):
    a, b, rois = images(tmp_path)
    (tmp_path / "metadata.json").write_text(
        json.dumps({"original": a.name, "sha256": "wrong", "complete": True}), encoding="utf-8"
    )
    with pytest.raises(AgentError, match="manifest"):
        compare(a, b, rois)


def test_histogram_statistics_known_distribution():
    h = [0] * 256
    h[0] = h[255] = 2
    stats = channel_statistics(h)
    assert stats["mean"] == stats["stddev"] == 127.5
    assert stats["percentiles"]["50"] == 0
    assert stats["fraction_at_0"] == 0.5


def test_comparison_cli_exclusive_output_and_no_scanner_access(tmp_path, monkeypatch):
    from spectra_scanner import common

    a, b, rois = images(tmp_path)
    roi_path = tmp_path / "rois.json"
    roi_path.write_text(json.dumps(rois), encoding="utf-8")
    monkeypatch.setattr(common, "DATA_ROOT", tmp_path)
    output = tmp_path / "comparison.json"
    args = ["--a", str(a), "--b", str(b), "--rois", str(roi_path), "--output", str(output)]
    assert main(args) == 0
    previous = output.read_bytes()
    assert main(args) == 2
    assert output.read_bytes() == previous
