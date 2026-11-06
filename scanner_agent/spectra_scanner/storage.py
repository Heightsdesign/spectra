"""Byte-preserving local test originals, exclusive creation, manifest committed last."""

from __future__ import annotations

import hashlib
import os
import shutil
import struct
import warnings
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .common import AgentError, environment, identifier, utc_now, write_json_new
from .config import validate_config
from .quality import acquisition_checks

MAX_BYTES = 768 * 1024 * 1024
MAX_PIXELS = 200_000_000  # A full A4 flatbed at 1200 DPI is ~139 million pixels.
TIFF_LOSSLESS = {1, 5, 8, 32773, 32946}
EXTENSIONS = {"PNG": ".png", "TIFF": ".tiff", "BMP": ".bmp"}


def encoded_bit_depth(path: Path, image: Any) -> dict[str, Any]:
    """Read original encoding metadata; Pillow's decoded RGB mode can hide 16/48-bit input."""
    with path.open("rb") as stream:
        header = stream.read(54)
    if image.format == "BMP":
        dib_size = struct.unpack_from("<I", header, 14)[0]
        offset = 24 if dib_size == 12 else 28
        return {"bits_per_pixel": struct.unpack_from("<H", header, offset)[0]}
    if image.format == "PNG":
        depth, color_type = header[24], header[25]
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
        return {"bits_per_pixel": depth * channels, "bits_per_sample": [depth] * channels}
    depths = image.tag_v2.get(258, (1,))
    depths = list(depths) if isinstance(depths, (tuple, list)) else [depths]
    return {
        "bits_per_pixel": sum(depths),
        "bits_per_sample": depths,
        "compression_tag": int(image.tag_v2.get(259, 1)),
        "encoded_width": int(image.tag_v2.get(256, image.width)),
        "encoded_height": int(image.tag_v2.get(257, image.height)),
        "orientation_tag": int(image.tag_v2.get(274, 1)),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_image(path: Path) -> dict[str, Any]:
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise AgentError("invalid_image", "Image is empty or exceeds the 768 MiB S1 limit")
    old_limit = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format not in EXTENSIONS:
                    raise AgentError(
                        "unsupported_format", "Export lossless TIFF, PNG or BMP, not JPEG"
                    )
                image.verify()
            with Image.open(path) as image:
                frames = []
                pixels = 0
                count = getattr(image, "n_frames", 1)
                if count > 16:
                    raise AgentError("invalid_image", "More than 16 frames is outside the S1 limit")
                for index in range(count):
                    image.seek(index)
                    pixels += image.width * image.height
                    if pixels > MAX_PIXELS:
                        raise AgentError(
                            "invalid_image", "Image exceeds the aggregate S1 pixel limit"
                        )
                    if image.format == "TIFF":
                        compression = int(image.tag_v2.get(259, 1))  # type: ignore[attr-defined]
                        if compression not in TIFF_LOSSLESS:
                            raise AgentError(
                                "unsupported_format", "TIFF compression is not verified lossless"
                            )
                    if image.format == "BMP" and image.info.get("compression", 0) not in (0, 3):
                        raise AgentError(
                            "unsupported_format", "BMP compression is not verified lossless"
                        )
                    encoding = encoded_bit_depth(path, image)
                    width = encoding.pop("encoded_width", image.width)
                    height = encoding.pop("encoded_height", image.height)
                    # TIFF decoding can apply orientation internally. Describe the stored
                    # geometry/tags before decoding and never write that decoded representation.
                    embedded_dpi = (
                        [float(v) for v in image.info["dpi"]] if image.info.get("dpi") else None
                    )
                    image.load()  # Verify alone does not prove a complete pixel stream.
                    extrema = image.getextrema()
                    bands = extrema if isinstance(extrema[0], tuple) else (extrema,)
                    uniform = all(low == high for low, high in bands)
                    frames.append(
                        {
                            "width": width,
                            "height": height,
                            "mode": image.mode,
                            **encoding,
                            "dpi_metadata": embedded_dpi,
                            "icc_profile_present": bool(image.info.get("icc_profile")),
                            "uniform_pixel_content": uniform,
                        }
                    )
                return {"format": image.format, "frames": frames, "frame_count": len(frames)}
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        EOFError,
        struct.error,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise AgentError("invalid_image", "Invalid, incomplete or excessive image data") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = old_limit


class ArtifactStore:
    def __init__(self, root: Path, configuration: dict[str, Any] | None = None):
        self.configuration = validate_config(configuration or {})
        self.root = root
        self.captures = root / "captures"
        self.staging = root / ".staging"
        self.captures.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)
        for folder in (self.captures, self.staging):
            if not folder.resolve().is_relative_to(root.resolve()):
                raise AgentError(
                    "invalid_path", "Artifact directories must not redirect outside S1 storage"
                )

    def duplicate(self, digest: str) -> dict[str, Any] | None:
        import json

        for manifest in self.captures.glob("*/metadata.json"):
            try:
                value = json.loads(manifest.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue  # Incomplete manifests never establish a committed original.
            if value.get("sha256") != digest or value.get("complete") is not True:
                continue
            name = value.get("original", "")
            if name not in {"original.png", "original.bmp", "original.tiff"}:
                raise AgentError("storage_integrity_error", "Invalid committed original reference")
            original = manifest.parent / name
            if not original.is_file() or sha256_file(original) != digest:
                raise AgentError(
                    "storage_integrity_error", "Existing original failed its SHA-256 check"
                )
            return {
                "status": "duplicate",
                "capture_id": value["capture_id"],
                "sha256": digest,
                "quality_control": value.get(
                    "quality_control", {"status": "pending_legacy_manifest"}
                ),
            }
        return None

    def commit(
        self, snapshot: Path, provenance: dict[str, Any], *, deduplicate: bool = False
    ) -> dict[str, Any]:
        image = inspect_image(snapshot)
        digest = sha256_file(snapshot)
        if deduplicate:
            prior = self.duplicate(digest)
            if prior:
                return prior
        capture_id = identifier()
        destination = self.captures / capture_id
        destination.mkdir()  # Never reuse an existing capture directory, even on UUID collision.
        original_name = "original" + EXTENSIONS[image["format"]]
        original = destination / original_name
        with snapshot.open("rb") as source, original.open("xb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if sha256_file(original) != digest:
            raise AgentError("storage_integrity_error", "Original copy failed SHA-256 verification")
        metadata = {
            "schema_version": 2,
            "complete": True,
            "capture_id": capture_id,
            "original": original_name,
            "sha256": digest,
            "file_size": original.stat().st_size,
            "stored_at_utc": utc_now(),
            "image": image,
            "provenance": provenance,
            "acquisition": {
                "id": capture_id,
                "mode": provenance.get("method"),
                "source_filename": provenance.get("source_filename"),
                "acquired_at_utc": provenance.get("acquired_at_utc"),
                "observed_at_utc": utc_now(),
                "timestamp_evidence": "driver_transfer"
                if provenance.get("acquired_at_utc")
                else "unknown_manual_scan_time",
                "user_configured": self.configuration,
                "device_reported": {
                    "identity": provenance.get("device_identity"),
                    "settings": provenance.get("transfer_time_settings"),
                    "image_info": provenance.get("twain_image_info"),
                    "region": provenance.get("confirmed_region"),
                },
                "independently_observed_file": image,
                "software": {
                    key: value
                    for key, value in environment().items()
                    if key in {"agent_version", "python", "python_bits", "pytwain", "Pillow", "os"}
                },
            },
            "quality_control": acquisition_checks(image, self.configuration),
            "derived_images": [],
            "pixel_transformations": [],
            "calibration_verified": False,
            "storage_namespace": "S1_local_test",
            "production_card_association": None,
        }
        # Absence of this final manifest means recovery is needed, never a successful import.
        write_json_new(destination / "metadata.json", metadata)
        return {
            "status": "stored",
            "capture_id": capture_id,
            "sha256": digest,
            "original": str(original.relative_to(self.root)),
            "metadata": str((destination / "metadata.json").relative_to(self.root)),
            "image": image,
            "quality_control": metadata["quality_control"],
        }
