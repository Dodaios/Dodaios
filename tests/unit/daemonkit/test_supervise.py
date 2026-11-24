"""The supervisor with real child processes and short timings."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from daemonkit.lock import InstanceLock
from daemonkit.paths import DaemonPaths
from daemonkit.supervise import (
    EXIT_CONFIG,
    Supervisor,
    SupervisorPolicy,
    read_stop_request,
    write_stop_request,
)

REPO = Path(__file__).resolve().parents[3]

FAST = SupervisorPolicy(
    min_backoff=0.05,
    max_backoff=0.2,
    stable_after=5.0,
    stop_grace=0.3,
    standby_poll=0.05,
    poll=0.02,
)


def _counting_child(counter: Path, *, fail_times: int, final: int = 0) -> list[str]:
    """A child that exits 1 for its first ``fail_times`` runs, then ``final``."""
    return [
        sys.executable,
        "-c",
        "from pathlib import Path; import sys;"
        f"p = Path({str(counter)!r}); n = int(p.read_text()) if p.exists() else 0;"
        "p.write_text(str(n + 1));"
        f"sys.exit(1 if n < {fail_times} else {final})",
    ]


def _paths(tmp_path: Path) -> DaemonPaths:
    return DaemonPaths(tmp_path, "srv")


def test_restarts_after_crashes_until_a_clean_exit(tmp_path: Path) -> None:
    counter = tmp_path / "runs"
    sup = Supervisor(_counting_child(counter, fail_times=2), _paths(tmp_path), policy=FAST)
    assert sup.run() == 0
    assert sup.starts == 3
    assert counter.read_text() == "3"


def test_a_configuration_error_is_not_restarted(tmp_path: Path) -> None:
    counter = tmp_path / "runs"
    child = _counting_child(counter, fail_times=0, final=EXIT_CONFIG)
    sup = Supervisor(child, _paths(tmp_path), policy=FAST)
    assert sup.run() == EXIT_CONFIG
    assert sup.starts == 1


def test_a_stop_request_ends_a_running_server_and_the_supervisor(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    sup = Supervisor([sys.executable, "-c", "import time; time.sleep(60)"], paths, policy=FAST)
    result: list[int] = []
    runner = threading.Thread(target=lambda: result.append(sup.run()))
    runner.start()
    deadline = time.monotonic() + 10
    while sup.starts == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert sup.starts == 1
    write_stop_request(paths.stop)
    runner.join(15)
    assert not runner.is_alive()
    assert result == [0]
    assert sup.child.poll() is not None
    assert read_stop_request(paths.stop) is None  # consumed


def test_a_signal_stop_terminates_the_server_at_once(tmp_path: Path) -> None:
    policy = SupervisorPolicy(stop_grace=60.0, poll=0.02)
    sup = Supervisor(
        [sys.executable, "-c", "import time; time.sleep(60)"], _paths(tmp_path), policy=policy
    )
    result: list[int] = []
    runner = threading.Thread(target=lambda: result.append(sup.run()))
    runner.start()
    while sup.starts == 0:
        time.sleep(0.02)
    started = time.monotonic()
    sup.request_stop()
    runner.join(15)
    assert result == [0]
    assert time.monotonic() - started < 10  # did not wait out the 60 s grace


def test_stands_by_while_another_server_holds_the_lock(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    other = InstanceLock(paths.lock)
    assert other.acquire()
    counter = tmp_path / "runs"
    sup = Supervisor(_counting_child(counter, fail_times=0), paths, policy=FAST)
    result: list[int] = []
    runner = threading.Thread(target=lambda: result.append(sup.run()))
    runner.start()
    time.sleep(0.4)
    assert sup.starts == 0  # waiting, not fighting
    other.release()
    runner.join(10)
    assert result == [0]
    assert sup.starts == 1


def test_already_running_backs_off_instead_of_looping(tmp_path: Path) -> None:
    """Exit 75 with this lock free (the application's own lock is taken) must not spin."""
    counter = tmp_path / "runs"
    child = _counting_child(counter, fail_times=0, final=75)
    policy = SupervisorPolicy(min_backoff=0.2, max_backoff=0.4, stable_after=60.0, poll=0.02)
    sup = Supervisor(child, _paths(tmp_path), policy=policy)
    runner = threading.Thread(target=sup.run)
    runner.start()
    time.sleep(1.2)
    sup.request_stop()
    runner.join(10)
    # Without the pause this would be dozens of starts in 1.2 s.
    assert 2 <= sup.starts <= 6


def test_an_old_stop_request_does_not_stop_a_new_supervisor(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.stop.write_text('{"requested_at": 1000.0}', encoding="utf-8")
    counter = tmp_path / "runs"
    sup = Supervisor(_counting_child(counter, fail_times=1), paths, policy=FAST)
    assert sup.run() == 0
    assert sup.starts == 2
    assert not paths.stop.exists()


def test_command_line_runs_the_server_and_logs(tmp_path: Path) -> None:
    log = tmp_path / "srv.log"
    result = subprocess.run(  # noqa: S603 - test helper
        [
            sys.executable,
            "-m",
            "daemonkit.supervise",
            "--state-dir",
            str(tmp_path),
            "--name",
            "srv",
            "--env",
            "DK_TEST=hello",
            "--min-backoff",
            "0.05",
            "--",
            sys.executable,
            "-c",
            "import os; print('server says', os.environ['DK_TEST'], flush=True)",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    text = log.read_text(encoding="utf-8")
    assert "server says hello" in text
    assert "supervisor" in text and "exits" in text


def test_command_line_without_a_server_command_is_refused(tmp_path: Path) -> None:
    result = subprocess.run(  # noqa: S603 - test helper
        [sys.executable, "-m", "daemonkit.supervise", "--state-dir", str(tmp_path), "--name", "x"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 2
