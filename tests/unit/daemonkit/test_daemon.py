"""``Daemon`` end to end: a real server process, started, found and stopped by a client."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from daemonkit import AlreadyRunning, Daemon, StartTimeout
from daemonkit.process import pid_alive
from daemonkit.record import ServerRecord, write_record
from daemonkit.service import NullServiceManager, ServiceSpec, ServiceStatus

REPO = Path(__file__).resolve().parents[3]

#: A tiny server: claims the name, says it is ready on a made-up port, and runs
#: until it is asked to stop. A "crash" file makes its first run die.
SERVER = """
import sys, time
from pathlib import Path
from daemonkit import Daemon
state, crash = Path(sys.argv[1]), Path(sys.argv[2])
if crash.exists():
    crash.unlink()
    sys.exit(3)
daemon = Daemon("srv", [], state_dir=state)
with daemon.claim() as claim:
    claim.ready(port=40000 + len(str(state)) % 1000, version="1.0", flavour="test")
    while not claim.stop_requested():
        time.sleep(0.05)
"""


def _daemon(tmp_path: Path, **kwargs: object) -> Daemon:
    script = tmp_path / "server.py"
    script.write_text(SERVER, encoding="utf-8")
    state = tmp_path / "state"
    return Daemon(
        "srv",
        [sys.executable, str(script), str(state), str(tmp_path / "crash")],
        state_dir=state,
        cwd=REPO,
        env={"PYTHONPATH": str(REPO)},
        python=sys.executable,
        service=NullServiceManager("tests start directly"),
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.fixture
def daemon(tmp_path: Path):  # type: ignore[no-untyped-def]
    d = _daemon(tmp_path)
    yield d
    d.stop(timeout=10)


def test_ensure_running_starts_once_and_then_finds_it(daemon: Daemon) -> None:
    assert not daemon.is_running()
    record = daemon.ensure_running(timeout=30)
    assert record.ready and record.port is not None and record.version == "1.0"
    assert record.info == {"flavour": "test"}
    assert pid_alive(record.pid)
    again = daemon.ensure_running(timeout=5)
    assert again.pid == record.pid  # found, not started twice
    status = daemon.status()
    assert status.running and status.ready and status.record == record


def test_stop_ends_the_server_and_the_supervisor_does_not_restart_it(daemon: Daemon) -> None:
    record = daemon.ensure_running(timeout=30)
    assert daemon.stop(timeout=15)
    assert not daemon.is_running()
    assert not daemon.paths.record.exists()
    time.sleep(1.0)  # longer than the supervisor's first backoff
    assert not daemon.is_running()
    assert not pid_alive(record.pid)


def test_a_crashed_server_comes_back(tmp_path: Path) -> None:
    (tmp_path / "crash").write_text("x", encoding="utf-8")
    d = _daemon(tmp_path)
    try:
        record = d.ensure_running(timeout=30)  # first run dies, supervisor restarts it
        assert record.ready
        assert not (tmp_path / "crash").exists()
        assert "exited with code 3" in d.paths.log.read_text(encoding="utf-8")
    finally:
        d.stop(timeout=10)


def test_graceful_stop_is_tried_first(daemon: Daemon) -> None:
    daemon.ensure_running(timeout=30)
    seen: list[ServerRecord] = []
    assert daemon.stop(timeout=15, graceful=seen.append)
    assert len(seen) == 1 and seen[0].ready


def test_a_second_claim_is_refused(tmp_path: Path) -> None:
    d = Daemon("srv", [], state_dir=tmp_path)
    with d.claim() as claim:
        claim.ready(port=1)
        with pytest.raises(AlreadyRunning) as raised:
            d.claim(wait=0.1)
        assert raised.value.record is not None and raised.value.record.port == 1
    assert not d.is_running()
    assert not d.paths.record.exists()


def test_a_stale_record_is_not_reported_and_is_cleaned(tmp_path: Path) -> None:
    d = Daemon("srv", [], state_dir=tmp_path)
    write_record(d.paths.record, ServerRecord(pid=999_999, state="ready", port=5))
    assert d.find() is None
    assert not d.paths.record.exists()


def test_a_record_written_by_a_live_claim_is_found(tmp_path: Path) -> None:
    d = Daemon("srv", [], state_dir=tmp_path)
    with d.claim() as claim:
        assert d.find() is not None and not d.find().ready  # type: ignore[union-attr]
        claim.ready(port=7, token="t")  # noqa: S106 - a fixture value
        found = d.find()
        assert found is not None and found.ready and found.pid == os.getpid()
        claim.stopping()
        assert d.find().state == "stopping"  # type: ignore[union-attr]


def test_wait_ready_times_out_with_the_log_path(tmp_path: Path) -> None:
    d = Daemon("srv", [], state_dir=tmp_path)
    with pytest.raises(StartTimeout, match="srv.log"):
        d.wait_ready(0.2)


def test_ensure_running_uses_a_custom_start(tmp_path: Path) -> None:
    d = Daemon("srv", [], state_dir=tmp_path)
    holder: list[object] = []

    def start() -> None:
        claim = d.claim()
        claim.ready(port=99)
        holder.append(claim)

    record = d.ensure_running(timeout=5, start=start)
    assert record.port == 99
    holder[0].release()  # type: ignore[attr-defined]


def test_the_ready_probe_must_pass(tmp_path: Path) -> None:
    d = Daemon("srv", [], state_dir=tmp_path)
    with d.claim() as claim:
        claim.ready(port=1)
        with pytest.raises(StartTimeout):
            d.wait_ready(0.3, ready=lambda _r: False)
        assert d.wait_ready(1, ready=lambda r: r.port == 1).port == 1


def test_supervisor_argv_carries_state_env_and_server(tmp_path: Path) -> None:
    d = Daemon(
        "srv",
        ["server", "--flag"],
        state_dir=tmp_path,
        cwd=tmp_path,
        env={"B": "2", "A": "1"},
        python="/opt/py/bin/python3",
    )
    argv = d.supervisor_argv(windowless=False)
    assert argv[:3] == ["/opt/py/bin/python3", "-m", "daemonkit.supervise"]
    assert argv[argv.index("--state-dir") + 1] == str(tmp_path)
    assert argv[argv.index("--cwd") + 1] == str(tmp_path)
    assert argv.count("--env") == 2 and "A=1" in argv and "B=2" in argv
    assert argv[argv.index("--") + 1 :] == ["server", "--flag"]
    custom = Daemon("srv", ["x"], state_dir=tmp_path, supervisor_command=["app.exe", "--sv"])
    assert custom.supervisor_argv()[:2] == ["app.exe", "--sv"]


class _RecordingManager:
    mechanism = "fake"

    def __init__(self, installed: bool, starts: bool) -> None:
        self._installed = installed
        self._starts = starts
        self.calls: list[str] = []

    def available(self) -> tuple[bool, str]:
        return True, ""

    def install(self, spec: ServiceSpec, *, start_at: str = "login", start_now: bool = True):  # type: ignore[no-untyped-def]
        self.calls.append(f"install:{start_at}:{start_now}")
        return ServiceStatus(self.mechanism, True, True)

    def uninstall(self, spec: ServiceSpec, *, stop: bool = True) -> ServiceStatus:
        self.calls.append(f"uninstall:{stop}")
        return ServiceStatus(self.mechanism, True, False)

    def status(self, spec: ServiceSpec) -> ServiceStatus:
        return ServiceStatus(self.mechanism, True, self._installed)

    def start(self, spec: ServiceSpec) -> bool:
        self.calls.append("start")
        return self._starts

    def stop(self, spec: ServiceSpec) -> bool:
        return True


def test_default_start_goes_through_an_installed_service(tmp_path: Path) -> None:
    manager = _RecordingManager(installed=True, starts=True)
    d = Daemon("srv", ["server"], state_dir=tmp_path, service=manager)
    spawned: list[int] = []
    d.start = lambda: spawned.append(1) or 0  # type: ignore[method-assign]
    d._default_start()
    assert manager.calls == ["start"]
    assert spawned == []


def test_default_start_falls_back_to_spawning(tmp_path: Path) -> None:
    manager = _RecordingManager(installed=True, starts=False)
    d = Daemon("srv", ["server"], state_dir=tmp_path, service=manager)
    spawned: list[int] = []
    d.start = lambda: spawned.append(1) or 0  # type: ignore[method-assign]
    d._default_start()
    assert spawned == [1]


def test_install_service_registers_the_supervisor(tmp_path: Path) -> None:
    manager = _RecordingManager(installed=False, starts=True)
    d = Daemon("srv", ["server"], state_dir=tmp_path, service=manager, label="com.example.srv")
    d.install_service(start_at="boot", start_now=False)
    assert manager.calls == ["install:boot:False"]
    spec = d.service_spec()
    assert spec.label == "com.example.srv"
    assert spec.argv[-2:] == ("--", "server")
    assert spec.log_path == str(d.paths.log)


def test_invalid_names_are_refused(tmp_path: Path) -> None:
    for bad in ("", "../x", "a b", "-x", "x" * 65):
        with pytest.raises(ValueError):
            Daemon(bad, [], state_dir=tmp_path)
