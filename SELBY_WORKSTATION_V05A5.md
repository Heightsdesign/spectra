# SELBY Workstation V0.5a.5 — production identity bridge

## Architecture proposed before schema edits

Use additive PostgreSQL reservation/mapping tables plus additive tables in the existing SQLite order registry. A persistent UUID identifies the registry, not the machine/user/path. Backend submission ownership prevents two independent registries assigning different ORD identities to one SP. Local transactional allocation preserves existing ORD/SLB-C sequences. Neither backend `cards.id` nor `PhysicalCard.grading_card_id` is a local SLB-C namespace; both remain untouched.

Protocol: authenticated authoritative read; explicit conflict review; reserve SP for registry; atomic local identities/mappings/audit in `BEGIN IMMEDIATE`; confirm exact IDs to backend; mark local mapping confirmed. Retrying any stage reuses the same identities. A failure can leave a reservation or pending confirmation, never a successful-looking alternate mapping. A backend-confirmed mapping missing from SQLite requires registry restoration, not new allocation.

Authorization: existing active verified staff session and CSRF/Origin checks on every backend mutation. Operators/admins may create; only backend admins may reserve or confirm adoption. All mutations require a reason. Adoption explicitly supplies every physical UUID and local card ID, checks parentage/uniqueness, and never alters session links. Unmapped existing orders are reported as unverified records, without name/reference heuristics; creating a distinct order requires explicit acknowledgement.

Eligibility: confirmed submitted SP, reconciled intake, successful existing quantity reconciliation validation, at least one received card, every PC matched to an entry in this submission and parcel in this submission, no unresolved/acknowledged nonmissing concern, no pre-existing backend grading UUID requiring separate identity review, and no returned customer copy. Acknowledged missing quantities can remain; no SLB-C is allocated for absent objects. Preparation does not assert payment or authorize grading/inspection. Current backend inspection eligibility is returned separately.

Migration/backup: PostgreSQL Alembic 0011 adds tables/constraints/triggers without backfill or historical edits. SQLite schema v1 becomes v2 only when bridge use is explicitly invoked, after an online SQLite backup while writers are excluded. Ordinary registry reads preserve v1. Immutable bridge identities and append-only audit survive restart. No deployed database, existing local production registry, protected research artifact or grading evidence is to be modified during validation.

## Delivered schema and mapping contract

All identifiers are preserved in their original namespaces. The bridge keys are full submission/physical-card UUIDs plus the configured backend origin in SQLite, and an immutable registry UUID. Display names, customer names, entry names, list positions and `external_reference` never establish identity. A card position is allocated for local display only, after the PC identity is already known.

| Database | Table | Constraints and meaning |
| --- | --- | --- |
| PostgreSQL | `production_orders` | Submission UUID primary key; registry UUID owner; immutable `create`/`adopt` mode; nullable local ORD until confirmation; unique `(registry_id, local_order_id)`; actor, reason and timestamp |
| PostgreSQL | `production_cards` | PC UUID primary key; unique `(registry_id, local_card_id)`; composite FK to submission/registry reservation and PC/submission, preventing cross-submission pairs |
| SQLite v2 | `bridge_registry` | Exactly one immutable UUID, retained when the file is moved or restored |
| SQLite v2 | `bridge_orders` | Primary key `(scope, sid)`; unique ORD FK; immutable SP reference/mode/order; monotonic confirmation flag |
| SQLite v2 | `bridge_cards` | Primary key `(scope, pc_id)`; unique `(scope, pc)` reference; unique SLB-C FK; composite FKs to the mapped ORD and `(cards.id, cards.order_id)` enforce parentage |

The PostgreSQL migration adds `UNIQUE(id, submission_id)` to physical cards as the composite FK target. It adds no assignments to existing PC, SP or grading rows. Triggers reject bridge identity changes/deletion and PostgreSQL truncation. The existing immutable intake audit records `production_reserved` and `production_confirmed`; exact replays append no duplicate events. Local append-only audit records creation/adoption, each PC pairing and backend confirmation in the same SQLite transaction as each local state change. Existing local creation/session audit remains intact.

This is a recoverable multi-stage protocol, not a distributed ACID transaction. The visible states are unmapped, reserved, pending confirmation, confirmed and conflict. `Prepare order for production` must obtain a fresh backend snapshot on every invocation. The reservation serializes on the existing submission row lock, including across independent authenticated actors. `BEGIN IMMEDIATE`, SQLite uniqueness and the existing sequence allocation serialize local imports. New orders use `received`; cards use `registered`, with no automatic inspection/grading transitions. Repeated preparation of an existing mapping returns its IDs and does not append duplicate identity events. Manual Add cards is rejected for bridge-owned orders; intake remains the inventory authority.

## API and security contract

All bridge routes use the existing `/internal/intake` router, staff/session validation and private/no-store response middleware:

| Method and route under `/internal/intake/submissions/{sid}` | Contract |
| --- | --- |
| GET `/production` | Fresh declaration/intake detail, authenticated actor role, preparation eligibility/reason codes, independent inspection-start eligibility per PC, and current registry binding/pairs |
| POST `/production/reserve` | `registry_id`, `mode` (`create`/`adopt`), required reason; creates one durable registry ownership reservation or replays the same owner/mode |
| POST `/production/confirm` | `registry_id`, `local_order_id`, complete `cards` list of `{physical_card_id, local_card_id}`, required reason; atomically confirms exactly one full manifest or returns the unchanged identical confirmation |

Existing APIs reused: login/logout and `/api/auth/csrf`, plus the intake staff/session and CSRF transport. Existing intake `detail`, `validate_complete`, row lock and immutable audit functions are reused in the new endpoints. The server's existing inspection eligibility/commercial provider is evaluated directly, including current dossier state. No label or inspection mutation endpoint is called.

Every write requires an active, email-verified customer session, current staff membership (`operator` or `admin`), JSON, configured Origin, client header and matching CSRF. Adoption reservation **and** remote confirmation require the current backend administrator role; the desktop text operator field and local correction allowlist cannot grant that role. A registry UUID is an identity, not a credential. A different registry gets a conflict even if its user is an administrator. Confirmation rejects missing/extra/duplicate PC identities, duplicate SLB-C values, wrong owners, different previously confirmed IDs and uniqueness conflicts. All such failures retain the existing mapping.

Preparation is identity allocation only. It requires a submitted SP, `reconciled` intake, existing reconciliation quantity checks, at least one received PC, valid matched declaration/parcel associations, no returned-copy restriction, no open or acknowledged nonmissing concern, and no existing backend `grading_card_id`. The latter requires a separate reviewed backend-grading/local-grading identity procedure. Acknowledged missing quantities are permitted, but only actually received, verified PCs receive local IDs. Unknown/unexpected cards and uncertain exceptions block the whole preparation. Quote acceptance/payment are displayed separately and are not bypassed or asserted by this operation. The current payment provider remains unavailable, so inspection still reports `payment_unverified` even after successful preparation.

## Operator procedure and existing data

Select the confirmed Incoming Order and choose **Prepare / reopen production order…**. Review the SP, reconciliation, registry and PC list. Enter a decision reason, choose **Prepare order for production**, and confirm the consequential operation. The screen shows the resulting ORD and each PC/SLB-C pair, mapping state and current inspection-start reasons. **Reopen mapped order in local Orders** is enabled only when the local and backend confirmed identities agree. Local Orders shows SP/ORD and PC/SLB-C references; its offline display explicitly requests an online refresh for current reconciliation/payment/inspection status.

If any local order lacks a bridge mapping, preparation reports **all unverified order IDs**, without guessing candidates from names or external references. Review those records in Orders. Either explicitly acknowledge that the incoming order is distinct, or select administrator adoption and enter the exact existing ORD plus a JSON object mapping **each full PC UUID** to the verified existing SLB-C. The UI displays PC references with their full UUIDs for this purpose. Every received PC and every local card in the adopted ORD must occur exactly once. A wrong-parent, already-mapped, cancelled card, cancelled/shipped order, duplicate pair or incomplete plan is rejected. Existing customer metadata, statuses and saved session associations are not overwritten on adoption. The physical/dossier pairing is an operator verification recorded with their backend actor UUID and reason.

The interface explicitly confirms preparation/adoption; empty reasons and duplicate JSON keys are rejected. Network, migration, backup and import operations run in Qt workers. Escape/window close wait for bounded requests. Session/permission failures clear protected detail. Freshly loaded mapping conflicts disable preparation and reopening and display the restoration/review action; there is no silent repair or reallocation.

## Migration, backup and interrupted work

Alembic `0011` is additive and follows `0010`; deploy it only through the normal authorized database procedure after a PostgreSQL backup. No deployment or development/production database migration was performed here; validation migrations run only on the guarded `_test` database and disposable schemas. Downgrade refuses to discard any existing reservation/mapping. No existing historical reconciliation/declaration is backfilled or rewritten.

Opening the explicit bridge action upgrades the selected local registry to v2 in a worker. It first excludes writers and creates an online SQLite backup named `<registry>.v1-<UUID>.bak`, validates its integrity, then commits additive bridge DDL/registry UUID atomically. Failures roll back the schema change. Current `OrderStore` recognizes v2 without resetting the version; older workstation versions must be closed before use. The original v1 backup is retained.

After local identity commit and **before** remote confirmation, a consistent `<registry>.bridge-recovery.bak` is created via a uniquely named temporary SQLite backup and atomic replacement, with writers excluded. It includes registry UUID, existing session links, allocated identities and pending mappings. Confirmation is not sent if this backup fails. After local confirmation the recovery backup is refreshed. Protect these files as customer registry data, and keep normal off-device backups; the adjacent recovery file does not protect against loss of the entire disk. This backup is a registry snapshot, not a copy/edit of grading evidence files, and is refreshed by preparation rather than by later unrelated registry edits.

| Interruption | Recovery |
| --- | --- |
| Before reservation | Retry; no identities allocated |
| Reservation committed, reply lost | Same registry/mode reuses reservation |
| During local identity/audit transaction | All local inserts/sequence updates roll back together; retry |
| After local commit or backup, before backend confirmation | Pending IDs are reused, never replaced |
| Backend confirmation committed, reply/read lost | Fresh GET finds exact IDs; local confirmation completes without a second backend mapping event |
| Local final confirmation/backup fails | Original mapping remains; retry confirmation/backup |
| Backend confirmed but local rows missing/different | Stop and restore/review the original registry; no automatic ID allocation |

Reservations have no expiry, automatic release, registry reassignment or mode-change action. A mistaken reservation is retained for trusted diagnosis rather than silently transferred. After reserving adoption but before local commit, retry must supply the original explicitly verified adoption plan. After local commit the persisted plan is reused. Conflicts never unlink grading sessions or overwrite mappings.

## Files and remaining limits

New files: `backend/app/production.py`, `production_models.py`, `backend/alembic/versions/0011_production_bridge.py`; `scanner_agent/selby_workstation/production.py`, `production_ui.py`; `backend/tests/test_workstation_v05a5.py`, `test_production_concurrency.py`; `scanner_agent/tests/test_production_bridge.py`, `test_production_bridge_gui.py`; this report and its validation report. Existing files changed: backend `app/main.py`, `app/intake_models.py`, `alembic/env.py`; workstation `orders.py`, `orders_ui.py`, `incoming_ui.py`, `intake_client.py`, `app.py`, `desktop.py`, `__main__.py`.

One writable copy of a registry is supported. SQLite locks coordinate clients of the same file, and the server rejects other registry UUIDs. Do not run divergent writable copies of the same registry UUID; conflict checks detect differing confirmed IDs but this release is not a replicated registry service. Registry moves/restores retain the UUID. Keep the configured backend origin stable; alias changes require review, not heuristic remapping. Server reservation transfer and adoption of subsets of a local order are outside this slice. No printing, labels, QR scanning or grading-evidence changes were implemented. Native integration uses synthetic local test fixtures and does not constitute manual physical-card acceptance or production deployment. See [validation](SELBY_WORKSTATION_V05A5_VALIDATION.md).
