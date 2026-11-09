"""duel.py of scripts/unreal: the hangar duel run of the integration.

Pure logic: the engine is a fake folder and the runner is a stand-in, so
nothing here starts Unreal.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from scripts.unreal import _common as common
from scripts.unreal import duel


@pytest.fixture
def engine(tmp_path, monkeypatch):
    root = tmp_path / "UE_5.7"
    common.editor_cmd(root).parent.mkdir(parents=True, exist_ok=True)
    common.editor_cmd(root).write_text("", encoding="utf-8")
    monkeypatch.setenv(common.ENGINE_ENV, str(root))
    return root


def _command(**overrides) -> list[str]:
    options = dict(
        tier="hard",
        seconds=120.0,
        bots=False,
        autoplay=True,
        render=False,
        stats=Path("s.json"),
        log_path=Path("l.log"),
    )
    options.update(overrides)
    return duel.command_for(Path("E"), Path("P.uproject"), **options)


def test_headless_command_boots_the_hangar_and_starts_the_duel():
    command = _command()
    assert command[2] == duel.HANGAR_MAP and "-game" in command
    assert "-nullrhi" in command and "-fps=60" in command
    assert "-VerseDuel=hard" in command and "-VerseDuelSeconds=120" in command
    assert "-VerseDuelAutoplay" in command and "-VerseDuelBots" not in command


def test_rendered_bot_run_opens_off_screen_without_nullrhi():
    command = _command(render=True, bots=True, autoplay=False, tier="elite")
    assert "-nullrhi" not in command and "-d3d12" in command
    assert "-WinX=-32000" in command
    assert "-VerseDuelBots" in command and "-VerseDuel=elite" in command


def test_verdict_needs_shots_kills_and_no_errors():
    clean = {"errors": 0, "players": [{"shots": 30, "kills": 2}, {"shots": 10, "kills": 1}]}
    assert duel.verdict(clean) == []
    assert duel.verdict({"errors": 0, "players": []}) == ["nobody fired", "no kill"]
    assert duel.verdict({**clean, "errors": 3}) == ["3 error log lines"]


def test_run_reads_the_stats_the_game_wrote(engine, tmp_path, monkeypatch):
    project = tmp_path / "unreal" / "Verse" / "Verse.uproject"
    project.parent.mkdir(parents=True)
    project.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(common, "current_branch", lambda worktree: "claude/x")
    seen = []

    def fake_runner(command, *, label, cwd):
        seen.append(label)
        flag = "-VerseDuelStats="
        stats = next(part[len(flag):] for part in command if part.startswith(flag))
        Path(stats).write_text(
            json.dumps(
                {
                    "tier": "hard",
                    "errors": 0,
                    "players": [{"id": 1, "shots": 5, "kills": 1, "deaths": 0, "hits": 3}],
                }
            ),
            encoding="utf-8",
        )
        return 0

    args = argparse.Namespace(
        tier="hard", seconds=5.0, bots=False, autoplay=True, render=False, print_play_command=False
    )
    assert duel.run(args, worktree=tmp_path, runner=fake_runner) == 0
    assert seen and seen[0].startswith("duel player_hard_null")


def test_play_command_starts_the_windowed_game(engine):
    command = duel.play_command(engine, Path("P.uproject"))
    assert command[0].endswith("UnrealEditor.exe") and "-game" in command
