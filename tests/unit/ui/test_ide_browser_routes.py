"""REST routes of the IDE browser panel: honest answers without a desktop shell."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.ui import browser_embed
from dodaios.ui.web.ide_browser_routes import router


class FakeEmbed:
    def __init__(self, supported: bool = True) -> None:
        self._supported = supported
        self.calls: list[tuple[str, Any]] = []

    def supported(self) -> bool:
        return self._supported

    def status(self) -> dict[str, Any]:
        return {"available": self._supported, "state": "idle", "reason": "",
                "browser": "", "profile": "", "visible": False}

    def launch(self, browser: str, profile: str, url: str | None, host: int) -> dict[str, Any]:
        self.calls.append(("launch", (browser, profile, url, host)))
        return {**self.status(), "ok": True, "state": "embedded"}

    def place(self, owner: str, host: int, rect: Any, dpr: float, visible: bool) -> dict[str, Any]:
        self.calls.append(("place", (owner, host, rect, dpr, visible)))
        return {**self.status(), "ok": True}

    def release(self, *, close: bool, focus: bool = False) -> dict[str, Any]:
        self.calls.append(("release", (close, focus)))
        return {**self.status(), "ok": True}


def _client(desktop: Any, embed: FakeEmbed, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(browser_embed, "get_embed", lambda: embed)
    app = FastAPI()
    app.include_router(router)
    app.state.desktop_app = desktop
    return TestClient(app)


def _desktop(hwnd: int | None = 4242) -> SimpleNamespace:
    seen: list[str | None] = []

    def host(view: str | None) -> int | None:
        seen.append(view)
        return hwnd

    return SimpleNamespace(browser_panel_host=host, seen=seen)


def test_status_without_a_desktop_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(None, FakeEmbed(), monkeypatch)
    body = client.get("/api/ide-browser/status").json()
    assert body["available"] is False
    assert body["reason"] == "no_desktop_shell"


def test_status_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(_desktop(), FakeEmbed(supported=False), monkeypatch)
    body = client.get("/api/ide-browser/status").json()
    assert body == {**body, "available": False, "reason": "unsupported_platform"}


def test_status_without_a_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dodaios.ui.browser_profiles.installed_browsers", lambda: [])
    client = _client(_desktop(), FakeEmbed(), monkeypatch)
    assert client.get("/api/ide-browser/status").json()["reason"] == "no_browser"


def test_status_lists_browsers(monkeypatch: pytest.MonkeyPatch) -> None:
    browsers = [{"id": "chrome", "label": "Google Chrome", "profiles": [], "last_used": None}]
    monkeypatch.setattr("dodaios.ui.browser_profiles.installed_browsers", lambda: browsers)
    client = _client(_desktop(), FakeEmbed(), monkeypatch)
    body = client.get("/api/ide-browser/status").json()
    assert body["available"] is True
    assert body["browsers"] == browsers


def test_launch_targets_the_window_of_the_view(monkeypatch: pytest.MonkeyPatch) -> None:
    desktop, embed = _desktop(), FakeEmbed()
    client = _client(desktop, embed, monkeypatch)
    body = client.post("/api/ide-browser/launch", json={
        "browser": "chrome", "profile": "Profile 3",
        "url": "https://github.com/", "view": "agentic-ide",
    }).json()
    assert body["ok"] is True
    assert desktop.seen == ["agentic-ide"]
    assert embed.calls == [("launch", ("chrome", "Profile 3", "https://github.com/", 4242))]


def test_launch_without_a_window(monkeypatch: pytest.MonkeyPatch) -> None:
    embed = FakeEmbed()
    client = _client(_desktop(hwnd=None), embed, monkeypatch)
    payload = {"browser": "chrome", "profile": "Default"}
    body = client.post("/api/ide-browser/launch", json=payload).json()
    assert body["ok"] is False
    assert embed.calls == []


def test_place_passes_the_rectangle(monkeypatch: pytest.MonkeyPatch) -> None:
    desktop, embed = _desktop(), FakeEmbed()
    client = _client(desktop, embed, monkeypatch)
    client.post("/api/ide-browser/place", json={
        "owner": "panel-1", "visible": True, "dpr": 1.5,
        "rect": {"x": 10, "y": 20, "width": 300, "height": 400},
    })
    assert embed.calls == [("place", (
        "panel-1", 4242, {"x": 10.0, "y": 20.0, "width": 300.0, "height": 400.0}, 1.5, True,
    ))]
    assert desktop.seen == [None]


def test_place_rejects_a_bad_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(_desktop(), FakeEmbed(), monkeypatch)
    response = client.post("/api/ide-browser/place", json={"owner": "p", "visible": True, "dpr": 0})
    assert response.status_code == 422


@pytest.mark.parametrize(("close", "focus"), [(True, False), (False, True)])
def test_release(monkeypatch: pytest.MonkeyPatch, close: bool, focus: bool) -> None:
    embed = FakeEmbed()
    client = _client(_desktop(), embed, monkeypatch)
    client.post("/api/ide-browser/release", json={"close": close})
    assert embed.calls == [("release", (close, focus))]


def test_embed_refuses_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser_embed, "_is_windows", lambda: False)
    embed = browser_embed.ChromeEmbed()
    result = embed.launch("chrome", "Default", None, 1)
    assert result["ok"] is False
    assert result["reason"] == "unsupported"
    assert embed.place("p", 1, None, 1.0, True)["ok"] is False


def test_embed_rejects_bad_input_before_starting_anything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser_embed, "_is_windows", lambda: True)
    # A browser that never ran lists no profiles: only its Default may open.
    monkeypatch.setattr(browser_embed, "read_profiles", lambda _user_data: ([], None))
    embed = browser_embed.ChromeEmbed()
    assert embed.launch("netscape", "Default", None, 1)["reason"] == "unknown_browser"
    assert embed.launch("chrome", "Profile 5", None, 1)["reason"] == "bad_profile"
    assert embed.launch("chrome", "--user-data-dir=x", None, 1)["reason"] == "bad_profile"
    monkeypatch.setattr(browser_embed, "read_profiles", lambda _dir: ([], None))
    # Without a profile list only the default profile may be opened.
    assert embed.launch("chrome", "Profile 5", None, 1)["reason"] == "bad_profile"
    monkeypatch.setattr(browser_embed, "find_browser_exe", lambda spec: None)
    assert embed.launch("chrome", "Default", None, 1)["reason"] == "browser_missing"
    assert embed._thread is None


def test_embed_refuses_to_launch_after_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser_embed, "_is_windows", lambda: True)
    monkeypatch.setattr(browser_embed, "read_profiles", lambda _dir: ([], None))
    monkeypatch.setattr(browser_embed, "find_browser_exe", lambda spec: "chrome.exe")
    embed = browser_embed.ChromeEmbed()
    embed.shutdown()
    assert embed.launch("chrome", "Default", None, 1)["reason"] == "shutting_down"
    assert embed._thread is None
