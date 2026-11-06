# S1 gamma and color reproduction experiment

Prepared without executing physical scans. Only the isolated scanner agent changes;
no production custody, grading, authorization, database or customer data is involved.
Existing original images and their metadata are not modified.

## Finding and hypothesis

The previous S1 adapter hardcoded `(ICAP_GAMMA, TWTY_FIX32, 1.0)` in
`spectra_scanner/twain_driver.py`, in `configure_test`'s optional capability list.
It set this value before acquisition; it did not merely label the file with gamma.
The revised adapter takes this value from the explicit `gamma` configuration key.
The backward-compatible default remains 1.0; the experiment does not silently
change the default acquisition policy to 2.2.

The saved actual acquisition metadata inspected for this investigation is:
`local_data/twain-600dpi-frame-test/captures/20261017T164001_fdcee73a9492444d8ac06182514fae3d/metadata.json`.
It records requested gamma 1.0, accepted SET, negotiation/final readbacks of 1.0,
and transfer-time gamma 1.0. It records RGB24, 2005 x 2582 pixels, approximately
600 DPI file metadata, and no embedded ICC profile. The discovery report
`local_data/reports/20261017T163212_077a696898b6417a9708570b57780f63.json`
reports current gamma 2.1999969482421875. Its gamma container does not separately
expose a default value; 2.2 is Epson's documented default, not an additional measured
GETDEFAULT result from this report.

[Epson's TWAIN capability reference](https://epson.cl/Support/wa00954e) describes
gamma as image-data tone correction, with a default of 2.2 and a 0.5-3.0 range.
Its brightness/contrast description gives this final gamma mapping, where `w`
is the value after brightness/contrast and clipping:

```text
output = 255 * (w / 255) ** (1 / gamma)
```

At neutral brightness/contrast, gamma 1.0 leaves this modeled stage unchanged;
gamma 2.2 raises intermediate values. For example, 128 maps to approximately 186,
while ideal black and white endpoints remain 0 and 255. A darker gamma-1.0 capture
is therefore consistent with this mechanism. Fully clipped white background alone
may show little difference, so compare midtones and shadows as well.

This is a documented Epson-family curve and a testable hypothesis, not a measured
transfer function of this Scan 2 version or proof that the manual PNG profile used
only that curve. TWAIN readback proves the reported setting, not the exact internal
implementation. The source may process on the host or in device firmware; this
investigation does not distinguish those locations.

Driver-side processing happens before pixels are delivered to the application.
The native DIB-to-BMP wrapper preserves delivered pixels; an unchanged BMP original
can already contain driver-processed data. Gamma 1.0 does not establish raw sensor
data, linear-light values, no color matrix, or calibrated response. A post-acquisition
gamma transform would create a separate derivative and cannot recover clipped or
quantized source information. This experiment performs no such transformation.

PNG is lossless compression, not a brightness adjustment. A BMP-to-PNG conversion
with unchanged pixels alone does not explain different code values. ICC profiles,
PNG gamma/sRGB metadata, the viewer's color management, manual-profile adjustments
and exposure can also change appearance. Compare numerical pixels and metadata;
use the same viewer/display for visual assessment. A simple power 2.2 curve is not
identical to the piecewise sRGB transfer function.

## Configurations and exact commands

The two configuration files differ only in `gamma`:

- `acquisition.gamma-1.0.json`: gamma 1.0.
- `acquisition.gamma-2.2.json`: gamma 2.2.

Both request 600 DPI, RGB24, neutral brightness/contrast, disabled standard automatic
processing, and the measured scan region in inches:

```json
{"x": 0.4404144287109375, "y": 7.1679229736328125,
 "width": 3.3416595458984375, "height": 4.3033294677734375,
 "units": "inches"}
```

This represents left/top/right/bottom `[0.4404144287109375, 7.1679229736328125,
3.782073974609375, 11.47125244140625]` and predicts about 2005 x 2582 pixels.
The saved driver-default domain contains it; live acquisition checks it again.
The original `local_data/acquisition.json` and frame-test configuration are unchanged.

Keep a non-customer test card stationary with the same backing, lid, scan region,
orientation and scanner conditions. Let the scanner stabilize consistently. Close
Epson Scan 2 and other scanner clients. Do not use driver UI during these captures.
Run the following manually from PowerShell when ready; these commands were **not run**:

```powershell
Set-Location C:\Users\plher\Documents\spetra\scanner_agent
.\.venv\Scripts\python.exe acquire.py --device 'EPSON Perfection V39II' --config experiments/gamma/acquisition.gamma-1.0.json --data-dir local_data/gamma-ab/a --timeout 300
.\.venv\Scripts\python.exe acquire.py --device 'EPSON Perfection V39II' --config experiments/gamma/acquisition.gamma-2.2.json --data-dir local_data/gamma-ab/b --timeout 300
```

Repeat B then A if desired (A/B/B/A order) to investigate drift and within-setting
variation; these same commands always create new capture IDs, never overwrite.
Do not infer pixel repeatability just from stationary placement or matching sizes.
Save all command report paths to identify the exact captures, including repeats.

No `--strict-options` is specified because this source reports unsupported standard
controls; strict mode is expected to stop without a scan. Unknown optional/vendor
controls remain unverified in standard mode and must be reviewed. Gamma itself is
now required to be available and matching, even in standard mode, before enabling
acquisition and again at transfer. Known mismatching settings still block.

TW_FIX32 cannot represent 2.2 exactly. The agent accepts a gamma difference no larger
than 1/65536, recording the exact returned value (e.g. 2.1999969482421875). It does
not round or overwrite that evidence. Resolution comparisons remain exact. This
tolerance does not admit a materially different curve such as 2.19.

## Verify each capture before comparing

CLI stdout returns a JSON report pointer. Successful native transfer creates a new
`original.bmp` and `metadata.json` under the selected data directory. PNG preference
does not trigger conversion of the native BMP. Retain original hashes and reports.

In the report inspect:

- `settings.ICAP_GAMMA.requested`, `readback.current`, `final_readback.current`, and
  `verified`; expected 1.0 or approximately 2.2 as appropriate.
- `transfer_time_settings.ICAP_GAMMA.current`; it must still match the request.
- Both resolution capabilities' final and transfer readbacks: 600; actual transfer
  image-info X/Y resolution 600, RGB pixel type 2 and 24 bits per pixel.
- `scan_region.verified`, its requested/readback coordinates and
  `transfer_time_region_inches`; both runs must use the same measured rectangle.
- Every other setting/readback, device identity/version and unverified options.
  Stop causal interpretation if another effective setting changed.

Manifests retain `acquisition.user_configured.gamma`,
`provenance.capture_settings.ICAP_GAMMA`, and
`acquisition.device_reported.settings.ICAP_GAMMA` (also in
`provenance.transfer_time_settings`). Valid QC-failing originals remain preserved;
read diagnostics before using them. Physical margin and calibration remain pending.

## Read-only, reproducible comparison

The comparison script uses existing Pillow, no extra dependencies. It decodes
stored RGB24 without ICC conversion, gamma adjustment, resampling, registration,
auto-orientation or image writes. It checks SHA-256 before/after reading and checks
an adjacent original manifest when available. Output is a new JSON file under S1
`local_data`; an existing output is rejected. Originals and manifests are read only.

Use the exact successful capture IDs from the two reports:

```powershell
$a = 'local_data/gamma-ab/a/captures/<capture-id-a>/original.bmp'
$b = 'local_data/gamma-ab/b/captures/<capture-id-b>/original.bmp'
if (Test-Path -LiteralPath local_data/gamma-ab/rois.json) { throw 'ROI file exists; edit it instead of replacing it.' }
Copy-Item -LiteralPath experiments/gamma/rois.template.json -Destination local_data/gamma-ab/rois.json
notepad local_data/gamma-ab/rois.json
```

Replace every null rectangle with `[left, top, right, bottom]` integer pixel
coordinates (origin top-left, right/bottom exclusive). Select corresponding content
in A and B manually. `white_background` must contain only actual white backing,
not the card, shadow or glare. `card` should encompass the same card content.
`card_midtone_patch` should be a matching interior patch away from an edge, foil
glare or clipping. Additional named patch pairs are supported. There are no invented
default ROIs and no boundary detection. Example schema only, with symbolic entries:

```text
"white_background": {"a": [left_a, top_a, right_a, bottom_a],
                     "b": [left_b, top_b, right_b, bottom_b]}
```

The script rejects null, invalid or out-of-image ROIs. Matched rectangle size alone
does not prove pixel registration. It compares distributions, not unregistered pixel
differences. Save the ROI JSON with the report for repeatability, then run:

```powershell
$comparison = 'local_data/gamma-ab/comparison-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fffffff') + '.json'
.\.venv\Scripts\python.exe compare_acquisitions.py --a $a --b $b --rois local_data/gamma-ab/rois.json --output $comparison
```

The JSON includes whole-image and per-region 256-bin histograms for R/G/B, pixel
counts, means, standard deviations, extrema, percentiles 1/5/25/50/75/95/99,
fractions at code 0/255, and B-minus-A mean RGB deltas. It records input hashes,
dimensions, DPI, ICC hash, embedded gamma/sRGB information and acquisition evidence
when available. Whole-image and card histograms must be interpreted with region
composition in mind; do not confuse cropping differences with tone response.

Compare the manual PNG as a third input in a separate comparison report, with
its own corresponding ROIs. Missing acquisition metadata stays unknown, not inferred
from the filename or an embedded PNG gamma value. A manual PNG is a reference
workflow, not a calibrated truth image.

Expected hypothesis: gamma-2.2 midtone distributions shift higher while ideal clipped
endpoints can remain unchanged. Noise, reflections and different source processing
can prevent exact power-law correspondence. Matching perceived brightness, histograms
or white-background values does **not** prove correct colors, calibrated white,
ICC accuracy, or grading suitability. That would require controlled illumination,
traceable color targets/reference values and a separately validated color pipeline.

## Validation and stopping point

Final validation on 2026-10-17:

| Check | Result |
| --- | --- |
| Full isolated scanner-agent suite | 110 passed in 2.31s |
| Ruff lint | All checks passed |
| Ruff formatting | 26 files already formatted |
| Mypy | No issues in 13 source files |
| Python compilation, including comparison wrapper | Passed |
| Dependency compatibility | No broken requirements |
| Synthetic comparison CLI | Correct histograms/RGB deltas; existing output rejected unchanged |

Tests include valid/invalid gamma configuration, TW_FIX32 representation, genuine
gamma mismatches, missing required gamma, transfer-time gamma changes/unavailability,
requested versus reported gamma in manifests, unchanged synthetic originals,
histograms/percentiles/clipping, manual ROI validation, manifest hash mismatch,
and exclusive comparison output. Existing S1 acquisition/import checks remain covered.
No new dependencies were introduced. Synthetic smoke reports are ignored artifacts
under `local_data/gamma-comparison-smoke-*` and are not physical-device evidence.

Tests use synthetic
images/drivers; no physical scan or comparison of the actual manual PNGs was run.
The darkness mechanism is plausible and documented; causal confirmation is pending
the controlled real-device experiment. S2.1 boundaries/centering and grading are
not implemented.
