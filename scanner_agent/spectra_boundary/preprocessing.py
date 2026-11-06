from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def working_gray(rgb: Any, parameters: dict[str, Any]) -> Any:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    values = gray.astype(np.float32)
    limits = parameters["normalize_percentiles"]
    if limits is not None:
        low, high = np.percentile(values, limits)
        if high > low:
            values = (values - low) * (255 / (high - low))
    # Global working-image operation only; no spatial transform or sharpening.
    values = (values - 127.5) * parameters["contrast"] + 127.5
    return np.clip(values, 0, 255).astype(np.uint8)
