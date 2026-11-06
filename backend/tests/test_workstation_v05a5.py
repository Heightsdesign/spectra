"""Real HTTP bridge + PostgreSQL + transactional workstation registry."""
# ruff: noqa: F811 -- imported pytest fixtures are intentional.

import os
import subprocess
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from app.intake_models import PhysicalCard, StaffMembership
from app.production_models import ProductionCard, ProductionOrder
from app.submission_models import SubmissionEntry
from sqlalchemy import func, select, text
from test_workstation_v05a3 import native_backend  # noqa: F401
from test_workstation_v05a4 import decision, perform, setup


def receive(fixture, tmp_path, quantities=(2,), missing=0):
    auth, client, journal, sid = setup(fixture, tmp_path)
    db = fixture[2]
    entry = db.scalar(select(SubmissionEntry).where(SubmissionEntry.submission_id == UUID(sid)))
    entry.quantity = quantities[0]
    for quantity in quantities[1:]:
        db.add(
            SubmissionEntry(
                submission_id=UUID(sid),
                game="pokemon",
                card_name=entry.card_name,
                expansion="Explicit other printing",
                card_number="2",
                language="EN",
                quantity=quantity,
            )
        )
    db.commit()
    data = perform(journal, client, sid, "parcel", {"notes": "Synthetic received parcel"})
    decision(journal, client, sid, "override")
    decision(journal, client, sid, "begin")
    entries = data["entries"]
    for index, item in enumerate(entries):
        for _ in range(item["quantity"] - (missing if index == 0 else 0)):
            data = perform(journal, client, sid, "card", {"parcel_id": data["parcels"][0]["id"]})
            pc = next(c for c in data["cards"] if c["entry_id"] is None)
            data = perform(
                journal,
                client,
                sid,
                "match",
                {"entry_id": item["id"], "reason": "Verified physical printing"},
                pc["id"],
            )
    if missing:
        data = perform(
            journal,
            client,
            sid,
            "issue",
            {
                "kind": "missing",
                "entry_id": entries[0]["id"],
                "quantity": missing,
                "notes": "Absent objects",
            },
        )
        issue = data["discrepancies"][-1]
        perform(
            journal,
            client,
            sid,
            "resolve",
            {"status": "acknowledged", "reason": "Authorized missing exception"},
            issue["id"],
        )
    decision(journal, client, sid, "complete")
    return auth, client, sid


@pytest.mark.parametrize("quantities", [(1,), (3,), (2, 1)])
def test_prepare_retry_restart_exact_mapping(native_backend, tmp_path, quantities):
    from selby_workstation.production import ProductionService

    auth, client, sid = receive(native_backend, tmp_path, quantities)
    service = ProductionService(client, tmp_path / "registry.sqlite3")
    first = service.prepare(sid, "Verified production preparation")
    mapping = first["mapping"]
    assert mapping["confirmed"] and len(mapping["cards"]) == sum(quantities)
    assert len(set(mapping["cards"].values())) == sum(quantities)
    assert not any(c["grading_card_id"] for c in first["snapshot"]["submission"]["cards"])
    assert all(
        not e["eligible"] and "payment_unverified" in {r["code"] for r in e["reasons"]}
        for e in first["snapshot"]["inspection"].values()
    )
    reopened = ProductionService(auth.intake_client(), service.store.path)
    assert reopened.prepare(sid, "Retry")["mapping"] == mapping
    assert len(service.store.search_orders()) == 1
    data = reopened.load(sid)["snapshot"]["submission"]
    assert sum(e["action"] == "production_reserved" for e in data["events"]) == 1
    assert sum(e["action"] == "production_confirmed" for e in data["events"]) == 1
    db = native_backend[2]
    assert db.scalar(select(func.count()).select_from(ProductionCard)) == sum(quantities)
    assert all(
        c["order_id"] == mapping["order_id"] for c in service.store.cards(mapping["order_id"])
    )


@pytest.mark.parametrize(
    "stage",
    ["reserve_reply", "local_commit", "confirm_before", "confirm_reply", "local_confirmation"],
)
def test_interrupted_protocol_reuses_committed_identities(native_backend, tmp_path, stage):
    from selby_workstation.incoming import PreviewError
    from selby_workstation.production import ProductionService

    auth, client, sid = receive(native_backend, tmp_path, (1,))
    service = ProductionService(client, tmp_path / "registry.sqlite3")
    original = client.execute

    def interrupted(operation):
        kind = operation["kind"]
        if stage == "confirm_before" and kind == "production_confirm":
            raise PreviewError("Network interrupted before confirm")
        result = original(operation)
        if (stage == "reserve_reply" and kind == "production_reserve") or (
            stage == "confirm_reply" and kind == "production_confirm"
        ):
            raise PreviewError("Committed but reply lost")
        return result

    target = service.store
    method = "apply" if stage == "local_commit" else "confirm"
    if stage in ("local_commit", "local_confirmation"):
        with patch.object(target, method, side_effect=OSError("Interrupted local persistence")):
            with pytest.raises(OSError):
                service.prepare(sid, "Synthetic interruption")
    else:
        with patch.object(client, "execute", side_effect=interrupted):
            with pytest.raises(PreviewError):
                service.prepare(sid, "Synthetic interruption")
    before = service.store.mapping(service.scope, sid)
    if stage in ("confirm_before", "confirm_reply", "local_confirmation"):
        from selby_workstation.production import ProductionStore

        recovery = service.store.path.with_name(service.store.path.name + ".bridge-recovery.bak")
        assert ProductionStore(recovery).mapping(service.scope, sid)["cards"] == before["cards"]
    restarted = ProductionService(auth.intake_client(), service.store.path)
    after = restarted.prepare(sid, "Recover same permanent identities")["mapping"]
    assert after["confirmed"]
    if before:
        assert after["order_id"] == before["order_id"] and after["cards"] == before["cards"]
    assert len(restarted.store.search_orders()) == 1
    assert len(restarted.store.cards(after["order_id"])) == 1
    assert native_backend[2].scalar(select(func.count()).select_from(ProductionOrder)) == 1


def test_other_registry_conflicting_ids_and_missing_local_state(native_backend, tmp_path):
    from selby_workstation.incoming import PreviewError
    from selby_workstation.production import BridgeConflict, ProductionService

    _, client, sid = receive(native_backend, tmp_path, (1,))
    first = ProductionService(client, tmp_path / "first.sqlite3")
    result = first.prepare(sid, "First verified registry")
    other = ProductionService(client, tmp_path / "other.sqlite3")
    with pytest.raises(BridgeConflict, match="another registry"):
        other.prepare(sid, "Duplicate registry")
    assert other.store.search_orders() == []
    payload = {
        "registry_id": first.store.registry_id,
        "local_order_id": "ORD-000999",
        "cards": [
            {"physical_card_id": pc, "local_card_id": local}
            for pc, local in result["mapping"]["cards"].items()
        ],
        "reason": "Conflicting retry",
    }
    with pytest.raises(PreviewError, match="conflict"):
        client.execute({"kind": "production_confirm", "sid": sid, "payload": payload})
    with other.store.transaction() as db:
        # Simulate an original registry backup predating mapping; not a supported restore.
        db.execute("DROP TRIGGER keep_bridge_registry_UPDATE")
        db.execute("UPDATE bridge_registry SET id=?", (first.store.registry_id,))
    with pytest.raises(BridgeConflict, match="Restore registry"):
        other.prepare(sid, "Do not invent replacement IDs")


def test_adoption_is_explicit_admin_only_and_preserves_existing_links(native_backend, tmp_path):
    from selby_workstation.incoming import PreviewError
    from selby_workstation.production import BridgeConflict, ProductionService

    _, client, sid = receive(native_backend, tmp_path, (1,))
    service = ProductionService(client, tmp_path / "legacy.sqlite3")
    order = service.store.create_order(
        "Same external reference is not identity",
        external_reference=client.production(sid)["submission"]["reference"],
    )
    card = service.store.add_cards(order["id"])[0]
    session = str(uuid4())
    with service.store.transaction() as db:
        db.execute(
            "UPDATE cards SET session_reference=?,session_id=? WHERE id=?",
            ('{"path":"existing","sha256":"preserved"}', session, card["id"]),
        )
    before = service.store.get_card(card["id"])
    with pytest.raises(BridgeConflict, match="Unverified"):
        service.prepare(sid, "No automatic adoption")
    assert native_backend[2].get(ProductionOrder, UUID(sid)) is None
    pc = client.production(sid)["submission"]["cards"][0]["id"]
    plan = {"order_id": order["id"], "cards": {pc: card["id"]}}
    db, operator = native_backend[2], native_backend[4]
    db.get(StaffMembership, operator.id).role = "operator"
    db.commit()
    with pytest.raises(PreviewError, match="Permission denied"):
        client.execute(
            {
                "kind": "production_reserve",
                "sid": sid,
                "payload": {
                    "registry_id": service.store.registry_id,
                    "mode": "adopt",
                    "reason": "Forbidden",
                },
            }
        )
    with pytest.raises(BridgeConflict, match="administrator"):
        service.prepare(sid, "Forbidden adoption", "adopt", plan)
    db.get(StaffMembership, operator.id).role = "admin"
    db.commit()
    result = service.prepare(
        sid, "Physically verified exact PC and original dossier", "adopt", plan
    )
    assert (
        result["mapping"]["order_id"] == order["id"]
        and service.store.get_card(card["id"]) == before
    )
    assert len(service.store.search_orders()) == 1


def test_acknowledged_missing_exception_maps_only_received_objects(native_backend, tmp_path):
    from selby_workstation.production import ProductionService

    _, client, sid = receive(native_backend, tmp_path, (2,), missing=1)
    result = ProductionService(client, tmp_path / "registry.sqlite3").prepare(
        sid, "One received, one acknowledged absent"
    )
    assert len(result["mapping"]["cards"]) == 1
    assert result["snapshot"]["submission"]["declared_quantity"] == 2
    assert not next(iter(result["snapshot"]["inspection"].values()))["eligible"]


def test_unreconciled_draft_and_revoked_staff_cannot_allocate(native_backend, tmp_path):
    from selby_workstation.incoming import PreviewError
    from selby_workstation.production import BridgeConflict, ProductionService

    _, client, _, sid = setup(native_backend, tmp_path)
    service = ProductionService(client, tmp_path / "registry.sqlite3")
    with pytest.raises(BridgeConflict, match="intake_not_reconciled"):
        service.prepare(sid, "Must reconcile first")
    db = native_backend[2]
    item = native_backend[6][0]
    item.status = "draft"
    db.commit()
    with pytest.raises(PreviewError):
        client.execute(
            {
                "kind": "production_reserve",
                "sid": sid,
                "payload": {
                    "registry_id": service.store.registry_id,
                    "mode": "create",
                    "reason": "Draft forbidden",
                },
            }
        )
    item.status = "submitted"
    db.delete(db.get(StaffMembership, native_backend[4].id))
    db.commit()
    with pytest.raises(PreviewError):
        service.prepare(sid, "Revoked staff")
    assert (
        service.store.search_orders() == []
        and db.scalar(select(func.count()).select_from(ProductionOrder)) == 0
    )


def test_backend_mapping_history_is_immutable(native_backend, tmp_path):
    from sqlalchemy.exc import DBAPIError

    from selby_workstation.production import ProductionService

    _, client, sid = receive(native_backend, tmp_path, (1,))
    ProductionService(client, tmp_path / "registry.sqlite3").prepare(sid, "Permanent pairing")
    db = native_backend[2]
    for command in [
        "UPDATE production_orders SET registry_id=gen_random_uuid()",
        "DELETE FROM production_orders",
        "DELETE FROM production_cards",
        "UPDATE production_cards SET local_card_id='SLB-C-999999'",
    ]:
        with pytest.raises(DBAPIError), db.begin_nested():
            db.execute(text(command))


@pytest.mark.parametrize("concern", ["unresolved", "unexpected", "backend_grading_uuid"])
def test_reconciled_concerns_require_review_instead_of_identity_guessing(
    native_backend, tmp_path, concern
):
    from app.intake_models import Discrepancy
    from app.models import Card

    from selby_workstation.production import BridgeConflict, ProductionService

    _, client, sid = receive(native_backend, tmp_path, (1,))
    db = native_backend[2]
    pc = db.scalar(select(PhysicalCard).where(PhysicalCard.submission_id == UUID(sid)))
    if concern == "backend_grading_uuid":
        grading = Card(game="pokemon", card_name="Existing", set_name="", collector_number="")
        db.add(grading)
        db.flush()
        pc.grading_card_id = grading.id
    else:
        # Synthetic historical acknowledged concern. This must not become a
        # statement that the card is safe to inspect/grade.
        db.add(
            Discrepancy(
                submission_id=UUID(sid),
                card_id=pc.id,
                kind=concern,
                quantity=1,
                notes="Historical concern",
                status="acknowledged",
                resolution="Explicit exception",
                created_by=native_backend[4].id,
                resolved_by=native_backend[4].id,
            )
        )
    db.commit()
    service = ProductionService(client, tmp_path / "registry.sqlite3")
    with pytest.raises(BridgeConflict):
        service.prepare(sid, "Do not infer grading identity or clearance")
    assert service.store.search_orders() == []
    assert db.get(ProductionOrder, UUID(sid)) is None
    if concern == "backend_grading_uuid":
        assert db.get(PhysicalCard, pc.id).grading_card_id == grading.id


def test_bridge_writes_require_origin_session_csrf_and_exact_manifest(native_backend, tmp_path):
    from selby_workstation.incoming import PreviewError
    from selby_workstation.production import ProductionService

    auth, client, sid = receive(native_backend, tmp_path, (1,))
    service = ProductionService(client, tmp_path / "registry.sqlite3")
    api = native_backend[1]
    path = f"/internal/intake/submissions/{sid}/production"
    reservation = {
        "registry_id": service.store.registry_id,
        "mode": "create",
        "reason": "Authorized request",
    }
    assert api.post(path + "/reserve", json=reservation).status_code == 403
    headers = {"Origin": client.connection.auth_origin, "X-Spectra-Client": "1"}
    assert api.post(path + "/reserve", json=reservation, headers=headers).status_code == 401
    headers["Cookie"] = f"{auth._current.cookie_name}={auth._current.token}"
    assert api.post(path + "/reserve", json=reservation, headers=headers).status_code == 403
    assert native_backend[2].get(ProductionOrder, UUID(sid)) is None
    client.execute({"kind": "production_reserve", "sid": sid, "payload": reservation})
    bad = {
        "registry_id": service.store.registry_id,
        "local_order_id": "ORD-000001",
        "cards": [{"physical_card_id": str(uuid4()), "local_card_id": "SLB-C-000001"}],
        "reason": "Wrong PC identity",
    }
    with pytest.raises(PreviewError, match="inventory changed"):
        client.execute({"kind": "production_confirm", "sid": sid, "payload": bad})
    assert native_backend[2].get(ProductionOrder, UUID(sid)).local_order_id is None
    assert service.store.search_orders() == []


def test_native_qt_bridge_and_local_orders(native_backend, tmp_path):
    _, _, sid = receive(native_backend, tmp_path, (2, 1))
    root = Path(__file__).resolve().parents[2] / "scanner_agent"
    python = root / ".venv-analysis/Scripts/python.exe"
    if not python.exists():
        pytest.skip("Workstation Qt environment required")
    code = """
import sys,time
from pathlib import Path
from PySide6.QtCore import QSettings
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QMessageBox
from PySide6.QtTest import QTest
from selby_workstation.connection import DesktopConnection
from selby_workstation.desktop_auth import DesktopAuthService
from selby_workstation.production_ui import ProductionDialog
from selby_workstation.app import Workstation
class Vault:
    value=None
    def load(self): return self.value
    def save(self,value): self.value=value
    def delete(self): self.value=None
app=QApplication([])
assert app.platformName()==sys.argv[6],app.platformName()
auth=DesktopAuthService(DesktopConnection('development',sys.argv[1],sys.argv[2]),Vault())
auth.sign_in('desktop-operator@example.invalid','Synthetic-desktop-password!')
QMessageBox.question=lambda *a:QMessageBox.StandardButton.Yes
settings=QSettings(sys.argv[5],QSettings.Format.IniFormat)
settings.setValue('orders_path',sys.argv[4]);settings.sync()
with patch('selby_workstation.desktop.DesktopConnection.load',return_value=None):
    main=Workstation(settings_path=Path(sys.argv[5]))
main.orders_path=Path(sys.argv[4])
main.show()
def open_order(identity):
    main.open_orders();main.orders_dialog.open_order(identity)
w=ProductionDialog(auth,sys.argv[3],Path(sys.argv[4]),main,open_order)
w.show()
def wait():
    deadline=time.monotonic()+15
    while w.busy and time.monotonic()<deadline: QTest.qWait(10)
    assert not w.busy and w.value is not None,w.status.text()
wait()
w.reason.setText('Native synthetic verified production mapping')
w.prepare_button.click();wait()
mapping=w.value['mapping']
assert mapping['confirmed'] and len(mapping['cards'])==3
w.prepare_button.click();wait()
assert w.value['mapping']==mapping
w.open_button.click();QTest.qWait(30)
assert main.orders_dialog.order_id==mapping['order_id']
assert main.orders_dialog.cards.rowCount()==3
assert 'confirmed' in main.orders_dialog.bridge_label.text()
main.orders_dialog.open_card(next(iter(mapping['cards'].values())))
assert 'PC-' in main.orders_dialog.details.toPlainText()
w=ProductionDialog(auth,sys.argv[3],Path(sys.argv[4]),main,open_order)
w.show();wait()
assert w.value['mapping']==mapping
assert all(not e['eligible'] for e in w.value['snapshot']['inspection'].values())
w.close();main.close();auth.sign_out()
print('Native bridge workflow passed on',app.platformName())
"""
    platform = os.environ.get("SELBY_BRIDGE_QT_PLATFORM", "offscreen")
    result = subprocess.run(
        [
            str(python),
            "-c",
            code,
            native_backend[0],
            native_backend[3].auth_origin,
            sid,
            str(tmp_path / "gui-registry.sqlite3"),
            str(tmp_path / "desktop.ini"),
            platform,
        ],
        cwd=root,
        env={**os.environ, "QT_QPA_PLATFORM": platform},
        capture_output=True,
        text=True,
        timeout=75,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Native bridge workflow passed" in result.stdout
    native_backend[2].expire_all()
    assert native_backend[2].scalar(select(func.count()).select_from(ProductionCard)) == 3
