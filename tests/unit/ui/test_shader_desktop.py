"""The desktop shader figure: wrap, blend, and the command stream."""

from __future__ import annotations

from pathlib import Path

from dodaios.ui.pets.states import PET_STATES
from dodaios.ui.pets.store import PetStore
from ui.orb.pet_renderer import LEVEL_SMOOTHING, PetRenderer
from ui.orb.shader_desktop import (
    disc_backdrop_straight,
    shader_pass_levels,
    shader_source_for_id,
    step_shader_blend,
    wrap_desktop_fragment,
)
from ui.orb.shader_host import ShaderFigureHost

SOURCE = "void main() {\n  gl_FragColor = vec4(uState, uStateFrom, uBlend, 0.9);\n}\n"


def test_desktop_wrapper_draws_a_disc_and_mixes() -> None:
    wrapped = wrap_desktop_fragment(SOURCE)
    assert "void petMain(" in wrapped
    assert "gl_FragColor" not in wrapped
    assert "if (r2 > 1.0)" in wrapped
    assert "uniform float uLevel;" in wrapped
    assert "uniform float uLevelFrom;" in wrapped
    assert wrapped.index("petLevel = uLevelFrom;") < wrapped.index("petMain();")
    assert "mix(petFrom, fragColor, clamp(uBlend, 0.0, 1.0))" in wrapped
    assert wrapped.index("#define uState petState") < wrapped.index("#undef uState")
    assert wrapped.index("#undef uState") < wrapped.index("void main()")


def test_orb_scene_is_not_a_generated_sphere() -> None:
    source = shader_source_for_id("jarvis-orb") or ""
    assert source.startswith("// scene ")
    assert "if (r2 > 1.0)" not in source


def test_each_pass_keeps_the_level_of_its_own_state() -> None:
    talking = float(PET_STATES.index("talking"))
    listening = float(PET_STATES.index("listening"))
    idle = float(PET_STATES.index("idle"))
    # Leaving talking for idle: the outgoing pass keeps the captured voice.
    assert shader_pass_levels({"from": talking, "to": idle, "value": 0.2}, 0.0, 0.7) == (0.7, 0.0)
    # Entering talking from idle: only the incoming pass is loud.
    assert shader_pass_levels({"from": idle, "to": talking, "value": 0.2}, 0.4, 0.0) == (0.0, 0.4)
    # Listening into talking: each pass keeps the level that belonged to it.
    assert shader_pass_levels({"from": listening, "to": talking, "value": 0.5}, 0.3, 0.8) == (
        0.8,
        0.3,
    )


def test_disc_backdrop_is_black_inside_and_clear_in_the_corners() -> None:
    width, height = 5, 5
    rgba = bytearray(width * height * 4)
    center = (2 * width + 2) * 4
    rgba[center : center + 4] = bytes((255, 0, 0, 255))
    same = bytes(rgba)
    assert disc_backdrop_straight(same, width, height, 0) is same
    painted = disc_backdrop_straight(same, width, height, 1)
    assert painted[center : center + 4] == bytes((255, 0, 0, 255))
    assert painted[0:4] == bytes(4)  # corner stays clear
    mid = painted[center - 4 : center]  # a clear pixel inside the disc
    assert mid == bytes((0, 0, 0, 255))


def test_disc_does_not_replace_or_zero_shader_pixels() -> None:
    """A low-alpha wave pixel keeps its colour. The old straight scale crushed it."""
    width, height = 5, 5
    rgba = bytearray(width * height * 4)
    center = (2 * width + 2) * 4
    rgba[center : center + 4] = bytes((16, 24, 25, 27))
    painted = disc_backdrop_straight(bytes(rgba), width, height, 0.8)
    assert painted[center : center + 3] == bytes((16, 24, 25))
    assert painted[center + 3] > 27


def test_tighter_disc_leaves_the_old_outer_ring_clear() -> None:
    width = height = 21
    blank = bytes(width * height * 4)
    full = disc_backdrop_straight(blank, width, height, 1, 1.0)
    tight = disc_backdrop_straight(blank, width, height, 1, 0.88)
    outer = (10 * width + 0) * 4  # inside the unit disc, outside 0.88
    inner = (10 * width + 1) * 4
    assert full[outer : outer + 4] == bytes((0, 0, 0, 255))
    assert tight[outer : outer + 4] == bytes(4)
    assert tight[inner : inner + 4] == bytes((0, 0, 0, 255))


def test_host_sends_a_backdrop_change_on_its_own() -> None:
    sent: list[dict[str, object]] = []
    host = ShaderFigureHost(lambda _event: None)
    host._start = lambda: setattr(host, "_proc", object()) or True  # type: ignore[method-assign]
    host._send = lambda payload: sent.append(payload) or True  # type: ignore[method-assign]
    base = {
        "source": "void main(){}",
        "x": 1,
        "y": 2,
        "w": 10,
        "h": 10,
        "state": 0,
        "shown": True,
        "dragging": False,
    }
    host.sync(**base)
    host.sync(**{**base, "backdrop": 0.4})
    host.sync(**{**base, "backdrop": 0.404})
    assert [item["op"] for item in sent] == ["show", "backdrop"]
    assert sent[0]["backdrop"] == 0.0
    assert sent[1]["backdrop"] == 0.4


def test_blend_eases_then_snaps_when_reduced() -> None:
    blend = {"from": 0.0, "to": 0.0, "value": 1.0}
    step_shader_blend(blend, 3, 0.0, False)
    assert blend == {"from": 0.0, "to": 3.0, "value": 0.0}
    step_shader_blend(blend, 3, 0.33, False)
    assert blend["value"] == 1.0
    step_shader_blend(blend, 4, 1.0, True)
    assert blend["to"] == 4.0
    assert blend["value"] == 1.0


def test_host_sends_show_then_only_what_changed() -> None:
    sent: list[dict[str, object]] = []
    host = ShaderFigureHost(lambda _event: None)
    host._start = lambda: setattr(host, "_proc", object()) or True  # type: ignore[method-assign]
    host._send = lambda payload: sent.append(payload) or True  # type: ignore[method-assign]
    base = {
        "source": "void main(){}",
        "x": 1,
        "y": 2,
        "w": 10,
        "h": 10,
        "state": 0,
        "shown": True,
        "dragging": False,
    }
    host.sync(**base)
    host.sync(**{**base, "x": 4})
    host.sync(**{**base, "x": 4, "state": 3, "dragging": True})
    host.sync(**{**base, "x": 9, "state": 3, "dragging": True, "level": 0.42})
    host.sync(**{**base, "x": 9, "state": 3, "dragging": True, "level": 0.424})
    host.sync(source=None, x=0, y=0, w=1, h=1, state=0, shown=False, dragging=False)
    assert [item["op"] for item in sent] == ["show", "place", "state", "level", "hide"]
    assert sent[-2]["level"] == 0.42
    assert sent[0]["source"] == "void main(){}"
    assert sent[0]["state"] == 0


def test_host_keeps_the_strip_off_the_figure_channel() -> None:
    sent: list[dict[str, object]] = []
    host = ShaderFigureHost(lambda _event: None)
    host._start = lambda: setattr(host, "_proc", object()) or True  # type: ignore[method-assign]
    host._send = lambda payload: sent.append(payload) or True  # type: ignore[method-assign]
    assert host.show_strip(b"png", 4, 5, 20, 8)
    assert host.show_strip(b"png", 4, 5, 20, 8)
    assert host.show_strip(b"png", 9, 5, 20, 8)
    host.hide_strip()
    assert [item["op"] for item in sent] == ["strip", "strip", "strip-hide"]
    assert sent[0]["w"] == 20
    assert sent[1]["png"] == ""


def test_renderer_keeps_a_shader_instead_of_the_default_sprite(monkeypatch) -> None:
    monkeypatch.setattr("ui.orb.pet_renderer.shader_source_for_id", lambda _pet_id: SOURCE)
    calls: list[str] = []
    renderer = PetRenderer("tide", loader=lambda pet_id: calls.append(pet_id))
    assert calls == []
    assert renderer.shader_source == SOURCE
    assert renderer.has_figure
    assert renderer.size == (180, 180)
    assert renderer.frame_key()[0] == "shader"
    assert renderer.render().getpixel((0, 0)) == (255, 0, 255)


def test_shader_source_for_id_reads_the_fragment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("dodaios.core.config.DATA_DIR", tmp_path)
    store = PetStore(tmp_path / "pets")
    manifest = store.add_shader(source=SOURCE, name="Tide", description="Rings.")
    assert shader_source_for_id(manifest.id) == SOURCE
    assert shader_source_for_id("gigi") is None
    source = shader_source_for_id("wisp-swarm")
    assert source is not None and "uLevel" in source and "void main" in source


def test_voice_level_is_the_live_voice_only_while_talking_or_listening() -> None:
    clock = {"now": 10.0}

    def time() -> float:
        return clock["now"]

    renderer = PetRenderer("wisp-swarm", clock=time, loader=lambda _pet_id: None)
    renderer.on_mode("speak")
    assert renderer.state() == "talking"
    assert renderer.voice_level() == 0.0
    renderer.feed_level(0.8, clock["now"])
    assert renderer.voice_level() == 0.8 * LEVEL_SMOOTHING
    renderer.on_mode("think")
    assert renderer.voice_level() == 0.0
    renderer.on_mode("listen")
    renderer.feed_level(0.5, clock["now"])
    assert renderer.voice_level() > 0.0
    assert renderer.next_frame_delay_ms() <= 62
    clock["now"] += 1.0
    assert renderer.voice_level() == 0.0


def test_renderer_does_not_substitute_the_default_sprite_for_a_drawn_scene() -> None:
    calls: list[str] = []
    cat = PetRenderer("cube-cat", loader=lambda requested: calls.append(requested))
    assert calls == []
    assert cat.pet_id == "cube-cat"
    assert cat.shader_source is not None
    assert cat.shader_source.startswith("// model ")
    assert cat.has_figure

    orb = PetRenderer("jarvis-orb", loader=lambda requested: calls.append(requested))
    assert calls == []
    assert orb.pet_id == "jarvis-orb"
    assert orb.shader_source is not None
    assert orb.shader_source.startswith("// scene ")
    assert orb.has_figure
