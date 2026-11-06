# Synthetic V0.4 grading diagnostic example

This is an automated engineering fixture, not a human assessment of a real card.
The scripted final-validation action tests that control only; it does not certify
the synthetic card or authorize release.

Card ID: `SYNTHETIC-V04-CAP-DEMONSTRATION`.
Policy: `selby-human-supervised-draft`, version `0.4.0`.

Both face inspections have completed corner, edge and surface review. Front
centering has validated, balanced synthetic geometry, yielding a rule proposal of
10. Back centering is explicitly assigned 9.5 with a note; no back thresholds apply.

| Category | Inputs | Consolidated score |
|---|---|---|
| Centering | Front 10; independently reviewed back 9.5 | 9.5 |
| Corners | Front confirmed synthetic wear, severity 2; operator warrants 1-point penalty | 9 |
| Edges | No penalized findings on either face | 10 |
| Surface | Back confirmed synthetic minor localized crease, severity 3; numerical penalty zero; explicit structural cap 6 | 10 |

The corner wear and back crease have different physical damage group IDs. There
is no duplicate penalty/cap for either damage group.

```text
Arithmetic mean: (9.5 + 9 + 10 + 10) / 4 = 9.625
Weakest-subgrade ceiling: 9 + 1 = 10
Confirmed structural ceiling: 6
Calculated grade: floor(min(9.625, 10, 6)) = 6
Overrides: none
Final operator-decision control exercised with grade: 6
```

The original calculated result remains 6. The UI state is **Human validated** in
this test artifact, with the operator identifier and final note explicitly stating
that this was an automated synthetic test. `automatic_acceptance` and
`commercial_release_authorized` remain false. The front's frozen synthetic source
report remains `review_required`.

The actual generated, versioned exports contain image hashes, source report
provenance, all penalty decisions, policy snapshot/hash, action history, geometry,
condition records and the final decision:

- [Generated Markdown diagnostic](local_data/selby_workstation/v04-validation/example/exports/inspection-5c2ed6cb-cb34-4c7f-9208-7c568f19bc04-dfe1bf7d-061d-458e-8c9f-fc5cc04244a6.md)
- [Generated JSON diagnostic](local_data/selby_workstation/v04-validation/example/exports/inspection-5c2ed6cb-cb34-4c7f-9208-7c568f19bc04-dfe1bf7d-061d-458e-8c9f-fc5cc04244a6.json)
- [Native grading screenshot after the viewer-state fix](local_data/selby_workstation/v04-validation/example/grading-native-final.png)
- [Example summary](local_data/selby_workstation/v04-validation/example/summary.json)

These generated local artifacts are retained in the workspace and ignored by Git.
The example generator refuses to overwrite its existing output directory.
