"""Read stored originals and persist private, separately versioned diagnostics."""

import hashlib
import io
import json
import re
import shutil
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import cv2
import numpy as np
from PIL import Image

from app.boundary import BoundaryConfig, BoundaryDetection, BoundaryResult, detect_boundary
from app.config import Settings
from app.models import CardImage


@dataclass
class StoredBoundaryAnalysis:
    image_id: UUID
    run_id: UUID
    result: BoundaryResult


def analyze_original(original: CardImage, settings: Settings, config: BoundaryConfig | None = None) -> StoredBoundaryAnalysis:
    """No DB writes or original writes. Diagnostic I/O failures propagate.

    Source/integrity/detection failures return structured rejected results.
    """
    config = config or BoundaryConfig()
    storage = settings.card_image_dir.resolve()
    diagnostics = settings.boundary_output_dir.resolve()
    if storage == diagnostics or storage in diagnostics.parents or diagnostics in storage.parents:
        raise ValueError("Original and diagnostic storage trees must be separate")
    if not re.fullmatch(r"[0-9a-f]{32}", original.storage_key):
        raise ValueError("Invalid generated storage key")
    source = storage / original.storage_key
    if source.is_symlink() or source.resolve().parent != storage:
        raise ValueError("Original must resolve within private storage")
    detection = BoundaryDetection(BoundaryResult())
    data = None
    try:
        with source.open("rb") as input_file:
            data = input_file.read(settings.max_image_size_bytes + 1)
    except OSError:
        detection.result.failure_reason = "original_unavailable"
    if data is not None:
        if len(data) > settings.max_image_size_bytes:
            detection.result.failure_reason = "original_too_large"
        elif len(data) != original.file_size or hashlib.sha256(data).hexdigest() != original.sha256:
            detection.result.failure_reason = "original_integrity_mismatch"
        else:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(data)) as header:
                        width, height = header.size
                        frames = getattr(header, "n_frames", 1)
                    detection.result.image_dimensions = {"width": width, "height": height}
                    if width * height > config.max_input_pixels:
                        detection.result.failure_reason = "image_too_large"
                    elif frames != 1:
                        detection.result.failure_reason = "multiple_image_frames"
                    else:
                        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
                        detection = detect_boundary(image, config)
            except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning, cv2.error):
                detection = BoundaryDetection(BoundaryResult(failure_reason="invalid_image"))
    run_id = uuid4()
    diagnostics.mkdir(parents=True, exist_ok=True)
    run_dir = diagnostics / run_id.hex
    run_dir.mkdir()  # Exclusive: never reuse or overwrite a previous run.
    try:
        metadata = {
            "algorithm": "uniform-background-silhouette-v1",
            "image_id": str(original.id), "run_id": str(run_id),
            "source_sha256": original.sha256,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "config": config.model_dump(), "opencv_version": cv2.__version__,
            "numpy_version": np.__version__, "result": detection.result.to_dict(),
            "transform": detection.transform.tolist() if detection.transform is not None else None,
        }
        with (run_dir / "result.json").open("x", encoding="utf-8") as output:
            json.dump(metadata, output, indent=2, allow_nan=False)
        for name, image in (("mask.png", detection.foreground_mask), ("overlay.png", detection.overlay), ("normalized.png", detection.normalized_image)):
            if image is not None:
                ok, encoded = cv2.imencode(".png", image)
                if not ok:
                    raise OSError("Diagnostic encoding failed")
                with (run_dir / name).open("xb") as output:
                    output.write(encoded.tobytes())
    except Exception:
        shutil.rmtree(run_dir)
        raise
    return StoredBoundaryAnalysis(original.id, run_id, detection.result)
