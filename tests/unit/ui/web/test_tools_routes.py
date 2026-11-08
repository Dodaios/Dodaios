"""The tools endpoint reports the BrainManager's effective live surface."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.ui.web.tools_routes import router


def _tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=f"{name} description",
        risk_tier="monitor",
        schema={"type": "object"},
    )


def test_lists_effective_brain_tools_not_partial_mcp_registry() -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.brain = SimpleNamespace(
        _tools={
            "wiki-recall": _tool("wiki-recall"),
            "cli_gh": _tool("cli_gh"),
            "notebooklm-mcp/search": _tool("notebooklm-mcp/search"),
        }
    )
    app.state.tool_registry = {"partial/only": _tool("partial/only")}

    with TestClient(app) as client:
        body = client.get("/api/tools").json()

    assert body["total"] == 3
    assert {item["name"] for item in body["tools"]} == {
        "wiki-recall",
        "cli_gh",
        "notebooklm-mcp/search",
    }
    assert body["by_source"] == {"mcp": 1, "cli": 1, "native": 1}


def test_falls_back_to_user_mcp_registry_before_brain_ready() -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.brain = None
    app.state.tool_registry = {"weather/search": _tool("weather/search")}

    with TestClient(app) as client:
        body = client.get("/api/tools").json()

    assert body["total"] == 1
    assert body["tools"][0]["name"] == "weather/search"
    assert body["by_source"]["mcp"] == 1


def test_list_tools_reconciles_stale_brain_surface_before_listing(monkeypatch) -> None:
    """Issue #1189: GET /api/tools reconciles the brain tool surface before reading
    brain._tools so MCP tools that connected after initial brain build appear
    even before the first chat turn.
    """
    from dodaios.brain import tool_surface

    app = FastAPI()
    app.include_router(router)

    brain = SimpleNamespace(
        _tools={"wiki-recall": _tool("wiki-recall")},
        _tool_surface_fp=frozenset(),
    )

    async def _refresh_async() -> None:
        brain._tools["tradingview/tv_quote"] = _tool("tradingview/tv_quote")

    brain.refresh_tools_async = _refresh_async
    app.state.brain = brain

    monkeypatch.setattr(
        tool_surface,
        "live_tool_surface_fingerprint",
        lambda: frozenset({"mcp:tradingview:tv_quote"}),
    )

    with TestClient(app) as client:
        body = client.get("/api/tools").json()

    assert body["total"] == 2
    assert body["by_source"] == {"mcp": 1, "cli": 0, "native": 1}
    assert {t["name"] for t in body["tools"]} == {"wiki-recall", "tradingview/tv_quote"}


def test_usage_reports_what_ran_and_what_never_did(tmp_path, monkeypatch) -> None:
    import json
    from datetime import datetime

    from dodaios.telemetry import tool_usage as usage

    day = datetime.now().date().isoformat()
    rows = [
        {"ts_ns": 1, "event": "ActionExecuted", "payload": {"tool_name": "wiki-recall"}},
        {"ts_ns": 2, "event": "ActionExecuted", "payload": {"tool_name": "wiki-recall"}},
    ]
    (tmp_path / f"{day}.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    monkeypatch.setattr(usage, "DEFAULT_DATA_DIR", tmp_path)

    app = FastAPI()
    app.include_router(router)
    app.state.brain = SimpleNamespace(
        _tools={"wiki-recall": _tool("wiki-recall"), "cli_gh": _tool("cli_gh")}
    )
    with TestClient(app) as client:
        body = client.get("/api/tools/usage", params={"days": 7}).json()

    assert body["window_days"] == 7
    assert body["total_calls"] == 2
    assert body["tools"][0]["tool"] == "wiki-recall"
    assert body["registered"] == 2
    assert body["never_used"] == ["cli_gh"]
