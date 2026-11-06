# SELBY Workstation V0.5c — Scan-to-Grading

## Architecture and scope

The scan path is a read-only vertical slice over V0.5a.5 production mappings and the existing inspection workspace. `scanning.py` loads the existing dependency-free `backend/app/physical_identity.py` versioned decoder; it does not introduce another production QR grammar. Calibration uses V0.5b.1 `decode_diagnostic`. The repository backend contract file must remain present in workstation distributions.

Audited `physical_identity.py`, `calibration.py`, `production.py` and `production_ui.py`, `label_mapping.py`, `orders.py` and `orders_ui.py`, desktop startup/navigation, inspection Session persistence, grading UI, backend production snapshots, inspection eligibility and commercial checks. Production snapshots already provide authenticated staff identity, active physical inventory, immutable registry binding and per-PC inspection eligibility. No backend endpoint, database migration, commercial override, custody event or production allocation was added.

## Scan path

1. Open **Scan card** from any module, or **Ctrl+Shift+S**. The single application-owned dialog captures keyboard input only in its dedicated field.
2. Enter/Return submits a complete payload; a saved no-suffix option requires Identify. Paste/manual input uses the same strict decoder and resolver. No whitespace, case or URL normalization is performed.
3. A physical QR is matched by its complete PC reference to exactly one local bridge mapping. Order QR resolves the complete SP reference and only opens order lookup. Diagnostic payloads are recognized locally and never reach production lookup.
4. Require confirmed mapping and the configured backend origin. Fetch the authenticated production snapshot in the existing bounded background worker; compare registry UUID, SID/SP, ORD, every PC UUID/reference and every SLB-C pair. Missing/voided identities, conflicts, wrong origin/registry and network failures fail closed. Re-read the local mapping before returning; discard results after a registry or connection switch.
5. Show the card description, ORD/SP, PC and SLB-C. Blocked cards remain in a read-only scan result with backend reason codes/messages; no session is created/resumed and no status is changed.
6. Eligible cards are selected by exact SLB-C in existing Orders, then passed to `DesktopShell.open_card_workflow`. Saved associations retain existing checksum/provenance verification, unsaved-work confirmation and inspection resume behavior.
7. Without a linked dossier, **Open original scan for identified card…** explicitly refreshes backend eligibility before invoking the existing image picker/session creation flow. Cancellation creates nothing. Saving a grading dossier and associating it with an operator/reason remain explicit existing actions. The scan does not auto-associate evidence or create a grading dossier.

## Input and concurrency

This release deliberately uses an explicit capture surface, without global keystroke heuristics. Ordinary text entry and other dialogs retain their normal behavior; scan from those screens by opening Scan card first. Input readiness is displayed separately from hardware connection status, which remains unverified. Identical payloads within two seconds are suppressed. During lookup, capture and actions are disabled, and closing the scan dialog/main window is blocked. Scans during lookup are not queued: wait for the result before scanning another card. After two seconds, a repeat performs a fresh backend read. No scan writes identities or changes status, including after restart.

## Hardware findings

Windows PnP inventory found several USB HID keyboards, Bluetooth HID and Bluetooth serial ports COM3–COM6. COM3 is described as a standard Bluetooth serial link; that does not establish scanner transport. The inventory cannot attribute the generic keyboards to TD-W6. No serial port is opened. USB/Bluetooth HID keyboard-wedge transport is supported by the input surface, pending actual TD-W6 operator testing. Connection, keyboard layout, suffix and physical QR capture are not yet hardware-accepted.

## Files and validation

Added `scanning.py`, `scanner_ui.py`, resolver/UI tests and `probe_scan_navigation.py`. Updated desktop navigation, application close guard and V0.5c version text. Settings registry selection now accepts the existing schema-2 production registry, requiring its bridge tables; schema-1 support is retained. Existing grading, custody, print and production components are reused.

See [validation](SELBY_WORKSTATION_V05C_VALIDATION.md) and [operator instructions](SELBY_WORKSTATION_V05C_OPERATOR.md). No physical scans or prints were automated, and existing development orders were not edited.
