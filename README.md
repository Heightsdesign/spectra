# SPECTRA

Internal receiving and physical inventory (W5.1): see [INTERNAL_OPERATIONS.md](INTERNAL_OPERATIONS.md) for staff bootstrap, migration `0006`, the protected `/admin` workflow, reconciliation rules and validation results.

Customer accounts (W2): see [Authentication and account management](AUTHENTICATION.md) for migrations, bilingual routes, security decisions, private development email and local setup. Customer submissions and payments remain outside the current milestone.

The W1 public Next.js frontend lives in [`frontend/`](frontend/README.md). It runs independently of the backend and contains informational pages only. See its README for local setup, validation status and pending launch details.

SPECTRA is a professional computer-assisted trading card grading and certification system, initially focused on Pokémon cards. Final grades require human validation.

The backend registers Pokémon cards, preserves original front/back images, and returns their metadata. A standalone physical-boundary analysis prototype produces corner estimates and perspective-corrected diagnostics; it does not calculate centering or grades. Final grades always require human validation.

See [Physical boundary detection](backend/BOUNDARY_DETECTION.md) for usage, configurable thresholds, diagnostic storage, and limitations. This prototype is tested on synthetic images and is not production validated.

For the opt-in local review page, saved human labels and real-photo dataset guidance, see [Real-image validation workflow](backend/REAL_IMAGE_VALIDATION.md). This workflow is disabled by default and restricted to loopback access.

## Windows installation

Install Python 3.12 or newer. Open PowerShell in the project root:

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If `backend/.venv` already exists, skip creating it. Commands use the environment's Python directly, so activation and PowerShell execution policy changes are unnecessary.

Copy the example configuration if `.env` does not already exist:

```powershell
Copy-Item .env.example .env
```

Install PostgreSQL and create two separate databases, for example `spectra` and `spectra_test`, using pgAdmin or your PostgreSQL administrator account. The test database must be dedicated to this project and its name must end in `_test`. Set `DATABASE_URL` and `TEST_DATABASE_URL` in `backend/.env` to the respective `postgresql+psycopg://` connection URLs. Replace every placeholder; percent-encode special characters in URL passwords. Never commit credentials.

`CARD_IMAGE_DIR` selects private image storage (default: `backend/data/card_images`). Relative paths are resolved from the working directory, so run commands from `backend`. `MAX_IMAGE_SIZE_BYTES` defaults to 26214400 (25 MiB). Do not serve this directory through a web server or place it inside a public/static directory.

Apply the development database migration from `backend`:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

No tables are created automatically at application startup. Alembic can generate future migrations with `alembic revision --autogenerate -m "description"`; always review generated changes before applying them.

## Start the backend

From the `backend` directory:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Visit <http://127.0.0.1:8000/api/health>:

```json
{"status": "ok", "application": "SPECTRA"}
```

Interactive API documentation is available at <http://127.0.0.1:8000/docs>. The health endpoint checks application availability only.

## Run tests

From the `backend` directory:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Tests use FastAPI TestClient and do not require a running API server. Integration tests require PostgreSQL and `TEST_DATABASE_URL`; they apply Alembic migrations only to that database, isolate each test in a rolled-back transaction, and use temporary image storage. They refuse a database name without the `_test` suffix or the same database name as development, regardless of host aliases. The test role needs permission to migrate the test database. `pytest.ini` configures discovery and imports.

Run the health and image-validation tests without PostgreSQL:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_health.py tests/test_image_validation.py
```

To check the application import separately:

```powershell
.\.venv\Scripts\python.exe -c "from app.main import app; print(app.title)"
```

## Local images

Keep local card images under `backend/data/card_images/`. Local data directories and image files are ignored by Git. The API stores exact original bytes under generated keys, uses exclusive file creation, and provides no image download, update, or deletion endpoint. Originals must also be protected from manual modification through filesystem permissions and backups.

## Card API

- `POST /api/cards`: JSON with `game` (currently only `pokemon`, the default), `card_name`, `set_name`, and `collector_number`. Returns HTTP 201 with a UUID, `registered` status and timezone-aware timestamps. Status is managed by the server.
- `GET /api/cards/{card_id}`: retrieve card metadata.
- `POST /api/cards/{card_id}/images`: multipart fields `side` (`front` or `back`) and `file`. Returns HTTP 201 with image metadata. Actual PNG, JPEG and TIFF contents are validated regardless of the supplied MIME type or extension. Filenames containing path separators, drive separators or control characters are rejected.
- `GET /api/cards/{card_id}/images`: list image metadata, including the original filename, detected MIME type, original-byte SHA-256, size and upload timestamp. Storage keys and filesystem paths are never returned.

Missing cards return 404; invalid inputs/images return 422; oversized image files return 413; an existing original for the same side returns 409. Storage or transaction failures return 503 with no internal paths. Pokémon and status values use string fields plus validation/check constraints so future games/statuses can be introduced through explicit schema and API changes.

Example registration in PowerShell:

```powershell
$card = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/cards -ContentType application/json -Body '{"game":"pokemon","card_name":"Pikachu","set_name":"Base Set","collector_number":"58/102"}'
curl.exe -F "side=front" -F "file=@C:\cards\front.png" "http://127.0.0.1:8000/api/cards/$($card.id)/images"
Invoke-RestMethod "http://127.0.0.1:8000/api/cards/$($card.id)/images"
```

Upload success and failure events are logged as JSON using the `spectra.uploads` logger. Database uniqueness reserves each side before disk writes. Ordinary write/commit failures roll back metadata and remove newly created files; existing files are never overwritten. Failed cleanup emits `image_cleanup_failed` for operator attention. Filesystem storage and PostgreSQL cannot share an atomic transaction: a process crash or an ambiguous connection failure during commit can require reconciliation of orphaned files or missing files. Production deployment should add reconciliation and coordinated backups before accepting valuable originals.

## Customer services and pricing (W3.2)

See [PRICING.md](PRICING.md) for configurable processing tiers and upgrades, per-card choices, server-generated quotes, immutable acceptance snapshots, development-only catalog setup and exact validation results. Submission confirmation remains separate from commercial acceptance and payment.
