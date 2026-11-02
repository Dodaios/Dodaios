"""The machine-wide gpu-heavy lock of scripts/unreal/with_lock.py (G0.6)."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from scripts.unreal import _common as common
from scripts.unreal import with_lock


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(with_lock.HELD_ENV, raising=False)


def _lock(tmp_path, pid=1000, alive=lambda _pid: True, messages=None, **kwargs):
    sink = [] if messages is None else messages
    kwargs.setdefault("poll", 0)
    return with_lock.MachineLock(
        "job", ["cmd", "arg"], directory=tmp_path, pid=pid, alive=alive,
        echo=sink.append, **kwargs,
    )


def test_the_plan_limits_are_one_holder_and_a_ninety_minute_hold():
    assert common.LOCK_HOLDERS == 1
    assert common.MAX_HOLD_MINUTES == 90
    assert common.MAX_PARALLEL_ACTIONS == 10
    assert common.MAX_HEADLESS_JOBS == 4
    assert common.QUEUE_DEPTH_WARN == 8


def test_the_lock_lives_in_the_shared_machine_folder_unless_overridden():
    if os.name == "nt":
        assert with_lock.lock_dir({}) == with_lock.DEFAULT_LOCK_DIR
    assert str(with_lock.lock_dir({with_lock.LOCK_DIR_ENV: "X:/locks"})).replace("\\", "/") == (
        "X:/locks"
    )


def test_the_holder_file_says_who_what_when_and_pid_and_goes_on_release(tmp_path):
    lock = _lock(tmp_path)
    with lock:
        holder = json.loads(lock.holder_path.read_text(encoding="utf-8"))
        assert holder["holder"] == "job"
        assert holder["command"] == "cmd arg"
        assert holder["pid"] == 1000
        assert holder["started"]
        assert os.environ[with_lock.HELD_ENV].endswith("|1000")
        assert not list(lock.queue_dir.glob("*.json")), "the ticket goes once the lock is held"
    assert not lock.holder_path.exists()
    assert with_lock.HELD_ENV not in os.environ


def test_waiters_queue_first_in_first_out(tmp_path):
    queue = tmp_path / "gpu-heavy.queue"
    queue.mkdir()
    older = queue / f"{1:020d}-77.json"
    older.write_text(json.dumps({"pid": 77, "label": "older"}), encoding="utf-8")
    sleeps: list[int] = []

    def sleep(_seconds):
        sleeps.append(1)
        assert len(sleeps) < 50, "never got the lock"
        if len(sleeps) == 3:
            older.unlink()  # the older waiter had its turn and left

    lock = _lock(tmp_path, alive=lambda pid: pid in (77, 1000), sleep=sleep)
    lock.acquire()
    try:
        assert len(sleeps) == 3, "the free lock was taken while an older ticket waited"
    finally:
        lock.release()


def test_tickets_of_dead_processes_are_dropped(tmp_path):
    queue = tmp_path / "gpu-heavy.queue"
    queue.mkdir()
    dead = queue / f"{1:020d}-55.json"
    dead.write_text(json.dumps({"pid": 55}), encoding="utf-8")
    lock = _lock(tmp_path, alive=lambda pid: pid != 55, sleep=lambda _s: pytest.fail("waited"))
    with lock:
        assert not dead.exists()


def test_a_waiter_waits_on_a_busy_lock_and_a_wait_limit_cleans_its_ticket(tmp_path):
    messages: list[str] = []
    first = _lock(tmp_path, pid=1)
    first.acquire()
    try:
        now = [0.0]

        def sleep(_s):
            now[0] += 10

        # pid 1 counts as dead here only so the second lock does not read the
        # first one's marker in this same test process as its own parent's.
        second = _lock(tmp_path, pid=2, clock=lambda: now[0], sleep=sleep, wait_timeout=35,
                       messages=messages, alive=lambda pid: pid != 1)
        with pytest.raises(with_lock.LockTimeout):
            second.acquire()
        assert now[0] > 30, "it waited before giving up"
        assert any("waiting for the gpu-heavy lock" in m and "held by job" in m for m in messages)
        assert not list(second.queue_dir.glob("*.json"))
    finally:
        first.release()


def test_a_hold_past_ninety_minutes_is_reported_loudly_and_nothing_is_killed(tmp_path):
    messages: list[str] = []
    first = _lock(tmp_path, pid=1)
    first.acquire()
    try:
        holder = json.loads(first.holder_path.read_text(encoding="utf-8"))
        holder["started_epoch"] -= 91 * 60
        first.holder_path.write_text(json.dumps(holder), encoding="utf-8")
        now = [0.0]
        second = _lock(tmp_path, pid=2, wait_timeout=5, messages=messages,
                       clock=lambda: now[0], sleep=lambda _s: now.__setitem__(0, now[0] + 1),
                       alive=lambda pid: pid != 1)
        with pytest.raises(with_lock.LockTimeout):
            second.acquire()
        assert any("LOCK HELD TOO LONG" in m and "nothing is killed" in m for m in messages)
        assert first.holder_path.exists(), "the long hold is still in place"
    finally:
        first.release()


def test_a_deep_queue_tells_the_orchestrator_to_stop_scheduling_builds(tmp_path):
    queue = tmp_path / "gpu-heavy.queue"
    queue.mkdir()
    for n in range(common.QUEUE_DEPTH_WARN + 1):
        (queue / f"{n:020d}-{500 + n}.json").write_text(json.dumps({"pid": 500 + n}), "utf-8")
    messages: list[str] = []
    now = [0.0]
    lock = _lock(tmp_path, wait_timeout=1, messages=messages, clock=lambda: now[0],
                 sleep=lambda _s: now.__setitem__(0, now[0] + 1))
    with pytest.raises(with_lock.LockTimeout):
        lock.acquire()
    assert any("LOCK QUEUE DEEP" in m for m in messages)


def test_a_job_under_the_lock_does_not_queue_for_it_again(tmp_path):
    outer = _lock(tmp_path, pid=1)
    outer.acquire()
    try:
        inner = _lock(tmp_path, pid=2, sleep=lambda _s: pytest.fail("nested lock waited"))
        with inner:
            assert inner.nested
            assert not list(inner.queue_dir.glob("*.json"))
        assert outer.holder_path.exists(), "the inner release left the outer hold alone"
    finally:
        outer.release()


def test_a_held_marker_of_a_dead_process_is_not_trusted(tmp_path, monkeypatch):
    monkeypatch.setenv(with_lock.HELD_ENV, f"{tmp_path / 'gpu-heavy.lock'}|4242")
    lock = _lock(tmp_path, pid=1, alive=lambda pid: pid != 4242)
    with lock:
        assert not lock.nested
        assert lock.holder_path.exists()


def test_a_running_process_is_alive_and_a_free_pid_is_not():
    assert with_lock.pid_alive(os.getpid())
    assert not with_lock.pid_alive(0)


class _FakeProcess:
    def __init__(self, timeout=False):
        self.timeout = timeout
        self.killed = False
        self.calls = 0

    def wait(self, timeout=None):
        self.calls += 1
        if self.timeout and self.calls == 1:
            raise subprocess.TimeoutExpired("cmd", timeout)
        return -9 if self.killed else 0

    def kill(self):
        self.killed = True


def _factory(tmp_path):
    return lambda label, command: _lock(tmp_path, pid=os.getpid())


def test_run_locked_runs_the_command_inside_the_hold_and_hands_down_the_marker(tmp_path):
    seen = {}

    def popen(command, cwd=None, env=None):
        seen["command"] = command
        seen["held"] = env[with_lock.HELD_ENV]
        seen["holder_file"] = (tmp_path / "gpu-heavy.holder.json").exists()
        return _FakeProcess()

    code = with_lock.run_locked(["a", "b"], label="x", popen=popen,
                                lock_factory=_factory(tmp_path))
    assert code == 0
    assert seen == {"command": ["a", "b"], "held": seen["held"], "holder_file": True}
    assert seen["held"].endswith(f"|{os.getpid()}")
    assert not (tmp_path / "gpu-heavy.holder.json").exists()


def test_run_locked_stops_only_its_own_job_after_the_hold_limit(tmp_path, capsys):
    process = _FakeProcess(timeout=True)
    code = with_lock.run_locked(["slow"], label="slow", popen=lambda *a, **k: process,
                                lock_factory=_factory(tmp_path), max_hold_minutes=0.01)
    assert code == 124
    assert process.killed
    assert "LOCK HOLD TIMEOUT" in capsys.readouterr().out
    assert not (tmp_path / "gpu-heavy.holder.json").exists()


def test_status_lists_the_live_holder_and_queue(tmp_path):
    with _lock(tmp_path, pid=os.getpid()):
        report = with_lock.status(tmp_path, alive=lambda _pid: True)
    assert report["holder"]["holder"] == "job"
    assert report["queue"] == []
    assert with_lock.status(tmp_path, alive=lambda _pid: True)["holder"] is None


def test_the_cli_needs_a_command():
    with pytest.raises(SystemExit):
        with_lock.main(["--label", "x"])


def test_the_blender_runner_takes_the_same_machine_lock(tmp_path, monkeypatch):
    from scripts.verse import blender

    monkeypatch.setenv(with_lock.LOCK_DIR_ENV, str(tmp_path))
    with blender.gpu_lock("cook hangar"):
        holder = json.loads((tmp_path / "gpu-heavy.holder.json").read_text(encoding="utf-8"))
        assert holder["holder"] == "blender cook hangar"
    assert not (tmp_path / "gpu-heavy.holder.json").exists()
