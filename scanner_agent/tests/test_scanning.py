# ruff: noqa: F401, F811 -- imported pytest fixtures
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_production_bridge import bridge

from selby_workstation.incoming import PreviewError
from selby_workstation.scanning import identify, resolve


@pytest.fixture
def ready(bridge):
    store, data = bridge
    for c in data["submission"]["cards"]:
        c["status"] = "matched"
    mapping = store.apply("http://local", data, "Synthetic scan test")
    data["binding"].update(local_order_id=mapping["order_id"], cards=mapping["cards"])
    store.confirm("http://local", data, "Synthetic confirmation")
    data["inspection"] = {
        c["id"]: {"eligible": True, "reasons": []} for c in data["submission"]["cards"]
    }
    client = SimpleNamespace(
        connection=SimpleNamespace(backend_origin="http://local"),
        production=lambda sid: deepcopy(data),
    )
    return store, data, client


def test_distinct_copies_repeat_restart(ready):
    store, data, client = ready
    before = store.path.read_bytes()
    found = []
    for card in data["submission"]["cards"]:
        for _ in range(3):
            result = resolve(store.path, "SP:PC:1:" + card["reference"], client)
            assert result["eligibility"]["eligible"]
        found.append(result["card"]["card_id"])
    assert len(set(found)) == 2
    assert store.path.read_bytes() == before
    assert (
        resolve(store.path, "SP:ORDER:1:" + data["submission"]["reference"], client)["kind"]
        == "order"
    )


@pytest.mark.parametrize("mutation", ["void", "registry", "origin", "binding", "unpaid", "offline"])
def test_fail_closed(ready, mutation):
    store, data, client = ready
    card = data["submission"]["cards"][0]
    payload = "SP:PC:1:" + card["reference"]
    if mutation == "void":
        card["status"] = "voided"
    if mutation == "registry":
        data["binding"]["registry_id"] = "another"
    if mutation == "origin":
        client.connection.backend_origin = "http://other"
    if mutation == "binding":
        data["binding"]["cards"] = {}
    if mutation == "offline":

        def offline(sid):
            raise PreviewError("Offline")

        client.production = offline
    if mutation == "unpaid":
        data["inspection"][card["id"]] = dict(
            eligible=False, reasons=[dict(code="payment_required")]
        )
        result = resolve(store.path, payload, client)
        assert not result["eligibility"]["eligible"]
        assert result["eligibility"]["reasons"] == [dict(code="payment_required")]
    else:
        with pytest.raises(PreviewError):
            resolve(store.path, payload, client)


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "PC-" + "A" * 32,
        "SP:PC:2:PC-" + "A" * 32,
        "SP:PC:1:PC-" + "A" * 31,
        "SP:PC:1:PC-" + "a" * 32,
        "SELBY:TEST:V2:CALIBRATION",
        "https://other/PC-" + "A" * 32,
    ],
)
def test_invalid(payload):
    with pytest.raises(PreviewError):
        identify(payload)


def test_diagnostic_no_client():
    assert resolve("missing", "SELBY:TEST:V1:CALIBRATION", None)["kind"] == "diagnostic"


def test_unknown(ready):
    store, _, client = ready
    with pytest.raises(PreviewError, match="Unknown"):
        resolve(store.path, "SP:PC:1:PC-" + "F" * 32, client)
