"""The clip actions (:mod:`dodaios.nodes.clip.ops`): timeline arithmetic and ids.

Every action is checked on the spec it leaves behind, which always passed
through the clip grammar (``motion.normalize``), so a test also proves the
result is a clip the editor and the page can draw.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from dodaios.nodes.clip import ops
from dodaios.nodes.kinds import motion
from dodaios.nodes.types import NodeError

TAKE = "a" * 24
SONG = "b" * 24
LOGO = "c" * 24


def _library() -> dict[str, Any]:
    return {
        TAKE: {
            "kind": "video",
            "name": "take.mp4",
            "file": TAKE + ".mp4",
            "seconds": 30,
            "width": 1080,
            "height": 1920,
            "audio": True,
        },
        SONG: {"kind": "audio", "name": "song.mp3", "file": SONG + ".mp3", "seconds": 120},
        LOGO: {
            "kind": "image",
            "name": "logo.png",
            "file": LOGO + ".png",
            "width": 400,
            "height": 400,
        },
    }


def _clip(**extra: Any) -> dict[str, Any]:
    spec = {
        "format": "tall",
        "media": _library(),
        "scenes": [
            {"id": "v1", "type": "video", "media": TAKE, "in": 2, "seconds": 10},
            {
                "id": "v2",
                "type": "video",
                "media": TAKE,
                "in": 15,
                "seconds": 5,
                "transition": "fade",
            },
        ],
        **extra,
    }
    return motion.normalize(spec)


def _run(spec: dict[str, Any], *actions: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    return ops.apply_actions(spec, list(actions))


def _scene(spec: dict[str, Any], scene_id: str) -> dict[str, Any]:
    return next(scene for scene in spec["scenes"] if scene.get("id") == scene_id)


def _item(spec: dict[str, Any], item_id: str) -> dict[str, Any]:
    for track in spec.get("tracks") or []:
        for item in track["items"]:
            if item["id"] == item_id:
                return item
    raise AssertionError(item_id)


# ------------------------------------------------------------------ ids and safety


def test_every_scene_gets_an_id_and_given_ids_are_kept() -> None:
    spec = motion.normalize(
        {"scenes": [{"type": "title", "title": "Hi"}, {"id": "s1", "text": "x"}]}
    )
    out, _ = _run(spec, {"do": "format", "theme": "light"})
    assert [scene["id"] for scene in out["scenes"]] == ["s2", "s1"]


def test_actions_are_all_or_nothing_and_name_the_failing_action() -> None:
    spec = _clip()
    before = copy.deepcopy(spec)
    with pytest.raises(NodeError, match=r"Action 2 \(split\)"):
        _run(
            spec,
            {"do": "transition", "id": "v2", "kind": "wipe"},
            {"do": "split", "id": "v1", "at": 99},
        )
    assert spec == before


def test_an_unknown_action_lists_the_actions() -> None:
    with pytest.raises(NodeError, match="'do' must be one of add_clip"):
        _run(_clip(), {"do": "explode"})


def test_times_may_be_written_as_a_clock() -> None:
    out, _ = _run(_clip(), {"do": "split", "id": "v1", "at": "0:04.5"})
    assert _scene(out, "v1")["seconds"] == 4.5


# ------------------------------------------------------------------ split


def test_split_cuts_the_source_where_the_clock_says() -> None:
    spec = _clip()
    spec["scenes"][0].update(speed=2, fade_in=0.5, fade_out=1, filter="warm")
    spec = motion.normalize(spec)
    out, report = _run(spec, {"do": "split", "id": "v1", "at": 4})
    left, right = out["scenes"][0], out["scenes"][1]
    assert left["seconds"] == 4 and right["seconds"] == 6
    assert left["in"] == 2 and right["in"] == 10  # 2 + 4 s at double speed
    assert right["transition"] == "cut" and right["filter"] == "warm"
    assert "fade_out" not in left and left["fade_in"] == 0.5
    assert "fade_in" not in right and right["fade_out"] == 1
    assert right["id"] in report[0]


def test_split_keeps_a_zoom_in_motion_continuous() -> None:
    spec = _clip()
    spec["scenes"][0]["keys"] = [{"t": 0, "zoom": 1}, {"t": 10, "zoom": 1.2}]
    out, _ = _run(motion.normalize(spec), {"do": "split", "id": "v1", "at": 5})
    left, right = out["scenes"][0], out["scenes"][1]
    middle = ops.key_value(spec["scenes"][0]["keys"], "zoom", 5)
    assert left["keys"][-1] == {"t": 5, "zoom": pytest.approx(middle, abs=1e-4)}
    assert right["keys"][0]["t"] == 0 and right["keys"][0]["zoom"] == pytest.approx(
        middle, abs=1e-4
    )
    assert right["keys"][-1] == {"t": 5, "zoom": 1.2}


def test_a_card_is_not_split_and_a_cut_too_near_an_edge_is_refused() -> None:
    spec = motion.normalize({"scenes": [{"id": "s1", "type": "title", "title": "Hi"}]})
    with pytest.raises(NodeError, match="only video pieces"):
        _run(spec, {"do": "split", "id": "s1", "at": 1})
    with pytest.raises(NodeError, match="not inside"):
        _run(_clip(), {"do": "split", "id": "v1", "at": 10.02})


def test_split_a_text_item_hands_over_its_animations() -> None:
    spec = _clip(
        tracks=[{"kind": "text", "items": [{"id": "x1", "text": "Hook", "start": 1, "seconds": 4}]}]
    )
    out, _ = _run(spec, {"do": "split", "id": "x1", "at": 3})
    track = out["tracks"][0]["items"]
    assert [(i["start"], i["seconds"]) for i in track] == [(1, 2), (3, 2)]
    assert track[0]["out"] == "none" and track[1]["anim"] == "none"


# ------------------------------------------------------------------ trim, delete, ripple


def test_trimming_the_head_moves_the_source_and_pulls_the_track_forward() -> None:
    out, _ = _run(_clip(), {"do": "trim", "id": "v1", "start": 3})
    assert _scene(out, "v1")["in"] == 5 and _scene(out, "v1")["seconds"] == 7
    assert ops.starts(out) == [0, 7]


def test_trimming_the_end_and_a_source_that_runs_out() -> None:
    out, _ = _run(_clip(), {"do": "trim", "id": "v2", "end": 12})
    assert _scene(out, "v2")["seconds"] == 2
    with pytest.raises(NodeError, match="source has only"):
        _run(_clip(), {"do": "trim", "id": "v2", "end": 40})
    with pytest.raises(NodeError, match="cannot start earlier"):
        _run(_clip(), {"do": "set", "id": "v2", "in": 1}, {"do": "trim", "id": "v2", "start": 8})


def test_deleting_a_main_piece_closes_the_gap_on_every_track() -> None:
    spec = _clip(
        tracks=[
            {
                "kind": "text",
                "items": [
                    {"id": "x1", "text": "early", "start": 1, "seconds": 2},
                    {"id": "x2", "text": "late", "start": 12, "seconds": 2},
                ],
            },
            {"kind": "audio", "items": [{"id": "a1", "media": SONG, "start": 0, "seconds": 15}]},
        ],
        captions={"items": [{"start": 10.5, "end": 12, "text": "after the cut"}]},
    )
    # v1 → v1 [0-4] + v3 [4-10]; delete v3 (6 s): the later things move 6 s earlier.
    out, _ = _run(spec, {"do": "split", "id": "v1", "at": 4}, {"do": "delete", "ids": ["v3"]})
    assert ops.starts(out) == [0, 4]
    assert _item(out, "x1")["start"] == 1
    assert _item(out, "x2")["start"] == 6
    assert _item(out, "a1")["seconds"] == 9  # the music loses the 6 s too
    assert out["captions"]["items"][0]["start"] == 4.5


def test_the_main_track_keeps_one_piece() -> None:
    with pytest.raises(NodeError, match="at least one piece"):
        _run(_clip(), {"do": "delete", "ids": ["v1", "v2"]})


def test_ripple_on_a_track_moves_only_its_later_items() -> None:
    spec = _clip(
        tracks=[
            {
                "kind": "text",
                "items": [
                    {"id": "x1", "text": "a", "start": 0, "seconds": 2},
                    {"id": "x2", "text": "b", "start": 2, "seconds": 2},
                    {"id": "x3", "text": "c", "start": 5, "seconds": 1},
                ],
            }
        ]
    )
    out, _ = _run(spec, {"do": "delete", "ids": ["x2"], "ripple": True})
    assert [(i["id"], i["start"]) for i in out["tracks"][0]["items"]] == [("x1", 0), ("x3", 3)]
    out, _ = _run(spec, {"do": "delete", "ids": ["x2"]})
    assert [(i["id"], i["start"]) for i in out["tracks"][0]["items"]] == [("x1", 0), ("x3", 5)]


def test_remove_silences_cuts_each_silent_stretch_out() -> None:
    spec = _clip(captions={"items": [{"start": 9, "end": 10, "text": "end of first take"}]})
    # v1 plays source 2-12. Silences at 4-5 and 8-9.5 (source time) = 3.5 s gone.
    out, report = _run(spec, {"do": "remove_silences", "id": "v1", "silences": [[4, 5], [8, 9.5]]})
    pieces = [s for s in out["scenes"] if s["media"] == TAKE]
    assert [(p["in"], p["seconds"]) for p in pieces][:3] == [(2, 2), (5, 3), (9.5, 2.5)]
    assert ops.main_length(out) == 15 - 2.5
    assert out["captions"]["items"][0]["start"] == 9 - 2.5
    assert "removed 2 silence(s), 2.50 s" in report[0]


def test_remove_silences_drops_a_too_short_edge() -> None:
    # 0.05 s of speech before the silence is less than a piece can be: it goes too.
    out, _ = _run(_clip(), {"do": "remove_silences", "id": "v1", "silences": [[2.05, 3]]})
    assert out["scenes"][0]["in"] == 3 and out["scenes"][0]["seconds"] == 9


# ------------------------------------------------------------------ adding


def test_add_clip_replaces_the_blank_starter_and_inserts_by_time() -> None:
    blank = motion.normalize({"media": _library(), "scenes": [{"type": "title"}]})
    out, report = _run(blank, {"do": "add_clip", "media": "take.mp4", "in": 1, "out": 6})
    assert len(out["scenes"]) == 1 and out["scenes"][0]["seconds"] == 5
    assert out["scenes"][0]["media"] == TAKE and "added piece v1" in report[0]
    out, _ = _run(_clip(), {"do": "add_clip", "media": LOGO, "at": 2, "seconds": 3})
    assert [s["id"] for s in out["scenes"]] == ["v3", "v1", "v2"]
    out, _ = _run(_clip(), {"do": "add_clip", "media": LOGO, "at": 8, "seconds": 3})
    assert [s["id"] for s in out["scenes"]] == ["v1", "v3", "v2"]


def test_add_clip_on_the_overlay_track_and_the_named_media_error() -> None:
    out, _ = _run(
        _clip(),
        {"do": "add_clip", "media": LOGO, "track": "overlay", "at": 1, "seconds": 2, "w": 20},
    )
    track = out["tracks"][-1]
    assert track["kind"] == "overlay" and track["items"][0]["w"] == 20
    with pytest.raises(NodeError, match="no media 'nope.mp4'"):
        _run(_clip(), {"do": "add_clip", "media": "nope.mp4"})


def test_add_text_takes_a_free_text_track() -> None:
    out, _ = _run(
        _clip(),
        {"do": "add_text", "text": "STOP SCROLLING", "start": 0, "seconds": 2, "id": "hook"},
        {"do": "add_text", "text": "second", "start": 1, "seconds": 2},
        {"do": "add_text", "text": "third", "start": 3, "seconds": 1},
    )
    texts = [t for t in out["tracks"] if t["kind"] == "text"]
    assert len(texts) == 2  # the overlapping second line needed a track of its own
    assert _item(out, "hook")["text"] == "STOP SCROLLING"


def test_add_music_runs_to_the_end_ducked_under_speech() -> None:
    out, _ = _run(_clip(), {"do": "add_music", "media": SONG})
    music = out["tracks"][0]["items"][0]
    assert out["tracks"][0]["kind"] == "audio"
    assert music["seconds"] == 15 and music["duck"] is True and music["volume"] == 0.25
    assert music["fade_in"] == 1 and music["fade_out"] == 2


def test_add_scene_inserts_a_card() -> None:
    out, _ = _run(_clip(), {"do": "add_scene", "type": "end", "title": "Follow for more"})
    assert out["scenes"][-1]["type"] == "end" and out["scenes"][-1]["id"] == "s1"


# ------------------------------------------------------------------ changing


def test_set_keyframe_transition_move_and_duplicate() -> None:
    out, _ = _run(
        _clip(),
        {"do": "set", "id": "v1", "zoom": 1.1, "filter": "vivid", "volume": 0.5},
        {"do": "keyframe", "id": "v1", "t": 0, "zoom": 1},
        {"do": "keyframe", "id": "v1", "t": 10, "zoom": 1.08},
        {"do": "transition", "id": "v2", "kind": "blur"},
        {"do": "move", "id": "v2", "index": 0},
        {"do": "duplicate", "id": "v1"},
    )
    assert [s["id"] for s in out["scenes"]] == ["v2", "v1", "v3"]
    first = _scene(out, "v1")
    assert first["zoom"] == 1.1 and first["filter"] == "vivid" and first["volume"] == 0.5
    assert [k["t"] for k in first["keys"]] == [0, 10]
    assert _scene(out, "v2")["transition"] == "blur"
    out, _ = _run(out, {"do": "keyframe", "id": "v1", "t": 10, "remove": True})
    assert len(_scene(out, "v1")["keys"]) == 1


def test_set_refuses_a_value_the_grammar_cannot_read() -> None:
    with pytest.raises(NodeError, match="Action 1"):
        _run(_clip(), {"do": "set", "id": "v1", "media": "f" * 24})


def test_captions_style_and_edit() -> None:
    lines = [
        {"start": 0, "end": 1.2, "text": "hello there"},
        {"start": 1.2, "end": 2, "text": "world"},
    ]
    out, _ = _run(
        _clip(),
        {"do": "captions", "items": lines, "style": "bold"},
        {"do": "caption_style", "position": "middle"},
        {"do": "caption_edit", "index": 1, "text": "friends"},
        {"do": "caption_edit", "remove": 0},
    )
    assert out["captions"]["style"] == "bold" and out["captions"]["position"] == "middle"
    assert [line["text"] for line in out["captions"]["items"]] == ["friends"]


def test_format_and_moving_a_track_item() -> None:
    spec = _clip(
        tracks=[{"kind": "text", "items": [{"id": "x1", "text": "a", "start": 0, "seconds": 2}]}]
    )
    out, _ = _run(
        spec,
        {"do": "format", "format": "square", "accent": "pink"},
        {"do": "move", "id": "x1", "to": 4},
    )
    assert out["format"] == "square" and out["accent"] == "pink"
    assert _item(out, "x1")["start"] == 4
    with pytest.raises(NodeError, match="'format' must be one of"):
        _run(spec, {"do": "format", "format": "cinema"})


# ------------------------------------------------------------------ reading


def test_describe_lists_every_id_with_its_times() -> None:
    spec = _clip(
        tracks=[
            {"kind": "text", "items": [{"id": "x1", "text": "Hook line", "start": 0, "seconds": 2}]}
        ],
        captions={"items": [{"start": 0, "end": 1, "text": "hi"}]},
    )
    text = ops.describe(spec)
    assert "v1: 0.00-10.00 s, video 'take.mp4' source 2.00-12.00" in text
    assert "v2: 10.00-15.00 s" in text and "transition fade" in text
    assert "x1: 0.00-2.00 s, title 'Hook line'" in text
    assert "Captions: 1 line(s)" in text
    assert f"{TAKE}: 'take.mp4' video, 30.00 s, 1080x1920, sound" in text


def test_piece_times_for_a_transcript() -> None:
    times = ops.piece_times(_clip(), "v2")
    assert times == {"start": 10.0, "end": 15.0, "in": 15.0, "speed": 1.0, "media": TAKE}
