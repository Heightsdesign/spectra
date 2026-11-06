"""Render completed diagnostic evidence; never runs extraction or changes inputs."""

import argparse
import csv
import hashlib
import html
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ev, out = args.evaluation.resolve(), args.output.resolve()
    evaluation = read(ev / "evaluation.json")
    records = evaluation["records"]
    post = read(ev / "post-reference-evaluation.json")
    reference = read(Path(post["reference_comparison"]))
    key = reference["provenance"]["image_sha256"]
    tritox = [r for r in records if r["image_sha256"] == key][0]
    first = read(Path(tritox["output"]) / "semantic.json")
    unique = {}
    for r in records:
        unique.setdefault(r["image_sha256"], r)
    series = reference["provenance"]["s2_1"]["path"]
    group = Path(series).parent.parent.name
    matching = [
        r
        for r in unique.values()
        if group in read(Path(r["output"]) / "semantic.json")["source_provenance"]["s2_1"]["path"]
    ]
    objectives = first["objectives"]
    sensitivity = []
    for r in unique.values():
        data = read(Path(r["output"]) / "semantic.json")
        for row in data["hypotheses"]:
            views = [v for v in row["views"].values() if v["objectives"] is not None]
            sensitivity.append(
                dict(
                    image_sha256=r["image_sha256"],
                    hypothesis=row["hypothesis_id"],
                    fronts_by_view=[v["pareto_front"] for v in views],
                    objective_ranges={
                        k: [
                            min(v["objectives"][k] for v in views),
                            max(v["objectives"][k] for v in views),
                        ]
                        for k in objectives
                    }
                    if views
                    else {},
                )
            )
    stability = read(ev / "stability.json")
    matches = [m for s in stability for m in s["associations"] if m["reliable_match"]]
    write(
        out / "sensitivity-summary.json",
        dict(
            per_capture=sensitivity,
            reliable_matches=len(matches),
            cross_capture_max_absolute_objective_change={
                k: max(abs(m["objective_changes_source_minus_target"][k]) for m in matches)
                for k in objectives
            },
            matched_front_changes=sum(
                len(set(m["pareto_front_source_target"])) > 1 for m in matches
            ),
        ),
    )
    with (out / "descriptor-matrix.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["report", "image_sha256", "hypothesis", "view", "pareto_front", *objectives]
        )
        for r in records:
            data = read(Path(r["output"]) / "semantic.json")
            for h in data["hypotheses"]:
                for view, v in h["views"].items():
                    writer.writerow(
                        [
                            r["report"],
                            r["image_sha256"],
                            h["hypothesis_id"],
                            view,
                            v["pareto_front"],
                            *[(v["objectives"] or {}).get(k) for k in objectives],
                        ]
                    )
    colors = ["#1966bc", "#d75b0c", "#238b45"]
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="970"><rect width="1200" height="970" fill="white"/><style>text{font:13px sans-serif}</style>'
    ]
    for j, k in enumerate(objectives):
        y = 35 + j * 235
        svg.append(
            f'<text x="20" y="{y}">{k}: larger is more compatible (not semantic correctness)</text>'
        )
        for tick in [0, 0.25, 0.5, 0.75, 1]:
            yy = y + 180 - tick * 150
            svg.append(
                f'<line x1="70" x2="1160" y1="{yy}" y2="{yy}" stroke="#ddd"/><text x="25" y="{yy}">{tick:g}</text>'
            )
        for i, h in enumerate(first["hypotheses"]):
            x = 120 + i * 120
            svg.append(
                f'<text x="{x - 25}" y="{y + 205}">{h["hypothesis_id"].replace("frame-", "F")}</text>'
            )
            for c, r in enumerate(matching):
                d = read(Path(r["output"]) / "semantic.json")
                v = next(v for v in d["hypotheses"] if v["hypothesis_id"] == h["hypothesis_id"])[
                    "views"
                ]["0.0:full"]["objectives"][k]
                yy = y + 180 - v * 150
                svg.append(
                    f'<circle cx="{x + (c - 1) * 7}" cy="{yy:.3f}" r="4" fill="{colors[c]}"/>'
                )
    svg.append("</svg>")
    with (out / "descriptor-comparison.svg").open("x", encoding="utf-8") as stream:
        stream.write("".join(svg))
    lines = [
        "# S2.2b semantic compatibility V1 — evaluation",
        "",
        "**Recommendation: REVISE as a semantic selector; retain the descriptors as diagnostic evidence only.** V1 does not uniquely discriminate the intended Tritox frame. Preserve abstention and every existing gate. No parameter was tuned after the initial results.",
        "",
        "## Scope and preserved architecture",
        "",
        "Additive implementation: spectra_frame_evaluation/semantic.py and semantic_validation.py. Existing S2.2b analysis/evaluation code, S2.2a generator, frozen S2.1 and S2.2c are unchanged. The module emits a different diagnostic report kind/version, never an eligible physical or printed-frame analysis. All outputs review_required, automatic_acceptance=false, measurements=null. Existing selected IDs and criteria are recorded, not replaced.",
        "",
        f"Evaluated all **{len(records)} existing validation reports**, covering **{evaluation['unique_captures']} distinct original captures**. Repeated historical reports are not independent observations. Three Tritox originals contain nine hypotheses each; the other nine originals have no four-sided hypotheses and truncated candidate generation. The module does not invent candidates for them. Thus semantic discrimination is evaluated on 27 distinct candidate frames from three captures of one card, not 26 independently labelled cards.",
        "",
        "## Predeclared method and leakage control",
        "",
        "The specification in scanner_agent/experiments/frame_semantics/README.md was written before semantic ordering was computed. It is motivated by already known Tritox findings, so this is a development experiment, not a held-out benchmark. The extraction API takes only original RGB pixels and existing S2.2b geometry. It does not accept references, candidate error, index preferences, size, symmetry or outermost rank.",
        "",
        "96 original-pixel along-side probes; 2/4/8 px collars; 16 physical-to-frame corridor positions; 16-bin marginal RGB histograms. Descriptors are continuity, narrow exterior-collar photometric consistency, shared global-band appearance, and interior/exterior difference. Values are descriptive RGB code-value statistics, not calibrated color or physical measurements. Global-band consistency is a hypothesis about a shared enclosing printed band, not recognition of text/artwork or proof of design intent.",
        "",
        "Pareto fronts preserve competing objectives without learned weights or tie-breaking. A diagnostic preference would require the same unique leader across all nine phase/subset views and complete untruncated evidence. Existing production validity criteria are never replaced. scores-complete.json was written before the manual-comparison report was loaded for post-evaluation. The manual reference was not used for extraction, ordering or cross-capture association.",
        "",
        "## Tritox descriptors and post-scoring reference evaluation",
        "",
        "| Hypothesis | Continuity | Collar consistency | Global-band consistency | Region difference | Pareto front | Manual MAE px (post hoc) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    postmap = {h["hypothesis_id"]: h for h in post["hypotheses"]}
    for h in first["hypotheses"]:
        view = h["views"]["0.0:full"]
        o = view["objectives"]
        p = postmap[h["hypothesis_id"]]
        lines.append(
            f"| {h['hypothesis_id']} | "
            + " | ".join(f"{o[k]:.6f}" for k in objectives)
            + f" | {view['pareto_front']} | {p['reference_mae_px']:.3f} |"
        )
    lines += [
        "",
        "**Partial discrimination, not a supported unique ranking:** frame-0000 has by far the strongest global-band compatibility (0.856 vs <=0.310 for the others). However frame-0003 has stronger transition continuity and region distinction; frame-0006 also has stronger continuity. All three are nondominated. Their manual-reference errors, read only afterward, are 0.871, 34.481 and 37.461 px. The six remaining hypotheses fall on fronts 2–3. Photometric evidence can demote alternatives, but continuity/contrast still rewards local artwork/name-region transitions. Choosing global-band consistency alone now would be outcome-driven feature selection; V1 does not do that.",
        "",
        "## Stability and sensitivity",
        "",
        "All three Tritox captures retain exactly the same first front {frame-0000, frame-0003, frame-0006} at every phase (-0.5/0/+0.5 px) and full/even/odd profile subset. Every matched hypothesis also retains its full-profile front between captures. Stability establishes descriptor repeatability on these captures, not correctness.",
        "",
        "All 12 within-series capture pairs pass the explicit print-registration guards. Tritox pair held-out p95 residuals are 0.527/0.611/0.410 px. All nine hypotheses match across each of its three pairs: 27 mutual associations, maximum corner discrepancy 0.772 px. Other series have no hypotheses to associate despite usable registration. Associations use geometry only after scoring; no reference geometry is used.",
        "",
        "| Maximum absolute objective change across reliably matched captures | Value |",
        "|---|---:|",
    ]
    for k in objectives:
        lines.append(
            f"| {k} | {max(abs(m['objective_changes_source_minus_target'][k]) for m in matches):.6f} |"
        )
    lines += [
        "",
        "Registration holdout is conditional on RANSAC inliers and the similarity model; it is not calibrated edge uncertainty. Pair membership uses exact upstream series, not inferred card labels. Full matrices, residuals, spatial support and matching guards are in final-evaluation/stability.json. Sampling-phase ranges for every hypothesis are in sensitivity-summary.json and the CSV. No favourable phase was chosen.",
        "",
        "## Ambiguity, false positives and regressions",
        "",
        "- All 26 reports abstain; no unique diagnostic preference or automatic acceptance is emitted. Existing analytic statuses, selected geometry and gates are unchanged.",
        "- Against the one exposed manual reference, two of three first-front peers are geometrically far from the reviewed intended frame. These are false semantic contenders, not false accepted predictions. A real-card false-positive rate cannot be estimated: the other captures lack independent printed-frame labels or existing complete hypotheses.",
        "- Uniform nested-rectangle and competing-objective synthetic controls retain ambiguity. Histogram/color similarity cannot distinguish visually equivalent printed structures or guarantee a semantic interpretation. Marginal histograms discard spatial/color correlations; foil, printing gradients and scanner changes can confound them.",
        "- Nine distinct non-Tritox captures remain generator-limited: no new semantic evidence, no recovery claim and no improvement claim. Hash preservation and the existing regression suite establish software/gate preservation, not universal detector accuracy.",
        "",
        "## Validation and engineering recommendation",
        "",
        "Automated checks: **337 passed, 3 browser tests deselected**, including 13 new semantic tests. UI code was unchanged; browser regressions were not rerun. Tests cover conflicting objectives, ties, absent/invalid/truncated hypotheses, uniform nested structures, interpolation/domain validity, continuity, order/reference-metadata invariance, immutability, determinism and registration/association refusal. Ruff check/format and mypy for both new modules passed. Final extraction reproduced all 26 initial semantic results without changing ordering.",
        "",
        "**REVISE the semantic-selection approach; retain V1 only as diagnostic instrumentation.** Shared-band evidence is promising but the declared multi-objective rule leaves the intended frame unresolved. Do not introduce an outermost rule, pick frame-0000 by ID, tune feature weights to its manual error or promote a single descriptor based on this example. No automatic selector is integrated. S2.1 review_required and the existing downstream gate remain in force.",
        "",
        "## Outputs and reproduction",
        "",
        f"Exact output root: `{out}`.",
        "",
        "- [Descriptor plot across three Tritox captures](descriptor-comparison.svg). Blue/orange/green are capture 1/2/3; all plots use identical 0–1 scales.",
        "- [Descriptor CSV](descriptor-matrix.csv): every report/hypothesis/view, including side summaries in corresponding semantic.json files.",
        "- [Sensitivity summary](sensitivity-summary.json).",
        "- final-evaluation/capture-NNN/semantic.json and hypotheses.png: all existing-hypothesis descriptors and magenta line overlays, with no manual reference.",
        "- final-evaluation/scores-complete.json, evaluation.json, stability.json, post-reference-evaluation.json and integrity.json.",
        "- tests-final.xml, protected-before.json and final-verification.json.",
        "",
        "From scanner_agent, run into a NEW exclusive output directory:",
        "",
        "```powershell",
        ".\\.venv-analysis\\Scripts\\python.exe -B -m spectra_frame_evaluation.semantic_validation --output local_data\\NEW_SEMANTIC_OUTPUT --reference-comparison local_data\\s2_2c\\compare\\20261019T143930_50e17bd14131403588f099c16d729a38\\report.json",
        "```",
        "",
        "The reference argument is optional and used only after scoring. No reference or original is rewritten. The earlier evaluation/ directory is preserved as development evidence; final-evaluation/ is authoritative. Only additive experimental code/docs/tests and new output artifacts were created; no commit or cleanup.",
    ]
    with (out / "REPORT.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    entries = []
    for r in records:
        folder = Path(r["output"]).relative_to(out).as_posix()
        entries.append(
            f'<tr><td>{html.escape(folder)}</td><td>{r["hypotheses"]}</td><td>{html.escape(str(r["leaders"]))}</td><td><a href="{folder}/semantic.json">JSON</a> <a href="{folder}/hypotheses.png">overlay</a></td></tr>'
        )
    page = (
        '<html><meta charset="utf-8"><title>S2.2b semantic V1</title><style>body{font:16px system-ui;margin:24px}td,th{border:1px solid #aaa;padding:6px}table{border-collapse:collapse}</style><h1>Semantic V1: retain diagnostic evidence, revise selection</h1><p>No unique preference; review_required. Manual reference was used only after scoring.</p><p><a href="REPORT.md">Full report</a> | <a href="descriptor-matrix.csv">CSV</a></p><img src="descriptor-comparison.svg" width="100%"><table><tr><th>Report</th><th>Hypotheses</th><th>Unresolved leaders</th><th>Evidence</th></tr>'
        + "".join(entries)
        + "</table></html>"
    )
    with (out / "index.html").open("x", encoding="utf-8") as stream:
        stream.write(page)
    # Save exact source provenance separately; never mutate completed extraction reports.
    root = Path(__file__).resolve().parents[2]
    sources = [
        root / "spectra_frame_evaluation/semantic.py",
        root / "spectra_frame_evaluation/semantic_validation.py",
        root / "tests/test_frame_semantic.py",
        Path(__file__).resolve(),
        Path(__file__).with_name("README.md"),
    ]
    write(
        out / "source-manifest.json",
        {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
    )
    print(out / "REPORT.md")


if __name__ == "__main__":
    main()
