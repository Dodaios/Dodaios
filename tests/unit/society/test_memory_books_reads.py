"""Reading an agent's notebooks never creates them.

Every agent the roster ever listed used to get two frontmatter-only files the
first time anything read its memory, which left 170 empty pages in one vault.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dodaios.society.memory_books import edit_book, has_books, read_books


def _agent(agent_id: str = "vega") -> SimpleNamespace:
    return SimpleNamespace(agent_id=agent_id, name="Vega")


def test_reading_an_agent_without_notebooks_writes_nothing(tmp_path: Path) -> None:
    agent = _agent()
    assert read_books(tmp_path, agent) == {"memory": [], "user": []}
    assert not (tmp_path / "society").exists()
    assert not has_books(tmp_path, agent)


def test_the_first_write_creates_the_notebooks_and_reads_find_it(tmp_path: Path) -> None:
    agent = _agent()
    edit_book(tmp_path, agent, "Deploys run on Fridays.", target="memory")
    assert has_books(tmp_path, agent)
    books = read_books(tmp_path, agent)
    assert [entry.text for entry in books["memory"]] == ["Deploys run on Fridays."]
