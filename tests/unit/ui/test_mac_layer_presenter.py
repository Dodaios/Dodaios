"""The pet's frames on macOS go through a native layer, not the Tk canvas.

Aqua-Tk 9 draws into an alpha-less bitmap and composites with source-over:
transparent pixels show black and old frames are never erased, so the pet
showed a black box and every animation frame stacked on the last. These tests
pin the routing with fakes; the real AppKit path was checked against the
window server (the figure window matched the intended frame pixel for pixel).
"""

from __future__ import annotations

from collections import OrderedDict
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from ui.orb import mac_layer, overlay


class _Presenter:
    def __init__(self, ok: bool) -> None:
        self.ok = ok
        self.frames: list[Image.Image] = []

    def present(self, image: Image.Image) -> bool:
        self.frames.append(image)
        return self.ok


class _Renderer:
    def __init__(self) -> None:
        self.renders = 0

    def render(self, *_args: Any) -> Image.Image:
        self.renders += 1
        return Image.new("RGB", (4, 4), tuple(int(c) for c in overlay.COLOR_KEY_RGB))

    def next_frame_delay_ms(self, _t: float) -> int:
        return 100


def _overlay(presenter: _Presenter, *, mac: bool = True) -> Any:
    o = overlay.OrbOverlay.__new__(overlay.OrbOverlay)
    o._mac_transparent = mac
    o._root = object()
    o._presenter = presenter
    o._native_shown = False
    o._image_id = None
    o._frame_key = None
    o._photo_cache = OrderedDict()
    o._mode = "idle"
    o._ext_level = 0.0
    o._controls = None
    o.shown_photos = []
    o._show_photo = o.shown_photos.append
    return o


@pytest.fixture
def native(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(overlay, "native_frames_available", lambda: True)


def test_a_pet_frame_goes_to_the_native_layer(
    native: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(overlay.ImageTk, "PhotoImage", lambda *a, **k: pytest.fail("Tk drew"))
    presenter = _Presenter(ok=True)
    o = _overlay(presenter)
    renderer = _Renderer()
    o._paint_keyed_frame(renderer, 0.0, "idle-0")
    assert len(presenter.frames) == 1
    frame = presenter.frames[0]
    assert frame.mode == "RGBA"
    assert frame.getpixel((0, 0))[3] == 0  # the colour key became transparent
    assert o.shown_photos == []
    # The same frame is not painted again, and a cached frame is not re-rendered.
    o._paint_keyed_frame(renderer, 0.1, "idle-0")
    assert len(presenter.frames) == 1
    o._paint_keyed_frame(renderer, 0.2, "idle-1")
    o._paint_keyed_frame(renderer, 0.3, "idle-0")
    assert len(presenter.frames) == 3
    assert renderer.renders == 2


def test_tk_draws_when_the_layer_is_not_ready_and_the_layer_is_tried_again(
    native: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(overlay.ImageTk, "PhotoImage", lambda image, **_k: ("photo", image.size))
    presenter = _Presenter(ok=False)
    o = _overlay(presenter)
    o._paint_keyed_frame(_Renderer(), 0.0, "idle-0")
    assert o.shown_photos == [("photo", (4, 4))]
    assert o._frame_key is None  # next tick retries the native layer
    presenter.ok = True
    o._paint_keyed_frame(_Renderer(), 0.1, "idle-0")
    assert len(presenter.frames) == 2
    assert o._native_shown


def test_other_platforms_keep_the_tk_canvas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(overlay.ImageTk, "PhotoImage", lambda image, **_k: ("photo", image.size))
    presenter = _Presenter(ok=True)
    o = _overlay(presenter, mac=False)
    o._paint_keyed_frame(_Renderer(), 0.0, "idle-0")
    assert presenter.frames == []
    assert o.shown_photos == [("photo", (4, 4))]


def test_the_strip_and_the_cards_use_the_layer_on_macos() -> None:
    from pathlib import Path

    root = Path(overlay.__file__).parent
    strip = (root / "overlay.py").read_text(encoding="utf-8")
    cards = (root / "layered_surface.py").read_text(encoding="utf-8")
    assert 'MacLayerPresenter(self._top, name="pet strip")' in strip
    assert "MacLayerPresenter(self.top, name=self._name)" in cards


def test_present_is_a_no_op_without_pyobjc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mac_layer, "_appkit", lambda: None)
    presenter = mac_layer.MacLayerPresenter(SimpleNamespace())
    assert presenter.present(Image.new("RGBA", (2, 2))) is False
    presenter.refresh()  # nothing to do, never raises


def test_the_cgimage_keeps_straight_alpha() -> None:
    quartz = pytest.importorskip("Quartz")
    cf = pytest.importorskip("CoreFoundation")
    image = Image.new("RGBA", (3, 2), (255, 0, 0, 0))
    image.putpixel((1, 1), (0, 0, 255, 255))
    cg = mac_layer.cgimage_from_pil(image, quartz, cf)
    assert (quartz.CGImageGetWidth(cg), quartz.CGImageGetHeight(cg)) == (3, 2)
    assert quartz.CGImageGetAlphaInfo(cg) == quartz.kCGImageAlphaLast
    data = bytes(quartz.CGDataProviderCopyData(quartz.CGImageGetDataProvider(cg)))
    row = quartz.CGImageGetBytesPerRow(cg)
    assert data[row + 4 : row + 8] == bytes((0, 0, 255, 255))
    assert data[3] == 0
