# SPECTRA S1 - Epson V39 II acquisition pipeline

The separate native SELBY workstation now includes
[V0.4 human-supervised draft grading](SELBY_WORKSTATION_V04.md), with
[validation results](SELBY_WORKSTATION_V04_VALIDATION.md) and a
[synthetic grading example](SELBY_WORKSTATION_V04_EXAMPLE.md). Its grading decisions
do not change S1 acquisition or authorize production release.

Start with [Windows quick start](WINDOWS_QUICKSTART.md). Agent version: **0.2.2**.
This is an isolated local Python CLI with no API, production integration, database,
customer identity, custody, audit or grading changes. Output is confined to
`scanner_agent/local_data`; use only non-customer test images.
The isolated [S2.1 physical-boundary experiment](experiments/boundary/README.md) now
analyzes existing captures using a separate optional OpenCV/NumPy environment.
S1 acquisition behavior and original-preservation rules remain unchanged.

## Evidence and current readiness

The [contrast tuning experiment](experiments/contrast/README.md) prepares contrast
0/-50/-100 at fixed gamma 2.2. Contrast is configurable (default 0, normalized TWAIN
range -1000 to 1000); contrast and brightness readbacks are now mandatory. Comparison
reports include percentile spreads, tonal bands, clipping and RGB balance diagnostics.

For the later successful operator-run direct acquisition and the gamma-1.0 versus
gamma-2.2 experiment, see [gamma investigation](experiments/gamma/README.md).
The explicit `gamma` configuration now controls the driver tone curve (default 1.0,
range 0.5-3.0); disabling automatic enhancements does not disable this curve.
The experiment comparison script reads originals without changing their pixels.
Historical S1 revision validation below describes the earlier implementation.

The operator reports a working Epson Scan 2 profile `SPECTRA_CARD_600DPI`: 600 DPI,
RGB, lossless PNG, deskew disabled, custom selection, all four card edges/rounded
corners visible with white surround. Three scans were produced without intentional
card movement. This establishes a viable **manual** workflow, not pixel repeatability,
calibration, verified profile reload persistence, or programmatic TWAIN control.
The agent has not inspected those three images. Machine-readable operator evidence:
[operator-manual-workflow.json](diagnostics/operator-manual-workflow.json).

Earlier actual read-only tests on this Windows 11 workstation loaded the x64 DSM,
enumerated `EPSON Perfection V39II`, and found Epson source version `6.7.92.42160`.
Opening that source returned `CheckDeviceOnlineError`. The underlying cause was not
established. That historical observation is preserved in
[observed-workstation.json](diagnostics/observed-workstation.json); it does not
contradict the later operator-reported manual success. No new physical scan or
live region negotiation was executed during this revision.

| Capability | Evidence |
| --- | --- |
| Manual Epson Scan 2 / 600 DPI / RGB / PNG | Operator-reported successful acquisitions |
| Source discovery / x64 DSM loading | Earlier actual read-only workstation execution |
| Live capabilities, region setting, triggering, transfer | Implemented, tested with doubles; real hardware unverified |
| Stable-file folder import, exact-byte storage, hashes, deduplication | Automated tests and synthetic CLI smoke test |
| Physical margins, card presence, repeatability, optical DPI, calibration | Not certified; boundary-dependent margin check pending S2.1 |

## Configuration

Copy [acquisition.example.json](acquisition.example.json) to
`local_data/acquisition.json`. All commands accept `--config`; omitting it uses the
same defaults: 600 DPI, RGB24, preferred PNG, enhancement/deskew/automatic cropping/
automatic rotation off, profile `SPECTRA_CARD_600DPI`.
These are **user-configured requests**, never automatic proof of driver settings.
The JSON loader rejects unknown keys, nonfinite values and unsupported processing.

`scan_region` defaults to `null`: the operator has not supplied measured coordinates.
The agent never substitutes card dimensions or assumes glass origin equals usable
scan origin. To configure it, use the actual acquisition surface and driver coordinate
system. Schema (replace the symbolic values with measured numbers):

```text
"scan_region": {"x": measured_x, "y": measured_y,
                "width": measured_width, "height": measured_height, "units": "mm"}
```

Units may be `mm` or `inches`. Origins can be signed if the driver exposes them.
The rectangle includes the white surround, not just the expected card dimensions.
Do not copy illustrative dimensions from another card or scanner. A manually saved
Epson region is not automatically extracted from the profile by this prototype.

`expected_dimensions` optionally specifies `[pixel_width, pixel_height]` from an
independently reviewed acquisition setup. Otherwise expected dimensions derive
from the configured region and requested DPI. With neither, the dimension check
is pending. Default dimension tolerance is 2 pixels; embedded DPI tolerance is 1 DPI
for PNG/BMP metadata rounding. Both are configurable. These tolerances do not prove
calibration. `safety_margin_mm` defaults to an operator-adjustable 2 mm target,
not a validated hardware minimum. The physical-margin check always remains
`pending_s2_1` because S1 does not locate card edges.

## Mode A - supervised direct TWAIN experiment

The isolated environment pins `pytwain 2.3.0` (import `twain`, Windows ctypes binding)
and Pillow 12.3.0. Compatibility with the installed Python/DSM was verified earlier;
real Epson source opening and acquisition remain separate hardware tests. The
installed binding exposes `SourceManager.source_list` as a property and supports
image-layout GET/GETDEFAULT/SET. See [pytwain API](https://pytwain.readthedocs.io/en/latest/twain.html).
Python, DSM and source bitness must match. No WIA capability is assumed or probed.

Discovery queries supported/current resolution, RGB/pixel formats, depth,
compression/transfer modes, frame capability, physical dimensions, enhancements,
and current/default layout with units. A symbolic pixel-format legend is not a list
of supported formats. Unsupported options are recorded individually. Discovery
never triggers acquisition, and does not change the saved Epson profile.

Acquisition requests inch units (converting configured mm), RGB24, 600 DPI,
uncompressed native transfer and neutral standard processing/geometry options.
Legacy per-channel depth 8 is allowed only with actual RGB24 image-info/file checks.
Every configured capability is read back after all negotiation. Known conflicting
processing settings block acquisition; unavailable standard options are marked
unverified. `--strict-options` also blocks unknown options. Vendor-specific Epson
processing remains unverified even when all standard controls read back correctly.

The driver's default frame, in verified inch units, is used as a **conservative
usable domain**, not asserted to be the full glass. The requested rectangle must fit
inside this frame, including its reported origin. The agent SETs the rectangle and
checks all four coordinates with only TW_FIX32 quantization tolerance (2/65536 inch).
Missing/invalid default bounds, absent configuration, out-of-domain or adjusted
coordinates produce `fallback_required`; no scan is triggered. An exposed default
selection can be smaller than the true bed: use folder mode rather than inventing
larger bounds. Region changes that reset DPI are detected. The transfer callback
rechecks settings and region so UI changes cannot silently replace negotiated values.

This direct prototype preserves the driver's native DIB transfer as its lossless
BMP original. It does **not** claim that Epson supports direct PNG file transfer.
Preferred PNG is provided by the validated manual workflow. No BMP-to-PNG conversion
or other derived transformation is performed; no original is recompressed.

Native calls run in a disposable worker with a hidden Win32 owner window, not Tk.
An OS lock prevents concurrent agents. A timed supervisor and Windows Job Object
contain this worker and new helper processes; existing Epson applications are not
terminated. Driver crash/timeout reports retain completed discovery checkpoints and
a driver log. Busy, absent, canceled and unsupported states produce structured
errors. After a timeout inspect retained originals/reports before retrying.

## Mode B - Epson Scan 2 export-folder import

Use the manually saved `SPECTRA_CARD_600DPI` profile and a dedicated local test inbox.
Reload it, check controls and region, then save PNG using new filenames. Import is
explicitly separate from scanning: it cannot inspect the Epson UI, confirm scanner
identity, extract the active profile, or know the true scan time.

The watcher polls only top-level image files, ignoring temporary names, directories,
links and reparse points. It waits for unchanged identity/size/mtime across a quiet
period (default 3 seconds). On Windows it opens a read handle denying concurrent
writers/delete/rename, copies a private snapshot, rechecks file identity/stamp/length,
and fully decodes it before committing. Busy/changing files are retried. Incomplete
or corrupt exports produce diagnostics; a subsequent file change can be reconsidered.
PNG, uncompressed BMP and supported lossless TIFF are accepted; JPEG/lossy TIFF are
rejected. The configured preferred format does not force a source conversion.

Originals are copied byte-for-byte into unique capture directories with exclusive
creation, then SHA-256 is verified. The completion manifest is committed last.
Duplicate hashes reuse an integrity-checked existing capture, including across
watcher restarts. A changed source becomes a new capture; originals and source
exports are never overwritten or deleted. Deduplication returns the prior capture's
QC/configuration evidence rather than rewriting history for a new configuration.
An interrupted copy/manifest may leave an uncommitted directory: inspect it manually;
it is never treated as a successful capture. Filesystem immutability is application
level, not WORM storage; hashes detect external modification on deduplication.

## Metadata and acquisition quality

Each schema-2 `captures/<id>/metadata.json` records capture/acquisition identifier,
original name, SHA-256, size, storage/observation UTC time, mode, source filename,
requested settings and software/agent versions. Metadata separates:

- `acquisition.user_configured`: intended model, manual profile, settings and region.
- `acquisition.device_reported`: actual driver identity/settings/image-info/region
  when available; null for manual folder imports.
- `acquisition.independently_observed_file`: decoded dimensions, encoded bit depth,
  DPI metadata, orientation/ICC presence and uniform-content observation. Embedded
  DPI is a file assertion, not independent optical verification.
- `provenance`: original source facts, driver information and transfer time where
  available. Manual scan time is null; import/observation/mtime are explicitly
  different facts and never relabeled as the scan timestamp.

Every valid original receives checks for full decode, nonzero data/dimensions,
single-frame RGB24, expected dimensions, DPI consistency when present, orientation
tag and completely uniform content. A blank uniform image fails; variation alone
does not prove card presence, adequate exposure or a usable scan. No boundaries,
centering, scoring or measurements are computed. Missing DPI/dimensions are pending;
physical margin always remains pending. Overall QC is `fail` on any failure and
otherwise `pending`, never a false acquisition-readiness approval.

Valid but QC-failing images are still preserved as original evidence. The watcher
reports `imported_with_qc_failures` and exits 2 after a bounded run. Direct profile
or QC mismatch reports `profile_mismatch`. Corrupt/unsupported input is rejected.
No original is rotated, cropped, resampled, enhanced or recompressed. TIFF orientation
is recorded from encoded tags, not silently applied to stored bytes. `pixel_transformations`
and `derived_images` are empty: this revision generates no derivatives. Future
explicit derivative tooling must create separate files/manifests linked to the
original SHA-256 and record transformations; it must not edit original metadata.

Reports are exclusive JSON files in `local_data/reports`; worker logs/checkpoints
are retained under `local_data/.work`. CLI stdout contains JSON report pointers.
Success exits 0, controlled error/QC failure 2, worker crash/timeout 3, cancel 130,
and report-write failure 1. The watcher emits per-file report pointers and a final
summary. Ctrl+C stops a continuous watch gracefully; review per-file QC reports.

## Hardware checklist and Epson limitations

Run these on the actual USB-connected Windows workstation with non-customer targets:

1. Reload the saved profile after selecting another profile, and again after closing/
   reopening Epson Scan 2. Compare the displayed X/Y/width/height or preview selection,
   DPI/RGB/PNG and all disabled controls with a recorded reference. If the application
   does not expose numeric coordinates, record that limitation and compare the
   preview visually; do not call it exact coordinate persistence.
2. Acquire a new scan after each reload. Manually inspect every physical edge,
   rounded corner and the white surround. Retain files and metadata; identical pixel
   dimensions alone do not prove identical region origin or pixel repeatability.
3. Run discovery and inspect live resolution/depth/frame/unit reports. Close Epson
   Scan 2 first to avoid contention. Do not infer hardware support from binding names.
4. Configure a measured driver-coordinate rectangle and run direct acquisition.
   Confirm bounds/readback, actual transfer region, RGB24/600 evidence and dimensions.
   If layout cannot be verified, retain `fallback_required` and use manual PNG imports.
5. Test device absent, busy, UI cancellation and unsupported coordinates without
   losing or overwriting originals. Changing the region or processing in Epson UI
   during direct acquisition should be detected and blocked when exposed.
6. Import a real Epson PNG; check hash equals source, restart watcher to confirm
   duplicate handling, then acquire a distinct new file and verify prior hashes.

Driver default layout may reflect a selection rather than the entire usable bed;
physical width/height alone do not establish a usable origin. Vendor settings,
profile region persistence, PNG transfer support and calibrated optical behavior
cannot be established by synthetic tests. Source availability errors do not establish
USB fault cause. Keep folder acquisition as the operational S1 fallback.

The revision is ready to collect local evidence for a later S2.1 investigation,
conditional on manual image review and the hardware checklist. Pixel repeatability,
physical margins and calibrated measurements remain unverified. Stop here: no
S2.1 boundary detection is implemented.

## Automated validation

From `scanner_agent`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m compileall -q spectra_scanner discover.py acquire.py watch_exports.py
.\.venv\Scripts\python.exe -m pip check
```

Final revision validation on 2026-10-17 (Windows 11, CPython 3.13.2 x64):

| Check | Result |
| --- | --- |
| Full scanner-agent suite | **89 passed in 1.97s**; no physical scans |
| Ruff lint | All checks passed |
| Ruff format check | 22 files already formatted |
| Mypy | No issues in 12 source files |
| Python compileall | Passed, exit 0 |
| Dependency compatibility | `pip check`: no broken requirements |
| Synthetic folder CLI, dedicated inbox | First process `stored` / `imported`, exit 0 |
| Restarted synthetic folder CLI | `duplicate` / `imported`, exit 0 |
| Existing mixed test inbox smoke | Correctly reported `imported_with_qc_failures` for legacy test evidence; retained originals |
| Repository whitespace | `git diff --check` passed; existing LF/CRLF notices |

The 30 additional tests cover configuration, mm conversion, nonzero driver origin,
absent/adjusted/out-of-domain coordinates, layout changes resetting resolution,
transfer-time region changes, metadata evidence separation, RGB/DPI/dimension checks,
uniform blank rejection, pending margin status, exact originals, deduplication and
machine-readable configuration/QC failure paths. The prior 59 tests remain covered.
CLI smoke files are clearly named synthetic artifacts in ignored local test storage.
Raw run pointers: `local_data/revision-isolated/reports` and
`local_data/revision-smoke/reports`; these are workstation artifacts, not committed
hardware evidence. The historical read-only hardware snapshot is unchanged.

Backend/frontend suites are outside this isolated change; their source and rules
were not changed by this revision. No physical scanning is claimed by these tests.
