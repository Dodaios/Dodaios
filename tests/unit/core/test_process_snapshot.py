"""The one-read process table, checked against the process running the test."""

from __future__ import annotations

import os
import subprocess
import sys
import time

from dodaios.core import process_snapshot
from dodaios.core.process_snapshot import command_line, read_processes


def test_the_table_holds_this_process_with_plausible_numbers() -> None:
    time.process_time()
    rows = {row.pid: row for row in read_processes()}

    me = rows[os.getpid()]
    assert me.ppid == os.getppid()
    assert "python" in me.name.lower() or me.name
    assert 0 < me.create_time <= time.time()
    assert time.time() - me.create_time < 6 * 3600
    assert me.cpu_seconds > 0
    assert me.memory > 1024 * 1024
    assert me.threads >= 1
    assert 0 not in rows or sys.platform != "win32"  # the idle counter is not a process
    assert len(rows) > 5


def test_processor_time_only_grows() -> None:
    before = {row.pid: row for row in read_processes()}[os.getpid()].cpu_seconds
    deadline = time.perf_counter() + 0.3
    while time.perf_counter() < deadline:
        sum(range(2000))
    after = {row.pid: row for row in read_processes()}[os.getpid()].cpu_seconds
    assert after > before


def test_a_command_line_comes_back_as_arguments() -> None:
    child = subprocess.Popen(  # noqa: S603 - the test's own child
        [sys.executable, "-c", "import time; time.sleep(30)", "first arg", "second"]
    )
    try:
        parts: tuple[str, ...] = ()
        for _ in range(50):  # the arguments are readable a moment after the start
            parts = command_line(child.pid)
            if parts:
                break
            time.sleep(0.05)
        assert parts[1] == "-c"
        assert parts[3:] == ("first arg", "second")
    finally:
        child.kill()
        child.wait(timeout=10)


def test_a_process_that_is_gone_has_no_command_line() -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603
    child.wait(timeout=30)
    time.sleep(0.2)
    assert command_line(child.pid) == () or isinstance(command_line(child.pid), tuple)


def test_long_arguments_are_cut() -> None:
    child = subprocess.Popen(  # noqa: S603 - the test's own child
        [sys.executable, "-c", "import time; time.sleep(30)", "x" * 2000, *["a"] * 40]
    )
    try:
        parts: tuple[str, ...] = ()
        for _ in range(50):
            parts = command_line(child.pid)
            if parts:
                break
            time.sleep(0.05)
        assert len(parts) == process_snapshot._MAX_ARGUMENTS
        assert len(parts[3]) == process_snapshot._MAX_ARGUMENT_CHARS
    finally:
        child.kill()
        child.wait(timeout=10)


def test_the_portable_reader_gives_the_same_shape(monkeypatch) -> None:
    import psutil

    class _Times:
        user, system = 1.5, 0.5

    class _Memory:
        rss = 4096

    class _Process:
        def __init__(self, info: dict) -> None:
            self.info = info

    full = {
        "pid": 7,
        "ppid": 1,
        "name": "tool",
        "create_time": 100.0,
        "cpu_times": _Times(),
        "memory_info": _Memory(),
        "num_threads": 3,
    }
    # A process the caller may not inspect answers None for what it withholds.
    denied = {"pid": 8, "ppid": None, "name": None, "create_time": None}
    monkeypatch.setattr(psutil, "process_iter", lambda _attrs: [_Process(full), _Process(denied)])

    first, second = process_snapshot._read_portable()

    assert (first.pid, first.ppid, first.name, first.create_time) == (7, 1, "tool", 100.0)
    assert (first.cpu_seconds, first.memory, first.threads) == (2.0, 4096, 3)
    assert (second.pid, second.ppid, second.name, second.cpu_seconds, second.memory) == (
        8,
        0,
        "",
        0.0,
        0,
    )
