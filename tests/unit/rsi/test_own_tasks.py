"""Benchmark tasks from the person's own memory and messages."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.store import MemoryVault
from dodaios.rsi import night as nights
from dodaios.rsi import overlay, params
from dodaios.rsi.bench.model import Domain, Source, Split
from dodaios.rsi.bench.own import chat, messages, questions
from dodaios.rsi.bench.own.maker import OwnRecallMaker
from dodaios.rsi.bench.own.world import LIVE_WORLD, LiveWorld, take_snapshot
from dodaios.rsi.bench.store import BenchStore
from dodaios.self_change import SelfChangeRegistry

# Mostly things that happened: those are not in the always-on block, so a search has to
# find them. (What the assistant always has in mind is never offered to the labeller.)
FACTS = [
    ("Lea told me her birthday party is on 14 March.", "episode", ["Lea"]),
    ("Lea moved to Lisbon for her new job at the harbour office.", "episode", ["Lea", "Lisbon"]),
    ("The dentist moved to the second floor above the bakery.", "episode", []),
    ("I signed up for the harbour half marathon in October.", "episode", []),
    ("We painted the kitchen green last spring.", "episode", []),
    ("My sister plays the cello in a quartet.", "relationship", []),
    ("We put the spare keys in the blue tin on the shelf.", "episode", []),
    ("I prefer window seats on long train rides.", "preference", []),
]
HIDDEN_FACT = "The surprise party for Lea is on Saturday evening."

SAID = [
    "When is Lea's birthday again?",
    "thanks, that is all for today",
    "Where did we put the spare keys?",
    "What is the capital of Australia?",
    "Book me a window seat for the train on Friday please",
    "ok",  # too short to be a task
    "Remind me which colour the kitchen is",
    "How far is the half marathon I train for?",
    "Summarise the last three commits in this repository",
    "Which floor is the dentist on?",
]


def _vault(path: Path) -> MemoryVault:
    vault = MemoryVault(path)
    for text, kind, entities in FACTS:
        vault.remember(text, kind, entities=entities)
    vault.remember(HIDDEN_FACT, "episode", entities=["Lea"], sensitivity="sensitive")
    return vault


def _chat_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE agent_chat_sessions (session_id TEXT PRIMARY KEY, surface TEXT);"
        "CREATE TABLE agent_chat_events (session_id TEXT, seq INTEGER, ts_ms INTEGER,"
        " kind TEXT, payload TEXT);"
        "INSERT INTO agent_chat_sessions VALUES ('lead', 'jarvis');"
        "INSERT INTO agent_chat_sessions VALUES ('code', 'agent');"
    )
    rows = [("lead", i, 1000 + i, "user_message", {"text": text}) for i, text in enumerate(SAID)]
    rows.append(("lead", 50, 2000, "user_message", {"text": "report", "origin": "background"}))
    rows.append(("lead", 51, 2001, "user_message",
                 {"text": "A long brief written around it", "typed": "Where does Lea live now?"}))
    rows.append(("code", 0, 3000, "user_message", {"text": "fix the failing test in parser.py"}))
    rows.append(("lead", 52, 2002, "assistant_text", {"text": "not a user message"}))
    conn.executemany(
        "INSERT INTO agent_chat_events VALUES (?,?,?,?,?)",
        [(s, q, t, k, json.dumps(p)) for s, q, t, k, p in rows],
    )
    conn.commit()
    conn.close()
    return path


class Model:
    """A stand-in for the assistant's provider: answers both kinds of prompt by rule."""

    def __init__(self, *, answers: bool = True, agree: bool = True) -> None:
        self.prompts: list[tuple[str, str]] = []
        self.answers = answers
        self.agree = agree

    def __call__(self, system: str, prompt: str) -> str | None:
        self.prompts.append((system, prompt))
        if not self.answers:
            return None
        if system == questions.SYSTEM:
            facts = json.loads(prompt[prompt.index("[") : prompt.rindex("]") + 1])
            out = []
            for fact in facts:
                words = [w for w in re.findall(r"[A-Za-z]{5,}", fact["fact"])][:2]
                first = f"Tell me again what you know about {' and '.join(words)}"
                out.append({"id": fact["id"], "messages": [first, fact["fact"], "x" * 3]})
            return "```json\n" + json.dumps(out) + "\n```"
        answer = []
        blocks = re.findall(r"Message (\d+): (.*)\nFacts: (\{.*\})", prompt)
        for number, text, raw in blocks:
            facts = json.loads(raw)
            said = set(re.findall(r"[a-z]{5,}", text.lower()))
            needs = [
                name
                for name, fact in facts.items()
                if said & set(re.findall(r"[a-z]{5,}", fact.lower()))
            ]
            if not self.agree and name_starts_with_g(facts):
                needs = [name for name in facts if name not in needs]  # always another answer
            answer.append({"n": int(number), "needs": needs})
        return json.dumps(answer)


def name_starts_with_g(facts: dict[str, str]) -> bool:
    return any(name.startswith("g") for name in facts)


@pytest.fixture
def home(tmp_path: Path):
    vault = _vault(tmp_path / "vault.db")
    bench = BenchStore(tmp_path / "bench.db")
    world = LiveWorld(tmp_path / "vault.db", tmp_path / "rsi")
    yield SimpleNamespace(
        path=tmp_path, vault=vault, bench=bench, world=world, chat=_chat_db(tmp_path / "chat.db")
    )
    world.close()
    bench.close()
    vault.close()
    params.install(None)


# ----------------------------------------------------------------- the copy


def test_a_night_runs_against_a_copy_and_the_live_memory_is_not_touched(home) -> None:
    before = hashlib.sha256((home.path / "vault.db").read_bytes()).hexdigest()
    assert home.world.worlds() == {}
    assert home.world.refresh()
    copy = home.world.worlds()[LIVE_WORLD]
    assert len(copy.vault.list()) == len(FACTS) + 1
    home.vault.remember("A fact that arrives after the copy was taken.", "episode")
    assert len(copy.vault.list()) == len(FACTS) + 1  # the copy stands still
    vault_runtime.recall_for(copy.vault, "Lea birthday")
    copy.vault.mark_used([copy.vault.list()[0].id])  # even a write lands in the copy only
    assert all(m.use_count == 0 for m in home.vault.list())
    home.world.close()
    assert before != "" and (home.path / "rsi" / "vault-snapshot.db").exists()
    assert take_snapshot(home.path / "no-vault.db", home.path / "rsi") is None
    assert not LiveWorld(home.path / "no-vault.db", home.path / "x").refresh()


def test_only_what_the_person_wrote_counts_as_their_message(home) -> None:
    said = chat.person_messages(home.chat)
    assert said[: len(SAID)] == SAID
    assert said[-1] == "Where does Lea live now?"  # the person's sentence, not the brief around it
    assert "report" not in said and all("parser.py" not in text for text in said)
    assert chat.person_messages(home.path / "nothing.db") == []


# ---------------------------------------------------------------- questions


def test_a_question_task_is_kept_only_when_python_agrees(home) -> None:
    memories = home.vault.list()
    lea, lisbon = (next(m for m in memories if word in m.text) for word in ("birthday", "Lisbon"))
    prompt = questions.build_prompt([lea, lisbon], ["ok thanks"])
    assert lea.id in prompt and "ok thanks" in prompt and "Lisbon" in prompt
    answer = [
        {
            "id": lea.id,
            "messages": [
                "When is the birthday of Lea?",
                "Lea's birthday is on 14 March.",  # the memory said again
                "What is the weather like tomorrow?",  # shares no word with it
                "When is the birthday of Lea?",  # the same message twice
                "Which birthday present suits her " + "really " * 40,  # far too long
            ],
        },
        {"id": lisbon.id, "messages": ["Tell me Lea's birthday, the one on 14 March please"]},
        {"id": "mem_unknown", "messages": ["What about the birthday?"]},
    ]
    tasks = questions.tasks_from(answer, [lea, lisbon])
    assert [t.payload["query"] for t in tasks] == ["When is the birthday of Lea?"]
    (task,) = tasks
    assert task.check["gold"] == [lea.id] and task.group == f"memory:{lea.id}"
    assert (task.source, task.payload["world"]) == (Source.MADE, LIVE_WORLD)
    assert questions.tasks_from(answer, [lea, lisbon])[0].id == task.id  # stable
    assert questions.parse("no json here") == [] and questions.parse("[{]") == []
    assert questions.parse('```json\n[{"id": "a", "messages": ["x", 3]}]\n```') == [
        {"id": "a", "messages": ["x"]}
    ]


# ----------------------------------------------------------------- messages


def test_what_is_offered_to_the_labeller_does_not_depend_on_what_was_learned(home) -> None:
    in_mind = vault_runtime.in_mind_ids(home.vault)
    with overlay.active(overlay.Overlay(params={"recall.min_score": 12.0})):
        blind = vault_runtime.recall_for(home.vault, "Lea birthday Lisbon harbour", in_mind=in_mind)
        offered = messages.candidates_for(home.vault, "Lea birthday Lisbon harbour", frozenset())
    assert blind.chosen == () and len(offered) >= 2
    assert all(m.sensitivity != "sensitive" for m in offered)  # never sent to a model
    assert messages.candidates_for(home.vault, "the and you", frozenset()) == ()
    hidden = frozenset(m.id for m in offered)
    assert messages.candidates_for(home.vault, "Lea birthday Lisbon harbour", hidden) == ()


def test_a_message_becomes_a_task_only_when_two_askings_agree(home) -> None:
    lea, keys = (
        next(m for m in home.vault.list() if word in m.text) for word in ("birthday", "spare")
    )
    one = messages.Candidate(messages.key_of("When is Lea's birthday?"), "When is Lea's birthday?",
                             (lea, keys))
    two = messages.Candidate(messages.key_of("thanks"), "thanks, see you", (keys, lea))
    first, second = messages.build_prompt([one, two]), messages.build_prompt([one, two], flip=True)
    assert '"f1"' in first and '"g1"' in second and "Message 2: thanks, see you" in first
    assert first.index(lea.text) < first.index(keys.text)
    assert second.index(keys.text) < second.index(lea.text)  # the other order
    a = messages.parse('[{"n": 1, "needs": ["f1"]}, {"n": 2, "needs": []}]', [one, two])
    b = messages.parse('[{"n": 1, "needs": ["g2"]}, {"n": 2, "needs": ["g1"]}]', [one, two],
                       flip=True)
    assert a == {one.key: frozenset({lea.id}), two.key: frozenset()}
    assert b[one.key] == frozenset({lea.id})  # g2 in the flipped order is the same memory
    assert messages.agreed(a, b) == {one.key: frozenset({lea.id})}
    task = messages.task_from(one, frozenset({lea.id}))
    assert task.check["gold"] == [lea.id] and task.payload["style"] == "message"
    # An answer that names a fact which was not offered is not trusted.
    assert messages.parse('[{"n": 1, "needs": ["f9"]}, {"n": 7, "needs": []}]', [one, two]) == {}
    assert messages.key_of("When is  LEA's birthday?") == one.key
    assert not messages.usable("ok") and not messages.usable("/clear the conversation now")
    assert not messages.usable("word " * 80) and messages.usable("Where are the spare keys?")


# -------------------------------------------------------------------- maker


def test_a_night_makes_tasks_within_its_budget_and_never_sends_a_sensitive_memory(home) -> None:
    model = Model()
    maker = OwnRecallMaker(home.bench, home.world, home.chat, model)
    assert home.world.refresh()
    report = maker.run(max_calls=8)
    assert report["calls"] == len(model.prompts) <= 8 and not report["deferred"]
    assert report["questions"] == len(FACTS) and report["messages"] >= 6
    assert all(HIDDEN_FACT not in prompt for _, prompt in model.prompts)
    tasks = home.bench.tasks(Domain.RECALL, source=Source.MADE)
    styles = [t.payload["style"] for t in tasks]
    assert styles.count("question") == len(FACTS)
    said = [t for t in tasks if t.payload["style"] == "message"]
    by_text = {t.payload["query"]: t.check["gold"] for t in said}
    lea = next(m.id for m in home.vault.list() if "birthday" in m.text)
    assert by_text["When is Lea's birthday again?"] == [lea]
    assert by_text["What is the capital of Australia?"] == []  # needs no memory
    assert "ok" not in by_text
    # Everything was looked at: the next night has nothing to ask.
    again = Model()
    assert OwnRecallMaker(home.bench, home.world, home.chat, again).run(8)["calls"] == 0
    assert again.prompts == []


def test_without_a_model_nothing_is_made_and_nothing_is_marked_as_done(home) -> None:
    assert home.world.refresh()
    for model in (Model(answers=False), lambda system, prompt: 1 / 0):
        report = OwnRecallMaker(home.bench, home.world, home.chat, model).run(8)
        assert report["deferred"] and report["questions"] == 0 and report["calls"] == 1
    assert home.bench.tasks(Domain.RECALL) == []
    later = OwnRecallMaker(home.bench, home.world, home.chat, Model()).run(8)
    assert later["questions"] == len(FACTS)  # it tries again and nothing was lost


def test_a_small_budget_makes_less_and_the_next_night_goes_on(home) -> None:
    assert home.world.refresh()
    first = OwnRecallMaker(home.bench, home.world, home.chat, Model()).run(max_calls=1)
    assert first["calls"] == 1 and first["questions"] == len(FACTS)
    labelled = first["messages"]  # only messages no memory was found for cost nothing
    second = OwnRecallMaker(home.bench, home.world, home.chat, Model()).run(max_calls=8)
    assert second["messages"] > 0 and second["questions"] == 0
    assert labelled + second["messages"] >= 6


def test_messages_the_two_askings_disagree_on_are_left_out_for_good(home) -> None:
    assert home.world.refresh()
    report = OwnRecallMaker(home.bench, home.world, home.chat, Model(agree=False)).run(8)
    tasks = [t for t in home.bench.tasks(Domain.RECALL) if t.payload["style"] == "message"]
    assert all(t.check["gold"] == [] for t in tasks)  # only the ones without a candidate
    assert report["messages"] == len(tasks)
    assert OwnRecallMaker(home.bench, home.world, home.chat, Model()).run(8)["messages"] == 0


def test_forgetting_a_memory_erases_the_tasks_about_it(home) -> None:
    assert home.world.refresh()
    OwnRecallMaker(home.bench, home.world, home.chat, Model()).run(8)
    lea = next(m for m in home.vault.list() if "birthday" in m.text)
    about = [t for t in home.bench.tasks(Domain.RECALL) if lea.id in t.check["gold"]]
    assert len(about) >= 2
    home.vault.forget(lea.id)
    assert home.world.refresh()
    report = OwnRecallMaker(home.bench, home.world, home.chat, Model()).run(8)
    assert report["forgotten"] == len(about)
    left = home.bench.tasks(Domain.RECALL)
    assert all(lea.id not in t.check["gold"] for t in left)
    raw = sqlite3.connect(home.path / "bench.db")
    rows = raw.execute(
        "SELECT payload, check_json, retired_ms FROM tasks WHERE id = ?", (about[0].id,)
    ).fetchall()
    raw.close()
    assert rows == [("{}", "{}", rows[0][2])] and rows[0][2] > 0  # the text is gone


# -------------------------------------------------------- in the night


def test_the_installations_night_builds_its_tasks_and_measures_on_them(home) -> None:
    registry = SelfChangeRegistry(home.path)
    store = params.install(home.path)
    registry.register_handler(nights.Surface.PARAMETER, store)
    maker = OwnRecallMaker(home.bench, home.world, home.chat, Model())
    closed: list[bool] = []

    def prepare() -> dict[str, Any]:
        assert home.world.refresh()
        return maker.run(nights.MAX_MODEL_CALLS)

    def finish() -> None:
        closed.append(True)
        home.world.close()

    night = nights.Night(
        registry, home.bench, home.world.worlds, prepare=prepare, finish=finish, learners=()
    )
    try:
        report = night.run()
        assert report.made["questions"] == len(FACTS) and not report.idle
        assert sum(report.tasks["recall"].values()) == len(home.bench.tasks(Domain.RECALL))
        assert night.gate.tasks(Domain.RECALL, Split.PRACTICE)  # own tasks decide here
        assert "from your own memory and messages" in " ".join(report.lines())
        assert closed == [True] and home.world.vault is None
        for point in report.measured:
            assert point["source"] == "own" and point["diff"] == 0.0
        assert home.bench.nights()[0]["made"]["calls"] == report.made["calls"]
    finally:
        registry.close()


def test_the_app_wiring_stays_quiet_when_no_model_may_be_asked(tmp_path: Path) -> None:
    _vault(tmp_path / "memory" / "vault.db").close()
    config = SimpleNamespace(
        memory=SimpleNamespace(
            data_dir=str(tmp_path), vault=SimpleNamespace(path=str(tmp_path / "memory/vault.db"))
        )
    )
    registry = SelfChangeRegistry(tmp_path)
    service = nights.install(tmp_path, registry, config=config, loop=None)
    try:
        report = service.night.run()
        assert report.made["deferred"] and report.made["questions"] == 0
        assert report.idle and service.night.bench.tasks(Domain.RECALL) == []
        assert (tmp_path / "rsi" / "vault-snapshot.db").exists()
    finally:
        service.night.bench.close()
        registry.close()
