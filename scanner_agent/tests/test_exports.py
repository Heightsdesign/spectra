import contextlib
import json
import os
import sys

import pytest
from test_storage import image_bytes

from spectra_scanner.common import AgentError
from spectra_scanner.exports import FileStamp, FolderImporter, snapshot_export
from spectra_scanner.storage import ArtifactStore


def importer(tmp_path, seconds=3):
    inbox = tmp_path / "epson-exports"
    inbox.mkdir()
    store = ArtifactStore(tmp_path / "artifacts")
    return FolderImporter(inbox, store, seconds), store, inbox


def test_quiet_period_restarts_after_file_changes(tmp_path):
    watcher, store, inbox = importer(tmp_path)
    source = inbox / "front.png"
    original = image_bytes()
    source.write_bytes(original[:30])
    assert watcher.poll(0) == []
    assert watcher.poll(2) == []
    source.write_bytes(original)
    assert watcher.poll(3) == []
    assert watcher.poll(5.9) == []
    result = watcher.poll(6)
    assert result[0]["status"] == "stored"
    assert source.read_bytes() == original
    metadata = json.loads((store.root / result[0]["metadata"]).read_text())
    assert metadata["provenance"]["device_identity"] is None
    assert metadata["provenance"]["acquired_at_utc"] is None
    assert metadata["provenance"]["capture_settings"] == "not_verified_by_folder_import"
    assert watcher.poll(20) == []


def test_duplicate_exports_and_same_name_new_content(tmp_path):
    watcher, store, inbox = importer(tmp_path)
    source = inbox / "front.png"
    source.write_bytes(image_bytes())
    watcher.poll(0)
    assert watcher.poll(3)[0]["status"] == "stored"
    (inbox / "same-copy.png").write_bytes(source.read_bytes())
    watcher.poll(4)
    assert watcher.poll(7)[0]["status"] == "duplicate"
    source.write_bytes(image_bytes(dpi=(600, 600)))
    watcher.poll(8)
    assert watcher.poll(11)[0]["status"] == "stored"
    assert len(list(store.captures.glob("*/metadata.json"))) == 2


def test_incomplete_and_lossy_exports_do_not_stop_other_imports(tmp_path):
    watcher, _, inbox = importer(tmp_path)
    (inbox / "broken.png").write_bytes(b"incomplete")
    (inbox / "lossy.jpg").write_bytes(image_bytes("JPEG"))
    (inbox / "valid.tiff").write_bytes(image_bytes("TIFF"))
    (inbox / "unfinished.part").write_bytes(b"ignored")
    watcher.poll(0)
    assert {e["status"] for e in watcher.poll(3)} == {
        "invalid_image",
        "unsupported_format",
        "stored",
    }


def test_changed_snapshot_rejected(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(image_bytes())
    old = FileStamp.of(source.stat())
    source.write_bytes(b"new version")
    with pytest.raises(AgentError, match="changed"):
        snapshot_export(source, tmp_path / "snapshot", old)


def test_change_during_copy_rejected(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    source.write_bytes(image_bytes())
    expected = FileStamp.of(source.stat())

    @contextlib.contextmanager
    def changing_reader(path):
        with path.open("rb") as stream:

            class Reader:
                changed = False

                def fileno(self):
                    return stream.fileno()

                def read(self, amount):
                    result = stream.read(amount)
                    if not self.changed:
                        self.changed = True
                        os.utime(path, ns=(expected.modified_ns, expected.modified_ns + 1_000_000))
                    return result

            yield Reader()

    monkeypatch.setattr("spectra_scanner.exports.locked_reader", changing_reader)
    with pytest.raises(AgentError, match="changed during"):
        snapshot_export(source, tmp_path / "snapshot", expected)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file-sharing semantics")
def test_open_writer_blocks_import_until_closed(tmp_path):
    watcher, _, inbox = importer(tmp_path)
    source = inbox / "front.png"
    source.write_bytes(image_bytes())
    watcher.poll(0)
    with source.open("ab"):
        assert watcher.poll(3)[0]["status"] == "source_busy"
    assert watcher.poll(4)[0]["status"] == "stored"


@pytest.mark.parametrize("delay", [0, -1, float("nan"), float("inf")])
def test_invalid_quiet_period_rejected(tmp_path, delay):
    with pytest.raises(AgentError):
        importer(tmp_path, delay)


def test_output_and_input_overlap_rejected(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(AgentError, match="overlap"):
        FolderImporter(store.root, store)
