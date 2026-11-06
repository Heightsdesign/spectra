"""Render completed V2 evidence without running or modifying any detector."""

import argparse
import csv
import html
import json
from pathlib import Path

from PIL import Image


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    ev = out / "evaluation"
    evaluation = read(ev / "evaluation.json")
    captures = [(s, read(Path(s["output"]) / "regions.json")) for s in evaluation["summaries"]]
    tritox = [(s, d) for s, d in captures if d["hypotheses"]]
    first = tritox[0][1]
    trio = {"frame-0000", "frame-0003", "frame-0006"}
    relevant = [p for p in first["comparisons"] if set(p["hypotheses"]) <= trio]
    post = read(ev / "post-reference-evaluation.json")
    errors = {h["hypothesis"]: h["mean_absolute_px"] for h in post["reference_metrics"]}
    sensitivity = []
    discordant = []
    for s, d in tritox:
        for p in d["comparisons"]:
            ranges = [
                c["leave_one_block_out_median_range"]
                for v in p["views"]
                for c in v["contextual_evidence"]
            ]
            sensitivity.append(
                dict(
                    image_sha256=s["image_sha256"],
                    hypotheses=p["hypotheses"],
                    preferred=p["preferred"],
                    reason=p["reason"],
                    available=p["available"],
                    assignment_signs=[v["region_assignment_sign"] for v in p["views"]],
                    contextual_margin_range=[min(r[0] for r in ranges), max(r[1] for r in ranges)]
                    if ranges
                    else None,
                )
            )
    for p in first["comparisons"]:
        if p["preferred"] and errors[p["preferred"]] > min(errors[h] for h in p["hypotheses"]):
            discordant.append(
                dict(
                    hypotheses=p["hypotheses"],
                    preferred=p["preferred"],
                    preferred_reference_mae=errors[p["preferred"]],
                    alternative_reference_mae=min(errors[h] for h in p["hypotheses"]),
                )
            )
    with (out / "sensitivity-summary.json").open("x") as f:
        json.dump(sensitivity, f, indent=2)
    with (out / "post-reference-failure-cases.json").open("x") as f:
        json.dump(discordant, f, indent=2)
    with (out / "region-measurements.csv").open("x", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "capture_sha256",
                "pair",
                "different_side",
                "native_pixels",
                "luminance_p10",
                "luminance_p50",
                "luminance_p90",
                "highpass_rms",
                "edge_density_8",
                "edge_density_16",
                "edge_density_32",
                "conditional_preference",
            ]
        )
        for s, d in tritox:
            for p in d["comparisons"]:
                v = next((v for v in p["views"] if "appearance" in v), None)
                if v:
                    a = v["appearance"]
                    w.writerow(
                        [
                            s["image_sha256"],
                            " / ".join(p["hypotheses"]),
                            p["different_sides"][0],
                            a["native_pixel_count"],
                            *a["luminance_p10_p50_p90"],
                            a["highpass_rms"],
                            *[a["edge_density"][str(t)] for t in [8, 16, 32]],
                            p["preferred"],
                        ]
                    )
    # Native-pixel context overview retained separately from tinted region crops.
    with Image.open(out / "phase1-top-regions.png") as image:
        image.crop((0, 0, 1800, 230)).save(out / "phase1-context-compact.png")
    colors = ["#1966bc", "#d75b0c", "#238b45"]
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="930"><rect width="1500" height="930" fill="white"/><style>text{font:12px sans-serif}</style>'
    ]
    for row, p in enumerate(relevant):
        for col, common in enumerate([1, 2, 3]):
            x = col * 500 + 45
            y = row * 300 + 45
            svg.append(
                f'<text x="{x}" y="{y - 20}">{" / ".join(p["hypotheses"])}; context side {common}</text>'
            )
            svg.append(
                f'<rect x="{x}" y="{y}" width="420" height="200" fill="#fafafa" stroke="#aaa"/>'
            )
            for tick in [-1, 0, 1]:
                yy = y + 100 - tick * 90
                svg.append(
                    f'<line x1="{x}" x2="{x + 420}" y1="{yy}" y2="{yy}" stroke="#ccc"/><text x="{x - 25}" y="{yy}">{tick}</text>'
                )
            for i, (_, d) in enumerate(tritox):
                q = next(q for q in d["comparisons"] if q["hypotheses"] == p["hypotheses"])
                v = next(v for v in q["views"] if v["trim_px"] == 2 and v["span"] == [0.18, 0.82])
                c = next(c for c in v["contextual_evidence"] if c["context_side"] == common)
                points = " ".join(
                    f"{x + 15 + k * 35},{y + 100 - m * 90:.3f}"
                    for k, m in enumerate(c["block_margins"])
                )
                svg.append(
                    f'<polyline points="{points}" stroke="{colors[i]}" stroke-width="2" fill="none"/>'
                )
            svg.append(
                f'<text x="{x}" y="{y + 225}">12 along-side blocks; positive = interior appearance</text>'
            )
    svg.append("</svg>")
    with (out / "region-context-margins.svg").open("x", encoding="utf-8") as f:
        f.write("".join(svg))
    # Explicitly inventory additional available evidence with no valid hypotheses.
    root = Path.cwd()
    additional = []
    scored = {s["image_sha256"] for s in evaluation["summaries"]}
    for p in sorted((root / "local_data/s2_2b").glob("*/report.json")):
        d = read(p)
        sha = d.get("source", {}).get("sha256", d.get("inputs", {}).get("image_sha256"))
        additional.append(
            dict(
                report=str(p),
                status=d["status"],
                hypotheses=len(d.get("frame_evaluation", {}).get("hypotheses", [])),
                same_original_already_scored=sha in scored,
                error=d.get("error"),
            )
        )
    for p in sorted((root / "local_data/rd_pipeline/runs").glob("20261019T113*/manifest.json")):
        d = read(p)
        additional.append(
            dict(
                pipeline_manifest=str(p),
                status=d["status"],
                reason="No existing S2.2 hypotheses; preserve upstream block, do not generate substitutes",
            )
        )
    with (out / "additional-capture-inventory.json").open("x") as f:
        json.dump(additional, f, indent=2)
    lines = [
        "# S2.2 semantic V2 — competing-frame regions",
        "",
        "**Recommendation: REVISE before semantic selection; retain the region diagnostics.** V2 conditionally resolves the three V1 leaders in favor of frame-0000 on all three Tritox captures, but it does not establish a general intended-frame selector. The full nine-hypothesis set remains abstained. Existing S2.1/S2.2 statuses, criteria and gates are unchanged.",
        "",
        "## Phase 1: exact source of ambiguity",
        "",
        "frame-0000, frame-0003 and frame-0006 have identical right-0, bottom-1 and left-0 geometry; their only differing side is top (top-0/top-1/top-2). Top-0 to top-1 spans about 135 px of the name/header area; top-1 to top-2 spans about 12 px of the pale artwork-frame stripe. Top-0 to top-2 includes both, about 147 px. These separations repeat across all three captures. Identification as header/artwork stripe comes from visual context, not an automatic OCR or material classifier. Some BASE/HP context lies outside the central measured span.",
        "",
        "V1 rewards the continuous high-contrast name/artwork boundary even though its full exterior corridor includes the header. Its continuity/region-difference objectives compete with the much stronger global-band consistency of frame-0000. Narrow collars see local transitions; marginal pooled descriptors lose the spatial meaning of the region between the alternatives.",
        "",
        "The following measurements use native integer RGB pixels, central physical-side fractions .18–.82, with 2 px removed from each disputed boundary, for capture 1. Luminance is an uncalibrated RGB code-value projection, not optical radiometry. Texture and derivatives are computed in derived arrays only.",
        "",
        "| Region between hypotheses | Median separation px | Native pixels | Luminance p10 / p50 / p90 | High-pass RMS | Edge density >=8 / >=16 / >=32 |",
        "|---|---:|---:|---|---:|---|",
    ]
    for p in relevant:
        v = next(v for v in p["views"] if "appearance" in v)
        a = v["appearance"]
        lines.append(
            f"| {' / '.join(p['hypotheses'])} | {p['midpoint_separation_px']:.3f} | {a['native_pixel_count']} | "
            + " / ".join(f"{x:.3f}" for x in a["luminance_p10_p50_p90"])
            + f" | {a['highpass_rms']:.3f} | "
            + " / ".join(f"{a['edge_density'][str(t)]:.4f}" for t in [8, 16, 32])
            + " |"
        )
    lines += [
        "",
        "The header is darker/red-brown and contains visible printed glyphs and decoration; the stripe is lighter and near-gray. Header versus stripe median RGB is approximately (96,55,46) versus (171,165,163); complete percentiles and histograms are in the native-region JSON, not inferred from overlays. Across 12 along-side blocks, capture-1 median luminance is 58.6–86.0 in the header and 147.4–201.7 in the stripe: neither is a uniform band.",
        "",
        "The stripe has larger high-pass RMS and more weak gradients than the header, but fewer gradients above 16 and none above 32. Thus raw texture/edge density does not provide a stable semantic ordering: interpretation reverses with gradient threshold. At threshold 16, about 29.6% of header edge tangents lie within 10 degrees of the physical-side direction, versus 50.0% in the stripe. Edge directions are descriptive; the narrow stripe has far fewer edge pixels, and neither orientation nor texture proves text, border or artwork.",
        "",
        "**Useful discriminative observation:** the disputed header looks like the interior of the three unchanged borders rather than their exterior band. The narrow gray stripe instead resembles their exterior band, despite being an artwork decoration. This supports testing appearance assignment, while also exposing its semantic aliasing failure in advance. Color alone, smoothness, edge strength, rectangularity and outermost position remain insufficient.",
        "",
        "## Phase 2: isolated region-aware diagnostic",
        "",
        "The specification in experiments/frame_semantics/REGION_V2.md was written after the above region inspection and before V2 evaluation. semantic_regions.py is additive; semantic V1 was not changed. Source RGB pixels are selected with bounded native raster masks between existing fitted equations. Twelve blocks preserve along-side variation. Context uses separate 2–8 px collars on each of the three geometrically identical sides.",
        "",
        "For each block and each unchanged side, report marginal RGB histogram total-variation distance to exterior and interior prototypes. Margin = distance to exterior minus distance to interior: positive supports assigning the disputed region to the interior, negative to the exterior. A region matching the band can favor the inward boundary; there is no outermost prior. Geometry equality, not candidate identity, identifies unchanged sides. IDs label records only.",
        "",
        "A pairwise preference requires consistent strict signs for all three context sides, every leave-one-block-out median and all six settings (1/2/3 px trims, spans .18–.82/.22–.78). Jackknife ranges are sensitivity summaries, not statistical confidence intervals. Mixed evidence or insufficient pixels produces abstention. Pairs differing on multiple sides are confounded and are not forced into this single-strip model. No score weights or acceptance thresholds were changed or tuned after seeing results.",
        "",
        "## Phase 3: evaluation and stability",
        "",
        "All 26 V1 validation report entries were traced, deduplicating to 12 original images. Each Tritox capture has nine existing hypotheses and 36 pairs: 18 differ on one side, 18 on two sides. Of 18 measurable pairs, 11 have stable conditional preferences and 7 remain mixed. The other nine distinct captures have no existing complete hypotheses and retain unavailable/abstained results. No new candidates or downstream reports were fabricated. Additional standalone Card D evidence fails upstream geometry; recent Card E runs remain blocked. Additional-capture inventory records these exclusions.",
        "",
        "| V1-leader comparison | Conditional region-model preference | Meaning |",
        "|---|---|---|",
        "| frame-0000 vs frame-0003 | frame-0000 | Header assigned to interior |",
        "| frame-0000 vs frame-0006 | frame-0000 | Header-plus-stripe assigned to interior |",
        "| frame-0003 vs frame-0006 | frame-0006 | Gray artwork stripe assigned to exterior; semantic alias |",
        "",
        "These three relations hold in all three captures and all six trim/span settings. Existing V1 registration supports 27 matched hypotheses across three Tritox capture pairs; V2 pairwise preferences/unavailability agree for all 108 matched pair comparisons (including confounded pairs). This is stable behavior, not independent semantic truth. Registration holdout p95 was 0.527/0.611/0.410 px and maximum matched-corner discrepancy 0.772 px, as preserved in V1. No new registration or manual alignment was fitted.",
        "",
        "Within the pre-existing V1 nondominated subset only, frame-0000 wins directly against both alternatives. Across all nine, it has four direct wins, zero losses and four unassessed multi-side comparisons; that is not a complete ranking. No transitive preference was invented, and wins are not converted into confidence scores. All results keep semantic_selection=null and abstained=true.",
        "",
        "| Hypothesis | Pairwise wins | Losses | Mixed / unavailable |",
        "|---|---:|---:|---:|",
    ]
    for h in first["hypotheses"]:
        lines.append(
            f"| {h['hypothesis_id']} | {h['pairwise_wins']} | {h['pairwise_losses']} | {h['unresolved_or_unavailable']} |"
        )
    lines += [
        "",
        "## Post-scoring reference evaluation and failure cases",
        "",
        "Region reports and region-scores-complete.json were written before the manual comparison was read. Manual geometry, candidate indices and reference error never enter the appearance rule. The reference remains exposed rather than blind; development already knew previous Tritox results, so this is not a held-out test.",
        "",
        "The reference supports frame-0000 (0.871 px MAE), followed by frame-0003 (34.481) and frame-0006 (37.461). V2 agrees about the best member of that trio, but **4 of its 11 direct pairwise preferences in this annotated capture favor the larger-reference-error alternative**. Those errors concern already wrong alternatives, not four accepted outputs, and cannot be interpreted as a production false-positive rate.",
        "",
        "| Pair | V2 preference | Preferred manual MAE px | Better alternative MAE px |",
        "|---|---|---:|---:|",
    ]
    for d in discordant:
        lines.append(
            f"| {' / '.join(d['hypotheses'])} | {d['preferred']} | {d['preferred_reference_mae']:.3f} | {d['alternative_reference_mae']:.3f} |"
        )
    lines += [
        "",
        "The stripe failure is concrete: a decorative artwork frame shares the gray appearance of the true enclosing band. Common-side collars are also local and can reflect text or artwork, so they do not guarantee a correct global semantic model. Other failure modes include multi-side changes, narrow disputed strips, missing contextual contrast, conflicting side prototypes, colour/foil/scanner shifts, and marginal histograms losing spatial/color correlations. Histograms do not read the text or certify intended design.",
        "",
        "## Verification and recommendation",
        "",
        "REVISE before any semantic-selection integration; RETAIN V2 as a bounded region diagnostic. It explains why the original three-way ambiguity arose and supplies consistent conditional evidence for frame-0000 in this example. It does not support replacing the existing evaluator or gates, propagating a subset winner to all nine hypotheses, or claiming broad semantic accuracy. No additional implementation was added after the failure cases were observed.",
        "",
        "Automated tests exercise both directions of preference (including a case favoring the inward boundary), neutral/conflicting context, renamed candidates, source/reference-metadata independence, immutable inputs, multi-side confounding, truncated searches, narrow regions, empty hypotheses, cyclic preferences and known edge orientation. The full suite passed: 348 tests, with 3 unchanged browser tests deselected. All 11 new region tests passed; Ruff check/format and mypy on the two runtime modules passed. Detailed results are recorded in tests-final2.xml and final-verification.json. An initial conflict fixture failed because its patch did not cover the full sampled collar; only that fixture was corrected.",
        "",
        f"Exact output root: `{out}`.",
        "",
        "- [Native header context](phase1-context-compact.png) and [Phase 1 numerical inventory](phase1.json).",
        "- [Spatial contextual margins across captures](region-context-margins.svg). Blue/orange/green indicate captures; positive means interior appearance.",
        "- [All pair-region measurements CSV](region-measurements.csv), [sensitivity summary](sensitivity-summary.json), [post-reference failures](post-reference-failure-cases.json).",
        "- evaluation/capture-003,004,005/regions.json and regions.png: every pair/view, RGB/luminance histograms, texture, edge orientation, along-side blocks and tinted native crops. Other capture directories explicitly record no available hypotheses.",
        "- evaluation/evaluation.json, stability.json, region-scores-complete.json, post-reference-evaluation.json, integrity.json and additional-capture-inventory.json.",
        "- [Specification and reproduction command](../../../experiments/frame_semantics/REGION_V2.md).",
        "",
        "Originals, references, frozen S2.1, existing S2.2 validity criteria and all semantic V1 code/diagnostics are preserved. All outputs remain experimental review_required without acceptance or grading promotion. No commits or cleanup.",
    ]
    # The spec link is absolute so it remains valid from this local output root.
    lines = [
        line.replace(
            "../../../experiments/frame_semantics/REGION_V2.md",
            (root / "experiments/frame_semantics/REGION_V2.md").as_posix(),
        )
        for line in lines
    ]
    with (out / "REPORT.md").open("x", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    links = "".join(
        f'<li><a href="{Path(s["output"]).relative_to(out).as_posix()}/regions.png">{html.escape(Path(s["output"]).name)}</a> - {s["hypotheses"]} hypotheses; conditional subset leader {s["conditional_v1_subset_leader"]}</li>'
        for s in evaluation["summaries"]
    )
    page = (
        '<html><meta charset="utf-8"><title>S2.2 competing regions V2</title><style>body{font:16px system-ui;margin:24px}img{max-width:100%}</style><h1>V2: conditional region evidence, full-set abstention</h1><p><a href="REPORT.md">Evaluation report</a> | <a href="region-measurements.csv">Native-region measurements</a></p><img src="phase1-context-compact.png"><img src="region-context-margins.svg"><ul>'
        + links
        + "</ul></html>"
    )
    with (out / "index.html").open("x", encoding="utf-8") as f:
        f.write(page)
    print(out / "REPORT.md")


if __name__ == "__main__":
    main()
