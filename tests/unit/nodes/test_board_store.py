"""Whiteboard nodes on disk: the person's saves, the merge with the assistant's
edits, pictures, and the older grammar converted when a node is read."""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
import types
from pathlib import Path
from typing import Any

import pytest

from dodaios.nodes.board import files as board_files
from dodaios.nodes.board.scene import MAX_SCENE_BYTES, empty_scene
from dodaios.nodes.model import HISTORY_DIR, STATE_FILE
from dodaios.nodes.store import SAVE_COALESCE_SECONDS, SAVE_STRETCH_SECONDS, NodeStore
from dodaios.nodes.types import MAX_SPEC_BYTES, NodeError

T0 = 1_731_500_000.0
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcff9f010005fe02fea7d6a4b90000000049454e44ae426082"
)
PNG_URL = "data:image/png;base64," + base64.b64encode(PNG).decode()


def _el(ident: str, kind: str = "rectangle", **fields: Any) -> dict[str, Any]:
    return {"id": ident, "type": kind, "x": 0, "y": 0, "width": 100, "height": 50, **fields}


def _scene(*elements: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"format": "scene", "elements": list(elements), **extra}


@pytest.fixture
def store(tmp_path: Path) -> NodeStore:
    return NodeStore(root=tmp_path)


@pytest.fixture
def board(store: NodeStore) -> str:
    return store.create(type="whiteboard", title="Board", now=T0).id


def _history(store: NodeStore, node_id: str) -> list[str]:
    run_dir = store.dir_of(node_id)
    assert run_dir is not None
    folder = run_dir / HISTORY_DIR
    return sorted(entry.name for entry in folder.iterdir()) if folder.is_dir() else []


def test_a_new_whiteboard_is_an_empty_scene(store: NodeStore, board: str) -> None:
    node, scene = store.scene_of(board)
    assert scene == empty_scene() == node.spec


def test_the_persons_saves_share_one_history_version_while_they_draw(
    store: NodeStore, board: str
) -> None:
    first = store.save_scene(board, _scene(_el("a", version=1)), now=T0 + 10)
    second = store.save_scene(board, _scene(_el("a", version=2, x=5)), now=T0 + 70)
    third = store.save_scene(board, _scene(_el("a", version=3, x=9)), now=T0 + 130)
    assert (first.version, second.version, third.version) == (2, 3, 4)
    assert _history(store, board) == ["v1.json"]  # only the board before the first save
    assert third.extra["last_save"] == {"by": "person", "at": T0 + 130, "since": T0 + 10}
    # A pause longer than the window starts a new stretch.
    later = store.save_scene(
        board, _scene(_el("a", version=4, x=1)), now=T0 + 130 + SAVE_COALESCE_SECONDS + 1
    )
    assert later.version == 5 and _history(store, board) == ["v1.json", "v4.json"]


def test_a_long_stretch_of_drawing_still_keeps_a_version_every_hour(
    store: NodeStore, board: str
) -> None:
    at, version = T0, 1
    while at < T0 + SAVE_STRETCH_SECONDS + 300:
        at += 300
        version += 1
        store.save_scene(board, _scene(_el("a", version=version, x=version)), now=at)
    assert len(_history(store, board)) == 2


def test_any_other_revision_ends_the_stretch(store: NodeStore, board: str) -> None:
    store.save_scene(board, _scene(_el("a")), now=T0 + 10)
    revised = store.update(board, spec=_scene(_el("a", version=2), _el("b")), now=T0 + 20)
    assert "last_save" not in revised.extra
    store.save_scene(board, _scene(_el("a", version=3)), now=T0 + 30)
    assert _history(store, board) == ["v1.json", "v2.json", "v3.json"]


def test_a_save_that_changes_nothing_writes_nothing(store: NodeStore, board: str) -> None:
    saved = store.save_scene(board, _scene(_el("a")), now=T0 + 10)
    again = store.save_scene(board, _scene(_el("a")), now=T0 + 20)
    assert again.version == saved.version and again.updated_at == T0 + 10


def test_only_a_whiteboard_takes_a_scene(store: NodeStore) -> None:
    sheet = store.create(type="sheets", title="Sheet", now=T0)
    with pytest.raises(NodeError, match="not a whiteboard"):
        store.save_scene(sheet.id, _scene())
    with pytest.raises(NodeError, match="not a whiteboard"):
        store.put_file(sheet.id, PNG_URL)
    with pytest.raises(NodeError, match="No node"):
        store.save_scene("0123456789ab", _scene())


def test_merge_save_keeps_what_the_assistant_drew_meanwhile(store: NodeStore, board: str) -> None:
    store.save_scene(board, _scene(_el("a", x=1)), now=T0 + 10)
    # The assistant adds b and moves a (version 2) while the editor still holds a at version 1.
    store.update(board, spec=_scene(_el("a", x=50, version=2), _el("b", x=200)), now=T0 + 20)
    node, merged = store.merge_save_scene(
        board, _scene(_el("a", x=1), _el("c", x=400)), now=T0 + 30
    )
    assert merged
    assert {element["id"]: element["x"] for element in node.spec["elements"]} == {
        "a": 50,
        "c": 400,
        "b": 200,
    }
    # Now the editor is current: its next save needs no answer.
    _, merged = store.merge_save_scene(board, node.spec, now=T0 + 40)
    assert not merged


def test_a_whiteboard_spec_may_be_larger_than_other_types(store: NodeStore, board: str) -> None:
    strokes = [_el(f"f{n}", "freedraw", points=[[i, i] for i in range(2_000)]) for n in range(40)]
    big = _scene(*strokes)
    assert MAX_SPEC_BYTES < len(json.dumps(big)) < MAX_SCENE_BYTES
    assert store.save_scene(board, big, now=T0 + 1).version == 2


def test_pictures_are_kept_read_and_copied_with_a_duplicate(store: NodeStore, board: str) -> None:
    file_id, mime = store.put_file(board, PNG_URL)
    assert mime == "image/png" and store.read_file(board, file_id) == (PNG, "image/png")
    assert store.read_file(board, "missing") is None
    scene = _scene(
        _el("i", "image", fileId=file_id),
        files={file_id: {"id": file_id, "mimeType": "image/png", "created": 1}},
    )
    store.save_scene(board, scene, now=T0 + 5)
    run_dir = store.dir_of(board)
    assert run_dir is not None
    page = next((run_dir / "tasks" / "node" / "artifacts" / "files").glob("*.html"))
    assert "data:image/png;base64," in page.read_text(encoding="utf-8")
    copy = store.duplicate(board, title="Copy")
    assert store.read_file(copy.id, file_id) == (PNG, "image/png")
    copy_dir = store.dir_of(copy.id)
    assert copy_dir is not None
    copy_page = next((copy_dir / "tasks" / "node" / "artifacts" / "files").glob("*.html"))
    assert "data:image/png;base64," in copy_page.read_text(encoding="utf-8")


def test_pictures_named_by_a_kept_version_survive_a_prune(
    store: NodeStore, board: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    gif = b"GIF89a" + b"\x00" * 40
    jpeg = b"\xff\xd8\xff" + b"\x00" * 40
    in_history = store.put_file(board, PNG_URL)[0]
    unnamed = store.put_file(board, "data:image/gif;base64," + base64.b64encode(gif).decode())[0]
    store.save_scene(board, _scene(_el("i", "image", fileId=in_history)), now=T0 + 5)
    store.update(board, spec=_scene(_el("r")), now=T0 + 10)  # the picture is only in history now
    run_dir = store.dir_of(board)
    assert run_dir is not None
    old = T0 - board_files.PRUNE_GRACE_SECONDS
    for entry in (run_dir / board_files.FILES_DIR).iterdir():
        os.utime(entry, (old, old))
    monkeypatch.setattr(board_files, "MAX_BOARD_BYTES", len(PNG) + len(gif) + 10)
    new = store.put_file(board, "data:image/jpeg;base64," + base64.b64encode(jpeg).decode())[0]
    assert store.read_file(board, in_history) is not None
    assert store.read_file(board, unnamed) is None
    assert store.read_file(board, new) is not None


def test_concurrent_saves_are_serialised(store: NodeStore, board: str) -> None:
    errors: list[BaseException] = []

    def save(n: int) -> None:
        try:
            for step in range(5):
                store.merge_save_scene(
                    board, _scene(_el(f"t{n}", version=step + 1, x=step)), now=T0 + n + step
                )
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=save, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    node, _ = store.scene_of(board)
    assert sorted(element["id"] for element in node.spec["elements"]) == ["t0", "t1", "t2", "t3"]


# ------------------------------------------------------------ the older grammar


@pytest.fixture
def fake_convert(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """A stand-in converter that keeps each picture through ``store_image``."""
    kept: list[Any] = []

    def legacy_to_scene(spec: Any, *, store_image: Any = None) -> dict[str, Any]:
        if not isinstance(spec, dict) or not spec.get("items"):
            raise NodeError('A whiteboard needs "items".')
        elements: list[dict[str, Any]] = []
        files: dict[str, Any] = {}
        for index, item in enumerate(spec["items"]):
            if item.get("image") and store_image is not None:
                stored = store_image(item["image"])
                kept.append(stored)
                if stored is not None:
                    file_id, mime = stored
                    files[file_id] = {"id": file_id, "mimeType": mime, "created": 1}
                    elements.append(_el(f"i{index}", "image", fileId=file_id))
                    continue
            elements.append(_el(f"n{index}", "text", text=str(item.get("text", ""))))
        return {"format": "scene", "elements": elements, "files": files}

    module = types.ModuleType("dodaios.nodes.board.convert")
    module.legacy_to_scene = legacy_to_scene  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dodaios.nodes.board.convert", module)
    return kept


def test_creating_from_the_older_grammar_keeps_its_pictures(
    store: NodeStore, fake_convert: list[Any]
) -> None:
    node = store.create(
        type="whiteboard",
        title="Old",
        spec={"items": [{"text": "Note"}, {"type": "image", "image": PNG_URL}, {"image": "bad"}]},
        now=T0,
    )
    assert node.spec["format"] == "scene"
    file_id = fake_convert[0][0]
    assert fake_convert[1] is None  # a picture that is no picture becomes a box
    assert store.read_file(node.id, file_id) == (PNG, "image/png")
    assert file_id in node.spec["files"]


def test_a_failed_creation_leaves_no_folder_behind(
    store: NodeStore, fake_convert: list[Any], tmp_path: Path
) -> None:
    with pytest.raises(NodeError, match="items"):
        store.create(type="whiteboard", title="Old", spec={"items": []}, now=T0)
    assert list(tmp_path.iterdir()) == []


def test_a_stored_older_board_is_converted_when_it_is_read(
    store: NodeStore, board: str, fake_convert: list[Any]
) -> None:
    run_dir = store.dir_of(board)
    assert run_dir is not None
    state = json.loads((run_dir / STATE_FILE).read_text(encoding="utf-8"))
    state["spec"] = {"items": [{"text": "Kept"}, {"image": PNG_URL}], "layout": "auto"}
    state["rendered"] = 0
    (run_dir / STATE_FILE).write_text(json.dumps(state), encoding="utf-8")
    node = store.get(board)
    assert node is not None and node.spec["format"] == "scene" and node.version == 1
    assert node.spec["elements"][0]["text"] == "Kept"
    assert store.read_file(board, fake_convert[0][0]) is not None
    # The conversion is on disk: the next read does not convert again.
    assert json.loads((run_dir / STATE_FILE).read_text(encoding="utf-8"))["spec"] == node.spec


def test_reverting_to_a_version_in_the_older_grammar_converts_it(
    store: NodeStore, fake_convert: list[Any]
) -> None:
    node = store.create(type="whiteboard", title="Old", spec={"items": [{"text": "v1"}]}, now=T0)
    store.update(node.id, spec=_scene(_el("r")), now=T0 + 1)
    run_dir = store.dir_of(node.id)
    assert run_dir is not None
    snapshot = run_dir / HISTORY_DIR / "v1.json"
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    data["spec"] = {"items": [{"text": "from history"}]}
    snapshot.write_text(json.dumps(data), encoding="utf-8")
    reverted = store.revert(node.id, now=T0 + 2)
    assert reverted.spec["elements"][0]["text"] == "from history"
    assert "last_save" not in reverted.extra


def test_board_files_stay_out_of_the_page_folder(store: NodeStore, board: str) -> None:
    store.put_file(board, PNG_URL)
    run_dir = store.dir_of(board)
    assert run_dir is not None
    assert (run_dir / board_files.FILES_DIR).is_dir()
    page_files = [entry for entry in (run_dir / "tasks").rglob("*") if entry.is_file()]
    assert [entry.suffix for entry in page_files] == [".html"]
