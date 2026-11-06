"""Desktop custody transport against the actual FastAPI/PostgreSQL contracts."""
# ruff: noqa: F811 -- imported pytest fixtures are intentionally named as test arguments.

import os
import subprocess
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
from app.auth import now
from app.customer_models import CustomerSession
from app.intake_models import PhysicalCard, StaffMembership
from app.submission_models import SubmissionEntry
from sqlalchemy import select
from test_workstation_v05a3 import PASSWORD, auth_service, native_backend  # noqa: F401


def setup(fixture, tmp_path, admin=True):
    from selby_workstation.intake_journal import IntakeJournal

    origin, _, db, _, operator, _, items = fixture
    if admin:
        db.get(StaffMembership, operator.id).role = "admin"
        db.commit()
    auth = auth_service(fixture)
    auth.sign_in("desktop-operator@example.invalid", PASSWORD)
    return (
        auth,
        auth.intake_client(),
        IntakeJournal(tmp_path / "requests.sqlite3"),
        str(items[0].id),
    )


def perform(journal, client, sid, kind, payload, target=None):
    scope = client.connection.credential_target
    intent = journal.begin(scope, sid, kind, payload, target)
    return journal.run(scope, intent, client)


def decision(journal, client, sid, action):
    return perform(
        journal,
        client,
        sid,
        "transition",
        {"action": action, "reason": "Explicit synthetic custody decision"},
    )


def clear_rejected(journal, client, sid):
    # Simulate the explicit UI review, after a fresh authoritative read.
    scope = client.connection.credential_target
    client.load(sid)
    journal.finish(scope, journal.pending(scope, sid))


@pytest.mark.parametrize("quantity", [1, 2, 4])
def test_desktop_receive_copies_multiple_parcels_match_complete(native_backend, tmp_path, quantity):
    auth, client, journal, sid = setup(native_backend, tmp_path)
    _, _, db, _, _, _, _ = native_backend
    entry = db.scalar(select(SubmissionEntry).where(SubmissionEntry.submission_id == UUID(sid)))
    # Synthetic fixture configuration only, before the workflow snapshot.
    entry.quantity = quantity
    db.commit()
    original = (entry.card_name, entry.quantity, entry.language)
    data = perform(
        journal,
        client,
        sid,
        "parcel",
        {"carrier": "", "tracking": "", "notes": "First parcel physically arrived"},
    )
    if quantity > 1:
        data = perform(
            journal, client, sid, "parcel", {"notes": "Second parcel physically arrived"}
        )
    parcels = [p["id"] for p in data["parcels"]]
    decision(journal, client, sid, "override")
    decision(journal, client, sid, "begin")
    for index in range(quantity):
        data = perform(
            journal,
            client,
            sid,
            "card",
            {"parcel_id": parcels[index % len(parcels)], "notes": "Individual physical copy"},
        )
        unmatched = next(c for c in data["cards"] if c["entry_id"] is None)
        data = perform(
            journal,
            client,
            sid,
            "match",
            {"entry_id": str(entry.id), "reason": "Operator verified this particular copy"},
            unmatched["id"],
        )
    data = decision(journal, client, sid, "complete")
    assert data["status"] == "reconciled" and data["received_quantity"] == quantity
    assert len({c["id"] for c in data["cards"]}) == quantity
    assert all(
        c["reference"].startswith("PC-") and c["grading_card_id"] is None for c in data["cards"]
    )
    assert data["payment_status"] == "not_implemented" and not data["commercially_accepted"]
    assert (entry.card_name, entry.quantity, entry.language) == original
    assert {
        "parcel_registered",
        "physical_card_created",
        "card_matched",
        "intake_transition",
        "operational_override",
    } <= {e["action"] for e in data["events"]}
    # Existing inspection policy remains independent of custody completion.
    api = native_backend[1]
    headers = {"Cookie": f"{auth._current.cookie_name}={auth._current.token}"}
    lookup = api.get(
        "/internal/inspection/lookup",
        params={"reference": data["cards"][0]["reference"]},
        headers=headers,
    )
    assert lookup.status_code == 200
    assert "payment_unverified" in {
        r["code"] for r in lookup.json()["eligibility"]["start"]["reasons"]
    }
    from selby_workstation.incoming import PreviewError

    with pytest.raises(PreviewError, match="does not permit"):
        decision(journal, client, sid, "begin")


@pytest.mark.parametrize("issue_kind", ["mismatch", "unexpected"])
def test_desktop_missing_wrong_unexpected_and_explicit_exceptions(
    native_backend, tmp_path, issue_kind
):
    from selby_workstation.incoming import PreviewError

    auth, client, journal, sid = setup(native_backend, tmp_path)
    data = perform(journal, client, sid, "parcel", {"notes": "Observed arrival"})
    assert data["status"] == "partially_received" and data["received_quantity"] == 0
    decision(journal, client, sid, "override")
    decision(journal, client, sid, "begin")
    data = perform(
        journal,
        client,
        sid,
        "card",
        {"parcel_id": data["parcels"][0]["id"], "notes": "Wrong card, do not match"},
    )
    cid = data["cards"][0]["id"]
    eid = data["entries"][0]["id"]
    with pytest.raises(PreviewError, match="Missing quantities"):
        decision(journal, client, sid, "complete")
    clear_rejected(journal, client, sid)
    for payload in [
        {"kind": "missing", "entry_id": eid, "quantity": 2, "notes": "Both declared copies absent"},
        {"kind": issue_kind, "card_id": cid, "quantity": 1, "notes": "Different received card"},
    ]:
        perform(journal, client, sid, "issue", payload)
    with pytest.raises(PreviewError, match="all open discrepancies"):
        decision(journal, client, sid, "complete")
    clear_rejected(journal, client, sid)
    for issue in client.load(sid)[1]["discrepancies"]:
        perform(
            journal,
            client,
            sid,
            "resolve",
            {"status": "acknowledged", "reason": "Explicit exception reviewed by operator"},
            issue["id"],
        )
    data = decision(journal, client, sid, "complete")
    assert data["status"] == "reconciled" and data["received_quantity"] == 1
    assert data["cards"][0]["entry_id"] is None


def test_committed_receipt_lost_response_restart_replays_same_identity(native_backend, tmp_path):
    from selby_workstation.incoming import PreviewError
    from selby_workstation.intake_journal import IntakeJournal

    auth, client, journal, sid = setup(native_backend, tmp_path)
    scope = client.connection.credential_target
    intent = journal.begin(scope, sid, "parcel", {"notes": "Persist before sending"})
    real = client.reader.submission
    with patch.object(
        client.reader, "submission", side_effect=PreviewError("Lost reply", kind="offline")
    ):
        with pytest.raises(PreviewError):
            journal.run(scope, intent, client)
    assert len(real(sid)["parcels"]) == 1  # POST committed, final read was lost.
    restarted = IntakeJournal(journal.path)
    data = restarted.retry(scope, sid, auth.intake_client())
    assert len(data["parcels"]) == 1 and restarted.pending(scope, sid) is None
    assert sum(e["action"] == "parcel_registered" for e in data["events"]) == 1
    decision(journal, client, sid, "override")
    decision(journal, client, sid, "begin")
    intent = journal.begin(scope, sid, "card", {"parcel_id": data["parcels"][0]["id"], "notes": ""})
    with patch.object(
        client.reader, "submission", side_effect=PreviewError("Lost reply", kind="offline")
    ):
        with pytest.raises(PreviewError):
            journal.run(scope, intent, client)
    data = IntakeJournal(journal.path).retry(scope, sid, auth.intake_client())
    assert len(data["cards"]) == 1
    assert sum(e["action"] == "physical_card_created" for e in data["events"]) == 1


def test_operator_gate_expired_session_role_removal_no_receipt(native_backend, tmp_path):
    from selby_workstation.incoming import PreviewError

    auth, client, journal, sid = setup(native_backend, tmp_path, admin=False)
    perform(journal, client, sid, "parcel", {"notes": "Operator can receive, not override"})
    with pytest.raises(PreviewError, match="Administrator custody"):
        decision(journal, client, sid, "begin")
    clear_rejected(journal, client, sid)
    with pytest.raises(PreviewError, match="Permission denied"):
        decision(journal, client, sid, "override")
    clear_rejected(journal, client, sid)
    _, _, db, _, operator, _, _ = native_backend
    db.delete(db.get(StaffMembership, operator.id))
    db.commit()
    with pytest.raises(PreviewError, match="Permission denied"):
        perform(journal, client, sid, "parcel", {"notes": "Must not be accepted"})
    scope = client.connection.credential_target
    assert journal.pending(scope, sid) is not None
    record = db.scalars(select(CustomerSession)).one()
    record.expires_at = now() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(PreviewError, match="expired"):
        journal.retry(scope, sid, client)
    assert db.scalars(select(PhysicalCard)).all() == []


def test_distinct_declared_entries_sharing_name_require_explicit_ids(native_backend, tmp_path):
    _, client, journal, sid = setup(native_backend, tmp_path)
    db = native_backend[2]
    second = SubmissionEntry(
        submission_id=UUID(sid),
        game="pokemon",
        card_name="Synthetic card",
        expansion="Different printing",
        card_number="A-01",
        language="EN",
        quantity=1,
    )
    db.add(second)
    db.commit()
    data = perform(journal, client, sid, "parcel", {"notes": "Three physical cards arrived"})
    pid = data["parcels"][0]["id"]
    decision(journal, client, sid, "override")
    decision(journal, client, sid, "begin")
    entries = client.load(sid)[1]["entries"]
    assert len(entries) == 2 and entries[0]["card_name"] == entries[1]["card_name"]
    for entry in entries:
        for _ in range(entry["quantity"]):
            data = perform(
                journal, client, sid, "card", {"parcel_id": pid, "notes": "Identify individually"}
            )
            card = next(c for c in data["cards"] if c["entry_id"] is None)
            perform(
                journal,
                client,
                sid,
                "match",
                {"entry_id": entry["id"], "reason": "Verified printing, not just card name"},
                card["id"],
            )
    data = decision(journal, client, sid, "complete")
    assert data["status"] == "reconciled" and data["received_quantity"] == 3
    assert {c["entry_id"] for c in data["cards"]} == {e["id"] for e in entries}


def test_qt_dialog_real_backend_workflow(native_backend, tmp_path):
    root = Path(__file__).resolve().parents[2] / "scanner_agent"
    python = root / ".venv-analysis/Scripts/python.exe"
    if not python.exists():
        pytest.skip("Workstation virtual environment required for Qt/API integration")
    _, _, db, _, operator, _, items = native_backend
    db.get(StaffMembership, operator.id).role = "admin"
    db.commit()
    code = """
import sys,time
from PySide6.QtWidgets import QApplication,QMessageBox
from PySide6.QtTest import QTest
from selby_workstation.connection import DesktopConnection
from selby_workstation.desktop_auth import DesktopAuthService
from selby_workstation.intake_ui import PhysicalIntake
from selby_workstation.intake_journal import IntakeJournal
class SyntheticVault:
    value=None
    def load(self): return self.value
    def save(self,value): self.value=value
    def delete(self): self.value=None
app=QApplication([])
assert app.platformName()==sys.argv[5], app.platformName()
auth=DesktopAuthService(DesktopConnection('development',sys.argv[1],sys.argv[2]),SyntheticVault())
auth.sign_in('desktop-operator@example.invalid','Synthetic-desktop-password!')
QMessageBox.question=lambda *args:QMessageBox.StandardButton.Yes
w=PhysicalIntake(auth,sys.argv[3],journal=IntakeJournal(sys.argv[4]))
w.show()
def wait():
    deadline=time.monotonic()+8
    while w.busy and time.monotonic()<deadline: QTest.qWait(10)
    assert not w.busy and w.fresh, w.status.text()
def act(key):
    assert w.buttons[key].isEnabled(),key
    w.buttons[key].click();wait()
wait()
w.notes.setText('Synthetic physical parcel arrived');act('parcel')
w.reason.setText('Synthetic authorized custody decision');act('override');act('begin')
eid=w.data['entries'][0]['id']
for copy in range(2):
    act('card')
    physical=next(c for c in w.data['cards'] if c['entry_id'] is None)
    w.card.setCurrentIndex(w.card.findData(physical['id']))
    w.entry.setCurrentIndex(w.entry.findData(eid))
    act('match')
act('complete')
assert w.data['status']=='reconciled' and w.data['received_quantity']==2
assert all(c['grading_card_id'] is None for c in w.data['cards'])
assert w.data['payment_status']=='not_implemented'
assert not w.buttons['card'].isEnabled()
w.close()
w=PhysicalIntake(auth,sys.argv[3],journal=IntakeJournal(sys.argv[4]))
w.show();wait()
assert w.data['status']=='reconciled' and w.data['received_quantity']==2
assert all(not button.isEnabled() for button in w.buttons.values())
w.close();auth.sign_out()
print('Qt platform:',app.platformName())
print('Qt/FastAPI intake workflow passed with synthetic data')
"""
    platform = os.environ.get("SELBY_INTAKE_QT_PLATFORM", "offscreen")
    env = {**os.environ, "QT_QPA_PLATFORM": platform}
    result = subprocess.run(
        [
            str(python),
            "-c",
            code,
            native_backend[0],
            native_backend[3].auth_origin,
            str(items[0].id),
            str(tmp_path / "gui-intents.sqlite3"),
            platform,
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "workflow passed" in result.stdout
    db.expire_all()
    cards = list(db.scalars(select(PhysicalCard).where(PhysicalCard.submission_id == items[0].id)))
    assert len(cards) == 2 and all(c.entry_id for c in cards)
