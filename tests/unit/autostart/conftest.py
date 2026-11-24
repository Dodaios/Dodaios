"""Shared fixtures/helpers for the autostart port unit tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dodaios.platform import PlatformName
from dodaios.platform.capabilities import Capabilities


@pytest.fixture(autouse=True)
def _not_in_linked_worktree(monkeypatch):
    """The suite runs from agent worktrees too; the reconcile tests describe the
    main checkout, so the worktree guard is off unless a test turns it on."""
    import dodaios.autostart as autostart

    monkeypatch.setattr(autostart, "running_from_linked_worktree", lambda root=None: False)


def make_caps(
    *,
    platform: PlatformName = "linux",
    display_present: bool = True,
) -> Capabilities:
    """A Capabilities snapshot with only the fields the autostart port reads
    varied; the rest get harmless defaults."""
    return Capabilities(
        platform=platform,
        has_hotkey=False,
        has_ax_tree=False,
        has_overlay=False,
        has_pty=False,
        has_elevation=False,
        has_cursor=False,
        display_present=display_present,
        is_wayland=False,
        has_webview=False,
        ax_permission_granted=None,
    )


def make_cfg(*, enabled: bool = True, start_minimized: bool = True) -> SimpleNamespace:
    """A minimal stand-in for JarvisConfig with just an ``autostart`` block."""
    return SimpleNamespace(
        autostart=SimpleNamespace(enabled=enabled, start_minimized=start_minimized)
    )
