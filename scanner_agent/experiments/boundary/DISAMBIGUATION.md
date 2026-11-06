# S2.1 targeted physical-boundary disambiguation (algorithm 0.2.0)

This iteration improves **provisional boundary selection and evidence**, not physical
accuracy certification. It does not change S1, acquisition settings, original files,
production grading, custody, audit, authorization, payment or database code. No new
physical scans were executed. All reports and diagnostic images use new exclusive
analysis directories; previous reports remain unchanged.

## What caused the original displacement

The previous selector chose the largest one-pixel signed-normal Canny point bin,
then fitted points within two pixels of that bin. All sufficiently separated dense
alternatives caused review, but their raw image evidence was not examined for
selection. More texture points could outweigh a physical boundary.

The original real gamma-2.2/contrast-0 BMP and its support files are accessible.
Inspection of the original support coordinates, histograms and original-gray normal
profiles reproduces the right-side switch:

| Right-side normal bin, positive inward from contour seed | Baseline count | Preprocessed count |
| --- | ---: | ---: |
| [4,5) pixels | 524 | 528 |
| [9,10) pixels | 492 | 530 |

Thus the winner changed from the exterior-transition neighborhood to an approximately
five-pixel-more-inward layer. The point counts do not establish which is physical.
This was a density-ranking instability, not evidence of changed card geometry.

The original raw grayscale median falls from roughly 242 outside the right side
to 131 at seed offset 4 and approximately 81 at offset 9. The strongest localized
fall is near 4; the inward layer is already on the darker card-side portion of the
profile. Its numerous Canny points therefore need different interpretation from
the exterior backing transition. Exact raw profiles and point samples are retained,
not classified as printed border or shadow solely from this description.

## Selection criterion and conservative guards

`layers.py` now enumerates separated candidate bins and fits each layer. Labels
L0, L1, etc. are local to that side and preprocessing mode, sorted by bin offset.
The original point-density winner is marked `legacy_density_winner` for comparison.
All retained candidates record coefficients, peak counts, point samples, coverage,
residuals, scores, criterion failures and selected/rejected disposition.

Every candidate is assessed using the **original grayscale**, even when candidate
edges came from a normalized working image. It samples 160 profiles along the same
straight side portion, excluding the rounded-corner regions. Bilinear sampling
reads the original coordinate system; it does not edit or resample an original file.

The provisional criterion requires:

1. Existing residual and coverage checks: RMS <=2 pixels and coverage >=0.65 by
   default. At least 20 inlier points remain required. Nothing about the previous
   geometry, margin, aspect, DPI or nominal-dimension tolerances is relaxed.
2. Consistent inward darkening: >=75% positive signed gradients and >=75% profiles
   with a raw drop of at least 20 code values across +/-2 pixels. Positive here
   means exterior is brighter than interior; no inference is made for white-on-white
   boundaries that lack this evidence.
3. A localized transition, not merely broad illumination change: the median slope
   over +/-1 pixel divided by the broad +/-8-pixel slope must be >=1.15.
4. A path to the exterior backing. Per-profile backing is estimated from the first
   eight available samples at the exterior end of the search strip. Across the
   upstream corridor ending four pixels outside the fitted line, the median worst
   intensity deficit may be at most 35% of the background-to-inside drop. The corridor
   reaches at least 48 pixels and scales with search width. Invalid out-of-image
   samples are excluded, never treated as dark backing.

The **whole exterior corridor** is checked: a white printed band inside a dark card
border cannot masquerade as exterior backing just because one nearby probe looks
white. Spatial distance alone is insufficient, and there is no outermost-edge
preference. A weak outer shadow can lose to a sharper, coherent physical-transition
candidate farther inward. Strong shadows or multiple coherent transitions can remain
indistinguishable from image evidence and require review.

Eligible candidates are ranked by raw signed drop, strong-profile fraction, coverage,
residual and exterior-path consistency. Nominal 63 x 88 mm dimensions do **not** enter
the ranking. The score is a heuristic, not a probability. If none qualifies, a best
available provisional fit remains available for diagnosis with explicit review;
it is not silently declared a physical boundary.

Crucially, the old safety guard remains intact: another bin more than three pixels
from the old density winner with >35% of its count still causes
`legacy_density_competition_retained`. Candidate ranking does not clear that guard.
The iteration also retains review for multiple criterion-passing candidates, another
coherent darkening transition, no eligible candidate, or a substantial exterior
shoulder (>15% local deficit four pixels outside the selected fit). A shoulder can
be blur, shadow or another effect; it is not automatically classified.

`physical_criterion_passed` on a candidate means it passes this ranking criterion.
It is distinct from side-level `physical_selection_resolved` and overall success.
The selected disposition always says `provisional_selected`. The strong-gradient
locus within a blurred transition is not independently established as the exact
material edge. Stability, low residuals and plausible dimensions do not prove it.

Configuration is recorded under `physical_boundary`; defaults are visible in
`config.example.json`. Unknown/invalid values are rejected. Global normalization
affects candidate generation only; it does not replace the raw-profile evidence.

## Real competing layers on all four sides

There are 8/9/9/7 retained candidates for top/right/bottom/left in each variant.
All alternatives, including weaker texture layers, remain in the reports. Baseline
highlights (bin centers are labels for the integer-bin intervals, not exact fitted
positions):

| Side | Provisional layer | Raw +/-2-pixel drop | Principal alternative | Alternative drop | Interpretation supported by the evidence |
| --- | --- | ---: | --- | ---: | --- |
| Top 0 | L0, bin center 4.5 | 99 | L1, 9.5; old density winner | 27 | L0 is closer to exterior backing and has a much stronger continuous transition; L1 is already inward, but a coherent extra transition remains a review reason |
| Right 1 | L2, 4.5 | 92 | L3, 9.5; preprocessed old density winner | 8 | L3 has weak local drop and poor exterior-path consistency despite dense support |
| Bottom 2 | L0, 0.5 | 145 | L1, 5.5 | 19 | L0 is the strong exterior transition; L1 is a weaker inward layer |
| Left 3 | L0, 2.5 | 107 | L1, 6.5, and dense L2, 13.5 | 10 / 3 | L0 has the coherent exterior transition; inward candidates are mostly weak/texture evidence; exterior shoulder still requires review |

These descriptions distinguish exterior-transition evidence from inward texture,
printed-border possibilities and exterior-shoulder/shadow possibilities without
claiming their physical classes are proven. The top selection changes from the old
baseline as well: the baseline was not used as ground truth.

Detailed right-side comparison:

| Quantity | Baseline L2 selected | Preprocessed L2 selected | Baseline L3 rejected | Preprocessed L3 rejected |
| --- | ---: | ---: | ---: | ---: |
| Peak bin count | 524 | 528 | 492 | 530 |
| Coverage | 1.000 | 1.000 | 0.975 | 1.000 |
| Raw signed local drop | 92 | 93 | 8 | 7 |
| Positive gradient fraction | 0.981 | 0.981 | 0.731 | 0.731 |
| Exterior-path deficit fraction | 0.218 | 0.217 | 0.856 | 0.856 |
| Raw-criterion support score | 27.078 | 27.382 | 0.085 | 0.064 |

The more-outward L1 near bin 0.5 has a substantial raw drop (~63) but only 0.475/0.525
edge coverage; it fails the existing 0.65 limit. L0 is sparser still. They are kept
as possible shoulder/low-support alternatives, not selected just for being outward.
Other right-side layers at 15.5-36.5 have median drops around -3 to +2 and are not
consistent with the backing-to-card transition. A raw exterior plateau is observed
about 13 pixels outward of the selected fitted line versus about 18 for L3; this
distance is diagnostic, not by itself a selection rule or scale calibration.

Bin centers and fitted midpoint locations are both reported. Sparse low-coverage
fits can extrapolate far from their peak bin away from their actual support; do not
treat that extrapolation as physical evidence. Their low coverage and failures
remain visible in JSON and zoom legends.

## Baseline/preprocessed displacement

Candidate IDs are not assumed equivalent across modes. A one-to-one nearest-line
midpoint match within 2 pixels is reported with unmatched candidates preserved.
This is a diagnostic correspondence rule, not proof of the same physical layer.

All selected sides are compared along the baseline inward normal at its seed start,
midpoint and end in the original image coordinate system. Positive means inward.
The real right side gives approximately:

```text
start:    -0.007633 pixels
midpoint: -0.023562 pixels
end:      -0.039491 pixels
```

The right-corner intersection changes are:

| Corner | Original implementation horizontal change | Current horizontal change | Current vertical change | Current 2D magnitude |
| --- | ---: | ---: | ---: | ---: |
| Top-right | -6.064221 | +0.007791 | +0.029017 | ~0.030044 |
| Bottom-right | -4.637994 | +0.039502 | +0.013440 | ~0.041726 |

Left-corner horizontal changes remain about +0.182 and -0.214 pixels. These are
same-image algorithm-sensitivity measurements, **not** scanner repeatability or
subpixel accuracy. The real capture still has `review_required` in both variants;
all four density-competition guards remain active. Top/right retain extra coherent
transition concerns, and right/left have non-plateau exterior approaches. Nominal
card dimensions are not evidence that these provisional lines are correct.

## Diagnostics and exact rerun command

From `scanner_agent` in the already installed analysis environment:

```powershell
$scan = 'local_data/contrast-ab/c0/captures/20261017T173237_f7bd5f05b3cd4748b1ad764e9c390695/original.bmp'
.\.venv-analysis\Scripts\python.exe analyze_boundaries.py analyze $scan --config experiments/boundary/config.example.json --compare-preprocessing
```

This analyzes the existing file only and produces a fresh `local_data/s2_1/<id>`.
The printed pointer leads to a top-level index, then `scan-000/report.json`.
New artifacts for **each** baseline/preprocessed variant:

- Four `*-side-0-zoom.png` through `*-side-3-zoom.png` panels: unannotated source
  beside colored/labelled candidate overlays, raw support samples, selected cyan
  fit, score/coverage/drop/polarity table and raw-versus-working normal-profile plot.
- Four `*-corner-0-zoom.png` through `*-corner-3-zoom.png` source/overlay pairs,
  showing extrapolated candidate lines and the selected theoretical intersection.
  Labels include side index because L0 etc. are local to a side.
- `parallel-layer-comparison.json`: complete candidate evidence for each side,
  geometric matches, unmatched IDs, signed normal displacement and an explicit
  `right_side_comparison`. Corner displacement is in `report.json` under
  `preprocessing_comparison`, including vector and 2D magnitude.

Crop boxes are recorded in original pixels. Diagnostic zooms use explicit 4x nearest
neighbor magnification; these are derived visualization files, never original
replacements. Raw and working curves overlap in baseline mode. Scores/labels are
not grading outputs. Accepted/rejected edge coordinates and the original full-image
overlays remain available as before. The schema now also describes candidate layers.

The new diagnostics should be reviewed alongside the unannotated source. Resolving
the remaining shadow/blur/material-edge ambiguity requires independent physical-edge
annotations or a suitable reference experiment. Do not clear review simply because
the two tonal variants now agree.

## Validation

New synthetic tests cover close printed borders (including a white internal band),
wrong gradient polarity, multiple parallel layers, external weak/strong shadows,
not selecting the outermost shadow by default, alternate normalizations, small
source-tone changes, preserved ambiguity guards, geometric candidate matching,
all side/corner artifacts, and refusal to overwrite outputs. The entire original
S2.1 suite is also run. Results and final diagnostic locations are recorded below.

Final validation on 2026-10-17:

| Check | Actual result |
| --- | --- |
| Full isolated scanner-agent suite | **189 passed in 10.88s**, including all 41 prior S2.1 cases and 17 new cases |
| Original S1-only environment | 131 passed, 2 optional analysis modules skipped in 2.34s |
| Ruff lint | All checks passed |
| Ruff formatting | 43 files already formatted |
| Mypy | No issues in 23 source files |
| Compilation | Passed |
| Dependency compatibility | No broken requirements; no new dependencies added |
| Existing original and reports | 35 protected files hash-verified unchanged, including original BMP, S1 metadata and previous diagnostics |
| New real-image analysis | Both variants remain review_required; 16 side/corner zooms generated and right-side/corner diagnostics visually inspected |
| Schema | Updated schema JSON syntax parsed; full draft-2020-12 validation not run |
| Repository whitespace | `git diff --check` passed; pre-existing LF/CRLF notices |

Final real-image index:
`local_data/s2_1/20261017T182453_6affb45673054b41b3ed2d16631bf72b/report.json`.
All detailed files are in its `scan-000` directory, particularly
`baseline-side-1-zoom.png`, `preprocessed-side-1-zoom.png`, the eight corner zooms,
`parallel-layer-comparison.json`, and `report.json`. Full point sets remain in the
baseline/preprocessed support sidecars. These ignored local artifacts are available
on this workstation; source images are not copied into tracked documentation.

Changed code is limited to the experimental S2.1 package: new `layers.py`,
`diagnostics.py`, `displacement.py`; updated `detector.py`, `analysis.py`, `config.py`
and algorithm version. The report schema, example configuration, documentation and
`tests/test_boundary_layers.py` were added/updated alongside them. S1 acquisition,
original capture manifests, production systems and unrelated working-tree changes
were preserved. No physical scanning or metrological validation was performed.
