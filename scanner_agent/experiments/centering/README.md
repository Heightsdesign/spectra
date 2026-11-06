# S2.2a — printed frame diagnostics, algorithm 0.1.0

This isolated vertical slice reads an immutable original and a **per-image S2.1
0.2.0 schema-1 report**, using its **baseline** selected physical sides. It does
not rerun or change S1/S2.1, acquire images, assign grades, or access production.
An index or repeatability summary is incompatible: use `scan-000/report.json`.

## Windows PowerShell quick start

From the repository root:

```powershell
Set-Location .\scanner_agent
# Reuse the existing analysis environment when available. For a new environment:
py -3.13 -m venv .venv-analysis
.\.venv-analysis\Scripts\python.exe -m pip install -r requirements-analysis.txt

$image = 'local_data\s2_1_validation\card-a\scan-1\captures\20261017T184714_f46f9ce59a8644009dff682365d48a3f\original.bmp'
$boundary = 'local_data\s2_1\20261017T191445_7938424fdc284f2da02470378250a71e\scan-000\report.json'
.\.venv-analysis\Scripts\python.exe analyze_printed_frame.py $image $boundary --config experiments\centering\traditional-frame.json
$LASTEXITCODE
```

The recommended first capture is **Tritox** at the paths above, which visibly has
a traditional outer frame. The full-art Mega Lucario and square-corner anime
captures are unsuitable initial positive controls. Paths are local experimental
artifacts, not distributed fixtures; substitute a matching image/report pair on
another workstation. No scanner command is invoked.

The CLI prints the unique report path under `local_data\s2_2a\<UTC_UUID>\`.
Exit **2** means `review_required` or `not_applicable`; **3** means
`analysis_failed` (including missing/incompatible inputs). There is deliberately
no automatic-success exit. Argument syntax errors follow argparse's exit 2.
Each run creates a new directory; existing outputs cannot be reused. Artifacts
are already excluded by the scanner agent's `local_data/` ignore rule.

```powershell
$report = 'local_data\s2_2a\<ID printed by CLI>\report.json'
$r = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
$r.status
$r.quality_flags
$r.sides | Select-Object name, selected_candidate_id, ambiguous
$r.measurements | ConvertTo-Json -Depth 12
Invoke-Item (Join-Path (Split-Path $report) 'overlay.png')
Invoke-Item (Join-Path (Split-Path $report) 'side-right.png')
```

`overlay.png` and `side-top/right/bottom/left.png` are derived visualizations.
Cyan denotes physical sides; lime denotes uniquely selected printed sides.
Other colored lines and support dots retain alternative candidates. Candidate
IDs link to the JSON and per-side evidence tables; rejected candidates remain
visible. Color cycling is diagnostic, not confidence. Inspect all four sides,
including apparent strong candidates that were rejected. These PNGs do not
replace or transform the BMP original.

## Model and measurement contract

Only `traditional_frame` is supported: an approximately homogeneous outer
printed band surrounding coherent inner transitions. This is a deliberately
limited design hypothesis, not a universal card detector.

1. Verify source SHA-256 against the frozen report, image dimensions/channels,
   ordered clockwise convex corners, selected side-line agreement and upstream
   geometric validation. Failed upstream analyses and incompatible versions
   fail closed. Original and report hashes are checked again after analysis.
2. Establish a card-unit-square homography and its inverse for coordinate
   interpretation. **No rectified image is used as a metric measurement.**
   Top/right/bottom/left follow upstream corner order; they do not identify
   printed upright orientation. An upside-down image can swap semantic sides.
3. Sample 120 inward normal profiles per side, excluding the outer 18% of each
   end to avoid rounded corners. Default search spans 0.8–12% of transverse
   card span; no nominal physical card size is used. Sampling uses bilinear
   interpolation into derived arrays without changing original pixels.
4. Find sustained symmetric four-pixel RGB transitions. Preserve separated
   peaks, fit straight lines using Huber fitting, and require sufficient support,
   low residuals, similar side orientation and an approximately homogeneous
   exterior printed band. Along-side color variation and interior corridor
   variation both count against a traditional-frame hypothesis. Cross-side
   outer-band colors must also agree before emitting ratios.
5. Preserve all retained candidates, gradients, profiles, support points,
   residuals and rejection reasons. Multiple eligible candidates, or truncating
   the candidate list, prevents selection. Never choose the outermost or highest
   peak merely because it looks plausible. There is no boundary fabrication.
6. When every side is uniquely supported, validate the printed quadrilateral
   inside the physical one. Measure 21 perpendicular ray distances per side;
   report their distribution, mean, extrema and standard deviation. Left/right
   and top/bottom percentages use the corresponding mean distances. This
   handles modest nonparallelism rather than relying on one midpoint.

Parameters in `traditional-frame.json` are experimental evidence thresholds,
not grade thresholds or calibrated probabilities. Copy the configuration to a
new filename for experiments; record differences instead of tuning until one
real card passes. RGB values are decoded code values, not calibrated Lab/color
measurements. No gamma, contrast, sharpening, rotation, crop or ICC conversion
is applied by this package.

Raw distances are original-image pixels. Optional millimeters scale original
normal directions using both reported DPI axes; invalid/missing DPI yields
`null` millimeters while preserving pixel measurements. Neither nominal card
size nor scanner DPI establishes absolute accuracy.

## Status and uncertainty

- `review_required`: supported conditional measurements, competing candidates,
  or inconsistent cross-side evidence requiring review. All supported analyses
  still require review because this experiment is not calibrated.
- `not_applicable`: insufficient evidence for the current traditional-frame
  hypothesis. **This is not proof that the card is borderless.** Ratios are null.
- `analysis_failed`: missing/corrupt/mismatched inputs, incompatible report,
  invalid physical/printed geometry, or changed inputs. Ratios are null.

`automatic_acceptance` is always false. Upstream review and physical-side
ambiguity are preserved as flags; downstream evidence cannot clear them.
Physical-boundary uncertainty **and** printed-frame uncertainty affect centering.
Line RMS describes fit residuals only. Sample variation is not a calibrated
uncertainty interval, and conditional ratios do not establish physical accuracy.

The machine-readable contract is `report.schema.json` (draft 2020-12). Successful
input validation includes original/report hashes, upstream selected variant and
side evidence, DPI provenance, algorithm/config versions, transforms, candidates,
measurements if eligible, status, quality flags and diagnostic paths. Failure
reports preserve available hashes and structured errors. Schema version 1 is
separate from algorithm 0.1.0 and frozen upstream algorithm 0.2.0.

## Real capture result and limitations

The recommended Tritox capture was analyzed without modifying it. Final run:
`local_data/s2_2a/20261017T200641_513cff16b98b49288fe2c04701b87d38/report.json`.
Result: **not_applicable**, no centering ratios. Strongest near-frame transitions
appear approximately 63.64 px top, 58.91 px right, 57.67 px bottom and 61.90 px
left inward from the selected physical sides. All four have full transition
support, but the outer-band variation exceeds the initial homogeneous-band
criterion (about 24.68, 22.71, 72.42 and 24.36 RGB RMS respectively). Alternative
transitions and rejection reasons remain in JSON and diagnostics. These are
candidate positions, not verified frame margins. Upstream remains review-required.
Thresholds were not relaxed to force this capture to pass.

The next human validation is to inspect the bottom band and all candidate lines
against the original, identify what the design's intended frame actually is,
and independently annotate sides before evaluating additional framed cards.
Metallic/gradient frames, text or artwork in the outer band, very narrow/wide
borders outside the search interval, curved printed sides and weak transitions
can fail this model. A uniform artwork rectangle can be indistinguishable from
a true frame without design knowledge; human review remains mandatory. The
central side portions provide evidence, not full corner/edge coverage. No
scanner repeatability, physical accuracy or real-card detection accuracy is
established by the synthetic suite. No S2.2b or grading integration is included.

## Validation on 2026-10-17

```powershell
.\.venv-analysis\Scripts\python.exe -m pytest -q
.\.venv-analysis\Scripts\python.exe -m ruff check .
.\.venv-analysis\Scripts\python.exe -m ruff format --check .
.\.venv-analysis\Scripts\python.exe -m mypy spectra_scanner spectra_boundary spectra_centering
.\.venv-analysis\Scripts\python.exe -m compileall -q spectra_centering analyze_printed_frame.py
.\.venv-analysis\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
```

Analysis environment: **207 passed in 11.94s**, including **18 new tests**.
S1-only environment: **131 passed, 3 skipped in 2.34s** (optional analysis
modules absent). Ruff passed; **52 files formatted**; mypy **29 source files**
passed; compilation passed; pip reported no broken requirements. The JSON schema
was parsed as JSON; an external JSON Schema validator is not installed in this
environment. Synthetic tests cover centered/off-center, rotation, weak contrast,
misleading artwork, missing frame, competing alternatives, nonparallel margins,
bad DPI, bad/missing/corrupt/mismatched reports, immutability and unique CLI output.
No physical scans were executed. Frontend/backend suites are outside this
isolated change; no production files were edited.

All **319** protected S1/S2.1 source, schema, documentation, original-image,
capture-metadata and generated-report files matched their pre-implementation
SHA-256 snapshot. New generated artifacts were confirmed ignored by Git.
