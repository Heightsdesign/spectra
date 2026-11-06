from __future__ import annotations

import contextlib
import json
import math
import os
import platform
import struct
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

AGENT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = AGENT_ROOT / "local_data"


class AgentError(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def identifier() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid4().hex


def json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if hasattr(value, "Whole") and hasattr(value, "Frac"):
        return value.Whole + value.Frac / 65536
    return str(value)


def write_json_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(json_safe(value), output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def environment() -> dict[str, Any]:
    from . import __version__

    return {
        "agent_version": __version__,
        "os": platform.platform(),
        "python": sys.version,
        "python_bits": struct.calcsize("P") * 8,
        "python_machine": platform.machine(),
        "pytwain": package_version("pytwain"),
        "Pillow": package_version("Pillow"),
        "wia_support": "not_probed_or_assumed",
        "physical_scan_performed": False,
    }


def confined_data_dir(path: Path) -> Path:
    # Even --data-dir cannot route S1 originals to backend/customer storage.
    base = DATA_ROOT.resolve()
    if base != DATA_ROOT.absolute():
        raise AgentError("invalid_path", "local_data must not be a symlink or junction")
    candidate = path.resolve()
    if not candidate.is_relative_to(base):
        raise AgentError("invalid_path", "S1 output must stay under scanner_agent/local_data")
    return candidate


@contextlib.contextmanager
def agent_lock(root: Path) -> Iterator[None]:
    """OS lock released on crashes; do not delete the persistent lock inode."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".agent.lock").open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise AgentError("busy", "Another S1 process holds this output-directory lock") from exc
        try:
            yield
        finally:
            lock.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
