from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

from PIL import Image


def page(rgb: Any, reference: dict[str, Any], reports: list[dict[str, Any]], output: Path) -> None:
    buffer = io.BytesIO()
    Image.fromarray(rgb).save(buffer, format="PNG")
    data = {
        "image": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
        "reference": reference,
        "reports": reports,
    }
    encoded = json.dumps(data, allow_nan=False).replace("<", "\\u003c").replace("&", "\\u0026")
    root = Path(__file__).parent
    # Reuse camera transforms, line arithmetic and history without touching S2.2c.
    core = (root.parent / "spectra_reference/editor-core.js").read_text(encoding="utf-8")
    template = (root / "editor.html").read_text(encoding="utf-8")
    template = template.replace("__DATA__", encoded).replace("__CORE__", core)
    template = template.replace(
        "__MODEL__", (root / "reference-core.js").read_text(encoding="utf-8")
    )
    template = template.replace("__EDITOR__", (root / "editor.js").read_text(encoding="utf-8"))
    with output.open("x", encoding="utf-8") as handle:
        handle.write(template)
