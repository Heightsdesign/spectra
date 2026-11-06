# SPECTRA W5.2a — Inspection operations

## Architecture and scope

`/admin/inspection` is a dynamic, server-authenticated staff workstation. Next.js
proxies the private FastAPI `/internal/inspection` namespace. It reuses the W2
verified-account session and W5.1 staff membership checks, W5.1c complete PC
references and scanner parser, shared admin language/navigation, and the existing
monochrome workspace and official logo components.

Repository inspection confirmed W4 payment evidence does not exist. W5.1 final
reconciliation and its administrator override are receiving controls. They do not
establish commercial or inspection authorization. This implementation reads those
records and never updates W5.1 inventory, discrepancy or audit history.

The implementation adds an inspection dossier and evidence children to the
existing physical identity. It does not create internal `cards` records or assign
the reserved `physical_cards.grading_card_id`. Submission and customer context are
derived from that physical card. Existing legacy card/image endpoints remain
unchanged and cannot enumerate or attach these inspection images.

No scores, measurements, grading algorithms, grading approval, certification,
slabs, encapsulation actions, payment processing or outbound shipping are added.

## Eligibility policy

`backend/app/inspection_eligibility.py` contains the policy shared by lookup,
start, pause, resume and image acquisition. Authentication and staff membership
are mandatory router dependencies and run before card lookup. The business
policy returns `eligible` and an array of `{code, en, fr}` explanations per
operation. A failed mutation returns HTTP 409 with that structured result.

| Reason | Rule |
| --- | --- |
| `intake_not_reconciled` | The submission must have an intake finalized as `reconciled`; absent, pending and held intake block |
| `association_invalid` | Card status must be `matched`; declared entry and parcel must both belong to the physical card's submission |
| `discrepancy_block` | A relevant open discrepancy, or an acknowledged remaining physical concern, blocks |
| `quote_not_accepted` | An immutable acceptance must exist and its quote must belong to this submission |
| `payment_unverified` | Trusted independent payment clearance is unavailable or unverified |
| `commercial_restriction` | Absence of commercial restrictions has not been independently established |
| `operation_conflict` | Dossier status/location is incompatible with the requested operation |

Discrepancy policy preserves W5.1 semantics: acknowledged means accepted for
receiving, not resolved for inspection. All acknowledged concerns about this
physical card (including damage, mismatch, unexpected and unresolved identity)
block it. Relevant open issues always block. A closed acknowledged `missing`
quantity concerns an absent object and does not block a different, correctly
matched physical card. Issues tied to a different physical card do not block this
card; issues without a physical-card scope are evaluated conservatively at
submission level. Resolved issues do not themselves block. Incorrect or uncertain
matches remain blocked independently of issue resolution.

The current operational holds are W5.1 `on_hold` intake and inspection `paused`
custody. Paused custody disallows image acquisition and requires an explicit
resume. There are no inferred exemptions or administrator overrides in inspection.
All actual mutations recheck the policy while holding the submission lock. Exact
command replays return existing state without performing another transition.

## Commercial authorization and W4 boundary

`inspection_commercial.py` defines the server-owned `CommercialProvider` contract
and immutable `CommercialEvidence`. The shipped provider always reports payment
and restriction clearance as unavailable. It reads no environment override,
payment header, request assertion, staff role or intake override. No HTTP endpoint
can set its evidence.

Consequently, **ordinary production inspections cannot start while W4 is absent**,
even with an accepted quote, final reconciliation, an administrator account and
an administrative receiving override. Acquisition, pause and resume also fail
closed when their required commercial clearance cannot be proven. Read-only
identity, dossier, custody history and protected original retrieval remain
available to authorized staff.

W4 must replace the unavailable provider with a trusted database-backed reader
scoped to the supplied accepted quote. It must establish the quote/submission,
currency, required amount, independently verified settlement, and absence of
refund, chargeback and processing restrictions. If payment is not required, W4
must supply an independently authorized exemption; zero price or quote acceptance
alone cannot prove one. Unknown requirements remain blocked. Provider failures
must never become approval. Payment and commercial-hold changes must serialize
on the same submission lock used by inspection, so evidence cannot be revoked
between eligibility evaluation and commit.

Payment webhooks and their verification, exemption administration and payment
storage are future W4 work. Tests use dependency-injected doubles only within
isolated test processes/schemas; accepted quotes remain actual persisted fixture
records. The tests do not add a production flag, special header or approval API.

## Database and migration

Alembic `0007_inspection.py` follows `0006` and contains frozen PostgreSQL DDL.

| Table | Stored information |
| --- | --- |
| `inspections` | UUID; unique physical-card FK; starting operator; status; controlled location; optimistic version; creation, start and transition timestamps |
| `inspection_custody_events` | Immutable inspection FK, actor, UTC timestamp, request UUID, action, previous/new states, source/destination, reason |
| `inspection_images` | Immutable inspection FK, front/back side, side version, uploading operator/time, original filename, detected MIME, SHA-256, byte size, generated storage key and reason |

One dossier per physical card prevents conflicting active dossiers, including
when paused. Submission and full PC reference are reliably derived through the
physical-card FK; custody responses include the complete reference and inspection
ID. Unique command keys per dossier and unique `(inspection, side, version)` image
versions provide database protection. Card-reference lookup uses W5.1's unique
reference index. Inspection-child indexes and a compound custody-history index
support dossier/history retrieval. Checks constrain lifecycle, status/location
pairs, custody transition/location pairs, image sides and positive versions/sizes.

Both new evidence tables have PostgreSQL statement triggers rejecting UPDATE,
DELETE and TRUNCATE. They reuse the immutable-audit trigger function installed by
0006 without changing its function or W5.1 trigger/events. Foreign keys retain
referenced actors, physical cards and dossiers. Protect database-owner credentials
and backups; privileged schema maintenance can still remove triggers/tables.

Upgrade from `backend` using the deployment's intended database configuration:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
```

The migration adds empty tables and indexes, with no staff/payment seeds or
historical rewrites. It has been exercised in the guarded test database and fresh
disposable schemas. It has **not** been applied to the development/production
database as part of this task. A downgrade removes only the new inspection tables;
it destroys their evidence and is a trusted maintenance operation, never a UI
action. No database reset is required or performed.

## State machine, custody and concurrency

| Explicit action | Source | Destination | Custody transfer |
| --- | --- | --- | --- |
| Start | No dossier (`not_started`) | `in_progress` | Secure intake storage → inspection workstation |
| Pause | `in_progress` | `paused` | Inspection workstation → inspection hold storage |
| Resume | `paused` | `in_progress` | Inspection hold storage → inspection workstation |

`not_started` is represented by absence of a dossier. Scanning creates no dossier
and no custody event. Before a first confirmed handover the UI explicitly reports
that inspection custody is unconfirmed. The operator must verify the full PC
identity and actually collect the card from the stated source before confirming
Start. The confirmation dialog identifies the PC and both transfer locations.

Pause/resume are confirmations of the coupled physical handover, not merely
screen toggles. Each action requires an operational reason. Destination locations
are selected by the controlled state graph, never supplied as arbitrary text.
Awaiting encapsulation is intentionally not a reachable location in W5.2a.

Lock order follows existing operations: authenticated actor, then submission
`FOR UPDATE`. Card association is refreshed after acquiring that lock. Dossier
uniqueness and the submission lock protect concurrent starts by different staff.
Every non-replayed command checks the expected dossier version (zero before
start); state changes and image acquisition increment it. State and custody event
commit in one transaction. Event timestamps are server-derived UTC transition
times, not scanner/device timestamps.

Clients retain a command UUID across an ambiguous retry while the current card
and command input remain unchanged. The same key/action/reason replays without a
new event; changing action/reason with that key returns `idempotency_conflict`.
Expected version is a precondition for a new transition, not a new mutation on a
replay. Different-key duplicate starts and stale commands return 409. Reloading or
looking up a card clears the in-memory pending command, so inspect current history
before retrying after navigation. Image uploads use optimistic version checks;
ambiguous upload retries cannot silently create another version with an old
dossier version. Refresh and review history before deliberately acquiring again.

## QR workflow and workstation procedures

1. Sign in as a verified, active staff member and open `/admin/inspection`.
2. Focus the reference input. Scan the unchanged `SP:PC:1:PC-<full UUID hex>` label
   with a keyboard-emulating QR reader, or paste the complete PC reference. Enter
   submits lookup; CR/LF suffixes are normalized by the existing W5.1c parser.
3. Verify the exact reference against the physical label and the declared card,
   submission and associated customer link. This link describes the account
   association, not a new legal ownership assertion.
4. Review eligibility and its FR/EN reasons. With W4 absent, stop at identification
   and review; staff cannot manufacture payment confirmation here.
5. When trusted commercial clearance eventually exists, enter a reason, choose
   Start and explicitly confirm the named card and physical handover.
6. Acquire front/back separately, checking the reference and side in each
   confirmation. Review presence and version history. Use Pause only when moving
   the card to inspection hold storage; Resume confirms its return.

The page keeps scanner input separate from mutations, prevents simultaneous UI
operations, restores scanner focus after requests, offers FR/EN language selection,
uses semantic labels/live feedback, wraps full references on narrow screens and
reuses existing accessible staff controls. Existing W5.1c lookup remains available
and unchanged. Neither physical scanner/printer validation nor calibration is
asserted by these software tests.

## Image integrity and replacement

Original validation and exclusive file writing reuse `cards.validate_image` and
`cards.write_original`. The backend checks a bounded base64 JSON payload, bounded
decoded size, filename, client-supplied SHA-256 against server calculation, and
actual PNG/JPEG/TIFF contents including full pixel/frame decoding. MIME/extensions
cannot establish image validity. Maximum original size is the lower of the
existing configured limit and 25 MiB; Next's proxy cap accommodates base64 overhead.

The URL physical card, dossier ID and expected dossier version must agree. No
endpoint imports an existing arbitrary image ID or accepts a grading-card ID.
Each side acquisition appends a new immutable version and requires a reason;
original bytes use a new generated storage key and exclusive creation. Prior
versions remain visible. Acquisition increments the dossier version so concurrent
uploads/transitions cannot silently attach stale evidence. The UI warns explicitly
that scanner calibration has not been validated.

Protected original retrieval requires staff authorization, verifies dossier/card
scope, and rechecks stored byte size and SHA-256 before returning any image. A
missing original returns 503; detected tampering returns 409. Storage keys and
filesystem paths are not returned. Read access does not imply permission to
perform a processing mutation.

Database and filesystem cannot share an atomic transaction. Ordinary storage or
commit errors roll back metadata and attempt cleanup of files created by that
request; existing files are never overwritten or deleted on collision. Failed
cleanup is logged without image content or account data. Crashes or ambiguous
commit failures still require trusted storage/metadata reconciliation and
coordinated backups. Protect originals from manual filesystem writes; SHA checks
detect alterations but do not replace storage permissions or an external ledger.

## Private API and security

| Method / path under `/internal/inspection` | Operation |
| --- | --- |
| GET `/lookup?reference=…` | Identity/context, per-operation eligibility, dossier, image versions and custody history |
| POST `/{PC}/command` | `{request_key, version, action: start/pause/resume, reason}` |
| POST `/{PC}/images` | `{inspection_id, version, side, filename, sha256, data: base64, reason}` |
| GET `/{PC}/images/{image_uuid}` | Verified, scoped private original |

Both existing staff roles (`admin`, `operator`) may use this workflow; neither
receives commercial privileges. Every endpoint checks the active verified session
and current staff membership on the backend. Every POST requires the configured
exact Origin, JSON, `X-Spectra-Client: 1` and session-bound CSRF token. Unknown fields,
control characters, malformed UUIDs and invalid payloads are rejected; optimistic
versions must be actual integers. Validation responses are redacted.

Responses, including errors, use `private, no-store`, `no-referrer` and `nosniff`.
Routes are excluded from public OpenAPI. No customer-facing custody endpoint or
navigation is introduced. QR and structured custody payloads contain opaque
operational identities, not account names, emails or addresses. Operators must not
enter customer PII in free-text reasons. There is no client-side-only authorization
and no inspection-specific login or scanner authentication.

## Exceptional cases and W5.2b handoff

- A blocked card stays blocked. Do not reuse an intake override, relabel a card or
  edit historical discrepancies to force eligibility. Escalate the underlying
  concern through the appropriate commercial/operational process.
- Finalized W5.1 remains read-only. New receiving corrections after finalization
  and independent pre-inspection hold administration are future workflows; this
  milestone does not unfreeze records.
- On stale state, identify the card again and review custody/image history before
  another explicit action. On uncertain physical handover, verify the object and
  history; another scan is not a custody receipt.
- On missing/tampered originals, stop acquisition/review and arrange trusted
  integrity investigation. Preserve all database evidence and backups.
- W5.2b should consume this physical identity, dossier UUID, versioned front/back
  evidence and custody graph. Any link to a legacy grading card must use the
  reserved unique physical-card relationship transactionally, with explicit
  migration/identity checks. No alternative physical identity should be created.
- Further completion/approval states, calibration evidence, measurements, scoring,
  encapsulation handoff, pagination/retention for very long histories and payment
  integration require separately authorized milestones. None is simulated here.

## Changed files

Backend additions: `inspection.py`, `inspection_eligibility.py`,
`inspection_commercial.py`, `inspection_models.py`, migration
`0007_inspection.py`, and `tests/test_inspection.py`. Router/security integration
changes are limited to `main.py` and Alembic model registration in `env.py`.

Frontend additions: `/admin/inspection/page.tsx`, `inspection-workstation.tsx`,
`lib/inspection.ts`, unit/request tests, `inspection-browser.mjs` and
`run-inspection-integration.py`. Existing changes are the inspection navigation
link, proxy/body-size configuration, a browser-test script and scoped workspace
styles. `README.md` links to this document. Official V2 assets are unchanged by
this implementation; the pre-existing modified PSD working-tree file was retained.

## Validation

Executed on 2026-10-17:

| Check | Exact final result |
| --- | --- |
| Full backend suite | `338 passed, 22 warnings in 53.22s`, exit 0 |
| Full frontend unit/request suite | 59 passed, 0 failed/cancelled/skipped, `1017.067 ms`, exit 0 |
| ESLint | Exit 0 with `--max-warnings=0` |
| TypeScript | `tsc --noEmit`, exit 0 |
| Production build | Exit 0; `/admin/inspection` is a dynamic route; normal default backend URL restored in the final build |
| Inspection browser integration | 4 passed, exit 0: FR/EN × 1440×1000 desktop / 390×844 mobile |
| Real production HTTP integration | 1 passed, exit 0: actual Next/FastAPI proxy and PostgreSQL in a fresh disposable schema |
| Python compilation | `compileall -q backend/app frontend/tests/run-inspection-integration.py`, exit 0 |
| Whitespace | `git diff --check`, exit 0; existing LF/CRLF notices only |

Backend tests cover pending/final/held intake; missing, foreign and questionable
physical associations; acknowledged/resolved concerns; missing commercial evidence;
accepted quote without payment; intake override without inspection authorization;
both staff roles; absent/non-staff/unverified access; Origin/CSRF and forged payment
assertions; duplicate/replayed starts; real independent-connection concurrent starts;
pause/resume and custody order; immutable UPDATE/DELETE/TRUNCATE behavior; QR
suffixes; front/back acquisition and replacement; invalid/oversized images and
filenames; wrong dossier and cross-card reads; SHA mismatch and tampering detection.
The full suite retains all prior milestone tests. The HTTP test additionally
compares finalized W5.1 detail before and after inspection operations.

Frontend request tests exercise scanner normalization, uncached reads, CSRF/version/
request-key transport, localized structured rejection and expired sessions. Chrome
tests operate the final production build with synthetic UI fixtures, exercise
Enter scanner input, verify scan/cancel do not mutate, confirm Start and custody
handovers, acquire front/back files, check status/history and both languages, and
assert semantic labels, one main landmark and no page-level horizontal overflow.
Screenshots were generated under ignored `.visual-review/inspection/`; desktop
and mobile samples were visually inspected. Browser fixtures do not test actual
scanner hardware or provide production authorization. The separate HTTP runner
uses real PNG bytes and backend validation.

Commands from `backend`:

```powershell
.venv/Scripts/python.exe -m pytest tests -q --basetemp test_tmp_w52a_final_verified
```

Commands from `frontend`:

```powershell
npm.cmd test
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
npm.cmd run test:inspection-browser
```

Chrome must be installed at the runner's default Windows path or supplied using
`CHROME_PATH`. In this managed environment Chrome's debugging service could not
start inside the sandbox; the successful browser runs used approved execution
outside it. The runner binds only its dedicated loopback ports 18191–18193.

For the production HTTP test, run this dedicated-port build from `frontend`:

```powershell
$env:SPECTRA_BACKEND_URL='http://127.0.0.1:18194'
npm.cmd run build
Remove-Item Env:SPECTRA_BACKEND_URL
```

Then, from the repository root:

```powershell
backend/.venv/Scripts/python.exe frontend/tests/run-inspection-integration.py
```

Finally rebuild from `frontend` with the normal deployment backend URL. The final
build in this task uses the repository default `http://127.0.0.1:8000`. Dedicated
ports were chosen because an existing server occupied 8000; that server was left
running. The HTTP runner requires a separate PostgreSQL database ending `_test`,
creates a uniquely named schema, migrates it to head, and removes only that schema
and its temporary evidence afterward. Run database suites and HTTP integration
sequentially because existing pricing tests publish isolated test catalogs.

Observed non-failing warnings: the existing Starlette/httpx deprecation, Alembic
`path_separator` deprecation, Node's experimental type stripping, Next's ignored
parent-directory lockfile, and the documented experimental proxy body-size option.
There is no configured separate Python lint command; Python compilation and the
full backend suite were run. An earlier exploratory backend run had one failure
in the existing randomized physical-label QR decoder test (empty decoded payload;
331 other tests passed). Label generation was not changed; subsequent complete
runs passed, including the final 338-test run. Physical print/read validation
remains outstanding.
