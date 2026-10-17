"""What is already written stays readable, whatever the reviewer does.

Real notebook files under ``tmp_path``, a scripted reviewer, no provider and
no mocks. Each test reads the prompt block the conversation model would get.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from jarvis.memory.learning import loop as loop_module
from jarvis.memory.learning import notebook as notebook_module
from jarvis.memory.learning.loop import JarvisLearningLoop, current_loop, stop_learning
from jarvis.memory.learning.notebook import JarvisNotebook, snapshot_block
from jarvis.memory.learning.review import Turn


class ScriptedReviewer:
    def __init__(self, *replies: list[dict[str, Any]] | None) -> None:
        self._replies = list(replies)
        self.calls = 0

    async def __call__(self, prompt: str) -> list[dict[str, Any]] | None:
        json.loads(prompt)
        self.calls += 1
        return self._replies.pop(0) if self._replies else []


async def _unavailable(prompt: str) -> list[dict[str, Any]] | None:
    raise ConnectionError("no provider reachable")


def _vault(tmp_path: Path) -> Path:
    return tmp_path / "vault"


def _book(tmp_path: Path) -> JarvisNotebook:
    return JarvisNotebook(_vault(tmp_path), budgets={"user": 600, "memory": 600})


@pytest.fixture(autouse=True)
def _no_active_notebook():
    notebook_module.set_active(None)
    yield
    notebook_module.set_active(None)


async def _drain(loop: JarvisLearningLoop) -> None:
    for _ in range(100):
        if not loop._tasks:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("background work did not finish")


def _config(enabled: bool) -> Any:
    learning = SimpleNamespace(
        enabled=enabled,
        review_every_turns=30,
        idle_review_seconds=300,
        user_budget_chars=600,
        memory_budget_chars=600,
    )
    return SimpleNamespace(memory=SimpleNamespace(learning=learning))


# ── A: written memory is read without any review ───────────────────────────


def test_a_memory_entry_no_review_wrote_is_in_the_prompt(tmp_path: Path) -> None:
    book = _book(tmp_path)
    book.apply(target="memory", operation="add", text="The test project is MemoryTestAlpha.")

    notebook_module.set_active(_book(tmp_path))

    assert "MemoryTestAlpha" in snapshot_block()


# ── B: an explicit request is kept deterministically ───────────────────────


async def test_b_an_explicit_request_is_visible_on_the_next_turn(tmp_path: Path) -> None:
    book = _book(tmp_path)
    notebook_module.set_active(book)
    reviewer = ScriptedReviewer()
    loop = JarvisLearningLoop(book, reviewer, review_every_turns=50, idle_review_seconds=0)

    loop.record(
        "chat:c",
        Turn(user="Remember that my test project is MemoryTestAlpha.", assistant="Okay."),
    )
    await _drain(loop)

    assert "MemoryTestAlpha" in snapshot_block()
    assert reviewer.calls == 0  # no model decided this


# ── C: what the reviewer writes is read on the next turn ───────────────────


async def test_c_a_reviewer_write_is_seen_on_the_next_turn(tmp_path: Path) -> None:
    book = _book(tmp_path)
    notebook_module.set_active(book)
    said = "I am working on MemoryTestAlpha this month."
    reviewer = ScriptedReviewer(
        [
            {
                "target": "memory",
                "operation": "add",
                "text": "The user is working on MemoryTestAlpha this month.",
                "evidence": "working on MemoryTestAlpha this month",
                "importance": 6,
            }
        ]
    )
    loop = JarvisLearningLoop(book, reviewer, review_every_turns=1, idle_review_seconds=0)

    loop.record("chat:c", Turn(user=said, assistant="Noted."))
    await _drain(loop)

    assert reviewer.calls == 1
    assert "MemoryTestAlpha" in snapshot_block()


# ── D: reviewer off, idle or unreachable ───────────────────────────────────


async def test_d_learning_switched_off_still_reads_the_notebook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _book(tmp_path).apply(
        target="memory", operation="add", text="The test project is MemoryTestAlpha."
    )
    monkeypatch.setattr(notebook_module, "notebook_from_config", lambda config: _book(tmp_path))

    try:
        assert loop_module.start_learning(_config(enabled=False), bus=None) is None
        assert current_loop() is None
        assert "MemoryTestAlpha" in snapshot_block()
    finally:
        await stop_learning()
    assert snapshot_block() == ""


async def test_d_an_unreachable_reviewer_loses_nothing(tmp_path: Path) -> None:
    book = _book(tmp_path)
    book.apply(target="memory", operation="add", text="The test project is MemoryTestAlpha.")
    notebook_module.set_active(book)
    loop = JarvisLearningLoop(book, _unavailable, review_every_turns=1, idle_review_seconds=0)

    loop.record("chat:c", Turn(user="I prefer short answers.", assistant="Sure."))
    await _drain(loop)

    assert "MemoryTestAlpha" in snapshot_block()
    assert [e.text for e in book.entries()["memory"]] == ["The test project is MemoryTestAlpha."]


def test_d_an_idle_reviewer_does_not_gate_reading(tmp_path: Path) -> None:
    book = _book(tmp_path)
    book.apply(target="memory", operation="add", text="The test project is MemoryTestAlpha.")
    notebook_module.set_active(book)
    JarvisLearningLoop(book, ScriptedReviewer(), review_every_turns=50, idle_review_seconds=0)

    assert "MemoryTestAlpha" in snapshot_block()


# ── memory-loss cases ──────────────────────────────────────────────────────


def test_memory_survives_a_restart(tmp_path: Path) -> None:
    _book(tmp_path).keep_explicit("My test project is MemoryTestAlpha.")

    restarted = _book(tmp_path)  # a fresh process reads the same files

    assert "MemoryTestAlpha" in restarted.render()


def test_a_repeated_request_is_kept_once(tmp_path: Path) -> None:
    book = _book(tmp_path)
    book.keep_explicit("My test project is MemoryTestAlpha.")
    book.keep_explicit("My test project is MemoryTestAlpha.")

    memory = (book.folder / "MEMORY.md").read_text(encoding="utf-8")
    assert memory.count("MemoryTestAlpha") == 1


def test_a_correction_replaces_the_old_value(tmp_path: Path) -> None:
    book = _book(tmp_path)
    book.apply(target="memory", operation="add", text="The test project is MemoryTestAlpha.")
    [entry] = book.entries()["memory"]

    book.apply(
        target="memory",
        operation="replace",
        entry_id=entry.id,
        text="The test project is MemoryTestBeta.",
    )

    text = _book(tmp_path).render()
    assert "MemoryTestBeta" in text
    assert "MemoryTestAlpha" not in text


async def test_a_removed_entry_is_not_resurrected(tmp_path: Path) -> None:
    book = _book(tmp_path)
    book.apply(target="memory", operation="add", text="The test project is MemoryTestAlpha.")
    [entry] = book.entries()["memory"]
    book.apply(target="memory", operation="remove", entry_id=entry.id)
    loop = JarvisLearningLoop(book, ScriptedReviewer(), review_every_turns=1, idle_review_seconds=0)

    loop.record("chat:c", Turn(user="I prefer short answers.", assistant="Sure."))
    await _drain(loop)

    assert "MemoryTestAlpha" not in _book(tmp_path).render()


def test_an_edit_by_the_user_wins(tmp_path: Path) -> None:
    book = _book(tmp_path)
    book.apply(target="memory", operation="add", text="The test project is MemoryTestAlpha.")
    path = book.folder / "MEMORY.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("MemoryTestAlpha", "MemoryTestGamma"),
        encoding="utf-8",
    )
    book.invalidate()

    text = book.render()
    assert "MemoryTestGamma" in text
    assert "MemoryTestAlpha" not in text


async def test_an_arabic_request_is_kept_and_read_back(tmp_path: Path) -> None:
    book = _book(tmp_path)
    notebook_module.set_active(book)

    book.keep_explicit("مشروعي التجريبي اسمه MemoryTestAlpha")  # i18n-allow

    assert "مشروعي التجريبي اسمه MemoryTestAlpha" in snapshot_block()  # i18n-allow


# ── Arabic turns reach the reviewer ────────────────────────────────────────


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("اسمي أحمد وأنا مبرمج", True),  # i18n-allow
        ("مشروعي الجديد اسمه MemoryTestAlpha", True),  # i18n-allow
        ("من الآن جاوبني باختصار", True),  # i18n-allow
        ("كيف الطقس اليوم في المدينة", False),  # i18n-allow
    ],
)
def test_arabic_self_statements_are_a_review_signal(said: str, expected: bool) -> None:
    from jarvis.memory.learning.signals import has_signal

    assert has_signal(said) is expected


# ── Arabic explicit requests take the deterministic path ───────────────────


@pytest.mark.parametrize(
    "said",
    [
        "تذكر أن مشروعي التجريبي اسمه MemoryTestAlpha",  # i18n-allow
        "تذكّر أن مشروعي التجريبي اسمه MemoryTestAlpha",  # i18n-allow
        "احفظ أن مشروعي التجريبي اسمه MemoryTestAlpha",  # i18n-allow
        "افتكر أن مشروعي التجريبي اسمه MemoryTestAlpha",  # i18n-allow
        "بديك تتذكر إن مشروعي التجريبي اسمه MemoryTestAlpha",  # i18n-allow
        "بديك تتذكر أن مشروعي التجريبي اسمه MemoryTestAlpha",  # i18n-allow
        "لو سمحت، احفظ انو مشروعي التجريبي اسمه MemoryTestAlpha",  # i18n-allow
    ],
)
async def test_an_arabic_remember_request_is_kept_without_a_model(
    tmp_path: Path, said: str
) -> None:
    book = _book(tmp_path)
    notebook_module.set_active(book)
    reviewer = ScriptedReviewer()
    loop = JarvisLearningLoop(book, reviewer, review_every_turns=50, idle_review_seconds=0)

    loop.record("chat:c", Turn(user=said, assistant="تمام"))  # i18n-allow
    await _drain(loop)

    assert reviewer.calls == 0
    assert "MemoryTestAlpha" in snapshot_block()
    assert "MemoryTestAlpha" in (book.folder / "MEMORY.md").read_text(encoding="utf-8")
    assert "MemoryTestAlpha" in _book(tmp_path).render()  # after a restart


async def test_an_arabic_request_said_twice_is_kept_once(tmp_path: Path) -> None:
    book = _book(tmp_path)
    notebook_module.set_active(book)
    loop = JarvisLearningLoop(
        book, ScriptedReviewer(), review_every_turns=50, idle_review_seconds=0
    )
    said = "تذكر أن مشروعي التجريبي اسمه MemoryTestAlpha"  # i18n-allow

    loop.record("chat:c", Turn(user=said, assistant="تمام"))  # i18n-allow
    await _drain(loop)
    loop.record("chat:c", Turn(user=said, assistant="تمام"))  # i18n-allow
    await _drain(loop)

    memory = (book.folder / "MEMORY.md").read_text(encoding="utf-8")
    assert memory.count("MemoryTestAlpha") == 1


@pytest.mark.parametrize(
    "said",
    [
        "هل تتذكر أن مشروعي اسمه MemoryTestAlpha؟",  # i18n-allow
        "تذكرت أن عندي موعد اليوم",  # i18n-allow
        "كيف الطقس اليوم في المدينة",  # i18n-allow
        "ما بتذكر شو قلتلي امبارح",  # i18n-allow
        "احفظ الملف في المجلد",  # i18n-allow
    ],
)
def test_ordinary_arabic_is_not_a_remember_request(said: str) -> None:
    from jarvis.society.memory_intent import requested_memory

    assert not requested_memory(said)
