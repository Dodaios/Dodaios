"""Login import routes: detection reads no key, results carry counts, never values."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.society.browser import login_import
from dodaios.society.browser.login_import import LoginImportError, LoginSource
from dodaios.ui.web.society_browser_routes import router
from dodaios.ui.web.surface_security import COOKIE_NAME, SurfaceSecurity
from tests.fakes.fake_browser_profiles import ProfileRoster, already_started

pytestmark = pytest.mark.no_auto_web_auth
COOKIE_VALUE = "fixture-cookie-value-91c2"
IMPORT = "/api/society/agents/{agent_id}/browser/import-logins"


class FakeLive:
    def __init__(self):
        self.sessions = {}
        self.calls = []
        self.error = None

    async def import_logins(self, agent, browser, profile):
        self.calls.append((agent.agent_id, browser, profile))
        if self.error:
            raise self.error
        # The parent result may hold sites and counts; the route must pass no more.
        return {
            "imported": 3,
            "failed": 1,
            "expired": 2,
            "skipped": 0,
            "sites": {"example.com": 2, "example.org": 1},
            "browser": browser,
            "browser_name": "Google Chrome",
            "profile": profile,
            "imported_at": 1_800_000_000.0,
            "started": True,
            "cookies": [{"name": "sid", "value": COOKIE_VALUE}],
        }

    def login_source_for(self, agent):
        return {
            "browser": "chrome",
            "profile": "Default",
            "imported_at": 1.0,
            "imported": 3,
            "sites": 2,
            "status": "ok",
            "source_mtime": 0.5,
        }


@pytest.fixture
def api(monkeypatch, tmp_path):
    app = FastAPI()
    app.include_router(router)
    live = FakeLive()
    browser = SimpleNamespace(
        live=live, status_for=lambda agent: {"installed": True, "mode": "own"}
    )
    app.state.society = SimpleNamespace(
        roster=ProfileRoster(),
        browser=browser,
        ensure_started=already_started,
    )
    source = LoginSource(
        spec=login_import._BY_KEY["chrome"],
        profile="Default",
        name="Person 1",
        email="owner@example.com",
        user_data=tmp_path / "Chrome",
        cookie_db=tmp_path / "Chrome" / "Default" / "Cookies",
        last_used=True,
        supported=True,
        cookies=42,
    )
    monkeypatch.setattr(login_import, "detect_sources", lambda: [source])

    def forbidden(*_args, **_kwargs):
        raise AssertionError("listing sources must never read a key")

    monkeypatch.setattr(login_import, "_mac_key", forbidden)
    monkeypatch.setattr(login_import, "decryptor_for", forbidden)
    client = TestClient(
        SurfaceSecurity(app, session_validator=lambda value: value == "login-import-fixture"),
        base_url="http://127.0.0.1:8765",
        client=("127.0.0.1", 40000),
        headers={"Origin": "http://127.0.0.1:8765", "Sec-Fetch-Site": "same-origin"},
    )
    client.cookies.set(COOKIE_NAME, "login-import-fixture")
    return app, client, live, tmp_path


def test_sources_list_detection_only_without_paths(api):
    _app, client, _live, tmp_path = api
    body = client.get("/api/society/browser/login-sources").json()
    assert body["sources"][0]["id"] == "chrome:Default"
    assert body["sources"][0]["cookies"] == 42
    assert body["sources"][0]["email"] == "owner@example.com"
    assert str(tmp_path) not in json.dumps(body)


def test_import_is_dangerous_and_returns_counts_and_sites_only(api):
    app, client, live, _tmp = api
    assert app.openapi()["paths"][IMPORT]["post"]["x-jarvis-dangerous"] is True
    response = client.post(
        IMPORT.replace("{agent_id}", "lead"), json={"browser": "chrome", "profile": "Default"}
    )
    assert response.status_code == 200
    body = response.json()
    assert live.calls == [("lead", "chrome", "Default")]
    assert body["imported"] == 3 and body["site_count"] == 2
    assert body["sites"] == {"example.com": 2, "example.org": 1}
    assert "cookies" not in body and COOKIE_VALUE not in response.text


@pytest.mark.parametrize(
    "error,status",
    [
        (LoginImportError("keychain_denied", "macOS did not allow access"), 403),
        (LoginImportError("source_locked", "Close that browser"), 409),
        (LookupError("not found"), 404),
        (ValueError("Logins can only be imported into a Dodaios browser profile"), 422),
        (RuntimeError(f"worker said {COOKIE_VALUE}"), 503),
    ],
)
def test_import_failures_are_visible_and_leak_nothing(api, error, status):
    _app, client, live, _tmp = api
    live.error = error
    response = client.post(
        IMPORT.replace("{agent_id}", "lead"), json={"browser": "chrome", "profile": "Default"}
    )
    assert response.status_code == status
    assert COOKIE_VALUE not in response.text


def test_missing_agent_and_bad_body_import_nothing(api):
    _app, client, live, _tmp = api
    assert (
        client.post(
            IMPORT.replace("{agent_id}", "missing"),
            json={"browser": "chrome", "profile": "Default"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            IMPORT.replace("{agent_id}", "lead"), json={"browser": "", "profile": "Default"}
        ).status_code
        == 422
    )
    assert live.calls == []


def test_open_status_names_the_remembered_source(api):
    _app, client, _live, _tmp = api
    body = client.get("/api/society/agents/lead/browser/open").json()
    assert body["login_source"] == {
        "browser": "chrome",
        "profile": "Default",
        "imported_at": 1.0,
        "imported": 3,
        "sites": 2,
        "status": "ok",
    }
