"""Read-only existing-hypothesis evaluation of the isolated region experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from spectra_reference.inputs import load_bundle, read_json
from spectra_scanner.storage import sha256_file

from .semantic_regions import analyze, axes, normalized, raster
from .semantic_validation import write


def visualize(rgb: Any, evaluation: dict, result: dict, output: Path) -> None:
    physical = np.array(evaluation["physical_corners_pixels"])
    frames = {h["id"]: h for h in evaluation["frame_evaluation"]["hypotheses"]}
    lookup = {c["id"]: c for s in evaluation["sides"] for c in s["candidates"]}
    panels = []
    for number, p in enumerate(result["comparisons"]):
        if not p["available"]:
            continue
        index = p["different_sides"][0]
        _, normal, _ = axes(physical, index)
        lines = [
            normalized(lookup[frames[h]["candidate_ids"][index]]["line_abc"], normal)
            for h in p["hypotheses"]
        ]
        xy, _, valid = raster(physical, index, lines, (0.18, 0.82), rgb.shape)
        da, db = [xy @ line[:2] + line[2] for line in lines]
        mask = valid & (da * db < 0) & (abs(da) > 2) & (abs(db) > 2)
        for common in set(range(4)) - {index}:
            _, n, _ = axes(physical, common)
            line = normalized(
                lookup[frames[p["hypotheses"][0]]["candidate_ids"][common]]["line_abc"], n
            )
            mask &= xy @ line[:2] + line[2] >= 0
        coords = xy[mask]
        if not len(coords):
            continue
        lo = np.maximum(coords.min(axis=0) - 24, 0)
        hi = np.minimum(coords.max(axis=0) + 25, [rgb.shape[1], rgb.shape[0]])
        crop = rgb[lo[1] : hi[1], lo[0] : hi[0]].copy()
        locations = coords - lo
        crop[locations[:, 1], locations[:, 0]] = np.rint(
            0.75 * crop[locations[:, 1], locations[:, 0]] + 0.25 * np.array([0, 180, 255])
        ).astype(np.uint8)
        native = Image.fromarray(crop)
        native.save(output / f"pair-{number:03}-region.png")
        thumb = native.copy()
        thumb.thumbnail((590, 210))
        tile = Image.new("RGB", (600, 300), "white")
        tile.paste(thumb, ((600 - thumb.width) // 2, 20))
        draw = ImageDraw.Draw(tile)
        draw.text((8, 235), " / ".join(p["hypotheses"]) + f" side {index}", fill="black")
        draw.text((8, 255), f"Conditional preference: {p['preferred'] or 'none'}", fill="black")
        draw.text((8, 275), "Cyan tint = disputed region; original pixels unchanged", fill="black")
        panels.append(tile)
        p["region_visualization"] = f"pair-{number:03}-region.png"
    canvas = Image.new("RGB", (1800, max(1, (len(panels) + 2) // 3) * 300), "white")
    for i, tile in enumerate(panels):
        canvas.paste(tile, ((i % 3) * 600, (i // 3) * 300))
    if not panels:
        ImageDraw.Draw(canvas).text(
            (20, 20), "No comparable complete hypotheses: diagnostic abstention.", fill="black"
        )
    canvas.save(output / "regions.png")


def run(v1_manifest: Path, output: Path, reference_comparison: Path | None) -> None:
    output.mkdir(parents=True, exist_ok=False)
    records = read_json(v1_manifest)["records"]
    protected = {str(v1_manifest): sha256_file(v1_manifest)}
    unique: dict[str, dict] = {}
    inventory = []
    for r in records:
        report = Path(r["report"])
        evaluation = read_json(report)
        image = Path(r["image"])
        v1path = Path(r["output"]) / "semantic.json"
        for p in [report, image, v1path, Path(evaluation["boundary_report"]["path"])]:
            protected[str(p)] = sha256_file(p)
        key = r["image_sha256"]
        if key not in unique:
            rgb, evaluation, provenance = load_bundle(image, report)
            v1 = read_json(v1path)
            assert v1["source_provenance"]["image_sha256"] == provenance["image_sha256"] == key
            result = analyze(rgb, evaluation, v1)
            folder = output / f"capture-{len(unique):03}"
            folder.mkdir()
            visualize(rgb, evaluation, result, folder)
            result.update(
                source_provenance=provenance, original_report=str(report), v1_report=str(v1path)
            )
            write(folder / "regions.json", result)
            unique[key] = dict(image_sha256=key, output=str(folder), result=result)
            print(
                f"{len(unique)} captures: {len(result['comparisons'])} pairs; conditional V1-subset leader {result['conditional_leader_v1_subset']}",
                flush=True,
            )
        inventory.append(
            dict(
                report=str(report),
                image_sha256=key,
                region_report=str(Path(unique[key]["output"]) / "regions.json"),
            )
        )
    scores = dict(
        records=inventory,
        unique_captures=len(unique),
        manual_reference_used=False,
        summaries=[{k: v for k, v in r.items() if k != "result"} for r in unique.values()],
    )
    write(output / "region-scores-complete.json", scores)
    stability_path = v1_manifest.parent / "stability.json"
    protected[str(stability_path)] = sha256_file(stability_path)
    stability = []
    for entry in json.loads(stability_path.read_text()):
        source, target = (
            unique[entry["source_sha256"]]["result"],
            unique[entry["target_sha256"]]["result"],
        )
        mapping = {
            a["source_hypothesis"]: a["target_hypothesis"]
            for a in entry["associations"]
            if a["reliable_match"]
        }
        paired = []
        for p in source["comparisons"]:
            if not all(h in mapping for h in p["hypotheses"]):
                continue
            wanted = {mapping[h] for h in p["hypotheses"]}
            q = next((q for q in target["comparisons"] if set(q["hypotheses"]) == wanted), None)
            if q is not None:
                paired.append(
                    dict(
                        source_pair=p["hypotheses"],
                        target_pair=q["hypotheses"],
                        source_preferred=p["preferred"],
                        target_preferred=q["preferred"],
                        preference_agrees=(
                            mapping.get(p["preferred"]) == q["preferred"]
                            if p["preferred"]
                            else q["preferred"] is None
                        ),
                    )
                )
        stability.append(
            dict(
                source_sha256=entry["source_sha256"],
                target_sha256=entry["target_sha256"],
                registration=entry["registration"],
                pairwise_stability=paired,
            )
        )
    write(output / "stability.json", stability)
    post = None
    if reference_comparison:
        comparison = read_json(reference_comparison)
        protected[str(reference_comparison)] = sha256_file(reference_comparison)
        key = comparison["provenance"]["image_sha256"]
        region = unique[key]["result"]
        post = dict(
            reference_read_after_scoring=True,
            manual_reference_used_for_scoring=False,
            reference_comparison=str(reference_comparison),
            prior_exposure="exposed",
            conditional_leader_all=region["conditional_leader_all_hypotheses"],
            conditional_leader_v1_subset=region["conditional_leader_v1_subset"],
            reference_metrics=[
                dict(
                    hypothesis=h["hypothesis_id"],
                    rank=h["rank"],
                    mean_absolute_px=h["aggregate"]["mean_absolute_pixels"],
                )
                for h in comparison["hypotheses"]
            ],
        )
        write(output / "post-reference-evaluation.json", post)
    assert all(sha256_file(Path(p)) == h for p, h in protected.items())
    write(
        output / "evaluation.json",
        dict(
            records=inventory,
            unique_captures=len(unique),
            post_reference_evaluation=post,
            summaries=[
                dict(
                    image_sha256=key,
                    output=r["output"],
                    hypotheses=len(r["result"]["hypotheses"]),
                    pairs=len(r["result"]["comparisons"]),
                    conditional_v1_subset_leader=r["result"]["conditional_leader_v1_subset"],
                    conditional_all_leader=r["result"]["conditional_leader_all_hypotheses"],
                    abstained=r["result"]["abstained"],
                )
                for key, r in unique.items()
            ],
            status="review_required",
            automatic_acceptance=False,
        ),
    )
    write(output / "integrity.json", dict(all_existing_unchanged=True, sha256=protected))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-comparison", type=Path)
    args = parser.parse_args()
    run(args.v1_manifest.resolve(), args.output.resolve(), args.reference_comparison)


if __name__ == "__main__":
    main()
