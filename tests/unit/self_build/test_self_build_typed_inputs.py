"""What the person really does in the app reaches the loop.

The maintainer works in the IDE: prompts typed or dictated straight into a
Claude pane, the side chat, the agent chat. Before this, only the prompt bar
counted, so weeks of work left the loop with nothing to look at.

* A prompt a Claude pane reports (its ``UserPromptSubmit`` hook) is the
  person's when they pressed Enter in that pane's window first, it is not a
  prompt the IDE itself sent, and it describes a task.
* The side chat and the IDE's agent chat feed the loop; a surface nobody types
  to as themselves does not.
* Read offsets of pane files that are gone or too old are pruned, and files
  too old to count get none.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agentic_ide import claude_session_hook
from dodaios.agentic_ide.prompt_history import PromptHistoryEntry, path_for
from dodaios.self_build import Kind, State, loop

from .test_self_build_inputs import PANE_ANSWER, PROMPT
from .test_self_build_loop import _days_ago, _person_zone  # noqa: F401 - autouse fixture

PANE = "7f3c2a90b1d24e6f8a5b0c1d2e3f4a5b"


@pytest.fixture
def typed(world: Any, tmp_path: Path) -> Path:
    folder = tmp_path / "pane_sessions"
    history = tmp_path / "prompt_history"
    world.loop.builders.env.pane_typed = lambda: folder
    world.loop.builders.env.pane_history = lambda: history
    world.configure(skill="suggest")
    return folder


def _report(folder: Path, prompt: str, at: float, pane: str = PANE) -> None:
    """What the pane's hook writes when the CLI accepts a prompt."""
    path = claude_session_hook.prompts_file(pane, folder)
    assert path is not None
    folder.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"at": at, "prompt": prompt, "session_id": "s"}) + "\n")


def _enter(world: Any, at: float, pane: str = PANE) -> None:
    """The person pressed Enter in the pane's window at ``at``."""
    world.loop._keyboard.setdefault(pane, []).append(at)


async def test_a_prompt_typed_into_a_pane_on_three_days_becomes_one_proposal(
    world: Any, typed: Path
) -> None:
    world.brain.answers = [PANE_ANSWER]
    for day in (6, 4, 2):
        at = _days_ago(day, 10) / 1000
        _enter(world, at - 0.2)
        _report(typed, PROMPT, at)
    assert await world.loop.ingest_typed_prompts([PANE]) == 3
    assert await world.loop.ingest_typed_prompts([PANE]) == 0  # read once
    turns = world.loop.store.recent_turns(since_ms=0)
    assert {t.channel for t in turns} == {"pane"} and len(turns) == 3
    assert turns[0].conversation == f"pane:{path_for(PANE).stem[:16]}"
    (card,) = await world.loop.run_queue()
    assert card.kind == Kind.SKILL and card.state == State.PROPOSED


async def test_a_reported_prompt_without_the_persons_enter_is_not_theirs(
    world: Any, typed: Path
) -> None:
    at = _days_ago(1, 10) / 1000
    _report(typed, PROMPT, at)
    _enter(world, at + 60)  # an Enter AFTER the prompt confirms nothing earlier
    assert await world.loop.ingest_typed_prompts([PANE]) == 0
    assert world.loop.store.recent_turns(since_ms=0) == []


async def test_one_enter_confirms_one_prompt(world: Any, typed: Path) -> None:
    at = _days_ago(1, 10) / 1000
    _enter(world, at - 1)
    _report(typed, PROMPT, at)
    _report(typed, "rebuild the whole frontend bundle and redeploy it", at + 5)
    assert await world.loop.ingest_typed_prompts([PANE]) == 1


async def test_a_prompt_the_ide_sent_is_not_the_persons_even_after_enter(
    world: Any, typed: Path, tmp_path: Path
) -> None:
    at = _days_ago(1, 10) / 1000
    history = tmp_path / "prompt_history"
    history.mkdir(parents=True)
    entry = PromptHistoryEntry("x", 1, f"{PROMPT}\n\nThe repo uses pytest.", at - 2, False)
    (history / path_for(PANE).name).write_text(json.dumps(asdict(entry)) + "\n", encoding="utf-8")
    # The person pressed Enter on a brief Jarvis left unsubmitted in the box.
    _enter(world, at - 0.5)
    _report(typed, f"{PROMPT}\n\nThe repo uses pytest.", at)
    assert await world.loop.ingest_typed_prompts([PANE]) == 0


@pytest.mark.parametrize(
    "prompt",
    [
        "continue please",  # steering, not a task
        "/clear",
        "!git status --short --branch now",
        "<teammate-message from='lead'>run the whole test suite</teammate-message>",
    ],
)
async def test_commands_and_steering_are_not_needs(world: Any, typed: Path, prompt: str) -> None:
    at = _days_ago(1, 10) / 1000
    _enter(world, at - 0.5)
    _report(typed, prompt, at)
    assert await world.loop.ingest_typed_prompts([PANE]) == 0


async def test_enter_in_a_pane_reads_it_a_moment_later(
    world: Any, typed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop, "TYPED_READ_DELAY_S", 0.0)
    world.loop._maintained = time.monotonic()  # no maintenance pass
    world.loop.pane_keyboard_submit(PANE)
    _report(typed, PROMPT, time.time() + 0.1)
    for _ in range(50):
        await world.loop.drain()
        if world.loop.store.recent_turns(since_ms=0):
            break
        await asyncio.sleep(0.02)
    (turn,) = world.loop.store.recent_turns(since_ms=0)
    assert turn.text == PROMPT and turn.channel == "pane"


async def test_the_maintenance_pass_reads_panes_the_person_typed_in(
    world: Any, typed: Path
) -> None:
    at = time.time() - 30
    _enter(world, at - 1)
    _report(typed, PROMPT, at)
    await world.loop.maintain()
    assert [t.text for t in world.loop.store.recent_turns(since_ms=0)] == [PROMPT]


# ------------------------------------------------------------------ chat surfaces


def _completion(text: str) -> Any:
    return SimpleNamespace(
        turn=SimpleNamespace(direct_user=True, user_text=text, turn_id="t1"),
        events_json=json.dumps(
            [
                {"kind": "user_message", "payload": {"text": text + "\n\nFiles...", "typed": text}},
                {"kind": "turn_finished", "payload": {"status": "done"}},
            ]
        ),
    )


@pytest.mark.parametrize(("surface", "channel"), [("side", "side"), ("agent", "pane")])
async def test_the_side_chat_and_the_agent_chat_are_the_person(
    world: Any, surface: str, channel: str
) -> None:
    text = "what does this queued sign on github mean"
    await world.loop.chat_turn_completed(
        SimpleNamespace(session_id="s1"), _completion(text), surface=surface
    )
    await world.loop.drain()
    (turn,) = world.loop.store.recent_turns(since_ms=0)
    assert turn.channel == channel and turn.text == text


async def test_a_surface_nobody_types_to_as_themselves_is_not_filed(world: Any) -> None:
    await world.loop.chat_turn_completed(
        SimpleNamespace(session_id="s2"),
        _completion("set up the local model server for me"),
        surface="local-models",
    )
    await world.loop.drain()
    assert world.loop.store.recent_turns(since_ms=0) == []


def test_the_ide_chats_carry_the_completion_hook() -> None:
    from dodaios.agent_chat.surface_kits import kit_for

    for surface in ("agent", "side", "jarvis", "society"):
        assert kit_for(surface).turn_completed is not None, surface


# ------------------------------------------------------------------ offsets stay bounded


async def test_offsets_of_gone_and_old_pane_files_are_pruned(world: Any, typed: Path) -> None:
    history = world.loop.builders.env.pane_history()
    history.mkdir(parents=True, exist_ok=True)
    fresh = history / "fresh.jsonl"
    old = history / "old.jsonl"
    for path in (fresh, old):
        path.write_text('{"id": "x"}\n', encoding="utf-8")
    month_ago = time.time() - 40 * 86_400
    os.utime(old, (month_ago, month_ago))
    store = world.loop.store
    for name in ("fresh.jsonl", "old.jsonl", "gone.jsonl"):
        store.set_meta(f"pane:{name}", "12")
    store.set_meta("typed:gone.prompts.jsonl", "40")
    store.set_meta("decide:day", "1")  # not an offset: kept

    assert await asyncio.to_thread(world.loop._prune_offsets) == 3
    assert store.meta_keys("pane:") == ["pane:fresh.jsonl"]
    assert store.meta_keys("typed:") == []
    assert store.get_meta("decide:day") == "1"


async def test_pane_files_too_old_to_count_get_no_offset(world: Any, typed: Path) -> None:
    history = world.loop.builders.env.pane_history()
    history.mkdir(parents=True, exist_ok=True)
    old = history / "old.jsonl"
    old.write_text('{"id": "x", "text": "t", "at": 1.0, "sequence": 1}\n', encoding="utf-8")
    month_ago = time.time() - 40 * 86_400
    os.utime(old, (month_ago, month_ago))
    assert await world.loop.ingest_pane_prompts() == 0
    assert world.loop.store.meta_keys("pane:") == []


# ------------------------------------------------------------------ the hook itself


def test_the_hook_appends_a_typed_prompt_and_prints_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    monkeypatch.setenv(claude_session_hook.PANE_ENV, PANE)
    monkeypatch.setenv(claude_session_hook.DIR_ENV, str(tmp_path))
    payload = {"hook_event_name": "UserPromptSubmit", "prompt": PROMPT, "session_id": "abc"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert claude_session_hook.main() == 0
    # Claude Code adds this hook's stdout to the prompt: it must stay empty.
    assert capsys.readouterr().out == ""
    path = claude_session_hook.prompts_file(PANE, tmp_path)
    (row,) = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert row["prompt"] == PROMPT and row["session_id"] == "abc"
    # The session record is not touched by a prompt.
    assert not (tmp_path / f"{PANE}.json").exists()


def test_the_hook_starts_a_full_prompts_file_over(tmp_path: Path) -> None:
    path = claude_session_hook.prompts_file(PANE, tmp_path)
    path.write_text("x" * (claude_session_hook.PROMPTS_MAX_BYTES + 1), encoding="utf-8")
    claude_session_hook.record_prompt(PANE, tmp_path, {"prompt": PROMPT})
    assert path.stat().st_size < 1_000


def test_the_pane_settings_add_the_prompt_hook() -> None:
    from dodaios.agentic_ide import pane_sessions

    argv, _env = pane_sessions.launch_wiring("pane-typed")
    settings = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    (entry,) = settings["hooks"]["UserPromptSubmit"]
    assert "claude_session_hook.py" in entry["hooks"][0]["command"]


# ------------------------------------------------------------------ no test writes the live data


def test_tests_never_write_the_real_prompt_history() -> None:
    from dodaios.agentic_ide import pane_sessions, prompt_history
    from dodaios.core.paths import user_data_dir

    real = user_data_dir().resolve()
    for folder in (prompt_history.store_dir(), pane_sessions.prompts_dir()):
        assert not folder.resolve().is_relative_to(real), folder


def test_a_dev_instance_keeps_its_own_prompt_history(monkeypatch: pytest.MonkeyPatch) -> None:
    from dodaios.agentic_ide import prompt_history
    from dodaios.core import instance

    monkeypatch.undo()  # the real resolver, not the test redirect
    dev = SimpleNamespace(state_file_suffix=".dev")
    monkeypatch.setattr(instance, "current_instance", lambda: dev)
    assert prompt_history._store_dir().name == "prompt_history.dev"


# ------------------------------------------------------------------ served by a skill


async def test_coding_agent_turns_are_not_served_by_an_assistant_skill(
    world: Any, typed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A skill the assistant's router would pick says nothing about work a
    coding agent did: found live, the GitHub plugin's skill 'served' a request
    to count a checkout's lines and no proposal was made."""
    from dodaios.self_build import judge

    asked: list[list[str]] = []

    def router(_installed: Any, said: list[str]) -> str:
        asked.append(said)
        return "plugin-github"

    monkeypatch.setattr(judge, "served_by", router)
    world.brain.answers = [PANE_ANSWER]
    for day in (6, 4, 2):
        at = _days_ago(day, 10) / 1000
        _enter(world, at - 0.2)
        _report(typed, PROMPT, at)
    await world.loop.ingest_typed_prompts([PANE])
    (card,) = await world.loop.run_queue()
    assert card.kind == Kind.SKILL and asked == []


# ------------------------------------------------------------------ voice


async def test_a_finished_voice_turn_on_the_bus_is_filed(world: Any) -> None:
    """The event every voice path publishes reaches the miner over the app's bus."""
    from dodaios.core.events import VoiceTurnCompleted

    await world.bus.publish(
        VoiceTurnCompleted(
            session_id="call-1",
            turn_id="t1",
            user_text="what is on my calendar for tomorrow morning",
            user_lang="en",
            jarvis_text="Two meetings.",
            tool_calls=("calendar_list",),
        )
    )
    await world.loop.drain()
    (turn,) = world.loop.store.recent_turns(since_ms=0)
    assert turn.channel == "voice" and turn.conversation == "voice:call-1"
    assert turn.tools == ("calendar_list",) and turn.ref == "voice:call-1/t1"
