"""Thermal protocol tests using the guarded PostgreSQL/HTTP fixture; never a printer."""

# ruff: noqa: F811 -- imported pytest fixture.
import hashlib
import json
from uuid import UUID, uuid4

import pytest
from app.intake_models import PhysicalCard
from app.physical_identity import decode_label, encode_label, parse_scan
from sqlalchemy import select
from test_workstation_v05a3 import native_backend  # noqa: F401
from test_workstation_v05a4 import decision
from test_workstation_v05a6 import accidental, void


@pytest.mark.parametrize("kind,prefix", [("order", "SP-"), ("physical_card", "PC-")])
def test_payload_roundtrip(kind, prefix):
    ref = prefix + uuid4().hex.upper()
    encoded = encode_label(kind, ref)
    assert decode_label(encoded) == (kind, ref)
    if kind == "physical_card":
        assert parse_scan(encoded) == ref
    for bad in [
        encoded + "x",
        encoded.lower(),
        "SELBY:2:" + ref,
        "https://example.invalid/" + ref,
    ]:
        with pytest.raises(ValueError):
            decode_label(bad)


def prepared(native_backend, tmp_path):
    auth, client, journal, sid, extra, legitimate = accidental(native_backend, tmp_path)
    void(client, sid, extra["id"])
    decision(journal, client, sid, "complete")
    return auth, client, sid, extra, legitimate


def test_authority_history_void_reprint_and_replay(
    native_backend, tmp_path, monkeypatch
):
    _auth, client, sid, extra, pcs = prepared(native_backend, tmp_path)
    state = client.labels(sid)
    assert len(state["labels"]) == 3
    assert extra["reference"] not in {l["reference"] for l in state["labels"]}
    refs = [l["reference"] for l in state["labels"] if l["kind"] == "physical_card"]
    assert len(set(refs)) == 2  # Identical names, distinct copies.
    assert not state["print_eligible"] and "payment_unverified" in state["blockers"]
    chosen = state["labels"][1:]
    payload = {
        "job_id": str(uuid4()),
        "phase": "rendered",
        "references": refs,
        "printer": "Virtual test printer",
        "fingerprint": hashlib.sha256(
            json.dumps(chosen, sort_keys=True).encode()
        ).hexdigest(),
    }

    def send(**updates):
        return client.execute(
            {"kind": "label_event", "sid": sid, "payload": dict(payload, **updates)}
        )

    assert send()["accepted"]
    assert not send()["accepted"]
    from selby_workstation.incoming import PreviewError

    with pytest.raises(PreviewError):
        send(phase="claimed")
    # Isolate claim state-machine tests from commercial provider, whose fail-closed
    # behavior was exercised above through the real authenticated HTTP transport.
    import app.thermal_labels as module

    real_manifest = module.manifest

    def cleared(*args):
        value = real_manifest(*args)
        value["print_eligible"] = True
        return value

    monkeypatch.setattr(module, "manifest", cleared)
    assert send(phase="claimed")["accepted"]
    assert not send(phase="claimed")["accepted"]
    assert send(phase="submitted")["accepted"]
    assert send(phase="verified")["accepted"]
    with pytest.raises(PreviewError):
        send(phase="failed")
    payload["job_id"] = str(uuid4())
    assert send()["accepted"]
    with pytest.raises(PreviewError):
        send(phase="claimed")
    assert send(phase="claimed", reason="Damaged sleeve; inspected previous queue")[
        "accepted"
    ]
    with pytest.raises(PreviewError):
        send(phase="claimed", printer="Other printer")
    with pytest.raises(PreviewError):
        send(width_mm=70)
    payload["job_id"] = str(uuid4())
    with pytest.raises(PreviewError):
        send(references=[extra["reference"]])
    with pytest.raises(PreviewError):
        send(fingerprint="0" * 64)
    other_sid = str(native_backend[-1][1].id)
    with pytest.raises(PreviewError):
        client.execute({"kind": "label_event", "sid": other_sid, "payload": payload})
    current = client.labels(sid)
    assert len([e for e in current["history"] if e["action"] == "label_claimed"]) == 2
    assert len([e for e in current["history"] if e["action"] == "label_verified"]) == 1
    assert set(pcs) == {
        str(c.id)
        for c in native_backend[2].scalars(
            select(PhysicalCard).where(
                PhysicalCard.submission_id == UUID(sid),
                PhysicalCard.id != UUID(extra["id"]),
            )
        )
    }


@pytest.mark.parametrize("quantity", [1, 3])
def test_one_and_multi_card_manifest(native_backend, tmp_path, quantity):
    from app.submission_models import SubmissionEntry
    from test_workstation_v05a4 import perform, setup

    _, client, journal, sid = setup(native_backend, tmp_path)
    db = native_backend[2]
    entry = db.scalar(
        select(SubmissionEntry).where(SubmissionEntry.submission_id == UUID(sid))
    )
    entry.quantity = quantity
    db.commit()
    data = perform(journal, client, sid, "parcel", {})
    decision(journal, client, sid, "override")
    decision(journal, client, sid, "begin")
    for _ in range(quantity):
        data = perform(
            journal, client, sid, "card", {"parcel_id": data["parcels"][0]["id"]}
        )
        card = next(c for c in data["cards"] if c["entry_id"] is None)
        data = perform(
            journal,
            client,
            sid,
            "match",
            {"entry_id": str(entry.id), "reason": "Synthetic verified copy"},
            card["id"],
        )
    decision(journal, client, sid, "complete")
    state = client.labels(sid)
    assert len(state["labels"]) == quantity + 1
    assert state["labels"][0]["text"] == f"{quantity} active physical cards"
    assert len({label["payload"] for label in state["labels"]}) == quantity + 1
    assert all(
        decode_label(label["payload"])[1] == label["reference"]
        for label in state["labels"]
    )
    # Authentication is required even for preview.
    raw = native_backend[1]
    raw.cookies.clear()
    assert raw.get(f"/internal/intake/submissions/{sid}/labels").status_code == 401
