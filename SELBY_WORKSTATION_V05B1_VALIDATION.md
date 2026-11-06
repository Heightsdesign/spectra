# SELBY Workstation V0.5b.1 — validation

Validated on native Windows on 2026-11-01. **No physical label was printed.** The final test is reserved for the operator. Calibration and existing production checks are isolated.

## Final automated checks

From the repository root:

```powershell
$env:QT_QPA_PLATFORM='windows'
$env:PYTHONPATH='scanner_agent'
New-Item -ItemType Directory -Path validation_artifacts/v05b1 -Force | Out-Null
scanner_agent/.venv-analysis/Scripts/python.exe -m pytest scanner_agent/tests/test_calibration.py scanner_agent/tests/test_labels_navigation.py scanner_agent/tests/test_thermal_labels.py scanner_agent/tests/test_selby_desktop.py -q -p no:cacheprovider --basetemp=validation_artifacts/v05b1/native-tests-04
# 45 passed, 9.13 s

scanner_agent/.venv-analysis/Scripts/python.exe -m pytest scanner_agent/tests/test_production_bridge.py scanner_agent/tests/test_intake_void_gui.py scanner_agent/tests/test_selby_incoming.py scanner_agent/tests/test_selby_desktop.py -q -p no:cacheprovider
# 41 passed, 16.80 s

backend/.venv/Scripts/python.exe -m pytest backend/tests/test_workstation_v05b.py backend/tests/test_physical_labels.py -q -p no:cacheprovider
# 35 passed, 11.17 s

scanner_agent/.venv-analysis/Scripts/ruff.exe check scanner_agent/selby_workstation/calibration.py scanner_agent/selby_workstation/calibration_ui.py scanner_agent/selby_workstation/thermal_printing.py scanner_agent/selby_workstation/labels_page.py scanner_agent/tests/test_calibration.py scanner_agent/tests/probe_labels_navigation.py
# All checks passed
```

The suites overlap; these totals are not a count of unique tests. Backend integration uses the existing guarded `_test` database, never the development order. Existing backend warnings concern Starlette/httpx deprecation, pytest cache configuration with caching disabled and Alembic path_separator.

The fourteen new calibration cases cover:

- Diagnostic codec roundtrip and rejection by the actual production decoder functions.
- Independent OpenCV QR decode and physical image dimensions at 203/300 DPI (two parameters); the outer 2 mm remain white and corner marks stay within the printable area.
- One-page Qt file-only PDF output; an independent Qt PDF parser checks media dimensions, then rasterizes the page for QR decoding.
- Preview without a selected printer, no history creation and forbidden backend API transports.
- Cancelled confirmation and nested/repeated activation while the confirmation is already active.
- One mocked submission despite repeated clicks; normal close blocked while busy; separate submitted diagnostic history and saved selection across dialog recreation.
- Unavailable printer and invalid paper settings rejected before any submission (two parameters).
- Uncertain native result, refusal of another submission and explicit local queue review retaining the original uncertain outcome.
- Restart with an unresolved persisted intent and safe explicit review.
- A **real native Qt confirmation dialog**, automatically cancelled; no driver opens or hardware calls occur.
- Concurrent local intents serialized to one unresolved job per printer.
- No available devices with a saved missing printer: preview still works, the saved name is visibly missing, and no alternative printer is silently chosen.

Existing thermal tests continue to use mocked submission or file-only Qt PDF devices. Automated tests never create a print painter for a physical device. Early test-only runs exposed a NumPy view whose QImage owner had expired and a missing artifact-parent directory; the helper now copies returned pixels and the directory is explicitly created. The final native suite passes.

## Native acceptance through the real entry point

Executed:

```powershell
$env:QT_QPA_PLATFORM='windows'
scanner_agent/.venv-analysis/Scripts/python.exe scanner_agent/tests/probe_labels_navigation.py --calibration --local-fixture-login
```

The external harness runs the real `selby_desktop.pyw` entry point and Workstation widgets, on the **windows** Qt platform. Its hardware-submit and backend business-write paths raise if called. Calibration is opened and previewed before the temporary fixture login and before selecting the existing production order. A separate driver-only probe creates/configures QPrinter without creating a painter or submitting a job.

Native results:

| Check | Result |
| --- | --- |
| Labels → Printer calibration reachable | Passed |
| No order selected or backend session required for diagnostic preview | Passed; calibration dialog accepts neither an order nor an auth client |
| Diagnostic image | 400 × 240 pixels at 203 DPI, target 50 × 30 mm |
| Independent QR decode | Exactly `SELBY:TEST:V1:CALIBRATION` |
| Real installed device selected | Munbyn ITPP941 |
| Native driver profile | 203 DPI; reported 50.09 × 29.99 mm for the 50 × 30 mm request |
| Physical diagnostic print button activated | **False** |
| Diagnostic jobs created by preview/probe | **0** |
| Production printer preference | Unchanged; calibration preference is separate |
| Existing unpaid production order | Printing remained disabled |
| Backend business POSTs | **0** |
| Physical print jobs | **0** |
| Existing local registry and backend submission snapshot | Unchanged |

After diagnostic preview/configuration, the harness signed in with the documented existing local operator fixture using an in-memory session, displayed the existing `ORD-000001` and its two confirmed PC mappings, and checked all production print buttons remained disabled. Backend blockers remained **payment_unverified**, **quote_not_accepted** and **commercial_restriction**. No blocker was cleared or bypassed. The temporary fixture session was revoked on exit; no fixture credential replaced the operator's saved Windows credential.

The local registry logical digest matched before/after:

```text
5e2d5c6225ad9919c7823d82e0a549912be040dd90d0c4ef7bb323c5450cd7ea
```

The complete backend submission snapshot, including physical-card state and audit history, also matched. No production print claim or event was created. The fixed diagnostic bitmap contains no real SP, PC, ORD, SLB-C or certification reference. Production references in the acceptance JSON/screenshots belong only to the separate existing-order restriction check.

## Native artifacts

- [Labels screen with Printer calibration section](validation_artifacts/v05b1/windows-calibration-section.png)
- [Diagnostic preview with Munbyn selected](validation_artifacts/v05b1/windows-calibration-preview.png)
- [Actual diagnostic label bitmap](validation_artifacts/v05b1/diagnostic-label.png)
- [Existing production order remains blocked](validation_artifacts/v05b1/windows-labels-preview-0.png)
- [Native acceptance JSON, profile and unchanged-state checks](validation_artifacts/v05b1/native-acceptance.json)
- [Actual Windows launcher/process evidence](validation_artifacts/v05b1/launcher-launch.json)

A fresh visible Workstation was also launched using the unmodified `scanner_agent/Launch_SELBY.vbs`. Windows reported its visible title as **SELBY · Workstation V0.5b.1**, using `.venv-analysis/Scripts/pythonw.exe -B selby_desktop.pyw`. Existing operator windows were not terminated. The operator-facing VBS launch has no injected validation hooks; it opens normally and does not print.

## Remaining physical acceptance

The installed driver accepted the requested profile within the shared 0.2 mm tolerance, but no paper came out during validation. Loaded media, feed alignment, physical text sharpness, real QR scanning and USB/spooler reliability are **not physically verified**. Software submission cannot prove physical success, and there is no automatic uncertain-job retry. No new hardware-calibration, payment or grading authorization is inferred from a preview.

Follow the [manual calibration instructions](SELBY_WORKSTATION_V05B1.md) to explicitly approve exactly one diagnostic test label, measure it and decode the paper QR. This final physical action is left to the operator. No deployment was performed.

