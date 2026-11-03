"""17.3 / A17.3, A17.4, A17.5: supervisor liveness, containment and the token rule."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import psutil
import pytest

from dodaios.verse_host import supervisor as supervisor_mod
from dodaios.verse_host.bridge import TokenBox, mint_token
from dodaios.verse_host.supervisor import BACKOFF_S, Supervisor, spawn_contained


class FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self._exit: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        self.killed = False

    async def wait(self) -> int:
        return await self._exit

    def kill(self) -> None:
        self.killed = True
        self.exit(-9)

    def exit(self, code: int) -> None:
        if not self._exit.done():
            self._exit.set_result(code)

    def alive(self) -> bool:
        return not self._exit.done()


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)


def _supervisor(tmp_path: Path, clock: Clock, spawned: list[FakeProcess], **kw: Any) -> Supervisor:
    exe = tmp_path / "Verse.exe"
    exe.write_text("dummy")
    tokens = TokenBox()

    async def spawn(argv: list[str], env: dict[str, str], cwd: Path) -> FakeProcess:
        p = FakeProcess(4000 + len(spawned))
        p.argv, p.env = argv, env  # type: ignore[attr-defined]
        spawned.append(p)
        return p

    sup = Supervisor(
        exe=lambda: exe,
        bridge_url=lambda: "ws://127.0.0.1:8765/api/verse/bridge",
        set_token=lambda t: tokens.set("launch", t),
        mint=mint_token,
        crash_dir=tmp_path / "crashes",
        spawn=spawn,
        clock=clock,
        sleep=clock.sleep,
        **kw,
    )
    sup.tokens = tokens  # type: ignore[attr-defined]
    return sup


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


async def test_restart_backoff_and_crash_loop(tmp_path: Path) -> None:
    clock, spawned = Clock(), []
    sup = _supervisor(tmp_path, clock, spawned)
    assert sup.state.status == "stopped"
    assert await sup.ensure_running()
    assert sup.state.status == "running" and len(spawned) == 1
    # Crash 1 -> restart after 1 s.
    spawned[0].exit(3)
    await _settle()
    assert clock.sleeps[-1] == BACKOFF_S[0] == 1.0
    assert len(spawned) == 2 and sup.state.status == "running"
    # Crash 2 -> restart after 4 s.
    clock.now += 30
    spawned[1].exit(3)
    await _settle()
    assert clock.sleeps[-1] == BACKOFF_S[1] == 4.0
    assert len(spawned) == 3
    # Crash 3 within 5 minutes -> crashed, no restart.
    clock.now += 30
    spawned[2].exit(3)
    await _settle()
    assert sup.state.status == "crashed"
    assert len(spawned) == 3
    assert not await sup.ensure_running()  # a crash loop needs a manual launch
    assert (Path(sup.state.crash_report) / "exit.json").is_file()
    assert await sup.ensure_running(manual=True)
    assert sup.state.status == "running" and len(spawned) == 4


async def test_third_backoff_is_15s_when_crashes_are_spread(tmp_path: Path) -> None:
    clock, spawned = Clock(), []
    sup = _supervisor(tmp_path, clock, spawned)
    await sup.ensure_running()
    for i in range(2):
        clock.now += 200
        spawned[i].exit(1)
        await _settle()
    clock.now += 200  # the first crash has left the 5-minute window
    spawned[2].exit(1)
    await _settle()
    assert clock.sleeps[-1] == BACKOFF_S[2] == 15.0
    assert sup.state.status == "running"


async def test_hung_bridge_kills_by_own_pid_and_restarts(tmp_path: Path) -> None:
    clock, spawned = Clock(), []
    sup = _supervisor(tmp_path, clock, spawned)
    await sup.ensure_running()
    await sup.on_hung()
    await _settle()
    assert spawned[0].killed
    assert len(spawned) == 2


async def test_stop_is_not_a_crash(tmp_path: Path) -> None:
    clock, spawned = Clock(), []
    asked: list[tuple[str, int]] = []

    async def request_quit(reason: str, deadline: int) -> bool:
        asked.append((reason, deadline))
        spawned[-1].exit(0)
        return True

    sup = _supervisor(tmp_path, clock, spawned, request_quit=request_quit)
    await sup.ensure_running()
    await sup.stop("app_quit")
    await _settle()
    assert asked == [("app_quit", 3000)]
    assert sup.state.status == "stopped" and len(spawned) == 1
    assert not sup.tokens.check(spawned[0].env["DODAIOS_VERSE_TOKEN"])  # type: ignore[attr-defined]


async def test_token_only_in_env_and_valid_only_while_alive(tmp_path: Path, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    clock, spawned = Clock(), []
    sup = _supervisor(tmp_path, clock, spawned)
    await sup.ensure_running()
    proc = spawned[0]
    token = proc.env["DODAIOS_VERSE_TOKEN"]  # type: ignore[attr-defined]
    assert len(token) == 43
    assert proc.env["DODAIOS_VERSE_BRIDGE"].startswith("ws://127.0.0.1:")  # type: ignore[attr-defined]
    assert all(token not in arg for arg in proc.argv)  # type: ignore[attr-defined]
    assert sup.tokens.check(token)
    proc.exit(1)
    await _settle()
    assert not sup.tokens.check(token)
    assert token not in caplog.text


CHILD = textwrap.dedent(
    """
    import os, sys, time
    sys.stdout.write("ARGV=" + repr(sys.argv) + "\\n")
    sys.stdout.write("HAS_TOKEN=" + str(bool(os.environ.get("DODAIOS_VERSE_TOKEN"))) + "\\n")
    sys.stdout.flush()
    time.sleep(60)
    """
)

APP = textwrap.dedent(
    """
    import asyncio, sys
    from pathlib import Path
    sys.path.insert(0, {root!r})
    from dodaios.verse_host.supervisor import spawn_contained

    async def main():
        env = dict(__import__("os").environ, DODAIOS_VERSE_TOKEN="T" * 43)
        p = await spawn_contained([sys.executable, {child!r}], env, Path({cwd!r}))
        print(p.pid, flush=True)
        await asyncio.sleep(60)

    asyncio.run(main())
    """
)


@pytest.mark.skipif(sys.platform not in ("win32", "linux"), reason="containment is Windows/Linux")
def test_killing_the_app_ends_verse_within_2s(tmp_path: Path) -> None:
    root = str(Path(__file__).resolve().parents[3])
    child = tmp_path / "dummy_verse.py"
    child.write_text(CHILD)
    app = tmp_path / "app.py"
    app.write_text(APP.format(root=root, child=str(child), cwd=str(tmp_path)))
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, str(app)], stdout=subprocess.PIPE, text=True
    )
    try:
        line = proc.stdout.readline().strip()  # type: ignore[union-attr]
        verse_pid = int(line)
        assert psutil.pid_exists(verse_pid)
        verse = psutil.Process(verse_pid)
        cmdline = " ".join(verse.cmdline())
        assert "T" * 43 not in cmdline  # A17.5: never on the command line
        started = time.perf_counter()
        proc.kill()  # the app process dies hard, by its own PID
        proc.wait(5)
        try:
            verse.wait(2.0)
        except psutil.TimeoutExpired:
            verse.kill()
            pytest.fail("dummy Verse outlived the app by more than 2 s")
        assert time.perf_counter() - started <= 2.0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_spawn_contained_keeps_linux_preexec_off_macos(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """macOS has no prctl. The Linux preexec_fn raises and aborts the spawn."""
    seen: dict[str, object] = {}

    class _Popen:
        def __init__(self, argv: list[str], **kwargs: object) -> None:
            seen["argv"] = argv
            seen.update(kwargs)
            self.pid = 4242

        def poll(self) -> None:
            return None

    monkeypatch.setattr(supervisor_mod.subprocess, "Popen", _Popen)
    monkeypatch.setattr(supervisor_mod.sys, "platform", "darwin")
    proc = supervisor_mod._spawn_contained_sync(["verse"], {}, tmp_path)
    assert proc.pid == 4242
    assert "preexec_fn" not in seen

    seen.clear()
    monkeypatch.setattr(supervisor_mod.sys, "platform", "linux")
    supervisor_mod._spawn_contained_sync(["verse"], {}, tmp_path)
    assert seen.get("preexec_fn") is supervisor_mod._linux_preexec


async def test_real_spawn_keeps_token_off_the_command_line(tmp_path: Path) -> None:
    child = tmp_path / "dummy_verse.py"
    child.write_text(CHILD.replace("time.sleep(60)", "time.sleep(0.2)"))
    token = mint_token()
    env = dict(__import__("os").environ, DODAIOS_VERSE_TOKEN=token)
    p = await spawn_contained([sys.executable, str(child)], env, tmp_path)
    try:
        cmd = " ".join(psutil.Process(p.pid).cmdline())
        assert token not in cmd
    finally:
        p.kill()
        await p.wait()


async def test_exit_after_bye_is_a_stop(tmp_path: Path) -> None:
    clock, spawned = Clock(), []
    sup = _supervisor(tmp_path, clock, spawned)
    await sup.ensure_running()
    sup.expect_exit()  # lifecycle.bye arrived
    clock.now += 60
    spawned[0].exit(0)
    await _settle()
    assert sup.state.status == "stopped"
    assert len(spawned) == 1 and sup.state.crashes == []
    # The next launch clears the expectation: a later exit is a crash again.
    assert await sup.ensure_running(manual=True)
    spawned[1].exit(3)
    await _settle()
    assert len(sup.state.crashes) == 1 and len(spawned) == 3


async def test_expected_exit_window_expires(tmp_path: Path) -> None:
    clock, spawned = Clock(), []
    sup = _supervisor(tmp_path, clock, spawned)
    await sup.ensure_running()
    sup.expect_exit(10.0)
    clock.now += 11  # Verse did not quit in time; a later exit is a crash
    spawned[0].exit(3)
    await _settle()
    assert len(sup.state.crashes) == 1 and len(spawned) == 2


async def test_dormant_gpu_yield_exit_is_not_a_crash(tmp_path: Path) -> None:
    from tests.unit.verse_host._support import close, connect, make_host

    clock, spawned = Clock(), []
    sup = _supervisor(tmp_path, clock, spawned)
    host, _ = make_host(tmp_path, supervisor=sup)
    await sup.ensure_running()
    t, task = await connect(host)
    t.push({"type": "lifecycle.state", "ts": 1.0, "data": {"state": "dormant", "vram_mb": 900}})
    for _ in range(100):
        if host.state == "dormant":
            break
        await asyncio.sleep(0.01)
    assert host.state == "dormant"
    assert await host.gpu_pressure(True, "local_model")
    await t.wait_for(lambda f: f["type"] == "gpu.yield")
    spawned[0].exit(0)  # a Dormant Verse quits at once on gpu.yield (contract 12)
    await _settle()
    assert sup.state.status == "stopped"
    assert len(spawned) == 1, "a GPU yield must not relaunch Verse"
    assert sup.state.crashes == [] and sup.state.crash_report is None
    await close(t, task)
