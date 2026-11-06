# Isolated R&D validation pipeline — 0.1.0

This local CLI orchestrates S1, frozen S2.1 `0.2.0`, S2.2a, S2.2b and the **existing** S2.2c human-reference editor. It introduces no detector, threshold, grade, production endpoint, background service or database change. Outputs are experimental. Repeatability, agreement with a human annotation and absolute accuracy remain separate questions.

## Verified interfaces and dependency gate

| Stage | Existing command | Contract reused |
| --- | --- | --- |
| S1 | `acquire.py --config ... --data-dir ...` | Committed native BMP, metadata SHA-256 and acquisition report; multiple captures require explicit selection |
| S2.1 | `analyze_boundaries.py analyze ORIGINAL` | Schema 1 analysis index points to per-image report; algorithm `0.2.0`, original hash, image dimensions, four sides and geometry flags |
| S2.2a | `analyze_printed_frame.py ORIGINAL PHYSICAL_REPORT` | Schema 1 printed-frame report, original/physical-report hashes and unchanged default configuration |
| S2.2b | `evaluate_printed_frames.py ORIGINAL PHYSICAL_REPORT` | Schema 1 candidate-evaluation report, hypotheses, original/physical-report hashes; existing reference input validator |
| S2.2c | `reference_frames.py prepare ORIGINAL S2_2B_REPORT` | Existing offline editor and candidate inventory; no automatic annotation, confirmation or reference ranking |

S2.2a and S2.2b are sibling experiments using the same card's physical report. An S2.2a `not_applicable` does not alone prevent S2.2b. An invalid S2.2b report prevents editor preparation.

**Pipeline policy is stricter than the standalone experimental S2.2 adapter:** any S2.1 or baseline `review_required`, failed geometry flag, insufficient side coverage, or ambiguous side blocks **all** S2.2 stages. Only a successful baseline passing the existing geometry contract proceeds. No override is exposed. The first version accepts only the existing frozen default analysis configurations; custom/mismatching configurations fail explicitly rather than silently reusing incompatible results. S1 acquisition configuration remains explicitly operator supplied.

## PowerShell setup and help

Run from the repository root:

```powershell
Set-Location 'C:\Users\plher\Documents\spetra\scanner_agent'
# Reuse the existing analysis environment. If absent, create it with a supported Python:
# py -3.13 -m venv .venv-analysis
# .\.venv-analysis\Scripts\python.exe -m pip install -r requirements-analysis.txt
$python = (Resolve-Path '.\.venv-analysis\Scripts\python.exe').Path
& $python .\rd_pipeline.py --help
& $python .\rd_pipeline.py scan-and-analyze --help
& $python .\rd_pipeline.py analyze-existing --help
& $python .\rd_pipeline.py resume --help
```

No dependency is added beyond the existing scanner/analysis environments. TWAIN acquisition may use a different compatible Python via `--acquisition-python` (driver/DSM bitness must match). Device discovery and hardware settings remain the S1 operator's responsibility. This pipeline is not hardware calibration.

## Analyze an existing original — no scanner access

```powershell
$original = '.\local_data\s2_2c_validation\card-d\captures\20261018T061725_b599c7bc84654c2b9db6506a6ec92287\original.bmp'
& $python .\rd_pipeline.py analyze-existing --card D --image $original
```

This executes fresh S2.1 analysis on Card D's own bytes. All existing originals, metadata, manifests and reports are read-only inputs. New detector reports use the existing CLIs' unique output directories under `local_data/s2_1`, `s2_2a`, `s2_2b` and `s2_2c`; the pipeline links them, avoiding copies or competing geometry.

## Resume Card D's existing physical report

```powershell
$physical = '.\local_data\s2_1\20261018T062229_355f5070499942f190627e4cad430cd8\scan-000\report.json'
$result = & $python .\rd_pipeline.py resume --card D --from $physical | ConvertFrom-Json
$result
Start-Process -FilePath $result.dashboard
Start-Process -FilePath $result.batch_dashboard
# Repeat using the generated manifest: reuse validated analysis, no duplicate detector execution.
& $python .\rd_pipeline.py resume --card D --from $result.manifest
```

Expected Card D outcome: process exit **2**, `status=blocked_upstream`, `execution_status=completed`, S2.1 `review_required`, S2.2a/b/c `blocked_upstream`. The detail page displays side **2** coverage **0.625** versus the frozen **0.65** minimum, failed `side_support` and `unambiguous_side_layers` checks, ambiguity on all four sides, candidate-layer evidence and clickable diagnostic PNGs. Side indices are the existing report indices, not invented anatomical labels. The editor is explicitly unavailable. This is not a pass. Expected original SHA-256:

```text
2935dd598b6f793eabbac2d6c290cc911a05183342fda2cd0d3afa2d53b0e129
```

`resume --from` accepts a committed S1 `metadata.json`, S1 acquisition report, S2.1 index/per-image report, S2.2a/b report, or pipeline manifest/checkpoint. If a capture report contains several originals, add `--capture-id ACTUAL_ID`. Resume never reacquires. A checkpoint with no committed original is refused. Completed valid stages are reused; absent/failed stages may run again in a **new** execution directory. A blocked gate remains blocked. For pipeline-manifest/checkpoint resume, card/batch must match and every recorded source, code, configuration, report and diagnostic hash must still match. Code changes invalidate that cache; explicitly resume from an unchanged source analysis report or analyze the original again after reviewing the change. No previous manifest is rewritten.

## Scan and analyze a new card — operator-run hardware operation

The following command **triggers the scanner**. It has not been physically executed during pipeline implementation. Use an existing individually verified S1 configuration for the actual scan surface, 600 DPI RGB24 and provisional acquisition settings. Do not copy another card's detection geometry or annotations.

```powershell
$config = (Resolve-Path '.\experiments\contrast\acquisition.contrast-0.json').Path
& $python .\rd_pipeline.py scan-and-analyze --card E --acquire-config $config --strict-options --scan-timeout 300
# If the TWAIN installation requires the separate compatible S1 environment:
# & $python .\rd_pipeline.py scan-and-analyze --card E --acquire-config $config --acquisition-python '.\.venv\Scripts\python.exe' --strict-options
```

That existing configuration matches Card D's recorded requested 600 DPI / RGB24 / gamma 2.2 / contrast 0 settings and scanner-surface region. The operator must verify that the new card is positioned inside that region before requesting acquisition; it is not a reusable detected card boundary or annotation.

The pipeline preflights analysis dependencies, delegates all scanner configuration and acquisition to S1, saves into the new run's `acquisition/` directory, then validates committed BMP integrity and S1 QC before S2.1. S1's global acquisition lock is preserved. A canceled/failed/timeout acquisition is an explicit failure; it never silently retries hardware. Existing S1 `pending` physical-margin QC is preserved, not promoted to success. The separately recorded `physical_scan_performed_this_execution` reflects acquisition evidence; resume does not claim another scan.

## Incremental D–H overview

```powershell
# Register each newly available card with its own actual original:
# & $python .\rd_pipeline.py analyze-existing --card E --image 'C:\PATH\TO\CARD-E\original.bmp'
# Repeat with --card F, G, H and their respective originals.
$overview = & $python .\rd_pipeline.py dashboard --batch cross-card --cards D E F G H | ConvertFrom-Json
Start-Process -FilePath $overview.dashboard
```

Each run also generates a new batch snapshot automatically. D–H appear by default; absent cards remain `not_run`. Other card identifiers are included incrementally. Use a different `--batch NAME` to separate experiments (supply it consistently on run/resume/dashboard). HTML is static and local, requires no server or network, links complete history and source diagnostics, and does not refresh itself. Re-run `dashboard` for a fresh snapshot; old snapshots remain intact.

## Outputs, statuses and integrity

Every execution receives a unique `local_data/rd_pipeline/runs/<UTC_UUID>/` directory:

```text
manifest.json                  final immutable machine-readable execution record
dashboard.html                 static per-card detail page
checkpoints/0001_<UTC_UUID>.json ... ordered, immutable recovery snapshots
logs/<stage>/stdout.txt         subprocess output, including partial timeout output
logs/<stage>/stderr.txt
acquisition/                   only for a newly requested S1 scan
```

Batch snapshots: `local_data/rd_pipeline/dashboards/<UTC_UUID>/index.html` and `overview.json`. All generated artifacts remain ignored under `local_data/`; never add customer images or outputs to source control. Files are created exclusively; no overwrite or source transformation is performed. Native originals are verified using the existing S1 image-integrity reader and adjacent metadata when available. For a standalone BMP with no acquisition metadata, the hash is calculated but historical acquisition provenance cannot be proven. All images must decode as lossless native BMP RGB24 under the existing evidence contract.

`manifest.schema.json` documents schema 1; runtime validation uses the existing input validators plus strict orchestrator contracts. `stages` preserves each original analytical status separately from pipeline stage status, execution status, return code, hashes, commands, paths, evidence and reasons.

| Pipeline status | Meaning | Exit |
| --- | --- | --- |
| `completed` | Requested execution completed (e.g. dashboard generation), **not** analytical approval | 0 |
| `review_required` | Execution completed; experimental analysis/human reference remains unresolved | 2 |
| `blocked_upstream` | Gate rejected a dependency; dependent command not executed | 2 |
| `analysis_failed` | Input/schema/integrity/subprocess failure | 3 |
| `not_run` | No card/stage requested or registered | — |

`execution_status=completed` can accompany `blocked_upstream`. Exit 2 is an expected conservative analytical outcome, not a command crash. Argparse usage errors also exit 2 with usage text. No detector/editor invocation is inferred from an old file alone: status, return code and report contract must agree. `automatic_acceptance` is always false. An eligible S2.2b report prepares the **existing** editor; the operator must independently inspect, confirm, export and use the existing `reference_frames.py save` / `compare` workflow. Reference agreement ranking is never manufactured by this pipeline.

## Validation and limitations

Actual 2026-10-18 results and generated Card D paths are recorded in [VALIDATION.md](VALIDATION.md).

```powershell
& $python -m pytest tests/test_pipeline.py -q
& $python -m pytest -q
& $python -m ruff check .
& $python -m ruff format --check .
& $python -m mypy spectra_scanner spectra_boundary spectra_centering spectra_frame_evaluation spectra_reference spectra_pipeline reference_frames.py evaluate_printed_frames.py rd_pipeline.py
& $python -m compileall -q spectra_pipeline rd_pipeline.py
& $python -m pip check
```

Tests inject isolated subprocess/acquisition fixtures; these are not CLI/runtime bypasses. Successful synthetic progression exercises the existing S2.2 analyzers/editor but proves neither physical accuracy nor live TWAIN operation. Local Card D regression is skipped on machines without its private evidence; no real reference annotation is fabricated. Existing headless-browser editor tests need permission to launch Chrome in restricted environments.

This first version is single-card per command, local and serial within an execution. It provides immutable snapshots, not a background watcher or shared database. It does not recover a subprocess artifact created after the last checkpoint automatically; rerunning may create another unique analysis report. No frames are fabricated if upstream geometry is invalid. Existing standalone analysis entry points retain their original behavior. Real hardware acquisition, E–H generalization, physical calibration and operator annotation remain separate validation tasks.
