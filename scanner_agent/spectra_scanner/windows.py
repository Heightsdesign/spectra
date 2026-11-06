"""Minimal Win32 owner window; pytwain supplies its own TWAIN event/message loop."""

from __future__ import annotations

import contextlib
import ctypes
from ctypes import wintypes
from typing import Iterator

from .common import AgentError


@contextlib.contextmanager
def hidden_window() -> Iterator[int]:
    user = ctypes.WinDLL("user32", use_last_error=True)
    create = user.CreateWindowExW
    create.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        ctypes.c_void_p,
    ]
    create.restype = wintypes.HWND
    destroy = user.DestroyWindow
    destroy.argtypes = [wintypes.HWND]
    destroy.restype = wintypes.BOOL
    # STATIC is a system-registered class. No WS_VISIBLE, executable callback or Tk runtime.
    owner = create(
        0, "STATIC", "SPECTRA S1 local TWAIN owner", 0, 0, 0, 1, 1, None, None, None, None
    )
    if not owner:
        raise AgentError("window_unavailable", "Could not create the local TWAIN owner window")
    try:
        yield int(owner)
    finally:
        destroy(owner)


@contextlib.contextmanager
def process_job(pid: int) -> Iterator[None]:
    """Confine our worker/helper tree; closing this job never kills existing Epson apps."""

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("min_working_set", ctypes.c_size_t),
            ("max_working_set", ctypes.c_size_t),
            ("active_processes", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in ("reads", "writes", "other", "read_bytes", "write_bytes", "other_bytes")
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", BasicLimits),
            ("io", IoCounters),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t),
            ("peak_job_memory", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateJobObjectW
    create.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    create.restype = wintypes.HANDLE
    configure = kernel.SetInformationJobObject
    configure.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    configure.restype = wintypes.BOOL
    assign = kernel.AssignProcessToJobObject
    assign.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    assign.restype = wintypes.BOOL
    open_process = kernel.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    job = create(None, None)
    if not job:
        raise AgentError("process_isolation_unavailable", "Cannot create a driver-process job")
    try:
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not configure(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise AgentError(
                "process_isolation_unavailable", "Cannot configure driver-process containment"
            )
        child = open_process(0x0101, False, pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        if not child:
            raise AgentError("process_isolation_unavailable", "Cannot contain the driver worker")
        try:
            if not assign(job, child):
                raise AgentError(
                    "process_isolation_unavailable", "Cannot assign driver worker to its job"
                )
        finally:
            close(child)
        yield
    finally:
        close(job)
