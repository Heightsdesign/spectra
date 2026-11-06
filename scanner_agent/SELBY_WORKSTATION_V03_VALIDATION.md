# SELBY V0.3 final validation — 2026-10-23

## Result and scope

**403 passed, 0 failed, 0 skipped** in the complete `scanner_agent/tests` suite
(28.88 seconds), including **52 workstation cases**. The scope includes scanner,
image integrity, reference editors, geometry, centering, workstation persistence
and Qt condition workflows. Backend/frontend commercial application suites were
not run because this consolidation changes only the native scanner workstation.

Command, from `scanner_agent`, with native Windows/Chrome access:

```powershell
.\.venv-analysis\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp local_data/selby_workstation/v03-final-validation/final-tests --junitxml local_data/selby_workstation/v03-final-validation/final-suite.xml --tb=short
```

Use a fresh basetemp name for any subsequent run to retain these artifacts; pytest
can replace an existing basetemp. Ruff checks passed for both changed Python files.

The initial invocation had 179 passes and 223 setup errors because its basetemp
parent did not yet exist. The first completed sandbox run had 399 passes and three
Chrome DevTools failures in legacy reference-editor tests. Those three passed
outside the sandbox, followed by the clean complete 403-case final run. These
were validation-environment failures, not changes to the detector or editor code.

## Verified working features

| Check | Actual result |
|---|---|
| Native Windows launch | Exit 0; `platform=win32`, original loaded, two source reports loaded, condition window opened, automatic acceptance false |
| Real scan | Tritox original, 2005 × 2582 RGB24 BMP; exact command in the V0.3 guide |
| Four corners | Four views; 26 experimental suggestions produced |
| Four edge strips | Four views; 45 experimental suggestions produced |
| Surface | Full original view; 12 experimental suggestions produced |
| Decisions | Unreviewed → confirmed → reclassified → rejected exercised; category review completion verified |
| Manual annotations | All nine views exercised; synthetic Qt mouse drags checked against expected original-image polygons |
| Coordinates | Synthetic rotated extraction tests passed; real patch/original round-trip maximum error below 5 × 10^-13 pixels |
| Session lifecycle | Versioned save, model reopen, GUI reopen, recovery snapshot and full condition equality verified |
| Exports | JSON/Markdown generated; complete condition payload, new inspection kind/prefix/heading and preserved review gates verified |
| Integrity | 367 readable protected files hashed before/after; zero changes, including the real scan, both frozen source reports and previous session |

Real-scan diagnostics took approximately 0.24 s for corners, 0.49 s for edges and
0.64 s for surface in this single run, including the diagnostic action's UI work.
These timings are observations, not performance guarantees or detection accuracy.
Native screenshots were visually inspected for all three categories.

The real-scan workflow was automated with explicitly labeled test-only operator
notes and candidate-seeded geometry. Temporary confirmation/reclassification
transitions exercised controls; **all 92 final findings (83 suggestions plus nine
manual test boxes) were rejected and zero remained confirmed**. Review stamps in
these artifacts represent automated workflow tests, not human assessment of the
card. Both frozen source statuses remained `review_required`.

## Consolidation changes

- Renamed new export filenames from `centering-...` to `inspection-...`, JSON kind
  from `selby_centering_diagnostic` to `selby_inspection_diagnostic`, and Markdown
  heading to **SELBY inspection diagnostic**. Existing artifacts/session schema
  were preserved. Integrators must update consumers that match the old export kind.
- Added an end-to-end synthetic Qt test for all categories, each review transition,
  manual mapping in all nine views, category completion, persistence, recovery and
  export contents. Existing features were reused without refactoring.
- Added the V0.3 operator guide and this report. No algorithm, frozen report,
  original scan or reference annotation was changed; no commits or cleanup ran.

## Experimental features and unresolved issues

No application crash, data-loss failure or incorrect coordinate mapping was
observed in this validation. This is bounded evidence, not proof that all inputs
or failure modes are covered. No functional defect requiring a code fix was
confirmed beyond the misleading export labels.

Visual suggestions remain experimental: no labeled dataset, measured precision or
recall, severity estimation or dedicated scratch/dent classifier. Background,
printed texture and foil can create false positives. Fixed candidate limits and
surface-mask erosion limit coverage. The real-run coordinate round trips verify
the affine implementation, not the correctness of the seeded physical boundaries.

Known persistence limits remain: disk failure can stop saves/autosave; JSON and
Markdown exports are not an atomic pair; pending gestures are uncommitted;
reopening requires evidence/ancestor paths; history and drafts grow without a
retention cap. Large-image processing is synchronous. These were documented,
not expanded into new persistence or packaging features.

The inherited integrity manifest also contains 4,152 unavailable historical test
artifact paths. They were explicitly recorded as unavailable and excluded from
the 367-file before/after claim. Required real image/source/session files were
readable and mandatory checks.

## Commercial use and V0.4 readiness

Commercial grading/acceptance remains unsupported: detection performance,
calibrated metrology, authenticated operator attribution, signed audit records,
front/back aggregation and business approval controls are absent. No scores or
automatic acceptance were introduced, and upstream blocks remain independent.

Ready for V0.4 integration as an assisted internal workflow: corner/edge region
views, original-coordinate annotations, explicit decisions/history, provenance,
versioned session storage/recovery and complete inspection diagnostic exports.
Detection outputs must remain suggestions until evaluated on labeled evidence.

## Evidence retained

All generated artifacts remain under
`local_data/selby_workstation/v03-final-validation/` (ignored local data):

- `final-suite.xml`: authoritative final full-suite result.
- `browser-native.xml`: three successful browser retries.
- `workflow-check.xml`: focused condition GUI run, three passes.
- `windows-native.png`: CLI native startup screenshot.
- `real-corners.png`, `real-edges.png`, `real-surface.png`: native workflow views.
- `real-workflow.json`, `validate_real_workflow.py`: real-run assertions and harness.
- `real-sessions/`, `real-drafts/`, `real-exports/`: separate test-only artifacts.
- `protected-current-before.json`: current readable-file integrity baseline.
- Earlier XML results and all test directories retained, including failed attempts.
