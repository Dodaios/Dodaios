"""Notes the assistant wrote for itself: in the registry, hidden "as shipped", undoable."""

from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.store import MemoryVault
from dodaios.rsi import adopt, overlay, overview, params
from dodaios.rsi import night as nights
from dodaios.rsi.bench.store import BenchStore
from dodaios.self_change import SelfChangeRegistry, State, Surface
from dodaios.self_change.wiring import _revert_lesson

HOW_TO = "The calendar tool needs the date as 2026-03-14, not as 14 March."
OTHER = "The mail search works with from: and not with sender: in the query."
CORRECTION = "Do not put meetings before ten in the morning."


@pytest.fixture
def home(tmp_path: Path):
    vault = MemoryVault(tmp_path / "vault.db")
    for text in (HOW_TO, OTHER):
        vault.remember(
            text,
            "procedural",
            origin="inferred",
            source={"note": "how_to", "trigger": "calling a tool that failed before"},
        )
    # The person's own correction is an instruction, not something the assistant chose.
    vault.remember(
        CORRECTION, "procedural", origin="inferred", source={"note": "lesson", "trigger": "x"}
    )
    for i in range(12):
        vault.remember(f"Trip number {i} went to the coast in spring.", "episode")
    registry = SelfChangeRegistry(tmp_path)
    registry.register_reverter(adopt.PREFIX, _revert_lesson)
    vault_runtime.set_active(vault)
    yield tmp_path, vault, registry
    vault_runtime.set_active(None)
    registry.close()
    params.install(None)


def _ids(vault: MemoryVault, *texts: str) -> frozenset[str]:
    return frozenset(m.id for m in vault.list() if m.text in texts)


def test_how_to_notes_get_an_entry_and_the_persons_corrections_do_not(home) -> None:
    path, vault, registry = home
    assert adopt.how_tos(registry, vault) == {"adopted": 2, "closed": 0}
    assert adopt.how_tos(registry, vault) == {"adopted": 0, "closed": 0}  # once
    learned = registry.learned()
    assert {c.surface for c in learned} == {Surface.LESSON}
    assert {c.state for c in learned} == {State.LIVE} and {c.author for c in learned} == {
        adopt.AUTHOR
    }
    assert adopt.memory_ids(registry) == _ids(vault, HOW_TO, OTHER)
    registry.close()
    # The registry holds the memory's id and none of its words.
    stored = (path / "self_changes.db").read_bytes()
    assert b"calendar tool" not in stored and b"mail search" not in stored


def test_a_run_of_the_assistant_as_it_ships_does_not_see_them(home) -> None:
    _, vault, registry = home
    adopt.how_tos(registry, vault)
    hidden = adopt.memory_ids(registry)
    query = "which date does the calendar tool need"
    live = vault_runtime.recall_for(vault, query)
    assert any(m.text == HOW_TO for m in live.chosen) or live.shows(next(iter(_ids(vault, HOW_TO))))
    with overlay.active(overlay.Overlay(label="factory", factory=True, hidden_memories=hidden)):
        shipped = vault_runtime.recall_for(vault, query)
        assert overlay.hidden_memories() == hidden
        assert not any(shipped.shows(memory_id) for memory_id in hidden)
        assert not hidden & vault_runtime.in_mind_ids(vault)
    assert overlay.hidden_memories() == frozenset()
    # The person's correction is the same on both sides.
    (correction,) = _ids(vault, CORRECTION)
    assert correction not in hidden


def test_taking_one_back_ends_the_note_in_the_memory(home) -> None:
    _, vault, registry = home
    adopt.how_tos(registry, vault)
    change = next(c for c in registry.learned() if adopt.memory_id(c) in _ids(vault, HOW_TO))
    registry.rollback(change.id)
    assert registry.store.get(change.id).state is State.REVERTED
    assert HOW_TO not in [m.text for m in vault.list()]
    assert OTHER in [m.text for m in vault.list()]  # only that one
    assert adopt.memory_ids(registry) == _ids(vault, OTHER)
    assert adopt.how_tos(registry, vault) == {"adopted": 0, "closed": 0}


def test_a_note_the_person_forgot_leaves_nothing_behind(home) -> None:
    _, vault, registry = home
    adopt.how_tos(registry, vault)
    (gone,) = _ids(vault, OTHER)
    vault.forget(gone)
    assert adopt.how_tos(registry, vault) == {"adopted": 0, "closed": 1}
    change = next(c for c in registry.store.list() if adopt.memory_id(c) == gone)
    assert change.state is State.REVERTED and "gone from the memory" in change.note
    assert gone not in adopt.memory_ids(registry)


def test_the_page_shows_a_notes_words_from_the_memory_and_nothing_once_it_is_gone(home) -> None:
    path, vault, registry = home
    adopt.how_tos(registry, vault)
    night = nights.Night(registry, BenchStore(path / "bench.db"), lambda: {})
    try:
        stack = overview.build(night)["stack"]
        assert {row["text"] for row in stack} == {HOW_TO, OTHER}
        assert all(row["surface"] == "lesson" and row["measured"] is False for row in stack)
        assert all(row["admitted"] is None and row["before"] is None for row in stack)
        (gone,) = _ids(vault, HOW_TO)
        vault.forget(gone)
        texts = [row["text"] for row in overview.build(night)["stack"]]
        assert sorted(texts) == ["", OTHER]  # until the next night closes the entry
    finally:
        night.bench.close()


def test_the_measured_advantage_counts_the_notes_as_learned(home, monkeypatch) -> None:
    path, vault, registry = home
    adopt.how_tos(registry, vault)
    seen: list[overlay.Overlay] = []
    from dodaios.rsi.bench import run

    real = run.measure

    def spy(tasks, running, worlds, **more):
        seen.append(running)
        return real(tasks, running, worlds, **more)

    monkeypatch.setattr(run, "measure", spy)
    from tests.unit.rsi import fakeworld

    box = fakeworld.sandbox(path / "box", monkeypatch, learners=())
    try:
        night = nights.Night(
            registry, box.bench, lambda: {fakeworld.WORLD: object()}, sources=box.night.sources,
            learners=(),
        )
        night.run()
        factory = next(o for o in seen if o.factory)
        assert factory.hidden_memories == adopt.memory_ids(registry) != frozenset()
        assert all(not o.hidden_memories for o in seen if not o.factory)
    finally:
        box.close()
