"""Stop ends the agent a wrapper started, not only the wrapper."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time

import psutil

from dodaios.core.process_tree import kill_with_descendants

# A wrapper that starts the "real" worker and waits on it, like node codex.js.
_WRAPPER = (
    "import subprocess, sys; "
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
    "print(child.pid, flush=True); child.wait()"
)


def _gone(pid: int, within_s: float = 10.0) -> bool:
    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.05)
    return False


def test_kills_the_worker_a_wrapper_started() -> None:
    async def scenario() -> tuple[int, int]:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", _WRAPPER, stdout=subprocess.PIPE
        )
        assert proc.stdout is not None
        worker = int((await proc.stdout.readline()).decode().strip())
        kill_with_descendants(proc)
        await asyncio.wait_for(proc.wait(), timeout=10)
        return proc.pid, worker

    wrapper, worker = asyncio.run(scenario())
    assert _gone(wrapper)
    assert _gone(worker)


def test_a_finished_process_is_left_alone() -> None:
    class Done:
        returncode = 0
        pid = 4

        def kill(self) -> None:
            raise AssertionError("a finished process must not be killed again")

    kill_with_descendants(Done())


def test_a_process_without_a_pid_is_only_asked_to_die() -> None:
    killed: list[bool] = []

    class Remote:
        returncode = None
        pid = None

        def kill(self) -> None:
            killed.append(True)

    kill_with_descendants(Remote())
    assert killed == [True]
