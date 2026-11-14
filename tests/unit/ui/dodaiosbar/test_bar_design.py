"""The Dodaios Bar's own design: a black pill with white marks.

Pins the four shapes, the controls the open bar offers in each mode, that a
click lands on the control drawn under it at every size, and that the motion
follows the audio (still when silent, moving with speech in either direction).
"""

from __future__ import annotations

import numpy as np
import pytest

from dodaios.ui.dodaiosbar import design, interaction, renderer
from dodaios.ui.dodaiosbar.overlay import JarvisBarOverlay
from dodaios.ui.dodaiosbar.qt_overlay import QtJarvisBarOverlay


@pytest.fixture(autouse=True)
def geometry():
    renderer.apply_display_scale(1.0, 1.0)
    yield
    renderer.apply_display_scale(1.0, 1.0)


def center(control, mode="idle", **switches):
    point = renderer.control_center(control, mode, **switches)
    assert point is not None, f"{control} is not on the open {mode} bar"
    return point


def frame(mode="idle", level=0.0, t=0.5, **kw):
    """A fresh renderer's first frame (no easing history)."""
    return renderer.JarvisBarRenderer().render(t, mode, level, **kw)


def rgba(mode="idle", level=0.0, t=0.5, **kw):
    return np.asarray(renderer.JarvisBarRenderer().render_rgba(t, mode, level, **kw))


# -- shapes ---------------------------------------------------------------------


def test_idle_rests_as_a_slim_pill():
    lay = design.layout(design.BarState())
    assert lay.shape == "rest"
    assert lay.width < design.LIVE_W and lay.height < design.LIVE_H


@pytest.mark.parametrize(
    "switch", [{"muted": True}, {"speaker_muted": True}, {"prompt_mode": True}]
)
def test_a_switched_on_state_is_visible_without_hover(switch):
    assert design.layout(design.BarState(**switch)).shape == "status"
    assert frame().tobytes() != frame(**switch).tobytes()


@pytest.mark.parametrize("mode", ["connect", "listen", "speak", "think", "dictate", "notice"])
def test_a_running_conversation_or_dictation_shows_the_live_pill(mode):
    assert design.layout(design.BarState(mode=mode)).shape == "live"


@pytest.mark.parametrize("mode", ["idle", "listen", "speak", "dictate"])
def test_the_pointer_opens_the_bar(mode):
    closed = design.layout(design.BarState(mode=mode))
    opened = design.layout(design.BarState(mode=mode, hovered=True))
    assert opened.shape == "open"
    assert opened.width > closed.width


def test_a_notice_does_not_open():
    assert design.layout(design.BarState(mode="notice", hovered=True)).shape == "live"


def test_every_shape_fits_the_window():
    for mode in renderer.MODES:
        for hovered in (False, True):
            lay = design.layout(design.BarState(mode=mode, hovered=hovered, prompt_mode=True))
            assert lay.width <= design.WINDOW_W and lay.height <= design.WINDOW_H


# -- colours ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "kw",
    [
        {"mode": "idle", "hovered": True, "muted": True, "hovered_action": "mic"},
        {"mode": "speak", "surface_mode": "listen", "level": 0.8},
        {"mode": "notice"},
        {"mode": "think"},
    ],
)
def test_the_bar_is_black_and_white(kw):
    kw = dict(kw)
    level = kw.pop("level", 0.0)
    pixels = rgba(kw.pop("mode"), level, **kw)
    drawn = pixels[pixels[:, :, 3] > 0][:, :3].astype(int)
    spread = drawn.max(axis=1) - drawn.min(axis=1)
    assert spread.max() <= 2, "the bar draws only greys"


def test_the_tk_frame_has_no_key_coloured_fringe():
    img = np.asarray(frame("idle", hovered=True))
    key = np.all(img == renderer.COLOR_KEY_RGB, axis=-1)
    pinkish = (img[:, :, 0] > 120) & (img[:, :, 2] > 120) & (img[:, :, 1] < 80) & ~key
    assert key[0, 0] and not pinkish.any()


# -- motion -----------------------------------------------------------------------


def test_silence_is_still_and_speech_moves_the_bars():
    silent = [frame("speak", 0.0, t, surface_mode="listen").tobytes() for t in (0.1, 0.9)]
    assert silent[0] == silent[1]
    assert (
        frame("speak", 0.0, surface_mode="listen").tobytes()
        != frame("speak", 0.8, surface_mode="listen").tobytes()
    )


def test_dodaios_speaking_moves_the_same_bars_as_the_user():
    """Output gets the same indicator as input: Dodaios's voice level comes in
    through the same level feed while it speaks."""
    you = frame("speak", 0.6, surface_mode="listen")
    dodaios = frame("speak", 0.6, surface_mode="speak")
    assert you.tobytes() == dodaios.tobytes()
    assert dodaios.tobytes() != frame("speak", 0.0, surface_mode="speak").tobytes()


def test_thinking_and_connecting_animate_without_audio():
    for mode in ("think", "connect"):
        assert frame(mode, t=0.1).tobytes() != frame(mode, t=0.6).tobytes()


def test_idle_never_moves():
    assert frame("idle", 0.0, 0.1).tobytes() == frame("idle", 1.0, 3.0).tobytes()


def test_bar_heights_rest_at_zero_and_rise_with_level():
    assert design.bar_heights(0.0, 1.0) == [0.0] * design.BAR_COUNT
    quiet, loud = design.bar_heights(0.2, 1.0), design.bar_heights(0.9, 1.0)
    assert sum(loud) > sum(quiet) > 0


def test_the_pill_eases_open_instead_of_jumping():
    bar = renderer.JarvisBarRenderer()
    bar.render(0.0, "idle")
    bar.render(0.016, "idle", hovered=True)
    assert bar.easing
    for i in range(60):
        bar.render(0.032 + i * 0.016, "idle", hovered=True)
    assert not bar.easing


def test_the_connected_flourish_plays_once_then_the_plain_look():
    from ui.orb import controls

    tl = controls.ConnectTimeline()
    tl.note_mode("listen", "connect", 0.0)
    tl.note_mode("connect", "listen", 1.0)
    plain = frame("speak", surface_mode="listen")
    flourish = frame("speak", surface_mode="listen", connect_look=tl.look("listen", 1.3))
    late = frame("speak", surface_mode="listen", connect_look=tl.look("listen", 9))
    assert flourish.tobytes() != plain.tobytes()
    assert late.tobytes() == plain.tobytes()


# -- clicks -----------------------------------------------------------------------


@pytest.mark.parametrize("screen,user", [(0.55, 0.5), (0.85, 1.35), (1.6, 2.0)])
def test_every_control_is_clickable_at_every_size(screen, user):
    renderer.apply_display_scale(screen, user)
    assert frame().size == (renderer.WIN_W, renderer.WIN_H)
    for control, expected in [
        ("mic", "mute"),
        ("center", "talk"),
        ("speaker", "speaker"),
        ("compose", "compose"),
    ]:
        x, y = center(control)
        assert interaction.resolve_click(x, renderer.WIN_W, "idle", y=y) == expected


@pytest.mark.parametrize("mode", ["connect", "listen", "think", "speak"])
def test_a_running_call_hangs_up_only_on_the_x(mode):
    for control, expected in [
        ("mic", "mute"),
        ("center", "none"),
        ("speaker", "speaker"),
        ("close", "hangup"),
    ]:
        x, y = center(control, mode)
        assert interaction.resolve_click(x, renderer.WIN_W, mode, y=y) == expected


@pytest.mark.parametrize("mode", ["dictate", "dictate_transcribing"])
def test_a_dictation_offers_only_stop(mode):
    lay = design.layout(design.BarState(mode=mode, hovered=True))
    assert [name for name, *_ in lay.slots] == ["center", "close"]
    for control in ("center", "close"):
        x, y = center(control, mode)
        assert interaction.resolve_click(x, renderer.WIN_W, mode, y=y) == "dictation_stop"


def test_prompt_mode_adds_its_switch_to_the_idle_bar():
    x, y = center("prompt", prompt_mode=True)
    assert (
        interaction.resolve_click(x, renderer.WIN_W, "idle", y=y, prompt_mode=True)
        == "prompt_mode_toggle"
    )
    x, y = center("center", prompt_mode=True)
    assert interaction.resolve_click(x, renderer.WIN_W, "idle", y=y, prompt_mode=True) == "talk"
    assert renderer.control_center("prompt", "idle") is None


def test_transparent_corners_do_not_trigger_actions():
    for x, y in [(0, 0), (renderer.WIN_W - 1, 0), (0, renderer.WIN_H - 1)]:
        assert interaction.resolve_click(x, renderer.WIN_W, "listen", y=y) == "none"


def test_a_notice_is_not_a_control():
    x, y = center("center")
    assert interaction.resolve_click(x, renderer.WIN_W, "notice", y=y) == "none"


def test_hover_stays_on_the_open_bar_and_leaves_beside_it():
    x, y = center("compose")
    assert renderer.in_hover_footprint(x, y, "idle", hovered=True)
    assert not renderer.in_hover_footprint(2, 2, "idle", hovered=True)


@pytest.mark.parametrize("kind", ["tk", "qt"])
def test_both_hosts_route_compose_and_audio_independently(kind):
    bar = JarvisBarOverlay() if kind == "tk" else QtJarvisBarOverlay()
    events = []
    bar.set_on_compose(lambda: events.append("compose"))
    bar.set_on_speaker_toggle(lambda: events.append("speaker"))
    bar.set_on_mute_toggle(lambda: events.append("microphone"))
    click = bar._on_click if kind == "tk" else bar._dispatch_click_ui
    for control in ["compose", "speaker", "mic"]:
        x, y = center(control)
        click(x, click_y=y)
    assert events == ["compose", "speaker", "microphone"]
    assert bar._muted is True
    # Output mute only changes after the authoritative pipeline event.
    assert bar._speaker_muted is False
    bar.set_speaker_muted(True)
    assert bar._speaker_muted is True


@pytest.mark.parametrize("kind", ["tk", "qt"])
def test_hangup_guard_keeps_audio_controls_available(kind):
    bar = JarvisBarOverlay() if kind == "tk" else QtJarvisBarOverlay()
    events = []
    bar.set_on_compose(lambda: events.append("compose"))
    bar.set_on_speaker_toggle(lambda: events.append("speaker"))
    bar.set_on_mute_toggle(lambda: events.append("mic"))
    bar._hangup_click_block_until = float("inf")
    click = bar._on_click if kind == "tk" else bar._dispatch_click_ui
    for control in ["compose", "speaker", "mic"]:
        x, y = center(control)
        click(x, click_y=y)
    assert events == ["compose", "speaker", "mic"]


# -- flat near the bottom edge ---------------------------------------------------


@pytest.mark.parametrize("mode", ["idle", "listen", "dictate"])
@pytest.mark.parametrize("hovered", [False, True])
def test_the_bar_lies_flat_at_the_bottom_of_its_window(mode, hovered):
    state = design.BarState(mode=mode, hovered=hovered)
    lay = design.layout(state)
    assert lay.width > lay.height
    x0, _y0, x1, y1 = design.pill_rect(lay, 1.0)
    assert abs((x0 + x1) / 2 - design.WINDOW_W / 2) < 1e-6
    assert abs(y1 - (design.WINDOW_H - design.BOTTOM_PAD)) < 1e-6


def test_the_open_controls_line_up_left_to_right():
    lay = design.layout(design.BarState(mode="listen", hovered=True))
    names = [name for name, *_ in lay.slots]
    assert names == ["mic", "center", "speaker", "close"]
    lefts = [x0 for _name, x0, _x1 in lay.slots]
    assert lefts == sorted(lefts)


def test_the_resting_pill_is_see_through_inside_a_light_rim():
    pixels = rgba("idle")
    alpha = pixels[:, :, 3]
    drawn = pixels[alpha > 0]
    assert drawn[:, 3].min() < 200, "the fill lets the page show through"
    rim = drawn[drawn[:, 0] > 150]
    assert len(rim) > 0, "the rim is light"


def test_the_default_place_is_centred_near_the_bottom():
    x, y = interaction.default_bar_spot(work=(0, 38, 1470, 918), bar_w=190, bar_h=70, gap=12)
    assert x == (1470 - 190) // 2
    assert y == 38 + 918 - 70 - 12


def test_a_place_saved_by_the_earlier_bar_is_not_reused(tmp_path):
    cfg = tmp_path / "jarvis.toml"
    cfg.write_text("[jarvisbar]\npos_x = 870\npos_y = 598\nrel_x = 0.73\nrel_y = 0.65\n")
    assert interaction.load_jarvisbar_position(cfg) is None
    assert interaction.load_jarvisbar_relative(cfg) is None
    interaction.save_jarvisbar_position(cfg, 640, 874, rel=(0.5, 1.0))
    assert interaction.load_jarvisbar_position(cfg) == (640, 874)
    assert interaction.load_jarvisbar_relative(cfg) == (0.5, 1.0)


# -- labels -----------------------------------------------------------------------


def test_the_control_under_the_pointer_says_what_it_does():
    idle = design.BarState(language="de")
    assert design.control_label("center", idle) == "Mit Dodaios sprechen"
    assert design.control_label("mic", idle) == "Mikrofon stumm"
    assert design.control_label("mic", design.BarState(muted=True)) == "Unmute microphone"
    assert design.control_label("close", design.BarState(mode="dictate")) == "Stop dictation"


def test_no_label_for_a_control_that_does_nothing():
    assert design.control_label("center", design.BarState(mode="listen")) == ""


def test_the_label_is_drawn_above_the_bar():
    plain = rgba("idle", hovered=True)
    labelled = rgba("idle", hovered=True, hovered_action="mic")
    y0 = round(
        design.pill_rect(design.layout(design.BarState(hovered=True)), renderer.design_scale())[1]
    )
    assert plain[: y0 - 2, :, 3].max() == 0
    assert labelled[: y0 - 2, :, 3].max() > 0


# -- voice row ----------------------------------------------------------------------


def _run_row(levels, *, fps=60, start=0.0):
    row = design.VoiceRow()
    frames = []
    for i, level in enumerate(levels):
        frames.append(row.update(start + i / fps, level))
    return row, frames


def test_a_new_sound_enters_in_the_middle_and_travels_outward():
    row, frames = _run_row([0.0] * 10 + [0.9] * 3)
    centre = row.centre
    early = frames[-1]
    assert early[centre] > early[0] and early[centre] > early[-1]
    _row, later = _run_row([0.0] * 10 + [0.9] * 40)
    assert later[-1][0] > 0.3, "the sound reaches the ends after a moment"


def test_bars_glide_instead_of_jumping():
    levels = [0.0] * 5 + [1.0] * 10 + [0.0] * 10 + [0.8] * 10
    _row, frames = _run_row(levels)
    for before, after in zip(frames, frames[1:], strict=False):
        assert max(abs(a - b) for a, b in zip(before, after, strict=True)) < 0.5


def test_silence_drains_to_still_dots():
    row, frames = _run_row([0.8] * 20 + [0.0] * 120)
    assert frames[-1] == [0.0] * design.LINE_COUNT
    assert not row.moving


def test_the_painter_keeps_drawing_while_the_bars_glide():
    bar = renderer.JarvisBarRenderer()
    for i in range(10):
        bar.render(i / 60, "speak", 0.9, surface_mode="dictate")
    for i in range(10, 14):
        bar.render(i / 60, "speak", 0.0, surface_mode="dictate")
    assert bar.easing, "a host must not freeze the frame mid-glide"
    for i in range(14, 200):
        bar.render(i / 60, "speak", 0.0, surface_mode="dictate")
    assert not bar.easing
