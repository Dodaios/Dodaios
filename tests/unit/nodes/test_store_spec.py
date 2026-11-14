"""The person's saves from a type editor (``NodeStore.save_spec``): validated
by the type, refused when made from an older version, and kept as one
history version per stretch of editing."""

from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.nodes.model import HISTORY_DIR
from dodaios.nodes.store import (
    SAVE_COALESCE_SECONDS,
    SAVE_STRETCH_SECONDS,
    NodeStore,
    SpecConflict,
)
from dodaios.nodes.types import NodeError

T0 = 1_731_500_000.0
DOC = {"markdown": "# Plan\n\nFirst draft."}


@pytest.fixture
def store(tmp_path: Path) -> NodeStore:
    return NodeStore(root=tmp_path)


def _doc(store: NodeStore) -> str:
    return store.create(type="docs", title="Plan", spec=DOC, now=T0).id


def _history(store: NodeStore, node_id: str) -> list[str]:
    run_dir = store.dir_of(node_id)
    assert run_dir is not None
    folder = run_dir / HISTORY_DIR
    return sorted(entry.name for entry in folder.iterdir()) if folder.is_dir() else []


def _markdown(text: str) -> dict[str, str]:
    return {"markdown": f"# Plan\n\n{text}"}


def test_a_save_from_the_version_it_was_made_from_is_written_and_drawn(store: NodeStore) -> None:
    node_id = _doc(store)
    saved = store.save_spec(node_id, _markdown("Second draft."), base_version=1, now=T0 + 5)
    assert saved.version == 2 and saved.updated_at == T0 + 5
    assert "Second draft." in saved.spec["markdown"]
    run_dir = store.dir_of(node_id)
    assert run_dir is not None
    assert "Second draft." in (run_dir / saved.page_path).read_text(encoding="utf-8")
    assert store.get(node_id).spec == saved.spec  # type: ignore[union-attr]


def test_the_saved_spec_is_what_the_type_kept(store: NodeStore) -> None:
    node_id = _doc(store)
    saved = store.save_spec(
        node_id, {"markdown": "# Plan\n\nText.", "unknown": 1}, base_version=1, now=T0 + 1
    )
    assert "unknown" not in saved.spec


def test_a_save_made_from_an_older_version_is_refused_with_the_current_node(
    store: NodeStore,
) -> None:
    node_id = _doc(store)
    store.update(node_id, spec=_markdown("The assistant's version."), now=T0 + 2)
    with pytest.raises(SpecConflict) as raised:
        store.save_spec(node_id, _markdown("Mine."), base_version=1, now=T0 + 3)
    assert isinstance(raised.value, NodeError)
    assert raised.value.node.version == 2
    assert "The assistant's version." in raised.value.node.spec["markdown"]
    # Nothing was written.
    assert "The assistant's version." in store.get(node_id).spec["markdown"]  # type: ignore[union-attr]


def test_no_base_version_saves_over_whatever_the_node_holds(store: NodeStore) -> None:
    node_id = _doc(store)
    store.update(node_id, spec=_markdown("Theirs."), now=T0 + 2)
    saved = store.save_spec(node_id, _markdown("Mine."), base_version=None, now=T0 + 3)
    assert saved.version == 3 and "Mine." in saved.spec["markdown"]


def test_a_spec_the_type_refuses_is_a_node_error_and_changes_nothing(store: NodeStore) -> None:
    node_id = _doc(store)
    with pytest.raises(NodeError):
        store.save_spec(node_id, {"markdown": 5}, base_version=1)
    with pytest.raises(NodeError):
        store.save_spec(node_id, "not an object", base_version=1)
    assert store.get(node_id).version == 1  # type: ignore[union-attr]


def test_a_whiteboard_and_an_unknown_node_are_refused(store: NodeStore) -> None:
    board = store.create(type="whiteboard", title="Board", now=T0).id
    with pytest.raises(NodeError, match="scene"):
        store.save_spec(board, {"elements": []}, base_version=1)
    with pytest.raises(NodeError, match="No node"):
        store.save_spec("0123456789ab", DOC, base_version=None)


def test_a_save_that_changes_nothing_keeps_the_version(store: NodeStore) -> None:
    node_id = _doc(store)
    same = store.save_spec(node_id, store.get(node_id).spec, base_version=1, now=T0 + 9)  # type: ignore[union-attr]
    assert same.version == 1 and same.updated_at == T0
    assert _history(store, node_id) == []


def test_saves_of_one_stretch_share_one_history_version(store: NodeStore) -> None:
    node_id = _doc(store)
    original = store.get(node_id).spec  # type: ignore[union-attr]
    version = 1
    for step in range(5):
        version = store.save_spec(
            node_id, _markdown(f"Draft {step}."), base_version=version, now=T0 + 10 * (step + 1)
        ).version
    assert version == 6
    # Only the version before the stretch is kept: one undo goes back to it.
    assert _history(store, node_id) == ["v1.json"]
    assert store.revert(node_id, now=T0 + 100).spec == original


def test_a_pause_or_a_long_stretch_starts_a_new_history_version(store: NodeStore) -> None:
    node_id = _doc(store)
    first = store.save_spec(node_id, _markdown("A."), base_version=1, now=T0 + 1)
    paused = store.save_spec(
        node_id, _markdown("B."), base_version=first.version, now=T0 + 1 + SAVE_COALESCE_SECONDS + 1
    )
    assert _history(store, node_id) == ["v1.json", "v2.json"]
    # A stretch of saves close together still ends after SAVE_STRETCH_SECONDS.
    at, version = T0 + 1 + SAVE_COALESCE_SECONDS + 1, paused.version
    while at < T0 + SAVE_COALESCE_SECONDS + SAVE_STRETCH_SECONDS + 600:
        at += SAVE_COALESCE_SECONDS / 2
        version = store.save_spec(
            node_id, _markdown(f"Edit {version}."), base_version=version, now=at
        ).version
    assert len(_history(store, node_id)) == 3


def test_the_assistants_revision_ends_the_stretch(store: NodeStore) -> None:
    node_id = _doc(store)
    saved = store.save_spec(node_id, _markdown("Mine."), base_version=1, now=T0 + 1)
    revised = store.update(node_id, spec=_markdown("Theirs."), now=T0 + 2)
    assert "last_save" not in revised.extra
    store.save_spec(node_id, _markdown("Mine again."), base_version=revised.version, now=T0 + 3)
    assert _history(store, node_id) == [
        "v1.json",
        f"v{saved.version}.json",
        f"v{revised.version}.json",
    ]


def test_a_preview_draws_the_spec_without_saving_it(store: NodeStore) -> None:
    node_id = _doc(store)
    page = store.preview(node_id, _markdown("Not saved yet."))
    assert page.lstrip().lower().startswith("<!doctype html") and "Not saved yet." in page
    node = store.get(node_id)
    assert node is not None and node.version == 1 and "Not saved yet." not in node.spec["markdown"]
    with pytest.raises(NodeError):
        store.preview(node_id, {"markdown": 5})
