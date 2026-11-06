# SELBY Workstation V0.5c — validation

Validation date: 2026-11-02, native Windows, PySide6 Qt `windows` platform.

## Results

- Resolver/UI slice: final offscreen run **22 passed** (`--basetemp=test_tmp_run/v05c-final-isolated`). Initial run was 19 checks; saved-session resume, authorized original-image creation and local cancellation checks were then added. Test recovery drafts are now isolated under each test directory.
- Native Windows regression: **39 passed**, covering the resolver/UI tests plus existing production bridge, bridge GUI and grading GUI tests.
- Ruff check passes for the two new modules and three new validation files.
- Real entrypoint `scanner_agent/selby_desktop.pyw --smoke-test --screenshot validation_artifacts/v05c/native-launcher.png` launched the actual Windows application successfully: Dashboard, no image/report/grading/orders loaded.
- Live read-only development-backend acceptance through the actual `.pyw` entrypoint passed the assertions recorded in [live-native-acceptance.json](validation_artifacts/v05c/live-native-acceptance.json). Software supplied the QR text; no physical scanner was automated.

## Live backend findings

The existing synthetic label identity resolved to **Rafflesia EX**, **ORD-000001**, **SP-BB8D2B9652094E5DA785C08723BF042E**, **PC-2577D23CF15C43C9A350149B3755ED77**, **SLB-C-000001**. Authoritative reasons were `quote_not_accepted`, `payment_unverified`, `commercial_restriction`.

Diagnostic payload recognized without opening grading; card remained blocked; immediate duplicate suppressed; Orders and Labels both exposed the central scan action; no grading session created. Logical SQLite registry digest and complete backend production snapshot were unchanged. The temporary operator-fixture login used an in-memory credential store and was revoked. The harness forbids business POSTs and printing. No development order was edited, and no payment/custody restriction was bypassed.

The live harness produced its result but did not terminate promptly after Qt exit; its process was interrupted after the evidence was written and the temporary session revoked. Cleanup now hides its windows before requesting Qt exit. That cleanup adjustment has not been rerun against the live backend. It does not affect the application scan path.

## Exact checks and evidence

| Case | Evidence |
| --- | --- |
| Mapped PC; multiple cards in one order; identical names with distinct PCs | `test_distinct_copies_repeat_restart`: resolves each exact mapping, repeats lookup, asserts registry bytes unchanged |
| Order lookup only | Resolver and Qt tests assert exact ORD and no session |
| Diagnostic excluded from grading | Resolver works without a client; native dialog reports TEST / NOT VALID, no session |
| Invalid/truncated/version/case/URL | Seven strict decoder cases |
| Unknown/unmapped identity | Unknown PC fails without allocation |
| Voided PC | Backend active manifest mismatch rejects |
| Wrong origin/registry/conflicting binding | Fail-closed resolver cases |
| Payment restriction | Exact backend reasons preserved; native Qt asserts no session, no Orders selection mutation and unchanged registry bytes |
| Backend unavailable | Resolver propagates offline failure, no write API present in scan path |
| Repeated scans | Read-only repeated resolver calls; Qt duplicate suppression; live duplicate test |
| Text-field focus | Ordinary Orders search typing is preserved; scanning requires the dedicated field |
| Existing saved dossier | Real Session save/association/resume test verifies session ID, PC-selected SLB-C and unchanged evidence hash |
| New local inspection session | Explicit button revalidates eligibility: revoked payment prevents creation; restored synthetic eligibility opens existing image picker; no automatic dossier association |
| Local terminal lifecycle | Cancelled local card remains blocked with unchanged status |
| Restart | Resolver reopens the registry on every call, saved suffix preferences use QSettings; real application startup smoke test |
| Grading/bridge regression | Existing bridge persistence, explicit association and grading GUI tests included |

Native screenshots:

- [Real launcher](validation_artifacts/v05c/native-launcher.png)
- [Live diagnostic](validation_artifacts/v05c/live-diagnostic.png)
- [Live unpaid card](validation_artifacts/v05c/live-unpaid-blocked.png)
- [Labels navigation](validation_artifacts/v05c/live-labels.png)
- [Synthetic identity result](validation_artifacts/v05c/identified-card.png)
- [Saved inspection resume](validation_artifacts/v05c/resumed-inspection.png)

## Reproduction

Run from the repository root in PowerShell. Use a new basetemp directory on each run (pytest manages that directory). The parent artifact directory must exist and be writable by the Windows account running Qt.

```powershell
$env:QT_QPA_PLATFORM='windows'
$env:SELBY_SCAN_SCREENSHOTS="$PWD/validation_artifacts/v05c"
scanner_agent/.venv-analysis/Scripts/python.exe -m pytest scanner_agent/tests/test_scanning.py scanner_agent/tests/test_scanner_ui.py scanner_agent/tests/test_production_bridge.py scanner_agent/tests/test_production_bridge_gui.py scanner_agent/tests/test_selby_grading_gui.py -q -p no:cacheprovider --basetemp=validation_artifacts/v05c/native-final-02
scanner_agent/.venv-analysis/Scripts/python.exe -m ruff check scanner_agent/selby_workstation/scanning.py scanner_agent/selby_workstation/scanner_ui.py scanner_agent/tests/test_scanning.py scanner_agent/tests/test_scanner_ui.py scanner_agent/tests/probe_scan_navigation.py
```

`probe_scan_navigation.py` requires the existing local development backend on 127.0.0.1:8000, a confirmed original registry mapping, and the documented local operator fixture. It reads the fixture credential without logging it and revokes its temporary session. Its live blocked-state assertion intentionally fails if the development fixture becomes eligible; do not change orders to satisfy it.

Two early native attempts failed before test execution because of test-directory ownership and a missing parent directory. The subsequent native runs used a writable artifact directory. These were environment setup failures, not passing checks.

## Limits and pending acceptance

Actual TD-W6 USB/Bluetooth mode, suffix, Windows keyboard layout, physical printed QR readability and unplug/reconnect behavior remain **unverified**. PnP inventory alone cannot identify which generic keyboard is TD-W6. COM3 is a Bluetooth serial link, not confirmed scanner transport. No physical scan or print was performed or automated. Human-operated diagnostic and valid synthetic-label scans are still required; see [operator instructions](SELBY_WORKSTATION_V05C_OPERATOR.md).

The input surface supports HID keyboard events rather than raw-device identification, and does not monitor scanner connection. It must be opened before scanning. While lookup is pending, additional scans are not queued. No automatic routing from unrelated text fields is attempted.

Production QR v1 contains neither backend origin nor registry UUID. The resolver verifies the complete identity against the selected local mapping and its configured authoritative backend; it cannot extract origin metadata that the payload does not contain.

The backend production snapshot evaluates inspection `start`. An existing backend custody/inspection dossier may return `operation_conflict`; this slice conservatively blocks it and does not issue custody resume/start commands. Existing local saved-session resume is tested with an eligible backend snapshot. Backend custody transitions remain in their established authorized workflow. Live paid eligibility was not manufactured or demonstrated; eligible creation/resume uses controlled synthetic responses in native Qt tests.

No server lock spans the UI transition or native file chooser. Backend mutation endpoints retain their own independent eligibility checks. No scan introduces a backend mutation or commercial authorization. The existing explicit image/dossier/association workflow remains responsible for evidence pairing.
