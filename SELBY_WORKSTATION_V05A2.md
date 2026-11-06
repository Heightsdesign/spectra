# SELBY Workstation V0.5a.2 — Authenticated Incoming Submissions

Incoming Submissions adds an in-memory, read-only view of the existing FastAPI staff intake API to the unified PySide6 desktop. Launch normally with `scanner_agent/Launch_SELBY.vbs` or the existing desktop entry point; choose **Incoming Submissions** in the sidebar (Ctrl+6). The existing Ctrl+1–5 assignments remain unchanged.

## Architecture and audit

The mandatory [integration audit](SELBY_V05A2_INTEGRATION_AUDIT.md) and actual routes/authentication/navigation/persistence/tests were inspected before edits. No repository `AGENTS.md` was found. Existing staged, unstaged and untracked files were preserved; no research, grading policies or evidence sources were edited. No database migrations or new backend were introduced.

`scanner_agent/selby_workstation/incoming.py` is a standard-library HTTP client restricted to these existing GET routes:

- `/internal/intake/me`: verify an active, verified operator/admin session.
- `/internal/intake/submissions?search=...&offset=...&limit=50`: submitted declarations only, bounded pagination and server reference search.
- `/internal/intake/submissions/{submission_uuid}`: declared entries, received physical cards, parcels, discrepancies and intake summary.

`incoming_ui.py` performs network operations in Qt's global thread pool and receives queued results on the UI thread. Bounded socket timeouts and response sizes prevent indefinite ordinary network waits or unbounded response allocation. Disconnect invalidates pending results; accepted desktop close clears the preview session. No background auto-refresh or disk cache exists. A request already in flight can finish after disconnect, but its result cannot reconnect or repopulate the page. Socket timeout is not a total wall-clock deadline for a server that continuously trickles bytes.

`desktop.py` hosts the new page. `app.py` clears it on accepted close. The feature does not instantiate `OrderStore`, allocate IDs, inspect local mappings, touch saved sessions, request labels, or call mutation endpoints. SQLite schema version 1 and existing ORD/SLB-C identities are unchanged. No dependencies were added.

## Configuration and authentication

1. Ensure the existing FastAPI deployment is running with its existing migrations provisioned by its administrator. This feature does not provision or migrate it.
2. Sign in to the existing portal using an active, verified account that already has an operator/admin staff membership. Account creation or membership changes are outside this feature.
3. In that browser's developer tools, open the site's application/storage cookies and locate the current session cookie. Production uses `__Host-spectra_session`; development uses `spectra_session`. Copy only its value. It is a secret with the account's session authority; do not share it, put it in notes, or include it in screenshots/logs. No browser files are read automatically.
4. In Incoming Submissions, enter the **FastAPI backend origin**, without an API path. Default local development address is `http://127.0.0.1:8000`. The API must accept the session issued by the portal's backend. An unrelated environment or separately configured session database will not authenticate it.
5. Select the exact cookie name and paste its value into the masked **Operator session value (not password)** field. Click **Connect**. For default local development, select `spectra_session` explicitly. HTTPS is required for production cookies and every non-loopback connection; TLS verification stays enabled. HTTP is allowed only for literal loopback IPs or exact `localhost`.

Only existing session-cookie authentication is reused. There is no new token issuer, password storage, browser scraping, or customer-frontend credential configuration. The input clears when submitted; the session is retained only in process memory until disconnect, expiry/authorization rejection, close, or process exit. It is never written to QSettings, the registry, documents or logs. The client disables redirects and ambient proxies to avoid forwarding the credential unexpectedly; deployments requiring a proxy need a separately reviewed configuration.

The backend's existing authentication helper checks the cookie hash, expiry, revocation, verified/active account and staff membership on every GET. GET does not require Origin/CSRF headers. All requests issued by this feature are GET, including connection and disconnect (disconnect actually makes no request). Password sign-in would require POST, so it is intentionally performed in the existing portal. Server sign-out/revocation remains in the portal; disconnect only forgets the workstation's copy. Clear your clipboard after entering the session. Do not paste a password into this field.

## Workflow and meaning of records

Connect, search by full or partial `SP-…` reference, select a row, and use **Search / refresh** to fetch current information. Previous/Next controls page through 50 records at a time. Refresh returns to the first page and refreshes the selected detail if it remains on that page. List and detail requests are separate snapshots, not an atomic synchronized view.

| Display | Meaning |
| --- | --- |
| SP reference / submission UUID | Confirmed customer declaration; not proof of physical receipt, paid order or processing authorization |
| Expected cards / entry UUID | Original customer description and declared quantity; one entry can describe multiple copies |
| Received cards / PC reference / physical UUID | Actual centrally registered individual physical objects and their parcel/entry association |
| Match status | Backend physical-card match state, separate from overall reconciliation |
| Intake/reconciliation status | Existing central state such as awaiting receipt, reconciliation pending, reconciled or on hold |
| Parcels and discrepancies | Existing receiving records and missing/extra/mismatch/damage concerns; displayed without alteration |
| Backend grading-card UUID | Existing nullable link to the legacy backend card table; it is not a desktop SLB-C identity |
| Local production link | Unavailable: there is no durable portal-to-registry mapping in this version; no inference from names/free-text references |

An empty page reports no matching submitted submissions. During loading, the preview controls are disabled while the other desktop modules remain usable. Connection failures and backend errors clear displayed remote data and show a safe message; refresh can retry an existing connection. Invalid/expired sessions and lost staff access clear the session and require reconnecting. A fresh existing session must be pasted after failed initial connection because it is not persisted.

## Limitations and next step

No live production account/database, native visual review, deployed TLS endpoint, payment evidence, physical receiving, actual scanner or printer was exercised during implementation. Automated tests use real local HTTP with contract fixtures, offscreen Qt, and the actual FastAPI routes/auth helper with an isolated database double. They do not establish complete end-to-end intake. See [validation](SELBY_WORKSTATION_V05A2_VALIDATION.md) for exact results and boundaries.

This version neither evaluates nor bypasses inspection/payment policy. Commercial acceptance and the backend's `not_implemented` payment status are displayed as returned; there is no production-ready claim. Existing local-only inspection and grading continue independently when the backend is unavailable.

Expected units are not expanded into synthetic physical cards. Offset pagination may shift while other staff change the queue; use search and refresh before decisions. There is no incremental synchronization or offline cache. No local production association can be verified in this preview.

Next: review the audit's durable import design and explicitly authorize a minimal additive mapping/journal schema and atomic import service. Define backend/environment and registry identities, duplicate prevention, physical-card ownership, crash recovery, operator-confirmed links to existing orders, and central reconciliation rules before implementing any import. Preserve all existing ORD/SLB-C identities and immutable evidence; do not introduce a new backend or silently apply migrations.
