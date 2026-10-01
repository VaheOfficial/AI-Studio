"""Process helpers: killing a process tree, and tying native child servers to this server's lifetime."""

from __future__ import annotations

import atexit
import subprocess
import threading

import psutil

from .osenv import IS_WINDOWS

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r_ops", "w_ops", "o_ops", "r_bytes", "w_bytes", "o_bytes")]

    class _BasicLimits(ctypes.Structure):
        _fields_ = [("per_process_time", ctypes.c_int64), ("per_job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                    ("active_processes", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                    ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", _BasicLimits), ("io", _IoCounters), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process_memory", ctypes.c_size_t),
                    ("peak_job_memory", ctypes.c_size_t)]

    _KILL_ON_JOB_CLOSE = 0x2000
    _EXTENDED_LIMIT_INFO = 9
    _job_handle: int | None = None

    def _bind_windows(proc: subprocess.Popen[str]) -> None:
        """A job object that Windows kills when this server process exits, however it exits."""
        global _job_handle
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.OpenProcess.restype = wintypes.HANDLE
        if _job_handle is None:
            job = kernel32.CreateJobObjectW(None, None)
            limits = _ExtendedLimits()
            limits.basic.flags = _KILL_ON_JOB_CLOSE
            if not job or not kernel32.SetInformationJobObject(job, _EXTENDED_LIMIT_INFO, ctypes.byref(limits),
                                                               ctypes.sizeof(limits)):
                raise OSError(ctypes.get_last_error(), "Could not create a kill-on-close job object")
            _job_handle = job
        handle = kernel32.OpenProcess(0x0100 | 0x0001, False, proc.pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        if not handle:
            raise OSError(ctypes.get_last_error(), f"Could not open process {proc.pid}")
        try:
            if not kernel32.AssignProcessToJobObject(wintypes.HANDLE(_job_handle), wintypes.HANDLE(handle)):
                raise OSError(ctypes.get_last_error(), f"Could not bind process {proc.pid} to the server lifetime")
        finally:
            kernel32.CloseHandle(wintypes.HANDLE(handle))


# macOS / Linux: children bound to the server's lifetime are killed when it exits normally or on a signal the
# server handles (uvicorn turns SIGINT/SIGTERM into a normal shutdown). A SIGKILLed server can't clean up; the
# desktop app also kills the whole tree when it quits.
_bound: list[int] = []
_bound_lock = threading.Lock()


def kill_bound() -> None:
    """Kill the bound children now (POSIX; on Windows the job object does it when the process ends)."""
    with _bound_lock:
        pids, _bound[:] = list(_bound), []
    for pid in pids:
        kill_tree(pid)


def bind_to_server_lifetime(proc: subprocess.Popen[str]) -> None:
    """Make ``proc`` die with this server (for native child servers that, unlike our Python workers, can't watch
    a parent pid)."""
    if IS_WINDOWS:
        _bind_windows(proc)
        return
    with _bound_lock:
        if not _bound:
            atexit.register(kill_bound)
        _bound.append(proc.pid)


def kill_tree(proc: subprocess.Popen[str] | int) -> None:
    """Kill a process and all its descendants (venv launchers, ``python -m uv`` and shells each run the real work
    in a child process)."""
    pid = proc if isinstance(proc, int) else proc.pid
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    for child in parent.children(recursive=True):
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    try:
        parent.kill()
    except psutil.NoSuchProcess:
        pass
