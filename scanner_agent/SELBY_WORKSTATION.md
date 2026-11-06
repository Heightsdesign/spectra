# SELBY Grading Workstation V0.1

A native Python/PySide6 inspection application, separate from the R&D pipeline.
It opens originals, overlays existing predictions and records human corrections.
It does not run detectors, compute grades, accept cards or produce certified
ground truth. Existing upstream review/blocked states are never cleared.

## Launch on this workstation

PySide6 6.12.0 is installed in the existing analysis environment.

```powershell
Set-Location 'C:\Users\plher\Documents\spetra\scanner_agent'
.\.venv-analysis\Scripts\python.exe -B .\selby_workstation.py
```

Optional Tritox example (loads the existing printed report and its own physical
report automatically; neither report is changed):

```powershell
.\.venv-analysis\Scripts\python.exe -B .\selby_workstation.py --image 'local_data\s2_1_validation\card-a\scan-1\captures\20261017T184714_f46f9ce59a8644009dff682365d48a3f\original.bmp' --printed 'local_data\s2_2b_validation\20261017T202702_0892dd46243f4756a0076014efe3f13f\pair-000-b\report.json'
```

Additional input flags: `--physical PER_IMAGE_S2_1_REPORT`, `--printed
PER_IMAGE_S2_2A_OR_B_REPORT`, or `--session SAVED_INSPECTION_JSON`. A session is
reopened with its recorded image and sources, rather than mixed with new inputs.
Use per-image reports, not S2.1 indices, repeat summaries or pipeline manifests.

On a fresh Windows 11 x64 workstation with Python 3.13:

```powershell
Set-Location 'C:\Users\plher\Documents\spetra\scanner_agent'
py -3.13 -m venv .venv-workstation
.\.venv-workstation\Scripts\python.exe -m pip install -r requirements-workstation.txt
.\.venv-workstation\Scripts\python.exe -B .\selby_workstation.py
```

This adds Qt and the existing analysis dependencies; no AI dependencies are used.
Qt's [official installation documentation](https://doc.qt.io/qtforpython-6/gettingstarted.html)
describes the wheel-based installation. An executable installer is not included.

## Operator workflow

1. **Open scan**: select an existing single-frame RGB24 BMP, PNG or lossless TIFF.
   Non-RGB/alpha/high-bit-depth or oriented TIFF inputs are rejected rather than
   converted. Decoding, encoded dimensions and SHA-256 use existing S1/reference
   utilities. The original is never written.
2. **Load report**: load frozen S2.1 0.2.0 or verified S2.2a/b 0.1.0 per-image
   JSON. Identity and exact upstream hashes must match. Cyan dashed lines show
   existing physical predictions. Choose a printed hypothesis to preview its four
   magenta lines. Loading/previewing does not annotate or confirm anything.
3. Enter an operator identifier. Select **Physical** or **Printed** and a side,
   or click a row in the eight-side table. Side order follows the existing
   original-pixel/card-local convention; printed upright orientation is not inferred.
4. Select a **Source line**, then **Use source line**, or use **Draw two points**
   for manual placement. **Use hypothesis** explicitly replaces all four printed
   drafts, leaving them unconfirmed. Existing saved versions are preserved.
5. In **Edit lines**, click/drag an endpoint to change orientation, or drag a line
   to translate it. Arrows move the selected line/endpoint by 1 original pixel;
   Shift or Fine uses 0.1 pixel. Mouse wheel zooms; Pan or right/middle drag pans.
   Fit and 1:1 are available. Escape cancels an unfinished placement/drag. Finish or cancel a placement before
   saving or confirming a side.
6. Inspect the usable side and **Confirm reviewed side**, or enter a side note
   and **Mark side uncertain**. Uncertain sides can retain tentative geometry or
   remain without a line. Editing geometry or side notes clears prior confirmation.
   Green denotes physical edits, gold printed edits; dashed means unconfirmed or
   uncertain. Confirmation is an operator decision, never a physical certification.
7. **Save new version**: choose an artifact directory. The suggested directory is
   `local_data\selby_workstation\sessions`. Every save creates a new exclusive
   `inspection-SESSION_UUID-VERSION_UUID.json`; nothing is overwritten. Partial
   inspections may be saved once operator identity is entered.
8. **Open session**: reload a saved version. Corrections, side decisions, notes,
   candidate/manual attribution, exposure, view state and source provenance are
   restored. Every original/source hash is checked again. Changed or missing
   evidence is refused rather than silently relinked. Unsaved-change prompts guard
   replacement/closing of an inspection.

## Repository audit and reuse

| Existing component | Reused in V0.1 |
|---|---|
| `spectra_scanner.storage` | Encoded-image inspection, format/pixel limits, SHA-256 |
| `spectra_physical_reference.model` | Immutable RGB loading, S2.1 report validation, endpoint/line consistency, physical intersections |
| `spectra_reference.geometry` | Canonical normalized lines, original-pixel reference-ray endpoints, printed-quad containment checks |
| `spectra_reference` / S2.2c | Coordinate-system name, four-side order, candidate/manual distinction, explicit annotated/ambiguous/unannotated decisions |
| `spectra_reference.inputs.load_bundle` | Existing verified S2.2b/image/S2.1 provenance adapter and valid hypotheses |
| `spectra_centering.inputs.read_inputs` | Existing S2.2a upstream image/geometry validation |
| `spectra_scanner.common` | UTC timestamps and exclusive JSON writing with flush/fsync |
| R&D pipeline | No execution/import into its orchestration. Its stricter downstream gate is preserved; this GUI is a separate human inspection path |

The existing browser canvas/controller is JavaScript. Its geometry and annotation
conventions are retained; the native view uses Qt graphics items and Qt camera
transforms rather than adding another detector or rebuilding S2.2a/b/c. Existing
R&D PNG overlays remain diagnostics, not editable image measurements. Semantic
V1/V2 reports, manual-reference files and pipeline manifests are not interchangeable
with validated S2.1/S2.2 source inputs.

## Persistence and integrity

New kind: `selby_inspection_session`, schema 1, tool 0.1.0. It deliberately cannot
be consumed as an S2.1 report, S2.2c reference, gate override or grading result.
It records image path/SHA/dimensions/encoding, exact source paths/hashes/statuses,
operator and notes, eight side slots with original-pixel endpoints and line
coefficients, seed attribution, reviewed snapshots, timestamps and view state.
Manual edits preserve their seed basis but clear exact candidate selection.

Versions link the previous saved path and SHA-256. Source statuses are checked
against source files on save/reopen; `review_required` and
`automatic_acceptance=false` are invariant. Whole-contour geometry warnings are
retained without certifying the contour or rewriting any R&D decision. Loaded
source predictions are treated as prior exposure, never as independent annotation.

This is local provenance, not a signed audit trail or authenticated operator
identity. Reopening currently requires the original and source paths, plus the
immediate parent version when present. A corrupt/interrupted JSON write fails
closed; no autosave/recovery service is present.

## Tests, validation and current limits

Focused tests: `tests/test_selby_session.py`, `tests/test_selby_gui.py`. These
exercise fractional endpoint persistence, parent version hashes, changed-evidence
refusal, candidate/manual provenance, uncertainty, stale confirmations, GUI draw,
drag preview/cancel/commit, endpoint nudges, camera transforms and pan.

```powershell
.\.venv-analysis\Scripts\python.exe -B -m pytest tests/test_selby_session.py tests/test_selby_gui.py -q -p no:cacheprovider --basetemp local_data\selby_workstation\NEW_TEST_DIRECTORY
```

Qt interaction tests use the offscreen rendering platform. A separate native
Windows 11 launch with the real Tritox original and both source reports completed
successfully; evidence is under `local_data\selby_workstation\validation-20261020`.
See `VALIDATION.md` there for final counts, source integrity and screenshot paths.

Known limits: source checkout/Python launch, one scan per window, synchronous
loading/saving, original-coordinate RGB24 only, no ICC/calibrated display, no
scan acquisition, report regeneration, score, commercial approval, authentication,
database, undo/redo, portable source relinking or autosave. The canvas preserves
double-precision geometry; viewport scroll positions are display-pixel quantized.
Printed lines do not automatically move when physical lines are corrected.

**Recommended V0.2:** add undo/redo and crash-safe draft recovery, with a single
eight-side review summary that exposes incomplete/uncertain geometry and preserved
upstream blocks. Package the already tested UI only after that persistence workflow
is validated. Keep grading/acceptance out of that increment.
