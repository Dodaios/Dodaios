"""PATH repair at the persistent coding-CLI turn host boundary."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from dodaios.agent_chat import turn_host
from dodaios.core import path_augment


async def test_codex_spawn_repairs_an_inherited_oversized_path_before_create_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A surviving turn host must repair its own PATH before the first CLI spawn."""
    host = turn_host.TurnHost("test-token", tmp_path / "spool")
    existing = tmp_path / "existing"
    cli_dir = tmp_path / "cli"
    existing.mkdir()
    cli_dir.mkdir()
    for name in ("node.exe", "npm.cmd", "codex.cmd"):
        (cli_dir / name).touch()

    budget = len(os.pathsep.join((str(existing), str(cli_dir))))
    bloated = os.pathsep.join([str(existing)] * 40)
    assert len(bloated) > budget
    monkeypatch.setenv("PATH", bloated)
    monkeypatch.setattr(path_augment, "candidate_dirs", lambda: [str(cli_dir)])
    monkeypatch.setattr(path_augment, "_path_budget", lambda: budget)
    monkeypatch.setattr(path_augment, "_settled_overflow", None)

    observed_paths: list[str] = []

    async def stop_at_create_process(*_argv: str, **_kwargs: Any) -> None:
        current = os.environ["PATH"]
        observed_paths.append(current)
        entries = current.split(os.pathsep)
        assert entries == [str(existing), str(cli_dir)]
        assert len(current) <= budget
        assert all((cli_dir / name).is_file() for name in ("node.exe", "npm.cmd", "codex.cmd"))
        raise OSError("test stops at CreateProcess")

    monkeypatch.setattr(turn_host.asyncio, "create_subprocess_exec", stop_at_create_process)
    frame = {
        "argv": [str(cli_dir / "codex.cmd"), "exec", "--json", "-"],
        "cwd": str(tmp_path),
        "env": {"PATH": bloated},
        "meta": {"runner": "codex-cli"},
    }

    with pytest.raises(OSError, match="test stops at CreateProcess"):
        await host._spawn(frame)
    repaired = os.environ["PATH"]
    with pytest.raises(OSError, match="test stops at CreateProcess"):
        await host._spawn(frame)

    assert observed_paths == [repaired, repaired]
    assert path_augment.ensure_cli_paths() == []
    assert os.environ["PATH"] == repaired
