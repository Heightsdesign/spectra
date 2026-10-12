import hashlib
import io
from uuid import UUID, uuid4

import pytest
from PIL import Image
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from app import cards
from app.models import CardImage


def image_bytes(format="PNG"):
    output = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(output, format=format)
    return output.getvalue()


def register(client):
    response = client.post("/api/cards", json={"game": "pokemon", "card_name": "Pikachu", "set_name": "Base Set", "collector_number": "58/102"})
    assert response.status_code == 201
    return response.json()


def upload(client, card_id, data=None, side="front", filename="card.png"):
    return client.post(f"/api/cards/{card_id}/images", data={"side": side}, files={"file": (filename, image_bytes() if data is None else data, "application/octet-stream")})


def assert_empty(session, settings):
    assert session.scalar(select(func.count()).select_from(CardImage)) == 0
    assert not settings.card_image_dir.exists() or list(settings.card_image_dir.iterdir()) == []


def test_card_creation_and_retrieval(api):
    client, session, _ = api
    session.execute(text("SET LOCAL TIME ZONE 'Europe/Paris'"))
    card = register(client)
    assert card["status"] == "registered"
    assert card["created_at"].endswith(("Z", "+00:00"))
    assert card["updated_at"] == card["created_at"]
    response = client.get(f"/api/cards/{card['id']}")
    assert response.status_code == 200
    assert response.json() == card
    assert client.get(f"/api/cards/{card['id']}/images").json() == []


@pytest.mark.parametrize("format,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("TIFF", "image/tiff")])
def test_original_upload_integrity_and_metadata(api, format, mime):
    client, session, settings = api
    session.execute(text("SET LOCAL TIME ZONE 'Europe/Paris'"))
    card = register(client)
    data = image_bytes(format)
    for side in ("front", "back"):
        response = upload(client, card["id"], data, side=side)
        assert response.status_code == 201
        metadata = response.json()
        assert metadata["sha256"] == hashlib.sha256(data).hexdigest()
        assert metadata["file_size"] == len(data)
        assert metadata["mime_type"] == mime
        assert metadata["original_filename"] == "card.png"
        assert metadata["uploaded_at"].endswith(("Z", "+00:00"))
        assert "storage_key" not in metadata
        record = session.get(CardImage, UUID(metadata["id"]))
        assert (settings.card_image_dir / record.storage_key).read_bytes() == data
    assert len(client.get(f"/api/cards/{card['id']}/images").json()) == 2


def test_duplicate_side_does_not_overwrite(api):
    client, session, settings = api
    card = register(client)
    first = upload(client, card["id"])
    before = {p.name: p.read_bytes() for p in settings.card_image_dir.iterdir()}
    assert first.status_code == 201
    assert upload(client, card["id"]).status_code == 409
    assert session.scalar(select(func.count()).select_from(CardImage)) == 1
    assert {p.name: p.read_bytes() for p in settings.card_image_dir.iterdir()} == before


@pytest.mark.parametrize("data", [b"not an image", b"", image_bytes("GIF"), image_bytes("JPEG")[:30], image_bytes()[:40]])
def test_invalid_image(api, data):
    client, session, settings = api
    assert upload(client, register(client)["id"], data).status_code == 422
    assert_empty(session, settings)


def test_oversized_image(api):
    client, session, settings = api
    assert upload(client, register(client)["id"], b"x" * 4097).status_code == 413
    assert_empty(session, settings)


def test_missing_card(api):
    client, session, settings = api
    card_id = str(uuid4())
    assert client.get(f"/api/cards/{card_id}").status_code == 404
    assert client.get(f"/api/cards/{card_id}/images").status_code == 404
    assert upload(client, card_id).status_code == 404
    assert_empty(session, settings)


@pytest.mark.parametrize("filename", [
    "../secret.png", "..\\secret.png", "C:\\secret.png", "C:/secret.png",
    "C:secret.png", "\\\\server\\share\\secret.png", "//server/share/secret.png",
    "folder/../secret.png", "folder\\..\\secret.png", "/secret.png",
    "\\secret.png", "\\\\?\\C:\\secret.png", "\\\\.\\C:\\secret.png",
])
def test_path_traversal_rejected(api, filename):
    client, session, settings = api
    assert upload(client, register(client)["id"], filename=filename).status_code == 422
    assert_empty(session, settings)


@pytest.mark.parametrize("field,value", [("game", "magic"), ("card_name", "  "), ("set_name", "x" * 201), ("collector_number", "")])
def test_invalid_card_input(api, field, value):
    client, _, _ = api
    payload = {"card_name": "Pikachu", "set_name": "Base Set", "collector_number": "58"}
    payload[field] = value
    assert client.post("/api/cards", json=payload).status_code == 422


def test_invalid_side_and_uuid(api):
    client, session, settings = api
    assert upload(client, register(client)["id"], side="left").status_code == 422
    assert client.get("/api/cards/not-a-uuid").status_code == 422
    assert_empty(session, settings)


def test_partial_filesystem_failure(api, monkeypatch):
    client, session, settings = api
    card = register(client)

    def fail(path, data):
        with path.open("xb") as output:
            output.write(data[:10])
        raise OSError("simulated disk failure")

    monkeypatch.setattr(cards, "write_original", fail)
    assert upload(client, card["id"]).status_code == 503
    assert_empty(session, settings)


@pytest.mark.parametrize("method", ["flush", "commit"])
def test_database_failure(api, monkeypatch, method):
    client, session, settings = api
    card = register(client)

    def fail(*args, **kwargs):
        raise SQLAlchemyError("simulated database failure")

    with monkeypatch.context() as patch:
        patch.setattr(session, method, fail)
        assert upload(client, card["id"]).status_code == 503
    assert_empty(session, settings)


def test_storage_collision_never_overwrites(api, monkeypatch):
    client, session, settings = api
    card = register(client)
    key = uuid4()
    settings.card_image_dir.mkdir()
    path = settings.card_image_dir / key.hex
    path.write_bytes(b"existing original")
    monkeypatch.setattr(cards, "uuid4", lambda: key)
    assert upload(client, card["id"]).status_code == 503
    assert path.read_bytes() == b"existing original"
    assert session.scalar(select(func.count()).select_from(CardImage)) == 0


def test_upload_logs(api, caplog):
    import json
    client, _, _ = api
    card = register(client)
    with caplog.at_level("INFO", logger="spectra.uploads"):
        assert upload(client, card["id"]).status_code == 201
        assert upload(client, card["id"], b"invalid").status_code == 422
    events = [json.loads(record.message) for record in caplog.records if record.name == "spectra.uploads"]
    assert [event["event"] for event in events] == ["image_uploaded", "image_upload_failed"]
