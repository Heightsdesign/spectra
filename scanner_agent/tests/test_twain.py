import contextlib
import io
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from spectra_scanner.common import AgentError
from spectra_scanner.twain_driver import (
    CAPABILITIES,
    classify_error,
    configure_region,
    configure_test,
    epson_v39ii,
    normalize_capability,
    profile_matches,
    run_job,
    select_source,
)


class CapUnsupported(Exception):
    pass


class CancelAll(Exception):
    pass


def binding():
    values = {name: index + 100 for index, name in enumerate(CAPABILITIES)}
    values.update(
        TWUN_INCHES=0,
        TWPT_RGB=2,
        TWCP_NONE=0,
        TWSX_NATIVE=0,
        TWPC_CHUNKY=0,
        TWTY_UINT16=4,
        TWTY_FIX32=7,
        TWTY_BOOL=6,
        TWTY_INT16=1,
        TWAS_NONE=0,
        TWNF_NONE=0,
        TWIF_NONE=0,
        TWFT_NONE=3,
    )
    values["exceptions"] = SimpleNamespace(CancelAll=CancelAll)
    return SimpleNamespace(**values)


CONFIG = {"scan_region": {"x": 1, "y": 2, "width": 20 / 600, "height": 30 / 600, "units": "inches"}}


class FakeSource:
    identity = {"ProductName": "EPSON Perfection V39II", "Info": "SYNTHETIC TEST DRIVER"}

    def __init__(self, twain):
        self.twain = twain
        self.values = {twain.ICAP_PHYSICALWIDTH: 8.5, twain.ICAP_PHYSICALHEIGHT: 11.7}
        self.unsupported = set()
        self.legacy_depth = False
        self.clamped_resolution = False
        self.enabled_enhancement = False
        self.canceled = False
        self.wrong_actual_dpi = False
        self.ui_change = False
        self.ui_region_change = False
        self.quantize_gamma = False
        self.ui_gamma_change = False
        self.ui_gamma_unknown = False
        self.ui_contrast_change = False
        self.ui_contrast_unknown = False
        self.ui_brightness_change = False
        self.ui_brightness_unknown = False
        self.frame = (1.0, 2.0, 9.5, 13.7)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get_capability_current(self, cap):
        if cap in self.unsupported:
            raise CapUnsupported()
        return (4, self.values.get(cap, 0))

    get_capability = get_capability_current

    def set_capability(self, cap, kind, value):
        if cap in self.unsupported:
            raise CapUnsupported()
        if cap == self.twain.ICAP_BITDEPTH and self.legacy_depth and value == 24:
            raise ValueError("Legacy per-channel depth")
        if cap == self.twain.ICAP_XRESOLUTION and self.clamped_resolution:
            value = 300
        if cap == self.twain.ICAP_AUTOBRIGHT and self.enabled_enhancement:
            value = True
        if cap == self.twain.ICAP_GAMMA and self.quantize_gamma:
            value = int(value * 65536) / 65536
        self.values[cap] = value

    def set_image_layout(self, frame):
        self.frame = frame

    def get_image_layout(self):
        return self.frame, 1, 1, 1

    def get_image_layout_default(self):
        return (1.0, 2.0, 9.5, 13.7), 1, 1, 1

    def acquire_natively(self, *, before, after, show_ui, modal):
        if self.canceled:
            return
        dpi = 300 if self.wrong_actual_dpi else 600
        if self.ui_change:
            self.values[self.twain.ICAP_AUTOBRIGHT] = True
        if self.ui_region_change:
            self.frame = (0, 0, 1, 1)
        if self.ui_gamma_change:
            self.values[self.twain.ICAP_GAMMA] = 1.0
        if self.ui_gamma_unknown:
            self.unsupported.add(self.twain.ICAP_GAMMA)
        if self.ui_contrast_change:
            self.values[self.twain.ICAP_CONTRAST] = 0.0
        if self.ui_contrast_unknown:
            self.unsupported.add(self.twain.ICAP_CONTRAST)
        if self.ui_brightness_change:
            self.values[self.twain.ICAP_BRIGHTNESS] = 10.0
        if self.ui_brightness_unknown:
            self.unsupported.add(self.twain.ICAP_BRIGHTNESS)
        try:
            before(
                {
                    "PixelType": 2,
                    "BitsPerPixel": 24,
                    "SamplesPerPixel": 3,
                    "BitsPerSample": [8, 8, 8, 0, 0, 0, 0, 0],
                    "Compression": 0,
                    "XResolution": dpi,
                    "YResolution": dpi,
                    "ImageWidth": 20,
                    "ImageLength": 30,
                }
            )
        except CancelAll:
            return
        output = io.BytesIO()
        image = Image.new("RGB", (20, 30))
        image.putpixel((0, 0), (255, 255, 255))
        image.save(output, format="BMP", dpi=(dpi, dpi))

        class NativeImage:
            def save(self, path):
                from pathlib import Path

                with Path(path).open("xb") as destination:
                    destination.write(output.getvalue())

        after(NativeImage(), 0)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("EPSON Perfection V39II", True),
        ("EPSON V39 II", True),
        ("epson v39-2", True),
        ("EPSON Perfection V39", False),
        ("EPSON Perfection V39III", False),
        ("EPSON Perfection V39II (USB)", True),
        ("Other scanner V39II", False),
    ],
)
def test_target_identity_matching(name, expected):
    assert epson_v39ii(name) is expected


def test_source_selection_is_unambiguous_and_exact():
    names = ["Other scanner", "EPSON Perfection V39II"]
    assert select_source(names, None) == names[1]
    assert select_source(names, names[0]) == names[0]
    with pytest.raises(AgentError):
        select_source(["EPSON Perfection V39"], None)
    with pytest.raises(AgentError):
        select_source([names[1], "EPSON V39II duplicate"], None)
    with pytest.raises(AgentError):
        select_source(names, "unlisted")


def test_capability_containers_including_packed_fixed_resolution():
    assert normalize_capability((4, 1200))["current"] == 1200
    assert normalize_capability((4, (1, 0, [300, 1200])))["current"] == 1200
    assert normalize_capability((4, [1, 2, 8]))["values"] == [1, 2, 8]
    assert (
        normalize_capability({"MinValue": 50, "MaxValue": 1200, "CurrentValue": 1200}, fixed=True)[
            "current"
        ]
        == 1200
    )
    assert normalize_capability({"CurrentValue": (32768 << 16) | 1}, fixed=True)["current"] == 1.5


@pytest.mark.parametrize("legacy", [False, True])
def test_verified_profile_and_legacy_rgb_depth(legacy):
    twain = binding()
    source = FakeSource(twain)
    source.legacy_depth = legacy
    report = {}
    configure_test(source, twain, report, True, CONFIG)
    assert report["settings"]["ICAP_XRESOLUTION"]["verified"]
    assert report["settings"]["ICAP_YRESOLUTION"]["verified"]
    assert report["settings"]["ICAP_BITDEPTH"]["requested"] == (8 if legacy else 24)
    assert report["settings"]["ICAP_AUTOMATICBORDERDETECTION"]["requested"] is False
    assert report["scan_region"]["verified"] is True
    assert report["vendor_specific_enhancements_verified"] is False


def test_clamped_resolution_and_known_active_enhancement_block_scan():
    for attribute in ("clamped_resolution", "enabled_enhancement"):
        twain = binding()
        source = FakeSource(twain)
        setattr(source, attribute, True)
        with pytest.raises(AgentError):
            configure_test(source, twain, {}, False, CONFIG)


def test_unsupported_options_are_reported_and_strict_mode_stops():
    twain = binding()
    source = FakeSource(twain)
    source.unsupported.add(twain.ICAP_AUTOMATICDESKEW)
    report = {}
    configure_test(source, twain, report, False, CONFIG)
    assert "ICAP_AUTOMATICDESKEW" in report["unverified_options"]
    with pytest.raises(AgentError):
        configure_test(source, twain, {}, True, CONFIG)


@pytest.mark.parametrize(
    "name,status",
    [
        ("DSTransferCancelled", "canceled"),
        ("MaxConnectionsError", "busy"),
        ("CheckDeviceOnlineError", "device_absent"),
        ("SMLoadFileFailed", "twain_unavailable"),
        ("CapUnsupported", "unsupported_option"),
        ("OperationError", "driver_error"),
    ],
)
def test_driver_failure_classification(name, status):
    assert classify_error(type(name, (Exception,), {})()) == status


@pytest.mark.skipif(sys.platform != "win32", reason="Windows TWAIN worker entrypoint")
@pytest.mark.parametrize(
    "operation,expected",
    [
        ("discover", "discovered"),
        ("acquire", "acquired"),
        ("canceled", "canceled"),
        ("mismatch", "profile_mismatch"),
        ("ui_change", "unsupported_option"),
        ("ui_region_change", "unsupported_option"),
        ("gamma22", "acquired"),
        ("ui_gamma_change", "unsupported_option"),
        ("ui_gamma_unknown", "unsupported_option"),
        ("contrast_minus50", "acquired"),
        ("contrast_minus100", "acquired"),
        ("ui_contrast_change", "unsupported_option"),
        ("ui_contrast_unknown", "unsupported_option"),
        ("ui_brightness_change", "unsupported_option"),
        ("ui_brightness_unknown", "unsupported_option"),
    ],
)
def test_adapter_uses_property_enumeration_and_preserves_transferred_original(
    tmp_path, monkeypatch, operation, expected
):
    from spectra_scanner import windows

    twain = binding()
    source = FakeSource(twain)
    source.canceled = operation == "canceled"
    source.wrong_actual_dpi = operation == "mismatch"
    source.ui_change = operation == "ui_change"
    source.ui_region_change = operation == "ui_region_change"
    source.quantize_gamma = operation == "gamma22"
    source.ui_gamma_change = operation == "ui_gamma_change"
    source.ui_gamma_unknown = operation == "ui_gamma_unknown"
    source.ui_contrast_change = operation == "ui_contrast_change"
    source.ui_contrast_unknown = operation == "ui_contrast_unknown"
    source.ui_brightness_change = operation == "ui_brightness_change"
    source.ui_brightness_unknown = operation == "ui_brightness_unknown"

    class Manager:
        source_list = [
            "EPSON Perfection V39II"
        ]  # The pinned library exposes a property, not a method.

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def open_source(self, name):
            return source

    twain.SourceManager = lambda *args, **kwargs: Manager()
    monkeypatch.setitem(sys.modules, "twain", twain)
    monkeypatch.setattr(windows, "hidden_window", lambda: contextlib.nullcontext(123))
    monkeypatch.setattr("spectra_scanner.twain_driver.dsm_path", lambda _: tmp_path / "fake.dll")
    report = {"physical_scan_performed": False}
    run_job(
        {
            "operation": "discover" if operation == "discover" else "acquire",
            "data_dir": str(tmp_path),
            "configuration": {
                **CONFIG,
                "contrast": -100
                if operation == "contrast_minus100"
                else -50
                if "contrast" in operation
                else 0,
                "gamma": 2.2
                if operation in {"gamma22", "ui_gamma_change", "ui_gamma_unknown"}
                or "contrast" in operation
                else 1.0,
            },
        },
        report,
    )
    assert report["status"] == expected
    if expected in {"acquired", "profile_mismatch"}:
        assert len(report["captures"]) == 1
        assert report["image_profile_verified"] is (expected == "acquired")
        if operation == "gamma22":
            import json

            metadata = json.loads(
                (tmp_path / report["captures"][0]["metadata"]).read_text(encoding="utf-8")
            )
            assert metadata["acquisition"]["user_configured"]["gamma"] == 2.2
            assert metadata["provenance"]["capture_settings"]["ICAP_GAMMA"]["verified"] is True
            assert (
                metadata["provenance"]["transfer_time_settings"]["ICAP_GAMMA"]["current"]
                == 2.1999969482421875
            )
        if operation.startswith("contrast_minus"):
            import json

            metadata = json.loads(
                (tmp_path / report["captures"][0]["metadata"]).read_text(encoding="utf-8")
            )
            expected_contrast = -100 if operation == "contrast_minus100" else -50
            assert metadata["acquisition"]["user_configured"]["contrast"] == expected_contrast
            assert metadata["acquisition"]["user_configured"]["gamma"] == 2.2
            assert metadata["provenance"]["capture_settings"]["ICAP_CONTRAST"]["verified"] is True
            assert (
                metadata["acquisition"]["device_reported"]["settings"]["ICAP_CONTRAST"]["current"]
                == expected_contrast
            )
    else:
        assert not report.get("captures")


def test_image_profile_requires_actual_24_bit_600_rgb():
    info = {
        "PixelType": 2,
        "BitsPerPixel": 24,
        "SamplesPerPixel": 3,
        "BitsPerSample": [8, 8, 8],
        "XResolution": 600,
        "YResolution": 600,
        "ImageWidth": 20,
        "ImageLength": 30,
        "Compression": 0,
    }
    image = {
        "frame_count": 1,
        "frames": [{"mode": "RGB", "width": 20, "height": 30, "bits_per_pixel": 24}],
    }
    assert profile_matches(info, image)
    assert not profile_matches({**info, "BitsPerPixel": 48}, image)
    assert not profile_matches({**info, "XResolution": 300}, image)


@pytest.mark.parametrize(
    "region",
    [
        None,
        {"x": 0, "y": 0, "width": 1, "height": 1, "units": "inches"},
        {"x": 1, "y": 2, "width": 20, "height": 1, "units": "inches"},
    ],
)
def test_missing_or_out_of_driver_frame_region_requires_fallback(region):
    from spectra_scanner.config import validate_config

    source = FakeSource(binding())
    with pytest.raises(AgentError) as error:
        configure_region(source, validate_config({"scan_region": region}), {})
    assert error.value.status == "fallback_required"


@pytest.mark.parametrize("failure", ["adjusted", "unsupported", "invalid_bounds"])
def test_region_must_have_valid_driver_domain_and_exact_readback(failure):
    from spectra_scanner.config import validate_config

    source = FakeSource(binding())
    if failure == "adjusted":
        source.set_image_layout = lambda frame: setattr(source, "frame", (0, 0, 1, 1))
    elif failure == "unsupported":

        def unsupported():
            raise CapUnsupported()

        source.get_image_layout_default = unsupported
    else:
        source.get_image_layout_default = lambda: ((float("nan"), 0, 1, 1), 1, 1, 1)
    report = {}
    with pytest.raises(AgentError) as error:
        configure_region(source, validate_config(CONFIG), report)
    assert error.value.status == "fallback_required"
    assert report["scan_region"]["verified"] is False


def test_region_setting_that_resets_resolution_is_detected():
    twain = binding()
    source = FakeSource(twain)

    def reset(frame):
        source.frame = frame
        source.values[twain.ICAP_XRESOLUTION] = 300

    source.set_image_layout = reset
    with pytest.raises(AgentError) as error:
        configure_test(source, twain, {}, False, CONFIG)
    assert error.value.status == "unsupported_option"
