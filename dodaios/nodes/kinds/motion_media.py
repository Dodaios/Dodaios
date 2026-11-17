"""The video side of a clip (``motion`` node): media, tracks and captions.

A clip started as a film of animated cards (:mod:`dodaios.nodes.kinds.motion`).
This module adds what makes it a video editor, in the same spec and on the same
page, so the person's editor, the assistant's tool, the stage and the export
all read and draw ONE thing:

* ``media``: the clip's library. Every file the person or the assistant
  imported (a video, a sound, a picture) is kept in the node's folder
  (:mod:`dodaios.nodes.clip.media`) under a random id and described here
  (kind, length, size, whether it has sound). The page loads it from the
  app's ``/clip-media/<node>/<file>`` route; nothing else leaves the page.
* the MAIN track is the list of scenes it always was; a scene of type
  ``video`` is a piece of a video from the library (where it starts in the
  source, how fast it runs, how loud, how it is framed and coloured).
* ``tracks``: layers above the main track, each of one kind: ``text`` (titles
  and labels with an entrance), ``overlay`` (a picture or a video on top, a
  picture-in-picture or a logo) and ``audio`` (music, a voice-over). Their
  items stand at a time of their own (``start``, ``seconds``).
* ``captions``: the subtitles, timed lines with optional word times, drawn in
  one of a few styles.

As everywhere on this page, a frame is a pure function of time: a video
element is put to the source time its item says for the clock's time, and
while the film plays it is only corrected when it drifts. The export
(:mod:`dodaios.nodes.clip.export`) asks the page for each frame
(``window.__clipFrame(t)``) and waits until every video stands on it.

No spec value is ever interpolated raw: texts are escaped, numbers formatted
here, and the page's script reads its timing from ``data-`` attributes.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final

from dodaios.nodes import shell
from dodaios.nodes.shell import attr, esc
from dodaios.nodes.types import NodeError

# --- bounds --------------------------------------------------------------------

MEDIA_KINDS: Final[tuple[str, ...]] = ("video", "audio", "image")
TRACK_KINDS: Final[tuple[str, ...]] = ("text", "overlay", "audio")
FITS: Final[tuple[str, ...]] = ("cover", "contain")
FILTERS: Final[tuple[str, ...]] = (
    "none",
    "vivid",
    "warm",
    "cool",
    "mono",
    "fade",
    "noir",
    "film",
)
TEXT_STYLES: Final[tuple[str, ...]] = ("title", "subtitle", "body", "label", "caption", "quote")
TEXT_BACKS: Final[tuple[str, ...]] = ("none", "shadow", "box", "pill")
TEXT_FONTS: Final[tuple[str, ...]] = ("sans", "serif", "mono")
ALIGNS: Final[tuple[str, ...]] = ("center", "left", "right")
ENTRANCES: Final[tuple[str, ...]] = ("fade", "rise", "pop", "slide", "zoom", "type", "none")
EXITS: Final[tuple[str, ...]] = ("fade", "rise", "pop", "slide", "zoom", "none")
CAPTION_STYLES: Final[tuple[str, ...]] = ("clean", "bold", "karaoke", "boxed", "none")
CAPTION_PLACES: Final[tuple[str, ...]] = ("bottom", "middle", "top")
CAPTION_SIZES: Final[tuple[str, ...]] = ("s", "m", "l")

MAX_MEDIA: Final[int] = 200
MAX_TRACKS: Final[int] = 12
MAX_ITEMS_PER_TRACK: Final[int] = 300
MAX_CAPTIONS: Final[int] = 2_000
MAX_KEYS: Final[int] = 24
#: The longest piece of one item on the timeline, and the latest it may start.
MAX_ITEM_SECONDS: Final[float] = 3_600.0
MIN_ITEM_SECONDS: Final[float] = 0.1
MAX_START: Final[float] = 36_000.0
MIN_SPEED: Final[float] = 0.25
MAX_SPEED: Final[float] = 4.0
MAX_FADE: Final[float] = 10.0

#: A media id is a random hex word; its file is the id plus the type's ending.
_MEDIA_ID_RE: Final = re.compile(r"^[0-9a-f]{16,32}$")
_MEDIA_FILE_RE: Final = re.compile(
    r"^[0-9a-f]{16,32}\.(mp4|webm|mov|m4v|m4a|mp3|wav|aac|ogg|oga|opus|png|jpg|jpeg|webp|gif)$"
)
#: An item or scene id: short, so the assistant can name it.
_ITEM_ID_RE: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

#: The logical type size of each text style (before the format's factor).
TEXT_SIZES: Final[dict[str, int]] = {
    "title": 92,
    "subtitle": 56,
    "body": 40,
    "label": 28,
    "caption": 36,
    "quote": 58,
}

#: Each look as a CSS filter; the colour sliders are added after it.
FILTER_CSS: Final[dict[str, str]] = {
    "none": "",
    "vivid": "saturate(1.35) contrast(1.08)",
    "warm": "sepia(.2) saturate(1.15) hue-rotate(-8deg)",
    "cool": "saturate(1.05) hue-rotate(12deg) brightness(1.02)",
    "mono": "grayscale(1)",
    "fade": "contrast(.86) brightness(1.08) saturate(.8)",
    "noir": "grayscale(1) contrast(1.35) brightness(.92)",
    "film": "sepia(.12) contrast(1.1) saturate(.9)",
}


# --- small readers ---------------------------------------------------------------


def _round(value: float, places: int = 3) -> float | int:
    """A number as JSON writes it plainly: 2, not 2.0; at most ``places`` decimals."""
    rounded = round(float(value), places)
    return int(rounded) if rounded == int(rounded) else rounded


def _num(raw: Any, low: float, high: float, default: float, places: int = 3) -> float | int:
    return _round(shell.bounded(raw, low, high, default), places)


def _flag(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def media_id_ok(value: Any) -> bool:
    return isinstance(value, str) and bool(_MEDIA_ID_RE.match(value))


class Ids:
    """The ids of one spec: those it gives are kept, new ones never take one of them."""

    def __init__(self, reserved: set[str] | None = None) -> None:
        self.reserved = set(reserved or ())
        self.used: set[str] = set()

    def take(self, raw: Any, prefix: str) -> str:
        """``raw`` when it is a well-formed id not used yet, else a new ``<prefix><n>``."""
        given = str(raw or "").strip().lower()
        if _ITEM_ID_RE.match(given) and given not in self.used:
            self.used.add(given)
            return given
        number = 1
        while f"{prefix}{number}" in self.used or f"{prefix}{number}" in self.reserved:
            number += 1
        found = f"{prefix}{number}"
        self.used.add(found)
        return found


def given_ids(spec: dict[str, Any]) -> set[str]:
    """Every well-formed id the raw spec already names (scenes, tracks, items)."""
    found: set[str] = set()

    def add(value: Any) -> None:
        text = str(value or "").strip().lower()
        if _ITEM_ID_RE.match(text):
            found.add(text)

    for scene in shell.as_list(spec.get("scenes"), 1000):
        if isinstance(scene, dict):
            add(scene.get("id"))
    for track in shell.as_list(spec.get("tracks"), 100):
        if isinstance(track, dict):
            add(track.get("id"))
            for item in shell.as_list(track.get("items"), 5000):
                if isinstance(item, dict):
                    add(item.get("id"))
    return found


# --- media -----------------------------------------------------------------------


def normalize_media(raw: Any) -> dict[str, dict[str, Any]]:
    """The clip's library: ``{id: {kind, name, file, seconds, width, height, audio}}``.

    An entry whose id or file is not one the media store writes is dropped:
    the page may only ever load the node's own files.
    """
    if not isinstance(raw, dict):
        return {}
    kept: dict[str, dict[str, Any]] = {}
    for key, entry in list(raw.items())[:MAX_MEDIA]:
        if not media_id_ok(key) or not isinstance(entry, dict):
            continue
        file = str(entry.get("file") or "")
        if not _MEDIA_FILE_RE.match(file) or not file.startswith(key + "."):
            continue
        kind = shell.pick(entry.get("kind"), MEDIA_KINDS, "")
        if not kind:
            continue
        item: dict[str, Any] = {
            "kind": kind,
            "name": shell.clean(entry.get("name"), 120) or file,
            "file": file,
            "seconds": _num(entry.get("seconds"), 0, 86_400, 0),
            "width": int(shell.bounded(entry.get("width"), 0, 16_384, 0)),
            "height": int(shell.bounded(entry.get("height"), 0, 16_384, 0)),
            "audio": _flag(entry.get("audio")),
        }
        if kind == "image":
            item["seconds"] = 0
            item["audio"] = False
        if kind == "audio":
            item["width"] = item["height"] = 0
            item["audio"] = True
        kept[key] = item
    return kept


def _known(media: dict[str, dict[str, Any]], value: Any, kinds: tuple[str, ...], where: str) -> str:
    key = str(value or "").strip().lower()
    entry = media.get(key)
    if entry is None:
        raise NodeError(
            f"{where} names media {key!r}, which is not in the clip's library: import the "
            "file first (clip tool, action 'import') and use the id it returns."
        )
    if entry["kind"] not in kinds:
        raise NodeError(f"{where} needs {' or '.join(kinds)} media; {key!r} is {entry['kind']}.")
    return key


# --- the look of a picture or a video -------------------------------------------


def _crop(raw: Any) -> dict[str, float | int] | None:
    if not isinstance(raw, dict):
        return None
    sides = {side: _num(raw.get(side), 0, 0.45, 0, 4) for side in ("l", "t", "r", "b")}
    return sides if any(sides.values()) else None


def _color(raw: Any) -> dict[str, int] | None:
    if not isinstance(raw, dict):
        return None
    values = {
        name: int(shell.bounded(raw.get(name), -100, 100, 0))
        for name in ("brightness", "contrast", "saturation", "warmth")
    }
    return values if any(values.values()) else None


#: What a key may set, with its bounds.
_KEY_FIELDS: Final[dict[str, tuple[float, float]]] = {
    "zoom": (0.1, 5.0),
    "x": (-100.0, 100.0),
    "y": (-100.0, 100.0),
    "rotate": (-360.0, 360.0),
    "opacity": (0.0, 1.0),
}


def _keys(raw: Any, seconds: float) -> list[dict[str, Any]]:
    """Keyframes: ``{t, zoom?, x?, y?, rotate?, opacity?}``, ``t`` inside the item, in order."""
    keys: list[dict[str, Any]] = []
    for entry in shell.as_list(raw, 64):
        if not isinstance(entry, dict):
            continue
        key: dict[str, Any] = {"t": _num(entry.get("t"), 0, seconds, 0)}
        for name, (low, high) in _KEY_FIELDS.items():
            value = shell.number(entry.get(name))
            if value is not None:
                key[name] = _round(max(low, min(high, value)), 4)
        if len(key) > 1:
            keys.append(key)
    keys.sort(key=lambda each: float(each["t"]))
    # One key per moment: a later key at the same time wins.
    unique: dict[float, dict[str, Any]] = {}
    for key in keys:
        unique[float(key["t"])] = {**unique.get(float(key["t"]), {}), **key}
    return list(unique.values())[:MAX_KEYS]


def visual(raw: dict[str, Any], seconds: float, *, with_fit: bool = True) -> dict[str, Any]:
    """How a picture or video is framed and coloured; only what differs from plain."""
    out: dict[str, Any] = {}
    if with_fit:
        fit = shell.pick(raw.get("fit"), FITS, "cover")
        if fit != "cover":
            out["fit"] = fit
    for name, (low, high) in _KEY_FIELDS.items():
        default = 1.0 if name in ("zoom", "opacity") else 0.0
        value = _num(raw.get(name), low, high, default, 4)
        if value != default:
            out[name] = value
    crop = _crop(raw.get("crop"))
    if crop:
        out["crop"] = crop
    look = shell.pick(raw.get("filter"), FILTERS, "none")
    if look != "none":
        out["filter"] = look
    color = _color(raw.get("color"))
    if color:
        out["color"] = color
    keys = _keys(raw.get("keys"), seconds)
    if keys:
        out["keys"] = keys
    return out


def timing(raw: dict[str, Any], entry: dict[str, Any] | None) -> dict[str, Any]:
    """Where a piece of a video or sound starts in its source, how fast and loud it runs."""
    out: dict[str, Any] = {}
    length = float(entry["seconds"]) if entry and entry.get("seconds") else 0.0
    start = _num(raw.get("in"), 0, max(0.0, length - 0.05) if length else 86_400, 0)
    if start:
        out["in"] = start
    speed = _num(raw.get("speed"), MIN_SPEED, MAX_SPEED, 1.0, 3)
    if speed != 1:
        out["speed"] = speed
    volume = _num(raw.get("volume"), 0, 1, 1.0, 3)
    if volume != 1:
        out["volume"] = volume
    if _flag(raw.get("muted")):
        out["muted"] = True
    for name in ("fade_in", "fade_out"):
        fade = _num(raw.get(name), 0, MAX_FADE, 0, 2)
        if fade:
            out[name] = fade
    return out


def natural_seconds(raw: dict[str, Any], entry: dict[str, Any] | None, default: float) -> float:
    """How long a piece runs on the timeline when nobody said: the rest of its source."""
    if not entry or not entry.get("seconds"):
        return default
    speed = shell.bounded(raw.get("speed"), MIN_SPEED, MAX_SPEED, 1.0)
    rest = float(entry["seconds"]) - shell.bounded(raw.get("in"), 0, 86_400, 0.0)
    return max(MIN_ITEM_SECONDS, rest / speed)


# --- tracks ----------------------------------------------------------------------


def _text_item(raw: dict[str, Any], out: dict[str, Any], where: str) -> None:
    text = shell.clean_block(raw.get("text"), 300)
    if not text:
        raise NodeError(f"{where} is a text item without 'text'.")
    out["text"] = text
    style = shell.pick(raw.get("style"), TEXT_STYLES, "title")
    out["style"] = style
    size = shell.number(raw.get("size"))
    if size is not None:
        out["size"] = int(max(12, min(320, size)))
    out["x"] = _num(raw.get("x"), 0, 100, 50, 2)
    out["y"] = _num(raw.get("y"), 0, 100, 50, 2)
    align = shell.pick(raw.get("align"), ALIGNS, "center")
    if align != "center":
        out["align"] = align
    color = shell.color(raw.get("color"))
    if color:
        out["color"] = str(raw.get("color")).strip()
    back = shell.pick(raw.get("bg"), TEXT_BACKS, "shadow")
    out["bg"] = back
    font = shell.pick(raw.get("font"), TEXT_FONTS, "sans")
    if font != "sans":
        out["font"] = font
    out["anim"] = shell.pick(raw.get("anim"), ENTRANCES, "rise")
    out["out"] = shell.pick(raw.get("out"), EXITS, "fade")
    keys = _keys(raw.get("keys"), float(out["seconds"]))
    if keys:
        out["keys"] = keys


def _overlay_item(
    raw: dict[str, Any], out: dict[str, Any], media: dict[str, dict[str, Any]], where: str
) -> None:
    key = _known(media, raw.get("media"), ("video", "image"), where)
    out["media"] = key
    entry = media[key]
    if entry["kind"] == "video":
        out.update(timing(raw, entry))
    out["x"] = _num(raw.get("x"), -50, 150, 50, 2)
    out["y"] = _num(raw.get("y"), -50, 150, 50, 2)
    out["w"] = _num(raw.get("w"), 2, 200, 40, 2)
    radius = _num(raw.get("radius"), 0, 50, 0, 1)
    if radius:
        out["radius"] = radius
    out.update(visual(raw, float(out["seconds"]), with_fit=False))
    # Position is the item's own x/y: a visual() x/y offset would say it twice.
    out["x"] = _num(raw.get("x"), -50, 150, 50, 2)
    out["y"] = _num(raw.get("y"), -50, 150, 50, 2)
    out["anim"] = shell.pick(raw.get("anim"), ENTRANCES, "fade")
    out["out"] = shell.pick(raw.get("out"), EXITS, "fade")


def _audio_item(
    raw: dict[str, Any], out: dict[str, Any], media: dict[str, dict[str, Any]], where: str
) -> None:
    key = _known(media, raw.get("media"), ("audio", "video"), where)
    out["media"] = key
    out.update(timing(raw, media[key]))
    if _flag(raw.get("duck")):
        out["duck"] = True


def normalize_tracks(raw: Any, media: dict[str, dict[str, Any]], ids: Ids) -> list[dict[str, Any]]:
    """The layers above the main track, each of one kind, items in time order."""
    tracks: list[dict[str, Any]] = []
    for index, track in enumerate(shell.as_list(raw, MAX_TRACKS)):
        if not isinstance(track, dict):
            raise NodeError(f"Track {index + 1} must be an object with 'kind' and 'items'.")
        kind = shell.pick(track.get("kind"), TRACK_KINDS, "")
        if not kind:
            raise NodeError(f"Track {index + 1} needs a 'kind': " + ", ".join(TRACK_KINDS) + ".")
        kept: dict[str, Any] = {"id": ids.take(track.get("id"), "tr"), "kind": kind}
        name = shell.clean(track.get("name"), 40)
        if name:
            kept["name"] = name
        for flag in ("muted", "hidden", "locked"):
            if _flag(track.get(flag)):
                kept[flag] = True
        items: list[dict[str, Any]] = []
        for number, item in enumerate(shell.as_list(track.get("items"), MAX_ITEMS_PER_TRACK)):
            where = f"Track {index + 1}, item {number + 1}"
            if not isinstance(item, dict):
                raise NodeError(f"{where} must be an object.")
            entry = media.get(str(item.get("media") or "").strip().lower())
            default = 3.0 if kind == "text" else 5.0
            if kind != "text" and entry and entry["kind"] != "image":
                default = natural_seconds(item, entry, default)
            out: dict[str, Any] = {
                "id": ids.take(item.get("id"), kind[0]),
                "start": _num(item.get("start"), 0, MAX_START, 0),
                "seconds": _num(
                    item.get("seconds"),
                    MIN_ITEM_SECONDS,
                    MAX_ITEM_SECONDS,
                    min(default, MAX_ITEM_SECONDS),
                ),
            }
            if kind == "text":
                _text_item(item, out, where)
            elif kind == "overlay":
                _overlay_item(item, out, media, where)
            else:
                _audio_item(item, out, media, where)
            items.append(out)
        items.sort(key=lambda each: float(each["start"]))
        kept["items"] = items
        tracks.append(kept)
    return tracks


# --- captions --------------------------------------------------------------------


def normalize_captions(raw: Any) -> dict[str, Any] | None:
    """The subtitles: ``{style, position, size, items: [{start, end, text, words?}]}``."""
    if isinstance(raw, list):
        raw = {"items": raw}
    if not isinstance(raw, dict):
        return None
    items: list[dict[str, Any]] = []
    for entry in shell.as_list(raw.get("items"), MAX_CAPTIONS):
        if not isinstance(entry, dict):
            continue
        text = shell.clean(entry.get("text"), 200)
        if not text:
            continue
        start = _num(entry.get("start"), 0, MAX_START, 0)
        end = _num(entry.get("end"), float(start) + 0.1, MAX_START + 60, float(start) + 2)
        line: dict[str, Any] = {"start": start, "end": end, "text": text}
        words = entry.get("words")
        count = len(text.split())
        if isinstance(words, list) and len(words) == count:
            times: list[list[float | int]] = []
            for pair in words:
                if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                    times = []
                    break
                first = _num(pair[0], float(start), float(end), float(start))
                last = _num(pair[1], float(first), float(end), float(end))
                times.append([first, last])
            if times:
                line["words"] = times
        items.append(line)
    items.sort(key=lambda each: float(each["start"]))
    return {
        "style": shell.pick(raw.get("style"), CAPTION_STYLES, "karaoke"),
        "position": shell.pick(raw.get("position"), CAPTION_PLACES, "bottom"),
        "size": shell.pick(raw.get("size"), CAPTION_SIZES, "m"),
        "items": items,
    }


# --- time ------------------------------------------------------------------------


def duration(spec: dict[str, Any]) -> float:
    """The clip's whole length: the main track, or a later item or caption."""
    main = sum(float(scene["seconds"]) for scene in spec.get("scenes") or [])
    ends = [main]
    for track in spec.get("tracks") or []:
        for item in track.get("items") or []:
            ends.append(float(item["start"]) + float(item["seconds"]))
    captions = spec.get("captions") or {}
    for line in captions.get("items") or []:
        ends.append(float(line["end"]))
    return round(max(ends), 3)


# --- drawing ---------------------------------------------------------------------


def media_url(node_id: str, entry: dict[str, Any]) -> str:
    """Where the page loads a library file from (the app's ``/clip-media`` route)."""
    return f"/clip-media/{node_id}/{entry['file']}"


def _source_size(entry: dict[str, Any] | None) -> tuple[float, float]:
    if entry and entry.get("width") and entry.get("height"):
        return float(entry["width"]), float(entry["height"])
    return 1920.0, 1080.0


def _filter_css(item: dict[str, Any]) -> str:
    parts = [FILTER_CSS.get(str(item.get("filter") or "none"), "")]
    color = item.get("color") or {}
    if color:
        bright = 1 + float(color.get("brightness", 0)) / 200
        contrast = 1 + float(color.get("contrast", 0)) / 150
        saturate = 1 + float(color.get("saturation", 0)) / 100
        warmth = float(color.get("warmth", 0))
        parts.append(f"brightness({bright:.3f}) contrast({contrast:.3f}) saturate({saturate:.3f})")
        if warmth > 0:
            parts.append(f"sepia({warmth / 250:.3f})")
        elif warmth < 0:
            parts.append(f"hue-rotate({-warmth * 0.25:.1f}deg)")
    return " ".join(part for part in parts if part)


def _base(item: dict[str, Any]) -> dict[str, float]:
    return {
        "z": float(item.get("zoom", 1)),
        "x": float(item.get("x", 0)),
        "y": float(item.get("y", 0)),
        "r": float(item.get("rotate", 0)),
        "o": float(item.get("opacity", 1)),
    }


def _keys_attr(item: dict[str, Any]) -> str:
    keys = item.get("keys")
    if not keys:
        return ""
    short = [
        {
            "t": key["t"],
            **{
                code: key[name]
                for name, code in (
                    ("zoom", "z"),
                    ("x", "x"),
                    ("y", "y"),
                    ("rotate", "r"),
                    ("opacity", "o"),
                )
                if name in key
            },
        }
        for key in keys
    ]
    return f' data-keys="{attr(json.dumps(short, separators=(",", ":")))}"'


def _media_attrs(item: dict[str, Any], start: float, seconds: float) -> str:
    """The timing of a playing element, read by the page script."""
    volume = 0.0 if item.get("muted") else float(item.get("volume", 1))
    return (
        f' data-ts="{start:.3f}" data-te="{start + seconds:.3f}"'
        f' data-in="{float(item.get("in", 0)):.3f}" data-sp="{float(item.get("speed", 1)):.3f}"'
        f' data-vol="{volume:.3f}" data-fi="{float(item.get("fade_in", 0)):.2f}"'
        f' data-fo="{float(item.get("fade_out", 0)):.2f}"'
        + (' data-duck="1"' if item.get("duck") else "")
    )


def _placed(
    entry: dict[str, Any] | None, box: tuple[float, float], crop: dict[str, Any] | None, fit: str
) -> str:
    """The element's size and place inside its box, so the crop fills the box."""
    width, height = box
    vw, vh = _source_size(entry)
    left_cut = float((crop or {}).get("l", 0))
    top_cut = float((crop or {}).get("t", 0))
    cw = vw * (1 - left_cut - float((crop or {}).get("r", 0)))
    ch = vh * (1 - top_cut - float((crop or {}).get("b", 0)))
    pick = min if fit == "contain" else max
    scale = pick(width / cw, height / ch)
    left = width / 2 - (vw * left_cut + cw / 2) * scale
    top = height / 2 - (vh * top_cut + ch / 2) * scale
    return f"left:{left:.2f}px;top:{top:.2f}px;width:{vw * scale:.2f}px;height:{vh * scale:.2f}px"


def _transform(base: dict[str, float], size: tuple[float, float]) -> str:
    width, height = size
    return (
        f"translate({base['x'] / 100 * width:.2f}px,{base['y'] / 100 * height:.2f}px) "
        f"scale({base['z']:.4f}) rotate({base['r']:.2f}deg)"
    )


def video_scene_html(
    scene: dict[str, Any],
    media: dict[str, dict[str, Any]],
    node_id: str,
    stage: tuple[float, float],
    start: float,
) -> str:
    """A piece of a video on the main track: the frame filled, the source at its time."""
    entry = media.get(str(scene.get("media") or ""))
    if entry is None:
        return '<div class="f-media is-missing"></div>'
    base = _base(scene)
    seconds = float(scene["seconds"])
    filters = _filter_css(scene)
    style = f"transform:{_transform(base, stage)};opacity:{base['o']:.3f}"
    if filters:
        style += f";filter:{filters}"
    placed = _placed(entry, stage, scene.get("crop"), str(scene.get("fit") or "cover"))
    src = attr(media_url(node_id, entry))
    if entry["kind"] == "image":
        element = f'<img class="f-pic" src="{src}" alt="" style="{placed}">'
    else:
        element = (
            f'<video class="f-vid" src="{src}" preload="auto" playsinline '
            f'disablepictureinpicture style="{placed}"'
            f"{_media_attrs(scene, start, seconds)}></video>"
        )
    return (
        f'<div class="f-media" data-b="{attr(json.dumps(base, separators=(",", ":")))}"'
        f'{_keys_attr(scene)} style="{style}">{element}</div>'
    )


def _layer_open(item: dict[str, Any], klass: str, style: str) -> str:
    start, seconds = float(item["start"]), float(item["seconds"])
    base = _base(item)
    # A layer's own x/y is its place; its keys move it from there.
    base["x"] = base["y"] = 0.0
    return (
        f'<div class="layer {klass}" data-id="{attr(item["id"])}" data-s="{start:.3f}" '
        f'data-e="{start + seconds:.3f}" data-ai="{attr(item.get("anim", "fade"))}" '
        f'data-ao="{attr(item.get("out", "fade"))}" '
        f'data-b="{attr(json.dumps(base, separators=(",", ":")))}"{_keys_attr(item)} '
        f'style="{style}">'
    )


def _text_layer(item: dict[str, Any], accent: str) -> str:
    style = str(item.get("style") or "title")
    size = int(item.get("size") or TEXT_SIZES.get(style, 56))
    color = shell.color(item.get("color"), "")
    inner = [f"--fs:{size}"]
    if color:
        inner.append(f"color:{color}")
    align = str(item.get("align") or "center")
    inner.append(f"text-align:{align}")
    klass = (
        f"lt lt-{style} lt-bg-{attr(item.get('bg', 'shadow'))} "
        f"lt-font-{attr(item.get('font', 'sans'))}"
    )
    text = str(item["text"])
    return (
        _layer_open(item, "l-text", f"left:{float(item['x']):.2f}%;top:{float(item['y']):.2f}%")
        + f'<div class="{klass}" style="{";".join(inner)}">'
        f'<span class="lt-t" data-full="{attr(text)}">{esc(text)}</span></div></div>'
    )


def _overlay_layer(
    item: dict[str, Any],
    media: dict[str, dict[str, Any]],
    node_id: str,
    stage: tuple[float, float],
) -> str:
    entry = media.get(str(item.get("media") or ""))
    if entry is None:
        return ""
    width = float(item.get("w", 40)) / 100 * stage[0]
    vw, vh = _source_size(entry)
    crop = item.get("crop") or {}
    cw = vw * (1 - float(crop.get("l", 0)) - float(crop.get("r", 0)))
    ch = vh * (1 - float(crop.get("t", 0)) - float(crop.get("b", 0)))
    height = width * ch / cw
    box = (
        f"left:{float(item['x']):.2f}%;top:{float(item['y']):.2f}%;"
        f"width:{width:.2f}px;height:{height:.2f}px"
    )
    radius = float(item.get("radius", 0))
    if radius:
        box += f";border-radius:{radius:.1f}px"
    filters = _filter_css(item)
    if filters:
        box += f";filter:{filters}"
    placed = _placed(entry, (width, height), crop or None, "cover")
    src = attr(media_url(node_id, entry))
    if entry["kind"] == "image":
        element = f'<img class="f-pic" src="{src}" alt="" style="{placed}">'
    else:
        element = (
            f'<video class="f-vid" src="{src}" preload="auto" playsinline '
            f'disablepictureinpicture style="{placed}"'
            f"{_media_attrs(item, float(item['start']), float(item['seconds']))}></video>"
        )
    return _layer_open(item, "l-pic", box) + element + "</div>"


def _audio_elements(
    item: dict[str, Any], media: dict[str, dict[str, Any]], node_id: str, track_muted: bool
) -> str:
    entry = media.get(str(item.get("media") or ""))
    if entry is None:
        return ""
    if track_muted:
        item = {**item, "muted": True}
    return (
        f'<audio class="f-aud" src="{attr(media_url(node_id, entry))}" preload="auto"'
        f"{_media_attrs(item, float(item['start']), float(item['seconds']))}></audio>"
    )


def layers_html(spec: dict[str, Any], node_id: str, stage: tuple[float, float], accent: str) -> str:
    """Every track above the main one, later tracks on top, then the captions."""
    media = spec.get("media") or {}
    parts: list[str] = []
    sounds: list[str] = []
    for track in spec.get("tracks") or []:
        if track.get("hidden") and track["kind"] != "audio":
            continue
        for item in track.get("items") or []:
            if track["kind"] == "text":
                parts.append(_text_layer(item, accent))
            elif track["kind"] == "overlay":
                if track.get("muted"):
                    item = {**item, "muted": True}
                parts.append(_overlay_layer(item, media, node_id, stage))
            else:
                sounds.append(
                    _audio_elements(
                        item, media, node_id, bool(track.get("muted") or track.get("hidden"))
                    )
                )
    captions = spec.get("captions") or {}
    if captions.get("items") and captions.get("style") != "none":
        lines = [
            [line["start"], line["end"], line["text"], line.get("words") or []]
            for line in captions["items"]
        ]
        parts.append(
            f'<div class="f-caps cap-{attr(captions["style"])} cap-{attr(captions["position"])} '
            f'cap-{attr(captions.get("size", "m"))}" '
            f'data-caps="{attr(json.dumps(lines, ensure_ascii=False, separators=(",", ":")))}">'
            '<p class="cap-line"></p></div>'
        )
    if not parts and not sounds:
        return ""
    return (
        '<div class="layers">'
        + "".join(parts)
        + "</div>"
        + (f'<div class="sounds" hidden>{"".join(sounds)}</div>' if sounds else "")
    )


def voice_spans(spec: dict[str, Any]) -> list[tuple[float, float]]:
    """When someone speaks on the main track: the video pieces whose sound plays.

    Music marked ``duck`` is lowered under these, in the page and the export.
    """
    spans: list[tuple[float, float]] = []
    media = spec.get("media") or {}
    at = 0.0
    for scene in spec.get("scenes") or []:
        seconds = float(scene["seconds"])
        entry = media.get(str(scene.get("media") or ""))
        if (
            scene.get("type") == "video"
            and entry is not None
            and entry.get("audio")
            and not scene.get("muted")
            and float(scene.get("volume", 1)) > 0
        ):
            spans.append((at, at + seconds))
        at += seconds
    return spans


MEDIA_CSS: Final[str] = """
.s-video{padding:0;background:#000}
.f-media{position:absolute;inset:0;overflow:hidden;transform-origin:50% 50%}
.f-media video,.f-media img,.l-pic video,.l-pic img{position:absolute;max-width:none;display:block;
  object-fit:fill}
.f-media.is-missing{background:repeating-linear-gradient(45deg,#1b1b1b 0 18px,#232323 18px 36px)}
.layers{position:absolute;inset:0;pointer-events:none;overflow:hidden;z-index:3}
.layer{position:absolute;visibility:hidden;transform:translate(-50%,-50%);transform-origin:50% 50%}
.layer.is-on{visibility:visible}
.l-pic{overflow:hidden}
.l-text{width:max-content;max-width:88%}
.lt{font-size:calc(var(--fs)*var(--k)*1px);line-height:1.12;color:#fff;white-space:pre-line;
  letter-spacing:-.01em;font-weight:700;overflow-wrap:anywhere}
.lt-title{font-weight:800;letter-spacing:-.035em;line-height:1.02}
.lt-subtitle{font-weight:650;letter-spacing:-.02em}
.lt-body{font-weight:500;line-height:1.3}
.lt-label{font-weight:700;text-transform:uppercase;letter-spacing:.08em}
.lt-caption{font-weight:600;line-height:1.25}
.lt-quote{font-family:Georgia,"Times New Roman",serif;font-style:italic;font-weight:500}
.lt-font-serif{font-family:Georgia,"Times New Roman",serif}
.lt-font-mono{font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;letter-spacing:0}
.lt-bg-shadow{text-shadow:0 2px 14px rgba(0,0,0,.55),0 1px 3px rgba(0,0,0,.5)}
.lt-bg-box{padding:.18em .42em;border-radius:.18em;background:rgba(10,10,10,.78)}
.lt-bg-pill{padding:.16em .62em;border-radius:999px;background:var(--fa);color:var(--fa-ink)}
.f-caps{position:absolute;left:9%;right:9%;display:flex;justify-content:center;pointer-events:none;
  z-index:4}
.cap-bottom{bottom:12%}.cap-middle{top:50%;transform:translateY(-50%)}.cap-top{top:12%}
.stage[data-format="tall"] .cap-bottom{bottom:24%}
.stage[data-format="tall"] .cap-top{top:15%}
.stage[data-format="portrait"] .cap-bottom{bottom:17%}
.cap-line{margin:0;text-align:center;color:#fff;font-weight:800;line-height:1.18;
  font-size:calc(var(--cs,58px)*var(--k));text-wrap:balance;
  text-shadow:0 2px 12px rgba(0,0,0,.6),0 1px 2px rgba(0,0,0,.7)}
.cap-s .cap-line{--cs:44px}.cap-l .cap-line{--cs:76px}
.cap-line:empty{display:none}
.cap-w{display:inline-block;transition:none}
.cap-bold .cap-line{text-transform:uppercase;font-weight:900;letter-spacing:.01em;
  -webkit-text-stroke:calc(5px*var(--k)) #000;paint-order:stroke fill}
.cap-karaoke .cap-line{font-weight:900;-webkit-text-stroke:calc(4px*var(--k)) #000;
  paint-order:stroke fill}
.cap-karaoke .cap-w.is-now{color:var(--cap-hi,#FFD84D);transform:scale(1.08)}
.cap-karaoke .cap-w.is-next{opacity:.92}
.cap-clean .cap-line{font-weight:700}
.cap-boxed .cap-line{text-shadow:none;font-weight:700;padding:.2em .5em;border-radius:.25em;
  background:rgba(10,10,10,.8);box-decoration-break:clone;-webkit-box-decoration-break:clone}
.film.is-bare .film-bar,.film.is-bare .f-replay{display:none!important}
.film.is-bare .film-view{padding:10px}
.film.is-bare .film-fit{cursor:default}
.film.is-bare .layer{pointer-events:auto;cursor:move}
.film.is-bare .layers{pointer-events:none}
/* The safe zone of the platforms' own buttons and captions (editor only). */
.stage.show-guides::after{content:"";position:absolute;z-index:9;pointer-events:none;
  inset:5% 5% 5% 5%;border:2px dashed rgba(255,255,255,.55);border-radius:6px;
  box-shadow:0 0 0 9999px rgba(0,0,0,.18)}
.stage.show-guides[data-format="tall"]::after{inset:7% 12% 20% 6%}
.stage.show-guides[data-format="portrait"]::after{inset:6% 8% 14% 6%}
.film.is-export .film-view{padding:0}
.film.is-export .film-fit{border-radius:0;box-shadow:none;cursor:default}
.film.is-export .film-bar,.film.is-export .f-replay{display:none!important}
"""

# The page script of the video side. It runs before the film's own script and
# hands it one object: ``draw(t, playing)`` puts every layer, caption and
# playing element where time ``t`` says; ``ready(t)`` resolves once every
# visible video stands on its frame (the export waits for it).
MEDIA_JS: Final[str] = r"""
var DodaiosClip=function(stage,d){
"use strict";
var each=function(l,f){Array.prototype.forEach.call(l,f);};
function clamp(x){return x<0?0:x>1?1:x;}
function ease(x){x=clamp(x);var q=1-x;return 1-q*q*q;}
function back(x){x=clamp(x);var c=1.70158;return 1+(c+1)*Math.pow(x-1,3)+c*Math.pow(x-1,2);}
function smooth(x){x=clamp(x);return x*x*(3-2*x);}
function json(el,name){try{return JSON.parse(el.getAttribute(name)||"null");}catch(e){return null;}}
var W=+stage.getAttribute("data-w"),H=+stage.getAttribute("data-h");
var duck=json(stage,"data-voice")||[];
function keyed(keys,base,lt){
  var v={z:base.z,x:base.x,y:base.y,r:base.r,o:base.o};
  if(!keys||!keys.length)return v;
  ["z","x","y","r","o"].forEach(function(p){
    var list=keys.filter(function(k){return typeof k[p]==="number";});
    if(!list.length)return;
    if(lt<=list[0].t){v[p]=list[0][p];return;}
    var last=list[list.length-1];if(lt>=last.t){v[p]=last[p];return;}
    for(var i=1;i<list.length;i++){
      if(lt<=list[i].t){var a=list[i-1],b=list[i],f=(lt-a.t)/Math.max(1e-6,b.t-a.t);
        v[p]=a[p]+(b[p]-a[p])*smooth(f);return;}}});
  return v;}
// The main track's pictures: the frame of a video scene moves with its keys.
var frames=[];
each(stage.querySelectorAll(".scene"),function(sc){
  var m=sc.querySelector(".f-media[data-keys]");if(!m)return;
  var v=m.querySelector("video");
  frames.push({el:m,b:json(m,"data-b")||{z:1,x:0,y:0,r:0,o:1},k:json(m,"data-keys"),
    ts:v?+v.getAttribute("data-ts"):NaN,sc:sc});});
var layers=[];
each(stage.querySelectorAll(".layer"),function(el){
  var t=el.querySelector(".lt-t");
  layers.push({el:el,s:+el.getAttribute("data-s"),e:+el.getAttribute("data-e"),
    ai:el.getAttribute("data-ai")||"fade",ao:el.getAttribute("data-ao")||"fade",
    b:json(el,"data-b")||{z:1,x:0,y:0,r:0,o:1},k:json(el,"data-keys"),on:null,
    txt:t,full:t?t.getAttribute("data-full")||"":"",shown:-1});});
function anim(kind,p){
  // What an entrance (or, mirrored, an exit) does at progress p.
  var o=1,dx=0,dy=0,s=1;
  if(kind==="none"||kind==="type")return {o:1,dx:0,dy:0,s:1};
  if(kind==="fade"){o=ease(p);}
  else if(kind==="rise"){o=clamp(p*1.6);dy=(1-ease(p))*40;}
  else if(kind==="slide"){o=clamp(p*1.4);dx=(1-ease(p))*-90;}
  else if(kind==="pop"){o=clamp(p*2);s=.55+.45*back(p);}
  else if(kind==="zoom"){o=ease(p);s=1.35-.35*ease(p);}
  return {o:o,dx:dx,dy:dy,s:s};}
function drawLayers(t){
  layers.forEach(function(L){
    var on=t>=L.s&&t<L.e;
    if(on!==L.on){L.on=on;L.el.classList.toggle("is-on",on);}
    if(!on)return;
    var lt=t-L.s,len=L.e-L.s,rest=L.e-t;
    var ind=Math.min(.45,len/3),outd=Math.min(.35,len/3);
    var a=anim(L.ai,ind?lt/ind:1),b=anim(L.ao,outd?rest/outd:1);
    var v=keyed(L.k,L.b,lt),k=+getComputedStyle(stage).getPropertyValue("--k")||1;
    L.el.style.transform="translate(-50%,-50%) translate("+((v.x/100)*W+(a.dx+b.dx)*k).toFixed(2)+
      "px,"+((v.y/100)*H+(a.dy+b.dy)*k).toFixed(2)+"px) scale("+(v.z*a.s*b.s).toFixed(4)+
      ") rotate("+v.r.toFixed(2)+"deg)";
    L.el.style.opacity=(v.o*a.o*b.o).toFixed(4);
    if(L.txt&&L.ai==="type"){
      var n=Math.round(L.full.length*clamp(lt/Math.max(.3,Math.min(1.6,len*.5))));
      if(n!==L.shown){L.shown=n;L.txt.textContent=L.full.slice(0,n);}}});}
function drawFrames(t){
  frames.forEach(function(F){
    if(!F.sc.classList.contains("is-on"))return;
    var v=keyed(F.k,F.b,isNaN(F.ts)?0:t-F.ts);
    F.el.style.transform="translate("+(v.x/100*W).toFixed(2)+"px,"+(v.y/100*H).toFixed(2)+
      "px) scale("+v.z.toFixed(4)+") rotate("+v.r.toFixed(2)+"deg)";
    F.el.style.opacity=v.o.toFixed(4);});}
// The captions: the line that is on, its words lit as they are spoken.
var caps=null;
(function(){
  var box=stage.querySelector(".f-caps");if(!box)return;
  var lines=json(box,"data-caps")||[];
  caps={box:box,p:box.querySelector(".cap-line"),lines:lines,cur:-2,ws:[],
    karaoke:box.classList.contains("cap-karaoke")};})();
function lineAt(t){
  var L=caps.lines,lo=0,hi=L.length-1,found=-1;
  while(lo<=hi){var m=(lo+hi)>>1;if(L[m][0]<=t){found=m;lo=m+1;}else hi=m-1;}
  return found>=0&&t<L[found][1]?found:-1;}
function drawCaps(t){
  if(!caps)return;
  var i=lineAt(t);
  if(i!==caps.cur){
    caps.cur=i;caps.p.textContent="";caps.ws=[];
    if(i>=0){
      var line=caps.lines[i],words=String(line[2]).split(/\s+/).filter(Boolean),times=line[3];
      var s=line[0],e=line[1],n=words.length;
      words.forEach(function(w,j){
        var span=d.createElement("span");span.className="cap-w";span.textContent=w;
        if(j)caps.p.appendChild(d.createTextNode(" "));caps.p.appendChild(span);
        var tj=times&&times[j];
        var ws=tj?tj[0]:s+(e-s)*j/n,we=tj?tj[1]:s+(e-s)*(j+1)/n;
        caps.ws.push({el:span,s:ws,e:we});});}}
  if(i<0||!caps.karaoke)return;
  caps.ws.forEach(function(w,j){
    var now=t>=w.s&&(t<w.e||(j+1<caps.ws.length?t<caps.ws[j+1].s:true));
    w.el.classList.toggle("is-now",now);});}
// Every element that plays: main-track and overlay videos, sounds.
var players=[];
each(stage.querySelectorAll("video[data-ts],audio[data-ts]"),function(el){
  players.push({el:el,ts:+el.getAttribute("data-ts"),te:+el.getAttribute("data-te"),
    inn:+el.getAttribute("data-in")||0,sp:+el.getAttribute("data-sp")||1,
    vol:+el.getAttribute("data-vol"),fi:+el.getAttribute("data-fi")||0,
    fo:+el.getAttribute("data-fo")||0,duck:el.hasAttribute("data-duck"),
    video:el.tagName==="VIDEO",want:-1});
  el.muted=false;el.defaultMuted=false;
  try{el.preservesPitch=true;}catch(e){}});
function ducked(t){
  var c=0;
  duck.forEach(function(sp){
    var x=t<sp[0]?1-(sp[0]-t)/.25:t>sp[1]?1-(t-sp[1])/.25:1;c=Math.max(c,clamp(x));});
  return 1-.7*c;}
function level(P,t){
  var v=P.vol;if(!(v>0))return 0;
  if(P.fi>0)v*=clamp((t-P.ts)/P.fi);
  if(P.fo>0)v*=clamp((P.te-t)/P.fo);
  if(P.duck)v*=ducked(t);
  return clamp(v);}
var exporting=false;
function source(P,t){
  var x=P.inn+(Math.min(t,P.te)-P.ts)*P.sp,dur=P.el.duration;
  if(isFinite(dur)&&dur>0)x=Math.min(x,dur-.04);
  return Math.max(0,x);}
function drawPlayers(t,playing){
  players.forEach(function(P){
    var el=P.el,active=t>=P.ts&&t<P.te,near=t>=P.ts-1.5&&t<P.te+.5;
    if(!near){if(!el.paused)el.pause();return;}
    var want=source(P,t);
    if(el.playbackRate!==P.sp){try{el.playbackRate=P.sp;}catch(e){}}
    el.volume=exporting?0:active?level(P,t):0;
    if(playing&&active&&!exporting){
      if(Math.abs(el.currentTime-want)>.3)el.currentTime=want;
      if(el.paused){var pr=el.play();if(pr&&pr.catch)pr.catch(function(){});}
    }else{
      if(!el.paused)el.pause();
      if(Math.abs(el.currentTime-want)>.015&&P.want!==want){P.want=want;el.currentTime=want;}}});}
function draw(t,playing){drawFrames(t);drawLayers(t);drawCaps(t);drawPlayers(t,playing);}
// Resolves once every video that shows at t stands on its frame.
function ready(t){
  exporting=true;
  var waits=[];
  players.forEach(function(P){
    if(!P.video)return;
    var el=P.el,on=t>=P.ts-.02&&t<P.te+.4;if(!on)return;
    waits.push(new Promise(function(done){
      var finish=function(){
        if(el.requestVideoFrameCallback){el.requestVideoFrameCallback(function(){done();});
          setTimeout(done,20);}else done();};
      var want=source(P,t);
      if(el.readyState>=2&&!el.seeking&&Math.abs(el.currentTime-want)<.02){done();return;}
      var timer=setTimeout(done,4000);
      el.addEventListener("seeked",function h(){el.removeEventListener("seeked",h);
        clearTimeout(timer);finish();});
      if(el.readyState<1){el.addEventListener("loadedmetadata",function h(){
        el.removeEventListener("loadedmetadata",h);el.currentTime=source(P,t);});}
      else el.currentTime=want;}));});
  each(stage.querySelectorAll("img"),function(img){
    if(!img.complete)waits.push(new Promise(function(done){
      img.addEventListener("load",done);img.addEventListener("error",done);setTimeout(done,4000);}));});
  return Promise.all(waits);}
return {draw:draw,ready:ready};};
"""


__all__ = [
    "CAPTION_PLACES",
    "CAPTION_SIZES",
    "CAPTION_STYLES",
    "ENTRANCES",
    "EXITS",
    "FILTERS",
    "FITS",
    "MEDIA_CSS",
    "MEDIA_JS",
    "MEDIA_KINDS",
    "TEXT_BACKS",
    "TEXT_STYLES",
    "TRACK_KINDS",
    "Ids",
    "duration",
    "given_ids",
    "layers_html",
    "media_id_ok",
    "media_url",
    "natural_seconds",
    "normalize_captions",
    "normalize_media",
    "normalize_tracks",
    "timing",
    "video_scene_html",
    "visual",
    "voice_spans",
]
