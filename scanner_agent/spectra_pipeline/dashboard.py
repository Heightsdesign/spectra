from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from spectra_scanner.common import AgentError, identifier, utc_now, write_json_new

from .contracts import read_json

STAGES = ("acquisition", "s2_1", "s2_2a", "s2_2b", "s2_2c")


def escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def link(path: str | Path | None, label: str) -> str:
    if not path:
        return escape(label + " (unavailable)")
    return f'<a href="{escape(Path(path).resolve().as_uri())}">{escape(label)}</a>'


def page(title: str, content: str) -> str:
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src file: data:; style-src \'unsafe-inline\'; base-uri \'none\'"><title>'
        + escape(title)
        + "</title><style>body{background:#141414;color:#eee;font:16px system-ui;margin:24px;max-width:1400px}a{color:#fff;text-decoration:underline}table{border-collapse:collapse;width:100%;margin:16px 0}td,th{text-align:left;border:1px solid #666;padding:9px;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere}img{max-width:100%;height:auto;border:1px solid #777}section{border:1px solid #777;padding:16px;margin:18px 0}.warning{color:#ffda77}.images{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}code{overflow-wrap:anywhere}</style><h1>"
        + escape(title)
        + '</h1><p class="warning">Isolated R&amp;D. Execution completion is not analytical acceptance. No automatic approval, grading or calibrated-accuracy claim.</p>'
        + content
        + "</html>"
    )


def run_dashboard(manifest: dict[str, Any], output: Path) -> None:
    content = f"<p>Run {escape(manifest['run_id'])} | Card {escape(manifest['card_id'])} | Batch {escape(manifest['batch_id'])}</p><p>Pipeline status: <strong>{escape(manifest['status'])}</strong></p>"
    content += "<p>" + link(output.parent / "manifest.json", "Machine-readable manifest") + "</p>"
    content += "<pre>" + escape(json.dumps(manifest.get("image"), indent=2)) + "</pre>"
    if manifest.get("error"):
        content += '<p class="warning">' + escape(manifest["error"]) + "</p>"
    for name in STAGES:
        item = manifest["stages"][name]
        content += f"<section><h2>{escape(name)}: {escape(item['status'])}</h2><p>Execution: {escape(item['execution_status'])} | Analytical result: {escape(item.get('analytical_status'))} | Reused: {escape(item.get('reused', False))}</p>"
        content += "<p>" + escape(item.get("reason", "")) + "</p>"
        if item.get("report"):
            content += "<p>" + link(item["report"], "Source report") + "</p>"
        for key in ("stdout_log", "stderr_log"):
            if item.get(key):
                content += link(item[key], key) + " "
        if item.get("command"):
            content += "<pre>" + escape(json.dumps(item["command"], ensure_ascii=False)) + "</pre>"
        if item.get("error"):
            content += '<pre class="warning">' + escape(item["error"]) + "</pre>"
        if item.get("physical_diagnostics"):
            diagnostics = item["physical_diagnostics"]
            content += (
                "<p>Existing minimum side coverage: <strong>"
                + escape(diagnostics["minimum_side_coverage"])
                + "</strong>. Failed checks: "
                + escape(", ".join(diagnostics["failed_checks"]))
                + "</p>"
            )
            content += "<table><tr><th>Side (report coordinates)</th><th>Coverage</th><th>Minimum</th><th>RMS px</th><th>Ambiguous parallel edge</th><th>Selected layer</th></tr>"
            for side in diagnostics["sides"]:
                content += (
                    "<tr>"
                    + "".join(
                        "<td>" + escape(side.get(key)) + "</td>"
                        for key in (
                            "index",
                            "coverage",
                            "minimum_side_coverage",
                            "rms_pixels",
                            "ambiguous_parallel_edge",
                            "selected_layer_id",
                        )
                    )
                    + "</tr>"
                )
            content += (
                "</table><details><summary>Preserved ambiguity evidence and criterion failures</summary><pre>"
                + escape(json.dumps(diagnostics["sides"], indent=2))
                + "</pre></details>"
            )
        if item.get("frame_summary"):
            content += "<pre>" + escape(json.dumps(item["frame_summary"], indent=2)) + "</pre>"
        if name == "s2_2c":
            content += (
                "<p>"
                + (
                    link(item["interface"], "Open existing S2.2c human reference editor")
                    if item.get("interface")
                    else "<strong>Editor unavailable: "
                    + escape(item.get("reason", "Not run"))
                    + "</strong>"
                )
                + "</p>"
            )
        images = [p for p in item.get("artifacts", []) if Path(p).suffix.lower() == ".png"]
        if images:
            content += '<div class="images">'
            for image in images:
                content += (
                    "<figure>"
                    + link(image, Path(image).name)
                    + f'<br><img loading="lazy" src="{escape(Path(image).as_uri())}" alt="{escape(Path(image).name)}"></figure>'
                )
            content += "</div>"
        content += "</section>"
    content += (
        "<h2>Integrity</h2><pre>"
        + escape(json.dumps(manifest.get("integrity"), indent=2))
        + "</pre><p>Human-reference ranking is not run automatically. No reference annotation is manufactured.</p>"
    )
    with output.open("x", encoding="utf-8") as handle:
        handle.write(page("SPECTRA R&D - card " + manifest["card_id"], content))


def batch_dashboard(root: Path, batch: str, cards: list[str] | None = None) -> Path:
    runs = []
    warnings = []
    for path in sorted((root / "runs").glob("*/manifest.json")):
        try:
            item = read_json(path)
            if item.get("kind") != "rd_pipeline_run" or item.get("schema_version") != 1:
                raise ValueError("Unsupported manifest")
            if item["batch_id"] == batch:
                runs.append((path, item))
        except (AgentError, OSError, ValueError, KeyError, TypeError) as exc:
            warnings.append(str(path) + ": " + str(exc))
    card_ids = list(
        dict.fromkeys(
            (cards or ["D", "E", "F", "G", "H"]) + sorted({r[1]["card_id"] for r in runs})
        )
    )
    output = root / "dashboards" / identifier()
    output.mkdir(parents=True, exist_ok=False)
    content = (
        "<p>Batch "
        + escape(batch)
        + ". Snapshot generated "
        + escape(utc_now())
        + ". Re-run the dashboard command to include newly added cards; previous snapshots remain unchanged.</p><table><tr><th>Card</th><th>Pipeline</th>"
        + "".join("<th>" + escape(s) + "</th>" for s in STAGES)
        + "<th>History</th></tr>"
    )
    rows = []
    for card in card_ids:
        history = sorted(
            [r for r in runs if r[1]["card_id"] == card],
            key=lambda r: (r[1]["created_at_utc"], r[1]["run_id"]),
            reverse=True,
        )
        latest = history[0][1] if history else None
        status = latest["status"] if latest else "not_run"
        row = {
            "card_id": card,
            "status": status,
            "latest_manifest": str(history[0][0].resolve()) if history else None,
            "history": [str(p.resolve()) for p, _ in history],
        }
        rows.append(row)
        content += "<tr><td>" + escape(card) + "</td><td>" + escape(status) + "</td>"
        for stage in STAGES:
            content += (
                "<td>"
                + escape(latest["stages"][stage]["status"] if latest else "not_run")
                + "</td>"
            )
        content += (
            "<td>"
            + (
                "<br>".join(link(p.parent / "dashboard.html", r["run_id"]) for p, r in history)
                if history
                else "No original or analysis registered"
            )
            + "</td></tr>"
        )
    content += "</table><p>Status meanings: completed = execution finished, not approved; review_required = human review; blocked_upstream = dependency gate refused; analysis_failed = command/input/report failure; not_run = no execution requested or no card added.</p>"
    if warnings:
        content += '<pre class="warning">' + escape("\n".join(warnings)) + "</pre>"
    write_json_new(
        output / "overview.json",
        {
            "schema_version": 1,
            "kind": "rd_batch_overview",
            "batch_id": batch,
            "cards": rows,
            "warnings": warnings,
            "automatic_acceptance": False,
        },
    )
    with (output / "index.html").open("x", encoding="utf-8") as handle:
        handle.write(page("SPECTRA R&D - " + batch, content))
    return output / "index.html"
