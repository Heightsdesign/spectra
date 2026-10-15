# Local real-image validation (Milestone 3.1b)

This workflow collects human assessments of the existing physical-boundary detector. It does not validate the detector automatically or implement printed-border detection, centering or grading. No real photographs are bundled, and no real-photo accuracy claim follows from the automated tests.

## Start locally

Use the existing PostgreSQL setup, migrations and original-image upload API described in the root README. From `backend`, in PowerShell:

```powershell
$env:BOUNDARY_REVIEW_ENABLED='true'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Open <http://127.0.0.1:8000/internal/boundary/review>. Paste the UUID returned by an original upload, or retrieve it with `GET /api/cards/{card_id}/images`. Click **Run analysis**. Existing runs are available in the selector and can be bookmarked using the page's run-ID fragment. Refresh discovers runs created in another session. Each analysis invocation creates a new run; existing runs and originals are preserved.

The page shows a PNG preview of the original decoded raster, the overlay and the normalized output, plus corners, metrics, warnings, failure reason, configuration and provenance. Preview conversion is in memory; it never rewrites the original. JPEG/TIFF inputs can therefore be viewed without native browser TIFF support. All three views use encoded raster orientation, ignoring EXIF rotation, matching detector coordinates. ICC profiles are not applied. Missing diagnostics are shown as unavailable; an image-loading failure is indicated beside that view. A rejected analysis has no normalized image.

Choose **correct**, **incorrect** or **uncertain**, optionally add notes, and save. The latest assessment pre-fills the form when reopening a run. Saving again adds a history record rather than replacing an earlier review. Text is displayed as text, including notes containing HTML.

## Development-only access

`BOUNDARY_REVIEW_ENABLED` defaults to false. Every workflow route returns 404 while disabled. Enabled routes require a loopback peer and a localhost/loopback Host. Foreign Origin headers are rejected; POST requests also require `X-Spectra-Review: 1`, supplied by the page. No CORS access is enabled. These checks are local access guards, not user authentication. Use the loopback binding and `--no-proxy-headers` shown above; do not expose this application through a reverse proxy, port forwarding or public hosting. Other local processes/users can access it. The existing card API has no new authentication restrictions.

Disable the workflow by stopping the server, removing the environment setting and restarting:

```powershell
Remove-Item Env:BOUNDARY_REVIEW_ENABLED
```

## Internal API

All paths below start with `/internal/boundary`. Clients supply UUIDs, never filesystem paths. Analysis uses the existing default `BoundaryConfig`; there are no client-supplied detector settings.

| Method/path | Behavior |
| --- | --- |
| `POST /images/{image_id}/analyses` | Analyze an existing original; return 201 with stored metadata, result, image URLs and review history |
| `GET /runs` | List saved runs with metadata and review history |
| `GET /runs/{run_id}` | Reload one run |
| `GET /images/{image_id}/preview` | Integrity-checked PNG raster preview |
| `GET /runs/{run_id}/diagnostics/{name}` | PNG only; `name` is exactly `mask`, `overlay` or `normalized` |
| `POST /runs/{run_id}/reviews` | Append `{"label":"correct","notes":"optional"}`; return 201 with review record |
| `GET /review` | Local review page |

Malformed UUIDs and invalid labels produce 422; unknown UUIDs or missing diagnostic files produce 404. Missing local access requirements produce 403. Preview integrity mismatch produces 409. Storage failures produce 503 without filesystem paths. Rejection by the detector is an analysis result, not an HTTP error. Notes are limited to 4,000 characters, and extra review payload fields are rejected.

## Local records and evaluation

Artifacts remain in `BOUNDARY_OUTPUT_DIR` (default `backend/data/boundary_diagnostics`), outside `CARD_IMAGE_DIR`. Overlapping trees are rejected. No new database schema is needed. No storage directory is mounted as static content; endpoints resolve generated IDs and fixed filenames and reject symlinks/junctions. Diagnostic responses use `no-store` caching.

Each run directory contains the existing `result.json` and available PNGs. Reviews are separate `review-<uuid>.json` files within that directory, published by rename after writing and flushing a temporary file. Each contains:

- `schema_version`, `review_id`, `created_at`, `label`, `notes`;
- `run_id`, `image_id`, `source_sha256`;
- `analysis_reference`, a relative reference to `<run-id-hex>/result.json`.

For evaluation, join review records to analysis metadata by `run_id` and source photographs by `image_id`/SHA-256. Preserve all reviews for audit; use the latest timestamp per run as the current label. The API returns history in timestamp/ID order. There is no reviewer identity or inter-reviewer adjudication. Back up originals, database metadata and analysis directories together. Runs whose database image record is later removed remain readable, but their original preview will return 404.

This minimal synchronous workflow is for small local datasets. Listing loads all runs; there is no pagination, job queue, retention policy or crash-recovery service. Interrupted writes can leave `.tmp` files, which are ignored. A corrupt result/review JSON can prevent a run/list from loading and requires local inspection/restoration. Do not edit artifacts while the server is running.

## Assemble a real-image validation dataset

1. Collect photographs you are permitted to use. Start with unsleeved cards on contrasting, matte, uniform surfaces under diffuse light, all edges visible, roughly overhead. Include different card colors, artwork styles, wear, cameras and resolutions.
2. Add explicit challenge cases: low contrast, textured/gradient backgrounds, sleeves/slabs, shadows, glare, clipping, blur, multiple objects, rotation, severe perspective and damaged corners. Include negative scenes without a card. Keep usable and deliberately unusable photos distinguishable in the manifest.
3. Preserve camera files unchanged and upload through the existing API. The current schema permits one front and one back original per registered card. For repeat captures, create a separate acquisition card record, and group those records under the same physical-card identifier in your dataset manifest. Never replace an earlier original to fit the schema.
4. Keep a local CSV/JSONL manifest outside original storage, for example `data/validation_manifest.jsonl`. Record `image_id`, SHA-256, physical-card group ID, capture session, side, camera, lighting, background, sleeve status, image dimensions, challenge tags and whether detection should be feasible. Avoid personal information in filenames/notes. The workflow does not create this manifest automatically.
5. Run analysis and compare the original, overlay and normalized image. For **correct**, acceptance/rejection must be appropriate; accepted corners must follow the actual physical edges and rectification must be usable. Label a false acceptance, misplaced outline, bad rectification or rejection of a usable image **incorrect**. Use **uncertain** when visibility is inadequate. For rejected cases, notes should distinguish appropriate rejection from missed detection. Record specific issues, not just a general impression.
6. For numerical corner accuracy, create separate human annotations of the four physical corners in decoded, EXIF-unrotated raster coordinates. Review labels alone do not supply ground-truth coordinates. Have another reviewer assess a subset and reconcile disagreements separately.
7. Separate threshold-tuning photos from a held-out evaluation set, grouping by physical card and capture session to avoid near-duplicate leakage. Freeze algorithm/configuration for the evaluation pass. Report counts, accepted/rejected outcomes, false accepts, false rejects, uncertainty and results per challenge condition. Multiple runs of the same image are not independent samples.

Keep uncertain cases separate from correctness-rate denominators and report their count. A set dominated by easy photographs cannot establish performance on uncontrolled acquisitions.

## Tests

From `backend`, use fresh writable temp/cache directories:

```powershell
$runRoot = Join-Path (Get-Location) ('test_tmp_validation_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $runRoot | Out-Null
$env:TEMP=$runRoot; $env:TMP=$runRoot; $env:TMPDIR=$runRoot
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest --basetemp="$runRoot\pytest" -o "cache_dir=$runRoot\cache" -ra
```

The existing dedicated PostgreSQL test database remains required. Tests cover API analysis, original preservation, safe diagnostic/preview access, saved review history, invalid inputs, local-access guards and storage failure behavior. Synthetic fixtures test workflow correctness, not real-image detector accuracy.
