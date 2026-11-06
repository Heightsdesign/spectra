# SELBY Workstation V0.5a.3

## Scope and audit

Incoming Orders now has operator sign-in, automatic recent-order loading, customer/reference search, pagination, details and private customer-photo preview. Local workstation modules remain usable without a network connection. This is a read-only business-data preview, not receipt, import, reconciliation, payment clearance or inspection authorization.

The audited backend has first-party email/password sessions in `CustomerSession`, existing password hashing, login throttling, verified/active account checks, Origin/client-header checks and CSRF-protected logout. Staff authorization is a database `StaffMembership` check on every internal intake request; supported roles are operator/admin. There is no OAuth/OIDC authorization endpoint, native client registration, PKCE exchange or refresh-token service. Existing intake list/detail/photo routes and the bounded, GET-only desktop preview client were reused. The list previously searched references only. Existing Windows startup uses `Launch_SELBY.vbs`, `selby_desktop.pyw` and the installed workstation virtual environment.

The working tree contained substantial prior changes, including staged changes and research files. These were preserved. No new database schema, migration, role, catalog, storage service or production deployment was introduced.

## Authentication architecture and rationale

The smallest compatible implementation uses the backend's existing first-party HTTPS login directly from the trusted native application. The operator enters email/password in a masked desktop form. The password is sent only in the login request body, is cleared from the form immediately, and is never persisted or intentionally logged. Native process memory is not guaranteed to erase Python strings immediately.

The backend issues its existing HttpOnly session cookie to the native client's own cookie jar. This is not browser-cookie extraction, a new token scheme, or the OAuth resource-owner-password grant. Redirects and ambient proxy discovery are disabled; ordinary TLS certificate validation is retained. Production configuration requires HTTPS for both origins. Cookie format, expiry and production Secure/host-only requirements are checked. The client verifies staff authorization before exposing Incoming data or retaining the credential. Nonstaff accounts cannot enter preview, and their newly issued session is revoked.

Only the session record is saved, using current-user Windows Credential Manager generic credentials with local-machine persistence, scoped by a hash of environment/backend/portal origins. Passwords, session values and customer data are not saved in `desktop.ini` or local order SQLite. There is no plaintext fallback. Non-Windows secure login is unsupported in this version; offline local tools still work. See [Microsoft Credential Manager API](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew) and [credential persistence](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw).

Startup restores a saved session only after a fresh server-side staff check. Expiry requires sign-in again; there is no refresh mechanism. Explicit sign-out uses the existing CSRF/logout endpoints to revoke the session and deletes the saved credential. Closing the application detaches the view while retaining a valid credential for the next launch. A canceled in-flight login does not populate the UI and an issued session is revoked when possible.

Offline sign-out immediately clears displayed data and marks the credential as pending revocation in secure storage. That credential is never resumed for preview. The next restore/retry attempts revocation before allowing another sign-in. Offline revocation cannot invalidate a server session until connectivity returns; the backend's ordinary expiry remains effective. Storage/network failures are reported, not treated as successful remote revocation.

For future SSO/MFA, prefer an established authorization server supporting native public clients and browser-based authorization code + PKCE with an approved redirect strategy, state validation and revocable refresh credentials. [RFC 8252](https://datatracker.ietf.org/doc/html/rfc8252) describes native OAuth practices. Implementing only a homegrown browser-to-token exchange would not supply this missing architecture. This release deliberately does not claim OAuth/PKCE or production authentication accreditation.

## Local setup and deployment configuration

Use the existing Python/Workstation environment and `requirements-workstation.txt`; the secure-store adapter uses Windows APIs through ctypes, with no extra keyring dependency. Start the backend using its existing local setup and provision a verified active account with existing staff membership. The UI never grants staff roles. Existing staff provisioning/administration remains authoritative.

Use **Settings → Use local development defaults → Test connection → Save connection** for local setup. Saving validates the origins, persists only nonsecret preferences and enables Incoming login immediately; no restart or routine file editing is required. The Incoming screen has a shortcut to Settings. Nothing connects to a default backend until an environment is explicitly selected and saved. Health tests send no credentials and verify the existing `/api/health` response; they do not establish database readiness or operator permissions.

Nonsecret connection settings live in the existing `scanner_agent/local_data/selby_workstation/desktop.ini`, independently of a custom orders-registry location or launcher working directory. Settings preserves unrelated keys. For administrator automation only, `scanner_agent/workstation-connection.example.ini` contains the equivalent explicit local-development example:

```ini
[incoming]
environment=development
backend_origin=http://127.0.0.1:8000
auth_origin=http://127.0.0.1:3000
```

`auth_origin` must exactly match the backend's configured portal auth origin, including scheme, host and port. Environment overrides are `SELBY_ENVIRONMENT`, `SELBY_BACKEND_ORIGIN` and `SELBY_AUTH_ORIGIN`. When overrides are present, Settings shows that they are administrator-managed and prevents a misleading save; change the launch environment and restart instead. Missing both environment and saved preferences leaves Incoming unconfigured and local modules available. Localhost defaults are used only with explicit development mode. Production mode requires both real, administrator-supplied HTTPS origins and the backend's production cookie configuration. Do not put passwords or sessions in settings or environment variables. Changing origins revokes the previous session before applying the change; if revocation is pending offline, preferences stay unchanged until it can complete.

Launch `scanner_agent/Launch_SELBY.vbs` as before. It sets the working directory to its own directory and prefers `.venv-analysis`, falling back to `.venv-workstation`. The normal order workflow exposes no origin, cookie name or session value fields. Connection preferences are editable in Settings and do not grant any backend role.

### Verified local setup and account prerequisites

The connection-fix investigation found no `desktop.ini` and no environment selection: the previous release intentionally disabled login but provided only file-editing guidance. The backend was actually running at `http://127.0.0.1:8000` (`/api/health` returned 200), the portal at `http://127.0.0.1:3000`, and FastAPI's development `AUTH_ORIGIN` matched that portal. A read-only count found one staff membership and one active verified account; no account details or secrets were printed and no memberships were changed. The two localhost origins have now been saved through Settings on this workstation. Native GUI relaunch loaded them and enabled login; the diagnostic reported backend reachable/authentication required.

For another local machine:

1. Start PostgreSQL using the existing project setup. From `backend`, run `.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`. Do not reset the database or apply production migrations. If the backend is already running, do not launch a duplicate.
2. From `frontend`, run `npm run dev` if the portal is not already running. Open `http://127.0.0.1:3000`. FastAPI `AUTH_ORIGIN` must match that exact origin. An alternative backend port can be entered in Settings explicitly.
3. Launch `scanner_agent/Launch_SELBY.vbs`. Open Settings, choose local defaults, Test connection, then Save connection. If already configured, verify the displayed intended origins instead of overwriting them.
4. Open Incoming Orders and sign in with the existing **verified, active operator/admin account**. A normal customer login has no Incoming permission. No default credentials exist, and the password should never be sent in a support conversation.
5. Confirm a customer submission through the portal, then refresh/search its reference in Incoming Orders and open its declared cards. Drafts are intentionally excluded. Preview does not create local order/card IDs.

If a new installation has **no staff membership**, its existing supported provisioning mechanism is the trusted-host bootstrap CLI. First register and verify an explicitly approved dedicated staff account through the existing portal/email process. From `backend`, the authorized administrator may run:

```powershell
.\.venv\Scripts\python.exe -m app.staff_bootstrap --email '<approved-verified-account-email>' --reason 'Authorized initial local administrator setup'
```

This existing command grants the initial **admin** membership, requires an active verified account, records an audit event, revokes old sessions, and refuses to run once any staff membership exists. Do not use it to elevate arbitrary customers or remove existing staff to reopen bootstrap. There is no general-purpose staff-provisioning UI added here; installations with existing staff must use the existing approved administrator/operator access process. This machine already has staff, so bootstrap was neither needed nor run. If account credentials are unknown, use the existing account password-reset flow; no password reset was performed during this fix.

## Operator workflow and API changes

Open Incoming Orders, sign in, and the latest authorized confirmed submissions load automatically. The table shows the immutable reference, current customer name, declared quantity, received quantity, submission date and existing intake status. Search reference/customer name, press Enter or Search, use Previous/Next, or Refresh. Pages contain 50 results; the API retains its existing list shape and bounded limit/offset parameters. A full last page can lead to an empty next page; Previous remains available.

Select/open a submission to see declared items, received physical cards, matches, parcels and discrepancies. The status mapping uses only existing backend states. Customer pre-shipment photographs are explicitly labeled, fetched through the existing staff-authorized private route, bounded and hash-checked, displayed in memory, and cleared with the view. They are not inspection evidence or proof of condition/possession. No previews create local orders, links, physical cards or `SLB-C-…` identifiers.

Compatible backend extensions:

- `GET /internal/intake/me`: additive `display_name`.
- Submission summary/detail: additive `customer_name` (current account name, not a change to confirmed declarations).
- Existing `GET /internal/intake/submissions?search=…`: case-insensitive literal reference or customer full-name substring, maximum query length 200. Existing confirmation filter, deterministic date/ID ordering and limit 1–100/offset bounds remain.
- Authentication routes, response list shape, submission snapshots and all business-write contracts remain unchanged.

The preview transport permits only existing business GET paths. A separate narrow authentication transport permits login/logout POST and CSRF GET. The application Uvicorn access-log filter removes query strings from Incoming routes, since customer-name searches contain PII. Reverse proxies and independently configured access/debug logs must also omit queries, authentication bodies and headers; this application filter cannot control external logging.

## Limits and next integration step

No efficient card-name search exists in the intake backend; it remains deferred. Name search is bounded but not benchmarked for large production datasets, and existing per-summary count queries remain. Queue customer names are current profile values. No live production TLS, real customer-data or deployed-Windows end-to-end acceptance test has been performed. The secure store is Windows-only, there is no SSO/MFA/refresh implementation, and corporate proxy support requires a separately reviewed configuration.

The next physical intake step must explicitly use existing authorized receipt/reconciliation APIs with their audit, CSRF, idempotency and commercial restrictions, plus an agreed local/external identity mapping. Preview must not silently become intake or fabricate production IDs. Existing grading, evidence, research, custody and payment restrictions remain authoritative. See the validation report for actual checks and manual acceptance steps.
