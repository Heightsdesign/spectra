import json
from pathlib import Path

import pytest
from PIL import Image
from test_twain import CONFIG, FakeSource, binding

from spectra_scanner.common import AgentError
from spectra_scanner.comparison import channel_statistics, compare
from spectra_scanner.config import validate_config
from spectra_scanner.twain_driver import capability_matches, configure_test


@pytest.mark.parametrize("contrast", [True, -1001, 1001, "-50", float("inf"), float("nan")])
def test_invalid_contrast_rejected(contrast):
    with pytest.raises(AgentError):
        validate_config({"contrast": contrast})


def test_contrast_experiments_only_vary_contrast():
    folder = Path(__file__).resolve().parents[1] / "experiments" / "contrast"
    configs = [
        validate_config(
            json.loads((folder / f"acquisition.contrast-{name}.json").read_text(encoding="utf-8"))
        )
        for name in ("0", "minus50", "minus100")
    ]
    assert [c["contrast"] for c in configs] == [0, -50, -100]
    assert all(c["gamma"] == 2.2 and c["dpi"] == 600 and c["bits_per_pixel"] == 24 for c in configs)
    assert all(
        [k for k in configs[0] if configs[0][k] != other[k]] == ["contrast"]
        for other in configs[1:]
    )


@pytest.mark.parametrize("contrast", [0, -50, -100])
def test_contrast_configuration_and_readbacks(contrast):
    twain = binding()
    source = FakeSource(twain)
    source.quantize_gamma = True
    report = {}
    configure_test(source, twain, report, False, {**CONFIG, "gamma": 2.2, "contrast": contrast})
    assert report["settings"]["ICAP_CONTRAST"]["requested"] == contrast
    assert report["settings"]["ICAP_CONTRAST"]["final_readback"]["current"] == contrast
    assert report["settings"]["ICAP_CONTRAST"]["verified"]
    assert report["settings"]["ICAP_BRIGHTNESS"]["final_readback"]["current"] == 0


@pytest.mark.parametrize("name", ["ICAP_CONTRAST", "ICAP_BRIGHTNESS"])
def test_required_tonal_controls_fail_closed_if_missing(name):
    twain = binding()
    source = FakeSource(twain)
    source.unsupported.add(getattr(twain, name))
    with pytest.raises(AgentError):
        configure_test(source, twain, {}, False, {**CONFIG, "contrast": -50})


def test_adjusted_contrast_is_not_silently_accepted():
    twain = binding()
    source = FakeSource(twain)
    original = source.set_capability

    def clamped(cap, kind, value):
        original(cap, kind, -49.9 if cap == twain.ICAP_CONTRAST else value)

    source.set_capability = clamped
    with pytest.raises(AgentError):
        configure_test(source, twain, {}, False, {**CONFIG, "contrast": -50})
    assert capability_matches("ICAP_CONTRAST", -50 + 1 / 65536, -50)
    assert not capability_matches("ICAP_CONTRAST", -49.999, -50)
    assert not capability_matches("ICAP_BRIGHTNESS", 0.001, 0)


def test_tonal_bands_and_spreads_known_histogram():
    hist = [0] * 256
    for value in (0, 63, 64, 128, 191, 192, 255):
        hist[value] = 1
    stats = channel_statistics(hist)
    assert stats["tonal_fractions"] == {
        "shadows_0_63": 2 / 7,
        "midtones_64_191": 3 / 7,
        "highlights_192_255": 2 / 7,
    }
    assert stats["percentile_spread_p95_p5"] == 255
    assert stats["interquartile_range"] == 129
    assert stats["fraction_at_0"] == stats["fraction_at_255"] == 1 / 7


def test_distribution_contraction_and_brightness_shift_are_distinct(tmp_path):
    a, b, shifted = (tmp_path / name for name in ("a.bmp", "b.bmp", "shifted.bmp"))
    for path, values in (
        (a, (0, 64, 128, 255)),
        (b, (32, 80, 128, 224)),
        (shifted, (10, 74, 138, 255)),
    ):
        image = Image.new("RGB", (4, 1))
        image.putdata([(value, value, value) for value in values])
        image.save(path)
    rois = {
        "white_background": {"a": [0, 0, 4, 1], "b": [0, 0, 4, 1]},
        "card": {"a": [0, 0, 4, 1], "b": [0, 0, 4, 1]},
    }
    result = compare(a, b, rois)["regions"]["card"]
    delta = result["distribution_deltas_b_minus_a"]["R"]
    assert delta["percentile_spread_p95_p5"] == -63
    assert delta["fraction_at_0"] == delta["fraction_at_255"] == -0.25
    assert result["channel_balance"]["a"]["mean_r_minus_g"] == 0
    assert compare(a, shifted, rois)["regions"]["card"]["mean_rgb_delta_b_minus_a"]["R"] > 0
