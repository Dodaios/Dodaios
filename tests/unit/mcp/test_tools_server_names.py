"""The app's own MCP server answers to ``dodaios`` and, forever, to ``jarvis``.

A coding CLI names a tool after the server it mounted, so the server's name is
part of every tool name the app reads back: ``mcp__dodaios__gmail`` today,
``mcp__jarvis__gmail`` in every transcript, registration and session written
before the rename. One test per reader of such a name, each run under both
server names, so a reader that knows only one of them fails here by name.
"""

from __future__ import annotations

import ast
import json
import re
import sqlite3
from pathlib import Path

import pytest

import jarvis.core.branding as branding
from jarvis.core import mcp_names

_ROOT = Path(__file__).resolve().parents[3]

SERVERS = pytest.mark.parametrize("server", list(mcp_names.TOOLS_SERVER_NAMES))


# ---------------------------------------------------------------------------
# The names
# ---------------------------------------------------------------------------


def test_the_current_name_comes_first_and_the_earlier_one_stays() -> None:
    assert branding.MCP_TOOLS_SERVER_NAME == "dodaios"
    assert branding.LEGACY_MCP_TOOLS_SERVER_NAMES == ("jarvis",)
    assert mcp_names.TOOLS_SERVER_NAMES == ("dodaios", "jarvis")
    assert mcp_names.own_cli_tool_prefixes() == ("mcp__dodaios__", "mcp__jarvis__")
    assert mcp_names.cli_tool_name("gmail") == "mcp__dodaios__gmail"


@SERVERS
def test_a_call_to_the_apps_own_server_is_recognised(server: str) -> None:
    assert mcp_names.is_tools_server(server)
    assert mcp_names.own_cli_tool(f"mcp__{server}__gmail") == "gmail"
    # Everything after the server belongs to the tool, double underscores included.
    assert mcp_names.own_cli_tool(f"mcp__{server}__a__b") == "a__b"
    assert mcp_names.split_cli_tool_name(f"mcp__{server}__gmail") == (server, "gmail")


@pytest.mark.parametrize(
    "name", ["mcp__github__create_issue", "gmail", "mcp__dodaios", "mcp____x", "dodaios__gmail"]
)
def test_anything_else_is_not_the_apps_own_tool(name: str) -> None:
    assert mcp_names.own_cli_tool(name) is None


def test_the_frontend_restates_the_server_names() -> None:
    source = (_ROOT / "jarvis/ui/web/frontend/src/lib/branding.ts").read_text(encoding="utf-8")
    match = re.search(r"MCP_TOOLS_SERVER_NAMES[^=]*=\s*(\[[^\]]*\])", source)
    assert match is not None
    assert tuple(json.loads(match.group(1))) == mcp_names.TOOLS_SERVER_NAMES


def test_no_shipped_module_spells_the_server_name_into_a_tool_prefix() -> None:
    """A literal prefix knows one name; the helper knows every name."""
    offenders: list[str] = []
    for path in (_ROOT / "jarvis").rglob("*.py"):
        if "node_modules" in path.parts:
            continue
        source = path.read_text(encoding="utf-8-sig")
        if "jarvis" not in source and "dodaios" not in source:
            continue
        relative = path.relative_to(_ROOT).as_posix()
        docstrings = _docstring_nodes(ast.parse(source))
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if (node.lineno, node.col_offset) in docstrings:
                continue
            if _SPELLED_OUT.search(node.value):
                offenders.append(f"{relative}:{node.lineno}: {node.value[:60]!r}")
    assert not offenders, "use jarvis.core.mcp_names / branding:\n" + "\n".join(offenders)


_SPELLED_OUT = re.compile(r"mcp__(?:jarvis|dodaios)__|mcp_servers\.(?:jarvis|dodaios)\b")


def _docstring_nodes(tree: ast.AST) -> set[tuple[int, int]]:
    found: set[tuple[int, int]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", [])
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            found.add((body[0].value.lineno, body[0].value.col_offset))
    return found


# ---------------------------------------------------------------------------
# Readers that single out the app's own server
# ---------------------------------------------------------------------------


@SERVERS
def test_a_runtimes_own_spelling_is_normalised(server: str) -> None:
    """Hermes, OpenClaw and Grok each spell the same tool their own way."""
    from jarvis.agent_runtimes.acp import normalize_tool_name

    expected = f"mcp__{server}__society_memory_recall"
    for spelled in (
        f"mcp_{server}_society_memory_recall",
        f"{server}__society_memory_recall",
        f"{server}.society_memory_recall",
        expected,
    ):
        assert normalize_tool_name(spelled) == expected
    assert normalize_tool_name("terminal") == "terminal"
    assert normalize_tool_name("mcp__github__create_issue") == "mcp__github__create_issue"


@SERVERS
def test_a_normalised_runtime_call_reaches_the_family_it_belongs_to(server: str) -> None:
    """The two readers compose: what the runtime reports is what the island shows."""
    from jarvis.agent_runtimes.acp import normalize_tool_name
    from jarvis.society.checkpoints import family_of_tool

    assert family_of_tool(normalize_tool_name(f"{server}__gmail"), cli_seat=True) == "comms"


@SERVERS
def test_the_society_classifies_a_call_by_the_tool_behind_the_server(server: str) -> None:
    from jarvis.society.checkpoints import family_of_tool

    assert family_of_tool(f"mcp__{server}__google_drive", cli_seat=True) == "plugin"
    assert family_of_tool(f"mcp__{server}__society_run_skill", cli_seat=True) == "skill"
    assert family_of_tool(f"mcp__{server}__gmail", cli_seat=True) == "comms"
    # Any other server stays an MCP capability, whatever its tool is called.
    assert family_of_tool("mcp__github__gmail", cli_seat=True) == "mcp"


@SERVERS
@pytest.mark.parametrize("hashed", [False, True])
def test_a_resumed_hermes_conversation_drops_its_pinned_tool_list(
    tmp_path: Path, server: str, hashed: bool
) -> None:
    """Without this a conversation resumed after the rename keeps offering dead tools."""
    from jarvis.agent_runtimes.tool_snapshot import refresh_tool_search_cache

    name = f"mcp__{server}__society_ask_user"
    snapshot = (
        json.dumps({"tools": [{"function": {"name": name}}, {"function": {"name": "tool_search"}}]})
        if hashed
        else json.dumps([name, "tool_search"])
    )
    pin = "snapshot-hash" if hashed else snapshot
    with sqlite3.connect(tmp_path / "state.db") as db:
        db.executescript(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, tool_names TEXT);"
            "CREATE TABLE system_prompts (hash TEXT PRIMARY KEY, prompt TEXT);"
        )
        db.execute("INSERT INTO sessions VALUES (?, ?)", ("selected", pin))
        db.execute("INSERT INTO system_prompts VALUES (?, ?)", ("snapshot-hash", snapshot))

    assert refresh_tool_search_cache(tmp_path, "selected")
    with sqlite3.connect(tmp_path / "state.db") as db:
        assert db.execute("SELECT tool_names FROM sessions").fetchone() == (None,)


def test_a_hermes_tool_list_without_the_apps_tools_is_kept(tmp_path: Path) -> None:
    from jarvis.agent_runtimes.tool_snapshot import refresh_tool_search_cache

    pin = json.dumps(["mcp__github__create_issue", "terminal"])
    with sqlite3.connect(tmp_path / "state.db") as db:
        db.executescript(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, tool_names TEXT);"
            "CREATE TABLE system_prompts (hash TEXT PRIMARY KEY, prompt TEXT);"
        )
        db.execute("INSERT INTO sessions VALUES (?, ?)", ("selected", pin))

    assert not refresh_tool_search_cache(tmp_path, "selected")


# ---------------------------------------------------------------------------
# Readers that strip any server: the bare tool decides
# ---------------------------------------------------------------------------


@SERVERS
def test_an_approval_is_matched_on_the_bare_tool(server: str) -> None:
    from jarvis.agent_chat.approval_bridge import _bare

    assert _bare(f"mcp__{server}__open-app") == "open-app"


@SERVERS
def test_an_agents_ask_rule_still_gates_the_tool(
    server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A permission rule must not fall away because the server was renamed."""
    from types import SimpleNamespace

    from jarvis.society import surface
    from jarvis.society.capabilities import capability_id_for_tool

    capability = capability_id_for_tool("gmail")
    assert capability is not None
    agent = SimpleNamespace(approval_rules={"require_approval": [capability]})
    monkeypatch.setattr(
        surface, "current_runtime", lambda: SimpleNamespace(cached_agent=lambda _id: agent)
    )
    monkeypatch.setattr(surface, "agent_id_of", lambda _session: "scout")

    assert surface.requires_explicit_approval("society:scout", f"mcp__{server}__gmail", {})
    assert surface.requires_explicit_approval("society:scout", "gmail", {})
    assert not surface.requires_explicit_approval(
        "society:scout", f"mcp__{server}__google_drive", {}
    )


@SERVERS
def test_the_pet_reads_the_action_behind_the_server(server: str) -> None:
    from jarvis.ui.pets.actions import action_for_tool

    assert action_for_tool(f"mcp__{server}__web_search") == "searching"
    assert action_for_tool(f"mcp__{server}__open-app") == "working"


@SERVERS
def test_the_tools_listing_marks_the_call_as_mcp(server: str) -> None:
    from types import SimpleNamespace

    from jarvis.ui.web.tools_routes import _tool_to_dict

    assert _tool_to_dict(f"mcp__{server}__gmail", SimpleNamespace())["source"] == "mcp"


@SERVERS
def test_the_realtime_budget_files_the_call_under_mcp(server: str) -> None:
    from jarvis.realtime.tools import _BUDGET_DROP_FAMILIES

    name = f"mcp__{server}__gmail"
    families = [family for family, pattern in _BUDGET_DROP_FAMILIES if pattern.search(name)]
    assert families[:1] == ["mcp"]


@SERVERS
def test_mission_evidence_names_a_codex_call_after_its_server(server: str) -> None:
    from jarvis.missions import stream_evidence

    stream = json.dumps(
        {
            "type": "item.completed",
            "item": {"type": "mcp_tool_call", "server": server, "tool": "gmail", "status": "ok"},
        }
    )
    assert f"mcp__{server}__gmail" in stream_evidence.normalize_worker_stream(stream)
