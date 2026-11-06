# SELBY Workstation V0.5b — thermal identification labels

## Audit and scope

Audited Incoming Orders (`incoming_ui.py`), the authenticated session/CSRF transport (`incoming.py`, `intake_client.py`), physical intake/reconciliation (`intake.py`, `intake_ui.py`), V0.5a.5 production bridge (`production.py` on both sides), V0.5a.6 immutable void facts (`intake_voids.py`), SQLite Orders/Cards (`orders.py`, `production.py`), and existing PDF labels/QR parsing (`physical_labels.py`, `physical_identity.py`). No native workstation printer utility existed. Existing PDF endpoints remain unchanged. The new dialog uses the shared operational dark stylesheet and wheel-safe printer/job selectors.

SP and PC references remain canonical. Printing never creates ORD, PC, SP, SLB-C, a backend grading UUID or a certification number, and never opens or upgrades the local Orders registry. Labels contain SELBY branding, full human-readable identities and QR; order labels include the active count; PC labels include declared name, expansion, number and language where available. Text is bounded; full identity always remains legible. Attach PC labels to sleeves or protective packaging, never to cards.

No grading evidence, protected research, payment status, custody state, reconciliation state or historical identity is edited. No deployment or existing development-order modification was performed.

## Implementation

`backend/app/thermal_labels.py` adds authenticated GET `/internal/intake/submissions/{sid}/labels` and POST `/internal/intake/submissions/{sid}/labels/events`. Both reuse existing staff authentication; POST also requires the existing session, JSON, Origin/client header and CSRF contracts. Submitted-order lookup and the shared submission row lock are reused. No schema migration is needed: all label events append to the existing immutable `intake_audit_events` ledger with a job UUID as entity ID.

A manifest uses current production/reconciliation checks and inspection-start eligibility. Active PCs only, matched declaration/parcel parentage, reconciliation quantity checks, discrepancy/return checks and commercial checks remain authoritative. An existing bridge reservation must be confirmed and its PC manifest must agree. No bridge reservation is required merely to identify otherwise valid PCs. Voided PCs are excluded from both counts and selection. A stale or wrong-order selection is rejected; a SHA-256 digest of the complete selected label records also rejects changed label text or active counts between preview and claim.

Previews are available for otherwise valid reconciled identities even when payment/inspection gates block printing. Submission requires *all* backend preparation and inspection-start checks to pass. The current W4 commercial provider cannot verify payment, so real printing currently fails closed with `payment_unverified`. There is no administrator bypass or workstation commercial override. Existing inspection dossiers can also cause `operation_conflict`: this deliberately conservative version does not authorize printing in later inspection states.

The shared order/card encoder and strict decoder are in `backend/app/physical_identity.py`; see [QR specification](SELBY_WORKSTATION_V05B_QR.md). The desktop renders backend-supplied payloads, never reconstructs identities from display text.

`scanner_agent/selby_workstation/thermal_printing.py` renders 203 DPI raster labels with integer QR modules and a four-module white quiet zone. Qt draws the raster at one source pixel per printer dot; there is no fit-to-page transform. At another driver resolution the raster is regenerated. Native output explicitly selects the saved exact printer, 50 × 30 mm media, Qt portrait for the custom width/height, full-page coordinates and one copy. Missing/error-state printers, driver rejection, changed device identity, excessive minimum margins and media differences over 0.2 mm are rejected. Paper dimensions necessarily round to physical printer dots; driver settings and real media still require calibration. Qt behavior follows its [QPrinter documentation](https://doc.qt.io/qtforpython-6/PySide6/QtPrintSupport/QPrinter.html).

## Job safety and audit

Each event records backend operator UUID, job UUID, entity references/types, printer, server timestamp, profile, selection fingerprint, phase, reason and bounded error. Phases are `rendered`, `claimed`, `submitted`, `failed`, `verified` (API names; stored with `label_` prefix). `verified` means the operator explicitly asserts that every physical label in the job was inspected and decoded. Neither QPainter completion nor Windows spooler acceptance is called physical success.

Rendering happens before submission. A fresh backend `claimed` event rechecks eligibility while holding the shared lock immediately before native printing. A repeated claim returns `accepted: false` and never grants another submission. Another job overlapping any earlier claim requires a nonblank reprint reason, including failed or uncertain earlier jobs. Immutable events preserve the original reason. The UI requires confirmation for every job, including all batches, and disables actions/closing while its bounded worker is active. Opening an order/dialog only reads state; it never prints.

Before every backend event and immediately after native submission, a local append-only JSONL journal is flushed and fsynced beside `desktop.ini`. It includes origin, operator, timestamp, request, and result, without credentials or customer personal information. Backend history survives restart; the selected printer persists under `labels/printer` in the existing desktop INI. Missing saved printers remain visibly missing; no default printer is substituted.

This is an at-most-once submission design, not an atomic transaction with Windows. A lost claim response means **no submission** by this client; a crash after a granted claim or after spooler submission can leave an uncertain job. There is no automatic print retry. Inspect physical output and the Windows queue, then refresh history and explicitly reprint with a reason if needed. Keep the local journal for diagnosis. An uncertain job without a confirmed `submitted` event cannot be marked verified through the normal submitted-job control; audit reconciliation requires review rather than inventing an outcome. Backend history is authoritative; the local journal supplements it.

## Installation and operation

Install `scanner_agent/requirements-workstation.txt` in the existing workstation environment; Segno 1.6.6 is the only added dependency. Deploy the additive backend code through the normal reviewed process, then restart backend/workstation. No migration or production deployment is part of this change. The title reports V0.5b. See [operator instructions](SELBY_WORKSTATION_V05B_OPERATOR.md) and [validation](SELBY_WORKSTATION_V05B_VALIDATION.md).

## Limits

The device probe confirms that the installed Munbyn driver accepts the requested native configuration; it does not certify loaded media, calibration, firmware behavior, USB connectivity, physical output or scanner performance. Qt error reporting cannot prove that an apparently idle printer is online. Windows/driver failures may produce partial batches. Live spooler monitoring/cancellation, automatic uncertain-job recovery, TD-W6 scanner transport, certification labels and commercial-provider implementation are outside this slice. Full audit history is read per order and remains subject to the existing bounded HTTP response limit; very large histories will need pagination in a later version. See validation for acceptance steps still pending.

## Desktop Labels integration

Labels is now reachable directly from the sidebar and from Orders → selected confirmed mapped order → Print labels / preview. Previews use fresh authenticated GETs and local rendering without recording a print attempt; actual printing retains the existing backend claim/audit gates. See [UI integration and native acceptance](SELBY_WORKSTATION_V05B_UI_INTEGRATION.md).

