"""Offline evaluation of committed historical captures; no scanner or S2.2 calls.

Run python -m spectra_boundary.controlled_evaluation --data-root local_data
--output NEW_DIRECTORY. Existing outputs are never overwritten.
"""

from __future__ import annotations

import argparse
import html
import json
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from spectra_pipeline.contracts import physical_report
from spectra_scanner.common import AgentError, write_json_new
from spectra_scanner.storage import sha256_file

from .analysis import overlay, save_png
from .config import configuration
from .controlled_detector import detect
from .controlled_layers import VERSION, select_layers
from .detector import detect as frozen_detect
from .diagnostics import write_zooms


def evaluate(data_root: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    protected = {}
    inventory = sorted(p for p in data_root.rglob("metadata.json") if "captures" in p.parts)
    for metadata in inventory:
        value = json.loads(metadata.read_text(encoding="utf-8"))
        if value.get("complete") is not True:
            continue
        image = metadata.parent / value["original"]
        for path in (metadata, image):
            protected[str(path.resolve())] = sha256_file(path)
        if sha256_file(image) != value["sha256"]:
            raise ValueError(f"Original integrity failed: {image}")
        entry: dict[str, Any] = {
            "image": str(image.resolve()),
            "metadata": str(metadata.resolve()),
            "sha256": value["sha256"],
            "modes": {},
        }
        entries.append(entry)
        folder = output / f"capture-{len(entries):03d}"
        folder.mkdir()
        entry["output"] = str(folder.resolve())
        with Image.open(image) as source:
            rgb = np.asarray(source.convert("RGB")).copy()
            dpi = source.info.get("dpi")
        for mode in ("frozen", "phase1", "phase2"):
            if mode == "frozen":
                detection, _, accepted, rejected = frozen_detect(rgb, dpi, configuration({}))
            else:
                detection, _, accepted, rejected = detect(
                    rgb,
                    dpi,
                    configuration({}),
                    layer_selector=partial(select_layers, support_reassignment=mode == "phase2"),
                )
            report = {
                "schema_version": 1,
                "kind": "single_image",
                "algorithm_version": "0.2.0" if mode == "frozen" else VERSION,
                "experimental_phase": mode,
                "configuration": configuration({}),
                "source": {"path": str(image.resolve()), "sha256": value["sha256"]},
                "status": detection["status"],
                "baseline": detection,
                "original_hash_verified_after_analysis": sha256_file(image) == value["sha256"],
                "physical_accuracy_verified": False,
            }
            path = folder / f"{mode}.json"
            write_json_new(path, report)
            # Never submit experimental geometry as frozen 0.2.0. Actual pipeline
            # contract must refuse the new version even if experimental status succeeds.
            gate = "not_submitted"
            if mode != "frozen":
                try:
                    physical_report(path, image)
                except AgentError as exc:
                    gate = exc.status
                else:
                    raise AssertionError("Experimental report escaped version gate")
            save_png(folder / f"{mode}-overlay.png", overlay(rgb, detection, accepted, rejected))
            write_json_new(
                folder / f"{mode}-support.json",
                {"accepted_pixels": accepted.tolist(), "rejected_edge_pixels": rejected.tolist()},
            )
            # Detailed zooms are generated for every historical capture, not only D/E.
            write_zooms(rgb, detection, folder, mode)
            summary = {
                "status": detection["status"],
                "pipeline_gate": gate,
                "validation": detection.get("geometry", {}).get("validation"),
                "sides": [],
            }
            for side in detection.get("sides", []):
                chosen = next(x for x in side["candidate_layers"] if x["selected"])
                summary["sides"].append(
                    {
                        "index": side["index"],
                        "selected": chosen["id"],
                        "line_abc": side["line_abc"],
                        "coverage": side["coverage"],
                        "continuity": chosen["raw_evidence"].get("strong_transition_fraction"),
                        "criterion_failures": chosen["criterion_failures"],
                        "ambiguity": side["ambiguity_reasons"],
                        "reassignment": chosen.get("support_reassignment"),
                    }
                )
            entry["modes"][mode] = summary
        print(f"Evaluated {len(entries)}/{len(inventory)}: {image}", flush=True)
    changed = [name for name, digest in protected.items() if sha256_file(Path(name)) != digest]
    result = {
        "algorithm_version": VERSION,
        "captures": entries,
        "protected": protected,
        "changed_files": changed,
        "integrity_verified": not changed,
        "physical_accuracy_verified": False,
        "reference_limitation": "No independent human-reviewed physical-boundary reference supplied; printed-frame annotations are not physical-edge references.",
    }
    write_json_new(output / "evaluation.json", result)
    rows = []
    for i, entry in enumerate(entries, 1):
        links = " ".join(
            f'<a href="capture-{i:03d}/{mode}-overlay.png">{mode} overlay</a>'
            for mode in entry["modes"]
        )
        rows.append(f"<li>{html.escape(entry['image'])}<br>{links}</li>")
    with (output / "index.html").open("x", encoding="utf-8") as stream:
        stream.write(
            '<!doctype html><meta charset="utf-8"><title>Controlled S2.1 evaluation</title>'
            "<h1>Experimental comparisons; physical accuracy unverified</h1><ul>"
            + "".join(rows)
            + "</ul>"
        )
    if changed:
        raise ValueError(f"Protected captures changed: {changed}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.data_root, args.output)
