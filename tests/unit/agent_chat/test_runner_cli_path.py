"""Windows PATH repair at the direct Codex CLI spawn boundary."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from dodaios.agent_chat import runner_cli
from dodaios.core import path_augment


@pytest.mark.skipif(os.name != "nt", reason="Windows CreateProcess PATH limit")
async def test_direct_codex_spawn_repairs_parent_and_child_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A normal text chat must repair both PATH copies before CreateProcess."""
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

    observed: list[tuple[str, str]] = []

    async def capture_spawn(*_argv: str, **kwargs: Any) -> object:
        parent_path = os.environ["PATH"]
        child_path = kwargs["env"]["PATH"]
        observed.append((parent_path, child_path))
        assert parent_path == child_path == os.pathsep.join((str(existing), str(cli_dir)))
        assert len(parent_path) <= budget
        assert all((cli_dir / name).is_file() for name in ("node.exe", "npm.cmd", "codex.cmd"))
        return object()

    monkeypatch.setattr(runner_cli.asyncio, "create_subprocess_exec", capture_spawn)
    for _ in range(2):
        plan = runner_cli.CliPlan(
            argv=[str(cli_dir / "codex.cmd"), "exec", "--json", "-"],
            env={"PATH": bloated},
            stdin_text="test",
            shape="codex",
            vendor_session=None,
        )
        result = await runner_cli._spawn_child(plan, tmp_path, None, "codex-cli")
        assert not isinstance(result, runner_cli._Outcome)

    assert len(observed) == 2
    assert observed[0] == observed[1]
    assert path_augment.ensure_cli_paths() == []
