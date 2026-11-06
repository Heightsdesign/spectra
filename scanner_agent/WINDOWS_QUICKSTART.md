# S1 Windows PowerShell quick start

Use the USB-connected Windows workstation and non-customer test images only.
The operator reports three successful manual scans with `SPECTRA_CARD_600DPI`.
Programmatic acquisition, saved-region persistence and pixel repeatability remain
unverified. Full behavior and limitations: [README](README.md).

## Setup

From the repository root:

```powershell
Set-Location .\scanner_agent
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
New-Item -ItemType Directory -Force local_data, export_inbox
Copy-Item acquisition.example.json local_data/acquisition.json
```

Reuse the existing `.venv` if already installed. Epson Scan 2 must be installed;
Python/DSM/TWAIN-source bitness must match (this workstation previously enumerated
with x64 Python). No backend environment or database is needed.

## Recommended manual profile + folder import

In Epson Scan 2 load **SPECTRA_CARD_600DPI** and verify 600 DPI, RGB24, PNG,
enhancement/deskew/auto-crop/auto-rotation off. Select a region around the card
including all edges, rounded corners and white surround. Keep the card stationary.
Export into `scanner_agent/export_inbox` with distinct filenames.

```powershell
.\.venv\Scripts\python.exe watch_exports.py --config local_data/acquisition.json --inbox export_inbox
```

Ctrl+C stops the watcher. For one bounded import pass:

```powershell
.\.venv\Scripts\python.exe watch_exports.py --config local_data/acquisition.json --inbox export_inbox --once
Get-ChildItem local_data/reports
Get-ChildItem local_data/captures
```

The watcher waits for stable, closed files and preserves exact bytes. Duplicate
hashes are skipped across restarts. Read each JSON quality report: preserved does
not mean QC passed. Missing region/DPI checks remain pending; physical margin is
always pending S2.1. Do not point this test importer at production customer storage.

## Verify profile reload persistence manually

Record the current region coordinates/units and preview selection plus controls.
Switch to another profile, reload `SPECTRA_CARD_600DPI`, compare them, then close/
reopen Epson Scan 2 and repeat. Acquire a scan after each reload. Review all four
edges/corners and white surround. If numeric coordinates are unavailable, report
visual-only persistence; matching image dimensions do not prove matching origin.
Do not claim pixel repeatability from these observations.

## TWAIN discovery and optional direct experiment

Close Epson Scan 2 and other scanner clients first:

```powershell
.\.venv\Scripts\python.exe discover.py --list-only --config local_data/acquisition.json
.\.venv\Scripts\python.exe discover.py --device 'EPSON Perfection V39II' --config local_data/acquisition.json --timeout 60
```

Reports show supported/current values, units and current/default frames if exposed.
Default configuration has no invented region. Set `scan_region` in the JSON to
measured `{x,y,width,height,units}` using mm or inches, with the driver's actual usable
origin. Optionally set reviewed `expected_dimensions: [width_pixels,height_pixels]`.
Do not use physical card dimensions as the acquisition rectangle.

```powershell
.\.venv\Scripts\python.exe acquire.py --device 'EPSON Perfection V39II' --config local_data/acquisition.json --strict-options --timeout 300
```

Absent/out-of-domain/adjusted region causes `fallback_required`; use manual folder
mode. Strict mode also refuses unknown standard options. No scan is claimed unless
a real transfer occurs. Direct native transfer preserves a BMP original; preferred
PNG comes from Epson manual exports. No conversion or image transformations occur.

## Troubleshooting

- `device_absent`: check USB/power and Epson Scan 2 manually; this status does not
  establish a specific hardware fault. Earlier source opening returned this status.
- `busy`: close other scanner clients; another agent may hold the local lock.
- `twain_unavailable` / `architecture_mismatch`: check installed Epson TWAIN source,y
  Python bitness and matching DSM. Use only a trusted absolute `--dsm` DLL path.
- `fallback_required`: inspect driver default frame/units and configured region;
  never substitute a zero-origin bed. Use manual imports when coordinates are not reliable.
- `unsupported_option`: inspect requested/readback values. Do not claim disabled
  vendor processing from unavailable readbacks.
- `imported_with_qc_failures` / `profile_mismatch`: inspect original and JSON checks.
  QC-failing valid images are retained unchanged. Correct acquisition and produce
  a new source file; never replace an existing original.
- `timeout` / `driver_crash`: inspect `local_data/.work` checkpoints/driver log and
  reports, check retained originals, then retry. Reconnect only after worker exits.
- No import: check quiet interval, writer closed, supported lossless file, readable
  dedicated inbox. `.tmp/.part`, links and production/backend folders are excluded.

No WIA, calibration, pixel-repeatability or S2.1 boundary detection is certified.
