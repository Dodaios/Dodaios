"""The bar's sharp edges: whole-pixel rim and lines, premultiplied layered frames."""

from __future__ import annotations

import numpy as np
from PIL import Image

from dodaios.ui.dodaiosbar import design, renderer, win_layered


def _frame(state: design.BarState, scale: float, look: str = "idle") -> np.ndarray:
    painter = design.BarPainter()
    img = painter.paint(state, 0.0, 0.0, look=look, scale=scale)
    return np.asarray(img)


def test_open_pill_top_rim_is_one_full_pixel_on_a_small_scale() -> None:
    # 0.714 window pixels per design point: the 27" 1440p case where the
    # sub-pixel rim used to smear into grey.
    arr = _frame(design.BarState(hovered=True), 0.7142)
    alpha = arr[..., 3]
    col = alpha.shape[1] // 2
    rows = np.nonzero(alpha[:, col])[0]
    top = rows.min()
    assert alpha[top, col] == 255  # the outline starts on a whole pixel
    assert tuple(arr[top, col, :3]) == design.RIM
    assert tuple(arr[top + 1, col, :3]) == design.FILL


def test_live_lines_have_equal_whole_pixel_width() -> None:
    arr = _frame(design.BarState(mode="listen"), 0.7142, look="speak")
    rgb = arr[..., :3].astype(int)
    row = rgb[_middle_row(arr)]
    white = row.sum(axis=1) > 600
    runs, n = [], 0
    for on in white:
        if on:
            n += 1
        elif n:
            runs.append(n)
            n = 0
    assert len(runs) == design.LINE_COUNT
    assert len(set(runs)) == 1


def _middle_row(arr: np.ndarray) -> int:
    alpha = arr[..., 3]
    rows = np.nonzero(alpha.max(axis=1))[0]
    return int((rows.min() + rows.max()) // 2)


def test_solid_renderer_keeps_the_resting_pill_opaque() -> None:
    renderer.apply_display_scale(renderer.BASE_DISPLAY_SCALE, user_size=1.0)
    solid = np.asarray(renderer.JarvisBarRenderer(solid=True).render_rgba(0.0, "idle"))
    clear = np.asarray(renderer.JarvisBarRenderer().render_rgba(0.0, "idle"))
    assert solid[..., 3].max() == 255
    assert (solid[..., 3] == 255).sum() > (clear[..., 3] == 255).sum()


def test_premultiplied_bgra_orders_channels_and_scales_by_alpha() -> None:
    img = Image.new("RGBA", (2, 1))
    img.putpixel((0, 0), (200, 100, 50, 255))
    img.putpixel((1, 0), (200, 100, 50, 128))
    data = win_layered.premultiplied_bgra(img)
    assert data[:4] == bytes((50, 100, 200, 255))
    assert data[4:] == bytes((25, 50, 100, 128))


def test_layered_window_is_inert_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(win_layered.sys, "platform", "linux")
    lw = win_layered.LayeredWindow(root=object())
    assert lw.present(Image.new("RGBA", (4, 4))) is False
    assert lw.set_opacity(0.5) is False
