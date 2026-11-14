"""'Restart Dodaios' in the macOS application menu."""

from __future__ import annotations

import inspect

import pytest

from dodaios.ui import macos_app_menu
from dodaios.ui.macos_app_menu import app_menu, restart_from_menu, supports_app_menu


class _Calls:
    def __init__(self, *, missions: list[str] | None = None, confirm: bool = True) -> None:
        self.missions = missions or []
        self.confirm_answer = confirm
        self.restarts = 0
        self.questions: list[tuple[str, str]] = []

    def restart(self) -> bool:
        self.restarts += 1
        return True

    def running_missions(self) -> list[str]:
        return list(self.missions)

    def confirm(self, title: str, message: str) -> bool:
        self.questions.append((title, message))
        return self.confirm_answer


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("6.2.1", True),
        ("6.1", True),
        ("7.0", True),
        ("6.0.3", False),
        ("5.3", False),
        ("", False),
        ("dev", False),
    ],
)
def test_app_menu_items_need_pywebview_6_1(version: str, expected: bool) -> None:
    assert supports_app_menu(version) is expected


def test_no_menu_outside_macos() -> None:
    calls = _Calls()
    assert (
        app_menu(
            restart=calls.restart,
            running_missions=calls.running_missions,
            confirm=calls.confirm,
            platform="win32",
            pywebview_version="6.2.1",
        )
        == []
    )


def test_no_menu_on_pywebview_without_app_menu_items() -> None:
    calls = _Calls()
    assert (
        app_menu(
            restart=calls.restart,
            running_missions=calls.running_missions,
            confirm=calls.confirm,
            platform="darwin",
            pywebview_version="6.0",
        )
        == []
    )


def test_restart_item_goes_into_the_application_menu() -> None:
    pytest.importorskip("webview.menu")
    from webview.menu import Menu, MenuAction

    calls = _Calls()
    menus = app_menu(
        restart=calls.restart,
        running_missions=calls.running_missions,
        confirm=calls.confirm,
        platform="darwin",
        pywebview_version="6.2.1",
    )

    assert len(menus) == 1
    assert isinstance(menus[0], Menu)
    assert menus[0].title == "__app__"
    (item,) = menus[0].items
    assert isinstance(item, MenuAction)
    assert item.title == "Restart Dodaios"

    item.function()
    assert calls.restarts == 1


def test_restart_runs_at_once_when_nothing_is_running() -> None:
    calls = _Calls()
    assert restart_from_menu(calls.restart, calls.running_missions, calls.confirm) is True
    assert calls.restarts == 1
    assert calls.questions == []


def test_running_missions_ask_first_and_a_no_keeps_the_app() -> None:
    calls = _Calls(missions=["m1", "m2"], confirm=False)
    assert restart_from_menu(calls.restart, calls.running_missions, calls.confirm) is False
    assert calls.restarts == 0
    (question,) = calls.questions
    assert "2" in question[1]


def test_running_missions_restart_after_a_yes() -> None:
    calls = _Calls(missions=["m1"], confirm=True)
    assert restart_from_menu(calls.restart, calls.running_missions, calls.confirm) is True
    assert calls.restarts == 1


def test_desktop_app_hands_the_menu_to_webview_start() -> None:
    import dodaios.ui.desktop_app as desktop_app

    src = inspect.getsource(desktop_app.DesktopApp.run_window_only)
    assert "self._native_app_menu()" in src
    assert macos_app_menu.MENU_TITLE == "__app__"


def _bare_desktop_app(*, server: object = None, window: object = None) -> object:
    import dodaios.ui.desktop_app as desktop_app

    app = object.__new__(desktop_app.DesktopApp)
    app._server = server
    app._window = window
    return app


class _State:
    def __init__(self, kontrollierer: object) -> None:
        self.kontrollierer = kontrollierer


class _Server:
    def __init__(self, kontrollierer: object) -> None:
        self.app = type("App", (), {"state": _State(kontrollierer)})()


def test_running_missions_come_from_the_kontrollierer() -> None:
    k = type("K", (), {"running_mission_ids": lambda self: ["m1", "m2"]})()
    assert _bare_desktop_app(server=_Server(k))._running_mission_ids() == ["m1", "m2"]


def test_no_server_means_no_running_missions() -> None:
    assert _bare_desktop_app()._running_mission_ids() == []


def test_unknown_missions_count_as_running_so_the_menu_asks() -> None:
    def broken(self: object) -> list[str]:
        raise RuntimeError("mission manager wedged")

    k = type("K", (), {"running_mission_ids": broken})()
    assert _bare_desktop_app(server=_Server(k))._running_mission_ids() == ["unknown"]


def test_confirmation_without_a_window_is_a_no() -> None:
    assert _bare_desktop_app()._confirm_in_window("t", "m") is False


def test_confirmation_uses_the_window_dialog() -> None:
    class _Window:
        def __init__(self, answer: bool) -> None:
            self.answer = answer

        def create_confirmation_dialog(self, title: str, message: str) -> bool:
            return self.answer

    assert _bare_desktop_app(window=_Window(True))._confirm_in_window("t", "m") is True
    assert _bare_desktop_app(window=_Window(False))._confirm_in_window("t", "m") is False
