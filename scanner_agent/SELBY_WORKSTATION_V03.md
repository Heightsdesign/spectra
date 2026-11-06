# SELBY Workstation V0.3 — Assisted Condition Inspection

V0.3 provides local corner, edge and surface inspection, experimental visual
suggestions and explicit operator decisions. It produces neither a grade nor
automatic acceptance. Upstream review and blocked statuses remain unchanged.
This guide supersedes the V0.3 recommendation in `SELBY_WORKSTATION_V02.md`;
that document remains the detailed centering and boundary-editing guide.

## Launch

Exact PowerShell command for the real scan validated on this workstation:

```powershell
Set-Location 'C:\Users\plher\Documents\spetra\scanner_agent'
.\.venv-analysis\Scripts\python.exe -B .\selby_workstation.py --image 'local_data\s2_1_validation\card-a\scan-1\captures\20261017T184714_f46f9ce59a8644009dff682365d48a3f\original.bmp' --printed 'local_data\s2_2b_validation\20261017T202702_0892dd46243f4756a0076014efe3f13f\pair-000-b\report.json' --condition
```

The printed report loads its exact physical-report dependency. Nothing is
regenerated. To select another scan interactively, launch:

```powershell
.\.venv-analysis\Scripts\python.exe -B .\selby_workstation.py
```

Use **Open scan**, optionally **Load report**, then **Condition inspection**.
To reopen a saved session directly:

```powershell
.\.venv-analysis\Scripts\python.exe -B .\selby_workstation.py --session 'C:\path\to\inspection-SESSION_UUID-VERSION_UUID.json' --condition
```

Replace that example session path with the actual saved file. Do not combine
`--session` with new image/report inputs. Dependencies are listed in
`requirements-workstation.txt`; the validated environment has PySide6 6.12.0.

## Operator workflow

1. Open the immutable original and matching reports. RGB24 BMP, PNG and lossless
   TIFF are supported under the existing image guards. Enter an operator identity
   and select front, back or unspecified. Images remain independent and unpaired.
2. Inspect/correct all four physical boundary lines in the main window. Confirm
   each certain side, then choose **Validate four physical sides**. Loading or
   seeding a prediction alone does not validate it. Missing, uncertain or stale
   geometry blocks extracted regions and all automated condition diagnostics.
   Printed boundaries are needed for centering, not for condition extraction.
3. Open **Condition inspection**. **Corners** shows top-left, top-right,
   bottom-right and bottom-left patches. **Edges** shows top, right, bottom and
   left strips rotated into local horizontal coordinates. **Surface** shows the
   original scan. Corner labels follow scan/card-local geometry, not inferred
   printed upright orientation.
4. Use the wheel to zoom and right/middle drag to pan. **Fit views** and **1:1
   pixels** apply to the active category. **Sync zoom / pan** synchronizes the
   corner or edge views using normalized viewport centers. Each patch pixel step
   corresponds to one original pixel along its axes; rotated extraction uses
   bilinear interpolation. Display zoom is independent of saved coordinates.
5. Select a category, then **Run category diagnostic**. Inspect the suggestions
   and their evidence in the table. **Locate selected** centers/zooms the relevant
   view; **Next pending** advances to an unreviewed suggestion. The **Suggestion
   overlay** checkbox hides/shows annotation outlines, including manual findings.
6. Select a finding, choose its type and enter an evidence/reason note. **Confirm
   defect** records an operator-confirmed observation. **Reject suggestion** keeps
   the record but hides its outline. **Reclassify (does not confirm)** changes
   its classification without asserting damage. Each decision records operator,
   timestamp, notes and prior decision history. Green solid outlines mean
   confirmed; amber dashed outlines mean unreviewed or reclassified.
7. To annotate manually, choose a type, enter an evidence note, enable **Draw
   manual defect (drag box)** and drag in the desired view. The box is immediately
   recorded as a confirmed operator finding in original-image coordinates. Turn
   drawing off to navigate normally. Too-small gestures are ignored; out-of-image
   boxes are rejected. Escape cancels a pending box. Review decisions can correct
   an annotation; Undo/Redo can reverse committed condition changes.
8. Resolve every unreviewed suggestion, enter a category review note, then choose
   **Complete category review**. Reclassification counts as a resolved decision,
   not a confirmed defect. Completion means the operator reviewed that category;
   it does not mean defect-free, accepted or graded. Repeat for all three tabs.
9. Choose **Save new version** and select an artifact directory. **Open session**
   restores findings, decision history, diagnostic provenance and review stamps.
   Choose **Export diagnostic** for a separate JSON/Markdown diagnostic pair.
   Save/export requires operator identity. Partial inspections can be saved.

Manual surface annotation and category completion are available without physical
geometry. Automated surface suggestions still require validated physical geometry
to define the inspected card interior.

## Persistence, reruns and recovery

The session's optional `condition` schema stores runs, findings and category review
snapshots. Findings include original-image quadrilaterals, category, type, origin,
evidence, decision, operator, timestamps and decision history. Runs record image
and source identities, physical validation, extraction transforms, algorithm
version, parameters and OpenCV version.

Rerunning retains previous records. The active table includes the latest run,
manual findings and previously confirmed/reclassified suggestions. Older rejected
or unreviewed suggestions remain archived. A new run or decision invalidates the
category completion. Changed physical geometry invalidates diagnostic review;
review/revalidate the boundaries and rerun before completing that category again.

Every save creates a new UUID version with saved-parent provenance. Original scans,
reports and saved versions are not overwritten. Reopening requires the original
image, sources and recorded saved ancestor to remain at their paths with matching
hashes. Portable relinking is unavailable.

Committed changes produce exclusive recovery snapshots in
`local_data/selby_workstation/drafts/`; condition actions request an immediate
snapshot and the main window also uses its 1.5-second timer. After interruption,
choose **Recover draft** and select the newest complete draft for that session.
Invalid/incomplete drafts are refused; select the previous complete snapshot.
Then save a new version. Undo/Redo history starts fresh after reopening/recovery.
Unfinished gestures and unsubmitted reason text are not saved findings. Autosave
disk failures are reported in the main window status bar; explicit saves remain
necessary. Drafts and in-memory history have no automatic retention limit.

## Diagnostic export

New exports use `inspection-SESSION_UUID-EXPORT_UUID.json` and `.md`, JSON kind
`selby_inspection_diagnostic`, and heading **SELBY inspection diagnostic**. JSON
contains the complete inspection session plus centering measurements where
available; Markdown includes category statuses and individual findings. These are
data exports, not rendered overlay-image exports. Old `selby_centering_diagnostic`
exports remain unchanged; consumers of the new export must accept the new kind
and filename prefix. Session kind/schema remain unchanged.

JSON and Markdown writes are separate: JSON can survive a failed Markdown write.
The UI reports the error; another export produces a new UUID rather than replacing
the partial pair. Keep exports in a dedicated artifact directory.

## Experimental detection and commercial limitations

- Suggestions are fixed visual heuristics: whitening indicators, local contrast,
  color discontinuities and, for corners/edges, contour deviations. Scratch, dent,
  wear and artwork/texture are available operator classifications, not trained
  damage classifiers. Printed artwork, foil, halftone and nearby printed edges can
  trigger suggestions. Absence of suggestions does not establish absence of damage.
- No labeled detection evaluation dataset was used. Precision, recall, defect
  severity and real-world detection accuracy are unknown. Suggestions require
  human inspection; the automated validation artifacts are engineering exercises.
- Extraction uses reviewed straight-line geometry. Rounded corners, curved edges,
  interpolation and background pixels affect the patches. Automated surface
  inspection erodes the card-interior mask; it does not cover the border band.
  Per-type candidate counts are capped, so this is not exhaustive defect discovery.
- Coordinates are original pixels. No calibrated physical measurements, scanner
  repeatability budget, uncertainty interval, ICC-calibrated display or certified
  ground truth is supplied. Transform tests verify software mapping, not physical
  inspection accuracy.
- One image is inspected independently. No front/back aggregation, scanner capture,
  authenticated operator identity, signed audit trail or commercial approval flow
  is included. The application uses synchronous image processing and local files;
  very large scans can block interaction and disk errors can prevent persistence.
- This supports assisted internal inspection. Unvalidated detection performance,
  metrology, operator/audit controls and business approval prevent treating V0.3
  alone as a commercial grading or acceptance system. Upstream review/blocked
  statuses and `automatic_acceptance=false` are preserved.

## Validation

See `SELBY_WORKSTATION_V03_VALIDATION.md` for actual results, evidence locations,
scope and unresolved limitations. No detection algorithms were added during final
consolidation.
