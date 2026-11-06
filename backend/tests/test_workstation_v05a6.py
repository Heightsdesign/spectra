"""Void lifecycle: actual HTTP/FastAPI/PostgreSQL and workstation transport."""
# ruff: noqa: F811 -- imported pytest fixtures.

import os
import subprocess
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from app.inspection_models import Inspection
from app.intake_models import Discrepancy, Intake, IntakeAudit, PhysicalCard, StaffMembership
from app.intake_voids import PhysicalCardVoid
from app.models import Card
from app.production_models import ProductionCard, ProductionOrder
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_workstation_v05a3 import native_backend  # noqa: F401
from test_workstation_v05a4 import decision, perform, setup


def accidental(fixture, tmp_path):
    auth, client, journal, sid = setup(fixture, tmp_path)
    data = perform(journal, client, sid, "parcel", {"notes": "Synthetic arrival"})
    decision(journal, client, sid, "override")
    decision(journal, client, sid, "begin")
    pid, eid = data["parcels"][0]["id"], data["entries"][0]["id"]
    legitimate = []
    for _ in range(2):
        data = perform(journal, client, sid, "card", {"parcel_id": pid})
        pc = next(c for c in data["cards"] if c["entry_id"] is None)
        legitimate.append(pc["id"])
        perform(
            journal,
            client,
            sid,
            "match",
            {"entry_id": eid, "reason": "Verified real object"},
            pc["id"],
        )
    data = perform(
        journal,
        client,
        sid,
        "card",
        {"parcel_id": pid, "notes": "Synthetic accidental extra click"},
    )
    extra = next(c for c in data["cards"] if c["entry_id"] is None)
    return auth, client, journal, sid, extra, legitimate


def void(client, sid, cid, reason="Registration mistake: no physical object exists"):
    return client.execute(
        {"kind": "void", "sid": sid, "target": cid, "payload": {"reason": reason}}
    )


def test_correction_reconcile_production_and_repeat_preserve_history(native_backend, tmp_path):
    from selby_workstation.production import ProductionService

    _, client, journal, sid, extra, legitimate = accidental(native_backend, tmp_path)
    db, operator = native_backend[2], native_backend[4]
    db.get(StaffMembership, operator.id).role = "operator"
    db.commit()
    original = dict(
        db.execute(select(PhysicalCard.__table__).where(PhysicalCard.id == UUID(extra["id"])))
        .mappings()
        .one()
    )
    assert extra["void_eligible"] and client.load(sid)[1]["received_quantity"] == 3
    corrected = void(client, sid, extra["id"])
    assert corrected["declared_quantity"] == corrected["received_quantity"] == 2
    assert sum(c["status"] == "matched" for c in corrected["cards"]) == 2
    assert sum(c["status"] == "unidentified" for c in corrected["cards"]) == 0
    historical = next(c for c in corrected["cards"] if c["id"] == extra["id"])
    assert historical["status"] == "voided" and historical["reference"] == extra["reference"]
    assert (
        historical["void"]["reason"].startswith("Registration mistake")
        and not historical["void_eligible"]
    )
    assert {c["id"] for c in corrected["cards"] if c["entry_id"] is not None} == set(legitimate)
    assert (
        dict(
            db.execute(select(PhysicalCard.__table__).where(PhysicalCard.id == UUID(extra["id"])))
            .mappings()
            .one()
        )
        == original
    )
    void(client, sid, extra["id"], "Different retry reason must not replace original")
    data = decision(journal, client, sid, "complete")
    assert data["status"] == "reconciled" and len(data["cards"]) == 3
    void(client, sid, extra["id"])  # Safe no-op replay after reconciliation.
    assert sum(e["action"] == "physical_card_voided" for e in client.load(sid)[1]["events"]) == 1
    assert db.scalar(select(func.count()).select_from(PhysicalCardVoid)) == 1
    result = ProductionService(client, tmp_path / "registry.sqlite3").prepare(
        sid, "Prepare only verified real objects"
    )
    assert result["mapping"]["confirmed"] and set(result["mapping"]["cards"]) == set(legitimate)
    assert len(result["snapshot"]["submission"]["voided_cards"]) == 1
    assert len(result["snapshot"]["submission"]["cards"]) == 2
    for command in [
        "UPDATE physical_card_voids SET reason='changed'",
        "DELETE FROM physical_card_voids",
        "TRUNCATE physical_card_voids",
    ]:
        with pytest.raises(DBAPIError), db.begin_nested():
            db.execute(text(command))


def test_voided_pc_cannot_match_create_issue_print_or_inspect(native_backend, tmp_path):
    from selby_workstation.incoming import PreviewError

    auth, client, _, sid, extra, _ = accidental(native_backend, tmp_path)
    void(client, sid, extra["id"])
    for kind, payload in [
        (
            "match",
            {"entry_id": client.load(sid)[1]["entries"][0]["id"], "reason": "Forbidden match"},
        ),
        ("issue", {"card_id": extra["id"], "kind": "unexpected", "notes": "No object"}),
    ]:
        with pytest.raises(PreviewError, match="VOIDED"):
            client.execute({"kind": kind, "sid": sid, "target": extra["id"], "payload": payload})
    api = native_backend[1]
    headers = {"Cookie": f"{auth._current.cookie_name}={auth._current.token}"}
    response = api.get(f"/internal/labels/cards/{extra['reference']}/pdf", headers=headers)
    assert response.status_code == 409 and response.json()["detail"] == "card_voided"
    lookup = api.get(
        "/internal/inspection/lookup", params={"reference": extra["reference"]}, headers=headers
    ).json()
    assert lookup["card"]["lifecycle_status"] == "voided"
    assert all(
        not e["eligible"] and "card_voided" in {r["code"] for r in e["reasons"]}
        for e in lookup["eligibility"].values()
    )
    # A creation request replay must retain the old (voided) identity, not create
    # a new active identity for that request key.
    raw = native_backend[2].get(PhysicalCard, UUID(extra["id"]))
    replay = client.execute(
        {
            "kind": "card",
            "sid": sid,
            "payload": {**raw.request_data, "request_key": str(raw.request_key)},
        }
    )
    assert len(replay["cards"]) == 3 and replay["received_quantity"] == 2


@pytest.mark.parametrize(
    "block",
    [
        "matched",
        "previous_match",
        "questionable",
        "discrepancy",
        "closed_discrepancy",
        "inspection",
        "grading",
        "reservation",
        "production",
        "reconciled",
        "on_hold",
    ],
)
def test_unsafe_void_rejected_without_changing_legitimate_links(native_backend, tmp_path, block):
    from selby_workstation.incoming import PreviewError

    _, client, _, sid, extra, legitimate = accidental(native_backend, tmp_path)
    db, actor = native_backend[2], native_backend[4]
    pc = db.get(PhysicalCard, UUID(extra["id"]))
    target = extra["id"]
    if block == "matched":
        target = legitimate[0]
    elif block == "previous_match":
        # Real match/unmatch history is consequential even if currently unidentified.
        db.add(
            IntakeAudit(
                actor_id=actor.id,
                submission_id=UUID(sid),
                action="card_matched",
                entity_id=pc.id,
                data={"before": None, "after": None},
                reason="Historical pairing",
            )
        )
    elif block == "questionable":
        pc.status = "questionable"
    elif block in ("discrepancy", "closed_discrepancy"):
        db.add(
            Discrepancy(
                submission_id=UUID(sid),
                card_id=pc.id,
                kind="unexpected",
                quantity=1,
                notes="An actual custody concern",
                status="open" if block == "discrepancy" else "resolved",
                created_by=actor.id,
            )
        )
    elif block == "inspection":
        db.add(Inspection(physical_card_id=pc.id, started_by=actor.id))
    elif block == "grading":
        grading = Card(game="pokemon", card_name="Existing", set_name="", collector_number="")
        db.add(grading)
        db.flush()
        pc.grading_card_id = grading.id
    elif block in ("reservation", "production"):
        registry = uuid4()
        db.add(
            ProductionOrder(
                submission_id=UUID(sid),
                registry_id=registry,
                mode="create",
                actor_id=actor.id,
                reason="Existing durable bridge reservation",
                local_order_id="ORD-000001" if block == "production" else None,
            )
        )
        db.flush()
        if block == "production":
            db.add(
                ProductionCard(
                    physical_card_id=pc.id,
                    submission_id=UUID(sid),
                    registry_id=registry,
                    local_card_id="SLB-C-000001",
                )
            )
    else:
        db.get(Intake, UUID(sid)).status = block
    db.commit()
    before = dict(
        db.execute(select(PhysicalCard.__table__).where(PhysicalCard.id == UUID(target)))
        .mappings()
        .one()
    )
    with pytest.raises(PreviewError, match="Void rejected"):
        void(client, sid, target)
    assert db.get(PhysicalCardVoid, UUID(target)) is None
    assert (
        dict(
            db.execute(select(PhysicalCard.__table__).where(PhysicalCard.id == UUID(target)))
            .mappings()
            .one()
        )
        == before
    )


def test_reason_cross_submission_and_authorization(native_backend, tmp_path):
    from selby_workstation.incoming import PreviewError

    _, client, _, sid, extra, _ = accidental(native_backend, tmp_path)
    with pytest.raises(PreviewError, match="Invalid intake fields"):
        void(client, sid, extra["id"], "   ")
    with pytest.raises(PreviewError, match="unavailable"):
        void(client, str(native_backend[6][1].id), extra["id"])
    db = native_backend[2]
    db.delete(db.get(StaffMembership, native_backend[4].id))
    db.commit()
    with pytest.raises(PreviewError, match="Permission denied"):
        void(client, sid, extra["id"])
    assert db.get(PhysicalCardVoid, UUID(extra["id"])) is None


def test_lost_reply_restart_retries_original_void_without_duplicate_audit(native_backend, tmp_path):
    from selby_workstation.incoming import PreviewError
    from selby_workstation.intake_journal import IntakeJournal

    auth, client, journal, sid, extra, _ = accidental(native_backend, tmp_path)
    scope = client.connection.credential_target
    intent = journal.begin(
        scope, sid, "void", {"reason": "No physical object; extra click"}, extra["id"]
    )
    with patch.object(client.reader, "submission", side_effect=PreviewError("Lost response")):
        with pytest.raises(PreviewError):
            journal.run(scope, intent, client)
    assert journal.pending(scope, sid) == intent
    restarted = IntakeJournal(journal.path)
    result = restarted.retry(scope, sid, auth.intake_client())
    assert result["received_quantity"] == 2 and restarted.pending(scope, sid) is None
    assert sum(e["action"] == "physical_card_voided" for e in result["events"]) == 1


def test_native_qt_void_then_reconcile_and_prepare(native_backend, tmp_path):
    _, _, _, sid, extra, legitimate = accidental(native_backend, tmp_path)
    root = Path(__file__).resolve().parents[2] / "scanner_agent"
    python = root / ".venv-analysis/Scripts/python.exe"
    if not python.exists():
        pytest.skip("Workstation Qt environment required")
    code = """
import sys,time
from pathlib import Path
from PySide6.QtWidgets import QApplication,QMessageBox
from PySide6.QtTest import QTest
from selby_workstation.connection import DesktopConnection
from selby_workstation.desktop_auth import DesktopAuthService
from selby_workstation.intake_ui import PhysicalIntake
from selby_workstation.intake_journal import IntakeJournal
from selby_workstation.production import ProductionService
class Vault:
    value=None
    def load(self): return self.value
    def save(self,value): self.value=value
    def delete(self): self.value=None
app=QApplication([])
assert app.platformName()==sys.argv[7]
auth=DesktopAuthService(DesktopConnection('development',sys.argv[1],sys.argv[2]),Vault())
auth.sign_in('desktop-operator@example.invalid','Synthetic-desktop-password!')
w=PhysicalIntake(auth,sys.argv[3],journal=IntakeJournal(Path(sys.argv[5])))
w.show()
def wait():
    deadline=time.monotonic()+15
    while w.busy and time.monotonic()<deadline: QTest.qWait(10)
    assert not w.busy and w.fresh,w.status.text()
wait()
w.card.setCurrentIndex(w.card.findData(sys.argv[4]))
reference=next(c['reference'] for c in w.data['cards'] if c['id']==sys.argv[4])
confirmations=[]
def confirm(*args):
    confirmations.append(args[2]);return QMessageBox.StandardButton.Yes
QMessageBox.question=confirm
w.reason.setText('Synthetic accidental registration: no physical object')
assert w.buttons['void'].isEnabled()
w.buttons['void'].click();wait()
assert reference in confirmations[-1]
assert 'Declared 2' in w.heading.text() and 'Received 2' in w.heading.text()
assert 'Matched 2' in w.heading.text() and 'Unidentified 0' in w.heading.text()
assert w.card.findData(sys.argv[4])==-1 and w.card.currentData() is None
assert any(w.inventory.item(r,3).text()=='VOIDED' for r in range(w.inventory.rowCount()))
w.reason.setText('Complete after audited correction')
w.buttons['complete'].click();wait()
assert w.data['status']=='reconciled'
w.close()
w=PhysicalIntake(auth,sys.argv[3],journal=IntakeJournal(Path(sys.argv[5])))
w.show();wait()
assert w.data['received_quantity']==2 and len(w.data['cards'])==3
w.close()
result=ProductionService(auth.intake_client(),Path(sys.argv[6])).prepare(sys.argv[3],'Prepare two legitimate synthetic objects')
assert result['mapping']['confirmed'] and len(result['mapping']['cards'])==2
assert sys.argv[4] not in result['mapping']['cards']
auth.sign_out()
print('Native void/reconcile/production workflow passed on',app.platformName())
"""
    platform = os.environ.get("SELBY_VOID_QT_PLATFORM", "offscreen")
    result = subprocess.run(
        [
            str(python),
            "-c",
            code,
            native_backend[0],
            native_backend[3].auth_origin,
            sid,
            extra["id"],
            str(tmp_path / "gui-journal.sqlite3"),
            str(tmp_path / "gui-registry.sqlite3"),
            platform,
        ],
        cwd=root,
        env={**os.environ, "QT_QPA_PLATFORM": platform},
        capture_output=True,
        text=True,
        timeout=75,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Native void/reconcile/production workflow passed" in result.stdout
    db = native_backend[2]
    db.expire_all()
    assert {str(c.physical_card_id) for c in db.scalars(select(ProductionCard))} == set(legitimate)
