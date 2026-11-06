"""pytwain 2.3 adapter. Import/load native libraries only in the supervised worker."""

from __future__ import annotations

import os
import re
import struct
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .common import AgentError, json_safe, utc_now
from .config import region_inches, validate_config
from .storage import ArtifactStore

CAPABILITIES = (
    "CAP_SUPPORTEDCAPS",
    "CAP_SERIALNUMBER",
    "CAP_DEVICEONLINE",
    "CAP_UICONTROLLABLE",
    "CAP_FEEDERENABLED",
    "CAP_XFERCOUNT",
    "CAP_INDICATORS",
    "ICAP_UNITS",
    "ICAP_XRESOLUTION",
    "ICAP_YRESOLUTION",
    "ICAP_PHYSICALWIDTH",
    "ICAP_PHYSICALHEIGHT",
    "ICAP_SUPPORTEDSIZES",
    "ICAP_FRAMES",
    "ICAP_PIXELTYPE",
    "ICAP_BITDEPTH",
    "ICAP_PLANARCHUNKY",
    "ICAP_PIXELFLAVOR",
    "ICAP_BITORDER",
    "ICAP_COMPRESSION",
    "ICAP_XFERMECH",
    "ICAP_IMAGEFILEFORMAT",
    "ICAP_AUTOBRIGHT",
    "ICAP_BRIGHTNESS",
    "ICAP_CONTRAST",
    "ICAP_GAMMA",
    "ICAP_AUTOMATICBORDERDETECTION",
    "ICAP_AUTOMATICDESKEW",
    "ICAP_AUTOMATICROTATE",
    "ICAP_AUTOMATICLENGTHDETECTION",
    "ICAP_AUTOMATICCOLORENABLED",
    "ICAP_COLORMANAGEMENTENABLED",
    "ICAP_AUTOSIZE",
    "ICAP_NOISEFILTER",
    "ICAP_IMAGEFILTER",
    "ICAP_FILTER",
    "ICAP_ROTATION",
    "ICAP_XSCALING",
    "ICAP_YSCALING",
)
FIXED_CAPS = {
    "ICAP_XRESOLUTION",
    "ICAP_YRESOLUTION",
    "ICAP_PHYSICALWIDTH",
    "ICAP_PHYSICALHEIGHT",
    "ICAP_BRIGHTNESS",
    "ICAP_CONTRAST",
    "ICAP_GAMMA",
    "ICAP_ROTATION",
    "ICAP_XSCALING",
    "ICAP_YSCALING",
}


def fixed_range_value(value: int) -> float:
    # pytwain exposes TW_RANGE FIX32 items as packed DWORDs: signed Whole, then Frac.
    whole = value & 0xFFFF
    if whole >= 0x8000:
        whole -= 0x10000
    return whole + ((value >> 16) & 0xFFFF) / 65536


def normalize_capability(raw: Any, *, fixed: bool = False) -> dict[str, Any]:
    if isinstance(raw, dict):
        values = {
            k: fixed_range_value(v) if fixed and isinstance(v, int) else json_safe(v)
            for k, v in raw.items()
        }
        return {"container": "range", "range": values, "current": values.get("CurrentValue")}
    type_id, value = raw
    if isinstance(value, tuple) and len(value) == 3 and isinstance(value[2], list):
        current_index, default_index, items = value
        values = json_safe(items)
        return {
            "container": "enumeration",
            "type_id": type_id,
            "values": values,
            "current": values[current_index] if 0 <= current_index < len(values) else None,
            "default": values[default_index] if 0 <= default_index < len(values) else None,
        }
    if isinstance(value, list):
        return {"container": "array", "type_id": type_id, "values": json_safe(value)}
    return {"container": "one_value", "type_id": type_id, "current": json_safe(value)}


def epson_v39ii(name: str) -> bool:
    return "epson" in name.lower() and bool(
        re.search(r"v[\s-]*39[\s-]*(?:ii|2)(?![a-z0-9])", name, re.I)
    )


def select_source(names: list[str], explicit: str | None) -> str:
    if explicit:
        if explicit not in names:
            raise AgentError("device_absent", "The exact requested TWAIN source was not enumerated")
        return explicit
    matches = [name for name in names if epson_v39ii(name)]
    if not matches:
        raise AgentError(
            "device_absent", "No Epson V39 II source found; inspect devices and bitness"
        )
    if len(matches) != 1:
        raise AgentError(
            "ambiguous_device", "Multiple Epson V39 II sources; use --device with an exact name"
        )
    return matches[0]


def classify_error(exc: Exception) -> str:
    name = type(exc).__name__
    if isinstance(exc, AgentError):
        return exc.status
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 193:
        return "architecture_mismatch"
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 126:
        return "twain_unavailable"
    if name == "CheckStatus":
        return "adjusted"
    if name in {"DSTransferCancelled", "CancelAll"}:
        return "canceled"
    if name == "MaxConnectionsError":
        return "busy"
    if name in {"NoDataSourceError", "CheckDeviceOnlineError"}:
        return "device_absent"
    if name in {
        "BadCapability",
        "CapUnsupported",
        "CapBadOperation",
        "CapabilityFormatNotSupported",
    }:
        return "unsupported_option"
    if name in {"SMLoadFileFailed", "SMGetProcAddressFailed", "ModuleNotFoundError", "ImportError"}:
        return "twain_unavailable"
    return "driver_error"


def dsm_path(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_absolute() or path.suffix.lower() != ".dll" or not path.is_file():
            raise AgentError(
                "invalid_path", "--dsm must be a trusted, absolute, existing DSM DLL path"
            )
        return path
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    bits = struct.calcsize("P") * 8
    # Explicit system paths avoid loading a DLL with a matching name from the working directory.
    folder = "SysWOW64" if bits == 32 and (windows / "SysWOW64").is_dir() else "System32"
    candidates = [windows / folder / "TWAINDSM.dll"]
    if bits == 32:
        candidates.append(windows / "twain_32.dll")
    for path in candidates:
        if path.is_file():
            return path
    raise AgentError(
        "twain_unavailable", "No matching system DSM found; install a matching TWAIN DSM"
    )


def query(source: Any, twain: Any, name: str, *, current: bool = False) -> dict[str, Any]:
    cap = getattr(twain, name, None)
    if cap is None:
        return {"status": "not_in_binding"}
    try:
        raw = source.get_capability_current(cap) if current else source.get_capability(cap)
        return {"status": "exposed", **normalize_capability(raw, fixed=name in FIXED_CAPS)}
    except Exception as exc:
        if type(exc).__name__ in {
            "GeneralFailure",
            "CheckDeviceOnlineError",
            "MaxConnectionsError",
            "NoDataSourceError",
        }:
            raise AgentError(classify_error(exc), f"{name}: {type(exc).__name__}") from exc
        return {"status": classify_error(exc), "error_type": type(exc).__name__}


def capability_matches(name: str, actual: Any, requested: Any) -> bool:
    # 2.2 cannot be represented exactly by TW_FIX32. Retain the unrounded readback
    # as evidence and tolerate only one fractional step for gamma/contrast. Integer
    # contrast targets are exactly representable; a materially clamped value fails.
    if name in {"ICAP_GAMMA", "ICAP_CONTRAST"} and isinstance(actual, (int, float)):
        return abs(actual - requested) <= 1 / 65536
    return actual is not None and actual == requested


def negotiate(source: Any, twain: Any, name: str, kind: str, value: Any) -> dict[str, Any]:
    attempt: dict[str, Any] = {"requested": value}
    if not hasattr(twain, name):
        return {**attempt, "verified": False, "status": "not_in_binding"}
    try:
        source.set_capability(getattr(twain, name), getattr(twain, kind), value)
        attempt["set_status"] = "accepted"
    except Exception as exc:
        if type(exc).__name__ in {
            "GeneralFailure",
            "CheckDeviceOnlineError",
            "MaxConnectionsError",
            "NoDataSourceError",
        }:
            raise AgentError(classify_error(exc), f"{name}: {type(exc).__name__}") from exc
        attempt["set_status"] = classify_error(exc)
        attempt["error_type"] = type(exc).__name__
    # CHECKSTATUS can adjust a value. A successful SET alone never proves the requested value.
    attempt["readback"] = query(source, twain, name, current=True)
    actual = attempt["readback"].get("current")
    attempt["verified"] = capability_matches(name, actual, value)
    return attempt


def configure_region(source: Any, config: dict[str, Any], report: dict[str, Any]) -> None:
    """Use the driver's default frame as a conservative domain, never invent a glass origin.

    The default frame need not describe the whole bed. Regions outside it require manual
    Epson acquisition until the driver exposes a verifiable domain covering that region.
    """
    result: dict[str, Any] = {"verified": False, "requested": config["scan_region"]}
    report["scan_region"] = result
    if config["scan_region"] is None:
        raise AgentError(
            "fallback_required", "Configure a measured scan_region or use Epson folder import"
        )
    frame = region_inches(config["scan_region"])
    try:
        bounds = tuple(float(v) for v in source.get_image_layout_default()[0])
        result.update(
            driver_default_frame_inches=bounds,
            bounds_scope="conservative_default_frame_not_entire_glass",
        )
        import math

        if (
            len(bounds) != 4
            or not all(math.isfinite(v) for v in bounds)
            or not (bounds[0] < bounds[2] and bounds[1] < bounds[3])
        ):
            raise ValueError("Driver default frame is invalid")
        if not (
            bounds[0] <= frame[0] < frame[2] <= bounds[2]
            and bounds[1] <= frame[1] < frame[3] <= bounds[3]
        ):
            raise AgentError(
                "fallback_required", "Region lies outside the driver's conservative usable frame"
            )
        source.set_image_layout(frame)
        actual = tuple(float(v) for v in source.get_image_layout()[0])
        # TW_FIX32 quantization only; a broad tolerance could hide an origin shift.
        result.update(
            requested_inches=frame,
            readback_inches=actual,
            verified=len(actual) == 4
            and all(abs(a - b) <= 2 / 65536 for a, b in zip(frame, actual, strict=True)),
        )
        if not result["verified"]:
            raise AgentError(
                "fallback_required", "Driver adjusted scan coordinates; use Epson folder import"
            )
    except AgentError:
        raise
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        if classify_error(exc) in {"busy", "device_absent"}:
            raise AgentError(
                classify_error(exc), "Device unavailable during region negotiation"
            ) from exc
        raise AgentError(
            "fallback_required", "Driver region could not be verified; use Epson folder import"
        ) from exc


def configure_test(
    source: Any,
    twain: Any,
    report: dict[str, Any],
    strict: bool,
    configuration: dict[str, Any] | None = None,
) -> None:
    config = validate_config(configuration or {})
    settings: dict[str, Any] = {}
    report["settings"] = settings
    core = (
        ("ICAP_UNITS", "TWTY_UINT16", twain.TWUN_INCHES),
        ("ICAP_PIXELTYPE", "TWTY_UINT16", twain.TWPT_RGB),
        ("ICAP_XRESOLUTION", "TWTY_FIX32", float(config["dpi"])),
        ("ICAP_YRESOLUTION", "TWTY_FIX32", float(config["dpi"])),
        ("ICAP_COMPRESSION", "TWTY_UINT16", twain.TWCP_NONE),
        ("ICAP_XFERMECH", "TWTY_UINT16", twain.TWSX_NATIVE),
    )
    for name, kind, value in core[:2]:
        settings[name] = negotiate(source, twain, name, kind, value)
    attempts = [negotiate(source, twain, "ICAP_BITDEPTH", "TWTY_UINT16", 24)]
    if not attempts[-1]["verified"]:
        # TWAIN documents legacy per-channel depth 8 for 24-bit RGB. Verify actual image info later.
        attempts.append(negotiate(source, twain, "ICAP_BITDEPTH", "TWTY_UINT16", 8))
    settings["ICAP_BITDEPTH"] = {**attempts[-1], "attempts": attempts}
    report["rgb_bitdepth_convention"] = "legacy_per_channel" if len(attempts) == 2 else "total_bits"
    for name, kind, value in core[2:]:
        settings[name] = negotiate(source, twain, name, kind, value)
    optional = (
        ("CAP_FEEDERENABLED", "TWTY_BOOL", False),
        ("CAP_XFERCOUNT", "TWTY_INT16", 1),
        ("ICAP_PLANARCHUNKY", "TWTY_UINT16", twain.TWPC_CHUNKY),
        ("ICAP_AUTOBRIGHT", "TWTY_BOOL", False),
        ("ICAP_AUTOMATICBORDERDETECTION", "TWTY_BOOL", False),
        ("ICAP_AUTOMATICDESKEW", "TWTY_BOOL", False),
        ("ICAP_AUTOMATICROTATE", "TWTY_BOOL", False),
        ("ICAP_AUTOMATICLENGTHDETECTION", "TWTY_BOOL", False),
        ("ICAP_AUTOMATICCOLORENABLED", "TWTY_BOOL", False),
        ("ICAP_COLORMANAGEMENTENABLED", "TWTY_BOOL", False),
        ("ICAP_AUTOSIZE", "TWTY_UINT16", twain.TWAS_NONE),
        ("ICAP_NOISEFILTER", "TWTY_UINT16", twain.TWNF_NONE),
        ("ICAP_IMAGEFILTER", "TWTY_UINT16", twain.TWIF_NONE),
        ("ICAP_FILTER", "TWTY_UINT16", twain.TWFT_NONE),
        ("ICAP_BRIGHTNESS", "TWTY_FIX32", 0.0),
        ("ICAP_CONTRAST", "TWTY_FIX32", float(config["contrast"])),
        ("ICAP_GAMMA", "TWTY_FIX32", float(config["gamma"])),
        ("ICAP_ROTATION", "TWTY_FIX32", 0.0),
        ("ICAP_XSCALING", "TWTY_FIX32", 1.0),
        ("ICAP_YSCALING", "TWTY_FIX32", 1.0),
    )
    for name, kind, value in optional:
        if name == "ICAP_AUTOSIZE":
            current = query(source, twain, name, current=True)
            if current.get("type_id") == twain.TWTY_BOOL:
                kind, value = "TWTY_BOOL", False  # Documented legacy Epson representation.
        settings[name] = negotiate(source, twain, name, kind, value)
    if query(source, twain, "ICAP_UNITS", current=True).get("current") != twain.TWUN_INCHES:
        raise AgentError("fallback_required", "Driver coordinate units could not be confirmed")
    configure_region(source, config, report)
    # Re-read every setting after all negotiation: layout/dependent capabilities may reset each other.
    for name, value in settings.items():
        value["final_readback"] = query(source, twain, name, current=True)
        actual = value["final_readback"].get("current")
        value["verified"] = capability_matches(name, actual, value["requested"])
    required_names = [name for name, _, _ in core] + [
        "ICAP_BITDEPTH",
        "ICAP_GAMMA",
        "ICAP_CONTRAST",
        "ICAP_BRIGHTNESS",
    ]
    report["unverified_options"] = [
        name for name, value in settings.items() if not value["verified"]
    ]
    if any(not settings[name]["verified"] for name in required_names):
        raise AgentError(
            "unsupported_option",
            "Requested DPI/RGB/gamma/contrast/brightness settings could not be confirmed",
        )
    if any(
        not settings[name]["verified"]
        and settings[name]["final_readback"].get("current") is not None
        for name, _, _ in optional
        if name != "CAP_XFERCOUNT"
    ):
        raise AgentError(
            "unsupported_option", "A known processing/geometry option could not be neutralized"
        )
    if strict and report["unverified_options"]:
        raise AgentError(
            "unsupported_option", "Strict option verification failed; no acquisition started"
        )
    report["vendor_specific_enhancements_verified"] = False


def profile_matches(info: dict[str, Any], image: dict[str, Any], dpi: float = 600) -> bool:
    frame = image["frames"][0]
    return (
        image["frame_count"] == 1
        and frame["mode"] == "RGB"
        and frame.get("bits_per_pixel") == 24
        and info.get("PixelType") == 2
        and info.get("BitsPerPixel") == 24
        and info.get("SamplesPerPixel") == 3
        and info.get("BitsPerSample", [])[:3] == [8, 8, 8]
        and info.get("XResolution") == dpi
        and info.get("YResolution") == dpi
        and info.get("ImageWidth") == frame["width"]
        and info.get("ImageLength") == frame["height"]
        and info.get("Compression") == 0
    )


def run_job(
    job: dict[str, Any], report: dict[str, Any], checkpoint: Callable[[], None] = lambda: None
) -> None:
    if sys.platform != "win32":
        raise AgentError(
            "twain_unavailable", "TWAIN acquisition requires an interactive Windows workstation"
        )
    import twain

    dsm = dsm_path(job.get("dsm"))
    report["dsm"] = str(dsm)
    config = validate_config(job.get("configuration", {}))
    report["requested_profile"] = config
    report["preferred_output_note"] = (
        "Folder PNG is preserved exactly; direct native transfer retains original BMP, never silently converts"
    )
    from .windows import hidden_window

    with hidden_window() as root:
        with twain.SourceManager(
            root, dsm_name=str(dsm), ProductName="SPECTRA S1 local test"
        ) as manager:
            names = manager.source_list
            report["devices"] = [
                {"name": name, "matches_epson_v39ii": epson_v39ii(name)} for name in names
            ]
            report["phase"] = "sources_enumerated"
            checkpoint()
            if job.get("list_only"):
                report["status"] = "devices_listed"
                return
            name = select_source(names, job.get("device"))
            report["selected_device"] = name
            report["phase"] = "opening_source"
            checkpoint()
            source = manager.open_source(name)
            if source is None:
                raise AgentError("device_absent", "TWAIN could not open the selected source")
            with source:
                report["device_identity"] = json_safe(source.identity)
                report["selected_device"] = name
                report["selection"] = (
                    "explicit" if job.get("device") else "unique_epson_v39ii_match"
                )
                report["capabilities"] = {}
                report["capabilities_status"] = "partial"
                for cap_name in CAPABILITIES:
                    report["phase"] = "querying_" + cap_name
                    checkpoint()
                    report["capabilities"][cap_name] = query(source, twain, cap_name)
                report["capabilities_status"] = "queried"
                report["pixel_formats"] = {
                    str(getattr(twain, n)): n for n in dir(twain) if n.startswith("TWPT_")
                }
                report["pixel_formats_note"] = (
                    "Names are binding definitions; supported values are ICAP_PIXELTYPE.values"
                )
                report["status"] = "discovered"
                if job["operation"] == "discover":
                    report["image_layout_probe"] = {}
                    for label, method in (
                        ("current", source.get_image_layout),
                        ("default", source.get_image_layout_default),
                    ):
                        try:
                            report["image_layout_probe"][label] = json_safe(method())
                        except Exception as exc:
                            report["image_layout_probe"][label] = {"error_type": type(exc).__name__}
                    report["image_layout_probe"]["units"] = query(
                        source, twain, "ICAP_UNITS", current=True
                    )
                    return
                if query(source, twain, "CAP_DEVICEONLINE", current=True).get("current") is False:
                    raise AgentError(
                        "device_absent", "The selected source reports that its device is offline"
                    )
                configure_test(source, twain, report, job.get("strict_options", False), config)
                report["phase"] = "profile_negotiated"
                checkpoint()
                store = ArtifactStore(Path(job["data_dir"]), config)
                report["captures"] = []
                image_info: dict[str, Any] = {}

                def before(info: dict[str, Any]) -> None:
                    image_info.update(json_safe(info))
                    report["transferred_image_info"] = image_info
                    # Epson UI can change negotiated values. Preserve transfer-time evidence;
                    # never label pre-UI verification as proof of the delivered processing state.
                    current = {
                        name: query(source, twain, name, current=True)
                        for name in report["settings"]
                        if name != "CAP_XFERCOUNT"
                    }
                    report["transfer_time_settings"] = current
                    report["unverified_transfer_options"] = [
                        name for name, value in current.items() if value.get("current") is None
                    ]
                    mismatches = [
                        name
                        for name, value in current.items()
                        if value.get("current") is not None
                        and not capability_matches(
                            name, value["current"], report["settings"][name]["requested"]
                        )
                    ]
                    try:
                        actual_region = tuple(float(v) for v in source.get_image_layout()[0])
                        region_matches = len(actual_region) == 4 and all(
                            abs(a - b) <= 2 / 65536
                            for a, b in zip(
                                report["scan_region"]["requested_inches"],
                                actual_region,
                                strict=True,
                            )
                        )
                        report["transfer_time_region_inches"] = actual_region
                    except Exception:
                        region_matches = False
                    if not region_matches:
                        mismatches.append("scan_region")
                    for required in ("ICAP_GAMMA", "ICAP_CONTRAST", "ICAP_BRIGHTNESS"):
                        if required in report["unverified_transfer_options"]:
                            mismatches.append(required + "_unavailable")
                    if mismatches or (
                        job.get("strict_options") and report["unverified_transfer_options"]
                    ):
                        report["transfer_block_status"] = "unsupported_option"
                        report["transfer_mismatches"] = mismatches
                        checkpoint()
                        raise twain.exceptions.CancelAll

                def after(image: Any, remaining: int) -> None:
                    report["image_transfer_performed"] = True
                    report["physical_scan_performed"] = (
                        True if epson_v39ii(name) else "unknown_non_target_source"
                    )
                    report["phase"] = "native_image_transferred"
                    checkpoint()
                    acquired_at = utc_now()
                    with tempfile.TemporaryDirectory(prefix="native-", dir=store.staging) as stage:
                        raw = Path(stage) / "driver-transfer.bmp"
                        # pytwain wraps the native DIB as BMP; no Pillow re-encoding or pixel transforms.
                        # The library's image object owns/frees the native handle.
                        image.save(str(raw))
                        capture = store.commit(
                            raw,
                            {
                                "method": "twain_native_dib_to_bmp",
                                "source_filename": "driver-transfer.bmp",
                                "confirmed_region": {
                                    "frame": report.get("transfer_time_region_inches"),
                                    "units": "inches",
                                    "evidence": "transfer_time_driver_readback",
                                },
                                "acquired_at_utc": acquired_at,
                                "device_identity": report["device_identity"],
                                "dsm": str(dsm),
                                "driver_information": report["device_identity"],
                                "requested_profile": report["requested_profile"],
                                "capture_settings": report["settings"],
                                "twain_image_info": image_info,
                                "transfer_time_settings": report.get("transfer_time_settings"),
                                "unverified_transfer_options": report.get(
                                    "unverified_transfer_options"
                                ),
                                "unverified_options": report["unverified_options"],
                                "vendor_specific_enhancements_verified": False,
                            },
                        )
                    report["captures"].append(capture)
                    report["image_profile_verified"] = profile_matches(
                        image_info, capture["image"], config["dpi"]
                    )
                    report["phase"] = "original_committed"
                    checkpoint()
                    if remaining:
                        raise twain.exceptions.CancelAll  # Exactly one S1 test original per command.

                report["physical_scan_performed"] = "unknown_until_transfer"
                source.acquire_natively(
                    after=after, before=before, show_ui=job.get("show_ui", False), modal=False
                )
                if not report["captures"]:
                    report["status"] = report.get("transfer_block_status", "canceled")
                else:
                    report["status"] = (
                        "acquired"
                        if report["image_profile_verified"]
                        and all(
                            c["quality_control"]["status"] != "fail" for c in report["captures"]
                        )
                        else "profile_mismatch"
                    )
