# S2.1 physical-boundary references — offline R&D, version 0.1.0

This vertical slice constructs human-reviewed **physical material boundary** data
for evaluation of automatic detection. It never grades, certifies, scans, changes
detector acceptance, or supplies a production gate. The production objective
remains fully automatic detection. Annotation is a research sampling activity,
never a required step for every processed card.

It reuses S2.2c's offline single-file HTML pattern and its original-pixel camera,
line arithmetic and edit history (`spectra_reference/editor-core.js`). It has a
separate Python package, UI, reference kind, schema and comparison utility. It
does not reuse printed-frame annotations or printed-frame containment checks.
All originals, metadata, frozen 0.2.0, experimental 0.3.0-exp1 and downstream
contracts remain unchanged.

## Prepare the editor

Run from `scanner_agent` using the existing analysis environment:

```powershell
$python = '.\.venv-analysis\Scripts\python.exe'
$image = '.\local_data\s2_2c_validation\card-d\captures\20261018T061725_b599c7bc84654c2b9db6506a6ec92287\original.bmp'
$frozen = '.\local_data\controlled-boundary\20261018T140407\evaluation\capture-021\frozen.json'
$experimental = '.\local_data\controlled-boundary\20261018T140407\evaluation\capture-021\phase2.json'
& $python .\physical_boundaries.py prepare $image --report $frozen --report $experimental
```

The command prints the absolute path to a new `annotate.html`. Open that file in
a local browser. No web server, network requests or extra browser package is
required. `--report` can be repeated or omitted for a blind manual review. Every
supplied detector report must be hash-bound to this image. A report's
`review_required` status is accepted as diagnostic input, never promoted.

The HTML embeds a lossless PNG representation of the decoded **unchanged RGB
pixels**. No RGB conversion, spatial processing or change to the original file
occurs. Display zoom is nearest-neighbor. Browser display is not a calibrated
optical measurement. A content security policy blocks network access.

## Review

1. Enter the reviewer name. Inspect the material edges independently and explicitly
   declare that review. The declaration is an operator assertion, not authentication
   or proof of independence. Candidate exposure and seed origin are recorded.
2. Review each side in the main view and all four edge/corner panes. The edge
   position slider traverses each side. The detail magnification is 4–32×; clicking
   a detail view focuses the main view there. Automatic view centers can come from
   diagnostic geometry; they are never saved as reference lines.
3. Place a line using two clicks, drag either endpoint independently, translate
   the line, or enter original-pixel endpoints. Numeric inputs accept subpixel
   coordinates; inward/outward nudges default to 0.05 px. Wheel zooms, empty-space
   drag pans, and Shift reduces drag motion or arrow nudges to 0.1 px.
4. Candidates are optional and initially hidden. Selecting one as a starting line
   never confirms it. Default references have no detector-generated coordinates.
   Independently inspect alignment along the usable straight edge, not only at
   its midpoint. Rounded corners are inspected separately; reported intersections
   are extrapolated straight-line corners, not measured rounded material contours.

   Candidate identification uses layer colors **plus** explicit labels and version
   patterns: frozen fits are dashed, experimental fits dotted. Labels such as
   `F1:L0` and `E2:L0` combine the version family, input-report number and report-local
   layer ID; colors repeat between reports and do not imply geometric correspondence.
   Canvas labels occupy a separate gutter with leaders, leaving the scan free of
   text. The accessible candidate key repeats the same IDs and colored patterns.

   Selecting an Optional seed entry (or its labeled swatch) highlights that fit,
   draws it last and dims the other visible candidates. Selection is retained when
   zooming or switching sides and does **not** place a reference. Frozen and
   experimental visibility have independent toggles under the master Show
   candidates control. Selecting a hidden fit respects those toggles; Show selected
   candidate explicitly enables its version. The metadata panel reports version,
   layer ID, coverage, heuristic support score, physical criterion failures,
   side ambiguity, admissibility and detector provisional-selection status, using
   "unavailable" when a report omits a field. None of these states is a human
   confirmation. Thick outlined reference/draft lines remain visually distinct.

   The main viewport shows the active side's candidates; each edge pane shows its
   own side, and each corner pane shows its outgoing side. Pane magnification and
   line-label layout are display-only. Previously generated HTML pages embed old
   assets: run `prepare` again to get this UI in a new immutable output directory.
5. Select `Visually determinate`, `Uncertain position`, or `Visually indeterminate`.
   Uncertain lines require an explicit positive ± pixel band and explanatory notes.
   Indeterminate sides require notes and deliberately carry **no line geometry**.
6. Explicitly confirm every side. Geometry, status, uncertainty or note edits
   invalidate that side's confirmation. Pending numeric drafts block export even
   after switching sides. Undo/redo restores edits as unconfirmed.
7. Export a new physical-reference JSON version. All four side reviews, including
   indeterminate ones, must be confirmed. There is no preconfirmed export path.

The schema is [reference.schema.json](reference.schema.json), kind
`physical_boundary_reference`, schema version 1. Each export has a UUID annotation
ID and a new UUID version, image SHA-256/dimensions, original-pixel coordinates,
reviewer identity, candidate exposure, side certainty/bands/notes, UTC confirmation
times and a snapshot of the reviewed state. JSON schema describes structure;
Python additionally verifies current image identity, side ordering, line/endpoint
equivalence, confirmation snapshots and stable in-image convex intersections.
No nominal card dimension or detector threshold is used to coerce a reference.

## Validate and store a downloaded human reference

```powershell
$review = 'C:\path\to\reviewer-exported-physical-boundary.json'
& $python .\physical_boundaries.py save $image --reference $review
```

Only actual reviewer exports belong here. `prepare` writes
`unconfirmed-draft.json`, which intentionally fails the reviewed-reference schema;
it does not write a human reference. `save` validates independently of the browser
and writes to a unique immutable directory. Existing output paths cannot be
overwritten. Image/report/reference input SHA-256 hashes are checked before and
after each command and recorded in `integrity.json`.

To revise an existing annotation, `prepare --reference $review` validates the
same image and carries over only editable geometry/notes, with a predecessor
hash and **new identifiers and cleared confirmations/declaration**. References
cannot be carried to a different image. Optional `--output NEW_DIRECTORY` controls
where each command writes; omit it for automatic unique local-data directories.

## Compare frozen and experimental results

```powershell
& $python .\physical_boundaries.py compare $image --reference $review --report $frozen --report $experimental
```

The separate `comparison.json` reports 101 normal-displacement samples per side
over the reviewer's endpoint span, start/middle/end values, mean/max absolute
agreement, adjacent-line corner differences, contour area/perimeter/side lengths,
convexity and parallel/perpendicular consistency. Detector statuses and geometry
validation are copied unchanged. It never writes a detector report or runs S2.2.

Uncertain sides retain descriptive nominal displacement and distance outside
the stated band but are excluded from certain-reference claims. Indeterminate
sides have no numeric displacement; their adjacent reference corners cannot be
compared. Corner comparisons are explicitly flagged when adjacent sides are
uncertain. Whole-contour outputs state whether the reference is complete and
certain. No definitive accuracy score is calculated, even for a complete reference:
human agreement is distinct from calibrated material-edge accuracy. No real-card
comparison is produced until a reviewer supplies actual physical annotations.

## Reproduce the diagnostic-only refit investigation

```powershell
& $python -m spectra_physical_reference.refit_investigation $image $frozen --side 2 --output '.\local_data\physical-reference-new-refit-run'
```

This reconstructs saved support, computes bounded-radius/ownership/photometric
filter ablations, verifies the exact experimental rejection, and generates full
point memberships, 40-bin coverage, profile continuity/quality, normal-displacement
profiles and separate raw/marked crops. Rejected proposal quality is measured
**only in diagnostics**; the proposal is never installed and the 0.5 px guard is
never changed. The source image, metadata and report hashes remain protected.

## Validation commands

```powershell
& $python -m pytest -q -p no:cacheprovider
& $python -m ruff check .
& $python -m ruff format --check .
& $python -m mypy spectra_scanner spectra_boundary spectra_centering spectra_frame_evaluation spectra_reference spectra_pipeline spectra_physical_reference reference_frames.py evaluate_printed_frames.py rd_pipeline.py physical_boundaries.py
& $python -m compileall -q spectra_physical_reference physical_boundaries.py
& $python -m pip check
```

The new real-browser regression uses **synthetic imagery only**. It exercises
actual pointer events, multiple zoom levels, subpixel endpoints/nudges, stale
confirmation handling, pending drafts, and uncertainty export; it does not annotate
Card D/E. Chrome requires an execution environment that permits launching it.
No new runtime dependency was introduced.
