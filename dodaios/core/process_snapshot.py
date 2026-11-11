"""Every process on the machine in one read.

Asking the operating system about processes one at a time costs a system call
or more per process and per question. On a Windows desktop with a thousand
processes that added up to over a minute for a single pass (measured
2026-11-11), which rules it out for anything that refreshes on a clock.

Windows hands out the whole table in one call, so that is what is read there:
parent, name, start time, processor time, memory and thread count of every
process, in a few milliseconds. Elsewhere ``psutil`` walks ``/proc`` (or its
macOS equivalent), which is fast enough.

Command lines are a separate, slower question and are answered per process on
request (:func:`command_line`); callers cache them, because a process's
arguments never change.

Read-only. Nothing here runs unless it is called.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass

_WINDOWS = sys.platform == "win32"
#: 100-nanosecond steps between 1601 and 1970, the two clocks' starting points.
_FILETIME_EPOCH = 116_444_736_000_000_000
_SYSTEM_PROCESS_INFORMATION = 5
_STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_COMMAND_LINE_INFORMATION = 60
_MAX_ARGUMENTS = 16
_MAX_ARGUMENT_CHARS = 400


@dataclass(slots=True)
class ProcessRow:
    """What one process looked like at the moment of the read."""

    pid: int
    ppid: int
    name: str
    #: Seconds since the Unix epoch.
    create_time: float
    #: Processor seconds used since it started, user and kernel together.
    cpu_seconds: float
    #: Bytes of physical memory that are this process's alone where the
    #: platform tells (Windows: the private working set), else its resident size.
    memory: int
    threads: int


class _UnicodeString(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_ushort),
        ("maximum_length", ctypes.c_ushort),
        ("buffer", ctypes.c_void_p),
    ]


class _SystemProcessInformation(ctypes.Structure):
    _fields_ = [
        ("next_entry_offset", ctypes.c_ulong),
        ("number_of_threads", ctypes.c_ulong),
        ("working_set_private_size", ctypes.c_longlong),
        ("hard_fault_count", ctypes.c_ulong),
        ("number_of_threads_high_watermark", ctypes.c_ulong),
        ("cycle_time", ctypes.c_ulonglong),
        ("create_time", ctypes.c_longlong),
        ("user_time", ctypes.c_longlong),
        ("kernel_time", ctypes.c_longlong),
        ("image_name", _UnicodeString),
        ("base_priority", ctypes.c_long),
        ("unique_process_id", ctypes.c_void_p),
        ("inherited_from_unique_process_id", ctypes.c_void_p),
        ("handle_count", ctypes.c_ulong),
        ("session_id", ctypes.c_ulong),
        ("unique_process_key", ctypes.c_void_p),
        ("peak_virtual_size", ctypes.c_size_t),
        ("virtual_size", ctypes.c_size_t),
        ("page_fault_count", ctypes.c_ulong),
        ("peak_working_set_size", ctypes.c_size_t),
        ("working_set_size", ctypes.c_size_t),
    ]


def _read_windows() -> list[ProcessRow]:
    ntdll = ctypes.WinDLL("ntdll")  # type: ignore[attr-defined]
    query = ntdll.NtQuerySystemInformation
    query.argtypes = [ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
    query.restype = ctypes.c_ulong
    size = ctypes.c_ulong(1 << 20)
    for _attempt in range(6):
        buffer = ctypes.create_string_buffer(size.value)
        needed = ctypes.c_ulong(0)
        status = query(_SYSTEM_PROCESS_INFORMATION, buffer, size.value, ctypes.byref(needed))
        if status == 0:
            break
        if status != _STATUS_INFO_LENGTH_MISMATCH:
            raise OSError(f"NtQuerySystemInformation failed: 0x{status:08X}")
        # The table grew between the two calls; ask again with room to spare.
        size = ctypes.c_ulong(max(needed.value, size.value) + (1 << 18))
    else:
        raise OSError("the process table kept growing")
    rows: list[ProcessRow] = []
    base = ctypes.addressof(buffer)
    offset = 0
    while True:
        entry = _SystemProcessInformation.from_address(base + offset)
        pid = int(entry.unique_process_id or 0)
        name = ""
        if entry.image_name.buffer and entry.image_name.length:
            name = ctypes.wstring_at(entry.image_name.buffer, entry.image_name.length // 2)
        if pid != 0:  # 0 is the idle counter, not a process
            rows.append(
                ProcessRow(
                    pid=pid,
                    ppid=int(entry.inherited_from_unique_process_id or 0),
                    name=name or ("System" if pid == 4 else ""),
                    create_time=max(0.0, (entry.create_time - _FILETIME_EPOCH) / 1e7),
                    cpu_seconds=(entry.user_time + entry.kernel_time) / 1e7,
                    memory=int(entry.working_set_private_size) or int(entry.working_set_size),
                    threads=int(entry.number_of_threads),
                )
            )
        if entry.next_entry_offset == 0:
            return rows
        offset += entry.next_entry_offset


def _read_portable() -> list[ProcessRow]:
    import psutil

    rows: list[ProcessRow] = []
    attrs = ["pid", "ppid", "name", "create_time", "cpu_times", "memory_info", "num_threads"]
    for process in psutil.process_iter(attrs):
        info = process.info
        times = info.get("cpu_times")
        memory = info.get("memory_info")
        rows.append(
            ProcessRow(
                pid=int(info["pid"]),
                ppid=int(info.get("ppid") or 0),
                name=str(info.get("name") or ""),
                create_time=float(info.get("create_time") or 0.0),
                cpu_seconds=float(times.user + times.system) if times else 0.0,
                memory=int(memory.rss) if memory else 0,
                threads=int(info.get("num_threads") or 0),
            )
        )
    return rows


def read_processes() -> list[ProcessRow]:
    """Every process the system lists, read at one moment."""
    if _WINDOWS:
        try:
            return _read_windows()
        except (OSError, AttributeError, ValueError):  # an exotic Windows build
            pass  # the portable reader below still answers
    return _read_portable()


def _command_line_windows(pid: int) -> tuple[str, ...]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    ntdll = ctypes.WinDLL("ntdll")  # type: ignore[attr-defined]
    shell32 = ctypes.WinDLL("shell32")  # type: ignore[attr-defined]
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    ntdll.NtQueryInformationProcess.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    ntdll.NtQueryInformationProcess.restype = ctypes.c_ulong
    shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
    if not handle:
        return ()
    try:
        needed = ctypes.c_ulong(0)
        ntdll.NtQueryInformationProcess(
            handle, _PROCESS_COMMAND_LINE_INFORMATION, None, 0, ctypes.byref(needed)
        )
        if needed.value == 0:
            return ()
        buffer = ctypes.create_string_buffer(needed.value)
        status = ntdll.NtQueryInformationProcess(
            handle, _PROCESS_COMMAND_LINE_INFORMATION, buffer, needed.value, ctypes.byref(needed)
        )
        if status != 0:
            return ()
        text = _UnicodeString.from_buffer(buffer)
        if not text.buffer or not text.length:
            return ()
        line = ctypes.wstring_at(text.buffer, text.length // 2)
    finally:
        kernel32.CloseHandle(handle)
    count = ctypes.c_int(0)
    parts = shell32.CommandLineToArgvW(line, ctypes.byref(count))
    if not parts:
        return ()
    try:
        return tuple(
            (parts[index] or "")[:_MAX_ARGUMENT_CHARS]
            for index in range(min(count.value, _MAX_ARGUMENTS))
        )
    finally:
        kernel32.LocalFree(parts)


def command_line(pid: int) -> tuple[str, ...]:
    """The first arguments ``pid`` was started with; empty when it will not say.

    Cut to a handful of arguments: enough to tell what runs, and no reason to
    hold a long prompt or a pasted file that someone passed on a command line.
    """
    if _WINDOWS:
        try:
            return _command_line_windows(pid)
        except (OSError, AttributeError, ValueError):  # empty is the documented answer
            return ()
    import psutil

    try:
        parts = psutil.Process(pid).cmdline()
    except (psutil.Error, OSError):  # it ended or belongs to another user: no arguments
        return ()
    return tuple(part[:_MAX_ARGUMENT_CHARS] for part in parts[:_MAX_ARGUMENTS])
