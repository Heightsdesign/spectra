# SELBY Workstation V0.4 — Human-Supervised Grading Engine

V0.4 adds a draft grading dossier to the existing native inspection workstation.
It reuses V0.2 centering geometry and V0.3 findings, reviews, sessions and recovery.
A human-validated provisional grade never authorizes commercial release and never
changes frozen S2.1/S2.2 review or blocked statuses.

## Exact Windows launch commands

PowerShell, using the existing environment:

```powershell
Set-Location 'C:\Users\plher\Documents\spetra\scanner_agent'
.\.venv-analysis\Scripts\python.exe -B .\selby_workstation.py
```

Open an image or session, then choose **Grading** on the toolbar. Enter operator
identity in the main window before submitting grading actions. Close a workbench
to return to the main window. For a saved dossier:

```powershell
.\.venv-analysis\Scripts\python.exe -B .\selby_workstation.py --session 'C:\path\to\inspection-SESSION_UUID-VERSION_UUID.json' --grading
```

Replace the example session path with an actual saved version. A native launch
with the existing real scan was verified using:

```powershell
.\.venv-analysis\Scripts\python.exe -B .\selby_workstation.py --image 'local_data\s2_1_validation\card-a\scan-1\captures\20261017T184714_f46f9ce59a8644009dff682365d48a3f\original.bmp' --printed 'local_data\s2_2b_validation\20261017T202702_0892dd46243f4756a0076014efe3f13f\pair-000-b\report.json' --grading
```

That command only opens the draft panel; it does not inspect or grade the real
card. `--grading` and `--condition` are alternative initial panels. Dependencies
remain in `requirements-workstation.txt` (validated with PySide6 6.12.0).

## Complete the two face inspections

1. Inspect the front using the existing boundary, centering and condition tools.
   Label it **front**, record operator identity, confirm all certain physical and
   printed lines, and independently validate both geometry groups. Review corners,
   edges and surface, resolving every active suggestion and completing each category.
2. Inspect the back independently and label it **back**. Complete its condition
   categories and save a separate session. The two faces must have different image
   hashes. Matching hashes are refused; image labels alone cannot prove that the
   scans belong to the same card.
3. Use one face's session as the card dossier owner. Open **Grading**, enter a
   physical card/intake identity and choose **Create dossier**. Enter an attachment
   explanation and choose **Attach current face**. Then enter a pairing explanation
   and choose **Attach saved opposite/revised face**, selecting the back session.
   The imported inspection and its existing finding IDs are reused, not re-entered.
4. **Inspect current image** returns to the existing condition tool for confirmation,
   rejection, reclassification or manual annotations. After changing inspection
   decisions, complete the affected categories and explicitly reattach that face.
   To revise the imported opposite face, open its session in a second workstation
   window, inspect/save a new version, then attach that version to the dossier.
   Save the dossier before opening a different image/session in its main window.

Attachments are immutable snapshots in the dossier, with original image hashes,
source report metadata, boundary reviews, condition evidence and saved-version
basis when available. Current inspection decisions are compared against the
attached revision. Editing geometry, findings, review stamps or operator identity
makes the current attachment stale. Viewer prediction exposure is recorded as
provenance but opening/viewing predictions alone does not invalidate a grade.

## Penalty decisions and physical damage groups

The table lists existing reviewed findings from both faces. Select a row to inspect
its original-image polygon and evidence. For every **confirmed** finding, explicitly
submit a grading decision, including when the penalty remains zero:

- Set severity **0–5**. Severity itself never changes a score.
- Select whether a penalty is warranted and enter a half-point penalty **0–9**.
  Default is zero; a positive penalty without the warranted checkbox is refused.
- Enter a specific explanation and physical damage group ID.
- If applicable, explicitly identify a confirmed structural defect from the policy
  dropdown. Then choose **Record / revise selected finding penalty and cap decision**.

Suggested findings never subtract points. Unreviewed findings must first be reviewed
in the condition tool. Rejected/reclassified findings cannot carry a positive
penalty or structural cap. Existing active confirmed findings without a grading
decision prevent calculation. No advisory penalty schedule is supplied in this slice.

Use the **same physical damage group ID** when multiple findings describe the same
damage, even across categories or faces. Choose one primary finding to own both
the penalty and structural classification; other evidence rows for that damage
must carry zero penalty and no additional cap. Multiple penalized/capped rows with
the same group ID block calculation. The software cannot recognize that two
differently named groups actually describe the same damage: final validation
requires an explicit operator attestation about pairing and deduplication.

Revisions append complete grading action snapshots. Undo/Redo restores working
grading inputs while appending an audit action; it does not erase submitted
penalties, overrides or final decisions. Undoing/revising grading inputs requires
new human validation, including after restoring equivalent inputs.

## Draft scores and centering

All category scores are **1–10 in 0.5-point increments**. The policy explicitly
chooses the following conservative front/back consolidation for this draft:

- Corners, edges and surface each start at 10. Sum their operator-assigned penalties
  across both faces and subtract from 10, with a minimum category score of 1.
- Consolidated centering is the lower of the two resolved face scores.

These consolidation choices are draft SELBY policy, not an asserted industry
standard. The score is separate from the underlying V0.2 pixel measurements and
dimensionless centering percentages. The worst imbalance across the front's
horizontal and vertical axes selects the highest qualifying threshold:

| Front score | Maximum imbalance |
|---|---|
| 10 | 55/45 |
| 9.5 | 57/43 |
| 9 | 60/40 |
| 8.5 | 62/38 |
| 8 | 65/35 |
| 7 | 70/30 |
| 6 | 75/25 |
| 5 | 80/20 |

There is no invented interpolation between those rules. Measurements beyond 80/20,
incompatible values, and incomplete/uncertain/unvalidated geometry produce an
unresolved rule proposal. Enter a reasoned **Explicit centering review / score**
to resolve such cases provisionally. Warnings and original measurements remain
visible. A resolved front rule score cannot be changed by ordinary centering review;
an exception to the final grade requires an authorized override.

**Back thresholds are undefined.** Back centering always requires an explicit
operator score and explanation. Front thresholds are never applied to the back.
The detailed result records both `rule_proposal` and effective `score`. Human
geometry review or manual scoring is not calibrated metrology.

## Final calculation, structural caps and overrides

The versioned draft policy is
`selby_workstation/policies/selby-draft-0.4.0.json`. Each dossier pins the complete
policy and its SHA-256, ID and version. Editing the installed file affects only
new dossiers. For rule changes, create a new versioned policy file/update the
default deliberately and use a new dossier/session; never edit an old dossier's
pinned policy or rewrite an existing exported decision.

The calculated final grade is:

```text
mean = (centering + corners + edges + surface) / 4
weakest_ceiling = min(the four scores) + 1
calculated = bound_1_to_10(floor(min(mean, weakest_ceiling, applicable_caps)))
```

The strictest operator-confirmed structural cap applies, independently of whether
that finding has a numeric penalty:

| Confirmed structural damage | Draft maximum |
|---|---|
| Severely crushed corner | 6 |
| Minor localized crease | 6 |
| Pronounced crease | 4 |
| Tear | 3 |
| Significant delamination | 3 |
| Severe overall alteration | 2 |

No detector assigns these structural types automatically. Operator decisions must
identify them explicitly. A confirmed crease with zero numerical penalty can
therefore still cap a card at 6 or 4.

Authorized operators can submit an integer **1–10** override with a specific
justification. Scope **grade** can override the calculated proposal. Scope
**structural_caps** bypasses the applicable draft caps but cannot exceed the
unmodified mean/weakest ceiling. Both scopes preserve the original calculated grade,
applicable caps, operator, timestamp, policy version and authorization-config hash.
An override never resolves missing inspection information and requires subsequent
human validation. A later override appends another record and invalidates the
previous final attestation.

Override access is denied by default. An administrator must configure exact
operator identifiers in `selby_workstation/override_authorization.json`:

```json
{"authorized_operators": ["YOUR_APPROVED_OPERATOR_ID"]}
```

This is a local allowlist checked by the engine, not authenticated identity or
tamper-resistant authorization. Protect it with deployment permissions. Do not use
this local mechanism alone as commercial access control.

## States, validation and persistence

| Grading state | Meaning |
|---|---|
| Draft | No attached inspection/working dossier yet |
| Incomplete | Missing face, unfinished condition review, unresolved centering, stale inputs, missing penalty decision or duplicate damage |
| Ready for operator review | All required grading inputs resolved; calculated proposal available, no final attestation |
| Human validated | Operator explicitly attested same-card pairing/deduplication and accepted the provisional proposal or authorized override |

No calculated grade is emitted for incomplete inputs. A ready proposal is not a
final operator decision. Review all warnings, the four subgrades, penalties, caps
and calculation explanation. Enter a final explanation, check the pairing/damage
attestation and choose **Human validate provisional grade**.

**Save new version** writes another exclusive inspection JSON, retaining previous
versions. It includes the grading dossier, pinned policy, append-only actions,
overrides, final decisions and `saved_grading_diagnostic` computed at that save.
The latter is a saved snapshot, not an authority for a later edited working state.
Live calculation/export always uses current grading inputs. Save/reopen, autosave,
recovery and Undo/Redo reuse the existing workstation machinery. Old V0.1–V0.3
sessions remain compatible.

**Export diagnostic** writes versioned JSON and Markdown. JSON contains complete
grading inputs/history and a current top-level `grading` result. Markdown includes
the four subgrades, mean, weakest ceiling, applicable caps, calculated/proposed/final
grades, operator explanation, front/back evidence identities and upstream statuses.
`review_status=review_required`, `automatic_acceptance=false` and
`commercial_release_authorized=false` remain independent of the grading state.

Original scans, frozen reports, reference annotations and old saved grading
versions are never overwritten. Attached source files and saved-version bases must
remain readable at their recorded paths with matching hashes. Changed/missing
evidence blocks saving/exporting and final validation. Recovery retains grading
history; in-memory Undo/Redo starts fresh after reopen, as in V0.2.

## Known limitations and validation before commercial use

- This is a transparent draft policy, not a validated commercial grading standard.
  No labeled detection/grade accuracy, inter-operator reliability, uncertainty
  budget or calibrated physical measurement is claimed.
- Pairing and damage grouping depend on honest operator attestation. Independent
  face sessions are pinned snapshots; later edits in another window are not silently
  imported. Explicitly attach the new saved version before revalidation.
- Operator identities are local text, and the history hash chain detects accidental
  inconsistency rather than providing signatures or preventing a malicious file
  rewrite. Immutable version files need external access control and backup.
- The UI and evidence checks are synchronous; large scans or large action histories
  can consume significant memory/disk and block interaction. Full snapshots and
  recovery drafts accumulate without automatic cleanup. The two export files are
  not an atomic pair. See the V0.3 guide for image, path and recovery restrictions.
- No production release switch, certificate issuance, payment/fulfillment workflow,
  back-threshold model, automatic structural classifier or new detector was added.

Before commercial use, freeze a reviewed policy, define/separately validate back
centering rules, and collect a representative labeled front/back dataset spanning
card designs, foil, scan conditions and all structural damage classes. Use blinded
independent graders and adjudication to assess agreement, penalty consistency,
damage grouping and threshold/cap boundary decisions. Separate development data
from held-out evaluation; measure false positives/negatives before making detection
claims. Validate scanner geometry, repeatability and display conditions. Exercise
crash/disk-full recovery, stale evidence, unauthorized overrides and audit tampering
under deployment permissions. Add authenticated roles, protected audit storage,
independent commercial release authorization and a documented human appeal process.

See `SELBY_WORKSTATION_V04_VALIDATION.md` for actual tests, retained evidence and the
synthetic diagnostic example.
