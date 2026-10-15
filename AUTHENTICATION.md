# SPECTRA W2 — Customer accounts

The existing FastAPI backend, PostgreSQL database and Next.js frontend now provide customer accounts. No second application backend, auth service or database is introduced. Card/image schemas and internal boundary-review access controls are unchanged. Existing card records are internal prototype records, not customer submissions; their existing API is not presented as a customer submission API. Customer submissions, checkout, payments, shipping, grading results and admin tools are outside this milestone.

## Architecture and security

- **Passwords:** versioned, per-password salted scrypt hashes using Python/OpenSSL (`N=131072`, `r=8`, `p=1`, 32-byte output, random 16-byte salt). Argon2 was not installed in the environment. This scrypt setting follows the [OWASP fallback recommendation](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#scrypt). Passwords accept 12–128 Unicode characters and are never truncated, normalized or stored in plaintext. Malformed Unicode is rejected. Login checks a dummy hash for unknown addresses. Scrypt uses roughly 128 MiB per operation; production worker/concurrency limits must account for that.
- **Identity:** UUID customers, trimmed/lowercase email uniqueness enforced in both validation and PostgreSQL. Internationalized domains are converted to IDNA; Unicode email local parts/SMTPUTF8 are not supported. Names support valid Unicode. Profile updates permit names and FR/EN preference only. Email, status and customer ID cannot be assigned by customer payloads.
- **Sessions:** independent cryptographically random 256-bit opaque identifiers. Only SHA-256 digests are stored. Cookies are host-only, HttpOnly, SameSite=Lax, Path=/ and expire after the configured absolute lifetime (24 hours by default). Production uses a Secure `__Host-spectra_session` cookie; development uses `spectra_session`, with Secure enabled for HTTPS origins. A successful login rotates the browser session; logout revokes the current session. Password reset/change revokes every account session and outstanding reset links. Disabled and unverified accounts fail authentication on every request.
- **CSRF:** every auth mutation requires the exact configured Origin, JSON and `X-Spectra-Client: 1`. Authenticated mutations additionally require `X-CSRF-Token`, obtained from `/csrf` and cryptographically bound to the opaque session. SameSite is defense in depth, consistent with [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html). No permissive CORS policy is added. Tokens are not stored in localStorage.
- **Verification/recovery:** 256-bit opaque tokens, only digests in PostgreSQL, scoped by purpose, expiring and single-use. Creating a new link invalidates older links of that purpose. Redemption and credential changes serialize on the customer row; concurrent verification attempts cannot both succeed. Verification requires an explicit action, not an email-link GET. Resetting a password does not verify an unverified email.
- **Rate limits:** PostgreSQL atomic upserts implement fixed-window IP and normalized-email budgets, independent per endpoint. Defaults are 10 attempts per 15-minute window. Verification/reset completion uses IP limits; request/login/registration endpoints also use email limits. Failed attempts count; 429 includes Retry-After. No in-process limiter that resets on restart is used. Boundary windows can admit two adjacent budgets. Old buckets require scheduled expiry cleanup before high-volume production use.
- **Privacy:** registration duplicates and recovery requests return generic messages. Recovery/resend delivery failures also return the generic accepted response and log only a fixed event name. Response timing is not claimed to be indistinguishable; production delivery should be queued to reduce timing differences. Auth validation responses never echo submitted passwords/tokens. Auth JSON responses use no-store and no-referrer. Do not enable request-body, cookie or outbound-mail-content logging in deployment.
- **Frontend:** browser auth requests use relative `/api/auth` URLs, proxied by Next.js to the existing backend. Account routes validate the session server-side and redirect unauthorized visitors to `/login`. A backend outage fails closed with an unavailable message. There are no client-supplied account IDs or customer/session lookup routes. No arbitrary return URL is accepted. Dashboard sections are explicitly unavailable placeholders, not invented customer data.

## Database migration

`backend/alembic/versions/0002_customers.py` follows `0001` and adds:

| Table | Purpose |
| --- | --- |
| `customers` | Unique normalized email, password hash, names, FR/EN preference, verification flag, active/disabled status, timestamps |
| `customer_sessions` | Unique session digest, customer FK, creation/expiry/revocation timestamps |
| `customer_auth_tokens` | Unique digest, customer FK, verify/reset purpose, creation/expiry/consumption timestamps |
| `auth_rate_buckets` | Hashed limiter key, count, indexed expiry |

Session/token customer foreign keys cascade on deletion. Customer and expiry indexes support revocation and retention. Card/image tables are not modified. No automatic schema creation occurs on application startup. The complete backend test suite upgrades only the dedicated test database to migration head; apply the development migration explicitly as shown below.

## API

All paths start with `/api/auth`:

| Method / path | Behavior |
| --- | --- |
| `POST /register` | Email, password, first_name, last_name, preferred_language; generic 202, verification delivery for new accounts |
| `POST /verification/request` | Email; generic 202, resend if eligible |
| `POST /verify-email` | Single-use token; mark email verified |
| `POST /login` | Email/password; verified active customers only; set fresh cookie |
| `GET /me` | Current customer's public profile |
| `GET /csrf` | CSRF token bound to current session |
| `POST /logout` | Revoke session and expire cookie |
| `PATCH /profile` | First/last name and FR/EN preference only |
| `POST /password/change` | Current password and new_password; revoke all sessions |
| `POST /password/reset/request` | Email; generic 202 |
| `POST /password/reset` | Single-use reset token and password; revoke all sessions |

Protected writes require the CSRF header in addition to Origin/custom header. Unknown, expired, revoked or disabled sessions return 401. Invalid input returns a redacted 422. Invalid/expired/used/wrong-purpose links return generic 400. Origin/CSRF failures return 403. Invalid content type returns 415. No credentials or auth-token values are returned in customer responses. A CSRF token is intentionally returned to the authenticated same-origin client; it is not a bearer session token.

## Routes and languages

`/register`, `/login`, `/verify-email`, `/forgot-password`, `/reset-password`, `/account`, `/account/settings` are implemented. Account routes require authentication. Settings include profile/language updates, password change and logout. Password changes require the current password and send the user back to sign-in.

`src/lib/i18n.ts` contains matching FR/EN dictionaries shared by reusable components. French is the initial default. The language selector uses a non-secret preference cookie; registration persists the chosen language, login restores it, and settings Save persists a changed preference in PostgreSQL. The entire new account interface switches language together. Verification/reset links carry the account's language. Existing public-site navigation/copy remains English pending a later localization milestone. Auth/account regions declare their own `lang`; the public root remains English.

## Local development

1. Use the existing PostgreSQL setup. Preserve your private `backend/.env`; do not overwrite it with example values. The example configuration contains placeholders, not operational credentials.
2. From `backend`, run:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
$env:AUTH_ORIGIN='http://127.0.0.1:3000'
$env:AUTH_ENVIRONMENT='development'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

3. In another terminal, from `frontend`:

```powershell
$env:SPECTRA_BACKEND_URL='http://127.0.0.1:8000'
npm ci
npm run dev
```

4. Open **http://127.0.0.1:3000/register**. Use the same hostname consistently; `localhost` is a different Origin and cookie host. Register, open the private development email file locally, follow its verification link and click Verify. Sign in, edit settings or try recovery.

No paid provider or added Python packages are required. For a production-mode local frontend, set the backend origin before **both** `npm run build` and `npm start`: Next.js rewrites are built into the output, while account SSR uses the runtime value. A mismatched build/runtime backend is unsupported.

## Private development email

`EmailDelivery` in `app/auth_email.py` is the provider contract. The current development implementation writes UUID-named JSON files under `AUTH_MAIL_DIR`, default `backend/data/auth_mail`. Each contains recipient, purpose, language and a verification/reset link. There is no API to list or retrieve these files. This directory must remain outside public/static directories and outside original/diagnostic storage; overlap with those storage trees is rejected.

The link token is in the **URL fragment**, not a query string, so HTTP servers and referrers do not receive it. The frontend reads it after hydration, removes the fragment and holds it only in component memory. Reloading then requires reopening the original email link. Do not paste links into shared terminals, logs, issue reports or chat. Files/directories are created with restrictive POSIX modes; on Windows, configure ACLs to grant access only to the local application/operator account. Git ignores data directories. Protect and expire the files because they contain live authentication secrets.

Production mode deliberately refuses the local delivery backend. Implement `EmailDelivery.send`, select it in `get_email_delivery` using deployment configuration, and inject SMTP/API credentials through a secrets manager or environment before enabling real delivery. Send both FR and EN templates, with retry/queue handling and no token-content logs. Registration fails closed if delivery is unavailable; recovery continues to return generic accepted responses. A production mail provider and queue are **not** implemented in W2.

## Production requirements and limits

- Set `AUTH_ENVIRONMENT=production` and a bare HTTPS `AUTH_ORIGIN` without trailing slash. HTTP origins are accepted only for loopback development. Use a canonical public host, TLS, Secure cookies and appropriately configured reverse-proxy trust.
- Never trust client-provided forwarded IP headers. The local Next proxy presents a shared loopback IP to the backend; its IP budget is intentionally conservative. Before public deployment, configure a trusted edge/proxy chain that supplies verified client IPs to FastAPI and strips untrusted forwarding headers, or implement a trusted identity forwarding mechanism. Test this chain; the development rewrite alone is not a production per-client-IP limiter.
- Keep the backend/private storage inaccessible from public static serving. Internal boundary review remains a separate opt-in loopback workflow. Customer auth does not turn it into a customer-accessible feature.
- Bound request size and worker concurrency, configure secret-safe logs, backups and retention for expired sessions/tokens/rate buckets/outbox files, and complete a deployment/security review. Sessions have an absolute lifetime; no idle timeout or remember-me option is implemented.
- Status changes are an operator/database operation, not an admin dashboard. Setting a customer to disabled blocks existing sessions and future logins immediately. Revoke their session rows as part of any disable/re-enable operation so re-enabling cannot restore an old unexpired session.
- Email changes, MFA, social login, breach-password screening, customer deletion/self-service export and administrative account tools are not included. No account or submission data is fabricated. SMTPUTF8 email local parts remain unsupported.
- Browser screenshots, device interaction, password-manager and assistive-technology behavior remain unverified. Automated HTTP integration does not simulate a real browser's cookie or native validation enforcement.

## Tests

Backend (dedicated PostgreSQL `_test` database required):

```powershell
cd backend
$runRoot = Join-Path (Get-Location) ('test_tmp_auth_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $runRoot | Out-Null
$env:TEMP=$runRoot; $env:TMP=$runRoot; $env:TMPDIR=$runRoot
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest --basetemp="$runRoot\pytest" -o "cache_dir=$runRoot\cache" -ra
```

Frontend (Node.js 22.14+):

```powershell
cd frontend
npm test
npm run lint
npm run build
npm run typecheck
..\backend\.venv\Scripts\python.exe tests/run-local-integration.py
```

The last command requires ports 8000 and 13000 to be free and a build with the default backend origin. It starts the existing FastAPI app and a Next production server against the dedicated test database, creates one uniquely named test customer, then stops its servers and deletes only that customer (cascading its sessions/tokens). It does not start or migrate a second production database. Run the backend suite first to apply test migrations. **Run backend and HTTP integration suites sequentially, never concurrently: they share the test database.** The test helper refuses the development database and occupied ports.

Coverage includes registration/duplicates/validation, normalized email and hashed credentials, verification/resend/expiry/purpose/single-use behavior, session rotation/expiry/revocation, logout, password recovery/reuse/change, disabled access, profile isolation, CSRF, database rate limits, FR/EN preference, safe validation/logging and private mail. Frontend tests cover validation, translation parity and failed/unauthorized account lookups. The real HTTP test exercises proxy cookie forwarding, server-side redirects, language rendering, account updates, recovery/change and concurrent single-use verification.

Final validation in this workspace:

| Check | Result |
| --- | --- |
| Complete PostgreSQL-backed backend suite | 137 passed, 0 failed/skipped, 2 deprecation warnings, 27.51 seconds; fresh writable temp/cache directories |
| Frontend unit tests | 8 passed, 0 failed/skipped |
| Frontend lint | Passed, zero warnings |
| Production build | Passed; original public routes plus all seven new routes generated |
| TypeScript | Passed after build |
| Real HTTP integration, run after backend suite | 1 passed, 0 failed/skipped, 3.01 seconds |

The backend warnings concern existing Starlette/httpx and Alembic configuration deprecations. Node 22 emits an experimental type-stripping warning for unit tests. Next.js reports an unrelated parent-directory lockfile which it ignores. No browser/device success is claimed. An earlier overlapping test run selected an integration fixture's reset row; the expiry assertion now targets its own token explicitly, and final suites were rerun sequentially. No existing tests were weakened.

## Files

Backend additions: `app/customer_models.py`, `app/passwords.py`, `app/auth_schemas.py`, `app/auth_email.py`, `app/auth.py`, migration `alembic/versions/0002_customers.py`, `tests/test_auth.py`.

Backend updates: `app/config.py`, `app/main.py`, `alembic/env.py`, `.env.example`.

Frontend additions: `src/lib/i18n.ts`, `auth-validation.ts`, `customer.ts`, `server-customer.ts`; `src/components/auth-ui.tsx`, `auth-page.tsx`, `account-area.tsx`; the seven new route modules plus account layout; `tests/auth.test.mjs`, `auth.integration.mjs`, `run-local-integration.py`; `.env.example`.

Frontend updates: `next.config.ts`, `package.json`, `src/components/header.tsx`, `src/app/globals.css`, `README.md`. Root updates: `README.md` and this document. No existing test assertions were weakened, and no Python dependency or card/image schema changes were required.
