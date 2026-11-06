# S2.2b — experimental printed-frame candidate evaluation

This is an isolated diagnostic evaluator (`spectra_frame_evaluation`, algorithm
0.1.0, schema/configuration version 1). It imports the **unchanged** S2.2a 0.1.0
candidate generator and S2.1 input adapter. It neither replaces S2.2a nor reruns
S2.1. No acquisition, original-image transformation, grade assignment or
production integration is performed.

## Run the same Tritox scan through S2.2a and S2.2b

PowerShell, from the repository root:

```powershell
Set-Location .\scanner_agent
# Use the existing analysis environment; no new dependency was introduced.
# For a new environment only:
# py -3.13 -m venv .venv-analysis
# .\.venv-analysis\Scripts\python.exe -m pip install -r requirements-analysis.txt

$image = 'local_data\s2_1_validation\card-a\scan-1\captures\20261017T184714_f46f9ce59a8644009dff682365d48a3f\original.bmp'
$boundary = 'local_data\s2_1\20261017T191445_7938424fdc284f2da02470378250a71e\scan-000\report.json'

.\.venv-analysis\Scripts\python.exe analyze_printed_frame.py $image $boundary --config experiments\centering\traditional-frame.json
.\.venv-analysis\Scripts\python.exe evaluate_printed_frames.py $image $boundary --config experiments\frame_evaluation\evaluation.json
```

Both print a new report path. Exit **2** is an expected non-acceptance outcome
(`review_required` or `not_applicable`), **3** is `analysis_failed`. S2.2b has no
automatic-success status. Input reports must be per-image S2.1 0.2.0 baseline
reports, not index/repeatability summaries. Paths above refer to existing local
data; they are not distributed image fixtures.

Outputs go exclusively to new unique `local_data/s2_2b/<UTC_UUID>/` directories.
Files are created exclusively, never reused. `local_data/` is already ignored by
Git. The image SHA must match the S2.1 report, and both inputs are hashed again
after processing. Originals, manifests and previous reports remain unchanged.

## Evidence dimensions and retention

Every candidate preserves S2.2a's raw fields and original `rejection_reasons`,
including `heterogeneous_outer_band`. Its original `eligible` flag still means
S2.2a eligibility. New fields are separate:

- `geometry_evidence`: support fraction/count, RMS and angular difference.
  Support is gradient-supported points within 3 px of the fitted line, divided
  by all sampled profiles. It is independent of the heterogeneity veto, **not**
  statistically independent of transition strength.
- `transition_evidence`: RGB transition vectors and RMS strengths at all 120
  positions along the actual fitted line, using samples 2 px on either side.
  Mean, p10/median/p90, standard deviation, coefficient of variation and signed
  RGB-vector direction agreement are recorded. Direction agreement uses cosine
  >=0.5 against the median vector; it is not brightness polarity alone.
- Exterior evidence: original S2.2a band deviation, plus RGB mean/std and spatial
  differences along/across a 48-position outer corridor. These describe color
  and sampled texture variation without conflating it with geometric validity.
  Spatial differences depend on sampling spacing; they are not calibrated
  texture measurements. A missing/invalid fitted line has null new evidence
  with an explicit rejection, rather than invented values.
- `distance_pixels` preserves the original peak location. Per-ray fitted-line
  normal distances are also recorded; a peak location is not a measured margin.
- `retention`: `retained`, `provisional` or `rejected`;
  `additional_rejection_reasons` never replaces original rejection reasons.

Only candidates whose sole original rejection is heterogeneity can become
**provisional**, and only if independent transition evidence passes. Original
geometric failures remain rejected. Default additional limits are p10 RGB RMS
>=12, strength CV <=0.75 and direction agreement >=0.8. These are experimental
limits, not probabilities, grading thresholds or uncertainty bounds. The p10
floor reuses S2.2a's transition magnitude scale; defaults were not adjusted to
force Tritox to pass. Copy `evaluation.json` to a different filename for tuning;
complete resolved settings are persisted in each report.

## Four-sided hypotheses and conservative outcomes

Enumerate top/right/bottom/left retained or provisional combinations in stable
candidate order, bounded to **256** by default (configuration maximum 4096).
S2.2a candidate truncation is also propagated. Both counts and truncation are
reported, and any truncation prevents unique selection.

Each hypothesis records candidate IDs, provisional membership, opposite-side
angles, adjacent-angle deviation, corner intersections and rejection reasons.
It must form a convex, nondegenerate, clockwise quadrilateral strictly inside
the physical card, with positive multi-position perpendicular widths. Opposite
parallelism and adjacent compatibility use configurable 6-degree limits. No
nominal 63 x 88 mm assumption, equal-margin requirement or idealized replacement
rectangle is used. Hypothesis margins are **conditional raw-pixel diagnostics**;
no millimeters or accepted centering ratios are emitted by this slice.

All geometrically valid hypotheses remain unresolved peers. There is no
outermost-edge, strongest-transition, symmetry or color ranking that claims to
identify the intended frame. Corner displacements relative to the first valid
hypothesis quantify differences; that reference is not a preferred frame.
One valid non-truncated hypothesis gets a *geometric* selection ID only, not
semantic acceptance. More than one valid hypothesis gets no selection.

- No complete valid frame and complete search: `not_applicable`, not proof of
  borderlessness. Provisional retention alone cannot yield a measurement.
- Competing frames, unique investigation hypothesis, or truncated search:
  `review_required`.
- Invalid/missing/mismatched inputs or changed hashes: `analysis_failed`.

`automatic_acceptance` is **always false**, `measurements` is **always null**.
Upstream review/ambiguity flags remain attached. Physical-boundary uncertainty
and printed-frame uncertainty both matter. Residuals, RGB metrics and repeatable
geometry are not metrological accuracy, probabilities or confidence intervals.

## Diagnostics

`report.json` follows `report.schema.json` (draft 2020-12).
`overlay.png` and four `side-*.png` images show all generated candidates,
including rejected ones. Physical sides are cyan. Candidate colors/IDs are
diagnostic labels, not quality scores; per-side tables explicitly show original
rejections, new rejections and `S2.2b_provisional/retained/rejected` status.
The reused S2.2a drawing legend mentions lime selection, but no candidate is
drawn as selected by this evaluator; geometric hypotheses have a separate view.

`hypotheses.png` compares up to 12 valid hypotheses (or rejected combinations
if none is valid), with cyan physical sides and magenta candidate frames.
Visualization limits are reported separately from search truncation; full
evaluated evidence remains in JSON. `explanation.txt` summarizes why the frame
is unresolved or merely an investigation candidate.

```powershell
$report = 'local_data\s2_2b\<ID printed by CLI>\report.json'
$r = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
$r.sides | ForEach-Object { $_.candidates | Select-Object id, retention, rejection_reasons, additional_rejection_reasons }
$r.frame_evaluation | Select-Object possible_combinations, evaluated_count, valid_count, search_truncated, selected_geometric_hypothesis_id
Invoke-Item (Join-Path (Split-Path $report) 'hypotheses.png')
Invoke-Item (Join-Path (Split-Path $report) 'side-bottom.png')
```

## Tritox findings

S2.2a remains reproducible: **not_applicable**, no ratios. For the first capture,
S2.2b retains **8 provisional** candidates and leaves **5 rejected**. Pools are
3 top x 1 right x 3 bottom x 1 left: **9 valid geometric hypotheses**, no search
truncation and no selected frame. Result: **review_required**, no measurement.

Final same-scan pair and diagnostics:
`local_data/s2_2b_validation/20261017T202702_0892dd46243f4756a0076014efe3f13f/`
(`pair-000-a/report.json`, `pair-000-b/report.json`, and
`pair-000-b/hypotheses.png`). The S2.2a candidate list, status, measurements,
quality flags and physical corners exactly match the existing pre-S2.2b Tritox
report; comparison did not overwrite it.

| Candidate | Peak distance px | Original band deviation | New p10 transition RMS | Strength CV | Direction agreement | Retention |
|---|---:|---:|---:|---:|---:|---|
| top-0 | 63.64 | 24.68 | 53.91 | 0.202 | 0.975 | provisional |
| right-0 | 58.91 | 22.71 | 74.88 | 0.116 | 1.000 | provisional |

Top-1/top-2 and bottom-1/bottom-2/bottom-3 also remain plausible geometrically.
The right/left weaker internal layers and bottom-0 retain essential continuity
or transition failures. Heterogeneity is not erased or silently treated as good.
All three Tritox scans produce nine unresolved hypotheses, with provisional
candidate counts 8/7/8. This does not establish physical or semantic accuracy.

**Manual inspection is required.** Independently annotate the intended frame,
especially whether a transition belongs to the name/artwork boundary or the
outer frame, and whether bottom text/attack-box transitions are internal artwork.
Do not choose frame-0000 just because it is listed first. Printed text or artwork
can form a perfectly coherent inner rectangle; geometry alone cannot distinguish
it. Full-art cards, foils, weak transitions and designs outside S2.2a's search
range remain unsupported or ambiguous. Candidate generation and its limits are
unchanged; this experiment cannot recover an ungenerated boundary.

## Existing dataset regression

The explicit runner analyzes supplied local reports with both versions, using
identical default candidate generation, and creates a new comparison directory.
Its exit 0 means the **regression runner completed and hashes passed**, not that
any detector result was accepted.

```powershell
$series = @(
  '20261017T191434_ed041007911447ad8cb03d82057f60e3',
  '20261017T191445_7938424fdc284f2da02470378250a71e',
  '20261017T191452_8cd6169e69e04563a0abd32d417f3d50',
  '20261017T191503_56e87af61c3547468ace58d19fcd419e'
)
$reports = @(foreach ($id in $series) {
  Get-ChildItem -Path "local_data/s2_1/$id/scan-*/report.json" | ForEach-Object { $_.FullName }
})
.\.venv-analysis\Scripts\python.exe -m spectra_frame_evaluation.validation @reports
```

Across all **12** real scans, all original/report hashes passed. Three Tritox
scans changed from S2.2a `not_applicable` to S2.2b `review_required` with nine
unresolved hypotheses each. The other nine scans remained review-required with
candidate-generation truncation explicitly propagated and no valid explored
frame. None produced an accepted result. This is transparency/regression
evidence, not calibration or a true-positive accuracy benchmark.

Full dataset comparison:
`local_data/s2_2b_validation/20261017T202503_96a7eaaca32a42c996a4808ad59b9e3a/comparison.json`.

## Automated validation (2026-10-17)

```powershell
.\.venv-analysis\Scripts\python.exe -m pytest -q
.\.venv-analysis\Scripts\python.exe -m ruff check .
.\.venv-analysis\Scripts\python.exe -m ruff format --check .
.\.venv-analysis\Scripts\python.exe -m mypy spectra_scanner spectra_boundary spectra_centering spectra_frame_evaluation evaluate_printed_frames.py
.\.venv-analysis\Scripts\python.exe -m compileall -q spectra_frame_evaluation evaluate_printed_frames.py
.\.venv-analysis\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
```

Analysis suite: **222 passed in 14.93s**, including **15 new tests**. S1-only:
**131 passed, 4 optional analysis modules skipped in 2.42s**. Ruff, formatting,
mypy, compilation and dependency consistency checks passed. Tests cover coherent
heterogeneous bands, multiple parallel frames, asymmetric/rotated geometry,
incomplete frames, misleading artwork, upstream review, essential geometric
failures, input guards, both search limits, deterministic metrics/artifact bytes,
original/report immutability and unchanged S2.2a candidate/results behavior.
After improving the status labels, the targeted suite passed again:
**15 passed in 1.55s**, and the Tritox pair was regenerated in a fresh directory.
The schema is parsed as JSON; an external JSON Schema validator is not installed.
No physical scans or production suites were run; production files were untouched.

All **1,211** pre-existing protected S1/S2.1/S2.2a source, schema, documentation,
capture and experimental artifact files match the pre-task SHA-256 snapshot.
The snapshot itself and all new reports are under ignored `local_data/`.

Created files: four `spectra_frame_evaluation` modules (`__init__`, `evaluation`,
`analysis`, `validation`), `evaluate_printed_frames.py`,
`tests/test_frame_evaluation.py`, and this directory's README, configuration and
JSON schema. Existing S1, S2.1 and S2.2a files were not modified.
