"""Separate derived zooms and profiles. Original pixel coordinates are recorded."""

from __future__ import annotations

import colorsys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def color(index: int) -> tuple[int, int, int]:
    red, green, blue = colorsys.hsv_to_rgb((index * 0.61803398875) % 1, 0.85, 1)
    return round(red * 210), round(green * 210), round(blue * 210)


def save(path: Path, image: Any) -> None:
    with path.open("xb") as stream:
        image.save(stream, format="PNG")


def box_for(points: Any, shape: Any, padding: float) -> tuple[int, int, int, int]:
    points = np.asarray(points)
    left = int(np.clip(np.floor(points[:, 0].min() - padding), 0, shape[1] - 1))
    top = int(np.clip(np.floor(points[:, 1].min() - padding), 0, shape[0] - 1))
    return (
        left,
        top,
        int(np.clip(np.ceil(points[:, 0].max() + padding) + 1, left + 1, shape[1])),
        int(np.clip(np.ceil(points[:, 1].max() + padding) + 1, top + 1, shape[0])),
    )


def mark_layers(canvas: Any, side: dict[str, Any], box: tuple[int, int, int, int]) -> None:
    start = np.array(side["seed_start_pixels"])
    end = np.array(side["seed_end_pixels"])
    direction = (end - start) / np.linalg.norm(end - start)
    normal = np.array(side["inward_normal"])
    center = (start + end) / 2
    for index, layer in enumerate(side["candidate_layers"]):
        line = np.array(layer["line_abc"])
        point = center - normal * ((line[:2] @ center + line[2]) / (line[:2] @ normal))
        tangent = np.array([-line[1], line[0]])
        ink = (0, 145, 245) if layer["selected"] else color(index)
        ends = [
            tuple(np.rint(point + tangent * d - np.array(box[:2])).astype(int))
            for d in (-10000, 10000)
        ]
        cv2.line(canvas, ends[0], ends[1], ink, 1, cv2.LINE_AA)
        for x, y in layer["support_sample_pixels"]:
            if box[0] <= x < box[2] and box[1] <= y < box[3]:
                cv2.circle(canvas, (round(x - box[0]), round(y - box[1])), 1, ink, -1)
        label_at = (
            point - direction * min(60, np.linalg.norm(end - start) * 0.12) - np.array(box[:2])
        )
        if 0 <= label_at[0] < canvas.shape[1] and 0 <= label_at[1] < canvas.shape[0]:
            cv2.putText(
                canvas,
                f"S{side['index']}:{layer['id']}",
                tuple(np.rint(label_at).astype(int)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.25,
                ink,
                1,
                cv2.LINE_AA,
            )


def write_zooms(rgb: Any, detection: dict[str, Any], folder: Path, prefix: str) -> dict[str, Any]:
    if "sides" not in detection or "geometry" not in detection:
        return {"unavailable": "No complete side fits / quadrilateral"}
    font = ImageFont.load_default(size=14)
    artifacts: dict[str, Any] = {
        "side_zooms": [],
        "corner_zooms": [],
        "rendering": "derived crops, 4x nearest-neighbor magnification; originals unchanged",
    }
    for side in detection["sides"]:
        start, end = np.array(side["seed_start_pixels"]), np.array(side["seed_end_pixels"])
        center = (start + end) / 2
        tangent = (end - start) / np.linalg.norm(end - start)
        half = min(90, np.linalg.norm(end - start) * 0.15)
        box = box_for(
            np.array([center - tangent * half, center + tangent * half]),
            rgb.shape,
            max(28, side["search_half_width_pixels"] + 10),
        )
        canvas = rgb[box[1] : box[3], box[0] : box[2]].copy()
        mark_layers(canvas, side, box)
        picture = Image.fromarray(canvas).resize(
            (canvas.shape[1] * 4, canvas.shape[0] * 4), Image.Resampling.NEAREST
        )
        source_picture = Image.fromarray(rgb[box[1] : box[3], box[0] : box[2]]).resize(
            picture.size, Image.Resampling.NEAREST
        )
        width = 1020
        legend_height = 110 + len(side["candidate_layers"]) * 23
        panel = Image.new(
            "RGB",
            (picture.width * 2 + width, max(picture.height + 40, legend_height + 320)),
            "white",
        )
        panel.paste(source_picture, (0, 40))
        panel.paste(picture, (picture.width, 40))
        draw = ImageDraw.Draw(panel)
        draw.text((8, 8), "SOURCE 4x", fill="black", font=font)
        draw.text((picture.width + 8, 8), "CANDIDATE LAYERS 4x", fill="black", font=font)
        left = picture.width * 2 + 14
        draw.text(
            (left, 8),
            f"SIDE {side['index']} | selected {side['selected_layer_id']} PROVISIONAL | original crop {box}",
            fill="black",
            font=font,
        )
        draw.text(
            (left, 30),
            "bin vs fitted midpoint inward / peak N / coverage / raw drop / polarity / score / criterion",
            fill="black",
            font=font,
        )
        for i, layer in enumerate(side["candidate_layers"]):
            raw = layer["raw_evidence"]
            ink = (0, 145, 245) if layer["selected"] else color(i)
            message = (
                f"{'*' if layer['selected'] else ' '} {layer['id']:>3} bin={layer['density_peak_offset_inward_pixels']:5.1f} fit={raw.get('offset_at_profile_median_inward_pixels', 0):5.1f} "
                f"N={layer['density_peak_count']:4} cov={layer['coverage']:.2f} "
                f"drop={raw.get('signed_inward_drop_gray', 0):6.1f} pol={raw.get('gradient_polarity_fraction', 0):.2f} "
                f"score={layer['support_score']:5.1f} {'PASS' if layer['physical_criterion_passed'] else 'reject'}"
            )
            draw.text((left, 58 + i * 23), message, fill=ink, font=font)
        y = legend_height
        draw.text(
            (left, y),
            "Median normal profile: black=original gray, blue=working; 0-255 code values",
            fill="black",
            font=font,
        )
        plot_box = (left + 40, y + 30, panel.width - 30, y + 220)
        draw.rectangle(plot_box, outline="gray")
        profile = side["normal_profile"]
        low, high = profile[0]["offset_inward_pixels"], profile[-1]["offset_inward_pixels"]

        def xy(
            offset: float, value: float, bounds: Any = plot_box, lo: float = low, hi: float = high
        ) -> tuple[float, float]:
            return (
                bounds[0] + (offset - lo) / (hi - lo) * (bounds[2] - bounds[0]),
                bounds[3] - value / 255 * (bounds[3] - bounds[1]),
            )

        for key, profile_ink in (("raw_median_gray", "black"), ("working_median_gray", "blue")):
            points = [xy(p["offset_inward_pixels"], p[key]) for p in profile if p[key] is not None]
            if len(points) > 1:
                draw.line(points, fill=profile_ink, width=2)
        for i, layer in enumerate(side["candidate_layers"]):
            offset = layer["raw_evidence"].get(
                "offset_at_profile_median_inward_pixels", layer["density_peak_offset_inward_pixels"]
            )
            x, _ = xy(offset, 0)
            layer_ink = (0, 145, 245) if layer["selected"] else color(i)
            draw.line((x, plot_box[1], x, plot_box[3]), fill=layer_ink, width=1)
            draw.text((x, plot_box[3] + 3 + (i % 3) * 13), layer["id"], fill=layer_ink, font=font)
        for tick in (low, 0, high):
            x, _ = xy(tick, 0)
            draw.text((x - 12, plot_box[3] + 48), f"{tick:g}", fill="black", font=font)
        for tick in (0, 128, 255):
            _, y_tick = xy(low, tick)
            draw.text((plot_box[0] - 32, y_tick - 7), str(tick), fill="black", font=font)
        name = f"{prefix}-side-{side['index']}-zoom.png"
        save(folder / name, panel)
        artifacts["side_zooms"].append(
            {
                "side_index": side["index"],
                "path": name,
                "crop_box_original_pixels": box,
                "magnification": 4,
                "display_panels": [
                    "unannotated_source",
                    "candidate_layers",
                    "legend_and_normal_profile",
                ],
            }
        )
    for index, point in enumerate(detection["geometry"]["corners_pixels"]):
        box = box_for(np.array([point]), rgb.shape, 65)
        canvas = rgb[box[1] : box[3], box[0] : box[2]].copy()
        for side_index in ((index - 1) % 4, index):
            mark_layers(canvas, detection["sides"][side_index], box)
        location = tuple(np.rint(np.asarray(point) - box[:2]).astype(int))
        cv2.circle(canvas, location, 4, (245, 20, 200), 1)
        picture = Image.fromarray(canvas).resize(
            (canvas.shape[1] * 4, canvas.shape[0] * 4), Image.Resampling.NEAREST
        )
        source_picture = Image.fromarray(rgb[box[1] : box[3], box[0] : box[2]]).resize(
            picture.size, Image.Resampling.NEAREST
        )
        panel = Image.new("RGB", (picture.width * 2, picture.height + 50), "white")
        panel.paste(source_picture, (0, 50))
        panel.paste(picture, (picture.width, 50))
        ImageDraw.Draw(panel).text(
            (6, 5),
            f"Corner {index}: SOURCE LEFT / LAYERS RIGHT | theoretical intersection, not observed round corner",
            fill="black",
            font=font,
        )
        name = f"{prefix}-corner-{index}-zoom.png"
        save(folder / name, panel)
        artifacts["corner_zooms"].append(
            {
                "corner_index": index,
                "path": name,
                "crop_box_original_pixels": box,
                "magnification": 4,
                "display_panels": ["unannotated_source", "candidate_layers"],
            }
        )
    return artifacts
