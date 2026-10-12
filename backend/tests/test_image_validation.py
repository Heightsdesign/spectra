import hashlib
import io

import pytest
from fastapi import HTTPException
from PIL import Image

from app.cards import validate_image, write_original


@pytest.mark.parametrize("format,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("TIFF", "image/tiff")])
def test_image_validation_and_exact_storage(tmp_path, format, mime):
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(output, format=format)
    original = output.getvalue()
    assert validate_image(original) == mime
    path = tmp_path / "generated-key"
    write_original(path, original)
    assert path.read_bytes() == original
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(original).digest()


@pytest.mark.parametrize("data", [b"", b"not an image", b"\x89PNG\r\n\x1a\n", b"GIF89a" + b"\x00" * 30])
def test_reject_malformed_image(data):
    with pytest.raises(HTTPException) as failure:
        validate_image(data)
    assert failure.value.status_code == 422


def test_exclusive_write_preserves_existing_file(tmp_path):
    path = tmp_path / "existing"
    path.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        write_original(path, b"replacement")
    assert path.read_bytes() == b"original"
