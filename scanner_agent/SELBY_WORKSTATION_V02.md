# SELBY Workstation V0.2 — centering inspection

Run from PowerShell:

```powershell
Set-Location 'C:\Users\plher\Documents\spetra\scanner_agent'
.\.venv-analysis\Scripts\python.exe -B .\selby_workstation.py
```

PySide6 6.12.0 is installed in this environment. For a fresh environment:

```powershell
.\.venv-analysis\Scripts\python.exe -m pip install -r requirements-workstation.txt
```

The existing `--image`, `--physical`, `--printed` and `--session` options remain available.
The V0.1 audit and detailed line-editing instructions remain in `SELBY_WORKSTATION.md`.

## Operator workflow

1. Open an immutable original scan. Load its existing S2.1 and, optionally, S2.2 report.
   Report image hashes and recorded source statuses must match. Loading S2.2b also loads
   its exact physical-report dependency. No detector is rerun.
2. Enter operator identity. Choose **front**, **back** or **unspecified** for this image.
   Each inspection is independent; this creates no front/back pairing.
3. Select a family and side. Draw with two points, seed an existing source line, or use
   a printed hypothesis as four unconfirmed lines. Drag a line or endpoint to correct it.
   Arrow keys nudge; Shift/Fine uses 0.1 original pixels. Right/middle drag pans.
4. Confirm each reviewed side, or enter an explanation and mark it uncertain.
   Changes to a line or its notes invalidate that side's confirmation.
   **Undo / Ctrl+Z** and **Redo / Ctrl+Y** restore complete line decisions, including
   confirmation and uncertainty. A drag is one committed edit. Finish or Escape a
   pending gesture before undoing, saving, validating or exporting.
5. Independently click **Validate four physical sides** and **Validate four printed
   sides** after confirming all four sides of each family. Missing, uncertain or
   geometrically inconsistent groups cannot validate. Changes to a group's decisions
   or operator identity invalidate its validation snapshot. Validation of one group
   does not imply validation of the other.
6. Read the centering panel (scroll below the side controls). It shows original-pixel
   mean/min/max margins, horizontal **left:right** percentages and vertical **top:bottom**
   percentages, active line endpoints, manual/candidate origin and source basis.
   All eight usable lines permit **provisional** measurements. Both explicit group
   validations permit **human_geometry_validated** measurements; this means reviewed
   geometry, not certified metrological accuracy. Missing or inconsistent boundaries
   produce **unavailable**, without inferred replacements. Uncertain lines can only
   support provisional results. These statuses never clear upstream review requirements.
7. **Save new version** writes a separate immutable session version. **Open session**
   restores corrections, decisions, face and view. V0.1 sessions reopen provisionally
   and acquire tool version 0.2.0 when next saved.
8. **Export diagnostic** writes UUID-versioned `.json` and `.md` files to the chosen
   directory. JSON includes all decisions, original geometry, full sampling diagnostics,
   source hashes/statuses, image identity, limitations and saved-session provenance.
   Markdown provides margins, ratios, provenance and individual side decisions.

## Draft recovery

Complete committed state is snapshotted every 1.5 seconds when changed, and on window
close, into:

`local_data/selby_workstation/drafts/draft-<session UUID>-<snapshot UUID>.json`

Snapshots are created exclusively, flushed and fsynced; previous drafts and saved
versions are never overwritten or deleted. Blank operator identity is allowed in
drafts, but saving/exporting requires an operator. An unfinished gesture is not a
committed edit and is not autosaved. There is a maximum normal timer interval of
unsaved work; blocked event-loop time and disk errors can extend it. Autosave disk
errors appear in the status bar.

After a crash, choose **Recover draft**, sort the file dialog by modification time
and choose the newest complete snapshot for the intended image/session. Recovery
checks decoded image identity, current image/report hashes, exact source status
provenance and any saved ancestor. A partial or damaged newest snapshot is rejected;
choose the previous complete snapshot. Recovery does not silently pick a different
image or source. Then save a new version. Draft history itself is retained; in-memory
Undo/Redo history starts fresh when a session or draft is opened.

## Reuse and boundaries

V0.2 adapts `spectra_centering.detector.measurements` with the unchanged default
21 samples and 0.18 corner exclusion. It uses reviewed physical-line intersections
and printed-line geometry in original coordinates. It does not use the canvas view,
baseline predictions as substitute physical boundaries, rectification or a new
measurement formula. Existing S2.2c line/intersection/containment validation and
S1 image encoding/identity checks remain reused. No frozen detector/configuration
or validity gate was changed.

Only pixels and dimensionless percentages are presented. Reported DPI is not treated
as calibrated metrology. Perspective, scanner distortion, local boundary curvature,
design ambiguity and repeatability are not corrected. No numeric measurement
uncertainty is invented. Sources and saved ancestors must remain at their recorded
paths. History is in memory and retains snapshots without a size cap. Drafts accumulate
without automatic cleanup. A JSON export can survive a failed companion Markdown
write; the UI reports the failure and a subsequent export creates new version IDs.

Human validation is operator attestation, not a signed certification or security
boundary. No grade, final score, automatic acceptance, front/back aggregation or
grading promotion is provided. Existing `review_required` and blocked source statuses
remain unchanged in sessions and diagnostic exports.

## Validation and V0.3

Evidence lives in `local_data/selby_workstation/v02-validation/`:

- `tests-final-complete.xml`: 34 passed; focused workstation persistence, Qt
  interactions and V0.2 cases on the final implementation.
- `regression.xml`: 382 passed, 3 browser tests deselected.
- `windows-native.png`: native Windows launch with original scan and two reports;
  process returned 0 and reported `platform=win32`, `image_loaded=true`,
  `report_count=2`, `automatic_acceptance=false`.
- `protected-verification.json`: 345 previously protected files checked; zero changed.
- `real-image-integration.json`, `sessions/`, `diagnostics/`: real-image integration
  artifacts with candidate-seeded, unconfirmed provisional geometry. No sides were
  automatically reviewed; these are engineering checks, not human references.

Synthetic tests check expected 30/40/50/20 pixel margins under rotation and translation,
ratios, independent group validation, missing/inconsistent/uncertain lines, stale
operator validation, history round trips, immutable saved ancestry, incomplete draft
rejection, image/report/status identity mismatches and V0.1 compatibility.

Recommended V0.3: add a reviewed uncertainty budget with calibrated scanner geometry
and repeatability evidence, then expose uncertainty alongside centering measurements.
Preserve the existing upstream validity gates and independent image records.
