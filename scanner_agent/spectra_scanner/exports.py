"""Quiet-period observation plus a stable, write-denying Windows file snapshot."""

from __future__ import annotations

import contextlib
import ctypes
import math
import os
import stat
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from .common import AgentError, utc_now
from .storage import MAX_BYTES, ArtifactStore


@dataclass(frozen=True)
class FileStamp:
    device: int
    inode: int
    size: int
    modified_ns: int

    @classmethod
    def of(cls, value: os.stat_result) -> FileStamp:
        # Windows/Python 3.13 path stat and CRT-handle fstat disagree on st_ctime
        # (creation versus change time). Compare file identity, byte size and mtime.
        return cls(value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def regular_file(path: Path) -> bool:
    info = path.lstat()
    return (
        stat.S_ISREG(info.st_mode)
        and not path.is_symlink()
        and not (getattr(info, "st_file_attributes", 0) & 0x400)  # Windows reparse point
    )


@contextlib.contextmanager
def locked_reader(path: Path) -> Iterator[BinaryIO]:
    if sys.platform != "win32":
        with path.open("rb") as stream:
            yield stream
        return
    # FILE_SHARE_READ only: deny existing/new writers and rename/delete during the snapshot.
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = create(str(path), 0x80000000, 1, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error in (32, 33):
            raise AgentError("source_busy", "Export is still open for writing; retry later")
        raise OSError(error, "Cannot open export for a stable snapshot")
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except Exception:
        close(handle)
        raise
    with os.fdopen(descriptor, "rb") as stream:
        yield stream


def snapshot_export(path: Path, destination: Path, expected: FileStamp) -> None:
    if not regular_file(path):
        raise AgentError(
            "invalid_path", "Import accepts regular files, not links or reparse points"
        )
    with locked_reader(path) as source:
        before = FileStamp.of(os.fstat(source.fileno()))
        if before != expected:
            raise AgentError("source_changed", "Export changed before the snapshot")
        if not 0 < before.size <= MAX_BYTES:
            raise AgentError("invalid_image", "Export is empty or exceeds the S1 size limit")
        copied = 0
        with destination.open("xb") as output:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                copied += len(chunk)
                if copied > MAX_BYTES:
                    raise AgentError("source_changed", "Export grew during the snapshot")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        after = FileStamp.of(os.fstat(source.fileno()))
        if after != before or FileStamp.of(path.stat()) != before or copied != before.size:
            raise AgentError(
                "source_changed", "Export changed during the snapshot; no original committed"
            )


class FolderImporter:
    def __init__(self, inbox: Path, store: ArtifactStore, stable_seconds: float = 3.0):
        if not math.isfinite(stable_seconds) or stable_seconds < 1:
            raise AgentError("invalid_input", "Use at least a one-second export quiet period")
        if inbox.is_symlink() or (getattr(inbox.lstat(), "st_file_attributes", 0) & 0x400):
            raise AgentError("invalid_path", "Export inbox must not be a link or junction")
        inbox = inbox.resolve()
        backend = Path(__file__).resolve().parents[2] / "backend"
        if not inbox.is_dir() or inbox.is_relative_to(backend):
            raise AgentError("invalid_path", "Use a dedicated existing Epson test export folder")
        output = store.root.resolve()
        if inbox.is_relative_to(output) or output.is_relative_to(inbox):
            raise AgentError("invalid_path", "Export inbox and artifact output must not overlap")
        self.inbox = inbox
        self.store = store
        self.stable_seconds = stable_seconds
        self.pending: dict[Path, tuple[FileStamp, float]] = {}
        self.processed: dict[Path, FileStamp] = {}

    def poll(self, now: float) -> list[dict[str, Any]]:
        events = []
        for path in sorted(self.inbox.iterdir()):
            if path.suffix.lower() not in {".png", ".bmp", ".tif", ".tiff", ".jpg", ".jpeg"}:
                continue  # Ignore .tmp/.part files, folders, sidecars and application locks.
            try:
                if not regular_file(path):
                    continue
                current = FileStamp.of(path.stat())
                if self.processed.get(path) == current:
                    continue
                previous = self.pending.get(path)
                if previous is None or previous[0] != current:
                    self.pending[path] = (current, now)
                    continue
                if now - previous[1] < self.stable_seconds:
                    continue
                with tempfile.TemporaryDirectory(prefix="export-", dir=self.store.staging) as stage:
                    snapshot = Path(stage) / "snapshot"
                    snapshot_export(path, snapshot, current)
                    result = self.store.commit(
                        snapshot,
                        {
                            "method": "epson_export_folder",
                            "source_filename": path.name,
                            "imported_at_utc": utc_now(),
                            "acquired_at_utc": None,
                            "source_file_modified_at_utc": datetime.fromtimestamp(
                                current.modified_ns / 1e9, timezone.utc
                            ).isoformat(),
                            "device_identity": None,
                            "driver_information": None,
                            "capture_settings": "not_verified_by_folder_import",
                            "quiet_seconds": self.stable_seconds,
                        },
                        deduplicate=True,
                    )
                self.processed[path] = current
                events.append({"source_filename": path.name, **result})
            except (AgentError, OSError) as exc:
                status = exc.status if isinstance(exc, AgentError) else "file_error"
                events.append({"source_filename": path.name, "status": status, "message": str(exc)})
                if isinstance(exc, AgentError) and status not in {"source_busy", "source_changed"}:
                    self.processed[path] = current
        return events
