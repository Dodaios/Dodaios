"""The semantic index encodes each page once and follows the vault on disk."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from dodaios.memory.wiki import semantic_index
from tests.fakes.fake_semantic_encoder import FakeSemanticEncoder


def _page(vault: Path, rel: str, body: str) -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntype: entity\n---\n{body}", encoding="utf-8")
    return path


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    facts = "- Sister of the user\n- Birthday on 4 May\n"
    _page(root, "entities/anna.md", f"# Anna\n\n## Facts\n{facts}")
    _page(root, "concepts/food.md", "# Food\n\nPizza with mushrooms is the favourite meal.\n")
    return root


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(tmp_path / "wiki.db"))
    yield connection
    connection.close()


def test_a_list_page_becomes_one_passage_per_fact() -> None:
    cut = semantic_index.passages("Anna", "# Anna\n\n## Facts\n- Sister of the user\n- Born 1961\n")
    assert [text for text, _encoded in cut] == ["Sister of the user", "Born 1961"]
    # The encoded text carries the page and the heading the fact stands under.
    assert cut[1][1] == "Anna: Facts: Born 1961"


def test_markup_is_reduced_to_the_words_a_reader_sees() -> None:
    body = "Works with [[projects/apollo|Apollo]] and **likes** `tea`, see [notes](http://x.test)."
    [(text, _encoded)] = semantic_index.passages("Page", body)
    assert text == "Works with Apollo and likes tea, see notes."


def test_code_blocks_and_stray_marks_are_not_passages() -> None:
    body = "Real sentence about the project.\n\n```\nprint('x')\n```\n\n- ok\n"
    assert [text for text, _ in semantic_index.passages("Page", body)] == [
        "Real sentence about the project."
    ]


def test_a_long_paragraph_is_cut_so_no_part_is_ignored() -> None:
    sentence = "This sentence describes one detail of the plan in plain words. "
    cut = semantic_index.passages("Plan", sentence * 30)
    assert len(cut) > 1
    assert all(len(text) <= 480 for text, _ in cut)
    assert "".join(text for text, _ in cut).count("detail") == 30


def test_sync_encodes_every_page_once(vault: Path, conn: sqlite3.Connection) -> None:
    encoder = FakeSemanticEncoder()
    first = semantic_index.sync_vault(conn, vault, encoder=encoder)
    assert (first.pages, first.encoded, first.removed) == (2, 2, 0)
    assert semantic_index.counts(conn) == (2, 3)

    encoded_before = encoder.texts_encoded
    second = semantic_index.sync_vault(conn, vault, encoder=encoder)
    assert (second.pages, second.encoded) == (2, 0)
    assert encoder.texts_encoded == encoded_before, "an unchanged vault costs no inference"


def test_sync_re_encodes_only_the_page_that_changed(vault: Path, conn: sqlite3.Connection) -> None:
    encoder = FakeSemanticEncoder()
    semantic_index.sync_vault(conn, vault, encoder=encoder)
    changed = _page(vault, "concepts/food.md", "# Food\n\nNow the favourite meal is soup.\n")
    later = changed.stat().st_mtime + 5
    os.utime(changed, (later, later))

    result = semantic_index.sync_vault(conn, vault, encoder=encoder)

    assert result.encoded == 1
    assert encoder.calls[-1] == ["Food: Now the favourite meal is soup."]


def test_sync_drops_pages_that_are_gone(vault: Path, conn: sqlite3.Connection) -> None:
    encoder = FakeSemanticEncoder()
    semantic_index.sync_vault(conn, vault, encoder=encoder)
    (vault / "entities" / "anna.md").unlink()

    result = semantic_index.sync_vault(conn, vault, encoder=encoder)

    assert result.removed == 1
    _matrix, rows = semantic_index.load_passages(conn)
    assert {path for path, _title, _text in rows} == {"concepts/food.md"}


def test_sync_against_another_vault_leaves_no_row_of_the_old_one(
    vault: Path, conn: sqlite3.Connection, tmp_path: Path
) -> None:
    encoder = FakeSemanticEncoder()
    semantic_index.sync_vault(conn, vault, encoder=encoder)
    other = tmp_path / "other"
    _page(other, "notes/trip.md", "# Trip\n\nThe flight to Paris leaves in the morning.\n")

    semantic_index.sync_vault(conn, other, encoder=encoder)

    _matrix, rows = semantic_index.load_passages(conn)
    assert {path for path, _title, _text in rows} == {"notes/trip.md"}


def test_rows_of_the_old_vault_are_gone_before_anything_is_encoded(
    vault: Path, conn: sqlite3.Connection, tmp_path: Path
) -> None:
    semantic_index.sync_vault(conn, vault, encoder=FakeSemanticEncoder())
    other = tmp_path / "other"
    _page(other, "notes/trip.md", "# Trip\n\nThe flight to Paris leaves in the morning.\n")

    stale, pages, removed = semantic_index.plan_sync(conn, other)

    assert (stale, pages, removed) == (["notes/trip.md"], 1, 2)
    assert semantic_index.counts(conn) == (0, 0), "no search can mix the two vaults"


def test_one_page_that_cannot_be_encoded_does_not_end_the_run(
    vault: Path, conn: sqlite3.Connection
) -> None:
    class Flaky(FakeSemanticEncoder):
        def encode(self, texts, *, wait=True):  # type: ignore[no-untyped-def]
            if any("Pizza" in text for text in texts):
                raise RuntimeError("inference failed")
            return super().encode(texts, wait=wait)

    result = semantic_index.sync_vault(conn, vault, encoder=Flaky())

    assert (result.encoded, result.failed) == (1, 1)
    _matrix, rows = semantic_index.load_passages(conn)
    assert {path for path, _title, _text in rows} == {"entities/anna.md"}


def test_one_page_can_be_read_back_on_its_own(vault: Path, conn: sqlite3.Connection) -> None:
    semantic_index.sync_vault(conn, vault, encoder=FakeSemanticEncoder())
    matrix, rows = semantic_index.load_passages(conn, path="entities/anna.md")
    assert matrix.shape == (2, 384)
    assert {path for path, _title, _text in rows} == {"entities/anna.md"}


def test_stored_vectors_come_back_as_one_matrix(vault: Path, conn: sqlite3.Connection) -> None:
    semantic_index.sync_vault(conn, vault, encoder=FakeSemanticEncoder())
    matrix, rows = semantic_index.load_passages(conn)
    assert matrix.shape == (3, 384)
    assert [title for _path, title, _text in rows] == ["Food", "Anna", "Anna"]


def test_remove_page_forgets_its_passages(vault: Path, conn: sqlite3.Connection) -> None:
    semantic_index.sync_vault(conn, vault, encoder=FakeSemanticEncoder())
    semantic_index.remove_page(conn, vault, vault / "entities" / "anna.md")
    assert semantic_index.counts(conn) == (1, 1)
