"""Semantic search reaches the watcher, the recall tool and the config file."""
from __future__ import annotations

import asyncio
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest

from dodaios.core.bus import EventBus
from dodaios.core.config import WikiContextConfig
from dodaios.core.config_writer import set_wiki_semantic_search
from dodaios.memory.wiki import semantic_search
from dodaios.memory.wiki.search import VaultSearch
from dodaios.memory.wiki.watcher import WikiWatcher
from dodaios.plugins.tool.wiki_recall import WikiRecallTool
from tests.fakes.fake_semantic_encoder import FakeSemanticEncoder


@pytest.fixture(autouse=True)
def _no_active_search() -> Iterator[None]:
    semantic_search.deactivate()
    yield
    semantic_search.deactivate()


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / "entities").mkdir(parents=True)
    return root


def _write(vault: Path, name: str, body: str) -> Path:
    path = vault / "entities" / name
    path.write_text(f"---\ntype: entity\n---\n{body}", encoding="utf-8")
    return path


def test_semantic_search_ships_switched_off() -> None:
    assert WikiContextConfig().semantic_search is False


def test_the_switch_is_written_as_one_key(tmp_path: Path) -> None:
    path = tmp_path / "jarvis.toml"
    path.write_text("[wiki_context]\nenabled = true\n", encoding="utf-8")

    set_wiki_semantic_search(True, path=path)

    block = tomllib.loads(path.read_text(encoding="utf-8"))["wiki_context"]
    assert block == {"enabled": True, "semantic_search": True}


def test_the_switch_rejects_anything_but_a_boolean(tmp_path: Path) -> None:
    path = tmp_path / "jarvis.toml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(TypeError):
        set_wiki_semantic_search("yes", path=path)  # type: ignore[arg-type]
    assert path.read_text(encoding="utf-8") == ""


def test_a_page_the_watcher_sees_change_is_searchable_by_meaning(
    vault: Path, tmp_path: Path
) -> None:
    db_path = tmp_path / "wiki.db"
    active = semantic_search.activate(vault, db_path=db_path, encoder=FakeSemanticEncoder())
    active.sync()
    watcher = WikiWatcher(vault, EventBus(), db_path=db_path)
    page = _write(vault, "anna.md", "# Anna\n\n- Meine Schwester\n- Geburtstag am 4. Mai\n")

    watcher._maintain_index(page, "modified", "entities/anna.md")
    assert [hit.title for hit in active.search("when is my sister's birthday")] == ["Anna"]

    page.unlink()
    watcher._maintain_index(page, "deleted", "entities/anna.md")
    assert active.search("when is my sister's birthday") == []


def test_the_watcher_leaves_a_search_for_another_vault_alone(
    vault: Path, tmp_path: Path
) -> None:
    encoder = FakeSemanticEncoder()
    semantic_search.activate(tmp_path / "other", db_path=tmp_path / "wiki.db", encoder=encoder)
    watcher = WikiWatcher(vault, EventBus(), db_path=tmp_path / "wiki.db")
    page = _write(vault, "anna.md", "# Anna\n\n- Meine Schwester\n")

    watcher._maintain_index(page, "modified", "entities/anna.md")

    assert encoder.calls == []


def test_the_watcher_works_unchanged_while_semantic_search_is_off(
    vault: Path, tmp_path: Path
) -> None:
    db_path = tmp_path / "wiki.db"
    watcher = WikiWatcher(vault, EventBus(), db_path=db_path)
    page = _write(vault, "anna.md", "# Anna\n\n- Meine Schwester\n")

    watcher._maintain_index(page, "modified", "entities/anna.md")

    assert [hit.title for hit in VaultSearch(vault, db_path=db_path).search("Schwester")] == [
        "Anna"
    ]


def test_the_recall_tool_adds_pages_found_by_meaning(vault: Path, tmp_path: Path) -> None:
    db_path = tmp_path / "wiki.db"
    _write(vault, "anna.md", "# Anna\n\n- Meine Schwester\n- Geburtstag am 4. Mai\n")
    tool = WikiRecallTool(VaultSearch(vault, db_path=db_path))
    query = {"query": "sister birthday"}

    before = asyncio.run(tool.execute(query, None))
    assert "No wiki matches" in before.output

    active = semantic_search.activate(vault, db_path=db_path, encoder=FakeSemanticEncoder())
    active.sync()

    after = asyncio.run(tool.execute(query, None))
    assert "**Anna**" in after.output
    assert "entities" in after.output
