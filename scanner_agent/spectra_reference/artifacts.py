from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from spectra_scanner.common import AgentError

from . import NAMES
from .geometry import points_on_reference
from .inputs import candidate_lookup


def annotation_page(
    rgb: Any, evaluation: dict[str, Any], reference: dict[str, Any], output: Path
) -> None:
    buffer = io.BytesIO()
    Image.fromarray(rgb).save(buffer, format="PNG")
    payload = {
        "evaluation": evaluation,
        "reference": reference,
        "image": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
    }
    encoded = json.dumps(payload, allow_nan=False).replace("<", "\\u003c").replace("&", "\\u0026")
    template = Path(__file__).with_name("annotation.html").read_text(encoding="utf-8")
    # Inline local assets so the generated interface stays a single offline file.
    template = template.replace(
        "__SPECTRA_EDITOR_CORE__",
        Path(__file__).with_name("editor-core.js").read_text(encoding="utf-8"),
    ).replace(
        "__SPECTRA_EDITOR_CONTROLLER__",
        Path(__file__).with_name("editor.js").read_text(encoding="utf-8"),
    )
    with output.open("x", encoding="utf-8") as handle:
        handle.write(template.replace("__SPECTRA_DATA__", encoded))


def overlays(
    rgb: Any,
    evaluation: dict[str, Any],
    reference: dict[str, Any],
    comparison: dict[str, Any],
    output: Path,
) -> list[str]:
    corners = np.asarray(evaluation["physical_corners_pixels"])
    lookup = candidate_lookup(evaluation)
    artifacts = []
    # Bound disk use for large hypothesis sets. All numerical rows remain in JSON.
    ordered = sorted(
        comparison["hypotheses"],
        key=lambda r: (r["rank"] is None, r["rank"] or 0, r["hypothesis_id"]),
    )
    comparison["overlay_policy"] = {
        "maximum": 32,
        "truncated": len(ordered) > 32,
        "ordering": "ranked first, then stable hypothesis ID",
    }
    for number, row in enumerate(ordered[:32]):
        canvas = Image.fromarray(rgb)
        draw = ImageDraw.Draw(canvas)
        draw.line([tuple(p) for p in corners] + [tuple(corners[0])], fill="cyan", width=3)
        for i, name in enumerate(NAMES):
            # Hypotheses remain visible even if an ambiguous/missing reference
            # prevents quantitative comparison on this side.
            ids = row["candidate_ids"]
            if i < len(ids) and ids[i] in lookup and lookup[ids[i]][0] == i:
                coefficients = lookup[ids[i]][1].get("line_abc")
                if coefficients is not None:
                    try:
                        exclusion = evaluation["configuration"]["candidate_generation"][
                            "corner_exclusion_fraction"
                        ]
                        points = points_on_reference(
                            corners,
                            i,
                            np.asarray(coefficients),
                            np.array([exclusion, 1 - exclusion]),
                        )
                        draw.line([tuple(p) for p in points], fill="magenta", width=2)
                    except (AgentError, ValueError, TypeError):
                        pass
            side = reference["sides"][i]
            if side.get("line_abc") is not None:
                points = points_on_reference(
                    corners, i, np.asarray(side["line_abc"]), np.array(side["valid_span_fraction"])
                )
                draw.line(
                    [tuple(p) for p in points],
                    fill="lime" if side["definition"] == "candidate" else "yellow",
                    width=3,
                )
            evidence = row["per_side"].get(name, {})
            if evidence.get("available"):
                points = evidence["hypothesis_points_pixels"]
                draw.line([tuple(points[0]), tuple(points[-1])], fill="magenta", width=2)
                for k in range(0, len(points), 5):
                    draw.line(
                        [tuple(evidence["reference_points_pixels"][k]), tuple(points[k])],
                        fill="orange",
                        width=2,
                    )
        banner = Image.new("RGB", (canvas.width, canvas.height + 65), "black")
        banner.paste(canvas, (0, 65))
        label = ImageDraw.Draw(banner)
        label.text(
            (8, 6),
            f"{row['hypothesis_id']} rank={row['rank']} | cyan physical | magenta hypothesis | lime candidate reference | yellow manual reference | orange displacement",
            fill="white",
        )
        label.text(
            (8, 30),
            "Experimental agreement only; rank does not establish correctness. Reference lines may overlap hypothesis lines.",
            fill="white",
        )
        filename = f"hypothesis-{number:04}.png"
        with (output / filename).open("xb") as handle:
            banner.save(handle, format="PNG")
        row["overlay"] = filename
        artifacts.append(filename)
    explanation = [
        "S2.2c: review_required; manual reference agreement, not certified ground truth.",
        comparison["interpretation"],
        "Reference flags: " + ", ".join(comparison["reference_quality_flags"]),
        "Rank | hypothesis | mean absolute px | maximum absolute px | availability | exclusions",
    ]
    for row in sorted(
        comparison["hypotheses"],
        key=lambda r: (r["rank"] is None, r["rank"] or 0, r["hypothesis_id"]),
    ):
        metrics = row["aggregate"] or {}
        explanation.append(
            f"{row['rank']} | {row['hypothesis_id']} | {metrics.get('mean_absolute_pixels')} | {metrics.get('maximum_absolute_pixels')} | {row['comparison_availability']} | {', '.join(row['exclusion_reasons'])}"
        )
    with (output / "summary.txt").open("x", encoding="utf-8") as handle:
        handle.write("\n".join(explanation) + "\n")
    return artifacts + ["summary.txt"]
