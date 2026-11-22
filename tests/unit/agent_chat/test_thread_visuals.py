"""A coding thread draws pictures, and every coding agent is told so."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from dodaios.agent_chat import runner_cli as rc
from dodaios.agent_chat import thread_visuals
from dodaios.agent_chat.runner_api import TurnHandle
from dodaios.agent_chat.store import AgentChatSession
from dodaios.agent_chat.thread_visuals import VISUALS_GUIDE, tell_claude_code

FRONTEND = Path(__file__).resolve().parents[3] / "dodaios/ui/web/frontend/src"


def _session(tmp_path: Path, surface: str) -> AgentChatSession:
    return AgentChatSession(
        session_id="s1",
        title="",
        provider="claude-api",
        model="",
        effort="",
        cwd=str(tmp_path),
        permission_mode="",
        vendor_session=None,
        created_ms=0,
        updated_ms=0,
        message_count=0,
        preview="",
        surface=surface,
    )


def test_the_guide_survives_a_windows_command_line() -> None:
    # Behind a .cmd shim the line is read by cmd.exe: a line break ends it,
    # a percent sign or a double quote changes it.
    assert "\n" not in VISUALS_GUIDE and "\r" not in VISUALS_GUIDE
    assert '"' not in VISUALS_GUIDE and "%" not in VISUALS_GUIDE
    assert len(VISUALS_GUIDE) < 1500


def test_the_guide_names_what_the_thread_draws() -> None:
    for fence in thread_visuals.VISUAL_FENCES:
        assert f"`{fence}`" in VISUALS_GUIDE
    for token in thread_visuals.VISUAL_TOKENS:
        assert f"`var(--{token})`" in VISUALS_GUIDE
    # A saved picture or page is shown by image syntax, and where to save it.
    assert "`![short title](path)`" in VISUALS_GUIDE
    assert "temp folder" in VISUALS_GUIDE
    # Scripts stay off until the person asks.
    assert "run only after the person clicks" in VISUALS_GUIDE


def test_the_frontend_draws_the_same_fences_and_colours() -> None:
    fence_source = (FRONTEND / "lib/visualFence.ts").read_text(encoding="utf-8")
    declared = re.search(r"export type VisualFenceLanguage = ([^;]+);", fence_source)
    assert declared is not None
    assert set(re.findall(r'"(\w+)"', declared[1])) == set(thread_visuals.VISUAL_FENCES)
    frame_source = (FRONTEND / "components/outputs/RenderedFence.tsx").read_text(encoding="utf-8")
    tokens = re.search(r"export const VISUAL_TOKENS = \[([^\]]+)\] as const;", frame_source)
    assert tokens is not None
    assert tuple(re.findall(r'"(\w+)"', tokens[1])) == thread_visuals.VISUAL_TOKENS


def test_a_claude_code_thread_reads_the_guide_in_its_system_prompt(tmp_path: Path) -> None:
    thread = _session(tmp_path, "agent")
    # Beside the tools' preamble: the flag counts once, so the guide joins it.
    argv = ["claude", "--append-system-prompt", "Dodaios tools come from MCP."]
    tell_claude_code(argv, thread)
    assert argv[:2] == ["claude", "--append-system-prompt"]
    assert argv[2:] == [f"Dodaios tools come from MCP. {VISUALS_GUIDE}"]
    tell_claude_code(argv, thread)
    assert argv[2].count(VISUALS_GUIDE) == 1
    # Without the tool server the guide stands alone.
    bare = ["claude", "--print"]
    tell_claude_code(bare, thread)
    assert bare == ["claude", "--print", "--append-system-prompt", VISUALS_GUIDE]


@pytest.mark.parametrize("surface", ["jarvis", "society"])
def test_other_surfaces_keep_their_own_prompt(tmp_path: Path, surface: str) -> None:
    argv = ["claude", "--append-system-prompt", "x"]
    tell_claude_code(argv, _session(tmp_path, surface))
    assert argv == ["claude", "--append-system-prompt", "x"]


def test_an_identity_file_is_left_alone(tmp_path: Path) -> None:
    identity = str(tmp_path / "identity.md")
    argv = ["claude", "--append-system-prompt-file", identity]
    tell_claude_code(argv, _session(tmp_path, "agent"))
    assert argv == ["claude", "--append-system-prompt-file", identity]


def _argv_of_a_claude_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, surface: str, plain: bool = False
) -> list[str]:
    """Run one turn against a Claude Code stand-in that writes down its command line."""
    out = tmp_path / "argv.json"
    body = f"""
import json, sys
open({str(out)!r}, "w", encoding="utf-8").write(json.dumps(sys.argv[1:]))
def send(obj):
    sys.stdout.write(json.dumps(obj) + chr(10)); sys.stdout.flush()
send({{"type": "system", "subtype": "init", "session_id": "v1"}})
send({{"type": "result", "subtype": "success", "result": "ok", "session_id": "v1"}})
"""

    def planner(**_: Any) -> rc.CliPlan:
        return rc.CliPlan(
            [sys.executable, "-c", body, "--append-system-prompt", "TOOLS"],
            dict(os.environ),
            rc.claude_stream_input("hi"),
            "claude",
            "v1",
            keep_stdin=True,
            control_init=rc.claude_control_init(),
        )

    monkeypatch.setitem(rc._PLANNERS, "claude-cli", planner)

    async def emit(_event: dict[str, Any]) -> None:
        return None

    async def ask(*_: object) -> str:
        return "deny"

    handle = TurnHandle(
        session=_session(tmp_path, surface),
        turn_id="t1",
        emit=emit,
        request_approval=ask,
        cancel=asyncio.Event(),
        tools_disabled=plain,
    )
    asyncio.run(rc.run_cli_turn(handle, "hi", "claude-cli"))
    return list(json.loads(out.read_text(encoding="utf-8")))


def test_a_real_thread_turn_starts_claude_code_with_the_guide(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv = _argv_of_a_claude_turn(monkeypatch, tmp_path, surface="agent")
    assert argv[argv.index("--append-system-prompt") + 1] == f"TOOLS {VISUALS_GUIDE}"


def test_a_turn_without_tools_is_not_told_to_save_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv = _argv_of_a_claude_turn(monkeypatch, tmp_path, surface="agent", plain=True)
    assert "--append-system-prompt" not in argv
    assert not any(VISUALS_GUIDE in part for part in argv)
