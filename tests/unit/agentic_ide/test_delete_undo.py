"""The explorer's Undo for deletes: a kept copy goes back where it was."""

from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.agentic_ide import delete_undo
from dodaios.agentic_ide.file_editing import EditError


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "store"
    monkeypatch.setattr(delete_undo, "_store_root", lambda: folder)
    return folder


@pytest.fixture
def root(tmp_path: Path) -> Path:
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


def test_keep_and_restore_a_file(root: Path, store: Path) -> None:
    (root / "notes.md").write_text("draft", encoding="utf-8")
    token = delete_undo.keep(root, "notes.md")
    assert token
    (root / "notes.md").unlink()

    assert delete_undo.restore(root, token) == "notes.md"
    assert (root / "notes.md").read_text(encoding="utf-8") == "draft"
    assert not (store / token).exists()


def test_restore_refuses_to_overwrite(root: Path, store: Path) -> None:
    (root / "a.txt").write_text("old", encoding="utf-8")
    token = delete_undo.keep(root, "a.txt")
    assert token
    (root / "a.txt").write_text("new", encoding="utf-8")

    with pytest.raises(EditError):
        delete_undo.restore(root, token)
    assert (root / "a.txt").read_text(encoding="utf-8") == "new"


def test_restore_refuses_another_workspace(root: Path, tmp_path: Path, store: Path) -> None:
    (root / "a.txt").write_text("x", encoding="utf-8")
    token = delete_undo.keep(root, "a.txt")
    other = tmp_path / "other"
    other.mkdir()
    assert token
    with pytest.raises(EditError):
        delete_undo.restore(other, token)


def test_bad_tokens_are_refused(root: Path, store: Path) -> None:
    for token in ("../../etc", "zz", "0" * 24):
        with pytest.raises(EditError):
            delete_undo.restore(root, token)


def test_large_entries_are_not_kept(
    root: Path, store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(delete_undo, "MAX_UNDO_BYTES", 4)
    (root / "big.bin").write_bytes(b"0123456789")
    assert delete_undo.keep(root, "big.bin") is None
    monkeypatch.setattr(delete_undo, "MAX_UNDO_FILES", 2)
    (root / "many").mkdir()
    for index in range(5):
        (root / "many" / f"{index}.txt").write_text("", encoding="utf-8")
    assert delete_undo.keep(root, "many") is None


def test_only_the_newest_copies_are_held(
    root: Path, store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(delete_undo, "MAX_KEPT", 2)
    (root / "a.txt").write_text("x", encoding="utf-8")
    tokens = [delete_undo.keep(root, "a.txt") for _ in range(4)]
    assert all(tokens)
    assert len([entry for entry in store.iterdir() if entry.is_dir()]) == 2
