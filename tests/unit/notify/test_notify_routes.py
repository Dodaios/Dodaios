"""``/api/notify``: settings, reminders, snooze and done."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.memory.vault import MemoryVault
from dodaios.memory.vault import runtime as vault_runtime
from dodaios.notify import notifier as notifier_module
from dodaios.notify.notifier import Verdict
from dodaios.notify.settings import forget_cached
from dodaios.ui.web import notify_routes
from dodaios.ui.web.notify_routes import router

NOW = datetime(2026, 11, 10, 10, 30, tzinfo=ZoneInfo("Europe/Berlin"))


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    vault = MemoryVault(
        tmp_path / "vault.db", clock=lambda: NOW.astimezone(UTC).isoformat(timespec="seconds")
    )
    vault_runtime.set_active(vault)
    settings_path = tmp_path / "settings.json"
    forget_cached()
    monkeypatch.setattr(notify_routes, "load_settings", lambda: _load(settings_path))
    monkeypatch.setattr(notify_routes, "save_settings", lambda patch: _save(patch, settings_path))
    monkeypatch.setattr(notify_routes.reminders, "person_zone", lambda _n=None: NOW.tzinfo)
    monkeypatch.setattr(notify_routes, "datetime", _FixedNow)
    app = FastAPI()
    app.include_router(router)
    app.state.channel_manager = None
    app.state.config = None
    with TestClient(app) as test_client:
        yield test_client
    vault_runtime.set_active(None)
    forget_cached()


def _load(path: Path) -> Any:
    from dodaios.notify.settings import load_settings

    return load_settings(path)


def _save(patch: dict[str, Any], path: Path) -> Any:
    from dodaios.notify.settings import save_settings

    return save_settings(patch, path)


class _FixedNow(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        return NOW.astimezone(tz) if tz else NOW


def test_settings_read_and_patch(client: TestClient) -> None:
    body = client.get("/api/notify/settings").json()
    assert body["enabled"] is True and body["kinds"]["approval"] is True
    saved = client.put(
        "/api/notify/settings",
        json={"kinds": {"approval": False}, "quiet_hours": {"enabled": True, "end": "08:30"}},
    ).json()
    assert saved["kinds"]["approval"] is False and saved["kinds"]["reminder"] is True
    assert saved["quiet_hours"] == {"enabled": True, "start": "22:00", "end": "08:30"}
    assert (
        client.put("/api/notify/settings", json={"quiet_hours": {"start": "9"}}).status_code == 400
    )


def test_a_reminder_from_plain_speech(client: TestClient) -> None:
    created = client.post(
        "/api/notify/reminders", json={"text": "remind me Friday at 9 about the taxes"}
    )
    assert created.status_code == 201
    row = created.json()
    assert row["text"] == "the taxes" and row["reminder"] is True and row["has_time"] is True
    assert row["due_at"] == "2026-11-13T08:00:00+00:00"
    listed = client.get("/api/notify/reminders?days=7").json()["items"]
    assert [r["id"] for r in listed] == [row["id"]]
    # Without a time the route says so instead of guessing.
    vague = client.post("/api/notify/reminders", json={"text": "mail Anna"}).json()
    assert vague == {"needs_time": True, "text": "mail Anna"}
    assert client.post("/api/notify/reminders", json={"text": ""}).status_code == 400


def test_snooze_and_done(client: TestClient) -> None:
    row = client.post(
        "/api/notify/reminders", json={"text": "taxes", "when": "in 10 minutes"}
    ).json()
    moved = client.post(f"/api/notify/reminders/{row['id']}/snooze", json={"minutes": 90}).json()
    assert moved["id"] != row["id"] and moved["due_at"] == "2026-11-10T11:00:00+00:00"
    tomorrow = client.post(
        f"/api/notify/reminders/{moved['id']}/snooze", json={"until": "tomorrow"}
    ).json()
    assert tomorrow["due_at"] == "2026-11-11T08:00:00+00:00"
    assert client.post(f"/api/notify/reminders/{tomorrow['id']}/done").json() == {"ok": True}
    assert client.post(f"/api/notify/reminders/{tomorrow['id']}/done").status_code == 404
    assert client.post("/api/notify/reminders/nope/snooze", json={}).status_code == 404
    bad = client.post(f"/api/notify/reminders/{row['id']}/snooze", json={"until": "whenever"})
    assert bad.status_code == 400


def test_capture_splits_a_dump(client: TestClient) -> None:
    rows = client.post(
        "/api/notify/reminders/capture", json={"text": "tomorrow dentist, buy milk"}
    ).json()["items"]
    assert [(r["text"], r["reminder"]) for r in rows] == [("dentist", True), ("buy milk", False)]


def test_telegram_state_without_a_channel(client: TestClient) -> None:
    assert client.get("/api/notify/telegram").json() == {"connected": False, "owner_known": False}


def test_test_notification_needs_a_notifier(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notifier_module, "_current", None)
    assert client.post("/api/notify/test").status_code == 503

    class _Notifier:
        async def notify(self, kind: str, title: str, body: str, **kw: Any) -> Verdict:
            assert kind == "reminder" and kw["ignore_focus"] is True
            assert title == "Notifications are on"
            return Verdict(True, how="shown")

    monkeypatch.setattr(notifier_module, "_current", _Notifier())
    assert client.post("/api/notify/test").json() == {"shown": True, "held": "", "how": "shown"}


def test_without_a_vault_the_routes_say_so(tmp_path: Path) -> None:
    vault_runtime.set_active(None)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/api/notify/reminders").status_code == 503
