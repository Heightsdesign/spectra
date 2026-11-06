# SELBY local development test accounts

Five fictional verified fixtures are available in the local `spectra` PostgreSQL database. These are development accounts only; do not reproduce them in production or reuse their passwords elsewhere.

| Display name | Email | Existing authorization model |
| --- | --- | --- |
| Client Test 01 | client01@selby.test | Customer, no staff membership |
| Client Test 02 | client02@selby.test | Customer, no staff membership |
| Client Test 03 | client03@selby.test | Customer, no staff membership |
| Opérateur Test | operator@selby.test | StaffMembership: operator |
| Administrateur Test | admin@selby.test | StaffMembership: admin |

Their unique random passwords are **only** in the root `SELBY_LOCAL_TEST_CREDENTIALS.md`. That file is untracked and explicitly excluded by `.gitignore`, root Docker build-context rules and Git archive export rules. No frontend/runtime module imports it. There is no deployment pipeline in this repository; any future non-Git/non-Docker packaging must retain the same exclusion. Never force-add or manually copy the credentials document into deployment artifacts.

## Setup and rerun

From `backend`:

```powershell
.venv/Scripts/python.exe -m app.local_test_accounts --database spectra --confirm-local-development
```

The command supports only the five fixed `.test` addresses. It creates missing accounts with existing salted scrypt hashes and marks only those newly created accounts as verified/active. Customers receive no staff membership. Staff fixtures receive the existing operator/admin memberships, with provenance in the existing audit model. It calls no email delivery service and creates no submissions. It does not change normal registration or global verification settings.

Existing addresses are preserved by default: no password, profile, verification, status or role changes. The output reports preserved addresses and their actual staff role/verification state, so a conflicting pre-existing account is visible. Missing plaintext for an existing account is reported in the document rather than guessed.

Guard conditions: development authentication, loopback portal and PostgreSQL origin, an explicitly confirmed allowed development database name, no URL connection overrides, and matching loopback/writable PostgreSQL server metadata. The connection pins hostaddr and port so libpq environment defaults cannot redirect the connection. Credentials must be Git-ignored and untracked before any insert. Database access is serialized by an advisory transaction lock, email uniqueness prevents duplicates, and no migration/database reset occurs. The allowlisted names are spectra, spectra_dev, selby_dev, spectra_test and selby_test; confirmation must match the configured database exactly. If safety checks fail, the command refuses to seed.

The credentials document is fsynced before committing database changes. If commit outcome is unknown, the document is retained with a warning rather than destroying the only newly issued passwords. A safe rerun preserves existing accounts. Never treat an unconfirmed batch as proof of account creation.

## Explicit fixture-only reset

No reset was performed when provisioning these accounts. If a fixture password is later lost, an authorized local developer can explicitly rotate one account:

```powershell
.venv/Scripts/python.exe -m app.local_test_accounts --database spectra --confirm-local-development --reset-email operator@selby.test --confirm-reset
```

Both reset flags are required. Only the fixed fixture addresses are accepted. Reset additionally requires this command's creation provenance and unchanged active/verified state and role; unrelated/conflicting accounts are not reset or promoted. It updates only that fixture's hash, revokes its sessions, adds an audit record and appends the new credentials locally. Use the latest issued row; older rows are historical. Other accounts and existing real-user passwords remain unchanged. Unknown/conflicting accounts require separate authorized investigation, not deletion, forced promotion or bypassing verification.

## Login and scenarios

Portal: `http://127.0.0.1:3000/login`. Use any customer fixture for manual declarations and ownership-isolation checks. Start the existing local FastAPI/portal processes if needed; there is no automatic startup or submission confirmation.

Workstation: relaunch `scanner_agent/Launch_SELBY.vbs`, confirm Settings points to the intended local FastAPI (`http://127.0.0.1:8000`) and portal origin, then open Incoming Orders and enter the operator/admin fixture credentials. Customers intentionally cannot enter Incoming. Administrator custody authorization remains the existing explicit policy; it is not payment verification or permission to inspect. No Windows Credential Manager entries were overwritten by account provisioning or validation.

## Validation (2026-10-25)

Audit established a running local PostgreSQL 17 Windows service, configured development authentication, localhost:5432 database spectra, loopback server address (::1), and no recovery replica. All five addresses were initially missing. Two pre-existing non-fixture accounts and the existing staff membership were preserved; no commercial submissions were created or confirmed. The existing three confirmed submissions remained in place.

Live validation used the actual Next.js authentication proxy at port 3000: all five fixture login/session checks passed; all three customers received 403 from the internal staff endpoint; staff roles returned operator/admin as expected; logout revoked each test session. These checks exercised HTTP through the real portal/backend, not a browser form automation run.

Both staff accounts also passed the actual desktop authentication/Incoming GET/logout transport against FastAPI port 8000, using a temporary in-memory validation vault so the operator's existing OS credential was preserved. This tests desktop transport compatibility, not a fresh native GUI acceptance session or Credential Manager roundtrip. Existing production OS-keychain behavior is unchanged.

A live rerun created/reset no account, kept the credentials file byte-for-byte unchanged, preserved unrelated account hashes/profile/state, and left submission and local verification-mail counts unchanged. Ordinary email verification remains enabled; its normal registration/login behavior is tested on the isolated test database and temporary local mail storage.

Relevant automated tests from `backend`:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_local_test_accounts.py tests/test_auth.py tests/test_intake.py tests/test_workstation_v05a3.py -q
```

Result: **58 passed**, two existing dependency/config deprecation warnings, 42.85 seconds. Coverage includes refusal of production/remote/overridden targets and mismatched/recovery server metadata; unique secure fixture passwords; ordinary verification remaining required; customer/staff/admin boundaries; idempotent preservation; conflicting-account preservation; provenance-restricted explicit resets and session revocation. Tests use the guarded isolated PostgreSQL test database and temporary mail storage, not live customers. Ruff checks on the new command and tests passed.

Git checks confirmed the credentials file is ignored and untracked; its export-ignore attribute is set. Live creation produced exactly five fixtures. A subsequent actual rerun created or reset none and left the document unchanged. No database reset, migration, deployment, inspection/grading change or commercial submission operation occurred.
