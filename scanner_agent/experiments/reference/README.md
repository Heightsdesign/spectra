# SPECTRA S2.2c — reference annotation and quantitative agreement

`spectra_reference` is an isolated experimental validation package, algorithm
0.1.0, annotation/comparison schema version 1. It reads immutable originals and
existing S2.1/S2.2b reports; it does not run or change any detector. It produces
manual references and agreement diagnostics, never a grade, centering subgrade,
approval, certification or production decision.

## Verified architecture and Tritox investigation

- S1 lives in `spectra_scanner`; frozen physical detector 0.2.0 is
  `spectra_boundary`. S2.2a is `spectra_centering` 0.1.0, and the separate S2.2b
  evaluator is `spectra_frame_evaluation` 0.1.0.
- S2.2b's `evaluation.hypotheses` forms ordered four-candidate combinations.
  `frame_evaluation.hypotheses[].candidate_ids` references
  `sides[i].candidates[].id`; `line_abc` is the actual fitted original-pixel line.
  `distance_pixels` is a detected peak location, not the line equation.
- S2.2b overlay labels can include `[provisional]`; these are visual decorations,
  not different candidate IDs. Always use the machine-readable IDs/equations.
- The first Tritox report has **9 distinct combinations and 9 distinct fitted
  geometries**, not duplicated combinations. Left/right are shared, while three
  top and three bottom alternatives form the 3 x 3 set. Some differ by only
  about 9–12 pixels and look similar in reduced contact sheets. None is thereby
  validated as the intended outer printed frame.
- There is no existing reference annotation or calibrated geometry contract to
  reuse. OpenCV is headless, so this tool generates a self-contained **offline
  HTML canvas** instead of adding a GUI framework or local server. Python does
  the authoritative provenance/geometry validation and immutable storage.

## Windows PowerShell workflow

From the repository root, with the existing analysis environment:

```powershell
Set-Location .\scanner_agent
# New workstation only; reuse an existing environment otherwise:
# py -3.13 -m venv .venv-analysis
# .\.venv-analysis\Scripts\python.exe -m pip install -r requirements-analysis.txt

$python = '.\.venv-analysis\Scripts\python.exe'
$image = 'local_data\s2_1_validation\card-a\scan-1\captures\20261017T184714_f46f9ce59a8644009dff682365d48a3f\original.bmp'
$s22b = 'local_data\s2_2b_validation\20261017T202702_0892dd46243f4756a0076014efe3f13f\pair-000-b\report.json'

# Optional: inspect duplicate combinations/geometries without annotating.
& $python reference_frames.py inspect $image $s22b
# Exit 2 is expected: experimental review_required.

# Load the existing report and create a NEW offline derived-image interface.
$prepared = & $python reference_frames.py prepare $image $s22b | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed; inspect the JSON error' }
Invoke-Item -LiteralPath $prepared.interface
```

The paths refer to local experimental data, not distributed fixtures. Use the
matching original/report pair on another workstation. The S2.2b report points
to its exact S2.1 per-image report; that file must remain available at its
recorded path. Mismatched images/reports are rejected.

In the browser:

1. Enter an operator annotation identifier (for example, operator/session/card).
   Select the layout assessment. The default is **ambiguous**, not supported.
2. Inspect each side using the side selector, 0.25–16x zoom and endpoint/middle
   view buttons. Automatic candidates are hidden initially: leave them hidden
   when independently identifying the intended border. Drag empty space, hold
   Space while dragging, or enable the Pan tool to navigate. Wheel/trackpad zoom
   stays centered on the delivered pointer position; the slider zooms at the
   viewport center. The canvas remains 1100 x 650 drawing pixels even at high
   zoom. Its lossless derived PNG leaves the source unchanged.
3. Identify the **intended outer printed frame**. Do not substitute an artwork
   edge, name/text box, decorative stripe, shadow, scanner artifact or physical
   card edge. For Tritox, inspect the name/artwork transitions and bottom text
   region independently instead of assuming frame-0000 is correct.
4. For an independent starting line, choose **Place manual line** and click two
   points on the intended border, without viewing candidate overlays. Alternatively
   select a candidate as an explicitly biased starting hypothesis. Click a green
   line to select it, drag the entire line to translate it, or drag an orange
   endpoint to change orientation independently. The white-halo side is active;
   a white-filled handle is the selected endpoint. A white dashed preview appears
   while dragging. Release commits geometry, **not confirmation**. Escape cancels.
5. Inspect the entire usable side and click **Confirm reviewed side** explicitly.
   Candidate selection, pointer edits, reset and numerical geometry/span edits do
   not confirm a side. Changing a previously confirmed geometry clears its
   confirmation. Mark uncertainty with the existing ambiguous/unannotatable
   statuses instead of inventing a boundary. Layout support is a separate
   operator assessment. Side notes and geometry survive side switches without
   a discard prompt. Ctrl+Z / Ctrl+Y and Undo/Redo restore annotation edits,
   including their previous status. **Reset initial candidate** restores the
   first chosen candidate for that side, or its imported candidate basis, and
   leaves it unconfirmed; it never chooses a detector candidate automatically.
6. Download a new reference JSON version. In-progress gestures and invalid
   numerical drafts block export. Unconfirmed/ambiguous sides may be exported
   as incomplete references, preserving their flags and preventing complete
   ranking. Each export receives a new UUID and UTC timestamp. Downloads do not
   write into capture folders or automatically become validated references.

For precise movement, select the line or endpoint and use arrow keys: **1 original
pixel**, or **0.1 original pixel** with Shift or Fine adjustment. Hold Shift before
starting a drag (or enable Fine) for 0.1x pointer motion. With no selection, arrows
pan; Escape deselects. No pixel snapping or display-value rounding is applied.
Two independently draggable endpoints define the exact infinite `line_abc`.
Invalid coincident handles or a line incompatible with its side are rejected,
never silently approximated. Pointer cancellation leaves the stored line intact.

Advanced numerical controls remain synchronized with the visual line. Offsets
refer to intersections at the evaluation-span fractions, not necessarily the
freely dragged handle positions. Changing only the span preserves line geometry.
Offset edits are previews until applied or committed on field change; valid
drafts commit on side switch, while invalid drafts are retained separately and
block export until corrected or explicitly discarded. Coefficients are stored
as original-pixel doubles. Reopening reconstructs handles at the usable span;
their visual placement can change, but the exported infinite line is unchanged.

Editor legend: **cyan** physical contour, **magenta** automatic candidates,
**green** reference regardless of candidate/manual origin, **white halo** active
side, **orange handles** endpoints, **white dashed** pending preview. Unconfirmed
references are dashed. Origin and status are displayed in text and exported.
The existing comparison PNG legend is unchanged: lime candidate reference,
yellow manual reference, magenta hypothesis and orange displacement connectors.
Lines may overlap; use visibility toggles and inspect coefficients. The interface
has no network requests, API, authentication or server. Previously generated HTML
files are immutable snapshots: run `prepare` again to obtain the interactive
editor. Use `--reference` to reopen a saved reference without losing its geometry.
The synthetic browser test uses a private loopback DevTools connection only.

Validate and preserve the downloaded annotation, then compare all hypotheses:

```powershell
$download = 'C:\Users\plher\Downloads\spectra-reference-<UUID>.json'
$saved = & $python reference_frames.py save $image $s22b --reference $download | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Reference validation/storage failed' }
$saved.reference

$compared = & $python reference_frames.py compare $image $s22b --reference $saved.reference | ConvertFrom-Json
if ($LASTEXITCODE -ne 2) { throw 'Comparison failed; inspect the JSON error' }
$report = Get-Content -LiteralPath $compared.report -Raw | ConvertFrom-Json
$report.reference_quality_flags
$report.common_spans_fraction
$report.hypotheses | Sort-Object rank,hypothesis_id | Select-Object hypothesis_id,rank,comparison_availability,aggregate,exclusion_reasons

$ranked = @($report.hypotheses | Where-Object { $null -ne $_.rank } | Sort-Object rank,hypothesis_id)
if ($ranked.Count -gt 0) {
  $best = $ranked[0]
  $best.per_side | ConvertTo-Json -Depth 12
  Invoke-Item -LiteralPath (Join-Path (Split-Path $compared.report) $best.overlay)
}
Invoke-Item -LiteralPath (Join-Path (Split-Path $compared.report) 'summary.txt')

# Revise a saved version without overwriting it:
$revision = & $python reference_frames.py prepare $image $s22b --reference $saved.reference | ConvertFrom-Json
Invoke-Item -LiteralPath $revision.interface
# Download, save and compare the NEW version with the same commands above.
```

All generated files live under ignored `local_data/s2_2c/` in unique operation /
UTC-UUID directories. Exclusive creation prevents accidental overwrites. Saving
the same downloaded version twice preserves both imports; its logical version
ID remains the same. A revised export receives a new version and links the
previous saved file's SHA-256. The original, S2.1 report, S2.2b report and supplied
annotation are hashed again at command completion. Parent hashes link operator
versions; they are not signed identities or a production audit system.

Exit codes: **0** prepared/saved, **2** inspected or compared with
`review_required`, **3** rejected input or processing error. CLI failures emit
structured JSON errors. No comparison issues a successful acceptance status.

## Reference and provenance contract

`annotation.schema.json` documents the reference. It records image SHA-256,
acquisition ID when known, exact S2.1/S2.2b report paths/hashes/identifiers and
algorithm versions, tool/schema versions, UTC timestamp, source dimensions,
reported DPI/provenance, operator identifier, version/parent hash, layout status,
per-side status, candidate/manual definition, fitted equation, usable span and
optional notes. Unsupported layouts can retain tentative lines for inspection
without making them eligible for ranking.

Coordinates are `original_image_pixels_xy_right_down_v1`: original image pixel
coordinates, x right, y down, line equation **a*x + b*y + c = 0**. Top/right/
bottom/left follow S2.1's clockwise corner order; they do not establish printed
upright orientation. A side span is a fraction along its S2.1 physical side,
not a cropped-image coordinate. Source hash, coordinate-system, dimension, DPI,
report or candidate-selection mismatches are rejected. A manually adjusted line
cannot continue claiming exact candidate selection. Unknown coordinate systems
and incompatible reports fail closed.

Complete references must have four coherent lines forming a convex quadrilateral
strictly inside the physical card. Inconsistent reference geometry or support
outside the physical contour remains review-required and is excluded from
ranking. Missing, ambiguous and unannotatable sides are explicit, not filled in.
The layout must be operator-assessed `supported` for quantitative side comparison.
The reference explicitly asserts it is **not certified ground truth**.

The interactive editor requires **no schema extension**. It exports the existing
`line_abc`, definition, candidate/basis, span, notes and status fields. Unannotated
means no confirmed reference; a present `definition: candidate` line is a selected
but unverified candidate, while a present manual line is an unconfirmed manual
edit. Only explicit confirmation sets `status: annotated`; ambiguous and
unannotatable retain their original values. Existing annotated references remain
loadable, but that legacy status does not prove independent human validation.
Showing or accepting a candidate can bias an annotation even after confirmation.

## Meaning of comparison metrics

`comparison.schema.json` describes the report. Each hypothesis retains its ID,
four candidate IDs when available, geometric validity, complete/partial/none
comparison availability, exclusions, metrics and nullable rank.

- Each side has one **common valid span** for every complete eligible hypothesis.
  It intersects the operator's reference span with S2.2a's configured sampled
  extent and the actual candidate support-point extents. Candidate extents are
  pulled back through the reference-normal ray mapping, including tilted lines.
  An empty or unavailable common span prevents ranking. Extent does not prove
  continuous support at every intervening pixel; support evidence remains in
  S2.2b. Adding another hypothesis can narrow the span and change measurements;
  use the recorded spans when comparing separate experiments.
- At **51 equal positions** on that span, locate the reference line using the
  corresponding physical-side parameter. Intersect the hypothesis with a ray
  perpendicular to the reference. **Positive signed displacement means inward
  from reference toward the card interior**. Negative means outward. This is
  reference-normal displacement, not a single midpoint or corner-only error.
- Per-side outputs include raw signed and absolute arrays, mean signed error,
  mean absolute error, maximum absolute error and RMS. Mean signed error can
  cancel tilt errors; use absolute/RMS values and the entire distribution too.
- Overall mean absolute error uses equal weight for four sides, each with 51
  samples. Ranking uses this value only. Numerical ties within 1e-9 pixels have
  the same dense rank; this tolerance is arithmetic bookkeeping, not achievable
  scanner precision. Partial metrics are labeled and never ranked alongside
  complete comparisons. Invalid/incomplete hypotheses remain in the report.
- Millimeters scale displacement vectors using both reported DPI axes. They
  are DPI-derived estimates, not calibrated physical distances. Invalid or
  missing DPI yields null millimeters while preserving pixel metrics.
- Corner intersection differences are additional vector diagnostics only when
  both quadrilaterals are coherent. Near-parallel/invalid intersections are
  excluded. Side-span errors remain the primary ranking evidence.
- Duplicate combinations and duplicate normalized four-line geometries are
  reported separately, preserving all hypothesis IDs. Coefficient tolerance
  1e-8 is numerical duplicate detection, not visual or metrological equivalence.

The report preserves source/provenance hashes, annotation version, reference and
upstream flags, search truncation, spans, exclusions, duplicate inventory, all
hypothesis metrics and rankings. Up to **32** derived full-resolution overlays
are emitted, ranked first then stable hypothesis ID; the report flags any visual
limit, while all numerical rows are retained. Tritox's nine hypotheses fit
within the limit. `summary.txt` presents rankings/exclusions in readable form.

## Scientific interpretation and next operator work

Keep three questions separate:

1. **Repeatability:** variation across independent acquisitions and/or repeated
   annotations. Repeating this calculation on identical inputs establishes
   software determinism only. This module does not perform a new repeatability
   experiment or image registration.
2. **Manual-reference agreement:** the reported deviations quantify agreement
   with one operator's intended-frame interpretation on that original image.
   Selecting a candidate as reference creates circular agreement for that side;
   zero error is not independent detector validation. Repeat blinded annotations
   and compare operators/versions before interpreting small differences.
3. **Absolute physical accuracy:** remains unvalidated. Both S2.1 physical-side
   uncertainty and printed-frame/annotation uncertainty contribute. Neither
   nominal card dimensions, reported DPI, display magnification nor lowest error
   establishes metrological accuracy, calibrated confidence or correctness.

**Lowest error does not declare a hypothesis correct.** All comparisons remain
`review_required` with `automatic_acceptance: false`, including perfect agreement.
Upstream review, truncated candidate search, unsupported layout and ambiguity
cannot be cleared by ranking. A best rank only applies to the supplied explored
hypotheses and reference, not all possible frame definitions.

The real Tritox annotation interface and duplicate inventory were generated, but
**no real-world reference annotation or ranked Tritox comparison was fabricated**.
An operator must now inspect all four sides, define the intended outer frame,
mark uncertainty and save a reference before a quantitative Tritox ranking exists.
Previously prepared interface:
`local_data/s2_2c/prepare/20261018T033144_49ac5d83388a4e18b6ebc7b95197533d/annotate.html`.
The `prepare` command above creates a fresh one using the current tool.

## Validation

Validated on **2026-10-18**:

```powershell
# Unique basetemp avoids overwriting earlier test evidence. Run in a terminal
# permitted to launch Chrome; the renderer did not respond in the Codex sandbox.
$testRoot = 'local_data/s2_2c/full-tests-' + [guid]::NewGuid().ToString('N')
if (Test-Path -LiteralPath $testRoot) { throw 'Test path already exists' }
& $python -m pytest -q --basetemp $testRoot -p no:cacheprovider

& $python -m ruff check .
& $python -m ruff format --check .
& $python -m mypy spectra_scanner spectra_boundary spectra_centering spectra_frame_evaluation spectra_reference reference_frames.py evaluate_printed_frames.py
& $python -m compileall -q spectra_reference reference_frames.py
& $python -m pip check
node --check tests/reference-browser.mjs
.\.venv\Scripts\python.exe -m pytest -q
```

Full scanner suite: **243 passed in 21.38s**. This includes **21 new tests** and
the synthetic offline Chrome UI smoke test. S1-only environment: **131 passed,
5 optional analysis modules skipped in 2.91s**. Ruff passed; **67 files already
formatted**; mypy **40 source files** passed; compilation, dependency consistency,
Node syntax and schema JSON syntax checks passed. Python enforces the runtime
annotation contract; an external JSON Schema validator is not installed.
After improving overlays for incomplete references and checking span edits
preserve geometry, the final S2.2c suite passed again: **21 passed in 2.82s**,
including the synthetic Chrome workflow.

Tests cover perfect/parallel/tilted agreement, different common spans, numerical
geometry and combination duplicates, invalid provenance/coordinates, missing or
ambiguous sides, unsupported layouts, invalid DPI, incomplete hypotheses,
inconsistent references, version preservation, immutable inputs and real S2.2b
report-structure regression. The real-data test is skipped if local captures are
unavailable. Chrome/Node tests are optional when those tools are absent. The UI
test uses only synthetic imagery and captures exported JSON in memory.

An initial sandboxed UI run failed at Chrome DevTools; the outside-sandbox retry
first encountered sandbox-owned temporary-directory permissions. A new local
temporary directory resolved that, and the UI/full suite then passed. No
physical scanner, production frontend/backend workflow or real annotation was
executed by these tests.

Created files: `reference_frames.py`; `spectra_reference/{__init__,geometry,
inputs,comparison,artifacts}.py` and `annotation.html`; `tests/test_reference.py`
and `tests/reference-browser.mjs`; this README and the two schema files. No
existing S1/S2.1/S2.2a/S2.2b or production source files were edited.

All **1,568** protected pre-task detector/acquisition sources, schemas,
documentation, captures, manifests and experimental artifacts retained their
SHA-256 values. New artifacts are under the existing ignored `local_data/` tree.

## Interactive editing revision validation (2026-10-18)

The current editor adds two small local JavaScript assets, `editor-core.js` and
`editor.js`, which `artifacts.annotation_page` embeds directly into the generated
HTML. There is no external asset request, package installation, framework or
server. The pure geometry/history module is also exercised independently by Node.
Annotation schema version 1, the Python validator, CLI and comparison semantics
are unchanged. Free handle locations are transient UI state: the exact infinite
line remains in `line_abc`; re-import reconstructs handles without changing it.

Modified files:

- `spectra_reference/annotation.html`: editor controls and accessible instructions.
- `spectra_reference/artifacts.py`: inline the two local script assets.
- `tests/reference-browser.mjs`: Pointer Events and full pipeline regression.
- `tests/test_reference.py`: core geometry test and exported-reference round-trip.
- `experiments/reference/README.md`: revised operator workflow and validation.

Created files:

- `spectra_reference/editor-core.js`: original-pixel transforms, anchored zoom,
  line geometry, snapshot-based drag deltas and bounded history.
- `spectra_reference/editor.js`: offline editor interaction/controller.
- `tests/reference-editor-core.mjs`: deterministic geometry/history tests.

Current validation:

- Full scanner analysis suite: **244 passed in 20.74s** (including Chrome UI).
- S1-only environment: **131 passed, 5 skipped in 2.47s**.
- Standalone Node geometry test: passed at **0.25, 0.5, 1, 2, 8 and 16x** zoom
  with a scaled/offset viewport, original-pixel round-trips, line/endpoint movement,
  fine motion, pointer-anchored zoom, offsets, exact history and 1,000 previews
  without accumulated movement error.
- Browser regression: passed at **0.25, 1, 4 and 16x** with real pointer input,
  no stored mutation during previews, release commit, independent endpoints,
  0.1-pixel keyboard nudging, candidate/manual distinction, explicit confirmation,
  undo/redo, preserved side edits/drafts, reset, numerical synchronization,
  unchanged geometry when editing spans, anchored wheel zoom, panning, blind
  manual placement, ambiguity and exact JSON export. The exported synthetic JSON
  passed Python validation, save and compare, then re-opened/exported with exactly
  equal per-side fields and a valid previous-version hash. Comparison still
  returned `review_required` and `automatic_acceptance: false`.
- Ruff check/format, mypy (**40 files**), compilation, dependency consistency and
  Node syntax checks passed. No new Python or frontend dependencies were added.
- All **1,590** protected pre-revision files, including immutable source images,
  manifests, detector code/reports and previously generated S2.2c interfaces,
  retained their hashes. New interfaces remain ignored by Git.

Extra standalone checks, after setting `$python` as above:

```powershell
node tests/reference-editor-core.mjs
node --check spectra_reference/editor-core.js
node --check spectra_reference/editor.js
node --check tests/reference-browser.mjs
```

The first browser assertion incorrectly assumed fractional CDP wheel coordinates
would be delivered unchanged; it now verifies anchoring at Chrome's actual wheel
event position. The re-import test also exposed Windows' deep Chrome-profile path
limit; test profiles now use short unique ignored paths under
`local_data/reference-browser-profiles/`. These are test-harness changes, not a
rounding or approximation applied to annotation coordinates.

Validation uses synthetic references only. A fresh Tritox interface was prepared
with **no sides pre-annotated**; no real reference, physical scan, independent
detector validation or measurement-calibration claim was manufactured. An
operator must inspect and explicitly confirm each intended side. Legacy
`annotated` statuses remain readable and do not establish independent review.
