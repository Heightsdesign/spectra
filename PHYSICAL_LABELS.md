# SPECTRA W5.1c — Physical labels and QR identification

## Scope and architecture

W5.1c adds individual labels, reprints, submission-scoped batch PDFs and keyboard-scanner input to W5.1/W5.1b. W5.1b was inspected and its 47 backend/HTTP tests passed before implementation. No grading, certification numbers, payments, carrier labels, direct Bluetooth API or printer SDK is added.

`PhysicalCard.reference` remains the authoritative identity: one physical card, one complete `PC-` reference. Label generation reads existing relationships; it never creates a physical-card record, allocates an identity, changes matching/custody/reconciliation, or writes an audit event. Frozen/reconciled cards remain printable. Identical card descriptions are distinguishable by their complete references.

**No Alembic migration is required. Head remains 0006.** The operational database was not reset or seeded. Tests use transactional fixtures and disposable schemas in the guarded PostgreSQL `_test` database.

Backend modules:

- `physical_identity.py`: canonical reference normalization and versioned scanner parsing, independent of routers/PDF libraries.
- `physical_labels.py`: bounded query/projection, Segno QR generation, ReportLab PDF rendering and staff-protected endpoints.
- `customer_operations.py`: existing protected lookup now accepts both a raw reference and a v1 scanner payload.
- `main.py`: router registration, safe validation errors and private response headers.

Frontend inventory actions use `PhysicalLabelsPanel`/`CardLabelActions`, outside the disabled reconciliation forms. The existing lookup at `/admin/cards` accepts scanner text. Shared FR/EN admin language/navigation remains in place. Official V2 logo assets are unchanged; the label uses the plain SPECTRA name in black.

Install runtime requirements with `backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt` from the repository root. Backend test installations additionally use `-r backend/requirements-test.txt`. New pinned runtime libraries are **Segno 1.6.6** and **ReportLab 5.0.1**; pypdf 6.20.1 and pypdfium2 5.14.0 validate PDFs in tests. [Segno documents standard QR generation and quiet zones](https://segno.readthedocs.io/en/latest/api.html); [ReportLab documents PDF generation](https://docs.reportlab.com/).

## QR payload v1

```text
SP:PC:1:PC-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

- `SP:PC:1:` identifies SPECTRA physical-card payload version 1.
- The suffix is the entire canonical reference: `PC-` plus **32 hexadecimal characters**, uppercase.
- Length is 43 ASCII characters. No UUID shortening, hash truncation or alternate identity is used.
- QR encoding: standard QR Model 2, **version 3**, error correction **Q**, alphanumeric mode, without automatic error-level boosting. It is not a Micro QR code.
- The 29×29 symbol has a four-module white quiet zone on every side (37×37 overall).
- The payload is deterministic, contains no URL/domain, account reference, name, email, address, phone, token or bearer credential, and has no session expiry.
- A valid QR does not grant access. Lookup still requires an active verified staff account and a valid session.

The parser accepts raw `PC-` references or this exact v1 format, normalizes case, and removes only leading/trailing ASCII space, tab, CR and LF. Embedded whitespace, another version, incomplete identifiers, URLs and non-hexadecimal characters are rejected. The frontend sends only the resolved canonical reference to the existing staff lookup API.

## Label profiles and rendering

| Profile | PDF page | QR module | Overall QR including quiet zone |
| --- | --- | --- | --- |
| `50x30` (initial default) | 50 × 30 mm | 4 dots at 203 DPI ≈ 0.5005 mm | ≈ 18.52 mm |
| `70x40` (alternate) | 70 × 40 mm | 5 dots at 203 DPI ≈ 0.6256 mm | ≈ 23.15 mm |

These are configurable application layout profiles, **not confirmed media specifications for the installed printer**. Profiles are an explicit bounded allowlist; operators choose one per PDF. To support another size, add and validate a server profile and matching UI option, rather than accepting arbitrary dimensions/file paths.

Each PDF page contains exactly one card label: SPECTRA, a vector QR, declared card name/number/language when associated, full PC reference, and submission reference. QR and text occupy separate fixed regions. Both current profiles show the full 35-character PC reference in 6pt Courier. Standard 35-character SP references also fit. No customer identity, recipient, address, telephone, notes, operational reasons or session information is queried for rendering.

Card-name text is width-bounded and abbreviated with `...` when necessary. The bundled licensed Vera font preserves supported Unicode (including French accents and basic Greek); unsupported characters use visible `?` markers instead of invisible missing-glyph boxes. The complete declared identification remains available through authenticated lookup. This is a current limitation for Japanese/Cyrillic and other unsupported scripts; labels still retain full identity and card number/language. Do not put personal contact information into declared card-identification fields: these existing free-text card fields are printed, whereas customer-account fields are excluded.

There are no gradients, halftones, HTML print layouts, remote font requests or logo modifications. Exact point dimensions are derived from millimetres. PDF viewer preferences request `/PrintScaling /None`; application code cannot force a browser, Windows driver or printer to honor actual size. The operator must verify settings.

ReportLab invariant mode gives byte-identical regeneration for unchanged data/profile, including fixed generic metadata. Metadata contains generic SPECTRA document information only; it does not record staff/customer identity, print status or a purported physical-print timestamp. If a card's declared association changes through a permitted W5.1 operation, label description can change; the authoritative reference and QR remain stable.

## Staff endpoints and privacy

All label APIs are internal and excluded from public OpenAPI:

| Endpoint | Use |
| --- | --- |
| `GET /internal/labels/cards/{reference}/pdf?profile=50x30` | Individual PDF or identical reprint |
| `POST /internal/labels/submissions/{submissionId}/pdf` | Single- or multi-card submission-scoped PDF |
| `GET /internal/labels/calibration/pdf?profile=50x30` | Synthetic calibration label |

Batch body:

```json
{"references":["PC-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"],"profile":"50x30"}
```

Every endpoint reuses W2/W5.1 server-side authentication and staff membership. Both admin and operator may prepare labels. Unauthorized callers are denied before card lookup. The POST additionally requires the established Origin, `X-Spectra-Client` and session-bound CSRF protections, although PDF generation has no business mutation.

- Responses, including validation/authorization errors, use private no-store and no-referrer headers. PDFs use `application/pdf`, safe generated inline filenames and `X-Label-Count`.
- References are fully validated; batch reference strings are at most 64 characters before normalization, with 1–250 input elements. Duplicates collapse to one page. Canonical references sort lexicographically, independent of checkbox or request ordering.
- Every selected card must exist **in the specified submission**. A missing or foreign-submission reference fails the whole request (`404 card_not_in_submission`); no partial PDF is returned.
- Parcel and associated entry must agree with the physical card's submission. Inconsistent relationships produce `409 trace_inconsistent`; no repair or reassignment is attempted.
- Resource bounds: 250 input records/pages, 8 MiB maximum output, a 15-second generation deadline checked between pages, and at most two concurrent render jobs per application process. Saturation/deadline returns `503 labels_busy`. Bounds do not replace deployment-level request/rate limits; all callers are authenticated staff.
- Parameterized SQL selects only card/submission/declared-entry information. There are no user-controlled filenames, filesystem reads/writes, SQL expressions or output paths.
- PDFs are built in memory. Browser previews use revocable blob URLs and are released on close/replacement/unmount. Downloads become local sensitive internal documents even though they contain no account PII.
- Existing public customer APIs do not gain internal QR/reference fields. Labels do not insert customer data into immutable audits.

## Individual, reprint and batch workflow

1. Open a submission's physical inventory. Each card has a labeled checkbox, **Print label** and **Reprint label**. Both actions prepare a PDF for that existing reference; neither implies that it was previously printed.
2. Choose the profile matching the intended stock. Preview the PDF, download it, or use **Open PDF / print** to open one standard PDF viewer and its print workflow. Physical output is never reported as successful by the app.
3. For a batch, check individual cards or **Select all**. The selected count is visible before preparation. **Prepare selected labels** and **Reprint selected labels** create one multi-page PDF, one deduplicated card per page.
4. If a submission has more than 250 physical cards, reduce the selection and print multiple bounded batches. Select all does not silently truncate. There is no global cross-customer batch.
5. Confirm the page count and first/last references before releasing a batch. Reprinting uses the same identifiers; discard duplicate physical stickers according to the operator's workflow.

The UI does not open a popup per card and never calls `window.print()` in a per-card loop. There is one PDF preview and one open/print link for a batch. Browsers may have their own PDF-viewer behavior, especially on mobile; downloading and printing from a desktop PDF reader is supported.

## Scanner workflow

Open the protected **Card lookup / Recherche de carte** page, focus its reference field, and scan with a keyboard-emulating QR-capable scanner configured to send Enter. A raw PC reference may also be pasted. CR/LF suffixes are normalized safely. An expired staff session requires sign-in; the same sticker remains valid afterward. QR scanners/readers that only open HTTP URLs will not automatically navigate because the payload is intentionally opaque.

Resolved results retain W5.1b card → parcel → submission → customer traceability and navigation. This is an operational association, not a legal ownership assertion. Unknown references remain errors rather than new card registrations.

## Printer documentation and Windows setup

The [official 941B product page](https://munbyn.com/products/bluetooth-thermal-label-printer-941b) lists 203 DPI, 150 mm/s and a 1.57–4.3 inch print-width range. Width alone does not establish supported label height, gap detection or reliable 50×30 mm media handling. **Neither application profile has been physically certified on this printer.** Rated speed is not an application throughput or readability guarantee.

MUNBYN's product page describes Bluetooth as mobile-only, while its newer [Windows Bluetooth setup guide](https://support.munbyn.com/hc/en-us/articles/54258310492563--Bluetooth-connection-method-How-to-connect-the-devices-using-Bluetooth-on-Windows) describes a Windows driver for ITPP941B/BP and excludes Windows-on-ARM Bluetooth installation. Verify the exact model, Windows architecture and installed driver with MUNBYN. The app supports any working standard Windows print queue, with no SDK/Bluetooth code.

1. Check the underside model label. Obtain the matching Windows driver through the [official driver download page](https://support.munbyn.com/hc/en-us/articles/6092502480787-Printer-Drivers-SDK-Download).
2. For USB, install the applicable USB driver and follow its installation instructions. This is a supported fallback if Bluetooth setup is unavailable.
3. For Bluetooth on a supported Windows machine, follow the vendor's driver installer discovery/setup flow rather than assuming ordinary Windows Bluetooth pairing creates a usable printer queue. Select the working installed print queue; identify USB/Bluetooth queues separately if both exist.
4. Confirm supported stock dimensions with the media supplier/vendor before buying/loading small labels. In printer preferences, set the exact profile dimensions, stock/gap sensing mode, orientation, speed and darkness appropriate to that stock. Driver screens differ by version.
5. In the PDF reader/print dialog select the intended queue, **Actual size / 100%**, **one PDF page per label**, matching paper dimensions and **one copy** for the pilot. Disable fit-to-page, shrink/expand, N-up, automatic rotation unless verified, and header/footer options if offered. Printing the PDF avoids webpage headers and footers.

## Calibration and physical QA

Printable files supplied:

- [50×30 mm calibration PDF](backend/label_samples/calibration-50x30.pdf)
- [70×40 mm calibration PDF](backend/label_samples/calibration-70x40.pdf)
- [Synthetic 50×30 mm sample](backend/label_samples/sample-50x30.pdf)

The staff calibration endpoint generates the same profile-specific test sheet. Calibration shows a 10 mm ruler and an inset border (48×28 mm or 68×38 mm). Its all-zero PC reference is synthetic, marked **CALIBRATION / NOT A CARD**, is not registered, and should not resolve to a real record. Never apply the calibration/sample label to production inventory.

Load stock and run the model-specific paper identification procedure. MUNBYN's [calibration troubleshooting guide](https://support.munbyn.com/hc/en-us/articles/4414515663251-ITPP941-Why-the-label-is-getting-stuck-or-half-printed) describes holding FEED and releasing at the single-beep calibration cue, then waiting for paper motion to finish. Confirm the matching model manual; do not perform the separate reset procedure as routine calibration.

Physical QA checklist (record results; none are confirmed by automated PDF tests):

- Measure the 10 mm ruler with a physical ruler/caliper. Check border dimensions and both axes; do not compensate for scaling by changing identity layout.
- Check feed position, orientation, full references, all four QR quiet zones and absence of clipping across at least 20 consecutive labels. Test 50/100-label batches only after a pilot passes.
- Start with conservative speed/darkness and adjust one setting at a time. Verify solid dark modules and distinct white modules without thermal bleeding or weak strokes; maximum rated speed is not the default recommendation.
- Scan the first/middle/last labels with the intended scanner at representative distances (e.g. 5, 10, 20 and 30 cm), angles and operational lighting. Record successful distance range, exact decoded payload and Enter behavior.
- Scan two identical card descriptions assigned to different accounts; ensure their complete references resolve to distinct expected records while authenticated.
- Attach labels only to approved protective sleeves or holders, never directly to a collectible card. Verify adhesive compatibility, secure adhesion and removal/residue behavior without risking a real card.
- On sacrificial sleeves, test normal rubbing/handling, moderate moisture exposure and storage conditions. Check smudge resistance and QR readability afterward; record stock/adhesive type and test conditions.
- Test an expired staff session: scan must require authentication, then resolve the same reference after signing in.
- Reprint a label and verify unchanged reference/payload; prevent duplicate stickers from being attached to different cards. Record printer/driver/firmware, stock, speed/darkness, print settings, measurements and scanner model.

**No real MUNBYN printer or physical scanner was tested.** Media compatibility, Windows Bluetooth operation, actual print scale, scanner distance/reliability, adhesive behavior and smudge resistance remain unverified. This milestone provides the software and test artifacts; it does not certify physical output.

## Validation results — 2026-10-15

| Check | Result |
| --- | --- |
| W5.1b inspection/regressions before implementation | 47 passed |
| New backend label tests | **30 passed** |
| Extended fresh Uvicorn/PostgreSQL HTTP test | **1 passed** |
| Full backend suite | **328 passed**, 21 existing dependency deprecation warnings |
| Full frontend suite | **54 passed** |
| ESLint | Passed, zero warnings |
| TypeScript | Passed |
| Production build | Passed |
| Headless Chrome | Passed at **1440×1000** and **390×844** |

Tests decode both QR PNGs and actual PDF pages rasterized with PDFium/OpenCV at 203 and 300 DPI, assert exact page dimensions and print-scaling preference, full unique references, deterministic bytes for unchanged data, deduplication/order, 20/50/100/250-page PDFs, bounded Unicode/long-name text, PII-free output/metadata, scanner validation, staff denial, POST Origin/CSRF, foreign-submission rejection, safe filenames, resource failures and frozen-record/audit preservation.

The fresh HTTP server runs against a disposable PostgreSQL schema and verifies authorized PDF generation/reprint, decoded payload, batch CSRF and scanner lookup. Chrome uses synthetic staff/card data and a real synthetic PDF fixture, not operational records. It checks 36-card selection/count, one batch PDF request, preview/download/open controls, individual reprint, frozen-card printing, keyboard Enter scanner submission, FR/EN, responsive overflow and the previous intake/customer-navigation regressions. It does not confirm a printer dialog or physical print completion.

Reproduce backend tests with `python -m pytest` from `backend` after installing test requirements; frontend checks with `npm test`, `npm run lint`, `npm run typecheck`, `npm run build`, then `npm run test:admin-browser` from `frontend`. The browser test needs installed Chrome or `CHROME_PATH` and free ports 18091–18093. Local screenshots are under `frontend/.visual-review/admin/`. Existing Next parent-lockfile and Node experimental type-stripping warnings do not fail checks.

## Files changed

- `backend/app/physical_identity.py`, `backend/app/physical_labels.py`
- `backend/app/customer_operations.py`, `backend/app/main.py`
- `backend/requirements.txt`, `backend/requirements-test.txt`
- `backend/tests/test_physical_labels.py`, `backend/tests/test_customer_operations_http.py`
- `backend/label_samples/calibration-50x30.pdf`, `backend/label_samples/calibration-70x40.pdf`, `backend/label_samples/sample-50x30.pdf` (synthetic artifacts)
- `frontend/src/lib/physical-labels.ts`, `frontend/src/lib/customer-operations.ts`
- `frontend/src/components/physical-labels.tsx`, `frontend/src/components/intake-workspace.tsx`, `frontend/src/components/customer-operations.tsx`
- `frontend/src/app/globals.css`, `frontend/next.config.ts`
- `frontend/tests/physical-labels.test.mjs`, `frontend/tests/admin-browser.mjs`
- `frontend/README.md`, `PHYSICAL_LABELS.md`
