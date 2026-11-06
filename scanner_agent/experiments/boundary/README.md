# SPECTRA S2.1 - experimental physical card boundaries and repeatability

This package analyzes **existing local test images**. It never calls acquisition,
connects to a device, changes S1 settings or originals, writes customer records,
or performs centering, grading, defect classification or production integration.
Algorithm 0.2.0 adds [targeted parallel-layer disambiguation](DISAMBIGUATION.md),
original-grayscale profile evidence, labeled source/overlay zooms and quantitative
baseline/preprocessing displacement reports. The historical 0.1.0 results below
are retained as prior evidence; current validation is in that investigation.
OpenCV/NumPy are installed in a separate analysis environment. S1 runtime code,
requirements and acquisition behavior are unchanged.

## Install on Windows

From the repository root, create the analysis environment once (reuse it thereafter):

```powershell
Set-Location C:\Users\plher\Documents\spetra\scanner_agent
py -3.13 -m venv .venv-analysis
.\.venv-analysis\Scripts\python.exe -m pip install -r requirements-analysis.txt
.\.venv-analysis\Scripts\python.exe -m pip check
```

Dependencies pin NumPy 2.4.6 and opencv-python-headless 4.13.0.92, plus the existing
S1 development requirements for regression testing. These releases provide Windows
CPython-compatible wheels: [NumPy](https://pypi.org/project/numpy/2.4.6/),
[OpenCV](https://pypi.org/project/opencv-python-headless/4.13.0.92/).
No GUI OpenCV package or production backend installation is needed. Overlays are PNG
files opened in the operator's image viewer, not windows launched by the detector.

## Analyze one existing original

An existing local gamma-2.2/contrast-0 capture can be analyzed directly:

```powershell
$scan = 'local_data/contrast-ab/c0/captures/20261017T173237_f7bd5f05b3cd4748b1ad764e9c390695/original.bmp'
.\.venv-analysis\Scripts\python.exe analyze_boundaries.py analyze $scan
```

For baseline versus optional preprocessing:

```powershell
.\.venv-analysis\Scripts\python.exe analyze_boundaries.py analyze $scan --config experiments/boundary/config.example.json --compare-preprocessing
```

The example specifies global 1st/99th-percentile normalization and working-image
contrast 1.05. The **baseline is always unenhanced grayscale**, even if configuration
contains preprocessing parameters. `--compare-preprocessing` runs the second path
and records both; it never substitutes the enhanced result as the preferred answer.
Baseline/preprocessed corner disagreement above the configured RMS limit or differing
geometry status requires review. A successful enhanced mode cannot rescue baseline
failure automatically. Without the comparison flag, preprocessing settings are not
applied; the baseline preprocessing actually used is recorded explicitly.

For another explicitly selected PNG/BMP/lossless TIFF, supply its path instead.
Inputs must decode fully as single-frame RGB24 with no nontrivial orientation tag.
Lossy JPEG, palette/alpha/grayscale files, corrupt images and nontrivial tagged
orientation are rejected explicitly rather than silently converted or rotated.
There is no folder watcher or production image discovery in this module.

The agent validates the S1 original hash against its adjacent manifest when present,
and hashes the image again after analysis. It reads S1 metadata without editing it.
Driver image-info DPI is preferred, otherwise embedded file DPI is used. Driver/file
DPI disagreement greater than 1 requires review. If DPI is missing, pixel geometry
is still reported but physical plausibility cannot pass. An explicit operator value
can be supplied with `--dpi 600`; its provenance remains an override, not calibration.
Nonfinite, nonpositive or out-of-range DPI is flagged; valid-range limits are 50-9600.

## Algorithm and justification

1. Verify encoding, dimensions/channels, file integrity and metadata; decode without
   spatial alteration. Coordinates always refer to the original image pixel grid.
2. Convert RGB to grayscale. Optional global percentile normalization/contrast
   operate on a derived working array only; no sharpening, local reconstruction,
   perspective correction or generated edges are used.
3. Otsu inverse thresholding on the white-backed image identifies connected exterior
   contour candidates. Candidate minimum area is a fraction of the whole image,
   not a hardcoded card coordinate. Similar-size competing candidates require review.
4. A minimum-area rotated rectangle seeds four orientation/position search strips.
   **Its corners are never the final corners or a fallback result.** The central
   64% of each side is searched by default, excluding 18% at either end so rounded
   corners are not used as straight-side evidence. Search width scales with the
   candidate's short dimension, not a fixed Lucario-card rectangle.
5. Canny edge points inside each strip are grouped into competing signed-normal
   layers. Each is fitted and assessed using original-grayscale polarity, contrast,
   continuity, transition localization and a path back to exterior backing. Density
   alone no longer selects the fit. Every alternative is retained. The original
   density-competition guard remains active; no threshold is relaxed.
6. OpenCV Huber line fitting estimates each side; distant points are rejected and
   the fit is repeated on inliers. At least 20 points per side and adequate along-side
   support are required. Coverage is occupied bins in a 40-bin straight-side span.
7. Adjacent independently fitted lines are intersected to give four theoretical
   sharp corners. These are extrapolated intersections, not rounded-outline vertices.
   Degenerate intersections fail; there is no axis-aligned or rotated-box fallback.
8. Validate convexity/non-self-intersection, opposite parallelism, adjacent
   perpendicularity, aspect ratio, DPI-derived dimensions, image margins, residuals,
   coverage and parallel-edge ambiguity.

Contour seeding provides a coherent exterior candidate and avoids treating every
printed edge as a physical boundary; independent robust side fits avoid equating
rounded contour corners with physical corner intersections. Canny can still expose
printed borders/shadows as alternative sides, so ambiguity is retained explicitly.
Relevant primary API documentation: [contours](https://docs.opencv.org/4.x/df/d0d/tutorial_find_contours.html)
and [line fitting / contour features](https://docs.opencv.org/4.11.0/dd/d49/tutorial_py_contour_features.html).

## Configurable checks and units

Copy/edit `config.example.json` in local test storage when exploring tolerances.
Unknown configuration keys and invalid numeric values are rejected.

| Parameter | Default | Interpretation |
| --- | --- | --- |
| Reference width/height | 63 / 88 mm | Initial Pokemon format plausibility reference; not measured truth |
| Dimension tolerance | 10% | Separate width/height plausibility tolerance |
| Aspect tolerance | 8% | Relative to configured short/long ratio |
| Minimum image margin | 12 pixels | Minimum theoretical-quad clearance to any image border |
| Maximum angle error | 4 degrees | Parallelism/perpendicularity limits |
| Maximum fitted RMS | 2 pixels | Conditional straight-side inlier residual |
| Minimum coverage | 0.65 | Fraction of occupied straight-side support bins |
| Corner exclusion | 0.18 per end | Rounded-corner exclusion along each seed side |
| Side search fraction | 0.025 | Relative to candidate short dimension |
| Canny thresholds | 30 / 90 | Fixed working-image intensity thresholds |

The format and tolerance values are heuristics for this experiment and need hardware
validation. Width/height are averages of opposite fitted-side lengths. Angle is the
short-side direction modulo 180 degrees, not printed-card orientation. Corner order
starts at the upper of the short sides, follows clockwise image coordinates, then
continues around the quadrilateral. Side i connects corner i to corner (i+1) mod 4.
Line coefficients satisfy `a*x + b*y + c = 0` with unit normal to numeric precision.

Pixel geometry is stored separately from millimeter estimates. Millimeter coordinates
scale X and Y independently by 25.4/reported DPI before calculating side lengths.
The nominal size does not force the line fit. It is a plausibility check only.
Fractional-pixel coordinates are mathematical line intersections; they do **not**
establish subpixel measurement accuracy. Reported optical DPI is not a calibration
of scale, distortion, edge placement, scanner repeatability or card dimensions.

## Diagnostics and status

Each invocation creates a unique, exclusive directory under `local_data/s2_1/<id>`.
Each image has `scan-000`, `scan-001`, etc. Existing output IDs are never reused;
there is no output option that routes results into S1 capture directories. Original
images, original S1 manifests and acquisition metadata are not overwritten.

Per-image outputs:

- `report.json`: hash/source/acquisition evidence, algorithm/software versions,
  config, DPI provenance, each fitted side, residuals, geometry and validation flags.
- `baseline-overlay.png`: unchanged source appearance underneath diagnostic markings.
  Cyan lines are fitted sides, magenta circles/labels are theoretical intersections,
  green points are accepted support and red points are rejected/unselected edges.
  The overlay is a separate derived image, not an original replacement.
- `baseline-working.png`: derived grayscale used for edge detection.
- `baseline-support.json`: all accepted/rejected point coordinates; accepted groups
  follow side order and can be split using each side's `support_count`.
- Corresponding `preprocessed-*` artifacts when explicitly requested.

The overlay displays a representative subset if point counts are large; the point
JSON retains the full set. Inspect at 100% and larger: check whether cyan follows
the actual physical straight edge, whether green support sits on a shadow/printed
border instead, and whether corners are plausible extrapolations outside the round
corner arc. Red interior printed edges are not by themselves evidence of failure.
For undecodable inputs an overlay cannot be made; the failure report says so and
records the source hash when readable. An I/O failure can leave an incomplete output
directory; do not treat artifacts without the final report/index as a completed run.

Statuses are `success`, `review_required` or `failure` (CLI exit 0, 2 or 3).
Success means the configured software checks passed, not validated physical accuracy.
Review preserves provisional geometry with failed checks. Failure does not invent
four sides or substitute a box. A shadow/printed-edge alternative, insufficient
margin, bad aspect/DPI/dimensions, residuals or low support must not be ignored.

RMS and P95 residuals describe only the selected straight-side inliers. Tight
residuals can coexist with a systematically wrong parallel boundary. The confidence
score combines minimum coverage and residual and is explicitly **not** a calibrated
probability. Do not interpret it as a grading or accuracy score.

The [JSON Schema](report.schema.json) uses draft 2020-12 and describes single-image,
repeatability and top-level index reports. Support point sidecars contain
`accepted_pixels` / `rejected_edge_pixels` arrays of original-coordinate `[x,y]` pairs.
The schema is a report contract; no schema-validation dependency is added at runtime.

## Three-scan repeatability

Select at least three separately acquired scans of the same unmoved card with the
same S1 region, DPI, RGB24, gamma 2.2, contrast 0 and brightness 0. This command only
reads existing images; it never performs those acquisitions:

```powershell
$scan1 = 'local_data/<capture-set>/captures/<first-id>/original.bmp'
$scan2 = 'local_data/<capture-set>/captures/<second-id>/original.bmp'
$scan3 = 'local_data/<capture-set>/captures/<third-id>/original.bmp'
.\.venv-analysis\Scripts\python.exe analyze_boundaries.py repeat $scan1 $scan2 $scan3 --config experiments/boundary/config.example.json --compare-preprocessing
```

More than three paths are accepted. The same detector configuration is used for
every image. The top-level JSON links every per-image report and records:

- Raw corner X/Y coordinates, signed side positions at reference-side midpoints,
  width, height, angle and center, with mean, sample standard deviation (N-1) and
  maximum absolute deviation from the mean. Per-corner radial maximum deviation is
  also reported. DPI-derived width/height variation is separate and unavailable
  if physical conversion cannot be supported.
- Angle statistics unwrap the modulo-180 short-side orientation. Near the canonical
  +/-90-degree label boundary, an explicit 0/2 cyclic corner relabeling maintains
  correspondence using centered shapes. Raw coordinates are not aligned or moved.
  The applied cyclic shifts are recorded. Pose changes of 45 degrees or more require
  review because physical corner correspondence is no longer reliable.
- Shape-only corner and side-position statistics after a least-squares proper 2D
  rigid registration to scan 0 (Kabsch/SVD). The report includes every row-vector
  rotation matrix and translation. No reflection, scale, image resampling or
  original-image modification is performed. Width/height remain rigid invariants
  and their reported variability is not reduced by this registration.
- Image-dimension and reported-DPI consistency, known acquisition-control
  differences and unavailable metadata. Known differences in gamma/contrast/
  brightness/resolution/color settings require review; unknown controls remain
  explicitly unknown. Nominal same settings do not prove same internal processing.

Distinct hashes are required to guard against counting copies as independent
evidence; byte-identical inputs are refused for this experimental workflow. Different
hashes do not prove separate acquisitions or card identity. Maintain the operator's
capture log and unchanged placement. A failed image analysis blocks the summary;
review-required geometry can be summarized only with review-required overall status.
No successful geometry is silently selected in place of a failed input. Repeatability
uses baseline detections; preprocessing disagreement is retained as review status.

Global translation can come from image-origin movement **or** physical movement;
this detector cannot distinguish them. Raw statistics include both. Rigid registered
shape statistics remove those global components but can also absorb detector errors.
Registration cannot erase scale/shape variation and cannot prove metrological
accuracy. Three samples provide limited statistical evidence. Repeatability is
not an accuracy calibration.

## Observed existing-image result and hardware next steps

One existing operator-acquired gamma-2.2/contrast-0 BMP (capture
`20261017T173237_f7bd5f05b3cd4748b1ad764e9c390695`, 2005 x 2582 pixels) was analyzed
read-only. Both baseline and preprocessed results were **review_required** due to
competing parallel edge layers. The preprocessing comparison shifted one right-side
intersection about six pixels. Overlay inspection showed plausible outer geometry
but did not resolve physical-edge versus competing near-edge evidence. This is
why low residuals and nominal-size agreement are insufficient to certify the fit.
The original SHA-256 was verified unchanged. No new physical scan was executed.
Local diagnostics are under `local_data/s2_1`; they are ignored experimental artifacts,
not committed customer images. The first real-image diagnostic index was
`20261017T174629_f562a3f0e47b4f73bf37dfebc9ecebfa/report.json`.

Before trusting real detections:

1. Manually inspect the straight physical boundary on all four sides at full image
   resolution, distinguishing any soft shadow, glossy reflection and printed inset.
   Record operator-reviewed edge locations and uncertainties independently of the fit.
2. Have the operator acquire at least three new unchanged-placement scans using the
   same provisional profile. Run repeatability on those existing files and inspect
   every overlay before interpreting summary statistics. The implementation did
   not execute this hardware experiment or combine differently processed captures
   as purported identical-setting repeatability evidence.
3. Test upside-down/slightly rotated placement, different margins, gentle backing
   variation and another test card. Compare baseline/preprocessed sensitivity.
   If ambiguity persists, improve candidate/support modeling using independently
   labeled edges; do not simply loosen thresholds to force success.
4. Investigate scanner origin drift separately from card movement using appropriate
   physical references. Validate pixel scale/distortion with a traceable target in
   a separately planned calibration experiment, not the nominal 63 x 88 mm card.

Known limitations: global thresholding can fail on white/low-contrast cards, strongly
uneven backing, touching objects, strong shadows, textured printed borders, glare
or heavy rotation/cropping. Candidate selection is conservative and optimized for
one separated rectangular card on light backing. Secondary edges can cause frequent
reviews. It does not identify Pokemon artwork, determine printed upright orientation,
measure print centering or classify defects. Physical corners are rounded and never
directly observed as the theoretical intersections.

## Validation commands and results

```powershell
.\.venv-analysis\Scripts\python.exe -m pytest -q
.\.venv-analysis\Scripts\python.exe -m ruff check .
.\.venv-analysis\Scripts\python.exe -m ruff format --check .
.\.venv-analysis\Scripts\python.exe -m mypy spectra_scanner spectra_boundary
.\.venv-analysis\Scripts\python.exe -m compileall -q spectra_scanner spectra_boundary analyze_boundaries.py
.\.venv-analysis\Scripts\python.exe -m pip check
```

S2.1 tests use synthetic rounded rectangles with known geometry, rotations, shifts,
tone/margin variation, uneven backing, shadows, absent/ambiguous edges, cropped and
wrong-aspect cards, invalid DPI, corrupt files, immutable originals, explicit failure
and review behavior, rigid registration, metadata mismatch and unique output creation.
Synthetic tests establish software behavior, not real-world boundary accuracy.
The original S1 environment can still run its suite: optional OpenCV tests skip there.
Final validation on 2026-10-17 (Windows 11, CPython 3.13.2 x64):

| Check | Actual result |
| --- | --- |
| Full scanner-agent suite in analysis environment | **172 passed in 4.08s**, including 41 S2.1 cases |
| Original S1-only environment regression run | 131 passed, 1 optional analysis module skipped in 2.32s |
| Ruff lint | All checks passed |
| Ruff format check | 38 files already formatted |
| Mypy on both packages | No issues in 20 source files |
| Python compileall | Passed |
| Dependency compatibility | No broken requirements |
| Synthetic three-image CLI repeat | Success; controlled X shift sample SD approximately 2.0000 pixels; rigid-registered corner maximum sample SD below 0.01 pixel |
| Existing real BMP analysis | Review required; competing parallel edges and preprocessing sensitivity; source hash unchanged |
| Schema | JSON parsed; a full draft-2020-12 validator was not run |
| Repository whitespace | `git diff --check` passed; existing LF/CRLF notices |

The tiny registered spread in the synthetic fixture is a numerical software result,
not scanner precision. No physical scanning or real three-scan repeatability was
performed. Synthetic CLI report: `local_data/s2_1/20261017T175317_84311300bc9d48a9a38f8ac7d9550702/report.json`.
Tests include the +/-90-degree correspondence boundary and preprocessing failure
that must not be hidden by baseline success. Production backend/frontend suites
are outside this isolated experimental change.
