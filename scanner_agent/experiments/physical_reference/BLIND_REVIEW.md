# Controlled blind physical-boundary review (R&D)

The production objective remains automated detection. This optional research
workflow never changes detector decisions, thresholds, gates or grading.

Use a reviewer who has not seen results for the image. Earlier D/E reviewers
cannot become naive by opening a new page. Prior image-specific exposure is
explicitly recorded as `none`, `exposed` or `unknown`; only `none` supports the
**self-declared** blind designation. It does not independently prove blindness.

## Reviewer procedure

Open the dedicated session `editor.html` locally in a modern browser. It contains
only a lossless PNG encoding of the original RGB pixels, empty schema-v1 manual
sides and session identity. No detector reports, previous references, seeds or
comparison assets are loaded or embedded. The original BMP is never rewritten.

1. Enter reviewer identity and prior exposure. Make the explicit manual-review
   declaration. Do not consult candidate-bearing pages during this pass.
2. Choose each side and **Place two points** on the material boundary. Wheel
   zooms about the pointer (up to 64×); drag pans; Fit image restores the view.
   Drag the central line body to translate both endpoints without changing
   orientation or length. Drag either visible circular handle to adjust that
   endpoint independently. Targets highlight on hover; handles remain a fixed
   screen size at every zoom. Dragging a line never pans. Drag empty image to
   pan, or use Shift-drag/middle-drag to pan over a line. No snapping is applied.
   Pan to inspect the full side and corners. Yellow is the active manual line;
   cyan lines are other manual sides. These are exclusively reviewer geometry.
3. Adjust endpoints independently using pixel coordinates (0.05 px input step,
   arbitrary finite subpixel values accepted). Mouse edits retain floating-point
   coordinates, notes and uncertainty, and require reconfirmation. Choose certain, uncertain or
   visually indeterminate. Uncertain requires positive ± pixel uncertainty and
   notes. Indeterminate requires notes and deliberately has no line; it is not
   forced into a fabricated geometry. Confirm **each** side explicitly,
   including uncertain/indeterminate sides. Any edit invalidates confirmation.
   Drag proposals outside the image or with endpoints less than one pixel apart
   are refused; the last valid geometry remains.
4. Export and lock the first pass. All four current confirmations, image-bound
   geometry, reviewer identity and declarations are checked. Download the single
   `blind-first-pass-SESSION_UUID.json` bundle. The page locks after export;
   this is an in-memory guard, not persistent access control. Reloading creates
   an empty page, not a restored or revised reference.
5. Give the coordinator the actual downloaded bundle. Do not inspect comparisons
   until the coordinator freezes it successfully. If downloading fails, do not
   claim it was frozen: a valid file must pass the coordinator checkpoint.

## Coordinator commands

Run from `scanner_agent` (PowerShell):

```powershell
$python = '.\.venv-analysis\Scripts\python.exe'
# New sessions reject detector-report/reference options and existing outputs.
& $python .\blind_physical_boundaries.py prepare $originalBmp --output $newSession
# After the actual reviewer exports; never synthesize or autofill this input:
& $python .\blind_physical_boundaries.py freeze $session --export $downloadedBundle
# Only after freeze: inputs must match the same original image.
& $python .\blind_physical_boundaries.py compare $session --report $frozenReport --report $phase2Report --previous-reference $previousHumanExport
```

`prepare` creates `session.json` and `editor.html` only. `freeze` validates the
existing physical-reference schema/geometry and prepared annotation IDs, all
four reviewed snapshots, manual-only origins, no source reports, no previous
reference, false in-page exposure, explicit prior exposure and timezone-aware
export time. It verifies the reference SHA-256 before reserving `first-pass/`.

The original downloaded bundle bytes become `first-pass/export.json`. Its
`reference_json` UTF-8 string becomes `first-pass/reference.json` **byte for byte**,
without reserialization. `first-pass/manifest.json` links their SHA-256 values,
reviewer, session/image/annotation identities, export/freeze times and exposure.
Existing first-pass directories are refused, including incomplete reservations.
Do not delete a reservation to retry silently: preserve it and use a separate
session after documenting the failed checkpoint.

`compare` validates the frozen checkpoint and hashes **before reading comparison
inputs**, then rechecks input integrity. Every result receives a new
`comparisons/UUID/` directory containing `comparison.json` and `integrity.json`.
There is no output option that can target the frozen reference. Reports use the
existing detector comparison utility and its 101-point inward-normal convention:
positive offsets point from the blind reference toward the card interior.
Previous-human comparisons preserve IDs, report provenance, reviewer, side
origins and exposure, explicitly flagging possible detector anchoring. Per-side
signed offsets, start/mid/end, mean/max absolute offsets and TL/TR/BR/BL
intersection distances are descriptive agreement, **not definitive accuracy**.
Uncertain statuses/bands remain explicit; indeterminate sides have no numerical
displacement. Corners are extrapolated straight-line intersections.

## Versioning and integrity limits

`experiments/physical_reference/reference.schema.json` remains unchanged at v1.
No blind fields are silently added. Separate version-1 JSON records are:

| kind | Required role-specific fields |
|---|---|
| `blind_physical_session` | session_id, created_at_utc, image_path, image, annotation_id, annotation_version |
| `blind_first_pass_export` | session_id, exported_at_utc, blind_review_declared, prior_detector_exposure, reference_sha256, reference_json |
| `frozen_blind_first_pass` | session/image/annotation IDs, reviewer, reference/export filenames and hashes, exported/frozen times, exposure, eligible_blind_declaration, limitation |

Each includes `schema_version: 1`. The image object retains SHA-256, dimensions
and RGB mode. Reviewer uncertainty and confirmations remain in the unchanged
reference. The bundle declaration refers to the **current pass**, while prior
exposure is separate. Exposed/unknown exports can be preserved and compared but
are explicitly ineligible for a blind claim.

Exclusive creation and hashes provide workflow integrity evidence, **not
tamper-proof storage**. A user with file access can edit files, hashes, JavaScript
or invoke other utilities. There is no authentication, signature, WORM storage,
cross-session exposure audit or enforceable control over the reviewer's outside
knowledge. Coordinator-controlled backups/access restrictions are study process.

Later assisted review must use a **separate** output/session and IDs. The existing
assisted editor can import the frozen reference into a new directory (clearing
confirmations and recording the previous-reference hash); never overwrite or
relabel the blind pass. An assisted revision is not a blind reference.

## Validation

`tests/test_blind_reference.py` covers payload isolation, empty initialization,
schema/geometry/confirmation rejection, uncertain/indeterminate handling, exact
byte freezing, SHA failures, image changes, overwrite refusal, checkpoint gating,
comparison metrics and tampering. `tests/blind-reference-browser.mjs` uses real
Chrome pointer events on synthetic imagery only. The existing editor and S2.2c
tests remain unchanged and run in the full suite. Browser tests require Chrome,
Node and working local DevTools connectivity.
