# SELBY Workstation V0.5a.6 — void erroneous physical registration

## Audit and smallest additive design

Audited `intake.py`, intake models/migration 0006, discrepancies, immutable intake audit, production bridge models/migration 0011 and local SQLite registry/session associations, inspection/eligibility/custody/image models, label resolution and customer-copy return handling. Existing writes serialize on the confirmed submission; inspection, production and return operations share that lock. Backend `grading_card_id` is a separate UUID FK. Label generation had no issuance ledger. Local production IDs and saved grading sessions remain separate from intake.

The original PC row can remain entirely unchanged. Alembic **0012** adds `physical_card_voids`: PC UUID primary/FK, authenticated actor FK, nonempty reason (up to 1000 characters), server timestamp. There is no backfill, deletion, reuse, status-check rewrite or SQLite migration. A PostgreSQL statement trigger rejects UPDATE, DELETE and TRUNCATE using the existing immutable-audit function. Downgrade refuses when void history exists. The existing immutable intake audit receives `physical_card_voided` in the same transaction as the void fact.

Historical registration fields (`status`, original timestamps, parcel, request key/data, notes and associations) are retained. API lifecycle `status` becomes `voided` when the immutable void fact exists; `registration_status` preserves the original status. This avoids changing the historical meaning of physical registration and preserves every existing PC ID/FK and production uniqueness constraint.

## API, authorization and safety policy

`POST /internal/intake/submissions/{sid}/cards/{cid}/void` accepts **only** `{ "reason": "..." }` and returns fresh complete intake detail. Existing authentication, active verified session, operator/admin membership, JSON, configured Origin/client header and CSRF enforcement apply. A local operator name is not authorization. Blank/invalid reasons fail validation. Wrong-submission/missing PCs return 404. No terminal correction override is provided, including for administrators.

New voids require **reconciliation_pending** and a current **unidentified** PC with no declared-entry association. Any of the following blocks void:

- A matched/questionable card, or historical match/custody audit evidence even after unmatching.
- Backend grading UUID link.
- Any inspection dossier, including its transitively associated custody/images.
- Any discrepancy associated with this PC, including resolved/acknowledged history.
- Any submission production reservation or PC production mapping, including a reservation whose local confirmation is still pending.
- Another relevant intake audit record identified by the PC entity UUID or `data.physical_card_id`, other than its initial creation event.
- Reconciled, held, partial or awaiting-receipt state.

The endpoint first authorizes and locks the confirmed submission, scopes the PC, then locks/refreshes that card. It checks existing void before eligibility. A repeated void is a safe no-op even after later reconciliation: the original actor, reason and timestamp remain, with no duplicate audit event. A changed retry reason cannot overwrite the historical reason. The PC UUID itself is the irreversible operation's idempotency key. Two actors racing void/match share the same submission lock; either match wins and void rejects, or void wins and match rejects. Simultaneous voids return one fact/event.

The backend is authoritative; GUI eligibility is only a display aid. `void_eligible`, `void_blockers`, immutable void actor/reason/time and historical registration status are included per PC in intake detail. Eligibility is rechecked during POST, so a stale UI cannot bypass new links/state.

## Active inventory and downstream guards

An active PC has **no row in `physical_card_voids`**. Intake summary received counts, match-capacity checks and reconciliation validation use this predicate. The Workstation computes matched/unidentified quantities from the active subset of the authoritative detail, while retaining all PCs in its inventory history. Missing declarations remain governed by the existing quantity policy; actual unexpected objects still require explicit discrepancies. A voided registration represents no object and requires no unexpected-card discrepancy. No declaration/customer snapshot is edited.

Matching/unmatching and creation of discrepancies against a voided PC return `card_voided`. Production snapshots contain active `cards` plus separate historical `voided_cards`; reservation/confirmation manifests include only the active set. The local importer defensively rejects voided identities in an active manifest. No ORD/SLB-C or grading session link is modified by void. Production reservations themselves prevent void, including before remote confirmation, so a pending local import cannot be silently invalidated.

Inspection eligibility explicitly reports `card_voided` for every operation, including start, pause, resume and images. Lookup remains available for historical tracing and identifies the lifecycle. Customer-operations lookup also reports `voided`. Existing grading UUID links block void; no new backend grading association is created. The bridge cannot allocate an SLB-C for a voided PC. Legacy offline free-text session identifiers are not backend custody or grading authorization; no grading evidence is rewritten.

Existing single/batch PDF label endpoints reject a request containing a voided PC rather than generating an active label. Label lookup now locks involved submissions in deterministic order before checking lifecycle, serializing generation checks with void. This adds no workstation printing feature. Previously generated external PDFs/physical labels cannot be recalled, and there is no historical label-issuance ledger to inspect. New label requests are blocked after void.

## Workstation workflow and recovery

Select an exact **active PC** from Received physical card. A plain-text summary displays its full reference, match/entry association, lifecycle and backend void eligibility/blockers. **Void erroneous registration** is shown only for a backend-eligible selection. A reason is required and the confirmation repeats the complete PC reference, reason and the assertion that **no physical object exists**. Success reloads authoritative detail in the existing Qt worker.

History retains the full PC reference with **VOIDED** and reason, plus the immutable audit event. Voided PCs are absent from all active selectors. After voiding the selected PC, selection is cleared; another legitimate PC is never silently selected for a subsequent operation. The existing wheel-safe widgets and consequential-operation confirmations remain in effect.

The existing technical journal persists void target/reason before POST. Lost-response recovery can replay the exact void after restart without another event. Retry requires a fresh read containing the target, and confirmation repeats the preserved full PC and reason. A rejected/stale void can use the existing explicit fresh-audit review to clear its local intent; that does not undo a backend void. No offline receipt/void success is fabricated, and all HTTP remains outside the UI thread. There is no unvoid action.

## Exact manual acceptance — existing dedicated development test order

**That order was not mutated during implementation or tests.** First complete the separately authorized backend rollout/backup and migration **0012**, then restart the backend and Workstation V0.5a.6. Validation has applied migrations only to the guarded test database/disposable schemas, not the existing development-order database.

1. Sign in with an authorized staff account. Open Incoming Orders and select the existing dedicated development test order by its **SP reference**. Choose **Start / resume reception…** and refresh. Confirm this is the intended order, declared quantity 2, received quantity 3 and reconciliation still in progress.
2. Review all three full PC references. Physically verify the two legitimate cards remain matched to the intended declared entries. Record those two references for comparison. Confirm that the third PC is unidentified and represents only the accidental extra click, with **no third object received**. Do not use void for an actual unexpected card.
3. Select **only that third PC** in Received physical card. Read its full PC reference and lifecycle/entry summary. The selected entry must be unidentified and backend void eligibility must say eligible. If blocked or the button is absent, stop and review its history; do not unmatch or unlink anything to force eligibility.
4. Enter a concrete reason, for example: `Accidental extra registration click during intake testing. Only the two declared physical objects were received; this PC represents no physical object.` Click **Void erroneous registration**. Compare the **full PC reference in confirmation** with the recorded accidental PC. Confirm only if it matches.
5. After the authoritative refresh, verify **Declared 2 / Received 2 / Matched 2 / Unidentified 0**. Verify both legitimate PC references and their declared-entry matches are unchanged. The accidental PC must be absent from the active card selector, which should now have no selection. Its historical row must remain **VOIDED** with the reason. Review `physical_card_voided` in the audit, including entity UUID, actor and time; the original creation event must remain.
6. Refresh or close/reopen the order and verify the same counts/history. If a network interruption occurred, refresh and use **Retry preserved receipt / void request — same identity**, verify its full target/reason, and confirm. Do not register another copy or delete the journal.
7. Enter an explicit completion reason and click **Complete reconciliation**. Confirm. The backend must permit it; no unexpected discrepancy should be needed for the voided registration. If any genuine discrepancy remains, handle that through existing reconciliation actions.
8. Reopen the order after reconciliation and verify history/counts persist. Open **Prepare / reopen production order…**, verify its active PC list contains **only the two recorded legitimate references**, and prepare with the existing bridge confirmation/reason. Check the resulting ORD has exactly those two PC→SLB-C pairs. The voided PC must have no production identity. Existing unverified-order/adoption conflicts still require the bridge's explicit review procedure.
9. Verify payment and inspection eligibility remain independently displayed/restricted. Reconciliation/production identity preparation does not grant payment or grading clearance.

## Migration, files and limits

No deployment, existing development-order update, production-data change, local production-registry migration, protected-research edit or grading-evidence rewrite was performed. Normal PostgreSQL backup/review is required before an authorized rollout. New files: `backend/app/intake_voids.py`, migration `0012_physical_card_voids.py`, `backend/tests/test_workstation_v05a6.py`, `test_void_concurrency.py`, `scanner_agent/tests/test_intake_void_gui.py`, and the two V0.5a.6 reports. Modified: intake counters/detail/actions, production active manifest, inspection eligibility/lookup, label lifecycle checks, customer-operations lifecycle lookup, Alembic model import, desktop custody client/journal/intake UI, defensive local bridge validation and version titles.

This is deliberately a narrow pre-reconciliation correction. There is no deletion, reactivation, matched-card void, discrepancy-history erasure, production unmapping, reservation release, terminal correction or automatic repair. Determining whether a physical object exists is the operator's explicit verified assertion. See [validation](SELBY_WORKSTATION_V05A6_VALIDATION.md) for executed evidence and limits.
