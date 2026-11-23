"""Desktop-only capability injection for subscription Realtime signalling."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from dodaios.ui.desktop_app import DesktopApp


def test_desktop_injects_distinct_realtime_broker_capability(monkeypatch) -> None:
    scripts: list[str] = []
    window = SimpleNamespace(evaluate_js=scripts.append)
    app = DesktopApp.__new__(DesktopApp)
    app.session_token = "ordinary-ui-session"  # noqa: S105 - synthetic test token
    app.realtime_transport_broker_token = (
        "desktop-broker-capability"  # noqa: S105 - synthetic test token
    )
    monkeypatch.setattr(app, "_start_desktop_integration_repair", lambda: None)
    monkeypatch.setitem(
        sys.modules,
        "dodaios.ui.icon_utils",
        SimpleNamespace(
            project_icon_path=lambda: "unused",
            set_window_icon_by_title=lambda *_args: None,
        ),
    )

    app._inject_token(window)

    assert len(scripts) == 1
    assert "ordinary-ui-session" in scripts[0]
    assert "desktop-broker-capability" in scripts[0]
    assert "__JARVIS_EMBEDDED_DESKTOP" in scripts[0]
    assert "__JARVIS_REALTIME_BROKER_TOKEN" in scripts[0]


# --- the tokens go to the app's own page only --------------------------------


def _desktop(monkeypatch) -> DesktopApp:
    app = DesktopApp.__new__(DesktopApp)
    app.session_token = "ordinary-ui-session"  # noqa: S105 - synthetic test token
    app.realtime_transport_broker_token = (
        "desktop-broker-capability"  # noqa: S105 - synthetic test token
    )
    app.cfg = SimpleNamespace(ui=SimpleNamespace(dev_mode=False, admin_api_port=47821))
    monkeypatch.setattr(app, "_start_desktop_integration_repair", lambda: None)
    monkeypatch.setitem(
        sys.modules,
        "dodaios.ui.icon_utils",
        SimpleNamespace(
            project_icon_path=lambda: "unused",
            set_window_icon_by_title=lambda *_args: None,
        ),
    )
    return app


def test_a_window_led_to_another_site_gets_no_token(monkeypatch) -> None:
    """The ``loaded`` hooks fire for every page the window loads. They used
    to hand the session and broker tokens to whatever page that was."""
    app = _desktop(monkeypatch)
    for foreign in (
        "https://example.test/landing",
        "http://127.0.0.1:3000/",
        "http://localhost:47821/",
        "https://127.0.0.1:47821/",
    ):
        scripts: list[str] = []
        window = SimpleNamespace(evaluate_js=scripts.append, get_current_url=lambda u=foreign: u)

        app._inject_token(window)
        app._inject_reopened_main(window)

        assert scripts == [], foreign


def test_the_apps_own_page_still_gets_its_tokens(monkeypatch) -> None:
    app = _desktop(monkeypatch)
    for own in ("http://127.0.0.1:47821/", "http://127.0.0.1:47821/threads/abc?view=agents", None):
        scripts: list[str] = []
        window = SimpleNamespace(evaluate_js=scripts.append, get_current_url=lambda u=own: u)

        app._inject_token(window)
        app._inject_reopened_main(window)

        assert len(scripts) == 2, own
        assert "ordinary-ui-session" in scripts[0]
        assert "desktop-broker-capability" in scripts[1]


def test_page_is_foreign_only_for_a_readable_other_origin() -> None:
    from dodaios.ui.desktop_app import page_is_foreign

    app_url = "http://127.0.0.1:47821"

    assert page_is_foreign("https://example.test/", app_url)
    assert page_is_foreign("http://127.0.0.1:47822/", app_url)
    assert not page_is_foreign("http://127.0.0.1:47821/settings", app_url)
    assert not page_is_foreign("HTTP://127.0.0.1:47821", app_url)
    assert not page_is_foreign("about:blank", app_url)
    assert not page_is_foreign("", app_url)
    assert not page_is_foreign(None, app_url)
