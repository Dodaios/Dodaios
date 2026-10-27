"""A stopped CLI probe takes what it spawned with it (#534).

``wrangler --version`` re-launches itself as a child ``node``. Killing only the
probe left that child running past ``jarvis serve``'s exit, holding the pipes,
so the wait timed out and the transport was collected after the loop closed.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from dodaios.clis import prober as prober_mod
from dodaios.clis.prober import CliStatusProber
from dodaios.clis.spec import AuthConfig, CliSpec, InstallMethods, RiskConfig


class _Proc:
    def __init__(self, pid: Any) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self.killed = False

    def kill(self) -> None:
        self.killed = True


def test_a_posix_stop_signals_the_whole_group(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(prober_mod, "_OWN_GROUP", True)
    monkeypatch.setattr(
        prober_mod.os, "killpg", lambda pid, sig: sent.append((pid, sig)), raising=False
    )
    proc = _Proc(4321)
    prober_mod._kill_probe(proc)  # type: ignore[arg-type]
    assert sent == [(4321, 9)]
    assert proc.killed is False


def test_without_a_group_only_the_child_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prober_mod, "_OWN_GROUP", False)
    proc = _Proc(4321)
    prober_mod._kill_probe(proc)  # type: ignore[arg-type]
    assert proc.killed is True


def test_a_group_that_is_not_ours_falls_back_to_the_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _denied(_pid: int, _sig: int) -> None:
        raise PermissionError

    monkeypatch.setattr(prober_mod, "_OWN_GROUP", True)
    monkeypatch.setattr(prober_mod.os, "killpg", _denied, raising=False)
    proc = _Proc(4321)
    prober_mod._kill_probe(proc)  # type: ignore[arg-type]
    assert proc.killed is True


def _spec(binary: str) -> CliSpec:
    return CliSpec(
        name="slowcli",
        display_name="SLOWCLI",
        description="d",
        homepage="",
        binary_name=binary,
        check_command=(binary, "--version"),
        version_parse_regex=r"(\d+)",
        install=InstallMethods(manual_url="https://x"),
        auth=AuthConfig(type="none"),
        risk=RiskConfig(default_tier="monitor"),
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
@pytest.mark.asyncio
async def test_a_timed_out_probe_leaves_no_grandchild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "grandchild.pid"
    script = tmp_path / "slowcli"
    # Like wrangler: the CLI starts a child that keeps the pipes, then waits.
    script.write_text(
        f"#!/bin/sh\nsleep 60 &\necho $! > '{pid_file}'\nwait\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setattr(prober_mod.shutil, "which", lambda _name: str(script))
    monkeypatch.setattr(prober_mod, "CHECK_TIMEOUT_S", 1.0)

    installed, version, _path = await CliStatusProber()._probe_binary(_spec("slowcli"))

    assert installed is True and version is None
    grandchild = int(pid_file.read_text(encoding="utf-8").strip())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break  # killed with its group, and reaped by init
        await asyncio.sleep(0.05)
    else:
        os.kill(grandchild, 9)
        pytest.fail("the probe's grandchild outlived the probe")
