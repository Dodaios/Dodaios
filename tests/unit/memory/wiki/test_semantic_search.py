"""Semantic search finds pages by meaning and never gets in a caller's way."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from dodaios.memory.wiki import semantic_search
from dodaios.memory.wiki.search import SearchHit
from dodaios.memory.wiki.semantic_search import SemanticVaultSearch, with_semantic_hits
from tests.fakes.fake_semantic_encoder import FakeSemanticEncoder


def _page(vault: Path, rel: str, body: str) -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntype: entity\n---\n{body}", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _no_active_search() -> Iterator[None]:
    semantic_search.deactivate()
    yield
    semantic_search.deactivate()


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    _page(
        root,
        "entities/anna.md",
        "# Anna\n\n## Facts\n- Meine Schwester\n- Geburtstag am 4. Mai\n- Likes pizza\n",
    )
    _page(root, "concepts/trip.md", "# Trip\n\nThe flight to Paris leaves in the morning.\n")
    return root


@pytest.fixture()
def encoder() -> FakeSemanticEncoder:
    return FakeSemanticEncoder()


@pytest.fixture()
def search(vault: Path, tmp_path: Path, encoder: FakeSemanticEncoder) -> SemanticVaultSearch:
    instance = SemanticVaultSearch(vault, db_path=tmp_path / "wiki.db", encoder=encoder)
    instance.sync()
    return instance


def test_a_question_finds_the_note_written_in_another_language(
    search: SemanticVaultSearch, vault: Path
) -> None:
    hits = search.search("when is my sister's birthday")
    assert [hit.path for hit in hits] == [vault / "entities" / "anna.md"]
    assert hits[0].title == "Anna"
    assert hits[0].score > 0.5


def test_each_page_appears_once_with_its_best_passage(search: SemanticVaultSearch) -> None:
    hits = search.search("birthday of my sister, and pizza", k=5)
    assert [hit.title for hit in hits].count("Anna") == 1


def test_an_unrelated_question_returns_nothing(search: SemanticVaultSearch) -> None:
    assert search.search("how tall is the Eiffel tower") == []


def test_blank_queries_touch_neither_disk_nor_model(
    search: SemanticVaultSearch, encoder: FakeSemanticEncoder
) -> None:
    before = len(encoder.calls)
    assert search.search("   ") == []
    assert len(encoder.calls) == before


def test_the_turn_path_does_not_read_the_vectors_from_disk(
    vault: Path, tmp_path: Path, encoder: FakeSemanticEncoder
) -> None:
    SemanticVaultSearch(vault, db_path=tmp_path / "wiki.db", encoder=encoder).sync()
    fresh = SemanticVaultSearch(vault, db_path=tmp_path / "wiki.db", encoder=encoder)

    assert fresh.search("sister birthday") == [], "not loaded yet, and it must not wait"

    fresh.warm_up()
    assert [hit.title for hit in fresh.search("sister birthday")] == ["Anna"]
    assert encoder.warmed == 1


def test_a_busy_model_costs_the_turn_only_its_semantic_hits(
    search: SemanticVaultSearch, encoder: FakeSemanticEncoder
) -> None:
    encoder.busy = True
    assert search.search("sister birthday") == []
    assert [hit.title for hit in search.search("sister birthday", wait=True)] == ["Anna"]


def test_a_broken_model_is_no_hits_not_an_error(vault: Path, tmp_path: Path) -> None:
    class Broken(FakeSemanticEncoder):
        def encode(self, texts, *, wait=True):  # type: ignore[no-untyped-def]
            if len(self.calls) >= 1:
                raise RuntimeError("native session died")
            return super().encode(texts, wait=wait)

    broken = Broken()
    instance = SemanticVaultSearch(vault, db_path=tmp_path / "wiki.db", encoder=broken)
    # The first page encodes, the second fails; the run goes on and counts it.
    result = instance.sync()
    assert (result.encoded, result.failed) == (1, 1)
    assert instance.search("sister birthday") == []


def test_a_page_update_does_not_wait_for_a_whole_sync(
    vault: Path, tmp_path: Path, encoder: FakeSemanticEncoder
) -> None:
    """The write lock is per page, so the watcher gets in between two pages."""
    instance = SemanticVaultSearch(vault, db_path=tmp_path / "wiki.db", encoder=encoder)
    seen_free: list[bool] = []

    def progress(_done: int, _total: int) -> None:
        free = instance._write_lock.acquire(blocking=False)
        seen_free.append(free)
        if free:
            instance._write_lock.release()

    instance.sync(progress=progress)

    assert seen_free == [True, True]


def test_a_sync_that_is_told_to_stop_ends_at_the_next_page(
    vault: Path, tmp_path: Path, encoder: FakeSemanticEncoder
) -> None:
    class Stop(Exception):
        pass

    def progress(_done: int, _total: int) -> None:
        raise Stop

    instance = SemanticVaultSearch(vault, db_path=tmp_path / "wiki.db", encoder=encoder)
    with pytest.raises(Stop):
        instance.sync(progress=progress)

    assert instance.counts()[0] == 1, "one page was written whole, the rest not at all"


def test_a_page_update_patches_memory_without_reloading_the_vault(
    search: SemanticVaultSearch, vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dodaios.memory.wiki import semantic_index

    reads: list[str | None] = []
    real = semantic_index.load_passages

    def spy(conn, *, path=None):  # type: ignore[no-untyped-def]
        reads.append(path)
        return real(conn, path=path)

    monkeypatch.setattr(semantic_index, "load_passages", spy)
    page = _page(vault, "concepts/meal.md", "# Meal\n\nPizza is the favourite food.\n")

    search.index_page(page)

    assert reads == ["concepts/meal.md"], "only the changed page is read back"
    assert search.counts() == (3, 5)
    assert "Meal" in [hit.title for hit in search.search("what do I like to eat")]


def test_a_changed_page_is_searchable_at_once(
    search: SemanticVaultSearch, vault: Path
) -> None:
    page = _page(vault, "concepts/meal.md", "# Meal\n\nPizza is the favourite food.\n")
    search.index_page(page)
    assert "Meal" in [hit.title for hit in search.search("what do I like to eat")]

    search.remove_page(page)
    assert "Meal" not in [hit.title for hit in search.search("what do I like to eat")]


def test_counts_report_pages_and_passages(search: SemanticVaultSearch) -> None:
    assert search.counts() == (2, 4)


def test_one_instance_is_active_per_vault(
    vault: Path, tmp_path: Path, encoder: FakeSemanticEncoder
) -> None:
    assert semantic_search.get_active() is None
    first = semantic_search.activate(vault, db_path=tmp_path / "wiki.db", encoder=encoder)
    assert semantic_search.activate(vault, db_path=tmp_path / "wiki.db") is first

    other = semantic_search.activate(
        tmp_path / "other", db_path=tmp_path / "wiki.db", encoder=FakeSemanticEncoder()
    )
    assert other is not first
    assert encoder.closed == 1, "the previous vault's model is released"

    semantic_search.deactivate()
    assert semantic_search.get_active() is None


def test_semantic_hits_are_appended_to_the_word_search_result(
    vault: Path, tmp_path: Path, encoder: FakeSemanticEncoder
) -> None:
    active = semantic_search.activate(vault, db_path=tmp_path / "wiki.db", encoder=encoder)
    active.sync()
    by_words = [SearchHit(title="Trip", path=vault / "concepts" / "trip.md", snippet="", score=0.9)]

    merged = with_semantic_hits(by_words, "sister birthday and the flight", vault_root=vault)

    assert [hit.title for hit in merged] == ["Trip", "Anna"], "word hits first, no duplicate"


def test_the_word_search_result_is_untouched_while_semantic_search_is_off(
    vault: Path, tmp_path: Path, encoder: FakeSemanticEncoder
) -> None:
    by_words = [SearchHit(title="Trip", path=vault / "concepts" / "trip.md", snippet="", score=0.9)]
    assert with_semantic_hits(by_words, "sister birthday", vault_root=vault) is by_words

    semantic_search.activate(tmp_path / "other", db_path=tmp_path / "wiki.db", encoder=encoder)
    assert with_semantic_hits(by_words, "sister birthday", vault_root=vault) is by_words
