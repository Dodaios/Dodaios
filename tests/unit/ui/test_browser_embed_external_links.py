"""A link opened in another program must end up in a normal browser window.

The browser sends such a link to its last active window, which is often the
panel's. The embed then hands that window back to the desktop.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.ui import browser_embed

CHROME, HOST, OTHER = 4242, 1111, 7777


def _embed(monkeypatch: pytest.MonkeyPatch, *, shown: bool, pointer_on: bool = False) -> Any:
    embed = browser_embed.ChromeEmbed()
    embed._chrome, embed._host, embed._shown = CHROME, HOST, shown
    embed._state = "embedded"
    handed: list[str] = []
    monkeypatch.setattr(embed, "_give_back", lambda **kw: handed.append("released"))
    monkeypatch.setattr(embed, "_raise_host_below_browser", lambda: handed.append("raised"))
    monkeypatch.setattr(embed, "_pointer_on_window", lambda: pointer_on)
    embed.handed = handed
    return embed


def _foreground(embed: Any, window: int) -> None:
    embed._on_event(None, browser_embed.EVENT_SYSTEM_FOREGROUND, window, 0, 0, 0, 0)


def test_link_into_hidden_panel_window_is_handed_back(monkeypatch: pytest.MonkeyPatch) -> None:
    embed = _embed(monkeypatch, shown=False)
    _foreground(embed, OTHER)
    _foreground(embed, CHROME)
    assert embed.handed == ["released"]
    assert embed._reason == "external_link"


def test_click_from_the_app_into_the_panel_stays(monkeypatch: pytest.MonkeyPatch) -> None:
    embed = _embed(monkeypatch, shown=True)
    _foreground(embed, HOST)
    _foreground(embed, CHROME)
    assert embed.handed == ["raised"]


def test_click_from_another_program_onto_the_panel_stays(monkeypatch: pytest.MonkeyPatch) -> None:
    embed = _embed(monkeypatch, shown=True, pointer_on=True)
    _foreground(embed, OTHER)
    _foreground(embed, CHROME)
    assert embed.handed == ["raised"]


def test_link_from_another_program_into_shown_panel_is_handed_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embed = _embed(monkeypatch, shown=True, pointer_on=False)
    _foreground(embed, OTHER)
    _foreground(embed, CHROME)
    assert embed.handed == ["released"]


def test_own_activation_is_not_a_link_from_elsewhere(monkeypatch: pytest.MonkeyPatch) -> None:
    embed = _embed(monkeypatch, shown=False)
    embed._own_until = time.monotonic() + 5
    _foreground(embed, OTHER)
    _foreground(embed, CHROME)
    assert embed.handed == ["raised"]


class _User32:
    def __init__(self, visible: bool) -> None:
        self.visible = visible
        self.calls: list[tuple[str, int]] = []

    def IsWindow(self, _h: int) -> bool:  # noqa: N802 - Win32 name
        return True

    def IsHungAppWindow(self, _h: int) -> bool:  # noqa: N802 - Win32 name
        return False

    def IsWindowVisible(self, _h: int) -> bool:  # noqa: N802 - Win32 name
        return self.visible

    def ShowWindow(self, _h: int, cmd: int) -> bool:  # noqa: N802 - Win32 name
        self.calls.append(("show", cmd))
        return True


@pytest.mark.parametrize(("was_shown", "handed_back"), [(False, True), (True, False)])
def test_window_the_browser_showed_by_itself_is_handed_back(
    monkeypatch: pytest.MonkeyPatch, was_shown: bool, handed_back: bool,
) -> None:
    """Hidden by the panel, then made visible by the browser: a link arrived."""
    embed = _embed(monkeypatch, shown=was_shown)
    user32 = _User32(visible=True)
    embed._api = SimpleNamespace(user32=user32)
    monkeypatch.setattr(embed, "_should_show", lambda: False)

    embed._sync()

    assert (embed.handed == ["released"]) is handed_back
    assert (("show", browser_embed.SW_HIDE) in user32.calls) is not handed_back
