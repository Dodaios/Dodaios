"""The ``node`` tool: every operation, its errors, its cards and its registration.

The real renderers are not under test here: a tiny stand-in kind is registered
for two types, so a change to a type's grammar cannot break these tests.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from dodaios.nodes import kinds, refresh, shell
from dodaios.nodes.kinds import NodeKind
from dodaios.nodes.store import NodeStore
from dodaios.nodes.types import NODE_TYPES, NodeError
from dodaios.orchestrator import jobs
from dodaios.plugins.tool import node as node_tool
from dodaios.plugins.tool.node import MAX_GET_CHARS, TYPE_LINES, NodeTool

REPO = Path(__file__).resolve().parents[4]
SPEC: dict[str, Any] = {"blocks": [{"text": "First"}, {"text": "Second"}]}


def _normalize(spec: Any) -> dict[str, Any]:
    blocks = spec.get("blocks") if isinstance(spec, dict) else None
    if not isinstance(blocks, list):
        raise NodeError("'blocks' must be a list of {text}.")
    return {"blocks": [{"text": str(b.get("text", ""))} for b in blocks if isinstance(b, dict)]}


def _render(node: Any) -> str:
    texts = "".join(f"<p>{shell.esc(block['text'])}</p>" for block in node.spec["blocks"])
    return shell.document(node, body=f"<main>{texts}</main>")


def _kind(name: str) -> NodeKind:
    return NodeKind(
        type=name,
        normalize=_normalize,
        render=_render,
        preview=lambda spec: {"blocks": len(spec["blocks"])},
        starter=lambda title, language: {"blocks": [{"text": title}]},
        guide=f"GUIDE for {name}: spec is {{blocks: [{{text}}]}}.",
    )


@pytest.fixture(autouse=True)
def fake_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kinds, "_KINDS", {name: _kind(name) for name in ("docs", "sheets")})


@pytest.fixture(autouse=True)
def ledger():
    store = jobs.JobLedger(":memory:")
    jobs.set_ledger(store)
    try:
        yield store
    finally:
        jobs.set_ledger(None)
        store.close()


@pytest.fixture(autouse=True)
def society_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """No society runtime unless a test brings its own refresh functions."""

    def down() -> tuple[Any, Any, Any]:
        raise RuntimeError("The agent society is not running")

    monkeypatch.setattr(refresh, "_services", down)


@pytest.fixture
def cards(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    posted: list[tuple[str, dict]] = []

    async def fake_post(session_id: str, payload: dict) -> bool:
        posted.append((session_id, payload))
        return True

    monkeypatch.setattr(node_tool, "post_card", fake_post)
    return posted


@pytest.fixture
def upkeep(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def start(store, node_id, *, track=None, every_minutes=None):
        calls.append(f"start:{node_id}:{track}:{every_minutes}")
        store.set_upkeep(node_id, track=track, every_minutes=every_minutes)
        return store.set_upkeep(node_id, refreshing=True, task_id="task-9")

    async def stop(store, node_id):
        calls.append(f"stop:{node_id}")
        return store.set_upkeep(node_id, refreshing=False, task_id="")

    monkeypatch.setattr(refresh, "start_refresh", start)
    monkeypatch.setattr(refresh, "stop_refresh", stop)
    return calls


def _ctx(session: str = "lead-1", **config: Any) -> SimpleNamespace:
    return SimpleNamespace(
        trace_id=uuid4(),
        user_utterance="",
        config={"approval_ref": f"agent-chat:{session}", "output_language": "de", **config},
        memory_read=None,
    )


def _tool(tmp_path: Path) -> tuple[NodeTool, NodeStore]:
    store = NodeStore(root=tmp_path)
    return NodeTool(store=store), store


# ------------------------------------------------------------------- guide


async def test_guide_lists_the_types_and_hands_out_one_grammar(tmp_path: Path) -> None:
    tool, _ = _tool(tmp_path)
    overview = await tool.execute({"operation": "guide"}, _ctx())
    assert overview.success
    for name in NODE_TYPES:
        assert f"- {name}: {TYPE_LINES[name]}" in overview.output
    assert "operation 'guide' and that type" in overview.output

    one = await tool.execute({"operation": "guide", "type": "docs"}, _ctx())
    assert one.success and one.output == "GUIDE for docs: spec is {blocks: [{text}]}."
    # What a person calls a type is understood too.
    alias = await tool.execute({"operation": "guide", "type": "spreadsheet"}, _ctx())
    assert alias.output.startswith("GUIDE for sheets")

    unknown = await tool.execute({"operation": "guide", "type": "hologram"}, _ctx())
    assert not unknown.success and "docs, slides" in unknown.error


def test_every_type_has_its_line_and_the_schema_offers_exactly_the_types() -> None:
    assert tuple(TYPE_LINES) == NODE_TYPES
    properties = NodeTool.schema["properties"]
    assert properties["type"]["enum"] == list(NODE_TYPES)
    assert properties["operation"]["enum"] == [
        "guide", "create", "update", "look", "get", "list", "revert", "keep_current", "stop",
    ]
    assert NodeTool.schema["required"] == ["operation"]


def test_the_description_is_short_and_says_the_rules() -> None:
    text = NodeTool.description
    assert len(text) < 900
    for name in NODE_TYPES:
        assert name in text
    for rule in ("'guide'", "'changes'", "'track'", "never HTML (except type design)"):
        assert rule in text


# ------------------------------------------------------------------ create


async def test_create_writes_the_node_records_the_job_and_shows_its_card(
    tmp_path: Path, cards, upkeep, ledger
) -> None:
    tool, store = _tool(tmp_path)
    result = await tool.execute(
        {"operation": "create", "type": "docs", "title": "Quarterly plan", "spec": SPEC},
        _ctx(tool_origin="agent-chat"),
    )
    assert result.success, result.error
    (node,) = store.list_nodes()
    assert (node.type, node.title, node.language) == ("docs", "Quarterly plan", "de")
    assert node.spec == SPEC and not node.refreshing
    assert "<p>First</p>" in (tmp_path / node.slug / node.page_path).read_text(encoding="utf-8")
    # The result names the node and keeps the chat reply short.
    assert node.id in result.output and "docs node 'Quarterly plan'" in result.output
    assert "Answer briefly" in result.output and "do not repeat" in result.output
    # ... but only after it looked at what it made.
    assert "operation 'look'" in result.output
    # A long conversation holds the tool's older schema without 'look' (seen 2026-11-14:
    # the lead read the node with 'get' instead); the result says it is valid anyway.
    assert "earlier in the conversation" in result.output
    assert upkeep == []
    # The page shows in the chat as its card, in the conversation that asked.
    assert cards == [
        (
            "lead-1",
            {
                "kind": "report", "text": "Quarterly plan", "summary": "",
                "artifact": node.visual_id, "sections": 0, "node_type": "docs",
            },
        )
    ]
    # Written synchronously: the ledger lists a finished job for it.
    (job,) = ledger.recent(owner_session="lead-1")
    assert (job.kind, job.state, job.title) == ("artifact", "done", "Quarterly plan")
    assert job.result_ref == f"artifact:{node.visual_id}"
    assert job.id in result.output


async def test_create_with_track_keeps_the_node_current_from_the_start(
    tmp_path: Path, cards, upkeep
) -> None:
    tool, store = _tool(tmp_path)
    result = await tool.execute(
        {
            "operation": "create", "type": "sheet", "title": "Open orders", "spec": SPEC,
            "track": "Open orders from the shop mails in Gmail.", "every_minutes": 60,
        },
        _ctx(),
    )
    assert result.success, result.error
    (node,) = store.list_nodes()
    assert node.type == "sheets" and node.refreshing and node.every_minutes == 60
    assert upkeep == [f"start:{node.id}:Open orders from the shop mails in Gmail.:60"]
    assert "refreshes every 60 minutes" in result.output


async def test_create_without_the_scheduler_still_keeps_the_node(
    tmp_path: Path, cards, ledger
) -> None:
    tool, store = _tool(tmp_path)
    result = await tool.execute(
        {"operation": "create", "type": "docs", "title": "Stocks", "spec": SPEC, "track": "x"},
        _ctx(),
    )
    assert result.success
    assert "could not be scheduled" in result.output
    assert "The agent society is not running" in result.output
    (node,) = store.list_nodes()
    assert not node.refreshing and node.track == "x"
    assert len(cards) == 1
    (job,) = ledger.recent(owner_session="lead-1")
    assert job.state == "blocked"


async def test_create_without_a_spec_asks_for_the_guide_first(tmp_path: Path, cards) -> None:
    tool, store = _tool(tmp_path)
    for args in ({}, {"spec": None}, {"spec": {}}):
        result = await tool.execute(
            {"operation": "create", "type": "docs", "title": "Plan", **args}, _ctx()
        )
        assert not result.success
        assert "operation 'guide' and type 'docs'" in result.error
    # Nothing was made from a starter behind the model's back.
    assert store.list_nodes() == [] and cards == []


async def test_create_refuses_what_the_store_refuses(tmp_path: Path, cards) -> None:
    tool, store = _tool(tmp_path)
    no_type = await tool.execute({"operation": "create", "title": "T", "spec": SPEC}, _ctx())
    assert not no_type.success and "'type' must be one of" in no_type.error
    no_title = await tool.execute({"operation": "create", "type": "docs", "spec": SPEC}, _ctx())
    assert not no_title.success and "'title'" in no_title.error
    bad_spec = await tool.execute(
        {"operation": "create", "type": "docs", "title": "T", "spec": {"blocks": "no"}}, _ctx()
    )
    assert not bad_spec.success and "'blocks' must be a list" in bad_spec.error
    assert store.list_nodes() == [] and cards == []


async def test_a_spec_sent_as_json_text_is_read_as_the_object(tmp_path: Path, cards) -> None:
    tool, store = _tool(tmp_path)
    result = await tool.execute(
        {"operation": "create", "type": "docs", "title": "T", "spec": json.dumps(SPEC)}, _ctx()
    )
    assert result.success, result.error
    assert store.list_nodes()[0].spec == SPEC


# ------------------------------------------------------------------ update


async def test_update_with_changes_makes_a_new_version_and_shows_the_fresh_page(
    tmp_path: Path, cards
) -> None:
    tool, store = _tool(tmp_path)
    node = store.create(type="docs", title="Plan", spec=SPEC)
    result = await tool.execute(
        {
            "operation": "update",
            "node": node.id,
            "changes": [
                {"op": "set", "path": "/blocks/0/text", "value": "Opening"},
                {"op": "insert", "path": "/blocks/-", "value": {"text": "Third"}},
            ],
        },
        _ctx("chat-7"),
    )
    assert result.success, result.error
    assert "version 2" in result.output and "2 edit(s) applied" in result.output
    fresh = store.get(node.id)
    assert [b["text"] for b in fresh.spec["blocks"]] == ["Opening", "Second", "Third"]
    assert [(s, c["artifact"]) for s, c in cards] == [("chat-7", fresh.visual_id)]


async def test_update_by_title_with_a_whole_spec_and_a_new_title(tmp_path: Path, cards) -> None:
    tool, store = _tool(tmp_path)
    node = store.create(type="docs", title="Plan", spec=SPEC)
    result = await tool.execute(
        {
            "operation": "update", "node": "plan", "title": "Plan 2027",
            "spec": {"blocks": [{"text": "Only"}]},
        },
        _ctx(),
    )
    assert result.success, result.error
    assert "Node 'Plan 2027' is now version 2" in result.output
    assert "its content was rewritten" in result.output
    assert "renamed from 'Plan'" in result.output
    assert store.get(node.id).spec == {"blocks": [{"text": "Only"}]}
    assert cards[0][1]["text"] == "Plan 2027"


async def test_a_note_only_update_changes_no_version_and_posts_no_card(
    tmp_path: Path, cards
) -> None:
    tool, store = _tool(tmp_path)
    node = store.create(type="docs", title="Plan", spec=SPEC)
    noted = await tool.execute(
        {"operation": "update", "node": node.id, "note": "Gmail is not connected"}, _ctx()
    )
    assert noted.success and "the note was recorded" in noted.output
    kept = store.get(node.id)
    assert (kept.version, kept.note, kept.spec) == (1, "Gmail is not connected", SPEC)
    assert cards == []

    # The next content that was read retires that line.
    await tool.execute(
        {"operation": "update", "node": node.id,
         "changes": [{"path": "/blocks/0/text", "value": "Fresh"}]},
        _ctx(),
    )
    assert store.get(node.id).note == ""


@pytest.mark.parametrize(
    "config",
    [
        {"unattended": True},
        {"approval_surface": "unattended"},
        {"approval_ref": "society:scout"},
    ],
)
async def test_a_refresh_run_updates_the_node_without_a_card(
    tmp_path: Path, cards, config: dict[str, Any]
) -> None:
    tool, store = _tool(tmp_path)
    node = store.create(type="docs", title="Plan", spec=SPEC)
    result = await tool.execute(
        {"operation": "update", "node": node.id,
         "changes": [{"path": "/blocks/1/text", "value": "Now"}]},
        _ctx(**config),
    )
    assert result.success and "version 2" in result.output
    assert store.get(node.id).spec["blocks"][1]["text"] == "Now"
    # The page itself shows the update; the conversation stays quiet.
    assert cards == []


async def test_update_errors_say_what_to_fix(tmp_path: Path, cards) -> None:
    tool, store = _tool(tmp_path)
    node = store.create(type="docs", title="Plan", spec=SPEC)
    missing = await tool.execute({"operation": "update", "spec": SPEC}, _ctx())
    assert not missing.success and "'node' is required for update" in missing.error
    unknown = await tool.execute({"operation": "update", "node": "0123456789ab"}, _ctx())
    assert not unknown.success and "operation 'list'" in unknown.error
    nothing = await tool.execute({"operation": "update", "node": node.id}, _ctx())
    assert not nothing.success and "Nothing to change" in nothing.error
    both = await tool.execute(
        {"operation": "update", "node": node.id, "spec": SPEC,
         "changes": [{"path": "/blocks/0/text", "value": "x"}]},
        _ctx(),
    )
    assert not both.success and "not both" in both.error
    bad_path = await tool.execute(
        {"operation": "update", "node": node.id,
         "changes": [{"op": "remove", "path": "/blocks/9"}]},
        _ctx(),
    )
    assert not bad_path.success and "outside the list" in bad_path.error
    assert store.get(node.id).version == 1 and cards == []


# ------------------------------------------------------- get, list, revert


async def test_get_returns_the_fields_and_the_whole_spec_as_json(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    node = store.create(type="docs", title="Plan", spec=SPEC, now=1_700_000_000)
    result = await tool.execute({"operation": "get", "node": node.id}, _ctx())
    assert result.success, result.error
    data = json.loads(result.output)
    assert data["spec"] == SPEC
    assert (data["id"], data["type"], data["title"], data["version"]) == (
        node.id, "docs", "Plan", 1,
    )
    assert data["kept_current"] is False and data["refreshing"] is False
    # Local time with its offset, so the model can say when it changed.
    assert data["updated_at"][:2] == "20" and data["updated_at"][-6] in "+-"


async def test_get_of_a_very_large_node_says_so_and_gives_the_first_part(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    big = {"blocks": [{"text": "x" * 500} for _ in range(200)]}
    node = store.create(type="docs", title="Big", spec=big)
    result = await tool.execute({"operation": "get", "node": "Big"}, _ctx())
    assert result.success
    head, _, body = result.output.partition("\n")
    assert f"these are the first {MAX_GET_CHARS}" in head
    assert len(body) == MAX_GET_CHARS and body.startswith('{"id": "' + node.id)


async def test_list_shows_every_node_newest_first(tmp_path: Path, upkeep) -> None:
    tool, store = _tool(tmp_path)
    assert (await tool.execute({"operation": "list"}, _ctx())).output == []
    first = store.create(type="docs", title="Plan", spec=SPEC, now=1_700_000_000)
    second = store.create(type="sheets", title="Orders", spec=SPEC, now=1_800_000_000)
    await tool.execute(
        {"operation": "keep_current", "node": second.id, "track": "orders", "every_minutes": 30},
        _ctx(),
    )
    listed = (await tool.execute({"operation": "list"}, _ctx())).output
    assert [row["id"] for row in listed] == [second.id, first.id]
    assert set(listed[0]) == {
        "id", "type", "title", "version", "updated_at", "kept_current", "refreshing",
        "every_minutes",
    }
    assert (listed[0]["kept_current"], listed[0]["refreshing"], listed[0]["every_minutes"]) == (
        True, True, 30,
    )
    assert (listed[1]["kept_current"], listed[1]["refreshing"]) == (False, False)


async def test_revert_puts_the_earlier_content_back(tmp_path: Path, cards) -> None:
    tool, store = _tool(tmp_path)
    node = store.create(type="docs", title="Plan", spec=SPEC)
    never = await tool.execute({"operation": "revert", "node": node.id}, _ctx())
    assert not never.success and "no earlier version" in never.error
    store.update(node.id, spec={"blocks": [{"text": "Changed"}]})
    result = await tool.execute({"operation": "revert", "node": node.id}, _ctx())
    assert result.success and "version 3" in result.output
    assert store.get(node.id).spec == SPEC
    assert len(cards) == 1


# ------------------------------------------------------ keep_current, stop


async def test_keep_current_and_stop(tmp_path: Path, cards, upkeep) -> None:
    tool, store = _tool(tmp_path)
    node = store.create(type="sheets", title="Orders", spec=SPEC)
    kept = await tool.execute(
        {"operation": "keep_current", "node": "Orders", "track": "open orders in Gmail",
         "every_minutes": 45},
        _ctx(),
    )
    assert kept.success and "refreshes every 45 minutes" in kept.output
    live = store.get(node.id)
    assert live.refreshing and live.track == "open orders in Gmail"

    stopped = await tool.execute({"operation": "stop", "node": node.id}, _ctx())
    assert stopped.success and "no longer refreshes" in stopped.output
    assert not store.get(node.id).refreshing and store.get(node.id).spec == SPEC
    assert upkeep == [f"start:{node.id}:open orders in Gmail:45", f"stop:{node.id}"]
    assert cards == []


async def test_keep_current_needs_a_track_and_a_running_scheduler(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    node = store.create(type="sheets", title="Orders", spec=SPEC)
    no_track = await tool.execute({"operation": "keep_current", "node": node.id}, _ctx())
    assert not no_track.success and "'track' must say" in no_track.error
    down = await tool.execute(
        {"operation": "keep_current", "node": node.id, "track": "orders"}, _ctx()
    )
    assert not down.success and "The agent society is not running" in down.error
    # Stopping works while the society is down: the node is marked stopped.
    assert (await tool.execute({"operation": "stop", "node": node.id}, _ctx())).success


async def test_bad_calls_say_what_to_fix(tmp_path: Path) -> None:
    tool, _ = _tool(tmp_path)
    for args in (None, {}, {"operation": "explode"}):
        result = await tool.execute(args, _ctx())
        assert not result.success and "'operation' must be one of guide, create" in result.error
    for operation in ("update", "get", "revert", "keep_current", "stop"):
        missing = await tool.execute({"operation": operation}, _ctx())
        assert not missing.success and f"'node' is required for {operation}" in missing.error
        unknown = await tool.execute({"operation": operation, "node": "nowhere"}, _ctx())
        assert not unknown.success and "'nowhere'" in unknown.error


async def test_an_archive_that_cannot_be_written_is_said_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool, store = _tool(tmp_path)

    def full(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("No space left on device")

    monkeypatch.setattr(store, "create", full)
    result = await tool.execute(
        {"operation": "create", "type": "docs", "title": "T", "spec": SPEC}, _ctx()
    )
    assert not result.success and "No space left on device" in result.error


# ------------------------------------------------------------ registration


def test_the_tool_is_router_reachable_registered_and_never_gated() -> None:
    from dodaios.brain.delegate_tool import DELEGATE_OVERLAPS
    from dodaios.brain.factory import ROUTER_TOOLS
    from dodaios.brain.tool_shortlist import DEFAULT_DIRECT
    from dodaios.society.capabilities import capability_id_for_tool

    assert "node" in ROUTER_TOOLS
    assert NodeTool.name == "node" and NodeTool.risk_tier == "monitor"
    # The factory builds it without arguments; the store opens on first use.
    assert NodeTool()._store is None
    # The lead sees it directly: it is not a hand-off behind delegate.
    assert "node" in DEFAULT_DIRECT and "node" not in DELEGATE_OVERLAPS
    # The lead's refresh routine (a society seat) may hold the tool.
    assert capability_id_for_tool("node") == "plugin:node"


def test_the_entry_point_resolves_to_the_tool() -> None:
    """Read from pyproject: the installed metadata of a long-lived checkout may
    not know a new entry point until the package is installed again."""
    import importlib

    declared = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    target = declared["project"]["entry-points"]["jarvis.tool"]["node"]
    module, _, attr = target.partition(":")
    assert getattr(importlib.import_module(module), attr) is NodeTool


# -------------------------------------------------------------------- look


async def test_look_hands_the_pictures_to_the_model(
    tmp_path: Path, cards, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool, store = _tool(tmp_path)
    await tool.execute(
        {"operation": "create", "type": "docs", "title": "Plan", "spec": SPEC}, _ctx()
    )
    (node,) = store.list_nodes()
    seen: dict[str, Any] = {}

    def fake_look(found, html, *, slides=None, theme=""):
        seen.update(id=found.id, html=html, slides=slides)
        return ["AAAA", "BBBB"], "The page from the top, in 2 piece(s)."

    monkeypatch.setattr(node_tool, "look", fake_look)
    result = await tool.execute(
        {"operation": "look", "node": node.id, "slides": [2, "x", 3]}, _ctx()
    )
    assert result.success, result.error
    assert seen["id"] == node.id and b"<p>First</p>" in seen["html"]
    assert seen["slides"] == [2, 3]
    assert [a["data"] for a in result.artifacts] == ["AAAA", "BBBB"]
    assert all(a["type"] == "image" and a["mime"] == "image/jpeg" for a in result.artifacts)
    assert "2 piece(s)" in result.output and "fix every weak point" in result.output


async def test_look_without_a_browser_says_how_to_go_on(
    tmp_path: Path, cards, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool, store = _tool(tmp_path)
    await tool.execute(
        {"operation": "create", "type": "docs", "title": "Plan", "spec": SPEC}, _ctx()
    )

    def no_browser(*_args, **_kwargs):
        raise node_tool.LookError("no Chromium-family browser is installed")

    monkeypatch.setattr(node_tool, "look", no_browser)
    result = await tool.execute({"operation": "look", "node": "Plan"}, _ctx())
    assert not result.success
    assert "no Chromium-family browser" in result.error and "'get'" in result.error
