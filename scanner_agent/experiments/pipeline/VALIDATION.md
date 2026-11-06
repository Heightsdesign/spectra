# Validation — 2026-10-18

Executed from `C:\Users\plher\Documents\spetra\scanner_agent`. No physical acquisition was executed. No S1/S2.1/S2.2 detector, threshold, original, prior report or production file was edited for this task.

## Automated checks

| Command / environment | Actual result |
| --- | --- |
| `.venv-analysis\Scripts\python.exe -m pytest tests/test_pipeline.py -q` | **17 passed**, 8.25 seconds |
| `.venv-analysis\Scripts\python.exe -m pytest -q --basetemp local_data/rd_pipeline/full-tests-<unique UUID> -p no:cacheprovider` | **261 passed**, 26.42 seconds; includes existing offline editor browser regressions; Chrome launched outside filesystem sandbox |
| `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | **131 passed, 6 skipped**, 2.37 seconds; optional OpenCV/NumPy analysis modules skip in the S1-only environment |
| `.venv-analysis\Scripts\python.exe -m ruff check .` | All checks passed |
| `.venv-analysis\Scripts\python.exe -m ruff format --check .` | **75 files already formatted** after formatting the new test file |
| `.venv-analysis\Scripts\python.exe -m mypy spectra_scanner spectra_boundary spectra_centering spectra_frame_evaluation spectra_reference spectra_pipeline reference_frames.py evaluate_printed_frames.py rd_pipeline.py` | Success, **46 source files** |
| `.venv-analysis\Scripts\python.exe -m compileall -q spectra_pipeline rd_pipeline.py` | Exit 0 |
| `.venv-analysis\Scripts\python.exe -m pip check` | No broken requirements found |
| `rd_pipeline.py --help` | Exit 0, four documented operations |

The new tests cover successful synthetic progression through existing S2.2 analysis/editor code, strict review/invalid-geometry gates, malformed stdout/reports, nonzero exit, timeouts and partial logs, OS errors, cross-card report hashes, changed evidence, source mutation detection, mock acquisition and acquisition resume, idempotent completed-stage reuse, checkpoint resume, incremental overview, malformed overview entries, invalid CLI identifiers, and the local real Card D blocked regression. Test-only runners never touch scanner hardware and cannot be enabled through the CLI.

## Actual Card D acceptance runs

Root for all paths below:

```text
C:\Users\plher\Documents\spetra\scanner_agent
```

| Operation | Run directory under `local_data\rd_pipeline\runs\` | Result |
| --- | --- | --- |
| Resume existing S2.1 per-image report | `20261018T064754_5091228ed7d84e4f9fd3bfc66e7875fb` | Existing S2.1 reused; **zero** subprocesses |
| Fresh `analyze-existing` of the original BMP | `20261018T064801_dc6c830a2b1b46c9a391712180bfef28` | Exactly one real analysis subprocess: `analyze_boundaries.py`; no scanner or dependent S2.2 invocation |
| Idempotent resume of first run's manifest | `20261018T064806_825502b13a21459b8c6ab52248120080` | Existing S2.1 reused; **zero** subprocesses |

Every directory contains immutable `manifest.json`, `dashboard.html` and ordered checkpoint JSONs. The fresh run also contains `logs\s2_1\stdout.txt` and `stderr.txt`. All three executions completed with analytical status **`blocked_upstream`**; the two explicitly checked PowerShell `$LASTEXITCODE` values were **2**. All dependent stages have `execution_status=not_run`, `status=blocked_upstream`, and no command. No editor was generated and no frame hypotheses or annotations were invented.

Fresh S2.1 index and per-image report:

```text
local_data\s2_1\20261018T064802_eb96edb7068246a08de3c26b30106c7a\report.json
local_data\s2_1\20261018T064802_eb96edb7068246a08de3c26b30106c7a\scan-000\report.json
```

Both existing and fresh S2.1 evidence report side **2** coverage **0.625**, minimum **0.65**, failed `side_support` and `unambiguous_side_layers`, and parallel-edge ambiguity on **all four sides**. Every run exposes **11** existing diagnostic artifacts through its manifest/dashboard, including images and side/corner support evidence. Artifact paths were checked to exist.

Final D–H batch snapshot (D blocked, E–H `not_run`):

```text
local_data\rd_pipeline\dashboards\20261018T064828_2ad36a859087442b88127884d414d310\index.html
local_data\rd_pipeline\dashboards\20261018T064828_2ad36a859087442b88127884d414d310\overview.json
```

Automatically created batch snapshots are also preserved:

```text
local_data\rd_pipeline\dashboards\20261018T064755_3c281988d931464997ba6dccdca7aec1\index.html
local_data\rd_pipeline\dashboards\20261018T064805_1908fd03ce7c440b9fc2fa669641050c\index.html
local_data\rd_pipeline\dashboards\20261018T064806_1c50953767cf45a68ba12e6236fffff8\index.html
```

Each has sibling `overview.json`. An earlier development smoke run and its dashboard remain preserved under `runs\20261018T064142_f91f43ed15e249d58fa9ef983a5e748d` and `dashboards\20261018T064142_802cc1dcf86d4842aff24aa2e4a37c5a`; code was subsequently edited, so its manifest must not be used as a current cache.

## Integrity

Verified **1,660** pre-existing protected paths against the pre-implementation snapshot:

```text
local_data\rd-pipeline-protected-20261018T063635_be6bb3ab867647eb9e6928e4c8303041.json
```

**Zero changed or missing paths**. This includes existing scanner/analysis/editor source, configuration, immutable captures and prior reports. The three acceptance manifests also independently report `integrity.verified=true`.

Card D original remained:

```text
local_data\s2_2c_validation\card-d\captures\20261018T061725_b599c7bc84654c2b9db6506a6ec92287\original.bmp
SHA-256: 2935dd598b6f793eabbac2d6c290cc911a05183342fda2cd0d3afa2d53b0e129
```

## Files introduced

```text
rd_pipeline.py
spectra_pipeline/__init__.py
spectra_pipeline/cli.py
spectra_pipeline/contracts.py
spectra_pipeline/engine.py
spectra_pipeline/dashboard.py
tests/test_pipeline.py
experiments/pipeline/README.md
experiments/pipeline/manifest.schema.json
experiments/pipeline/VALIDATION.md
```

All are isolated under `scanner_agent/`. Existing source files were not modified. Generated runs, test artifacts and logs remain under ignored `local_data/` (ordinary Python caches remain ignored).

## Open the validated dashboard

```powershell
Set-Location 'C:\Users\plher\Documents\spetra\scanner_agent'
Start-Process -FilePath (Resolve-Path '.\local_data\rd_pipeline\dashboards\20261018T064828_2ad36a859087442b88127884d414d310\index.html').Path
Start-Process -FilePath (Resolve-Path '.\local_data\rd_pipeline\runs\20261018T064801_dc6c830a2b1b46c9a391712180bfef28\dashboard.html').Path
```

Hardware scan mode still requires real Windows/TWAIN operator validation. E–H have no registered production evidence in this batch. Card D has **not** passed physical or printed-frame validation. No detector is claimed calibrated or production-ready.
