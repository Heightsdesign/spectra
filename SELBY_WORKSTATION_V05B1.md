# SELBY Workstation V0.5b.1 — hardware calibration

## Delivered behavior

**Labels → Printer calibration…** opens an independent diagnostic dialog. It requires no selected order, backend session, accepted quote, payment confirmation or production mapping. Previewing works without any printer available. Opening the screen and rendering a preview submit nothing and create no diagnostic print attempt.

The operator explicitly selects a printer, sees **50 × 30 mm**, previews the fixed diagnostic label, and may choose **Print test label…**. A native Qt confirmation repeats the selected printer, fixed diagnostic payload, target dimensions and exactly one label; Cancel is the default. The implementation never automatically performs the physical test.

This does not change production-label authorization. Customer labels still use authenticated, backend-authoritative eligibility and the existing claim/reprint/audit flow. No commercial, custody, reconciliation, inspection, identity or grading override was added.

## Audit and reuse

Audited `thermal_printing.py` (integer QR rendering, 50 × 30 mm native QPrinter configuration, physical dot placement and submission error handling), `labels_ui.py` (printer preference, backend claims, preview, confirmation and worker state), `labels_page.py` (navigation and mapped-order hosting), the current desktop INI, and `physical_identity.py` (strict production decoders). The real Windows launcher remains `Launch_SELBY.vbs → .venv-analysis/Scripts/pythonw.exe → selby_desktop.pyw → __main__.main`.

Calibration uses the existing **`render_label`**, **`native_printer`** and **`submit`** functions. There is no second printer engine, PDF-to-printer shell command, external browser or permissive customer-label endpoint. The renderer has a small diagnostic-only presentation branch; order/card presentation and backend eligibility are unchanged.

Native output still requires the exact selected printer, a valid native device, a driver-accepted custom page of 50 × 30 mm, one copy, full-page coordinates and minimum margins no larger than 2 mm. A driver-reported difference over 0.2 mm is rejected. The bitmap is regenerated at the printer's reported resolution and painted one source pixel per printer dot, without fit-to-page scaling. Target hardware is the Munbyn ITPP941 at 203 DPI.

## Fixed diagnostic QR and layout

The complete payload is:

```text
SELBY:TEST:V1:CALIBRATION
```

The human-readable identifier is **CALIBRATION-V1**. The image includes SELBY branding and prominent **TEST / NOT VALID** text. No customer reference, production reference, grading result, certification number, PII or credential is accepted as an input to diagnostic rendering.

`encode_diagnostic` and `decode_diagnostic` in `calibration.py` implement a strict fixed version-1 contract. Unknown identifiers, altered versions, case changes and appended characters are rejected. Production `decode_label`, `parse_scan` and `normalize_reference` reject this payload; it cannot become an active SP or PC lookup. It contains no ORD or SLB-C identity. A future scanner must treat this namespace/type as diagnostic only, never authorization or certification.

QR Model 2 error correction Q and a four-module white quiet zone are retained. At 203 DPI the diagnostic symbol uses four-dot modules. The 400 × 240 pixel image is the nearest-dot rendition of 50 × 30 mm. Four small L-shaped marks sit strictly inside the shared 2 mm printer-margin allowance; the top marks stop before the QR quiet-zone rectangle. Human text and the identifier remain outside the QR.

## Isolation and retry safety

`CalibrationDialog` accepts only a local settings path and a Qt parent. It has no order/submission/card parameters, authentication service or API client. Diagnostic rendering accepts no customer content. Neither preview nor printing calls production reserve/claim/event APIs, local OrderStore/ProductionStore, payment services or grading/research code.

The exact printer is saved separately as `calibration/printer` in the existing `desktop.ini`; `labels/printer` is preserved. A saved missing printer remains visibly missing and is never replaced by the default or first available device.

Confirmed diagnostic submissions and explicit diagnostic queue review use `printer-calibration.sqlite3`, beside the same INI. Opening and previewing do not create it. Its separate `diagnostic_jobs` table records diagnostic UUID, printer, fixed payload, timestamps, outcome, bounded error and optional queue-review timestamp. A local diagnostic UUID is not a customer or certification identity. Outcomes are `submitting`, `submitted` or `uncertain`; submitted means software/spooler acceptance, never physically verified output.

The UI becomes busy **before** the confirmation event loop, preventing repeated activation during confirmation or submission. A FULL-synchronous SQLite intent commits before the shared Qt submit call. A unique partial index plus `BEGIN IMMEDIATE` permits only one unresolved diagnostic intent per exact printer in that settings profile, including across windows or after restart. A native error marks the attempt uncertain; a crash or failed post-submission log write leaves a conservative pending intent. There is no automatic retry.

**Review uncertain diagnostic…** requires explicit confirmation that the Windows queue and physical output were inspected and no earlier diagnostic remains pending. It records a separate review timestamp without erasing the prior outcome/error. It sends no job and changes no production history. Any subsequent test requires a new explicit printing confirmation. The diagnostic dialog and main Workstation resist normal close while their diagnostic worker is active.

## Changed files

- `scanner_agent/selby_workstation/calibration.py`: fixed codec/record, shared-renderer adapter and separate local diagnostic history/retry guard.
- `scanner_agent/selby_workstation/calibration_ui.py`: standalone dark diagnostic dialog, persisted selector, preview, explicit one-label confirmation, error/review handling.
- `scanner_agent/selby_workstation/thermal_printing.py`: diagnostic headline and boundary markers in the existing renderer.
- `scanner_agent/selby_workstation/labels_page.py`: visible calibration section and dialog lifecycle/busy integration.
- `scanner_agent/selby_workstation/app.py`: diagnostic-worker close guard and V0.5b.1 title.
- `scanner_agent/selby_workstation/desktop.py`, `__main__.py`: V0.5b.1 version display.
- `scanner_agent/tests/test_calibration.py`: fourteen isolated diagnostic cases, with only mocked/file-only printing.
- `scanner_agent/tests/probe_labels_navigation.py`: optional `--calibration` native acceptance, driver configuration probe, screenshots and unchanged-record checks.

No backend implementation, database migration, customer identity, payment/quote evidence, custody/reconciliation record, grading evidence or protected research module was changed. No dependency was added and nothing was deployed to production.

## Manual calibration instructions

1. Use the fresh **SELBY · Workstation V0.5b.1** window, or reopen an older Workstation normally. Open **Labels → Printer calibration…**. Signing in or selecting an order is unnecessary.
2. Click **Preview test label**. Confirm SELBY, **TEST / NOT VALID**, `CALIBRATION-V1`, all four corner marks and the diagnostic QR. The QR must decode exactly to `SELBY:TEST:V1:CALIBRATION`.
3. Explicitly select **Munbyn ITPP941**. Load 50 × 30 mm media and calibrate the feed using the printer's normal hardware/driver procedure. The shared pipeline requests 50 × 30 mm, 203 DPI and one copy; it does not calibrate the feed sensor or modify firmware. Confirm the Windows queue is clear.
4. **The final physical test is left to the operator.** When ready, choose **Print test label…**, review the exact device/profile/diagnostic payload and explicitly approve **one** test label. Cancel leaves the printer untouched. Do not use production order labels to work around commercial restrictions.
5. Measure the paper label against the 50 × 30 mm target. Check that every corner mark is visible with approximately 2 mm white space at the boundary, the TEST / NOT VALID text and identifier are legible, and QR modules/quiet zone are sharp and unclipped. Scan the actual printed QR and compare the complete diagnostic payload. The onscreen preview is not a physical ruler.
6. Treat a submitted status as **physical output unverified**. If submission fails or the outcome is uncertain, inspect the Windows queue and physical output before retrying. Use **Review uncertain diagnostic…** only after that inspection. Another test always requires a new confirmation. Keep the local diagnostic history for support.
7. Use the diagnostic paper only for hardware checks; discard it after inspection. Customer identification printing remains a separate, authenticated and gated workflow.

## Limits

The driver can accept a job without producing paper, and Windows/USB/printer failures can produce partial or absent output. This version does not monitor/cancel spooler jobs, verify physical QR scanning, control feed calibration or guarantee physical media dimensions. Intent guards coordinate this local settings profile, not divergent copies on other machines. A physical label measurement/scan is still pending operator action. See [validation and native screenshots](SELBY_WORKSTATION_V05B1_VALIDATION.md).

