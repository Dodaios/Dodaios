"""The lead's turn contract is the same on every seat.

The matrix is seat (brain, claude-cli, codex-cli) x behaviour (``/slug`` skill,
trigger-phrase skill, recalled memory, unbacked claim caught, reply language,
offer instead of action). Every case drives the real chat service on a lead
conversation; only the model at the end of each seat is scripted.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from dodaios.agent_chat import dodaios_harness, runner_brain
from dodaios.agent_chat import service as service_mod
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.brain.manager import BrainManager
from dodaios.skills.registry import SkillRegistry
from dodaios.skills.runner import SkillRunner
from dodaios.skills.skill_context import SkillContext, set_skill_context
from tests.fakes.fake_brain_manager import FakeBrainManager

SEATS = ["brain", "claude-cli", "codex-cli"]
RECALL = "[Memory] The person's dog is called Rex."


@dataclass
class Seen:
    """What reached the seat, in a seat-independent shape."""

    prompts: list[str] = field(default_factory=list)
    skills: list[tuple[str, str]] = field(default_factory=list)
    visible: list[str] = field(default_factory=list)  # prompt + identity, per run
    languages: list[str] = field(default_factory=list)


class _LeadBrain(FakeBrainManager):
    """The brain seat: the real runner, a scripted model."""

    def __init__(self, replies: list[str], seen: Seen) -> None:
        super().__init__()
        self.replies = list(replies)
        self.seen = seen

    async def generate(self, text: str, **kwargs: Any) -> str:
        self.seen.prompts.append(text)
        self.seen.languages.append(kwargs.get("force_output_language") or "")
        # The manager recalls the vault itself for every turn (BrainManager.generate).
        recalled = await BrainManager._vault_recall(text)  # noqa: SLF001
        self.seen.visible.append(f"{text}\n{recalled}")
        self.reply = self.replies.pop(0)
        self.chunks = (self.reply,)
        return await super().generate(text, **kwargs)


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    root = tmp_path / "skills"
    skills = (("note-skill", None), ("morning-routine", "(morgenroutine|morning routine)"))
    for name, pattern in skills:
        d = root / name
        d.mkdir(parents=True)
        trigger = (
            f'triggers:\n  - type: voice\n    pattern: "{pattern}"\n    language: [de, en]\n'
            if pattern
            else ""
        )
        (d / "SKILL.md").write_text(
            f'---\nschema_version: "1"\nname: {name}\ndescription: Contract test skill.\n'
            f"execution: inline\n{trigger}---\nDo the {name} thing: {{{{ content }}}}\n",
            encoding="utf-8",
        )
    registry = SkillRegistry(root=root)
    registry.reload_sync()
    set_skill_context(SkillContext(registry=registry, runner=SkillRunner(registry=registry)))

    monkeypatch.setattr("dodaios.memory.vault.runtime.turn_block", lambda _t: RECALL)
    monkeypatch.setattr(service_mod, "_claude_cli_installed", lambda: True)
    yield
    set_skill_context(None)


class _Identity:
    """What a CLI seat's identity text holds on a fresh or file-carried turn."""

    async def render_surface_prompt(self, *, user_text: str, **_: Any):
        return f"IDENTITY\n{RECALL}", ""


async def _run(
    seat: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str, replies: list[str]
) -> tuple[Seen, list[dict[str, Any]]]:
    svc = AgentChatService(AgentChatStore(":memory:"), assistant_name=lambda: "Testo")
    provider = "openai-codex" if seat == "codex-cli" else "claude-api"
    session = svc.create_session(
        provider=provider, model="m", effort="", cwd=str(tmp_path),
        permission_mode="ask", surface="jarvis",
    )
    svc.store.set_lead_session_id(session.session_id)
    seen = Seen()
    monkeypatch.setattr(service_mod, "resolve_runner", lambda *a, **k: seat)

    async def seat_for(provider: str):
        return None if seat == "brain" else (provider, seat)

    monkeypatch.setattr("dodaios.core.task_agent.subscription_seat_off_loop", seat_for)
    if seat == "brain":
        fake = _LeadBrain(replies, seen)
        monkeypatch.setattr(runner_brain, "brain_manager", lambda: fake)
        monkeypatch.setattr(runner_brain, "_is_lead", lambda _sid: True)
    else:
        if seat == "codex-cli":
            # A resumed vendor conversation: the identity is not repeated, so the
            # contract itself carries the recalled memory.
            svc.store.update_session(session.session_id, vendor_session="vendor-1")
        monkeypatch.setattr(dodaios_harness, "_brain", lambda: _Identity())
        script = list(replies)

        async def cli_turn(handle, prompt, runner, **_kwargs):
            seen.prompts.append(prompt)
            seen.languages.append(handle.output_language)
            visible = prompt
            if runner == "claude-cli" or not handle.session.vendor_session:
                visible += "\n" + await dodaios_harness.identity_prompt(
                    user_text=prompt, history=[], resume=None, session_id="s"
                )
            seen.visible.append(visible)
            await handle.emit(
                make_event("assistant_text", {"turn_id": handle.turn_id, "text": script.pop(0)})
            )
            await handle.emit(
                make_event("turn_finished", {"turn_id": handle.turn_id, "status": "done"})
            )
            return None

        monkeypatch.setattr(service_mod, "run_cli_turn", cli_turn)
    await svc.send(session.session_id, text)
    await asyncio.wait_for(svc._running[session.session_id].task, 10)
    if seat == "brain":
        seen.skills = [(n, c) for n, c, _s in fake.noted_skills]
    else:
        for prompt in seen.prompts[:1]:
            for name in ("note-skill", "morning-routine"):
                if f"Skill instructions for `{name}`" in prompt:
                    marker = f"Do the {name} thing: "
                    content = prompt.split(marker, 1)[1].splitlines()[0].strip()
                    seen.skills.append((name, content))
    return seen, svc.store.list_events(session.session_id)


def _claim_notices(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        e for e in events
        if e["kind"] == "notice" and e["payload"].get("kind") == "unbacked_claim"
    ]


@pytest.mark.parametrize("seat", SEATS)
async def test_a_slash_pick_runs_the_skill_on_every_seat(seat, tmp_path, monkeypatch):
    seen, _ = await _run(seat, tmp_path, monkeypatch, "/note-skill buy milk", ["Noted."])
    assert seen.skills == [("note-skill", "buy milk")]
    if seat != "brain":
        # A coding CLI would read the slash as one of its own commands.
        assert not seen.prompts[0].lstrip().startswith("/")


@pytest.mark.parametrize("seat", SEATS)
async def test_a_trigger_phrase_runs_the_skill_on_every_seat(seat, tmp_path, monkeypatch):
    seen, _ = await _run(
        seat, tmp_path, monkeypatch, "start the morning routine please", ["Started."]
    )
    assert [name for name, _ in seen.skills] == ["morning-routine"]


@pytest.mark.parametrize("seat", SEATS)
async def test_recalled_memory_reaches_every_seat(seat, tmp_path, monkeypatch):
    seen, _ = await _run(seat, tmp_path, monkeypatch, "What is my dog called?", ["Rex."])
    assert RECALL in seen.visible[0]


@pytest.mark.parametrize("seat", SEATS)
async def test_an_unbacked_claim_is_sent_back_once_on_every_seat(seat, tmp_path, monkeypatch):
    seen, events = await _run(
        seat, tmp_path, monkeypatch, "Tell Anna that dinner is at eight.",
        ["I sent the email to Anna.", "I did not send anything; no tool ran."],
    )
    assert len(seen.prompts) == 2
    assert "no successful tool call of that kind" in seen.prompts[1]
    assert not _claim_notices(events)
    assert [e["kind"] for e in events].count("turn_finished") == 1


@pytest.mark.parametrize("seat", SEATS)
async def test_a_claim_unproven_after_the_follow_up_gets_a_notice(seat, tmp_path, monkeypatch):
    seen, events = await _run(
        seat, tmp_path, monkeypatch, "Tell Anna that dinner is at eight.",
        ["I sent the email to Anna.", "I have sent the email to Anna."],
    )
    assert len(seen.prompts) == 2
    assert len(_claim_notices(events)) == 1


@pytest.mark.parametrize("seat", SEATS)
async def test_the_reply_language_is_resolved_and_enforced_on_every_seat(
    seat, tmp_path, monkeypatch
):
    seen, _ = await _run(
        seat, tmp_path, monkeypatch, "Bitte erstelle mir eine Notiz über den Einkauf heute.",  # i18n-allow  # noqa: E501
        [
            "Here is the finished note about your shopping list for today, "
            "and everything that you need is already on it.",
            "Hier ist die fertige Notiz über deinen Einkauf von heute, alles ist schon darauf.",  # i18n-allow  # noqa: E501
        ],
    )
    assert seen.languages[0] == "de"
    assert len(seen.prompts) == 2
    assert "German" in seen.prompts[1]


@pytest.mark.parametrize("seat", SEATS)
async def test_an_offer_instead_of_action_is_corrected_on_every_seat(seat, tmp_path, monkeypatch):
    seen, _ = await _run(
        seat, tmp_path, monkeypatch, "Please create a README file.",
        ["I can create that for you. Shall I start?", "The README file is ready."],
    )
    assert len(seen.prompts) == 2
    assert "offered to do the requested work" in seen.prompts[1]


async def test_a_conversation_that_is_not_the_lead_keeps_its_single_pass(tmp_path, monkeypatch):
    svc = AgentChatService(AgentChatStore(":memory:"), assistant_name=lambda: "Testo")
    session = svc.create_session(
        provider="claude-api", model="m", effort="", cwd=str(tmp_path),
        permission_mode="ask", surface="jarvis",
    )
    seen = Seen()
    monkeypatch.setattr(service_mod, "resolve_runner", lambda *a, **k: "claude-cli")

    async def seat_for(provider: str):
        return provider, "claude-cli"

    monkeypatch.setattr("dodaios.core.task_agent.subscription_seat_off_loop", seat_for)

    async def cli_turn(handle, prompt, runner, **_kwargs):
        seen.prompts.append(prompt)
        await handle.emit(
            make_event("assistant_text", {"turn_id": handle.turn_id, "text": "I sent the email."})
        )
        await handle.emit(
            make_event("turn_finished", {"turn_id": handle.turn_id, "status": "done"})
        )

    monkeypatch.setattr(service_mod, "run_cli_turn", cli_turn)
    await svc.send(session.session_id, "/note-skill hi")
    await asyncio.wait_for(svc._running[session.session_id].task, 10)
    assert seen.prompts == ["/note-skill hi"]
