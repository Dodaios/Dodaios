"""The plugins list says when a connected CLI takes precedence (#601).

With the GitHub CLI connected, the brain hides the GitHub plugin's tools
unless the user names the plugin (``suppress_plugin_tools_covered_by_cli``).
The card used to say only "Connected · Live"; the list now carries
``covered_by_cli`` so the card can explain it.
"""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.marketplace.catalog import PluginCatalog, PluginSpec
from dodaios.marketplace.token_store import InMemoryBackend, Tokens, TokenStore
from dodaios.ui.web import marketplace_routes


def _catalog() -> PluginCatalog:
    def spec(plugin_id: str, name: str) -> PluginSpec:
        return PluginSpec(
            id=plugin_id,
            display_name=name,
            description=name,
            category="Developer",
            logo_slug=plugin_id,
            auth={
                "mode": "pat_paste",
                "token_creation_url": "https://example.test/tokens",
                "token_prefix": "tok",
                "validation_endpoint": "https://example.test/user",
                "instruction_md": "Paste a token.",
            },
        )

    return PluginCatalog(
        version=1,
        schema_version="test",
        plugins=[spec("github", "GitHub"), spec("vercel", "Vercel")],
    )


class _FakeCliRegistry:
    """Only the two calls the overlap lookup makes."""

    def __init__(self, active: list[str]) -> None:
        self._active = active

    def active_tools(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(name=f"cli_{name}") for name in self._active]

    def catalog(self) -> SimpleNamespace:
        specs = {
            "gh": SimpleNamespace(display_name="GitHub CLI"),
            "vercel": SimpleNamespace(display_name="Vercel CLI"),
        }
        return SimpleNamespace(all=lambda: specs)


def _client(monkeypatch, *, active_clis: list[str] | None, connected: list[str]) -> TestClient:
    store = TokenStore(InMemoryBackend())
    for plugin_id in connected:
        store.save(plugin_id, Tokens(access="tok"))
    monkeypatch.setattr(marketplace_routes, "load_catalog", _catalog)
    monkeypatch.setattr(marketplace_routes, "TokenStore", lambda: store)
    app = FastAPI()
    app.include_router(marketplace_routes.router)
    if active_clis is not None:
        app.state.cli_registry = _FakeCliRegistry(active_clis)
    return TestClient(app)


def _items(client: TestClient) -> dict[str, dict]:
    resp = client.get("/api/marketplace/plugins")
    assert resp.status_code == 200
    return {item["id"]: item for item in resp.json()["plugins"]}


def test_connected_plugin_names_the_cli_that_takes_precedence(monkeypatch):
    items = _items(_client(monkeypatch, active_clis=["gh"], connected=["github", "vercel"]))
    assert items["github"]["covered_by_cli"] == "gh"
    assert items["github"]["covered_by_cli_label"] == "GitHub CLI"
    # The Vercel CLI is not connected, so the Vercel plugin is used as usual.
    assert items["vercel"]["covered_by_cli"] is None


def test_no_hint_while_the_plugin_itself_is_not_connected(monkeypatch):
    items = _items(_client(monkeypatch, active_clis=["gh"], connected=[]))
    assert items["github"]["covered_by_cli"] is None


def test_no_hint_without_a_cli_registry(monkeypatch):
    items = _items(_client(monkeypatch, active_clis=None, connected=["github"]))
    assert items["github"]["covered_by_cli"] is None
    assert items["github"]["covered_by_cli_label"] is None
