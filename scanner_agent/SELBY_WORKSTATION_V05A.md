# SELBY Workstation V0.5a — Orders and individual card identity

This increment adds a local production registry to the existing PySide6 workstation.
It does not change V0.4 grading policy, condition review, inspection persistence,
recovery, operator overrides, reports, or upstream acceptance gates.

## Launch

From PowerShell:

```powershell
Set-Location 'C:\Users\plher\Documents\spetra\scanner_agent'
.\.venv-analysis\Scripts\python.exe -B .\selby_workstation.py --orders
```

Normal launch without `--orders` retains inspection navigation. The **Orders**
toolbar action works without loading an image. Close the Orders dialog to return
to inspection. `--orders`, `--condition`, and `--grading` are alternative initial
workbenches. Existing image/report/session flags still work. Optional
`--orders-store 'C:\path\orders.sqlite3'` selects a different registry explicitly;
use the same registry on every launch to retain the same identity namespace.
Dependencies remain in `requirements-workstation.txt`; SQLite is Python stdlib.

## Audit of the existing repository

Before implementation, repository status, scanner package/entry points, V0.1–V0.4
guides and validation reports, session and grading models, storage utilities,
workbench navigation, and workstation tests were inspected. The checkout contained
extensive staged and untracked work, including the existing workstation. No staging,
reset, cleanup, commit, research modification, or history rewrite was performed.
Git inspection used a command-scoped safe-directory exception for the sandbox
account's ownership mismatch; global configuration was unchanged.

Existing conventions: UTC ISO timestamps from `spectra_scanner.common.utc_now`,
session/version UUIDs, schema 1 inspection JSON, exclusive immutable version files,
parent SHA-256 provenance, local text operators, append-only grading actions, and
separate modal workbench dialogs. Those formats and evidence validators remain
unchanged. New production IDs do not replace the existing session UUIDs or legacy
operator-entered dossier card labels.
The unchanged grading/session engine retains its `0.4.0` serialization tool version;
the new registry is independently versioned with SQLite schema 1. The workstation
window and command help identify the combined UI as V0.5a.

## Architecture and storage

`selby_workstation/orders.py` owns the registry service. `orders_ui.py` presents it;
the main window supplies a toolbar entry and an explicit store path. Opening the
registry does not edit, save, or switch the active inspection. Submitted registry
changes commit immediately and are independent of inspection Undo/Redo/autosave.

Default storage is `local_data/selby_workstation/orders.sqlite3`, resolved relative
to the installed scanner package rather than the shell working directory. This is
a local SQLite database, not a server. Schema version is `PRAGMA user_version=1`;
unknown versions fail closed. SQLite's default rollback journal, foreign keys,
`synchronous=FULL`, and `BEGIN IMMEDIATE` serialize writers and commit each operation
with its audit rows. Every connection closes after use. A failed batch rolls back
all its cards, IDs, and events; interrupted uncommitted work is recovered by SQLite.

Tables:

| Table | Data |
|---|---|
| `orders` | AUTOINCREMENT number, immutable ID, customer name/contact, external reference, notes, created/received UTC timestamps, status |
| `cards` | AUTOINCREMENT number, immutable ID, parent order FK, permanent positive position, JSON metadata, status, created/updated UTC timestamps, nullable JSON session reference/session UUID, reserved null certification reference |
| `audit` | Monotonic event number, UTC timestamp, entity ID, operation, operator, JSON before/after snapshots, reason |

`card_count` is derived by query and includes cancelled card records. Contact is
free text supporting email, phone, address, or other supplied information. Card
metadata is an optional JSON object; the UI supplies a description for the batch.
The service returns ordinary dictionaries, with JSON columns decoded.

IDs format as `ORD-000001` and `SLB-C-000001`; six digits are minimum width, not a
one-million-ID ceiling. The independent SQLite AUTOINCREMENT sequences allocate
globally within this registry, under the write transaction. IDs become issued only
after commit. Failed, uncommitted allocations are not issued. Committed entities
cannot be deleted; cancellation retains them. IDs and parent/position cannot be
updated, including through direct SQL under the installed triggers. Unique indexes
reject duplicate IDs and order positions; a foreign key rejects orphan cards.
Audit update/delete triggers prevent accidental rewriting through normal SQL.

Never reset the sequences, delete the database, merge independent databases, or
restore an old backup as a new live registry without reconciling issued IDs.
These operations are outside this application's guarantees. For backup use
SQLite's backup API or close all registry users before copying the database;
do not copy only the main file during an active journaled transaction.

## Lifecycles and corrections

| Order state | Permitted ordinary next states |
|---|---|
| draft | received, cancelled |
| received | processing, cancelled |
| processing | completed, cancelled |
| completed | shipped |
| shipped | none |
| cancelled | none |

| Card state | Permitted ordinary next states |
|---|---|
| registered | processing, cancelled |
| processing | completed, cancelled |
| completed | none |
| cancelled | none |

Unknown states, unchanged states, skipped steps, and backward changes fail. The
first transition to received stamps the current UTC time; subsequent corrections
preserve that timestamp as history. Arbitrary historical received-date entry is
not exposed in this slice. Cards may be added only to draft/received orders;
positions append after the highest permanent position, including cancellations.
The service also supports an explicit starting position and rejects collisions.
UI batch size is 1–1000 and the whole batch is atomic.

Order and card statuses are independent operator declarations: cancelling an order
retains all its card records and does not cascade card statuses. Ordinary card
transitions are blocked under cancelled or shipped orders. Order completion is
not a grading validation or an attestation that every card is completed. Review
the card list before advancing an order; no business release approval is implied.

For a status correction, enter an operator, a specific reason, select **Authorized
correction**, and submit the desired state. Authorization is denied by default.
An administrator may configure exact identifiers in
`selby_workstation/orders_authorization.json`:

```json
{"authorized_operators": ["APPROVED_SUPERVISOR"]}
```

Only explicitly authorized corrections can move between otherwise disallowed
states. They append `status_corrected` with complete before/after snapshots.
They never change identities or move cards between orders. This follows the
existing local allowlist convention; it is not authenticated role security.
Protect the configuration and database with deployment filesystem permissions.

## UI workflow

1. Open **Orders**. Enter operator identity. The main inspection operator is copied
   initially; registry changes do not change the inspection's operator.
2. Choose **New order / clear form**, enter customer/contact/reference/notes, then
   **Create order**. Name is required. Save the displayed order ID on the order bag
   through the existing manual process; this version generates no physical labels.
3. Set a count and optional description, then **Add cards**. Each individual gets
   its own permanent internal ID and position. Adding cards to other lifecycle
   states is refused rather than silently reopening the order.
4. Search order ID/customer by case-insensitive substring. Click an order to view
   its card table and fields; **Update selected customer** saves customer changes.
5. Click a card or enter its exact ID in **Find card**. Its complete record and
   audit history appear below. Direct card search opens its parent order as well.
6. Choose desired order/card state and submit using its separate status button.
   Invalid transitions show the existing workstation warning dialog. Use **Show
   order audit** to return the detail pane to order history.
7. Associate a saved grading dossier explicitly as described below. Session path,
   UUID, version, SHA and legacy label remain visible in the record. **Verify
   associated evidence** rechecks the saved version and its required evidence.

Audit events cover creation, customer edits, status/cancellation changes, authorized
corrections, session linking/version replacement, and unlink corrections. Operator
may be empty when unavailable for ordinary operations; association and corrections
require it. Histories survive restarts and include prior full records and reasons.

## Safe V0.4 association adapter

V0.4's dossier `working.card_id` is historically free text, not a persistent foreign
key. Rewriting it would alter saved grading evidence. V0.5a therefore stores an
external association only on the production card. No session is automatically
migrated, imported, modified, relinked, graded, or assigned a production ID.

Select a card, enter an operator and physical-pairing explanation, then **Associate
saved grading session…**. Only a saved session with a working V0.4 grading dossier
is accepted. `Session.reopen` verifies existing image/source/parent provenance and
grading invariants. The association pins absolute path, SHA-256, session UUID,
version UUID, original dossier label, and adapter mode. A dossier already declaring
another `SLB-C-…` identity is refused. Legacy labels remain unchanged; the explanation
attests the operator's explicit mapping. Software cannot prove physical pairing.

One session UUID may belong to only one card at a time, including across versions.
Replacing a link (even with a newer version) or unlinking requires an authorized
operator and reason. Use **Unlink (authorized correction)** for a mistaken pairing;
the prior mapping remains in audit. Linking the exact same version is refused as
a no-op. Later saved versions are never followed automatically. Verification fails
if the pinned session or required evidence changes/disappears. Read-only viewing
of a stored reference is not a fresh evidence verification.

The adapter accepts incomplete grading dossiers for traceability; association does
not validate the grade. Existing V0.4 manual review, policy pinning, overrides,
exports, and `automatic_acceptance=false` behavior remain authoritative and separate.
The certification field is reserved and constrained to NULL: no public number is
issued, inferred from the card ID, or added to exported grading reports.

## Migration, limits, and validation

Existing sessions require no schema migration. Existing inspection directories
are untouched. Opening Orders creates a new empty registry; an existing SQLite
schema 1 registry is reused. No backend/frontend commercial-service database or
research artifact is involved. This is an internal local vertical slice, not a
claim of production readiness.

Known limits: synchronous UI and evidence loading; no pagination; no authenticated
identity, signed/tamper-resistant audit, database encryption, cross-site ID service,
retention policy, automatic backup or card reassignment; no metadata edit UI beyond
batch description; no automatic order/card/grading state synchronization. Audit
snapshots retain customer information, so protect backups and access accordingly.
SQLite durability still depends on the local filesystem/storage honoring sync;
network shares, actual disk-full/power-loss behavior, and malicious file tampering
have not been certified. Use one authoritative local store and retain backups.

QR/barcodes, scanner input, printers, shipping APIs, payments, customer portals,
public certification, automatic grades, detection changes, and grading formula
changes are outside this increment. Actual tests and limitations of validation
are recorded in `SELBY_WORKSTATION_V05A_VALIDATION.md`.
