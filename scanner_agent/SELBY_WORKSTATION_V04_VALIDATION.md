# SELBY V0.4 implementation and validation — 2026-10-23

## Actual results

| Validation | Result |
|---|---|
| Complete scanner/workstation regression | **446 passed, 0 failures/errors/skips**, 33.61 s |
| Focused V0.1–V0.4 workstation suite | **95 passed**, 10.28 s |
| New grading coverage within those runs | **41 model/policy tests and 2 Qt workflow tests** |
| Ruff on all changed Python modules/tests | Passed |
| Native Windows real-scan startup | Exit 0, `platform=win32`, grading panel loaded, real image plus two frozen reports loaded, automatic acceptance false |
| Native synthetic grading dossier reopen | `qt_platform=windows`, state Human validated, grade 6, saved dossier unchanged |
| Protected evidence integrity | **367 readable files checked, zero changes**, including the real original and frozen source reports |

The full regression includes scanner/storage, geometry, references, native
workstation and Chrome reference-editor tests. Native/Chrome runs used the normal
Windows environment outside the restricted sandbox. No backend or frontend
commercial-service code changed, so those separate suites were not run.

From `scanner_agent`, the exact final regression command was:

```powershell
.\.venv-analysis\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp local_data/selby_workstation/v04-validation/regression-final --junitxml local_data/selby_workstation/v04-validation/regression-final.xml --tb=short
```

The focused command was:

```powershell
.\.venv-analysis\Scripts\python.exe -B -m pytest tests/test_selby_grading.py tests/test_selby_grading_gui.py tests/test_selby_session.py tests/test_selby_v02.py tests/test_selby_condition.py tests/test_selby_condition_gui.py tests/test_selby_gui.py -q -p no:cacheprovider --basetemp local_data/selby_workstation/v04-validation/focused-final2 --junitxml local_data/selby_workstation/v04-validation/focused-final2.xml --tb=short
```

Use fresh output-directory names on future runs; pytest can replace an existing
basetemp. No cleanup was performed during this work.

## Delivered vertical slice

- Dedicated native **Grading** workbench and `--grading` launch flag, reusing the
  existing session/condition tools and existing finding IDs.
- Separate front/back inspection snapshots in one card dossier; explicit card
  identity/pairing attestation; same-image pairing refused; saved-session and
  original/source provenance retained and checked.
- Explicit severity, zero-default penalty/warrant decisions, notes and revisions.
  No points deducted from suggestions or severity alone. Confirmed findings need
  an explicit grading decision. Active unreviewed information prevents calculation.
- Operator-assigned physical damage groups; one primary penalized/capped finding
  per group. Duplicate primary decisions block the proposal.
- Pinned JSON policy with supplied front thresholds and all six structural caps.
  No back thresholds. Explicit review resolves back/uncertain centering. Front
  rule proposal, effective score and underlying V0.2 measurements are separate.
- Four half-point subgrades, conservative mean/weakest/cap/floor calculation,
  original calculated result and separate authorized override/final decision.
- Append-only grading action ledger and immutable saved versions. Undo/Redo changes
  working inputs while preserving submitted actions, overrides and final decisions.
- Save/reopen, recovery and full versioned JSON/Markdown grading exports; all
  upstream review/blocked metadata retained. No commercial-release authorization.

The draft policy explicitly chooses sum-of-penalties across faces for condition
categories and the lower resolved face score for centering. These are documented
draft choices. No detection algorithm or reference annotation was added or changed.

## Representative checks

Tests exercise positive penalties and their removal; rejected/unreviewed finding
guards; zero automatic penalties; all supplied centering thresholds at/around
boundaries; unknown back rules; uncertain geometry and explicit review; full 10/10
candidates; weakest ceilings and integer flooring; all six structural caps;
multiple defects and strictest-cap precedence; cross-face consolidation; duplicate
damage; missing/stale evidence; override allowlist and audit preservation; grading
initialization/penalty Undo/Redo; recovery; policy pinning despite installed rule
changes; source status and production gate preservation; and complete Qt lifecycle.

Visual inspection of the native example found one confirmed usability defect:
opening a previously engine-graded session displays source predictions and records
viewer exposure, which initially made the new grading attachment appear stale.
The fix preserves exposure provenance while excluding that view-only flag from
the decision staleness comparison. Geometry/review/finding/operator changes still
invalidate the attachment. A dedicated Qt regression covers engine-to-GUI reopen;
the corrected native screenshot shows the retained Human validated grade of 6.
Earlier successful runs (including 444 cases before the final additions) and
earlier failed development attempts remain as separate artifacts.

## Example and evidence

See [the synthetic example](SELBY_WORKSTATION_V04_EXAMPLE.md). Its subgrades
9.5/9/10/10 yield mean 9.625, weakest ceiling 10 and a confirmed localized-crease
cap of 6, producing grade 6. Both face inputs and decisions are synthetic; this
does not claim a real card received a human assessment or measured grade accuracy.

Retained artifacts under `local_data/selby_workstation/v04-validation/`:

- `regression-final.xml`: authoritative final full-suite results.
- `focused-final2.xml`: final focused suite.
- `windows-native.png`: grading startup with the existing real scan.
- `example/exports/`, `example/sessions/`, `example/input-sessions/`: separate
  synthetic grading diagnostics and versioned inspection evidence.
- `example/grading-native-final.png`, `example/gui-final-check.json`: corrected
  native dossier verification, saved-version integrity and protected-file checks.
- `example/protected-before.json`: current integrity baseline for 367 readable
  protected paths inherited from V0.3. Historically inaccessible test paths are
  outside this claim; the required real scan/reports were readable and checked.
- `generate_example.py`, `check_example_gui.py`: retained engineering harnesses.
- All earlier XML/screenshot/test artifacts retained; no originals overwritten.

## Remaining limitations and commercial validation

No unresolved functional failure was observed in the final tests. Validation is
bounded by these synthetic cases and native launches; it is not a detection or
commercial-grade accuracy evaluation.

Policy thresholds, consolidation, penalty judgments and structural caps remain
provisional. Detection suggestions remain experimental. Back scores, card pairing
and damage grouping require operator judgment. There is no calibrated metrology,
authenticated operator identity, signed/protected audit service, automatic source
relinking, retention management or production release mechanism. The override
allowlist is local configuration and must not be represented as secure commercial
authorization. Synchronous evidence loading and full audit snapshots can be costly
for large scans/histories. JSON and Markdown are separate writes; disk failure and
path availability remain existing persistence constraints.

Before commercial deployment, follow the protocol in the
[operator guide](SELBY_WORKSTATION_V04.md#known-limitations-and-validation-before-commercial-use):
review/freeze rules, collect representative independently labeled evidence, assess
blinded inter-grader agreement and damage deduplication, define back rules,
validate scanner repeatability and display conditions, stress persistence/audits,
and implement authenticated roles plus independent commercial-release approval.

No commits, migrations, broad refactoring or cleanup were performed.
