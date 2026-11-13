"""Nodes on disk: one run directory per node (``dodaios/nodes/store.py``).

The renderers are stand-ins here (``kinds`` below), so these tests say what the
store does with ANY type: what it writes, what a revision keeps, what a read
repairs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dodaios.missions.standalone_run import read_marker
from dodaios.nodes import kinds as node_kinds
from dodaios.nodes import shell
from dodaios.nodes import store as node_store
from dodaios.nodes.kinds import RENDER_REVISION, NodeKind
from dodaios.nodes.model import HISTORY_DIR, SLUG_INFIX, STATE_FILE, Node
from dodaios.nodes.store import (
    DEFAULT_EVERY_MINUTES,
    MAX_EVERY_MINUTES,
    MAX_HISTORY,
    MIN_EVERY_MINUTES,
    NodeStore,
    clamp_every,
)
from dodaios.nodes.types import MAX_SPEC_BYTES, MAX_TITLE_CHARS, NODE_TYPES, NodeError


@pytest.fixture(autouse=True)
def renders(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stand-in renderers for every type; returns the ids rendered, in order."""
    rendered: list[str] = []

    def render(node: Node) -> str:
        rendered.append(node.id)
        return shell.document(node, body=f"<main>{shell.esc(json.dumps(node.spec))}</main>")

    fakes = {
        name: NodeKind(
            type=name,
            normalize=lambda spec: spec,
            render=render,
            preview=lambda spec: {"probe": 1},
            starter=lambda title, language: {"probe": True},
            guide=f"guide for {name}",
        )
        for name in NODE_TYPES
    }
    monkeypatch.setattr(node_kinds, "_KINDS", fakes)
    return rendered


@pytest.fixture
def store(tmp_path: Path) -> NodeStore:
    return NodeStore(root=tmp_path)


def _state(store: NodeStore, node: Node) -> dict[str, Any]:
    return json.loads((store.root / node.slug / STATE_FILE).read_text(encoding="utf-8"))


def _page(store: NodeStore, node: Node) -> str:
    return (store.root / node.slug / node.page_path).read_text(encoding="utf-8")


def _history(store: NodeStore, node: Node) -> list[str]:
    folder = store.root / node.slug / HISTORY_DIR
    return sorted(entry.name for entry in folder.iterdir()) if folder.is_dir() else []


def _refused(call: Any, *args: Any, **kwargs: Any) -> str:
    with pytest.raises(NodeError) as caught:
        call(*args, **kwargs)
    return str(caught.value)


# ---------------------------------------------------------------------- create


def test_create_writes_one_run_directory_with_state_page_and_marker(store: NodeStore) -> None:
    node = store.create(
        type="sheets", title="  Open \n orders ", spec={"rows": [1, 2]}, language=" de ", now=100.0
    )

    assert node.type == "sheets" and node.title == "Open orders" and node.language == "de"
    assert node.spec == {"rows": [1, 2]}
    assert node.version == 1 and node.rendered == RENDER_REVISION
    assert node.created_at == node.updated_at == 100.0
    assert node.slug == f"19700101T000140{SLUG_INFIX}{node.id}"
    assert node.page_path == "tasks/node/artifacts/files/open-orders.html"
    assert node.visual_id == f"{node.slug}::{node.page_path}"
    assert node.page_url == f"/api/outputs/{node.slug}/files/{node.page_path}/page"

    run_dir = store.root / node.slug
    assert store.dir_of(node.id) == run_dir
    assert read_marker(run_dir) == {"kind": "node", "utterance": "", "title": "Open orders"}
    assert "<title>Open orders</title>" in _page(store, node)
    assert _state(store, node) == node.state()
    assert _history(store, node) == []
    # Nothing but the page sits where the outputs listing looks for deliverables.
    files = sorted(p.name for p in (run_dir / "tasks" / "node" / "artifacts" / "files").iterdir())
    assert files == ["open-orders.html"]
    assert store.get(node.id) == node


def test_create_without_a_spec_starts_from_the_types_starter(store: NodeStore) -> None:
    node = store.create(type="slides", title="Kickoff")
    assert node.spec == {"probe": True}
    assert node.language == "en"


def test_create_accepts_what_people_call_a_type(store: NodeStore) -> None:
    assert store.create(type="Deck", title="A", spec={}).type == "slides"
    assert store.create(type="spreadsheet", title="B", spec={}).type == "sheets"


def test_create_names_the_file_after_the_title(store: NodeStore) -> None:
    assert store.create(type="docs", title="Q3: Plan & Budget!", spec={}).page_path.endswith(
        "/q3-plan-budget.html"
    )
    assert store.create(type="docs", title="???", spec={}).page_path.endswith("/node.html")
    long_title = "word " * 60
    node = store.create(type="docs", title=long_title, spec={})
    assert len(node.title) == MAX_TITLE_CHARS
    assert len(node.page_path.rsplit("/", 1)[-1]) <= 48 + len(".html")


def test_create_refuses_what_it_cannot_keep(store: NodeStore) -> None:
    assert _refused(store.create, type="poem", title="A", spec={}) == (
        "'type' must be one of: docs, slides, sheets, design, data, whiteboard, motion."
    )
    assert _refused(store.create, type="docs", title="  ", spec={}) == "'title' must name the node."
    for not_an_object in ([1, 2], "text", 7):
        assert _refused(store.create, type="docs", title="A", spec=not_an_object) == (
            "'spec' must be an object in the type's grammar (ask for the guide)."
        )
    too_large = {"text": "a" * (MAX_SPEC_BYTES + 1)}
    assert _refused(store.create, type="docs", title="A", spec=too_large) == (
        "The node is too large; split it into several nodes."
    )
    assert store.list_nodes() == []
    assert list(store.root.iterdir()) == []


# ---------------------------------------------------------------------- update


def test_update_with_a_spec_rewrites_the_page_and_keeps_the_old_version(store: NodeStore) -> None:
    node = store.create(type="docs", title="Plan", spec={"text": "draft one"}, now=100.0)
    updated = store.update(node.id, spec={"text": "draft two"}, now=200.0)

    assert updated.spec == {"text": "draft two"} and updated.version == 2
    assert updated.created_at == 100.0 and updated.updated_at == 200.0
    assert (updated.slug, updated.page_path, updated.id) == (node.slug, node.page_path, node.id)
    assert "draft two" in _page(store, updated) and "draft one" not in _page(store, updated)
    assert _state(store, updated) == updated.state()
    assert _history(store, updated) == ["v1.json"]
    kept = json.loads((store.root / node.slug / HISTORY_DIR / "v1.json").read_text("utf-8"))
    assert kept == {
        "version": 1,
        "title": "Plan",
        "spec": {"text": "draft one"},
        "updated_at": 100.0,
    }
    assert store.get(node.id) == updated


def test_update_with_changes_edits_the_spec_in_place(store: NodeStore) -> None:
    node = store.create(type="slides", title="Deck", spec={"slides": [{"title": "One"}]})
    updated = store.update(
        node.id,
        changes=[
            {"op": "set", "path": "/slides/0/title", "value": "First"},
            {"op": "insert", "path": "/slides/-", "value": {"title": "Second"}},
        ],
    )
    assert updated.spec == {"slides": [{"title": "First"}, {"title": "Second"}]}
    assert updated.version == 2
    assert _history(store, updated) == ["v1.json"]


def test_a_refused_update_leaves_the_node_as_it_was(store: NodeStore) -> None:
    node = store.create(type="docs", title="Plan", spec={"text": "draft one"}, now=100.0)

    assert _refused(store.update, node.id, spec={"a": 1}, changes=[{"path": "/a", "value": 2}]) == (
        "Send either 'spec' (a rewrite) or 'changes' (edits), not both."
    )
    assert _refused(store.update, node.id) == (
        "Nothing to change: give 'spec', 'changes' or 'title'."
    )
    # Content that changes nothing says why that can happen, so the caller
    # checks its path instead of sending the same edit again.
    assert _refused(store.update, node.id, spec={"text": "draft one"}, title="Plan").startswith(
        "That left the node exactly as it was."
    )
    assert _refused(store.update, node.id, title=" ") == "'title' must name the node."
    assert _refused(store.update, node.id, spec=["not", "an", "object"]) == (
        "'spec' must be an object in the type's grammar (ask for the guide)."
    )
    assert "nothing at '/missing'" in _refused(
        store.update, node.id, changes=[{"op": "set", "path": "/missing/x", "value": 1}]
    )
    assert _refused(store.update, "0123456789ab", title="X") == "No node with id '0123456789ab'."

    assert store.get(node.id) == node
    assert _history(store, node) == []


def test_a_rename_keeps_the_page_where_it_is(store: NodeStore) -> None:
    node = store.create(type="docs", title="Plan", spec={"text": "body"}, now=100.0)
    renamed = store.update(node.id, title="  Budget   2027 ", now=200.0)

    assert renamed.title == "Budget 2027" and renamed.version == 2
    assert renamed.page_path == node.page_path and renamed.slug == node.slug
    assert renamed.spec == node.spec
    assert "<title>Budget 2027</title>" in _page(store, renamed)
    # The run list labels the run with the marker's title.
    assert read_marker(store.root / node.slug)["title"] == "Budget 2027"  # type: ignore[index]
    assert _history(store, renamed) == ["v1.json"]
    assert store.find("budget 2027") == renamed and store.find("Plan") is None


def test_a_note_alone_is_recorded_without_a_new_version(store: NodeStore) -> None:
    node = store.create(type="data", title="Numbers", spec={"n": 1}, now=100.0)
    noted = store.update(node.id, note="  The shop \n could not be read. ", now=200.0)

    assert noted.note == "The shop could not be read."
    assert noted.version == 1 and noted.updated_at == 200.0 and noted.spec == node.spec
    assert _history(store, noted) == []
    # A later revision keeps the note until a refresh writes a new one.
    assert store.update(node.id, spec={"n": 2}).note == "The shop could not be read."
    assert store.update(node.id, spec={"n": 3}, note="").note == ""


# ---------------------------------------------------------------------- revert


def test_revert_puts_the_previous_version_back(store: NodeStore) -> None:
    node = store.create(type="docs", title="Plan", spec={"text": "draft one"}, now=100.0)
    store.update(node.id, spec={"text": "draft two"}, title="Plan B", now=200.0)

    back = store.revert(node.id, now=300.0)
    assert back.spec == {"text": "draft one"} and back.title == "Plan"
    assert back.version == 3 and back.updated_at == 300.0
    assert back.page_path == node.page_path
    assert "draft one" in _page(store, back) and "<title>Plan</title>" in _page(store, back)
    assert read_marker(store.root / node.slug)["title"] == "Plan"  # type: ignore[index]
    # What was current is kept, so the revert itself can be taken back.
    assert _history(store, back) == ["v2.json"]

    again = store.revert(node.id, now=400.0)
    assert again.spec == {"text": "draft two"} and again.title == "Plan B" and again.version == 4
    assert _history(store, again) == ["v3.json"]


def test_revert_without_history_is_refused(store: NodeStore) -> None:
    node = store.create(type="docs", title="Plan", spec={})
    assert _refused(store.revert, node.id) == "This node has no earlier version to go back to."
    store.update(node.id, note="only a note")
    assert _refused(store.revert, node.id) == "This node has no earlier version to go back to."
    assert _refused(store.revert, "0123456789ab") == "No node with id '0123456789ab'."


def test_revert_skips_a_history_entry_it_cannot_read(store: NodeStore) -> None:
    node = store.create(type="docs", title="Plan", spec={"text": "draft one"})
    store.update(node.id, spec={"text": "draft two"})
    store.update(node.id, spec={"text": "draft three"})
    history = store.root / node.slug / HISTORY_DIR
    (history / "v2.json").write_text("{not json", encoding="utf-8")

    back = store.revert(node.id)
    assert back.spec == {"text": "draft one"} and back.version == 4


def test_history_keeps_only_the_newest_versions(store: NodeStore) -> None:
    node = store.create(type="docs", title="Plan", spec={"n": 0})
    revisions = MAX_HISTORY + 3
    for n in range(1, revisions + 1):
        node = store.update(node.id, spec={"n": n})

    assert node.version == revisions + 1
    kept = sorted(int(name[1:-5]) for name in _history(store, node))
    assert kept == list(range(revisions - MAX_HISTORY + 1, revisions + 1))
    assert store.revert(node.id).spec == {"n": revisions - 1}


# ------------------------------------------------------------ duplicate, delete


def test_duplicate_is_a_new_node_with_the_same_content(store: NodeStore) -> None:
    node = store.create(type="sheets", title="Orders", spec={"rows": [1]}, language="de")
    store.update(node.id, spec={"rows": [1, 2]})
    store.set_upkeep(node.id, track="the shop's open orders", refreshing=True, task_id="task-1")

    copy = store.duplicate(node.id)
    assert copy.id != node.id and copy.slug != node.slug
    assert (copy.type, copy.title, copy.language) == ("sheets", "Orders", "de")
    assert copy.spec == {"rows": [1, 2]}
    assert copy.version == 1 and _history(store, copy) == []
    # A copy is not kept current: it has no routine of its own.
    assert (copy.track, copy.refreshing, copy.task_id, copy.every_minutes) == ("", False, "", 0)

    named = store.duplicate(node.id, title="  Orders (copy) ")
    assert named.title == "Orders (copy)"
    assert len(store.list_nodes()) == 3
    assert _refused(store.duplicate, "0123456789ab") == "No node with id '0123456789ab'."


def test_delete_removes_the_node_its_page_and_its_history(store: NodeStore) -> None:
    node = store.create(type="docs", title="Plan", spec={"a": 1})
    store.update(node.id, spec={"a": 2})
    other = store.create(type="docs", title="Other", spec={})

    assert store.delete(node.id) is True
    assert not (store.root / node.slug).exists()
    assert store.get(node.id) is None and store.dir_of(node.id) is None
    assert store.list_nodes() == [other]
    assert store.delete(node.id) is False
    assert store.delete("../" + other.slug) is False and store.get(other.id) == other


# ---------------------------------------------------------------------- upkeep


def test_set_upkeep_records_how_the_node_is_kept_current(store: NodeStore) -> None:
    node = store.create(type="sheets", title="Orders", spec={"rows": []}, now=100.0)

    tracked = store.set_upkeep(node.id, track="  open orders \n in the shop ", every_minutes=45)
    assert tracked.track == "open orders in the shop" and tracked.every_minutes == 45
    assert tracked.refreshing is False and tracked.task_id == ""

    live = store.set_upkeep(node.id, refreshing=True, task_id="task-1")
    assert (live.track, live.every_minutes) == ("open orders in the shop", 45)
    assert live.refreshing is True and live.task_id == "task-1"
    # Upkeep is not a revision of the content.
    assert live.version == 1 and live.updated_at == 100.0 and _history(store, live) == []
    assert _state(store, live) == live.state() and store.get(node.id) == live
    assert shell.RELATIVE_TIME_JS in _page(store, live)

    stopped = store.set_upkeep(node.id, refreshing=False, task_id="")
    assert stopped.refreshing is False and stopped.task_id == "" and stopped.track == live.track
    assert _refused(store.set_upkeep, "0123456789ab", track="x") == (
        "No node with id '0123456789ab'."
    )


def test_the_refresh_cadence_stays_inside_its_bounds(store: NodeStore) -> None:
    node = store.create(type="data", title="Numbers", spec={})
    assert store.set_upkeep(node.id, every_minutes=1).every_minutes == MIN_EVERY_MINUTES
    assert store.set_upkeep(node.id, every_minutes=10**9).every_minutes == MAX_EVERY_MINUTES
    assert store.set_upkeep(node.id, every_minutes="often").every_minutes == DEFAULT_EVERY_MINUTES
    assert clamp_every("60") == 60 and clamp_every(None) == DEFAULT_EVERY_MINUTES


# --------------------------------------------------------------------- reading


def test_find_takes_an_id_a_slug_or_the_exact_title(store: NodeStore) -> None:
    older = store.create(type="docs", title="Weekly notes", spec={"n": 1}, now=100.0)
    newer = store.create(type="docs", title="Weekly Notes", spec={"n": 2}, now=200.0)

    assert store.find(older.id) == older
    assert store.find(f"  {older.slug} ") == older
    assert store.by_slug(older.slug) == older
    # Two nodes of one name: the one changed last.
    assert store.find("weekly notes") == newer
    assert store.find("Weekly") is None
    assert store.find("") is None and store.find("   ") is None
    assert store.by_slug("20260101T000000__report__0123456789ab") is None
    assert store.get("not-an-id") is None


def test_list_is_ordered_by_the_last_change(store: NodeStore) -> None:
    first = store.create(type="docs", title="First", spec={}, now=100.0)
    second = store.create(type="slides", title="Second", spec={}, now=200.0)
    third = store.create(type="data", title="Third", spec={}, now=300.0)
    assert [n.id for n in store.list_nodes()] == [third.id, second.id, first.id]

    store.update(first.id, spec={"changed": True}, now=400.0)
    assert [n.id for n in store.list_nodes()] == [first.id, third.id, second.id]


def test_nodes_are_read_from_every_root_and_written_to_the_first(tmp_path: Path) -> None:
    current, legacy = tmp_path / "current", tmp_path / "legacy"
    old = NodeStore(root=legacy).create(type="docs", title="Old", spec={}, now=100.0)
    store = NodeStore(root=current, read_roots=(current, legacy, tmp_path / "missing"))
    new = store.create(type="docs", title="New", spec={}, now=200.0)

    assert [n.id for n in store.list_nodes()] == [new.id, old.id]
    assert store.get(old.id) == old and store.dir_of(new.id) == current / new.slug
    assert store.update(old.id, title="Older").title == "Older"
    assert (legacy / old.slug / STATE_FILE).is_file()


def test_an_unreadable_state_file_is_skipped(store: NodeStore, tmp_path: Path) -> None:
    good = store.create(type="docs", title="Good", spec={})
    broken = store.create(type="docs", title="Broken", spec={})
    unknown = store.create(type="docs", title="Unknown type", spec={})
    no_state = store.create(type="docs", title="No state", spec={})
    (tmp_path / broken.slug / STATE_FILE).write_text("{not json", encoding="utf-8")
    state = _state(store, unknown)
    (tmp_path / unknown.slug / STATE_FILE).write_text(
        json.dumps({**state, "type": "poem"}), encoding="utf-8"
    )
    (tmp_path / no_state.slug / STATE_FILE).unlink()
    # Run directories that only look like a node's.
    (tmp_path / f"20260101T000000{SLUG_INFIX}not-a-node-id").mkdir()
    (tmp_path / f"20260101T000001{SLUG_INFIX}0123456789ab").write_text("a file", encoding="utf-8")

    assert store.list_nodes() == [good]
    for lost in (broken, unknown, no_state):
        assert store.get(lost.id) is None
        assert _refused(store.update, lost.id, title="X") == f"No node with id {lost.id!r}."
    # The directory is still there to be removed.
    assert store.delete(broken.id) is True


def test_a_page_from_an_older_renderer_is_drawn_again_when_read(
    store: NodeStore, renders: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    node = store.create(type="docs", title="Plan", spec={"text": "body"}, now=100.0)
    page = store.root / node.slug / node.page_path
    page.write_text("the old look", encoding="utf-8")
    assert store.get(node.id) == node  # same renderer revision: the page is left alone
    assert page.read_text(encoding="utf-8") == "the old look"

    monkeypatch.setattr(node_store, "RENDER_REVISION", RENDER_REVISION + 1)
    del renders[:]
    listed = store.list_nodes()

    assert [n.rendered for n in listed] == [RENDER_REVISION + 1]
    assert "<title>Plan</title>" in page.read_text(encoding="utf-8")
    assert _state(store, node)["rendered"] == RENDER_REVISION + 1
    # A new look is not a revision of the content.
    assert (listed[0].version, listed[0].updated_at, listed[0].spec) == (1, 100.0, node.spec)
    assert renders == [node.id]
    store.get(node.id)
    assert renders == [node.id]  # drawn once, not on every read


def test_a_redraw_that_fails_on_disk_still_lists_the_node(
    store: NodeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    node = store.create(type="docs", title="Plan", spec={"text": "body"})
    monkeypatch.setattr(node_store, "RENDER_REVISION", RENDER_REVISION + 1)

    def full_disk(target: Path, text: str) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr(node_store, "_atomic_write", full_disk)
    assert store.list_nodes() == [node]


def test_a_renderer_fault_during_a_redraw_still_lists_the_node(
    store: NodeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    node = store.create(type="docs", title="Plan", spec={"text": "body"})
    other = store.create(type="slides", title="Deck", spec={})

    def faulty(node: Node) -> str:
        raise TypeError("the new renderer does not expect this spec")

    kinds = dict(node_kinds._KINDS)
    kinds["docs"] = NodeKind(
        type="docs",
        normalize=lambda spec: spec,
        render=faulty,
        preview=lambda spec: {"probe": 1},
        starter=lambda title, language: {"probe": True},
        guide="",
    )
    monkeypatch.setattr(node_kinds, "_KINDS", kinds)
    monkeypatch.setattr(node_store, "RENDER_REVISION", RENDER_REVISION + 1)

    assert {n.id for n in store.list_nodes()} == {node.id, other.id}
