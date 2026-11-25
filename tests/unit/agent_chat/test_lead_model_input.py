"""What the lead's CLI is handed: the message bytes are pinned, and one function says it all.

The replay benchmark (``docs/self-improvement.md``, "Lead turns on record")
gives the model what it was given then, with one thing changed. That only
works while the message the lead gets is built in one known way, so the
bytes of today's message are pinned here, case by case.

A digest that no longer matches means the lead's message changed. When a line
changed on purpose, the composition check next to it still passes; put the
new digest in ``_PINNED`` (the failure message prints it).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

#: (surface, identity, text, continuation, output language) -> sha256 of the message.
_CASES: dict[str, tuple[str, bool, str, bool, str]] = {
    "fresh": ("jarvis", True, "Find me a train to Hamburg tomorrow morning", False, ""),
    "continuation": ("jarvis", True, "Find me a train to Hamburg tomorrow morning", True, ""),
    "secret": ("jarvis", True, "Here is my GitHub token for the release script", False, ""),
    "language": ("jarvis", True, "What is on today?", False, "de"),
    "secret_lang_continuation": (
        "jarvis",
        True,
        "Use this API key for the weather tool",
        True,
        "fr",
    ),
    "slash": ("jarvis", True, "/project list", False, ""),
    "slash_language": ("jarvis", True, "/project list", False, "de"),
    "goal_language": ("jarvis", True, "/goal ship the release notes", False, "de"),
    "indented_goal_language": ("jarvis", True, "  /goal ship it", False, "de"),
    "coding_thread_language": ("agent", False, "Fix the failing test", False, "de"),
}

_PINNED: dict[str, str] = {
    "fresh": "01bb2a2ba3178b5b0a10b0533e1b5bd4196e29753ce13227d0871d6874d6ea89",
    "continuation": "9921902baea9b013119131c2d4f7a48c625747915255a213948162882a427d3b",
    "secret": "055b10f6df828bd1d461040858459505004b0eb43786ff2d3af451b8257ffdce",
    "language": "0773291a08531ad0adfb1a505c1b2a44386b98e8776c88761a6505a5c5ab0458",
    "secret_lang_continuation": "e87086032f1b31eba63a7d7d73e109d58ff30fa4cb49b5f446c13598495288ae",
    "slash": "b280fd797dbfb6c3ae2aa87f86c9f2369375e7aba8821f63c379e516728b5639",
    "slash_language": "9ab2e20715c3f3dc5280b3aff468dcebf69d21897948dcf501fcc609b2588de9",
    "goal_language": "9df4053b191b38880e6364380d9ccaa73f291b21f291cdbb5db12e2405edd2c5",
    "indented_goal_language": "522b4c3860f74d098d682ee0b70537a40d2886c63a82f84fcbac612c6abff5fb",
    "coding_thread_language": "3900008b77595af632e7f72e5033a9b09e624efbc1d3d994fd5708f6cab0a8bf",
}

_WISHES = "\nTheir brief wishes: keep briefs under ten lines."


async def _message_today(monkeypatch: pytest.MonkeyPatch, case: str) -> str:
    """The message ``run_cli_turn`` hands the CLI runner for ``case``."""
    from dodaios.agent_chat import dodaios_harness, runner_cli
    from dodaios.agent_chat.runner_api import TurnHandle

    surface, identity, text, continuation, language = _CASES[case]
    seen: dict[str, Any] = {}

    async def no_briefing(_session: Any) -> None:
        return None

    async def build_identity(**kwargs: Any) -> Any:
        return dodaios_harness.Identity(kwargs["session_id"], "id", "id")

    async def once(handle: Any, prompt: str, runner: str, resume: Any, **kwargs: Any) -> Any:
        seen["prompt"] = prompt
        return runner_cli._Outcome("done", None, {}, None, resume)  # noqa: SLF001

    async def emit(_event: dict[str, Any]) -> None:
        return None

    async def deny(*_args: Any) -> str:
        return "deny"

    monkeypatch.setattr(runner_cli, "_surface_identity", no_briefing)
    monkeypatch.setattr(dodaios_harness, "build_identity", build_identity)
    monkeypatch.setattr(runner_cli, "_run_cli_once", once)
    monkeypatch.setattr("dodaios.core.brief_wishes.wishes_line", lambda: _WISHES)
    handle = TurnHandle(
        session=SimpleNamespace(
            surface=surface,
            session_id="lead-1",
            vendor_session="vendor-1",
            account_id="",
        ),
        turn_id="t1",
        emit=emit,
        request_approval=deny,
        cancel=asyncio.Event(),
        surface=surface,
        stance="ask",
        continuation=continuation,
        output_language=language,
    )
    await runner_cli.run_cli_turn(handle, text, "claude-cli", identity=identity)
    return str(seen["prompt"])


def _composed(case: str) -> str:
    """The same message spelled out from the line constants: the order and the conditions."""
    from dodaios.agent_chat import dodaios_harness as h
    from dodaios.agent_chat.runner_api import reply_language_line

    surface, identity, text, continuation, language = _CASES[case]
    out = text
    if identity and surface == "jarvis" and not text.lstrip().startswith("/"):
        if case.startswith("secret"):
            out += h.SECRET_FIELD_LINE
        out += h.EFFORT_LINE
        if not continuation:
            out += h.FIRST_LINE
        out += h.REPLY_SHAPE_LINE + h.BRIEF_LINE + _WISHES + h.QUESTION_CARD_LINE
    if language and not text.startswith("/goal"):
        out += reply_language_line(surface, language)
    return out


@pytest.mark.parametrize("case", sorted(_CASES))
async def test_the_message_bytes_are_pinned(monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    message = await _message_today(monkeypatch, case)
    assert message == _composed(case)
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
    assert digest == _PINNED[case], f"the lead's message for {case!r} changed; now {digest}"


def test_the_lead_message_is_one_pure_function() -> None:
    """The lines beside the person's message come from ``message_lines`` alone."""
    from dodaios.agent_chat import dodaios_harness as h

    lines = h.message_lines("Find me a train", continuation=False, brief="\nB")
    assert lines == h.EFFORT_LINE + h.FIRST_LINE + h.REPLY_SHAPE_LINE + "\nB" + h.QUESTION_CARD_LINE
    assert h.lead_message("Find me a train", continuation=False, brief=lambda: "\nB") == (
        "Find me a train" + lines
    )

    # A slash command goes out alone: the wishes are not even read.
    def unread() -> str:
        raise AssertionError("read for a slash command")

    assert h.lead_message("/project list", continuation=False, brief=unread) == "/project list"


def _identity(tmp_path: Path) -> Any:
    from dodaios.agent_chat import dodaios_harness

    path = tmp_path / "identity.md"
    path.write_text("FULL IDENTITY", encoding="utf-8")
    return dodaios_harness.Identity(
        "lead-1", "FULL IDENTITY", "SHORT", path=path, catchup="CATCH-UP\n\n"
    )


def _claude_message(plan: Any) -> str:
    return str(json.loads(plan.stdin_text.splitlines()[0])["message"]["content"])


def _argv_message(plan: Any) -> str:
    return str(plan.argv[plan.argv.index("-p") + 1])


@pytest.mark.parametrize("resume", [None, "vendor-1"])
@pytest.mark.parametrize(
    ("runner", "prefix", "message_of"),
    [
        ("claude-cli", "claude_argv_prefix", _claude_message),
        ("codex-cli", "codex_argv_prefix", lambda plan: plan.stdin_text),
        ("grok-cli", "grok_argv_prefix", _argv_message),
    ],
)
def test_lead_model_input_is_what_the_planner_hands_the_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: str,
    prefix: str,
    message_of: Any,
    resume: str | None,
) -> None:
    from dodaios.agent_chat import dodaios_harness, runner_cli

    monkeypatch.setattr(runner_cli, prefix, lambda: [runner.removesuffix("-cli")])
    monkeypatch.setattr(dodaios_harness, "mcp_config_json", lambda *_a: '{"mcpServers": {}}')
    identity = _identity(tmp_path)
    plan = runner_cli._PLANNERS[runner](  # noqa: SLF001
        prompt="hello",
        cwd=tmp_path,
        model="m",
        effort="high",
        permission_mode="bypassPermissions",
        resume=resume,
        identity=identity,
    )
    got = runner_cli.lead_model_input(
        runner=runner,
        model="m",
        effort="high",
        prompt="hello",
        identity=identity,
        resume=resume,
        tools="--mcp-config" in plan.argv,
    )
    assert (got.cli, got.model, got.effort) == (runner, "m", "high")
    assert got.message == message_of(plan)
    if resume:
        assert got.message == "CATCH-UP\n\nhello"
    if runner == "claude-cli":
        # The identity is the system-prompt file, read as the CLI reads it.
        flag = plan.argv.index("--append-system-prompt-file")
        assert got.system == Path(plan.argv[flag + 1]).read_text(encoding="utf-8")
        assert got.system == "FULL IDENTITY"
        if not resume:
            assert got.message == "hello"
    else:
        # Other seats carry the identity in the message, on a fresh conversation.
        assert got.system == ""
        if not resume:
            cut = "SHORT" if runner == "grok-cli" else "FULL IDENTITY"
            assert got.message == f"<jarvis_identity>\n{cut}\n</jarvis_identity>\n\nhello"


def test_without_the_tool_server_claude_code_gets_no_system_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dodaios.agent_chat import dodaios_harness, runner_cli

    monkeypatch.setattr(runner_cli, "claude_argv_prefix", lambda: ["claude"])
    monkeypatch.setattr(dodaios_harness, "mcp_config_json", lambda *_a: None)
    identity = _identity(tmp_path)
    plan = runner_cli.plan_claude(
        prompt="hello",
        cwd=tmp_path,
        model="m",
        effort="high",
        permission_mode="bypassPermissions",
        resume=None,
        identity=identity,
    )
    assert "--append-system-prompt-file" not in plan.argv
    got = runner_cli.lead_model_input(
        runner="claude-cli",
        model="m",
        effort="high",
        prompt="hello",
        identity=identity,
        resume=None,
        tools="--mcp-config" in plan.argv,
    )
    assert (got.system, got.message) == ("", "hello")


def test_lead_model_input_refuses_a_society_seat(tmp_path: Path) -> None:
    from dodaios.agent_chat import dodaios_harness, runner_cli

    seat = dodaios_harness.Identity("society:scout", "BRIEFING", "BRIEFING")
    with pytest.raises(ValueError, match="lead"):
        runner_cli.lead_model_input(
            runner="codex-cli",
            model="m",
            effort="",
            prompt="hello",
            identity=seat,
            resume=None,
        )
