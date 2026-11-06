# SELBY Workstation V0.5b — validation

Validated on Windows on 2026-11-01. Implementation and automated validation are complete for this slice; **physical acceptance is pending**. No test submitted a physical print job, changed the existing development order, or deployed production code. Database tests use the existing guarded PostgreSQL `_test` database and disposable concurrency schemas. Standard fixture setup may migrate that test database only; no new application migration is introduced.

## Executed checks

Commands below were run from the repository root using the existing virtual environments.

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_workstation_v05b.py backend/tests/test_workstation_v05a5.py backend/tests/test_workstation_v05a6.py -q -p no:cacheprovider
# 39 passed, 110.83 s

backend/.venv/Scripts/python.exe -m pytest backend/tests/test_workstation_v05b.py backend/tests/test_void_concurrency.py backend/tests/test_production_concurrency.py -q -p no:cacheprovider
# 8 passed, 12.47 s

backend/.venv/Scripts/python.exe -m pytest backend/tests/test_workstation_v05b.py backend/tests/test_physical_labels.py backend/tests/test_inspection.py backend/tests/test_intake.py -q -p no:cacheprovider
# 55 passed, 22.59 s

$env:PYTHONPATH='scanner_agent'
scanner_agent/.venv-analysis/Scripts/python.exe -m pytest scanner_agent/tests/test_thermal_labels.py scanner_agent/tests/test_selby_incoming.py scanner_agent/tests/test_physical_intake.py scanner_agent/tests/test_production_bridge.py scanner_agent/tests/test_production_bridge_gui.py scanner_agent/tests/test_intake_void_gui.py scanner_agent/tests/test_form_wheel.py scanner_agent/tests/test_intake_action_hierarchy.py -q -p no:cacheprovider
# 74 passed, 30.12 s (includes eight new thermal tests)

$env:QT_QPA_PLATFORM='windows'
scanner_agent/.venv-analysis/Scripts/python.exe -m pytest scanner_agent/tests/test_thermal_labels.py -q -p no:cacheprovider --basetemp=validation_artifacts/v05b/native-temp-03
# Final native Windows thermal run: 8 passed, 1.00 s

scanner_agent/.venv-analysis/Scripts/ruff.exe check backend/app/thermal_labels.py backend/app/physical_identity.py backend/tests/test_workstation_v05b.py scanner_agent/selby_workstation/labels_ui.py scanner_agent/selby_workstation/thermal_printing.py scanner_agent/tests/test_thermal_labels.py
# All checks passed
```

Suites overlap; their totals are not a unique-test count. The final eight-test native run followed the final rendering and dialog refinements. Existing backend warnings concern Starlette/httpx deprecation, pytest cache configuration with caching disabled, and Alembic path_separator. No failures remained in the listed checks. An initial native run hit Windows temp-directory permissions; rerunning with a fresh workspace `--basetemp` passed. Segno installation required network access and succeeded in the existing workstation environment. An initial implementation test caught a Qt virtual-method naming collision and incorrect test-side pixel stride; both were corrected before the passing runs.

## New test evidence

`backend/tests/test_workstation_v05b.py` has five cases: strict order/PC roundtrips (two parameters); authenticated HTTP lifecycle/replay/reprint/stale-selection coverage; one-card and three-card real intake/reconciliation manifests (two parameters). The lifecycle fixture receives two identical declared copies and voids one synthetic accidental extra PC before reconciliation. It verifies that exactly two active card labels plus the order label remain, that the two PCs have different QR identities, that voided references cannot be requested, and that no existing PC identity is replaced.

Real default backend eligibility rejects the claim with `payment_unverified`. A test-only monkeypatch then clears aggregate eligibility to isolate ledger transitions; it is neither application configuration nor an override exposed to an operator. That path covers rendered/claimed/submitted/verified phases, exact replay returning `accepted: false`, job-detail conflicts, mandatory reprint reasons, terminal failure rejection, incorrect profile dimensions, wrong-order references and stale content fingerprints. Unauthenticated manifest access returns 401. Existing bridge/void/inspection/intake tests cover the underlying authorization and immutable audit safeguards.

`scanner_agent/tests/test_thermal_labels.py` has eight cases: independent OpenCV decode of an order and two PC bitmap previews (three parameters); a two-page file-only QPrinter/PDF integration test; missing/error-state devices; driver-rejected/incorrect dimensions (two parameters); and a native Qt dialog test. The latter checks explicit batch cancellation, a repeated print click while busy, selected-card batching, mandatory reprint reason, physical-verification confirmation, no automatic job on open, preference persistence across dialog recreation, a lost claim response with **no** repeat spool call, durable intent journaling and an unavailable printer failure recorded before any claim.

The QPrinter PDF test independently checks media dimensions and page count with Qt's PDF parser, then rasterizes both output pages and decodes their QR codes with OpenCV. All print tests use file-only Qt PDF or mocked submission. They never create a painter for a physical printer. Restart coverage recreates the dialog/settings object and reloads the saved preference and backend history; it does not simulate a workstation power failure or assert Windows queue persistence.

## Native Windows evidence

The final preview harness ran with the real `windows` Qt platform and Qt 6.12.0, using a synthetic order, mocked authenticated backend and virtual printer. These are native Qt widget captures, not screenshots of the untouched existing development order:

- [Order preview](validation_artifacts/v05b/windows-preview-order.png)
- [First physical-card preview](validation_artifacts/v05b/windows-preview-card-one.png)
- [Second physical-card preview](validation_artifacts/v05b/windows-preview-card-two.png)
- [Preview environment metadata](validation_artifacts/v05b/preview-environment.json)
- [Driver probe result](validation_artifacts/v05b/windows-driver-probe.json)

Their payloads decode to:

```text
SP:ORDER:1:SP-11111111111111111111111111111111
SP:PC:1:PC-22222222222222222222222222222222
SP:PC:1:PC-33333333333333333333333333333333
```

The two card labels intentionally have identical descriptive metadata. Their complete PC references and QR identities differ. The order label shows two active physical cards. Dedicated number/language text avoids losing them when the name is elided. The full SP/PC reference is printed without shortening.

A read-only Windows printer inventory returned **Munbyn ITPP941** using driver **Munbyn ITPP941**, and **Microsoft Print to PDF**. A separate non-printing probe was executed:

```powershell
$env:QT_QPA_PLATFORM='windows'
scanner_agent/.venv-analysis/Scripts/python.exe scanner_agent/tests/probe_thermal_driver.py
```

It selected the real Munbyn driver, requested 203 DPI, one copy, portrait custom 50 × 30 mm and full-page coordinates. The driver reported **50.09 × 29.99 mm**. `physical_jobs_submitted` was **0**. This probe constructs/configures QPrinter only; it never constructs a print painter or calls the submission function. The regression suite does not depend on the Munbyn being present. Driver rounding is within the explicit 0.2 mm tolerance; no paper measurement was made.

## Acceptance status and remaining limitations

| Requested acceptance step | Evidence / status |
| --- | --- |
| Open existing reconciled synthetic development order | Pending operator session and confirmation of its current state; existing order left untouched |
| Preview order and two PC labels | Implemented; demonstrated in native Windows with synthetic mocked backend, and authoritative manifests tested over HTTP/PostgreSQL |
| Decode expected SP and distinct PC QR payloads | Passed on preview bitmaps and virtual printed PDF pages |
| Exclude voided PCs | Passed against actual authenticated intake/void/reconciliation APIs and guarded PostgreSQL |
| Select Munbyn ITPP941 | Installed Windows device enumerated; real native QPrinter configuration probe passed |
| Verify 50 × 30 mm layout | Passed virtual media/layout tests; real driver reported 50.09 × 29.99 mm; physical calibration pending |
| Print one physical test label with explicit approval | **Not performed**; no hardware approval was requested while backend payment eligibility prevents real printing |
| Scan/decode printed physical label | **Pending physical test**; no claim of printed-paper readability |
| Print history and mandatory reprint handling | Passed HTTP ledger and mocked native UI tests; physical-job verification remains pending |

The current independent payment provider cannot verify payment, so the implementation intentionally blocks real submissions. The conservative inspection-start policy also blocks later dossier states. Do not alter payment, custody or reconciliation to bypass these restrictions. Follow [operator instructions](SELBY_WORKSTATION_V05B_OPERATOR.md) once legitimate backend eligibility is available and obtain explicit approval for exactly one physical test label.

Windows can accept a job that never produces paper or can produce a partial batch. Driver connectivity/status is not physical verification. There is no automatic retry after a granted/uncertain claim, and no distributed atomic commit with Windows. Local journal review and explicit reprint reasons are required for uncertain outcomes; an uncertain job lacking a submitted backend event is not offered as physically verified. No live spooler monitoring/cancellation or automatic audit-recovery command is implemented. Long descriptive text is elided to fit, while complete canonical identity is retained. Extremely large order histories are subject to the current bounded HTTP response limit. TD-W6 transport and physical scanner integration remain future work; the versioned payload contract is ready for it.

