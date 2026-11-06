# SELBY V0.5b — label printing UI integration

## Root cause

The printing implementation existed but its desktop integration was incomplete. `DesktopShell` still constructed a disabled, hard-coded **Labels · future** placeholder and did not register a Labels page. V0.5b's only entry point was **Incoming orders → Print labels…**. `OrdersDialog` had no label action and no route from an existing local ORD to its confirmed backend SP/PC mappings. The earlier standalone label-dialog tests did not exercise desktop navigation or the imported local-order workflow.

This was not a missing Munbyn driver or an alternate installation. The running Windows command line was:

```text
C:\Users\plher\Documents\spetra\scanner_agent\.venv-analysis\Scripts\pythonw.exe -B C:\Users\plher\Documents\spetra\scanner_agent\selby_desktop.pyw
```

`Launch_SELBY.vbs` selects that virtual environment, sets `scanner_agent` as working directory and runs `selby_desktop.pyw`; the .pyw imports `selby_workstation.__main__.main`. That creates the same Workstation/DesktopShell audited here. The environment fallback is `.venv-workstation` only if `.venv-analysis` is absent. No packaged alternate UI was involved. Existing processes retain the UI imported at startup and must be reopened to see source changes. The launcher itself did not need modification.

Two additional UI defects were corrected: rendering a preview replaced the only eligibility/status text, and the generic worker-completion handler re-enabled print buttons after preview even when printing was blocked. The print handler/backend still rejected those jobs, but the enabled appearance was misleading. Eligibility now has a permanent visible panel and control state is recomputed after every operation.

## Result and operator path

A fresh native Workstation was launched with the actual `scanner_agent/Launch_SELBY.vbs`. Its window title is **SELBY · Workstation V0.5b**, with an active **Labels** navigation button (Ctrl+7). Existing operator windows were not terminated, to preserve unsaved work. Use the fresh window, or close/reopen an older window normally.

1. Sign in through **Incoming orders** using the existing backend operator account.
2. Open **Labels**, select **ORD-000001**, and click **Open label previews / printing**.
3. Select the order row or an individual **SLB-C → PC** row, then **Preview selected label**. The preview and print actions are grouped above the image.
4. The persistent amber panel explains current backend blockers. Disabled print buttons have matching explanations. Previewing never sends a print job.

The alternate path is **Orders → select ORD-000001 → Print labels / preview…**. This opens Labels with that order selected. Local orders without a confirmed bridge mapping have a disabled Orders action with an explanation. Labels never creates or confirms a mapping.

## Changed files

| File | Change |
| --- | --- |
| `scanner_agent/selby_workstation/desktop.py` | Registers active Labels navigation/page, preserves existing keyboard shortcuts, adds order-to-Labels routing, explains the remaining disabled Scanner placeholder |
| `scanner_agent/selby_workstation/orders_ui.py` | Adds the selected-order Print labels / preview action; disables it for missing/unconfirmed mappings with an explicit explanation |
| `scanner_agent/selby_workstation/label_mapping.py` | New read-only SQLite mapping reader and backend/local registry, origin, ORD/SP, PC UUID/reference and SLB-C manifest checks |
| `scanner_agent/selby_workstation/labels_page.py` | New dark Labels module with mapped-order selector, sign-in route, embedded existing label dialog, and safe selection/refresh handling |
| `scanner_agent/selby_workstation/labels_ui.py` | Accepts verified mapping context, displays ORD and SLB-C/PC associations, makes preview GET-only with fresh eligibility/mapping checks, keeps blockers visible and print controls correctly disabled, explains disabled actions, reports busy state to the containing screen |
| `scanner_agent/selby_workstation/app.py` | Prevents closing the Workstation while an embedded label operation is active |
| `scanner_agent/tests/test_labels_navigation.py` | Thirteen new cases for navigation, Orders routing, read-only registries, preview-only behavior, blocked controls and mapping/auth/network/staleness failures |
| `scanner_agent/tests/probe_labels_navigation.py` | Manual native acceptance harness through the real .pyw entry point; hardware and backend business writes are forbidden |
| `SELBY_WORKSTATION_V05B.md`, `SELBY_WORKSTATION_V05B_OPERATOR.md` | Links and instructions for the integrated route |
| This report and `validation_artifacts/v05b-navigation/*` | Native acceptance results and screenshots |

No launcher, backend business logic, database schema, payment evidence, production identity, custody state, reconciliation record, grading evidence or protected research was changed. The prior print claim/idempotency/reprint/audit behavior remains in place for actual operator-confirmed print attempts. Pure previews now use GETs and local rendering; they do not append a backend print event or local print-attempt journal entry.

The mapping reader opens SQLite with `mode=ro`; it does not instantiate `ProductionStore`, migrate a legacy registry, allocate IDs or create a missing registry. Confirmed mappings are checked against a fresh backend production snapshot before label loading and before every preview. Another origin, registry, parent order, PC manifest, voided active selection or changed local selection fails closed. The existing backend remains authoritative for every actual print claim, including payment and inspection eligibility.

## Native acceptance — existing development order

The final acceptance ran through the actual `selby_desktop.pyw` entry point on the **windows** Qt platform, with the real configured local backend and the existing local registry. UI navigation and preview rendering were exercised against the real order, not substituted manifests.

The saved Windows operator session was not usable. Validation signed in through the existing sign-in UI using the documented local operator fixture, with its session stored only in memory and revoked on exit. Passwords/tokens were not printed or copied to reports. No account roles or passwords were changed, and the operator's saved Windows credential was not replaced by the fixture session.

| Identity | Verified reference |
| --- | --- |
| Local order | `ORD-000001` |
| Backend order | `SP-BB8D2B9652094E5DA785C08723BF042E` |
| `SLB-C-000001` | `PC-2577D23CF15C43C9A350149B3755ED77` |
| `SLB-C-000002` | `PC-D1C6766C89B5488DB5153ECC0890D45A` |

All three previews rendered. OpenCV independently decoded their displayed QR images to exactly:

```text
SP:ORDER:1:SP-BB8D2B9652094E5DA785C08723BF042E
SP:PC:1:PC-2577D23CF15C43C9A350149B3755ED77
SP:PC:1:PC-D1C6766C89B5488DB5153ECC0890D45A
```

Printing remained disabled both before and after previews. Actual backend blockers were `payment_unverified`, `quote_not_accepted` and `commercial_restriction`. The screen explicitly explains that independent payment verification is required and previews remain available. No blocker was removed, ignored or overridden.

The complete local registry logical digest was identical before and after:

```text
5e2d5c6225ad9919c7823d82e0a549912be040dd90d0c4ef7bb323c5450cd7ea
```

The complete backend submission snapshot, including physical-card state and intake audit history, also matched before/after. The harness rejects all `IntakeClient.execute` calls and all native printer creation/submission calls. Results: **3 previews, 0 backend business POSTs, 0 physical print jobs**. Authentication login/logout is separate from business POSTs.

Evidence:

- [Order preview in the native Workstation](validation_artifacts/v05b-navigation/windows-labels-preview-0.png)
- [SLB-C-000001 / first PC preview](validation_artifacts/v05b-navigation/windows-labels-preview-1.png)
- [SLB-C-000002 / second PC preview](validation_artifacts/v05b-navigation/windows-labels-preview-2.png)
- [Read-only native acceptance result](validation_artifacts/v05b-navigation/native-acceptance.json)
- [Actual VBS launcher process/window result](validation_artifacts/v05b-navigation/launcher-launch.json)

The actual launcher produced the expected virtual-environment redirector/child process chain and a visible Workstation window. Native scripted acceptance uses the same .pyw entry point, with safety guards and automation injected by the external test harness; the final VBS-launched operator window has no injected test hooks.

## Exact validation commands and results

From the repository root:

```powershell
$env:QT_QPA_PLATFORM='windows'
$env:PYTHONPATH='scanner_agent'
scanner_agent/.venv-analysis/Scripts/python.exe -m pytest scanner_agent/tests/test_labels_navigation.py scanner_agent/tests/test_thermal_labels.py scanner_agent/tests/test_selby_desktop.py -q -p no:cacheprovider --basetemp=validation_artifacts/v05b-navigation/native-tests-02
# 31 passed, 9.29 s

scanner_agent/.venv-analysis/Scripts/python.exe scanner_agent/tests/probe_labels_navigation.py --local-fixture-login
# Exit 0; windows platform; existing ORD-000001; 3 QR decodes; unchanged registry/backend order; no printing

scanner_agent/.venv-analysis/Scripts/python.exe -m pytest scanner_agent/tests/test_production_bridge.py scanner_agent/tests/test_intake_void_gui.py scanner_agent/tests/test_selby_incoming.py -q -p no:cacheprovider
# 31 passed, 14.60 s

scanner_agent/.venv-analysis/Scripts/ruff.exe check scanner_agent/selby_workstation/label_mapping.py scanner_agent/selby_workstation/labels_page.py scanner_agent/selby_workstation/labels_ui.py scanner_agent/tests/test_labels_navigation.py scanner_agent/tests/probe_labels_navigation.py
# All checks passed
```

The thirteen new cases cover the full mapped-order screen/Orders route; origin, registry, order, pair, reference, void, unconfirmed and stale-local-context rejection (eight parameters); missing/legacy registry read-only behavior; and offline, expired-auth and stale-preview failures (three parameters). Existing thermal tests retain batch confirmation, claim/reprint safety and file-only Qt PDF output. No automated regression submits physical jobs.

An exploratory offscreen run did not reproduce native Windows font metrics and triggered the existing full-reference-fit guard; the release acceptance and combined label/desktop suite explicitly use the native Windows platform, where the complete references render and QR decode checks pass. The final native harness exits cleanly; its temporary fixture session is revoked. Headless font portability is not claimed.

This integration does not implement payment verification, grant quote acceptance, clear commercial restrictions or complete physical printer calibration. The real printer test remains separately operator-controlled. Nothing was deployed to production.
