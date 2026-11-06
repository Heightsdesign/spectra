# S1 driver-side contrast experiment

Prepared without physical scanning, transformations or changes to existing captures.
No production grading, custody, authorization, audit or database logic is changed.
The operator reports gamma 2.2 improved brightness, with stronger apparent contrast
in dark borders and orange areas than manual Epson PNG exports. These observations
motivate this experiment; no quantitative result for the three settings is claimed.

## Implementation and controls

Previously `configure_test` in `spectra_scanner/twain_driver.py` hardcoded
`ICAP_CONTRAST` to 0.0 (TW_FIX32). SET was followed by GETCURRENT, final readback
after layout negotiation, and a transfer-time readback. Known mismatches blocked,
but missing contrast readbacks were allowed outside strict mode. Contrast was not
configurable through JSON.

It now uses `contrast` in configuration, default 0.0, finite range -1000 to 1000.
These are normalized TWAIN units, not percentage changes in image contrast.
Configuration rejects booleans, strings, out-of-range and nonfinite values.
Contrast and brightness must be available and matching both after negotiation and
at transfer, even without `--strict-options`. Brightness remains hardcoded to 0.0;
the experiment does not introduce brightness tuning. Gamma remains configurable
as before and is fixed at 2.2 in all three configurations. The adapter sets and
reads back both resolutions, RGB24 and the measured region as before.

Gamma/contrast comparisons allow at most 1/65536 of a TW_FIX32 unit. All three contrast
targets are exactly representable. A returned -49.999 for requested -50 fails; a
returned -49.9 or 0 certainly fails. The exact readback is retained, not rounded in
metadata. Brightness 0 is checked exactly. A missing required transfer-time value
cancels delivery; negotiation failure prevents acquisition from being enabled.

[Epson's TWAIN reference](https://epson.cl/Support/wa00954e) documents contrast from
-1000 to +1000 and describes contrast adjustment before gamma. Negative contrast
should compress the modeled pre-gamma tonal range, potentially lifting dark values
and lowering highlights. That also means perceived brightness can change at fixed
gamma. This is an Epson-family model, not a measured transfer function of this
Scan 2 version. Do not interpret -50/-100 as a guaranteed percentage reduction.
No local contrast correction is applied to the saved image.

The files `acquisition.contrast-0.json`, `acquisition.contrast-minus50.json` and
`acquisition.contrast-minus100.json` differ **only** in contrast. They preserve:

- Gamma 2.2, brightness 0, 600 DPI, RGB24 and native uncompressed lossless BMP delivery.
- The measured inch region x=0.4404144287109375, y=7.1679229736328125,
  width=3.3416595458984375, height=4.3033294677734375 (about 2005 x 2582 pixels).
- The same standard enhancement/deskew/crop/rotation requests and quality tolerances.

The existing default configuration and gamma experiment configurations are not
overwritten. Application-level exclusive original creation, hash checks, capture
IDs and manifest-last commits remain intact. Requested contrast is recorded in
`acquisition.user_configured.contrast` / `provenance.requested_profile.contrast`.
Negotiation evidence is in `provenance.capture_settings.ICAP_CONTRAST`, including
initial/final readbacks and verification. Transfer-time evidence is in
`acquisition.device_reported.settings.ICAP_CONTRAST` and
`provenance.transfer_time_settings.ICAP_CONTRAST`. All other existing metadata is retained.

## Exact PowerShell acquisitions - execute manually when ready

Close Epson Scan 2 and other scanner clients. Keep the same non-customer card,
backing, lid, placement, orientation and scanner conditions. Use the same viewer at
matched magnification for visual review. These commands have not been executed:

```powershell
Set-Location C:\Users\plher\Documents\spetra\scanner_agent
.\.venv\Scripts\python.exe acquire.py --device 'EPSON Perfection V39II' --config experiments/contrast/acquisition.contrast-0.json --data-dir local_data/contrast-ab/c0 --timeout 300
.\.venv\Scripts\python.exe acquire.py --device 'EPSON Perfection V39II' --config experiments/contrast/acquisition.contrast-minus50.json --data-dir local_data/contrast-ab/cminus50 --timeout 300
.\.venv\Scripts\python.exe acquire.py --device 'EPSON Perfection V39II' --config experiments/contrast/acquisition.contrast-minus100.json --data-dir local_data/contrast-ab/cminus100 --timeout 300
```

Each successful run prints a JSON report pointer and creates a new capture directory
with `original.bmp` and `metadata.json`. Repeats create new IDs without overwriting.
Consider reversing order on a repeat (0/-50/-100/-100/-50/0) to observe drift.
Do not move the card between captures. Pixel alignment is still unverified.

No `--strict-options` is supplied because this source reports unsupported optional
controls and strict mode is expected to stop. Gamma, contrast and brightness are
mandatory regardless. Unknown optional/vendor processing remains unverified; inspect
the whole report. Do not silently change another setting to make a run succeed.

Before comparing, verify each report:

- `settings.ICAP_CONTRAST.requested`, `readback.current`, `final_readback.current`,
  `verified`, and `transfer_time_settings.ICAP_CONTRAST.current`: 0, -50 or -100.
- Gamma requested 2.2, reported approximately 2.1999969482421875 (or 2.2); brightness 0.
- X/Y resolution final and transfer readbacks 600; image-info RGB24 at 600 DPI.
- `scan_region.verified`, requested/readback coordinates and transfer-time region
  match the same rectangle in every capture.
- Same device/version, remaining settings, unverified controls, image dimensions,
  file integrity and acceptable acquisition QC. Expected physical margins remain
  pending; no boundary detection or calibration is performed.

Valid QC-failing evidence is still retained, but must be reviewed before comparison.
Failures report `unsupported_option`, `fallback_required` or `profile_mismatch`
as appropriate. No successful hardware result is inferred from automated tests.

## Exact PowerShell comparisons

Use exact original paths from the successful reports; substitute the capture IDs:

```powershell
$c0 = 'local_data/contrast-ab/c0/captures/<capture-id-0>/original.bmp'
$c50 = 'local_data/contrast-ab/cminus50/captures/<capture-id-minus50>/original.bmp'
$c100 = 'local_data/contrast-ab/cminus100/captures/<capture-id-minus100>/original.bmp'

foreach ($name in @('0-vs-minus50', '0-vs-minus100', 'minus50-vs-minus100')) {
    $roiPath = "local_data/contrast-ab/rois-$name.json"
    if (Test-Path -LiteralPath $roiPath) { throw "ROI file exists: $roiPath; edit instead of replacing it." }
    Copy-Item -LiteralPath experiments/contrast/rois.template.json -Destination $roiPath
}
notepad local_data/contrast-ab/rois-0-vs-minus50.json
notepad local_data/contrast-ab/rois-0-vs-minus100.json
notepad local_data/contrast-ab/rois-minus50-vs-minus100.json
```

Replace each null with `[left, top, right, bottom]` integer pixel coordinates,
origin top-left, right/bottom exclusive. Every pair contains separate `a` and `b`
rectangles. Select the same physical content manually for each comparison. Keep
region composition/area consistent and review alignment; there are no automatic
card boundaries or invented default ROIs. Template regions:

- `white_background`: actual backing outside card/shadow/glare.
- `card`: the same complete card content.
- `dark_border`: a matching dark border patch; avoid an edge transition when possible.
- `orange_patch`: the same printed orange area, avoiding text/glare.
- `midtone_patch`: a flat matching interior midtone region.
- `highlight_patch`: corresponding bright printed content, distinct from backing.

The script rejects null or out-of-image rectangles. It does not register, resample,
crop an output image, enhance or rewrite originals. After filling ROIs, run:

```powershell
$tag = Get-Date -Format 'yyyyMMdd-HHmmss-fffffff'
.\.venv\Scripts\python.exe compare_acquisitions.py --a $c0 --b $c50 --rois local_data/contrast-ab/rois-0-vs-minus50.json --output "local_data/contrast-ab/comparison-0-vs-minus50-$tag.json"
.\.venv\Scripts\python.exe compare_acquisitions.py --a $c0 --b $c100 --rois local_data/contrast-ab/rois-0-vs-minus100.json --output "local_data/contrast-ab/comparison-0-vs-minus100-$tag.json"
.\.venv\Scripts\python.exe compare_acquisitions.py --a $c50 --b $c100 --rois local_data/contrast-ab/rois-minus50-vs-minus100.json --output "local_data/contrast-ab/comparison-minus50-vs-minus100-$tag.json"
```

Reports are exclusive new JSON files. SHA-256 is checked before/after analysis and
against adjacent original manifests when available. Existing reports are refused.
All acquisition metadata and ROI definitions are included for reproducibility.
To compare against the manual PNG workflow, use that PNG as `--a` in separate runs
with each TWAIN BMP as `--b`, and select new corresponding ROIs. Unknown manual PNG
acquisition settings remain unknown; it is not a colorimetric ground truth.

## Metrics and interpretation

The existing tool retains RGB histograms (256 bins), means, standard deviations,
percentiles 1/5/25/50/75/95/99, extrema, clipping fractions at 0/255 and mean RGB
deltas. It now additionally reports for every channel/region:

- `percentile_spread_p95_p5` and `interquartile_range` (P75-P25), describing robust
  encoded tonal spread; `distribution_deltas_b_minus_a` includes their changes.
- Fixed code-value fractions: shadows 0-63, midtones 64-191, highlights 192-255,
  including fraction changes. These are reproducible bins, not calibrated optical
  zones or measurements of linear-light luminance.
- Percentile shifts, standard-deviation changes and clipping changes, allowing
  median movement to be considered alongside spread contraction.
- `channel_balance`: mean R-G and G-B per input, alongside separate R/G/B deltas,
  to flag channel-dependent changes in orange and other printed patches. These
  code differences are not chromaticity, perceptual color difference or delta-E.

Compare the dark and orange patch distributions plus highlights and backing. A
smaller spread and reduced clipping may support lower encoded contrast, but a flat
patch's spread can mainly reflect texture/noise. Gamma changes, sharpening halos,
color matrices, misregistration and changed ROI composition can also affect these
statistics. Histograms discard spatial information; they do not measure optical
resolution, sharpness, MTF or prove sharpening absent. Inspect matched flat patches
and borders separately, review metadata, and avoid attributing every change to
contrast. No edge detector, registration or sharpening metric is added in S1.

Do not select a setting solely to match manual PNG brightness or white level.
Brightness matching does not prove gamma equality, color accuracy or calibrated
reproduction. Colorimetric validation needs a separately validated reference pipeline.
No best contrast value is selected before the hardware experiment is performed.

## Validation

Final validation on 2026-10-17:

| Check | Result |
| --- | --- |
| Full isolated scanner-agent suite | 131 passed in 2.26s |
| Ruff lint | All checks passed |
| Ruff format check | 28 files already formatted |
| Mypy | No issues in 13 source files |
| Python compileall | Passed |
| Dependency compatibility | No broken requirements |
| Synthetic comparison CLI | Spread/clipping changes verified; existing report rejected |
| Repository whitespace | `git diff --check` passed; existing LF/CRLF notices |

The 21 added test cases cover invalid contrast values, configurations differing only
in contrast, requested/readback values for 0/-50/-100, required contrast/brightness,
materially clamped contrast, transfer-time changes or missing values, requested and
actual contrast metadata, tonal-band boundaries, spreads, clipping and distribution
deltas. New software version is 0.2.2; no new dependency was added. Synthetic CLI
artifacts remain ignored under `local_data/contrast-comparison-smoke-*`.

Tests use synthetic
images and driver doubles only. No physical scans were executed, no actual originals
were rewritten, and no production backend/frontend code was changed. Stop here;
card boundary detection, centering and grading remain out of scope.
