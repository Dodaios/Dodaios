"""Captions from what is said in a clip, on the clip's own timeline.

A clip is cut from its sources: a piece of a take starts somewhere in the
file, may run faster or slower, and sits somewhere on the timeline. So the
words are recognized in the SOURCE (each file once, over the stretch its
pieces use) and then placed where the person hears them: a word inside a
piece lands at ``piece start + (word time - in) / speed``; a word the cut left
out is not captioned.

Lines are short because they are read in passing, on a phone as much as on a
screen: a tall clip shows at most four words, a wide one seven. A line ends
at a sentence mark or a comma, at a pause in the speech, or after three
seconds; it stays a moment after its last word, never into the next line.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Final

from dodaios.nodes.clip.media import media_file
from dodaios.nodes.clip.transcribe import transcribe_file

#: Per format: the most words and characters on one caption line.
LINE_LIMITS: Final[dict[str, tuple[int, int]]] = {
    "tall": (4, 22),
    "portrait": (4, 22),
    "square": (5, 28),
    "wide": (7, 38),
}
#: A pause this long between two words starts a new line.
PAUSE_S: Final[float] = 0.45
#: The longest a line stays up.
MAX_LINE_S: Final[float] = 3.0
#: How long a line stays after its last word.
HOLD_S: Final[float] = 0.1
_BREAK_AFTER: Final[tuple[str, ...]] = (".", ",", "!", "?", ";", ":", "…")


def speech_pieces(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Every stretch of the timeline whose sound is speech, with its source range.

    Main-track video pieces with sound, and audio-track items that are not
    music lowered under speech (``duck``). Muted or silent ones are left out.
    """
    media = spec.get("media") or {}
    pieces: list[dict[str, Any]] = []

    def add(item: dict[str, Any], start: float) -> None:
        entry = media.get(str(item.get("media") or ""))
        if entry is None or not entry.get("audio") or item.get("muted"):
            return
        if float(item.get("volume", 1)) <= 0:
            return
        speed = float(item.get("speed", 1)) or 1.0
        seconds = float(item["seconds"])
        source_in = float(item.get("in", 0))
        pieces.append(
            {
                "media": str(item["media"]),
                "file": entry["file"],
                "start": start,
                "seconds": seconds,
                "in": source_in,
                "out": source_in + seconds * speed,
                "speed": speed,
            }
        )

    at = 0.0
    for scene in spec.get("scenes") or []:
        if scene.get("type") == "video":
            add(scene, at)
        at += float(scene["seconds"])
    for track in spec.get("tracks") or []:
        if track.get("kind") != "audio" or track.get("muted") or track.get("hidden"):
            continue
        for item in track.get("items") or []:
            if not item.get("duck"):
                add(item, float(item["start"]))
    return pieces


def place_words(
    pieces: list[dict[str, Any]], heard: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Source words (by media id) placed on the timeline through the pieces."""
    placed: list[dict[str, Any]] = []
    for piece in pieces:
        for word in heard.get(piece["media"], []):
            middle = (float(word["s"]) + float(word["e"])) / 2
            if not piece["in"] <= middle < piece["out"]:
                continue
            start = (
                piece["start"] + (max(float(word["s"]), piece["in"]) - piece["in"]) / piece["speed"]
            )
            end = (
                piece["start"]
                + (min(float(word["e"]), piece["out"]) - piece["in"]) / piece["speed"]
            )
            placed.append(
                {"w": word["w"], "s": round(start, 3), "e": round(max(end, start + 0.05), 3)}
            )
    placed.sort(key=lambda word: word["s"])
    return placed


def timeline_words(
    spec: dict[str, Any], node_dir: Path, language: str | None = None
) -> list[dict[str, Any]]:
    """Every word said in the clip as edited: ``[{w, s, e}]`` in timeline seconds."""
    pieces = speech_pieces(spec)
    ranges: dict[str, list[float]] = defaultdict(lambda: [float("inf"), 0.0])
    files: dict[str, str] = {}
    for piece in pieces:
        span = ranges[piece["media"]]
        span[0], span[1] = min(span[0], piece["in"]), max(span[1], piece["out"])
        files[piece["media"]] = piece["file"]
    heard: dict[str, list[dict[str, Any]]] = {}
    for key, (first, last) in ranges.items():
        path = media_file(node_dir, files[key])
        if path is None:
            continue
        heard[key] = transcribe_file(path, max(0.0, first - 0.2), last + 0.2, language)["words"]
    return place_words(pieces, heard)


def _ends_phrase(word: str) -> bool:
    return word.rstrip("\"'”’»)").endswith(_BREAK_AFTER)


def caption_lines(words: list[dict[str, Any]], fmt: str) -> list[dict[str, Any]]:
    """Words grouped into caption lines ``{start, end, text, words: [[s, e], ...]}``."""
    most_words, most_chars = LINE_LIMITS.get(fmt, LINE_LIMITS["wide"])
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for word in words:
        text = str(word["w"]).strip()
        if not text:
            continue
        if current:
            length = len(" ".join(str(each["w"]) for each in current)) + 1 + len(text)
            pause = float(word["s"]) - float(current[-1]["e"])
            if (
                len(current) >= most_words
                or length > most_chars
                or pause > PAUSE_S
                or float(word["e"]) - float(current[0]["s"]) > MAX_LINE_S
                or _ends_phrase(str(current[-1]["w"]))
            ):
                groups.append(current)
                current = []
        current.append({**word, "w": text})
    if current:
        groups.append(current)
    lines: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        start = float(group[0]["s"])
        end = float(group[-1]["e"]) + HOLD_S
        if index + 1 < len(groups):
            end = min(end, float(groups[index + 1][0]["s"]))
        end = max(end, start + 0.2)
        lines.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "text": " ".join(str(word["w"]) for word in group),
                "words": [
                    [round(float(word["s"]), 3), round(min(float(word["e"]), end), 3)]
                    for word in group
                ],
            }
        )
    return lines


__all__ = ["LINE_LIMITS", "caption_lines", "place_words", "speech_pieces", "timeline_words"]
