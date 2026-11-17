"""Edits of a clip, as the assistant asks for them: cut, trim, move, caption.

The ``clip`` tool (:mod:`dodaios.plugins.tool.clip`) does not rewrite a clip's
spec by hand. It sends ACTIONS ("split v3 at 4.2 s", "add a title layer",
"remove these silences"), and this module turns them into a valid spec: the
timeline arithmetic lives here once, so the assistant never computes a source
offset, a key's new time or where the next piece starts.

The rules match the person's editor (``frontend/.../motion/clipModel.ts``):

* the MAIN track is magnetic: its pieces always stand back to back, so a
  piece that gets shorter pulls every later piece forward;
* a piece of a video plays ``in`` to ``in + seconds * speed`` of its source;
  splitting it keeps both halves' look, hands the right half the fade-out and
  the rest of the keyframes (moved to its own clock), and puts a key on both
  sides of the cut so a zoom in motion does not jump;
* removing a stretch of the main track (``delete`` with ``ripple``,
  ``remove_silences``) also closes that stretch on every other track and in
  the captions: a title over a sentence stays over that sentence;
* a track item stands where it is put; ``ripple`` on a track only moves the
  later items of that track.

Actions run in order, all or nothing: the spec is copied first, and the first
action that cannot be done raises ``NodeError`` naming its index. After each
action the spec is passed through :func:`dodaios.nodes.kinds.motion.normalize`,
so a value the grammar refuses is reported at the action that set it.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping
from typing import Any, Final

from dodaios.nodes.kinds import motion
from dodaios.nodes.kinds import motion_media as mm
from dodaios.nodes.types import NodeError

ACTIONS: Final[tuple[str, ...]] = (
    "add_clip",
    "add_scene",
    "add_text",
    "add_music",
    "split",
    "trim",
    "delete",
    "move",
    "set",
    "keyframe",
    "transition",
    "captions",
    "caption_style",
    "caption_edit",
    "remove_silences",
    "format",
    "duplicate",
)

#: The shortest piece a cut or a trim may leave (the grammar's own floor).
MIN_PIECE: Final[float] = mm.MIN_ITEM_SECONDS
#: How close to a piece's edge a cut is refused: a sliver nobody could see.
_EDGE: Final[float] = 0.05
#: Fields an action may never set directly: the editor's identity of a thing.
_FIXED: Final[frozenset[str]] = frozenset({"id", "type", "do"})
#: The card scene types (not pieces of a video).
_CARDS: Final[frozenset[str]] = frozenset(kind for kind in motion.SCENE_TYPES if kind != "video")
#: A key's fields and how the page names them.
_KEY_FIELDS: Final[tuple[str, ...]] = ("zoom", "x", "y", "rotate", "opacity")

_CLOCK_RE: Final = re.compile(r"^\s*(?:(\d+):)?(\d+(?:[.,]\d+)?)\s*s?\s*$")


# --- reading values ------------------------------------------------------------


def _time(value: Any, what: str) -> float:
    """Seconds from a number, ``"4.2"``, ``"4.2s"`` or ``"1:04.5"``."""
    if isinstance(value, bool):
        raise NodeError(f"'{what}' must be a time in seconds, like 4.2 or \"1:04.5\".")
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        match = _CLOCK_RE.match(str(value or ""))
        if match is None:
            raise NodeError(f"'{what}' must be a time in seconds, like 4.2 or \"1:04.5\".")
        seconds = int(match.group(1) or 0) * 60 + float(match.group(2).replace(",", "."))
    if seconds < 0 or seconds != seconds:
        raise NodeError(f"'{what}' must not be negative.")
    return seconds


def _r(value: float) -> float | int:
    """A time as the spec keeps it: three decimals, a whole number plainly."""
    rounded = round(float(value), 3)
    return int(rounded) if rounded == int(rounded) else rounded


# --- finding things ------------------------------------------------------------


def starts(spec: Mapping[str, Any]) -> list[float]:
    """When each main-track piece starts on the clip's clock."""
    out: list[float] = []
    at = 0.0
    for scene in spec.get("scenes") or []:
        out.append(at)
        at += float(scene.get("seconds") or 0)
    return out


def main_length(spec: Mapping[str, Any]) -> float:
    return sum(float(scene.get("seconds") or 0) for scene in spec.get("scenes") or [])


class _Where:
    """Where an id lives: the main track (``track`` None) or a track's item."""

    def __init__(self, track: int | None, index: int) -> None:
        self.track = track
        self.index = index

    @property
    def main(self) -> bool:
        return self.track is None


def _find(spec: dict[str, Any], ref: Any) -> _Where:
    key = str(ref or "").strip().lower()
    if not key:
        raise NodeError("'id' is required: a piece's or an item's id ('read' lists them).")
    for index, scene in enumerate(spec.get("scenes") or []):
        if str(scene.get("id") or "") == key:
            return _Where(None, index)
    for number, track in enumerate(spec.get("tracks") or []):
        for index, item in enumerate(track.get("items") or []):
            if str(item.get("id") or "") == key:
                return _Where(number, index)
    raise NodeError(f"Nothing on the timeline has the id {key!r}; 'read' lists the ids.")


def _thing(spec: dict[str, Any], where: _Where) -> dict[str, Any]:
    if where.main:
        return spec["scenes"][where.index]
    return spec["tracks"][where.track]["items"][where.index]


def _span(spec: dict[str, Any], where: _Where) -> tuple[float, float]:
    """Timeline start and end of a piece or an item."""
    thing = _thing(spec, where)
    if where.main:
        start = starts(spec)[where.index]
    else:
        start = float(thing.get("start") or 0)
    return start, start + float(thing.get("seconds") or 0)


def _new_id(spec: dict[str, Any], prefix: str, wanted: Any = None) -> str:
    """A free id: the wanted one when it is well-formed and unused, else ``<prefix><n>``."""
    taken = mm.given_ids(spec)
    ids = mm.Ids(taken)
    given = str(wanted or "").strip().lower()
    if given and given not in taken:
        found = ids.take(given, prefix)
        if found == given:
            return found
    return ids.take(None, prefix)


def _media(spec: dict[str, Any], ref: Any, kinds: tuple[str, ...], what: str) -> str:
    """A library id from an id or a file's name (case-insensitive, must be unique)."""
    library: dict[str, Any] = spec.get("media") or {}
    key = str(ref or "").strip()
    if not key:
        raise NodeError(f"{what} needs 'media': a library id or a file name ('read' lists them).")
    found = key.lower() if key.lower() in library else ""
    if not found:
        named = [
            mid
            for mid, entry in library.items()
            if str(entry.get("name", "")).lower() == key.lower()
        ]
        if len(named) == 1:
            found = named[0]
        elif len(named) > 1:
            raise NodeError(f"Several files are named {key!r}; use the media id instead.")
    if not found:
        raise NodeError(
            f"The clip's library has no media {key!r}: import the file first (operation "
            "'import'), then use the id it returns."
        )
    kind = library[found].get("kind")
    if kind not in kinds:
        raise NodeError(f"{what} needs {' or '.join(kinds)} media; {key!r} is {kind}.")
    return found


def _source_left(spec: dict[str, Any], thing: dict[str, Any]) -> float | None:
    """How many seconds of source the piece may still use from its ``in`` (None: unknown)."""
    entry = (spec.get("media") or {}).get(str(thing.get("media") or ""))
    if not entry or entry.get("kind") == "image" or not entry.get("seconds"):
        return None
    return float(entry["seconds"]) - float(thing.get("in") or 0)


def _check_source(spec: dict[str, Any], thing: dict[str, Any], what: str) -> None:
    left = _source_left(spec, thing)
    if left is None:
        return
    if float(thing.get("in") or 0) < 0:
        raise NodeError(f"{what}: the piece would start before its source does.")
    needed = float(thing["seconds"]) * float(thing.get("speed") or 1)
    if needed > left + 0.05:
        raise NodeError(
            f"{what}: the source has only {max(0.0, left):.2f} s left after 'in' "
            f"({left / float(thing.get('speed') or 1):.2f} s at this speed)."
        )


def _is_blank_starter(spec: dict[str, Any]) -> bool:
    """The one empty card a new clip opens with: a first piece replaces it."""
    scenes = spec.get("scenes") or []
    if len(scenes) != 1:
        return False
    scene = scenes[0]
    if scene.get("type") not in ("title", "text", "end"):
        return False
    return not any(scene.get(field) for field in ("kicker", "title", "text"))


# --- keys ----------------------------------------------------------------------


def _smooth(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def key_value(keys: list[dict[str, Any]], field: str, t: float) -> float | None:
    """A key field's value at ``t``, as the page interpolates it (None: no key sets it)."""
    listed = [key for key in keys if isinstance(key.get(field), (int, float))]
    if not listed:
        return None
    if t <= float(listed[0]["t"]):
        return float(listed[0][field])
    if t >= float(listed[-1]["t"]):
        return float(listed[-1][field])
    for before, after in zip(listed, listed[1:], strict=False):
        if t <= float(after["t"]):
            span = max(1e-6, float(after["t"]) - float(before["t"]))
            share = _smooth((t - float(before["t"])) / span)
            return float(before[field]) + (float(after[field]) - float(before[field])) * share
    return float(listed[-1][field])


def _cut_keys(
    keys: list[dict[str, Any]], at: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keys of a piece cut at ``at`` (its own clock): left keeps its clock, right restarts."""
    if not keys:
        return [], []
    edge: dict[str, Any] = {}
    for field in _KEY_FIELDS:
        value = key_value(keys, field, at)
        if value is not None:
            edge[field] = round(value, 4)
    left = [dict(key) for key in keys if float(key["t"]) < at - 1e-6]
    right = [{**key, "t": _r(float(key["t"]) - at)} for key in keys if float(key["t"]) > at + 1e-6]
    return left + [{"t": _r(at), **edge}], [{"t": 0, **edge}, *right]


# --- the main track ------------------------------------------------------------


def _split_piece(spec: dict[str, Any], index: int, at: float) -> str:
    """Cut main-track piece ``index`` at timeline time ``at``; returns the right half's id."""
    scene = spec["scenes"][index]
    start = starts(spec)[index]
    seconds = float(scene["seconds"])
    offset = at - start
    if scene.get("type") != "video":
        raise NodeError(
            f"'{scene.get('id')}' is a {scene.get('type')} card; only video pieces and track "
            "items are split (shorten a card with 'trim', or add a second card)."
        )
    if offset < MIN_PIECE - 1e-9 or seconds - offset < MIN_PIECE - 1e-9:
        raise NodeError(
            f"{at:.3f} s is not inside '{scene['id']}' ({start:.3f} to {start + seconds:.3f} s) "
            f"far enough from its edges ({MIN_PIECE} s)."
        )
    speed = float(scene.get("speed") or 1)
    left = copy.deepcopy(scene)
    right = copy.deepcopy(scene)
    left["seconds"] = _r(offset)
    right["seconds"] = _r(seconds - offset)
    right["in"] = _r(float(scene.get("in") or 0) + offset * speed)
    right["id"] = _new_id(spec, "v")
    right["transition"] = "cut"
    left.pop("fade_out", None)
    right.pop("fade_in", None)
    if scene.get("keys"):
        left["keys"], right["keys"] = _cut_keys(scene["keys"], offset)
    spec["scenes"][index : index + 1] = [left, right]
    return str(right["id"])


def _close_gap(spec: dict[str, Any], at: float, length: float) -> None:
    """Take ``[at, at + length]`` out of every track and the captions (main ripple)."""
    if length <= 0:
        return
    end = at + length
    for track in spec.get("tracks") or []:
        kept: list[dict[str, Any]] = []
        for item in track.get("items") or []:
            start = float(item["start"])
            stop = start + float(item["seconds"])
            speed = float(item.get("speed") or 1)
            if stop <= at + 1e-9:
                kept.append(item)
                continue
            if start >= end - 1e-9:
                item["start"] = _r(start - length)
                kept.append(item)
                continue
            if start >= at and stop <= end:
                continue  # wholly inside the removed stretch
            if start >= at:  # starts inside: its head goes
                head = end - start
                item["start"] = _r(at)
                item["seconds"] = _r(stop - start - head)
                if "media" in item:
                    item["in"] = _r(float(item.get("in") or 0) + head * speed)
            else:  # starts before: the stretch is cut out of it
                item["seconds"] = _r(float(item["seconds"]) - min(stop, end) + at)
            if float(item["seconds"]) >= MIN_PIECE:
                kept.append(item)
        track["items"] = kept
    captions = spec.get("captions")
    if not captions:
        return
    lines: list[dict[str, Any]] = []
    for line in captions.get("items") or []:
        first, last = float(line["start"]), float(line["end"])
        if last <= at + 1e-9:
            lines.append(line)
            continue
        if first >= end - 1e-9:
            line["start"], line["end"] = _r(first - length), _r(last - length)
            if line.get("words"):
                line["words"] = [[_r(a - length), _r(b - length)] for a, b in line["words"]]
            lines.append(line)
            continue
        if first >= at and last <= end:
            continue
        # A line the cut runs through keeps its words, its timing is closed up.
        new_first = first if first < at else at
        new_last = last - min(length, max(0.0, last - at))
        line.pop("words", None)
        if new_last - new_first >= 0.2:
            line["start"], line["end"] = _r(new_first), _r(new_last)
            lines.append(line)
    captions["items"] = lines


def _remove_piece(spec: dict[str, Any], index: int, *, shift: bool) -> None:
    start = starts(spec)[index]
    seconds = float(spec["scenes"][index]["seconds"])
    del spec["scenes"][index]
    if shift:
        _close_gap(spec, start, seconds)


def _insert_index(spec: dict[str, Any], action: dict[str, Any]) -> int:
    """Where a new piece goes: ``index``, or next to the piece at time ``at``, else the end."""
    count = len(spec.get("scenes") or [])
    if action.get("index") is not None:
        try:
            return max(0, min(count, int(action["index"])))
        except (TypeError, ValueError) as exc:
            raise NodeError("'index' must be a whole number (0 is the first place).") from exc
    if action.get("at") is None:
        return count
    at = _time(action["at"], "at")
    for index, (start, scene) in enumerate(zip(starts(spec), spec["scenes"], strict=True)):
        end = start + float(scene["seconds"])
        if start - 1e-9 <= at < end:
            return index if at - start < (end - start) / 2 else index + 1
    return count


def _fields(action: dict[str, Any], skip: tuple[str, ...] = ()) -> dict[str, Any]:
    """An action's values meant for the thing itself."""
    return {
        key: value
        for key, value in action.items()
        if key not in _FIXED and key not in skip and value is not None
    }


# --- tracks --------------------------------------------------------------------


def _overlaps(track: dict[str, Any], start: float, end: float) -> bool:
    for item in track.get("items") or []:
        first = float(item["start"])
        if first < end - 1e-9 and first + float(item["seconds"]) > start + 1e-9:
            return True
    return False


def _track_for(
    spec: dict[str, Any], kind: str, start: float, end: float, wanted: Any = None
) -> dict[str, Any]:
    """The track a new item of ``kind`` goes on: the named one, else the topmost free one."""
    tracks: list[dict[str, Any]] = spec.setdefault("tracks", [])
    if wanted:
        key = str(wanted).strip().lower()
        for track in tracks:
            if track.get("id") == key:
                if track.get("kind") != kind:
                    raise NodeError(f"Track {key!r} holds {track.get('kind')} items, not {kind}.")
                return track
        raise NodeError(f"There is no track {key!r}; 'read' lists the tracks.")
    for track in reversed(tracks):
        if (
            track.get("kind") == kind
            and not track.get("locked")
            and not _overlaps(track, start, end)
        ):
            return track
    if len(tracks) >= mm.MAX_TRACKS:
        raise NodeError(
            f"A clip has at most {mm.MAX_TRACKS} tracks; put the item on an existing one."
        )
    track = {"id": _new_id(spec, "tr"), "kind": kind, "items": []}
    if kind == "audio":
        # Sound goes under the pictures in the editor; text and pictures on top.
        tracks.insert(0, track)
    else:
        tracks.append(track)
    return track


def _clip_end(spec: dict[str, Any]) -> float:
    ends = [main_length(spec)]
    for track in spec.get("tracks") or []:
        for item in track.get("items") or []:
            if track.get("kind") != "audio":
                ends.append(float(item["start"]) + float(item["seconds"]))
    return max(ends)


def _natural(spec: dict[str, Any], media_id: str, action: dict[str, Any], default: float) -> float:
    """How long a new piece runs: 'seconds', else 'out' - 'in', else the rest of its source."""
    if action.get("seconds") is not None:
        return _time(action["seconds"], "seconds")
    entry = spec["media"][media_id]
    speed = float(action.get("speed") or 1)
    start = _time(action.get("in") or 0, "in")
    if action.get("out") is not None:
        out = _time(action["out"], "out")
        if out <= start:
            raise NodeError("'out' must be later than 'in'.")
        return (out - start) / speed
    if entry.get("kind") == "image" or not entry.get("seconds"):
        return default
    return max(MIN_PIECE, (float(entry["seconds"]) - start) / speed)


# --- the actions ---------------------------------------------------------------


def _add_clip(spec: dict[str, Any], action: dict[str, Any]) -> str:
    media_id = _media(spec, action.get("media"), ("video", "image", "audio"), "add_clip")
    kind = spec["media"][media_id]["kind"]
    lane = str(action.get("track") or ("audio" if kind == "audio" else "main")).strip().lower()
    if lane == "music":
        lane = "audio"
    if kind == "audio" and lane != "audio" and not lane.startswith("tr"):
        raise NodeError("A sound file goes on an audio track ('track': 'audio' or add_music).")
    values = _fields(action, ("media", "track", "at", "index", "out", "start"))
    values["seconds"] = _r(_natural(spec, media_id, action, 4.0))
    if lane == "main":
        scene = {"type": "video", "media": media_id, **values}
        scene["id"] = _new_id(spec, "v", action.get("id"))
        scene.setdefault("transition", "cut")
        if _is_blank_starter(spec):
            spec["scenes"] = [scene]
        else:
            spec["scenes"].insert(_insert_index(spec, action), scene)
        _check_source(spec, scene, "add_clip")
        return f"added piece {scene['id']} ({float(scene['seconds']):.2f} s) to the main track"
    track_kind = "audio" if kind == "audio" or lane == "audio" else "overlay"
    if lane not in ("audio", "overlay", "main"):
        track_kind = next(
            (t["kind"] for t in spec.get("tracks") or [] if t.get("id") == lane), track_kind
        )
    start = _time(action.get("at", action.get("start", 0)) or 0, "at")
    end = start + float(values["seconds"])
    track = _track_for(spec, track_kind, start, end, lane if lane.startswith("tr") else None)
    prefix = "a" if track_kind == "audio" else "o"
    item = {"id": _new_id(spec, prefix, action.get("id")), "media": media_id, **values}
    item["start"] = _r(start)
    _check_source(spec, item, "add_clip")
    track["items"].append(item)
    return f"added {track_kind} item {item['id']} at {start:.2f} s on track {track['id']}"


def _add_scene(spec: dict[str, Any], action: dict[str, Any]) -> str:
    kind = str(action.get("type") or action.get("scene") or "").strip().lower()
    if kind not in _CARDS:
        raise NodeError("add_scene needs 'type': " + ", ".join(sorted(_CARDS)) + ".")
    scene = {"type": kind, **_fields(action, ("index", "at", "scene"))}
    scene["id"] = _new_id(spec, "s", action.get("id"))
    index = _insert_index(spec, action)
    spec["scenes"].insert(index, scene)
    return f"added {kind} card {scene['id']} as piece {index + 1}"


def _add_text(spec: dict[str, Any], action: dict[str, Any]) -> str:
    text = str(action.get("text") or "").strip()
    if not text:
        raise NodeError("add_text needs 'text'.")
    start = _time(action.get("start", action.get("at", 0)) or 0, "start")
    seconds = _time(action.get("seconds") or 3, "seconds")
    track = _track_for(spec, "text", start, start + seconds, action.get("track"))
    item = {**_fields(action, ("track", "at", "start", "seconds")), "start": _r(start)}
    item["seconds"] = _r(seconds)
    item["id"] = _new_id(spec, "x", action.get("id"))
    track["items"].append(item)
    return (
        f"added text {item['id']} ({start:.2f} to {start + seconds:.2f} s) on track {track['id']}"
    )


def _add_music(spec: dict[str, Any], action: dict[str, Any]) -> str:
    media_id = _media(spec, action.get("media"), ("audio", "video"), "add_music")
    start = _time(action.get("start", action.get("at", 0)) or 0, "start")
    entry = spec["media"][media_id]
    speed = float(action.get("speed") or 1)
    source_in = _time(action.get("in") or 0, "in")
    if action.get("seconds") is not None:
        seconds = _time(action["seconds"], "seconds")
    else:
        seconds = max(MIN_PIECE, _clip_end(spec) - start)
        if entry.get("seconds"):
            seconds = min(seconds, (float(entry["seconds"]) - source_in) / speed)
    track = _track_for(spec, "audio", start, start + seconds, action.get("track"))
    item: dict[str, Any] = {
        "volume": 0.25,
        "fade_in": 1,
        "fade_out": 2,
        "duck": True,
        **_fields(action, ("media", "track", "at", "start", "seconds")),
        "media": media_id,
        "start": _r(start),
        "seconds": _r(seconds),
    }
    item["id"] = _new_id(spec, "a", action.get("id"))
    _check_source(spec, item, "add_music")
    track["items"].append(item)
    span = f"{start:.2f} to {start + seconds:.2f} s"
    return f"added music {item['id']} ({span}, volume {item['volume']})"


def _split(spec: dict[str, Any], action: dict[str, Any]) -> str:
    where = _find(spec, action.get("id"))
    at = _time(action.get("at"), "at")
    if where.main:
        right = _split_piece(spec, where.index, at)
        return f"split at {at:.3f} s; the second half is {right}"
    item = _thing(spec, where)
    start, end = _span(spec, where)
    if at - start < MIN_PIECE - 1e-9 or end - at < MIN_PIECE - 1e-9:
        raise NodeError(f"{at:.3f} s is not inside '{item['id']}' ({start:.3f} to {end:.3f} s).")
    offset = at - start
    left, right = copy.deepcopy(item), copy.deepcopy(item)
    left["seconds"] = _r(offset)
    right["start"] = _r(at)
    right["seconds"] = _r(end - at)
    track = spec["tracks"][where.track]
    right["id"] = _new_id(spec, {"text": "x", "overlay": "o", "audio": "a"}[track["kind"]])
    if "media" in item:
        right["in"] = _r(float(item.get("in") or 0) + offset * float(item.get("speed") or 1))
    left.pop("fade_out", None)
    right.pop("fade_in", None)
    if track["kind"] != "audio":
        left["out"] = "none"
        right["anim"] = "none"
    if item.get("keys"):
        left["keys"], right["keys"] = _cut_keys(item["keys"], offset)
    track["items"][where.index : where.index + 1] = [left, right]
    return f"split at {at:.3f} s; the second half is {right['id']}"


def _trim(spec: dict[str, Any], action: dict[str, Any]) -> str:
    where = _find(spec, action.get("id"))
    thing = _thing(spec, where)
    start, end = _span(spec, where)
    speed = float(thing.get("speed") or 1)
    media_piece = "media" in thing
    if action.get("in") is not None:
        if not media_piece:
            raise NodeError(f"'{thing['id']}' has no source to slip ('in' is for video and sound).")
        thing["in"] = _r(_time(action["in"], "in"))
    if action.get("start") is not None:
        new_start = _time(action["start"], "start")
        head = new_start - start
        if end - new_start < MIN_PIECE:
            raise NodeError(
                f"'start' {new_start:.3f} s leaves less than {MIN_PIECE} s of '{thing['id']}'."
            )
        if media_piece:
            moved = float(thing.get("in") or 0) + head * speed
            if moved < -1e-6:
                raise NodeError(
                    f"'{thing['id']}' cannot start earlier: its source begins "
                    f"{float(thing.get('in') or 0) / speed:.3f} s before its current start."
                )
            thing["in"] = _r(max(0.0, moved))
        thing["seconds"] = _r(end - new_start)
        if not where.main:
            thing["start"] = _r(new_start)
        start = new_start
    if action.get("end") is not None:
        new_end = _time(action["end"], "end")
        # On the magnetic main track a piece's start may have moved with the head trim.
        if where.main:
            start = starts(spec)[where.index]
        if new_end - start < MIN_PIECE:
            raise NodeError(
                f"'end' {new_end:.3f} s leaves less than {MIN_PIECE} s of '{thing['id']}'."
            )
        thing["seconds"] = _r(new_end - start)
    if action.get("seconds") is not None:
        thing["seconds"] = _r(_time(action["seconds"], "seconds"))
    if media_piece:
        _check_source(spec, thing, "trim")
    first, last = _span(spec, where)
    return f"{thing['id']} now runs {first:.3f} to {last:.3f} s"


def _delete(spec: dict[str, Any], action: dict[str, Any]) -> str:
    refs = action.get("ids") if action.get("ids") is not None else [action.get("id")]
    if not isinstance(refs, list) or not refs:
        raise NodeError("delete needs 'ids': a list of ids.")
    wheres = [(_find(spec, ref), str(ref).strip().lower()) for ref in refs]
    mains = sorted({w.index for w, _ in wheres if w.main}, reverse=True)
    if mains and len(mains) >= len(spec["scenes"]):
        raise NodeError("The main track keeps at least one piece; delete fewer or add one first.")
    ripple_main = action.get("ripple") is not False
    removed: list[str] = []
    # Track items first (their indices do not move with the main track).
    by_track: dict[int, list[int]] = {}
    for where, ref in wheres:
        if not where.main:
            by_track.setdefault(where.track, []).append(where.index)
            removed.append(ref)
    for number, indices in by_track.items():
        track = spec["tracks"][number]
        for index in sorted(set(indices), reverse=True):
            item = track["items"][index]
            first = float(item["start"])
            length = float(item["seconds"])
            del track["items"][index]
            if action.get("ripple") is True:
                for later in track["items"]:
                    if float(later["start"]) >= first + length - 1e-9:
                        later["start"] = _r(float(later["start"]) - length)
    for index in mains:
        removed.append(str(spec["scenes"][index].get("id")))
        _remove_piece(spec, index, shift=ripple_main)
    return "deleted " + ", ".join(removed)


def _move(spec: dict[str, Any], action: dict[str, Any]) -> str:
    where = _find(spec, action.get("id"))
    thing = _thing(spec, where)
    if where.main:
        if action.get("index") is None:
            raise NodeError("A main-track piece moves by 'index' (its new place, 0 is the first).")
        try:
            target = max(0, min(len(spec["scenes"]) - 1, int(action["index"])))
        except (TypeError, ValueError) as exc:
            raise NodeError("'index' must be a whole number.") from exc
        scene = spec["scenes"].pop(where.index)
        spec["scenes"].insert(target, scene)
        return f"moved {thing['id']} to place {target + 1}"
    track = spec["tracks"][where.track]
    if action.get("to") is not None:
        thing["start"] = _r(_time(action["to"], "to"))
    if action.get("track"):
        key = str(action["track"]).strip().lower()
        target_track = next((t for t in spec.get("tracks") or [] if t.get("id") == key), None)
        if target_track is None:
            raise NodeError(f"There is no track {key!r}; 'read' lists the tracks.")
        if target_track["kind"] != track["kind"]:
            raise NodeError(
                f"Track {key!r} holds {target_track['kind']} items, not {track['kind']}."
            )
        track["items"].remove(thing)
        target_track["items"].append(thing)
        track = target_track
    return f"moved {thing['id']} to {float(thing['start']):.3f} s on track {track['id']}"


def _set(spec: dict[str, Any], action: dict[str, Any]) -> str:
    where = _find(spec, action.get("id"))
    thing = _thing(spec, where)
    changed = []
    for key, value in action.items():
        if key in _FIXED or (where.main and key == "start"):
            continue
        if value is None:
            thing.pop(key, None)
        else:
            thing[key] = value
        changed.append(key)
    if not changed:
        raise NodeError("set needs at least one field besides 'id'.")
    if "media" in thing and any(k in changed for k in ("in", "seconds", "speed")):
        _check_source(spec, thing, "set")
    return f"set {', '.join(changed)} of {thing['id']}"


def _keyframe(spec: dict[str, Any], action: dict[str, Any]) -> str:
    where = _find(spec, action.get("id"))
    thing = _thing(spec, where)
    if where.main and thing.get("type") != "video":
        raise NodeError("Keyframes move video pieces and track items, not cards.")
    t = _time(action.get("t", 0), "t")
    if t > float(thing["seconds"]) + 1e-6:
        raise NodeError(f"'t' is inside the item: 0 to {float(thing['seconds']):.3f} s.")
    keys: list[dict[str, Any]] = [dict(key) for key in thing.get("keys") or []]
    keys = [key for key in keys if abs(float(key["t"]) - t) > 1e-3]
    if action.get("remove"):
        thing["keys"] = keys
        return f"removed the key at {t:.3f} s of {thing['id']}"
    key: dict[str, Any] = {"t": _r(t)}
    for field in _KEY_FIELDS:
        if action.get(field) is not None:
            key[field] = action[field]
    if len(key) == 1:
        raise NodeError("A key sets at least one of zoom, x, y, rotate, opacity.")
    keys.append(key)
    keys.sort(key=lambda each: float(each["t"]))
    thing["keys"] = keys
    return f"key at {t:.3f} s of {thing['id']}"


def _transition(spec: dict[str, Any], action: dict[str, Any]) -> str:
    where = _find(spec, action.get("id"))
    if not where.main:
        raise NodeError("Transitions are between main-track pieces; a track item has 'anim'/'out'.")
    kind = str(action.get("kind") or action.get("transition") or "").strip().lower()
    if kind not in motion.TRANSITIONS:
        raise NodeError("transition 'kind' must be one of " + ", ".join(motion.TRANSITIONS) + ".")
    spec["scenes"][where.index]["transition"] = kind
    return f"{kind} into {spec['scenes'][where.index]['id']}"


def _captions(spec: dict[str, Any], action: dict[str, Any]) -> str:
    items = action.get("items")
    if not isinstance(items, list):
        raise NodeError(
            "captions needs 'items': [{start, end, text}] (or use operation 'captions')."
        )
    old = spec.get("captions") or {}
    spec["captions"] = {
        "style": action.get("style") or old.get("style") or "karaoke",
        "position": action.get("position") or old.get("position") or "bottom",
        "size": action.get("size") or old.get("size") or "m",
        "items": items,
    }
    return f"{len(items)} caption line(s)"


def _caption_style(spec: dict[str, Any], action: dict[str, Any]) -> str:
    captions = spec.get("captions")
    if not captions:
        raise NodeError("The clip has no captions yet; make them first (operation 'captions').")
    for key in ("style", "position", "size"):
        if action.get(key) is not None:
            captions[key] = action[key]
    return (
        f"captions: {captions['style']}, {captions['position']}, size {captions.get('size', 'm')}"
    )


def _caption_edit(spec: dict[str, Any], action: dict[str, Any]) -> str:
    captions = spec.get("captions") or {}
    lines = captions.get("items") or []
    raw = action.get("remove", action.get("index"))
    try:
        index = int(raw)
    except (TypeError, ValueError) as exc:
        raise NodeError("caption_edit needs 'index' (0 is the first line) or 'remove'.") from exc
    if not 0 <= index < len(lines):
        raise NodeError(f"There is no caption line {index}; the clip has {len(lines)}.")
    if action.get("remove") is not None:
        del lines[index]
        return f"removed caption line {index}"
    line = lines[index]
    if action.get("text") is not None:
        line["text"] = str(action["text"])
        if len(str(action["text"]).split()) != len(line.get("words") or []):
            line.pop("words", None)
    for key in ("start", "end"):
        if action.get(key) is not None:
            line[key] = _r(_time(action[key], key))
            # Word times outside the line's new edges would be clamped wrongly: drop them.
            line.pop("words", None)
    return f"edited caption line {index}"


def _remove_silences(spec: dict[str, Any], action: dict[str, Any]) -> str:
    where = _find(spec, action.get("id"))
    scene = _thing(spec, where)
    if not where.main or scene.get("type") != "video":
        raise NodeError("remove_silences works on a video piece of the main track.")
    spans = action.get("silences")
    if not isinstance(spans, list):
        raise NodeError("remove_silences needs 'silences': [[start, end], ...] in source seconds.")
    piece_id = str(scene["id"])
    source_in = float(scene.get("in") or 0)
    speed = float(scene.get("speed") or 1)
    source_out = source_in + float(scene["seconds"]) * speed
    ranges: list[tuple[float, float]] = []
    for pair in spans:
        if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
            raise NodeError("Each silence is [start, end] in source seconds.")
        first = max(source_in, _time(pair[0], "silence start"))
        last = min(source_out, _time(pair[1], "silence end"))
        if last - first >= 0.05:
            ranges.append((first, last))
    ranges.sort()
    removed = 0.0
    cuts = 0
    # From the last silence back, so the earlier ones keep their place.
    for first, last in reversed(ranges):
        # The piece holding this silence may be a half left by an earlier cut.
        index = _piece_holding(spec, piece_id, first)
        if index is None:
            continue
        start = starts(spec)[index]
        piece = spec["scenes"][index]
        piece_in = float(piece.get("in") or 0)
        a = start + (first - piece_in) / speed
        b = start + (last - piece_in) / speed
        end = start + float(piece["seconds"])
        a = max(start, a)
        b = min(end, b)
        if b - a < 0.05:
            continue
        target = index
        if a - start >= MIN_PIECE:
            _split_piece(spec, index, a)
            target = index + 1
        elif a > start + 1e-9:
            a = start  # too short a head to keep: it goes with the silence
        piece_end = starts(spec)[target] + float(spec["scenes"][target]["seconds"])
        if piece_end - b >= MIN_PIECE:
            _split_piece(spec, target, b)
        else:
            b = piece_end
        if len(spec["scenes"]) <= 1:
            break
        _remove_piece(spec, target, shift=True)
        removed += b - a
        cuts += 1
    return f"removed {cuts} silence(s), {removed:.2f} s in all"


def _piece_holding(spec: dict[str, Any], origin: str, source_time: float) -> int | None:
    """The main-track piece cut from ``origin`` whose source holds ``source_time``.

    Cutting from the last silence back, ``origin`` itself is always the piece
    that holds the earlier silences: its later halves were cut off or removed.
    """
    for index, scene in enumerate(spec["scenes"]):
        if scene.get("id") != origin:
            continue
        first = float(scene.get("in") or 0)
        last = first + float(scene["seconds"]) * float(scene.get("speed") or 1)
        return index if first - 1e-6 <= source_time < last + 1e-6 else None
    return None


def _format(spec: dict[str, Any], action: dict[str, Any]) -> str:
    changed = []
    for key in ("format", "theme", "accent", "loop"):
        if action.get(key) is not None:
            spec[key] = action[key]
            changed.append(f"{key} {action[key]}")
    if not changed:
        raise NodeError("format needs one of format, theme, accent, loop.")
    if action.get("format") is not None and action["format"] not in motion.FORMATS:
        raise NodeError("'format' must be one of " + ", ".join(motion.FORMATS) + ".")
    return ", ".join(changed)


def _duplicate(spec: dict[str, Any], action: dict[str, Any]) -> str:
    where = _find(spec, action.get("id"))
    thing = copy.deepcopy(_thing(spec, where))
    if where.main:
        thing["id"] = _new_id(
            spec, "v" if thing.get("type") == "video" else "s", action.get("new_id")
        )
        spec["scenes"].insert(where.index + 1, thing)
        return f"copied as {thing['id']} right after it"
    track = spec["tracks"][where.track]
    prefix = {"text": "x", "overlay": "o", "audio": "a"}[track["kind"]]
    thing["id"] = _new_id(spec, prefix, action.get("new_id"))
    thing["start"] = _r(float(thing["start"]) + float(thing["seconds"]))
    track["items"].append(thing)
    return f"copied as {thing['id']} at {float(thing['start']):.3f} s"


_HANDLERS: Final[dict[str, Callable[[dict[str, Any], dict[str, Any]], str]]] = {
    "add_clip": _add_clip,
    "add_scene": _add_scene,
    "add_text": _add_text,
    "add_music": _add_music,
    "split": _split,
    "trim": _trim,
    "delete": _delete,
    "move": _move,
    "set": _set,
    "keyframe": _keyframe,
    "transition": _transition,
    "captions": _captions,
    "caption_style": _caption_style,
    "caption_edit": _caption_edit,
    "remove_silences": _remove_silences,
    "format": _format,
    "duplicate": _duplicate,
}


def with_ids(spec: dict[str, Any]) -> dict[str, Any]:
    """The spec with an id on every main-track piece (cards get none by themselves)."""
    spec = copy.deepcopy(spec)
    ids = mm.Ids(mm.given_ids(spec))
    for scene in spec.get("scenes") or []:
        if isinstance(scene, dict):
            scene["id"] = ids.take(scene.get("id"), "v" if scene.get("type") == "video" else "s")
    return spec


def apply_actions(
    spec: dict[str, Any],
    actions: list[dict[str, Any]],
    *,
    media_lookup: Mapping[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Run ``actions`` on a copy of ``spec``; returns the new spec and one line per action.

    ``media_lookup`` adds library entries first (files imported in the same call).
    All or nothing: the first action that fails raises ``NodeError`` and the
    caller's spec is untouched.
    """
    if not isinstance(actions, list):
        raise NodeError('\'actions\' must be a list of objects like {"do": "split", ...}.')
    work = motion.normalize(spec)
    if media_lookup:
        work.setdefault("media", {}).update(copy.deepcopy(dict(media_lookup)))
        work = motion.normalize(work)
    work = with_ids(work)
    report: list[str] = []
    for number, action in enumerate(actions):
        where = f"Action {number + 1}"
        if not isinstance(action, dict):
            raise NodeError(f'{where} must be an object like {{"do": "split", ...}}.')
        name = str(action.get("do") or "").strip().lower()
        handler = _HANDLERS.get(name)
        if handler is None:
            raise NodeError(f"{where}: 'do' must be one of {', '.join(ACTIONS)}.")
        try:
            line = handler(work, dict(action))
            work = with_ids(motion.normalize(work))
        except NodeError as exc:
            raise NodeError(f"{where} ({name}): {exc}") from None
        report.append(f"{number + 1}. {line}")
    return work, report


# --- reading -------------------------------------------------------------------


def _words(text: Any, limit: int = 6) -> str:
    parts = str(text or "").split()
    return " ".join(parts[:limit]) + (" …" if len(parts) > limit else "")


def _scene_words(scene: dict[str, Any]) -> str:
    for field in ("title", "text", "quote", "value", "caption", "label"):
        if scene.get(field):
            return _words(scene[field])
    if scene.get("bullets"):
        return _words(scene["bullets"][0])
    return ""


def describe(spec: Mapping[str, Any]) -> str:
    """The clip as a compact reading for the model: every id with its times."""
    spec = with_ids(dict(spec))
    library: dict[str, Any] = spec.get("media") or {}
    total = mm.duration(spec)
    lines = [
        f"Clip: format {spec.get('format')} ({_RATIOS.get(str(spec.get('format')), '?')}), "
        f"theme {spec.get('theme')}, {total:.2f} s long, main track {main_length(spec):.2f} s."
    ]
    lines.append("Main track (back to back):")
    for start, scene in zip(starts(spec), spec.get("scenes") or [], strict=True):
        end = start + float(scene["seconds"])
        if scene.get("type") == "video":
            entry = library.get(str(scene.get("media"))) or {}
            speed = float(scene.get("speed") or 1)
            source_in = float(scene.get("in") or 0)
            extra = [f"source {source_in:.2f}-{source_in + float(scene['seconds']) * speed:.2f}"]
            if speed != 1:
                extra.append(f"speed {speed:g}")
            if scene.get("muted") or scene.get("volume") is not None:
                extra.append("muted" if scene.get("muted") else f"volume {scene['volume']}")
            for field in ("zoom", "filter", "fit"):
                if scene.get(field) is not None:
                    extra.append(f"{field} {scene[field]}")
            if scene.get("keys"):
                extra.append(f"{len(scene['keys'])} keys")
            what = f"video {entry.get('name', scene.get('media'))!r} " + ", ".join(extra)
        else:
            what = f"{scene['type']} card {_scene_words(scene)!r}"
        lines.append(
            f"- {scene['id']}: {start:.2f}-{end:.2f} s, {what}, "
            f"transition {scene.get('transition')}"
        )
    for track in spec.get("tracks") or []:
        flags = "".join(f", {flag}" for flag in ("muted", "hidden", "locked") if track.get(flag))
        lines.append(f"Track {track['id']} ({track['kind']}{flags}):")
        for item in track.get("items") or []:
            start = float(item["start"])
            end = start + float(item["seconds"])
            if track["kind"] == "text":
                words = _words(item.get("text"), 8)
                what = f"{item.get('style', 'title')} {words!r} at {item.get('x')},{item.get('y')}"
            else:
                entry = library.get(str(item.get("media"))) or {}
                what = repr(entry.get("name", item.get("media")))
                if item.get("volume") is not None:
                    what += f" volume {item['volume']}"
                if item.get("duck"):
                    what += " ducked"
                if track["kind"] == "overlay":
                    what += f" at {item.get('x')},{item.get('y')} width {item.get('w')}%"
            lines.append(f"- {item['id']}: {start:.2f}-{end:.2f} s, {what}")
    captions = spec.get("captions") or {}
    items = captions.get("items") or []
    if items:
        lines.append(
            f"Captions: {len(items)} line(s), {captions.get('style')}, {captions.get('position')}:"
        )
        for number, line in enumerate(items[:8]):
            lines.append(
                f"  [{number}] {float(line['start']):.2f}-{float(line['end']):.2f} {line['text']}"
            )
        if len(items) > 8:
            lines.append(f"  … {len(items) - 8} more")
    else:
        lines.append("Captions: none.")
    if library:
        lines.append("Library:")
        for media_id, entry in library.items():
            size = f", {entry['width']}x{entry['height']}" if entry.get("width") else ""
            sound = ", sound" if entry.get("audio") and entry.get("kind") == "video" else ""
            length = f", {float(entry['seconds']):.2f} s" if entry.get("seconds") else ""
            lines.append(
                f"- {media_id}: {entry.get('name')!r} {entry.get('kind')}{length}{size}{sound}"
            )
    else:
        lines.append("Library: empty (operation 'import' adds files).")
    return "\n".join(lines)


_RATIOS: Final[dict[str, str]] = {
    "wide": "16:9",
    "square": "1:1",
    "tall": "9:16",
    "portrait": "4:5",
}


def piece_times(spec: Mapping[str, Any], piece_id: str) -> dict[str, float]:
    """A piece's or item's timeline start/end and its source in/speed (for transcripts)."""
    work = with_ids(dict(spec))
    where = _find(work, piece_id)
    thing = _thing(work, where)
    start, end = _span(work, where)
    return {
        "start": start,
        "end": end,
        "in": float(thing.get("in") or 0),
        "speed": float(thing.get("speed") or 1),
        "media": thing.get("media") or "",
    }


__all__ = [
    "ACTIONS",
    "apply_actions",
    "describe",
    "key_value",
    "main_length",
    "piece_times",
    "starts",
    "with_ids",
]
