"""The instance lock and the server record: the two things clients trust."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from daemonkit.lock import InstanceLock, is_locked
from daemonkit.record import (
    READY,
    ServerRecord,
    new_token,
    read_record,
    remove_record,
    token_matches,
    write_record,
)

REPO = Path(__file__).resolve().parents[3]


def test_a_second_holder_is_refused_until_the_first_releases(tmp_path: Path) -> None:
    path = tmp_path / "srv.lock"
    first, second = InstanceLock(path), InstanceLock(path)
    assert first.acquire()
    assert not second.acquire()
    assert is_locked(path)
    first.release()
    assert not is_locked(path)
    assert second.acquire()
    second.release()


def test_hold_raises_when_taken(tmp_path: Path) -> None:
    path = tmp_path / "srv.lock"
    owner = InstanceLock(path)
    assert owner.acquire()
    with pytest.raises(TimeoutError):
        with InstanceLock(path).hold(timeout=0.1):
            pass
    owner.release()


def test_is_locked_is_false_for_a_missing_file(tmp_path: Path) -> None:
    assert not is_locked(tmp_path / "never.lock")


def test_the_lock_dies_with_its_process(tmp_path: Path) -> None:
    """A crashed server leaves no stale lock: the OS drops it."""
    path = tmp_path / "srv.lock"
    holder = subprocess.Popen(  # noqa: S603 - test helper
        [
            sys.executable,
            "-c",
            "import sys, time; from pathlib import Path; from daemonkit.lock import InstanceLock;"
            f"lock = InstanceLock(Path({str(path)!r})); assert lock.acquire();"
            "print('held', flush=True); time.sleep(60)",
        ],
        cwd=REPO,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        assert is_locked(path)
        holder.kill()
        holder.wait(10)
        deadline = time.monotonic() + 5
        while is_locked(path) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not is_locked(path)
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(10)


def test_a_child_does_not_inherit_the_lock(tmp_path: Path) -> None:
    """A helper the server starts must not keep the lock alive after the server."""
    path = tmp_path / "srv.lock"
    lock = InstanceLock(path)
    assert lock.acquire()
    child = subprocess.Popen(  # noqa: S603 - test helper
        [sys.executable, "-c", "import time; time.sleep(30)"], close_fds=False
    )
    try:
        lock.release()
        assert not is_locked(path)
    finally:
        child.kill()
        child.wait(10)


def test_record_round_trip_and_owner_only_permissions(tmp_path: Path) -> None:
    path = tmp_path / "state" / "srv.json"
    token = new_token()
    record = ServerRecord(pid=os.getpid(), state=READY, port=47821, token=token, info={"a": 1})
    write_record(path, record)
    assert read_record(path) == record
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o777 == 0o600
    assert not list(path.parent.glob(".*.tmp"))


@pytest.mark.parametrize(
    "text",
    ["", "not json", "[]", '{"pid": 0}', '{"pid": 12, "state": "weird"}', '{"pid": "x"}'],
)
def test_anything_but_a_record_reads_as_none(tmp_path: Path, text: str) -> None:
    path = tmp_path / "srv.json"
    path.write_text(text, encoding="utf-8")
    assert read_record(path) is None


def test_remove_record_keeps_a_record_of_another_pid(tmp_path: Path) -> None:
    path = tmp_path / "srv.json"
    write_record(path, ServerRecord(pid=4242))
    assert not remove_record(path, pid=1111)
    assert path.exists()
    assert remove_record(path, pid=4242)
    assert not path.exists()
    assert remove_record(path)  # already gone is fine


def test_token_matching() -> None:
    token = new_token()
    assert len(token) >= 40
    assert token_matches(token, token)
    assert not token_matches("wrong", token)
    assert not token_matches(None, token)
    assert not token_matches("", "")
