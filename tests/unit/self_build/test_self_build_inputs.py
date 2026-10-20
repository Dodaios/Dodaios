"""What the loop observes beyond voice and the Jarvis chat, and how a memory's use is measured.

* Prompts the person types to coding agents in the IDE are evidence; briefs
  the brain or an agent sent to a pane are not.
* Agent chats feed needs: a need of one agent's chat is left to that agent's
  own learning, a need that spans agents is the loop's unless an agent already
  has a skill for it.
* A self-built memory counts as used only when it was in the prompt and the
  turn relied on it; corrections count against it.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agentic_ide.prompt_history import PromptHistoryEntry, path_for
from dodaios.self_build import Kind, Outcome, State, judge, loop
from dodaios.self_build.miner import stems

from .test_self_build_loop import (  # noqa: F401 - _person_zone is an autouse fixture
    SKILL_ANSWER,
    _days_ago,
    _person_zone,
    _say,
    _settle,
)

PANE_ANSWER = {
    "build": "skill",
    "title": "A skill that runs the test suite and fixes what fails, as you keep asking.",
    "case": "Typed to a coding agent on three days.",
    "skill": {
        "name": "Run Tests And Fix",
        "description": "Hand the coding agent the test run and the fixes.",
        "triggers": ["run the test suite and fix the failures"],
        "body": "## Run Tests And Fix\n\n1. Ask the coding agent to run the test suite.\n"
        "2. Tell the user what failed and what was fixed.",
    },
}

PROMPT = "run the whole test suite and fix the failing tests"


def _write_history(folder: Path, history_id: str, rows: list[dict[str, Any]]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / path_for(history_id).name
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for i, row in enumerate(rows):
            entry = PromptHistoryEntry(
                id=row.get("id", f"{history_id}-{i}-{row['at']}"),
                sequence=i + 1,
                text=row["text"],
                at=row["at"],
                submitted=True,
                typed=row.get("typed", ""),
                attachments=tuple(row.get("attachments", ())),
                origin=row.get("origin", "person"),
            )
            handle.write(json.dumps(asdict(entry)) + "\n")
    return path


@pytest.fixture
def panes(world: Any, tmp_path: Path) -> Path:
    folder = tmp_path / "prompt_history"
    world.loop.builders.env.pane_history = lambda: folder
    world.configure(skill="suggest")
    return folder


# ------------------------------------------------------------------ pane prompts


async def test_a_pane_prompt_typed_on_three_days_becomes_one_proposal(
    world: Any, panes: Path
) -> None:
    world.brain.answers = [PANE_ANSWER]
    _write_history(
        panes,
        "pane-a",
        [{"text": PROMPT, "at": _days_ago(d, 10) / 1000} for d in (6, 4, 2)],
    )
    assert await world.loop.ingest_pane_prompts() == 3
    # Read once: a second pass files nothing again.
    assert await world.loop.ingest_pane_prompts() == 0
    turns = world.loop.store.recent_turns(since_ms=0)
    assert {t.channel for t in turns} == {"pane"} and len(turns) == 3
    opened = await world.loop.run_queue()
    assert len(opened) == 1
    (card,) = opened
    assert card.kind == Kind.SKILL and card.state == State.PROPOSED
    assert len(card.evidence) == 3 and " pane " in card.evidence[0]
    (decide_prompt,) = [p for s, p in world.brain.calls if "allowed" in p]
    assert json.loads(decide_prompt)["turns"][0]["channel"] == "pane"
    assert len(world.service.ledger.list(limit=100)) == 1


async def test_prompts_the_brain_or_an_agent_sent_are_not_evidence(world: Any, panes: Path) -> None:
    rows = [{"text": PROMPT, "at": _days_ago(d, 10) / 1000, "origin": ""} for d in (6, 4, 2)]
    # A dropped file without the person's own sentence: the text is the file's.
    rows.append(
        {
            "text": "contents of notes.txt: run the whole test suite",
            "at": _days_ago(1, 10) / 1000,
            "attachments": [{"name": "notes.txt"}],
        }
    )
    _write_history(panes, "pane-b", rows)
    assert await world.loop.ingest_pane_prompts() == 0
    assert world.loop.store.recent_turns(since_ms=0) == []


async def test_the_persons_words_are_filed_not_the_brief_around_them(
    world: Any, panes: Path
) -> None:
    _write_history(
        panes,
        "pane-c",
        [
            {
                "text": "## Task\nRun the suite. Context: @tests/ @pyproject.toml",
                "typed": PROMPT,
                "at": _days_ago(1, 10) / 1000,
            }
        ],
    )
    await world.loop.ingest_pane_prompts()
    (turn,) = world.loop.store.recent_turns(since_ms=0)
    assert turn.text == PROMPT and not turn.correction


async def test_the_ide_hook_reads_only_the_pane_it_names(world: Any, panes: Path) -> None:
    _write_history(panes, "pane-d", [{"text": PROMPT, "at": _days_ago(1, 10) / 1000}])
    _write_history(panes, "pane-e", [{"text": "open the changelog", "at": _days_ago(1, 11) / 1000}])
    world.loop._maintained = time.monotonic()  # no maintenance pass reading every pane
    world.loop.pane_prompt_recorded("pane-d")
    await world.loop.drain()
    assert [t.text for t in world.loop.store.recent_turns(since_ms=0)] == [PROMPT]


async def test_pane_prompts_typed_while_paused_are_never_filed(world: Any, panes: Path) -> None:
    _write_history(panes, "pane-f", [{"text": PROMPT, "at": _days_ago(1, 10) / 1000}])
    world.service.set_paused(True)
    assert await world.loop.ingest_pane_prompts() == 0
    world.service.set_paused(False)
    assert await world.loop.ingest_pane_prompts() == 0
    assert world.loop.store.recent_turns(since_ms=0) == []


def test_history_rows_keep_their_origin_and_old_rows_have_none() -> None:
    entry = PromptHistoryEntry("x", 1, "hello there", 1.0, True, origin="person")
    assert PromptHistoryEntry.from_dict(asdict(entry)).origin == "person"
    old = {"id": "y", "sequence": 1, "text": "hello", "at": 1.0, "submitted": True}
    assert PromptHistoryEntry.from_dict(old).origin == ""


@pytest.mark.parametrize(
    ("headers", "cookies", "person"),
    [
        ({"sec-fetch-site": "same-origin"}, {}, True),
        ({"sec-fetch-site": "same-origin", "authorization": "Bearer k"}, {}, False),
        ({"authorization": "Bearer k"}, {}, False),
        ({}, {}, False),
        ({"sec-fetch-site": "cross-site"}, {}, False),
    ],
)
def test_only_the_window_is_the_person(headers: dict, cookies: dict, person: bool) -> None:
    from dodaios.ui.web.control_auth import person_at_window

    request = SimpleNamespace(headers=headers, cookies=cookies)
    assert person_at_window(request) is person  # type: ignore[arg-type]


# ------------------------------------------------------------------ agent chats


async def _status_in(world: Any, agents: list[str]) -> None:
    for (days, hour), agent in zip(((5, 9), (3, 14), (1, 17)), agents, strict=True):
        extra: dict[str, Any] = {}
        if agent:
            extra = {"agent_id": agent, "channel": "agent", "conversation": f"chat:society:{agent}"}
        await _say(
            world,
            "Please check the build status of the dodaios repo",
            _days_ago(days, hour),
            tools=("mcp:github/list_runs",),
            **extra,
        )


def _agent_skill(tmp_path: Path, name: str, trigger: str, *, state: str = "draft") -> Any:
    from dodaios.skills.authoring.service import SkillCreateRequest, render_skill_md
    from dodaios.skills.loader import parse_skill

    folder = tmp_path / "agent-skills" / name
    folder.mkdir(parents=True)
    path = folder / "SKILL.md"
    path.write_text(
        render_skill_md(
            SkillCreateRequest(
                name=name,
                description="Report the CI build status of a repository.",
                triggers=({"type": "voice", "pattern": trigger},),
                body="1. Look up the latest CI run.\n2. Report it.",
                state=state,
            )
        ),
        encoding="utf-8",
    )
    return parse_skill(path)


async def test_a_need_of_one_agents_chat_is_left_to_that_agent(world: Any) -> None:
    world.brain.answers = [SKILL_ANSWER]
    await _status_in(world, ["octo", "octo", "octo"])
    assert len(world.loop.store.recent_turns(since_ms=0)) == 3  # filed, not dropped
    assert world.loop._queue == {}
    assert await world.loop.run_queue() == []
    assert world.brain.decide_calls == 0


async def test_a_need_an_agent_has_a_skill_for_is_not_built(world: Any, tmp_path: Path) -> None:
    skill = _agent_skill(tmp_path, "ci-status", "check the build status")
    asked: list[str] = []

    def agent_skills(agent_id: str) -> list[Any]:
        asked.append(agent_id)
        return [skill] if agent_id == "octo" else []

    world.loop.builders.env.agent_skills = agent_skills
    world.brain.answers = [SKILL_ANSWER]
    await _status_in(world, ["octo", "", ""])
    assert await world.loop.run_queue() == []
    assert world.brain.decide_calls == 0
    assert asked == ["octo"]
    signature = world.loop.store.cluster(world.loop.store.recent_turns(since_ms=0)[0].cluster)
    verdict = world.loop.store.decision(signature.signature)
    assert verdict is not None and verdict[1] == "served"


async def test_a_need_that_spans_agents_and_the_assistant_is_the_loops(world: Any) -> None:
    world.configure(skill="suggest")
    world.brain.answers = [SKILL_ANSWER]
    await _status_in(world, ["octo", "", "nova"])
    (card,) = await world.loop.run_queue()
    assert card.kind == Kind.SKILL and card.state == State.PROPOSED
    assert world.brain.decide_calls == 1


def test_an_agent_skill_without_routable_triggers_still_serves_by_its_words(
    tmp_path: Path,
) -> None:
    skill = _agent_skill(tmp_path, "ci-status", "zzzz qqqq")
    said = ["check the build status of the repo"] * 3
    core = stems(said[0])
    assert judge.served_by_agent([skill], said, core) == "ci-status"
    assert (
        judge.served_by_agent([skill], ["order a pizza with olives"], stems("order pizza")) is None
    )


async def test_a_domain_in_an_agents_chat_proposes_no_second_agent(world: Any) -> None:
    texts = [
        "list the open issues in the repo",
        "show the pull requests waiting",
        "check the ci run of main",
    ]
    for i in range(10):
        await _say(
            world,
            texts[i % 3],
            _days_ago(1 + 2 * i, 9),
            tools=("mcp:github/list_issues",),
            agent_id="octo",
            channel="agent",
            conversation="chat:society:octo",
        )
    await world.loop.run_queue()
    assert [r for r in world.service.ledger.list(limit=100) if r.kind == Kind.AGENT] == []


# ------------------------------------------------------------------ memory use


ENTRY = "The user's office is the Berlin office, not Munich."


async def _memory(world: Any) -> Any:
    world.brain.answers = [
        {
            "build": "memory",
            "title": "Remember that your office is the Berlin one.",
            "memory": {
                "target": "memory",
                "text": ENTRY,
                "evidence": "I meant the Berlin office",
                "importance": 8,
            },
        }
    ]
    await _say(world, "No, I meant the Berlin office, not Munich", _days_ago(3, 10))
    await _say(world, "that's wrong, I meant the Berlin office", _days_ago(1, 11))
    (opened,) = await world.loop.run_queue()
    record = await _settle(world, opened.id)
    assert record.kind == Kind.MEMORY and record.state == State.TRIAL, record.note
    assert ENTRY in world.notebook.snapshot()
    return record


def _outcomes(world: Any, record: Any) -> dict[str, int]:
    return world.service.ledger.get(record.id).outcomes


async def test_a_memory_counts_once_per_conversation_when_the_turn_names_it(
    world: Any,
) -> None:
    record = await _memory(world)
    stamp = _days_ago(0, 9)
    await _say(world, "book me a desk in the Berlin office", stamp, conversation="c1")
    await _say(
        world, "and a parking spot at the office in Berlin", stamp + 60_000, conversation="c1"
    )
    assert _outcomes(world, record) == {"used": 1}
    # Unrelated turns do not count, whatever the old approximation said.
    await _say(
        world, "what's the weather tomorrow", stamp + 120_000, conversation="c2", answer="Sun."
    )
    assert _outcomes(world, record) == {"used": 1}


async def test_a_memory_counts_when_the_answer_carries_what_only_it_knew(world: Any) -> None:
    record = await _memory(world)
    stamp = _days_ago(0, 9)
    await _say(
        world,
        "book me a meeting room near my office",
        stamp,
        conversation="c3",
        answer="Booked room 4.12 in the Berlin office for 10:00.",
    )
    assert _outcomes(world, record) == {"used": 1}


async def test_a_correction_right_after_a_memory_was_relied_on_counts_against_it(
    world: Any,
) -> None:
    record = await _memory(world)
    stamp = _days_ago(0, 9)
    await _say(world, "book me a desk in the Berlin office", stamp, conversation="c4")
    await _say(world, "no, that's wrong, I moved to Hamburg", stamp + 30_000, conversation="c4")
    assert _outcomes(world, record) == {"used": 1, "corrected": 1}


async def test_a_memory_not_in_the_prompt_or_not_read_there_is_not_counted(world: Any) -> None:
    record = await _memory(world)
    stamp = _days_ago(0, 9)
    # Coding agents and society agents do not read the assistant's notebook.
    await _say(world, "fix the Berlin office page", stamp, channel="pane", conversation="pane:x")
    await _say(
        world,
        "book a desk in the Berlin office",
        stamp + 1,
        agent_id="octo",
        channel="agent",
        conversation="chat:society:octo",
    )
    assert _outcomes(world, record) == {}
    # The person edited the entry: it is no longer in the prompt.
    (entry,) = [e for e in world.notebook.entries()["memory"] if e.text == ENTRY]
    world.notebook.apply(
        target="memory",
        operation="replace",
        entry_id=entry.id,
        expected=ENTRY,
        text="The user's office is the Hamburg office.",
        source="test: edited by the person",
    )
    await _say(world, "book me a desk in the Berlin office", stamp + 2, conversation="c5")
    assert _outcomes(world, record) == {}


def test_memory_relied_is_deterministic() -> None:
    said = stems("book me a desk in the Berlin office")
    assert judge.memory_relied(ENTRY, said=said, answer="", topic=False)
    weather = stems("what's the weather tomorrow")
    assert not judge.memory_relied(ENTRY, said=weather, answer="Berlin is sunny", topic=False)
    assert judge.memory_relied(ENTRY, said=weather, answer="Berlin is sunny", topic=True)
    assert not judge.memory_relied(ENTRY, said=weather, answer="", topic=True)


def test_loop_constants_keep_the_notebook_channels() -> None:
    assert {"voice", "chat"} == set(loop._NOTEBOOK_CHANNELS)
    assert Outcome.CORRECTED.value == "corrected"
