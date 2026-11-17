"""Captions on the clip's timeline (``dodaios/nodes/clip/captions.py``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dodaios.nodes.clip import captions
from dodaios.nodes.kinds import motion, motion_media

MID = "ab" * 12
ENTRY = {
    "kind": "video",
    "file": f"{MID}.mp4",
    "seconds": 60,
    "width": 1920,
    "height": 1080,
    "audio": True,
}


def _words(text: str, start: float = 0.0, step: float = 0.3) -> list[dict[str, Any]]:
    return [
        {"w": word, "s": round(start + n * step, 3), "e": round(start + n * step + 0.25, 3)}
        for n, word in enumerate(text.split())
    ]


def _spec(**scene: Any) -> dict[str, Any]:
    return motion.normalize(
        {
            "media": {MID: ENTRY},
            "scenes": [
                {"type": "title", "title": "Intro", "seconds": 2},
                {"type": "video", "media": MID, **scene},
            ],
        }
    )


@pytest.mark.parametrize(("fmt", "most"), [("tall", 4), ("square", 5), ("wide", 7)])
def test_a_line_holds_as_many_words_as_its_format_allows(fmt: str, most: int) -> None:
    lines = captions.caption_lines(_words("one two three four five six seven eight nine ten"), fmt)

    assert max(len(line["text"].split()) for line in lines) == most
    assert all(len(line["text"]) <= captions.LINE_LIMITS[fmt][1] for line in lines)


def test_a_line_ends_at_punctuation_a_pause_and_after_three_seconds() -> None:
    words = _words("Hello there. Nice to") + _words("see you", start=2.0)
    lines = captions.caption_lines(words, "wide")
    assert [line["text"] for line in lines] == ["Hello there.", "Nice to", "see you"]

    slow = captions.caption_lines(_words("a b c d e f g", step=0.6), "wide")
    assert len(slow) == 2
    for line in slow:
        assert line["end"] - line["start"] <= captions.MAX_LINE_S + captions.HOLD_S


def test_lines_hold_briefly_never_into_the_next_and_pass_the_spec_check() -> None:
    lines = captions.caption_lines(_words("we ship every friday. then we rest"), "tall")

    for line, after in zip(lines, lines[1:], strict=False):
        assert line["end"] <= after["start"]
    assert lines[-1]["end"] == pytest.approx(lines[-1]["words"][-1][1] + captions.HOLD_S, abs=1e-3)
    kept = motion_media.normalize_captions({"items": lines})
    assert kept is not None and all("words" in line for line in kept["items"])


def test_words_are_placed_through_in_and_speed_and_cut_words_are_dropped() -> None:
    spec = _spec(**{"in": 10, "seconds": 4, "speed": 2})
    pieces = captions.speech_pieces(spec)
    assert pieces == [
        {
            "media": MID,
            "file": f"{MID}.mp4",
            "start": 2.0,
            "seconds": 4.0,
            "in": 10.0,
            "out": 18.0,
            "speed": 2.0,
        }
    ]
    heard = {
        MID: [
            {"w": "before", "s": 9.0, "e": 9.5},
            {"w": "inside", "s": 12.0, "e": 12.4},
            {"w": "after", "s": 18.5, "e": 19},
        ]
    }

    placed = captions.place_words(pieces, heard)

    assert placed == [{"w": "inside", "s": 3.0, "e": 3.2}]


def test_muted_pieces_and_ducked_music_are_not_speech() -> None:
    spec = _spec(seconds=3, muted=True)
    spec["tracks"] = motion_media.normalize_tracks(
        [
            {
                "kind": "audio",
                "items": [{"media": MID, "duck": True}, {"media": MID, "start": 1, "seconds": 2}],
            }
        ],
        spec["media"],
        motion_media.Ids(),
    )
    pieces = captions.speech_pieces(spec)
    assert [(piece["start"], piece["seconds"]) for piece in pieces] == [(1.0, 2.0)]


def test_timeline_words_reads_each_file_once_over_its_pieces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / f"{MID}.mp4").write_bytes(b"x")
    spec = _spec(**{"in": 5, "seconds": 2})
    spec["scenes"].append(
        {"type": "video", "media": MID, "in": 20, "seconds": 1, "transition": "cut", "id": "v9"}
    )
    spec = motion.normalize(spec)
    calls: list[tuple[float, float | None]] = []

    def fake(path: Path, start: float, end: float | None, language: str | None) -> dict[str, Any]:
        calls.append((round(start, 3), round(end or 0, 3)))
        return {"words": [{"w": "a", "s": 5.5, "e": 5.8}, {"w": "b", "s": 20.2, "e": 20.5}]}

    monkeypatch.setattr(captions, "transcribe_file", fake)
    words = captions.timeline_words(spec, tmp_path, "en")

    assert calls == [(4.8, 21.2)]
    assert [(word["w"], word["s"]) for word in words] == [("a", 2.5), ("b", 4.2)]
