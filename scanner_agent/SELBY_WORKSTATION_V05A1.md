# SELBY Workstation V0.5a.1 — Unified desktop UI

## Launch on this Windows workstation

Double-click **`Launch_SELBY.vbs`** in `scanner_agent`. It locates the existing
`.venv-analysis\Scripts\pythonw.exe` (or `.venv-workstation` fallback) relative to
itself and opens `selby_desktop.pyw` without a command prompt. The launcher was
tested on native Windows. A missing environment produces a visible setup message;
the Python entry point also displays unexpected startup errors.

The standard console entry point opens the same Dashboard without business flags:

```powershell
Set-Location 'C:\Users\plher\Documents\spetra\scanner_agent'
.\.venv-analysis\Scripts\python.exe -B .\selby_workstation.py
```

Dependencies remain in `requirements-workstation.txt`. No installer or dependency
installation is performed by the launcher. If the environment is missing, use
the existing environment setup instructions in `SELBY_WORKSTATION.md` before launch.
Windows deployments that disable VBScript may instead use a shortcut whose target
is the full path to the environment's `pythonw.exe`, followed by `-B` and the quoted
full path to `selby_desktop.pyw`.

## Audit and implementation boundaries

The entry points, main inspection window, Orders/Grading/Condition dialogs,
session replacement/dirty-state handling, orders service and existing Qt tests
were inspected before implementation. The V0.4 and V0.5a guides and validation
reports were reviewed. The working tree already contained extensive staged and
untracked changes; no staging, cleanup, commit, history rewrite or unrelated edit
was performed. Git status used a command-scoped safe-directory exception only.

The audit found existing GUI access to orders, inspection, grading and condition
inspection through toolbar actions. `--orders` was an initial-workbench shortcut,
not a requirement for order creation. The missing pieces were unified navigation,
Dashboard/Settings, card-to-session reopening, and persistent workbench context.

Integration reuses `Workstation` as the main window, its original inspection
surface/state/save/recovery machinery, the existing `OrdersDialog` with its
`OrderStore`, and `GradingDialog`. New `desktop.py` adds navigation and local UI
preferences. Orders and Grading are embedded as widgets in scrollable pages;
they no longer block main navigation. The existing Condition inspection remains
an auxiliary modal inspector: close it to return to main navigation.

The orders persistence service, immutable identities, schema, session loader,
grading engine, policy, authorization configuration and evidence/export formats
were not changed. Existing saved sessions are never automatically linked or
migrated. The unchanged serialization engine retains its V0.4 tool version.

## Navigation

The default window has a persistent left navigation column and two-line context
header. Checked navigation buttons identify the current module. Native Qt styling
is shared with the existing application; dense workbenches scroll when the display
is too small to show all controls.

| Module | Actions |
|---|---|
| Dashboard | Order/card counts, browse intake, open original or saved session, resume inspection, return to selected order |
| Orders | Existing order creation/search, customer updates, batch card creation, direct card lookup, statuses, record/audit details, explicit association, linked inspection/grading opening |
| Inspection | Original canvas and all existing image/report/session/save, line editing, validation, recovery, export and Condition actions |
| Grading | Existing V0.4 dossier, face attachment, penalties, centering review, overrides, validation, save and export; an actionable landing page when no inspection is loaded |
| Settings | Current registry/recovery/preferences paths, confirmed registry selection, read-only authorization and grading-policy inspection |

**Labels** and **Scanner** are disabled future features. No printing, barcode
parsing, scanner hardware workflow or label generation was added.

Keyboard workflow: **Ctrl+1–5** select modules in the order above. **Ctrl+L** opens
Orders and focuses/selects the exact internal-card lookup field. Enter performs
lookup; Tab/Shift+Tab move through ordinary form controls. This prepares a focus
target for a future keyboard-wedge scanner, but does not parse barcode input.
Existing inspection Undo/Redo shortcuts remain available.

## Order/card-to-grading workflow, entirely through the GUI

1. Choose **Orders**, enter the operator identity, choose **New order / clear
   form**, enter customer/contact details and **Create order**.
2. Set the number and optional description, then **Add cards**. Click a card or
   enter its exact internal ID and press Enter. Orders without cards explain how
   to add them; empty searches explain how to clear the query or create an order.
3. If the card has a saved-session link, choose **Open linked inspection** or
   **Open linked grading**. The existing adapter verifies the pinned saved version
   and its required evidence before opening. A changed/missing session or image
   shows an error with restoration guidance and leaves the active session intact.
4. Choose **Orders** to return. The selected order/card, unsubmitted Orders fields,
   active inspection object, working grading inputs and dirty state remain alive.
   Choosing the same linked workflow again resumes that working session, preserving
   unsaved edits instead of reloading its saved snapshot.
5. To work on another linked session, first save the current inspection using
   **Save new version**, or explicitly accept the existing discard confirmation.
   Cancel keeps the current session. Unfinished canvas gestures must be completed
   or cancelled before a linked-session replacement.

The header deliberately separates **Selected order/card**, **Active session**, and
**Linked production card**. Browsing another order or selecting another card does
not relabel the active session. Directly opening a scan/session/recovery clears
the verified active-card context; it does not change any persistent link.

For an unlinked card, **Open linked…** explains what is missing and creates
nothing. Use **Inspection tools / open scan…**, then **Open scan** or **Open
session**. Complete the existing inspection and grading workflow, explicitly
create a dossier with the intended card identity, and **Save new version**.
Return to Orders, select the card, enter the operator and physical-pairing reason,
then **Associate saved grading session…**. Confirm the chosen card/file mapping.
Legacy dossier labels are preserved, and conflicting `SLB-C-…` identities are
rejected by the unchanged adapter. No default association or automatic dossier
creation occurs.

The GUI confirms cancellation, completed/shipped status submissions, authorized
status corrections, saved-session association, unlink corrections and registry
switches. Model authorization/reason requirements still apply after confirmation.
Existing final-grading attestation and override policy remain unchanged. Ordinary
registry operations commit immediately, as in V0.5a; unsubmitted form text is not
a persisted record and is not saved across application shutdown.

## Settings and persistence

Registry choice is saved using Qt `QSettings` INI format in
`local_data/selby_workstation/desktop.ini`. Only the registry path is persisted by
this increment; inspection/registry operator fields retain their existing behavior.
The default orders registry remains the V0.5a path. Choosing an existing registry
requires confirmation, checks compatibility read-only before invoking `OrderStore`,
clears selected order/card and unsubmitted Orders forms, and leaves the active
inspection open. It does not merge independent registries or change IDs. An
unrelated SQLite database is rejected without adding tables or changing its bytes.
**Use default orders registry** can initialize the normal empty registry if absent.

Policy and allowlists are visible read-only in Settings. Changing authorization,
grading policy, or deployment permissions remains an administrator-managed file
operation; this UI does not grant its own correction/override permissions. Recovery
and saved-evidence paths are displayed rather than silently changed/relinked.

Existing CLI options remain useful for diagnostics and initial selection:
`--image`, `--physical`, `--printed`, `--session`, `--orders`, `--grading`,
`--condition`, `--orders-store`, `--smoke-test`, and `--screenshot`. Input flags open
Inspection, and the selected initial-workbench flags open their modules inside the
same main window (Condition retains its auxiliary inspector). A CLI store override
applies to that run and does not overwrite the saved GUI preference. Smoke metadata
now includes `current_module`; Orders/Grading screenshots capture the unified shell.

## Remaining GUI limits

- Permanent association still requires a saved grading dossier. Inspection-only
  sessions can be opened through **Open session**, but cannot be persistently
  attached to a card through the existing V0.5a adapter.
- There is one active inspection/grading session at a time. Save before replacing
  it. To inspect a separate opposite face while retaining the dossier, save the
  dossier, open/inspect/save that face, reopen the dossier and explicitly attach
  the saved face. Multiple simultaneous sessions are not added.
- Condition inspection is a modal auxiliary window; close it before changing
  main modules. Large existing images/histories load synchronously.
- Administrative allowlist/policy edits, environment installation, backups,
  evidence-path restoration and permission management are not GUI workflows.
- Audit/card details retain the existing JSON presentation; dense panels require
  scrolling. There is no pagination, barcode parsing, printing, hardware scanner
  integration, commercial release control or new grading logic.
- Local identities and authorization retain the security/backup limits described
  in the V0.4/V0.5a guides. This UI integration is not production-readiness evidence.

See `SELBY_WORKSTATION_V05A1_VALIDATION.md` for actual results and native screenshots.
