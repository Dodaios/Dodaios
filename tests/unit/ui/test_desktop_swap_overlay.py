"""DesktopApp.swap_overlay live-swap logic.

A second in-process Tk root at runtime is impossible: tearing a ``tk.Tk()`` root
down and building a new one cross-thread-aborts the process with
``Tcl_AsyncDelete`` (BUG-031). So a style the app has not built yet starts in
its own host process (``_build_hosted_surface``), the surface being left goes
off the screen at once, and only a host that fails to start falls back to
``restart_required``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from dodaios.ui.desktop_app import DesktopApp
from dodaios.ui.dodaiosbar.null_overlay import NullOverlay


def _app(*, orb_style="jarvis_bar", bridge=..., orb=None):
    app = DesktopApp.__new__(DesktopApp)  # bypass heavy __init__
    app.cfg = SimpleNamespace(
        ui=SimpleNamespace(
            orb_style=orb_style,
            bar_persistent=True,
            bar_accent="#e7c46e",
        )
    )
    app._bridge = bridge
    app._orb = orb
    return app


class FakeBridge:
    def __init__(self):
        self.surface = None

    def set_surface(self, s):
        self.surface = s


class FakeOld:
    def __init__(self):
        self.hidden = False

    def hide(self):
        self.hidden = True


def test_swap_to_none_uses_nulloverlay_and_hides_old():
    bridge, old = FakeBridge(), FakeOld()
    app = _app(orb_style="jarvis_bar", bridge=bridge, orb=old)
    result = app.swap_overlay("none")
    assert result == {"ok": True, "applied_live": True, "style": "none"}
    assert isinstance(bridge.surface, NullOverlay)
    assert old.hidden is True  # old surface hidden, NOT destroyed (multi-root safety)
    assert app._orb is bridge.surface
    assert app.cfg.ui.orb_style == "none"
    # the new surface is cached for reuse
    assert app._surfaces["none"] is bridge.surface


def test_swap_reuses_cached_surface():
    bridge = FakeBridge()
    app = _app(orb_style="voice_orb", bridge=bridge, orb=FakeOld())
    sentinel = object()
    app._surfaces = {"none": sentinel}  # pretend 'none' was built before
    result = app.swap_overlay("none")
    assert result["applied_live"] is True
    assert bridge.surface is sentinel  # reused, not rebuilt


class FakeHosted(FakeOld):
    """Stands in for a surface in its own host process."""

    def __init__(self, style):
        super().__init__()
        self.style = style
        self.shown = []

    def show(self, mode="listen"):
        self.shown.append(mode)


def _host(app, built):
    def build(style, **_):
        surface = FakeHosted(style)
        built.append(surface)
        return surface

    app._build_hosted_surface = build


def test_swap_to_an_unbuilt_style_starts_it_hosted_and_hides_the_old():
    # Boot built only the voice orb; picking the bar must show the bar NOW and
    # take the orb off the screen — not leave it up until a restart.
    bridge, old, built = FakeBridge(), FakeOrbWindow("voice_orb"), []
    app = _app(orb_style="jarvis_bar", bridge=bridge, orb=old)  # route pre-wrote cfg
    app._surfaces = {"voice_orb": old}
    _host(app, built)

    result = app.swap_overlay("jarvis_bar")

    assert result == {"ok": True, "applied_live": True, "style": "jarvis_bar"}
    assert [s.style for s in built] == ["jarvis_bar"]
    assert bridge.surface is built[0] and app._orb is built[0]
    assert old.hidden is True  # in-process surface hidden, never destroyed
    assert built[0].shown == ["idle"]  # bar_persistent=True
    assert app._surfaces["jarvis_bar"] is built[0]


def test_swap_falls_back_to_restart_when_the_host_will_not_start():
    bridge, old = FakeBridge(), FakeOld()
    app = _app(orb_style="voice_orb", bridge=bridge, orb=old)
    app._surfaces = {}
    app._build_hosted_surface = lambda style, **_: None
    result = app.swap_overlay("jarvis_bar")
    assert result == {"ok": True, "applied_live": False, "style": "jarvis_bar"}
    assert bridge.surface is None  # bridge NOT repointed
    assert old.hidden is False  # nothing replaces it, so it stays


def test_leaving_a_hosted_surface_stops_its_process(monkeypatch):
    from dodaios.ui.dodaiosbar import subprocess_overlay

    class FakeHostProc(subprocess_overlay.SubprocessBarOverlay):
        def __init__(self):
            super().__init__()
            self.stopped = False

        def stop(self):
            self.stopped = True

    hosted = FakeHostProc()
    bridge = FakeBridge()
    app = _app(orb_style="none", bridge=bridge, orb=hosted)
    app._surfaces = {"jarvis_bar": hosted}
    assert app.swap_overlay("none")["applied_live"] is True
    assert hosted.stopped is True
    assert "jarvis_bar" not in app._surfaces  # a later switch starts a fresh host


def test_bar_back_to_a_cached_orb_window_reuses_it():
    # Boot was the voice orb, the bar was started hosted; picking the voice
    # orb again reuses the boot orb window instead of starting a second one.
    bridge, window, built = FakeBridge(), FakeOrbWindow("voice_orb"), []
    bar = FakeOld()
    app = _app(orb_style="voice_orb", bridge=bridge, orb=bar)
    app._surfaces = {"voice_orb": window, "jarvis_bar": bar}
    _host(app, built)

    assert app.swap_overlay("voice_orb")["applied_live"] is True
    assert built == []
    assert bridge.surface is window
    assert bar.hidden is True
    assert app._surfaces["voice_orb"] is window


@pytest.mark.parametrize("removed", ["pet", "mascot"])
def test_a_removed_desktop_pet_style_is_refused(removed):
    """Pets live in the app only (docs/pets.md); the route maps old values first."""
    app = _app(bridge=FakeBridge(), orb=FakeOld())
    assert app.swap_overlay(removed)["ok"] is False


def test_swap_without_bridge_is_persisted_only():
    app = _app(orb_style="voice_orb", bridge=None, orb=None)
    assert app.swap_overlay("jarvis_bar") == {
        "ok": True,
        "applied_live": False,
        "style": "jarvis_bar",
    }


def test_swap_rejects_unknown_style():
    app = _app(bridge=FakeBridge(), orb=FakeOld())
    assert app.swap_overlay("bogus")["ok"] is False


class FakeOrbWindow(FakeOld):
    """An orb surface: one window that can change what it paints."""

    def __init__(self, style="voice_orb"):
        super().__init__()
        self.style = style

    def set_style(self, style):
        self.style = style

    def show(self, mode="listen"):
        self.hidden = False


def test_bar_to_voice_orb_starts_the_orb_window_hosted():
    bridge, built = FakeBridge(), []
    app = _app(orb_style="jarvis_bar", bridge=bridge, orb=FakeOld())
    app._surfaces = {}
    _host(app, built)

    assert app.swap_overlay("voice_orb")["applied_live"] is True
    assert [s.style for s in built] == ["voice_orb"]
    assert bridge.surface is built[0]
