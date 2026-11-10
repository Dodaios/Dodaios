"""Settings, quiet hours, the desktop backends and the notifier's gate."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from dodaios.notify import desktop
from dodaios.notify.notifier import (
    HELD_KIND,
    HELD_LOOKING,
    HELD_OFF,
    HELD_QUIET,
    HELD_UNKNOWN_KIND,
    NotificationOpened,
    Notifier,
)
from dodaios.notify.settings import (
    KINDS,
    NotifySettings,
    QuietHours,
    forget_cached,
    load_settings,
    save_settings,
)

# ------------------------------------------------------------------ settings


def test_defaults_are_on_and_quiet_hours_off() -> None:
    settings = NotifySettings()
    assert settings.enabled is True
    assert all(settings.allows(kind) for kind in KINDS)
    assert settings.quiet_hours.enabled is False
    assert settings.telegram_approvals is True


def test_settings_round_trip_through_the_file(tmp_path: Path) -> None:
    path = tmp_path / "notify" / "settings.json"
    forget_cached()
    assert load_settings(path) == NotifySettings()
    saved = save_settings(
        {"kinds": {"finished": False}, "quiet_hours": {"enabled": True, "start": "23:00"}}, path
    )
    assert saved.allows("finished") is False
    assert saved.allows("reminder") is True
    assert saved.quiet_hours == QuietHours(enabled=True, start="23:00", end="07:00")
    forget_cached(path)
    assert load_settings(path) == saved


def test_a_bad_clock_falls_back_and_unknown_keys_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    saved = save_settings({"quiet_hours": {"start": "25:99"}, "colour": "gold"}, path)
    assert saved.quiet_hours.start == "22:00"
    assert "colour" not in saved.to_dict()


def test_an_unreadable_file_means_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    forget_cached(path)
    assert load_settings(path) == NotifySettings()


@pytest.mark.parametrize(
    ("start", "end", "hour", "inside"),
    [
        ("22:00", "07:00", 23, True),
        ("22:00", "07:00", 3, True),
        ("22:00", "07:00", 7, False),
        ("22:00", "07:00", 12, False),
        ("13:00", "14:00", 13, True),
        ("13:00", "14:00", 14, False),
        ("13:00", "13:00", 13, False),  # an empty window never covers
    ],
)
def test_quiet_hours_cover_windows_that_cross_midnight(
    start: str, end: str, hour: int, inside: bool
) -> None:
    quiet = QuietHours(enabled=True, start=start, end=end)
    assert quiet.covers(datetime(2026, 11, 10, hour, 0)) is inside
    assert (
        QuietHours(enabled=False, start=start, end=end).covers(datetime(2026, 11, 10, hour))
        is False
    )


# ------------------------------------------------------------------- desktop


def test_show_without_text_fails_honestly() -> None:
    assert desktop.show("", "") == desktop.FAILED


def test_show_on_an_unknown_platform_is_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(desktop.shutil, "which", lambda _name: None)
    assert desktop.show("Reminder", "taxes") == desktop.UNSUPPORTED


def test_linux_and_macos_spawn_their_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class _Proc:
        def __init__(self, argv: list[str], **_kw: Any) -> None:
            calls.append(argv)

    monkeypatch.setattr(desktop.subprocess, "Popen", _Proc)
    monkeypatch.setattr(desktop.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(sys, "platform", "linux")
    assert desktop.show("Reminder", "taxes") == desktop.SHOWN_NO_CLICK
    assert calls[-1][0].endswith("notify-send") and calls[-1][-2:] == ["Reminder", "taxes"]
    monkeypatch.setattr(sys, "platform", "darwin")
    assert desktop.show("Reminder", 'say "hi"') == desktop.SHOWN_NO_CLICK
    assert calls[-1][0].endswith("osascript")
    assert 'say \\"hi\\"' in calls[-1][-1]


def test_windows_prefers_the_toast_library_and_falls_back_to_powershell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    shown: list[dict[str, Any]] = []

    class _Toaster:
        def notification_active(self) -> bool:
            return False

        def show_toast(self, title: str, msg: str, **kwargs: Any) -> bool:
            shown.append({"title": title, "msg": msg, **kwargs})
            return True

    monkeypatch.setattr(desktop, "_toaster", None)
    monkeypatch.setattr(desktop, "_toaster_factory", _Toaster)
    clicked: list[str] = []
    assert desktop.show("Reminder", "taxes", on_click=lambda: clicked.append("x")) == desktop.SHOWN
    assert shown[0]["threaded"] is True and shown[0]["duration"] == desktop.TOAST_SECONDS
    shown[0]["callback_on_click"]()
    assert clicked == ["x"]

    # Library busy: PowerShell takes over, with the text escaped for the toast XML.
    class _Busy(_Toaster):
        def notification_active(self) -> bool:
            return True

    monkeypatch.setattr(desktop, "_toaster", _Busy())
    argv: list[list[str]] = []
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda a, **_k: argv.append(a))
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "powershell.exe")
    assert desktop.show("A & B", "it's <late>") == desktop.SHOWN_NO_CLICK
    script = argv[0][-1]
    assert "A &amp; B" in script and "it''s &lt;late&gt;" in script
    assert 'audio silent="true"' in script


def test_long_text_is_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    argv: list[list[str]] = []
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda a, **_k: argv.append(a))
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/notify-send")
    desktop.show("t" * 200, "b" * 1000)
    assert len(argv[0][-2]) == desktop.TITLE_CHARS
    assert len(argv[0][-1]) == desktop.BODY_CHARS


# ------------------------------------------------------------------ notifier


class _Bus:
    def __init__(self) -> None:
        self.published: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.published.append(event)


def _notifier(
    settings: NotifySettings | None = None,
    *,
    focused: bool = False,
    how: str = desktop.SHOWN,
    bus: _Bus | None = None,
    clock: datetime | None = None,
) -> tuple[Notifier, list[dict[str, Any]]]:
    shown: list[dict[str, Any]] = []

    def _show(title: str, body: str, *, on_click: Any = None) -> str:
        shown.append({"title": title, "body": body, "on_click": on_click})
        return how

    notifier = Notifier(
        bus=(lambda: bus) if bus else None,
        focus=lambda: shown.append({"focus": True}),
        show=_show,
        settings=lambda: settings or NotifySettings(),
        app_focused=lambda: focused,
        clock=lambda: clock or datetime(2026, 11, 10, 12, 0),
    )
    return notifier, shown


async def test_a_notification_is_shown_and_reported() -> None:
    notifier, shown = _notifier()
    verdict = await notifier.notify(
        "reminder", "Reminder", "taxes", session_id="s1", message_id="n-3"
    )
    assert verdict.shown is True and verdict.how == desktop.SHOWN
    assert shown[0]["title"] == "Reminder"


async def test_the_gate_holds_for_every_reason() -> None:
    off, _ = _notifier(NotifySettings(enabled=False))
    assert (await off.notify("reminder", "t", "b")).held == HELD_OFF
    kind_off, _ = _notifier(NotifySettings(kinds={"finished": False}))
    assert (await kind_off.notify("finished", "t", "b")).held == HELD_KIND
    quiet, _ = _notifier(
        NotifySettings(quiet_hours=QuietHours(enabled=True, start="22:00", end="07:00")),
        clock=datetime(2026, 11, 10, 23, 30),
    )
    assert (await quiet.notify("reminder", "t", "b")).held == HELD_QUIET
    looking, shown = _notifier(focused=True)
    assert (await looking.notify("needs_you", "t", "b")).held == HELD_LOOKING
    assert shown == []
    # A reminder may ask to be shown even while the window is in front.
    assert (await looking.notify("reminder", "t", "b", ignore_focus=True)).shown is True
    unknown, _ = _notifier()
    assert (await unknown.notify("gossip", "t", "b")).held == HELD_UNKNOWN_KIND


async def test_an_unsupported_system_is_an_honest_not_shown() -> None:
    notifier, _ = _notifier(how=desktop.UNSUPPORTED)
    verdict = await notifier.notify("reminder", "t", "b")
    assert verdict.shown is False and verdict.how == desktop.UNSUPPORTED and verdict.held == ""


async def test_a_click_raises_the_window_and_tells_the_app() -> None:
    bus = _Bus()
    notifier, shown = _notifier(bus=bus)
    await notifier.notify("reminder", "Reminder", "taxes", session_id="s1", message_id="n-7")
    # The click comes from the toast's own thread.
    await asyncio.to_thread(shown[0]["on_click"])
    await asyncio.sleep(0.05)
    assert {"focus": True} in shown
    assert len(bus.published) == 1
    opened = bus.published[0]
    assert isinstance(opened, NotificationOpened)
    assert (opened.kind, opened.session_id, opened.message_id) == ("reminder", "s1", "n-7")
