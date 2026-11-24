"""The new-window shim lets only http(s) reach the real ``webbrowser.open``."""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

from dodaios.platform.webview_new_window_guard import (
    _GuardedWebbrowser,
    guard_platform_modules,
    install_new_window_guard,
)


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://example.com/x", True),
        ("HTTP://example.com", True),
        ("  https://example.com ", True),
        ("ms-msdt:/id PCWDiagnostic", False),
        ("file:///C:/Windows/notepad.exe", False),
        ("javascript:alert(1)", False),
        ("//evil.example/", False),
        ("calculator:", False),
    ],
)
def test_shim_filters_schemes(url: str, allowed: bool) -> None:
    real = MagicMock()
    real.open.return_value = True
    assert _GuardedWebbrowser(real).open(url, 2, True) is allowed
    assert real.open.called is allowed


def test_guard_patches_platform_modules_only_and_is_idempotent() -> None:
    real = types.ModuleType("webbrowser")
    plat = types.ModuleType("webview.platforms.fake")
    plat.webbrowser = real  # type: ignore[attr-defined]
    other = types.ModuleType("something.else")
    other.webbrowser = real  # type: ignore[attr-defined]
    table = {"webview.platforms.fake": plat, "something.else": other}
    assert guard_platform_modules(table) == 1
    assert isinstance(plat.webbrowser, _GuardedWebbrowser)  # type: ignore[attr-defined]
    assert other.webbrowser is real  # type: ignore[attr-defined]
    assert guard_platform_modules(table) == 0


def test_install_wraps_initialize_and_fails_safe() -> None:
    calls: list[int] = []
    fake = types.SimpleNamespace(initialize=lambda *a, **k: calls.append(1) or "gui")
    assert install_new_window_guard(fake) is True
    assert fake.initialize() == "gui"
    assert calls == [1]
    assert install_new_window_guard(fake) is True  # idempotent
    assert install_new_window_guard(object()) is False  # layout differs: no raise
