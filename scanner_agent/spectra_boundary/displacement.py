from __future__ import annotations

from typing import Any

import numpy as np


def position(line: Any, anchor: Any, normal: Any) -> float:
    coefficients = np.asarray(line)
    return float(-(coefficients[:2] @ anchor + coefficients[2]) / (coefficients[:2] @ normal))


def compare_layers(baseline: dict[str, Any], enhanced: dict[str, Any]) -> dict[str, Any]:
    if "sides" not in baseline or "sides" not in enhanced:
        return {"unavailable": "Both modes need four fitted sides"}
    output: dict[str, Any] = {
        "sign_convention": "positive displacement inward along baseline seed normal; coordinates unchanged",
        "side_comparisons": [],
    }
    for side, other in zip(baseline["sides"], enhanced["sides"], strict=True):
        start, end = np.asarray(side["seed_start_pixels"]), np.asarray(side["seed_end_pixels"])
        anchors = np.array([start, (start + end) / 2, end])
        normal = np.asarray(side["inward_normal"])
        displacement = [
            position(other["line_abc"], a, normal) - position(side["line_abc"], a, normal)
            for a in anchors
        ]
        pairs = []
        for first in side["candidate_layers"]:
            for second in other["candidate_layers"]:
                delta = position(second["line_abc"], anchors[1], normal) - position(
                    first["line_abc"], anchors[1], normal
                )
                pairs.append((abs(delta), first["id"], second["id"], delta))
        matched = []
        used_a: set[str] = set()
        used_b: set[str] = set()
        for distance, a, b, delta in sorted(pairs):
            if distance > 2 or a in used_a or b in used_b:
                continue
            used_a.add(a)
            used_b.add(b)
            matched.append(
                {
                    "baseline_layer_id": a,
                    "preprocessed_layer_id": b,
                    "midpoint_normal_displacement_pixels": delta,
                }
            )
        output["side_comparisons"].append(
            {
                "side_index": side["index"],
                "baseline_selected": side["selected_layer_id"],
                "preprocessed_selected": other["selected_layer_id"],
                "normal": normal.tolist(),
                "anchors_original_pixels": anchors.tolist(),
                "selected_normal_displacement_pixels_start_mid_end": displacement,
                "candidate_matching": "one-to-one nearest midpoint line distance <=2 pixels; IDs are local to each mode; not proof of same physical edge",
                "candidate_matches": matched,
                "unmatched_baseline_ids": [
                    layer["id"] for layer in side["candidate_layers"] if layer["id"] not in used_a
                ],
                "unmatched_preprocessed_ids": [
                    layer["id"] for layer in other["candidate_layers"] if layer["id"] not in used_b
                ],
                "baseline_candidates": side["candidate_layers"],
                "preprocessed_candidates": other["candidate_layers"],
            }
        )
    right = int(
        np.argmax(
            [
                np.mean([s["seed_start_pixels"][0], s["seed_end_pixels"][0]])
                for s in baseline["sides"]
            ]
        )
    )
    output["right_side_index"] = right
    output["right_side_comparison"] = output["side_comparisons"][right]
    return output
