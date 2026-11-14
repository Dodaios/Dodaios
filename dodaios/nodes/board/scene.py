"""A whiteboard's scene: what the spec of a whiteboard node holds, and how two
copies of it are joined.

The board is drawn and edited in the app by the embedded open-source editor
``@excalidraw/excalidraw`` (0.18). Its scene is a list of element objects plus
a little view state, and the node keeps exactly that scene as its spec, so the
editor opens a board without any translation and nothing the person drew is
lost on the way to disk and back.

Why the scene is still checked field by field: the spec comes from three
writers (the person's editor, the assistant's ``whiteboard`` tool, scripts on
the HTTP API) and reaches a page and a shared file. So :func:`normalize_scene`
keeps only the element types and the fields this module knows, bounds every
number and every string, accepts colours only in forms that cannot carry
anything else into a style or an SVG attribute, and keeps links to web and
mail addresses only. Unknown fields are dropped instead of refused, because
the editor adds fields from version to version; unknown element TYPES are
refused, because a model that invents one should hear about it. The editor's
free-form ``customData`` is kept when it is a small plain JSON object; the
page never draws it. The element
types that load the web (``embeddable``, ``iframe``) and the generated-page
frame are dropped: the board and its page stay offline.

Why a merge and not "last writer wins": the person draws in the editor while
the assistant edits the same board through the tool. The editor's own rule
decides per element: every change raises an element's ``version`` and draws a
new random ``versionNonce``; the higher version wins, and on a tie the lower
nonce. :func:`merge_scene` applies that rule, keeps what only the stored scene
has (the assistant added it meanwhile), and says whether the editor has to take
the merged scene back. A deletion is a tombstone (``isDeleted`` with a raised
version), so a deleted element cannot come back from an older copy.

Pure functions, no I/O.
"""

from __future__ import annotations

import json
import math
import re
import zlib
from typing import Any, Final

from dodaios.nodes.types import NodeError

# --- limits ----------------------------------------------------------------------

#: Live (not deleted) elements one board may hold.
MAX_ELEMENTS: Final[int] = 5_000
#: Tombstones kept in a scene at most; the oldest beyond go first.
MAX_TOMBSTONES: Final[int] = 5_000
#: Tombstones a merge keeps without pruning, and the age before one may go.
KEEP_TOMBSTONES: Final[int] = 2_000
TOMBSTONE_AGE_MS: Final[int] = 60 * 60 * 1000
#: The size of a whiteboard's spec as JSON. Larger than other types': a
#: hand-drawn stroke is hundreds of points.
MAX_SCENE_BYTES: Final[int] = 8_000_000
MAX_FILES: Final[int] = 1_000

MAX_TEXT_CHARS: Final[int] = 20_000
MAX_NAME_CHARS: Final[int] = 200
MAX_LINK_CHARS: Final[int] = 2_000
MAX_ID_CHARS: Final[int] = 64
MAX_GROUPS: Final[int] = 32
MAX_BOUND: Final[int] = 1_000
MAX_LINEAR_POINTS: Final[int] = 5_000
MAX_FREEDRAW_POINTS: Final[int] = 50_000
MAX_SEGMENTS: Final[int] = 500
#: The editor's free-form ``customData`` of one element, as JSON. It is never
#: drawn on the page; it is kept so the editor gets back what it stored.
MAX_CUSTOM_DATA_BYTES: Final[int] = 4_096

#: Board units are CSS pixels at 100 % zoom. The canvas is infinite to the
#: person, but a coordinate beyond ten million is a bug, not a drawing.
COORD_LIMIT: Final[float] = 10_000_000.0
SIZE_LIMIT: Final[float] = 10_000_000.0
_INT31: Final[int] = 2**31 - 1
_MS_LIMIT: Final[int] = 2**53

# --- the element grammar -------------------------------------------------------------

#: The element types a board keeps.
ELEMENT_TYPES: Final[tuple[str, ...]] = (
    "rectangle",
    "ellipse",
    "diamond",
    "text",
    "arrow",
    "line",
    "freedraw",
    "image",
    "frame",
)
#: Types the editor knows that are dropped without complaint: the editor's own
#: selection box, and the ones that load web pages (the board stays offline).
DROPPED_TYPES: Final[frozenset[str]] = frozenset(
    {"selection", "embeddable", "iframe", "magicframe"}
)
SHAPE_TYPES: Final[frozenset[str]] = frozenset({"rectangle", "ellipse", "diamond"})
LINEAR_TYPES: Final[frozenset[str]] = frozenset({"arrow", "line"})

FILL_STYLES: Final[tuple[str, ...]] = ("solid", "hachure", "cross-hatch", "zigzag")
STROKE_STYLES: Final[tuple[str, ...]] = ("solid", "dashed", "dotted")
TEXT_ALIGNS: Final[tuple[str, ...]] = ("left", "center", "right")
VERTICAL_ALIGNS: Final[tuple[str, ...]] = ("top", "middle", "bottom")
ARROWHEADS: Final[tuple[str, ...]] = (
    "arrow",
    "bar",
    "dot",
    "circle",
    "circle_outline",
    "triangle",
    "triangle_outline",
    "diamond",
    "diamond_outline",
    "crowfoot_one",
    "crowfoot_many",
    "crowfoot_one_or_many",
)
IMAGE_STATUSES: Final[tuple[str, ...]] = ("pending", "saved", "error")
#: Roundness types: 1 legacy, 2 proportional radius, 3 adaptive radius.
ROUNDNESS_TYPES: Final[tuple[int, ...]] = (1, 2, 3)

#: The editor's font families by id (``FONT_FAMILY`` in the package), and the
#: unitless line height of each (its font metrics). 5 is the default.
FONT_FAMILIES: Final[dict[int, str]] = {
    1: "Virgil",
    2: "Helvetica",
    3: "Cascadia",
    5: "Excalifont",
    6: "Nunito",
    7: "Lilita One",
    8: "Comic Shanns",
    9: "Liberation Sans",
}
LINE_HEIGHTS: Final[dict[int, float]] = {
    1: 1.25,
    2: 1.15,
    3: 1.2,
    5: 1.25,
    6: 1.35,
    7: 1.15,
    8: 1.25,
    9: 1.15,
}
DEFAULT_FONT_FAMILY: Final[int] = 5
DEFAULT_FONT_SIZE: Final[float] = 20.0

DEFAULT_STROKE: Final[str] = "#1e1e1e"
DEFAULT_BACKGROUND: Final[str] = "transparent"
DEFAULT_VIEW_BACKGROUND: Final[str] = "#ffffff"

#: The colour words a scene may use besides hex. Kept small on purpose: a
#: colour reaches an SVG attribute, and a short fixed list cannot carry
#: anything else.
NAMED_COLORS: Final[frozenset[str]] = frozenset(
    {
        "transparent",
        "black",
        "white",
        "gray",
        "grey",
        "red",
        "pink",
        "purple",
        "violet",
        "indigo",
        "blue",
        "cyan",
        "teal",
        "green",
        "lime",
        "yellow",
        "orange",
        "brown",
    }
)

#: The file types an image element may show. No SVG: an SVG can carry script.
IMAGE_MIME_TYPES: Final[tuple[str, ...]] = ("image/png", "image/jpeg", "image/gif", "image/webp")

_ID_RE: Final = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_FILE_ID_RE: Final = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_INDEX_RE: Final = re.compile(r"^[0-9A-Za-z]{1,80}$")
_HEX_RE: Final = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_CONTROL_RE: Final = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
#: A link with a space or a control character in it is no address.
_LINK_BREAK_RE: Final = re.compile(r"[\x00-\x20\x7f]")
_LINK_SCHEMES: Final[tuple[str, ...]] = ("https://", "http://", "mailto:")

_WHAT_TO_SEND: Final[str] = (
    'A whiteboard\'s spec is a scene: {"format": "scene", "elements": [...], '
    '"appState": {"viewBackgroundColor": "#ffffff"}, "files": {}}. Edit a board with the '
    "whiteboard tool's actions instead of writing elements by hand."
)


# --- small readers ---------------------------------------------------------------------


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _tidy(value: float, digits: int = 2) -> int | float:
    """A number as the scene keeps it: a few decimals, an int when it is whole."""
    rounded = round(value, digits)
    if rounded == 0:
        return 0
    return int(rounded) if rounded == int(rounded) else rounded


def _num(value: Any, low: float, high: float, default: float, digits: int = 2) -> int | float:
    number = _number(value)
    if number is None:
        number = default
    return _tidy(max(low, min(high, number)), digits)


def _int(value: Any, low: int, high: int, default: int) -> int:
    number = _number(value)
    if number is None:
        return default
    return int(max(low, min(high, round(number))))


def _bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _pick(value: Any, allowed: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _text(value: Any, limit: int) -> str:
    """Text that keeps its line breaks, without control characters, clipped."""
    if not isinstance(value, str):
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROL_RE.sub("", text)[:limit]


def element_id(value: Any) -> str | None:
    """``value`` when it is a usable element id, else ``None``."""
    if isinstance(value, str) and _ID_RE.match(value):
        return value
    return None


def file_id(value: Any) -> str | None:
    """``value`` when it is a usable file id, else ``None``."""
    if isinstance(value, str) and _FILE_ID_RE.match(value):
        return value
    return None


def color(value: Any, default: str) -> str:
    """A colour as hex (3, 4, 6 or 8 digits), ``transparent`` or a word of a short list.

    Anything else becomes ``default``, so a colour can never carry markup or a
    style into the page.
    """
    if not isinstance(value, str):
        return default
    text = value.strip()
    if _HEX_RE.match(text):
        return text.lower()
    word = text.lower()
    return word if word in NAMED_COLORS else default


def safe_link(value: Any) -> str | None:
    """A web or mail address, else ``None``."""
    if not isinstance(value, str):
        return None
    href = value.strip()
    if not href or len(href) > MAX_LINK_CHARS or _LINK_BREAK_RE.search(href):
        return None
    return href if href.lower().startswith(_LINK_SCHEMES) else None


def _custom_data(value: Any) -> dict[str, Any] | None:
    """An element's ``customData`` when it is a small plain JSON object, else ``None``."""
    if not isinstance(value, dict):
        return None
    try:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError):  # not plain JSON (a NaN, an object): not kept
        return None
    if len(text.encode("utf-8")) > MAX_CUSTOM_DATA_BYTES:
        return None
    clean = json.loads(text)
    return clean if isinstance(clean, dict) else None


def _seed(ident: str, salt: str) -> int:
    """A stable stand-in for a missing random integer: the same id, the same number.

    Normalizing twice must give the same scene, so a default cannot be random.
    """
    return zlib.crc32(f"{salt}:{ident}".encode()) & _INT31 or 1


def _point(value: Any) -> list[int | float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    x, y = _number(value[0]), _number(value[1])
    if x is None or y is None:
        return None
    return [
        _tidy(max(-COORD_LIMIT, min(COORD_LIMIT, x))),
        _tidy(max(-COORD_LIMIT, min(COORD_LIMIT, y))),
    ]


def _points(value: Any, limit: int) -> list[list[int | float]]:
    if not isinstance(value, (list, tuple)):
        return []
    points: list[list[int | float]] = []
    for raw in value[:limit]:
        point = _point(raw)
        if point is not None:
            points.append(point)
    return points


def _roundness(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    kind = value.get("type")
    if isinstance(kind, bool) or kind not in ROUNDNESS_TYPES:
        return None
    clean: dict[str, Any] = {"type": int(kind)}
    radius = _number(value.get("value"))
    if radius is not None:
        clean["value"] = _tidy(max(0.0, min(10_000.0, radius)))
    return clean


def _bound_elements(value: Any) -> list[dict[str, str]] | None:
    if value is None or not isinstance(value, (list, tuple)):
        return None
    bound: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, dict):
            continue
        ident = element_id(entry.get("id"))
        kind = entry.get("type")
        if ident is None or kind not in ("text", "arrow") or ident in seen:
            continue
        seen.add(ident)
        bound.append({"id": ident, "type": kind})
        if len(bound) == MAX_BOUND:
            break
    return bound


def _binding(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    target = element_id(value.get("elementId"))
    if target is None:
        return None
    clean: dict[str, Any] = {
        "elementId": target,
        "focus": _num(value.get("focus"), -1.0, 1.0, 0.0, 4),
        "gap": _num(value.get("gap"), 0.0, 10_000.0, 0.0),
    }
    fixed = value.get("fixedPoint")
    if isinstance(fixed, (list, tuple)) and len(fixed) == 2:
        a, b = _number(fixed[0]), _number(fixed[1])
        if a is not None and b is not None:
            clean["fixedPoint"] = [
                _tidy(max(-10.0, min(10.0, a)), 4),
                _tidy(max(-10.0, min(10.0, b)), 4),
            ]
    return clean


def _segments(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, (list, tuple)):
        return None
    segments: list[dict[str, Any]] = []
    for entry in value[:MAX_SEGMENTS]:
        if not isinstance(entry, dict):
            continue
        start, end = _point(entry.get("start")), _point(entry.get("end"))
        if start is None or end is None:
            continue
        segments.append(
            {"start": start, "end": end, "index": _int(entry.get("index"), 0, 100_000, 0)}
        )
    return segments


def _crop(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    keys = ("x", "y", "width", "height", "naturalWidth", "naturalHeight")
    numbers = [_number(value.get(key)) for key in keys]
    if any(number is None for number in numbers):
        return None
    clean = {
        key: _tidy(max(0.0, min(SIZE_LIMIT, float(number or 0.0))))
        for key, number in zip(keys, numbers, strict=True)
    }
    if not clean["width"] or not clean["height"]:
        return None
    return clean


# --- one element ---------------------------------------------------------------------------


def _element(raw: dict[str, Any], kind: str, ident: str) -> dict[str, Any]:
    """One element of a known type with every field it may hold, bounded."""
    groups: list[str] = []
    raw_groups = raw.get("groupIds")
    for value in raw_groups if isinstance(raw_groups, list) else []:
        group = element_id(value)
        if group is not None and group not in groups:
            groups.append(group)
        if len(groups) == MAX_GROUPS:
            break
    index = raw.get("index")
    element: dict[str, Any] = {
        "id": ident,
        "type": kind,
        "x": _num(raw.get("x"), -COORD_LIMIT, COORD_LIMIT, 0.0),
        "y": _num(raw.get("y"), -COORD_LIMIT, COORD_LIMIT, 0.0),
        "width": _num(raw.get("width"), 0.0, SIZE_LIMIT, 0.0),
        "height": _num(raw.get("height"), 0.0, SIZE_LIMIT, 0.0),
        "angle": _tidy(math.fmod(_number(raw.get("angle")) or 0.0, 2 * math.pi) % (2 * math.pi), 6),
        "strokeColor": color(raw.get("strokeColor"), DEFAULT_STROKE),
        "backgroundColor": color(raw.get("backgroundColor"), DEFAULT_BACKGROUND),
        "fillStyle": _pick(raw.get("fillStyle"), FILL_STYLES, "solid"),
        "strokeWidth": _num(raw.get("strokeWidth"), 0.1, 64.0, 2.0),
        "strokeStyle": _pick(raw.get("strokeStyle"), STROKE_STYLES, "solid"),
        "roughness": _int(raw.get("roughness"), 0, 2, 1),
        "opacity": _int(raw.get("opacity"), 0, 100, 100),
        "groupIds": groups,
        "frameId": element_id(raw.get("frameId")),
        "roundness": _roundness(raw.get("roundness")),
        "seed": _int(raw.get("seed"), 1, _INT31, 0) or _seed(ident, "seed"),
        "version": _int(raw.get("version"), 1, _INT31, 1),
        "versionNonce": _int(raw.get("versionNonce"), 0, _INT31, 0),
        "index": index if isinstance(index, str) and _INDEX_RE.match(index) else None,
        "isDeleted": _bool(raw.get("isDeleted"), False),
        "boundElements": _bound_elements(raw.get("boundElements")),
        "updated": _int(raw.get("updated"), 0, _MS_LIMIT, 0),
        "link": safe_link(raw.get("link")),
        "locked": _bool(raw.get("locked"), False),
    }
    custom = _custom_data(raw.get("customData"))
    if custom is not None:
        element["customData"] = custom
    if element["angle"] >= 6.283185:  # the rounding above can reach 2π itself
        element["angle"] = 0
    if kind == "text":
        family = raw.get("fontFamily")
        family = (
            int(family)
            if isinstance(family, (int, float))
            and not isinstance(family, bool)
            and int(family) == family
            and int(family) in FONT_FAMILIES
            else DEFAULT_FONT_FAMILY
        )
        text = _text(raw.get("text"), MAX_TEXT_CHARS)
        original = raw.get("originalText")
        element.update(
            {
                "text": text,
                "originalText": _text(original, MAX_TEXT_CHARS)
                if isinstance(original, str)
                else text,
                "fontSize": _num(raw.get("fontSize"), 1.0, 1_000.0, DEFAULT_FONT_SIZE),
                "fontFamily": family,
                "textAlign": _pick(raw.get("textAlign"), TEXT_ALIGNS, "left"),
                "verticalAlign": _pick(raw.get("verticalAlign"), VERTICAL_ALIGNS, "top"),
                "containerId": element_id(raw.get("containerId")),
                "autoResize": _bool(raw.get("autoResize"), True),
                "lineHeight": _num(raw.get("lineHeight"), 0.5, 4.0, LINE_HEIGHTS[family], 4),
            }
        )
    elif kind in LINEAR_TYPES:
        points = _points(raw.get("points"), MAX_LINEAR_POINTS)
        if not points:
            points = [[0, 0], [element["width"], element["height"]]]
        default_end = "arrow" if kind == "arrow" else None
        start_head = raw.get("startArrowhead")
        end_head = raw.get("endArrowhead", default_end)
        element.update(
            {
                "points": points,
                "lastCommittedPoint": _point(raw.get("lastCommittedPoint")),
                "startBinding": _binding(raw.get("startBinding")),
                "endBinding": _binding(raw.get("endBinding")),
                "startArrowhead": start_head if start_head in ARROWHEADS else None,
                "endArrowhead": end_head if end_head in ARROWHEADS else None,
            }
        )
        if kind == "arrow":
            elbowed = _bool(raw.get("elbowed"), False)
            element["elbowed"] = elbowed
            if elbowed:
                start_special = raw.get("startIsSpecial")
                end_special = raw.get("endIsSpecial")
                element.update(
                    {
                        "fixedSegments": _segments(raw.get("fixedSegments")),
                        "startIsSpecial": start_special
                        if isinstance(start_special, bool)
                        else None,
                        "endIsSpecial": end_special if isinstance(end_special, bool) else None,
                    }
                )
    elif kind == "freedraw":
        points = _points(raw.get("points"), MAX_FREEDRAW_POINTS)
        if not points:
            points = [[0, 0]]
        pressures: list[int | float] = []
        raw_pressures = raw.get("pressures")
        if isinstance(raw_pressures, list):
            for value in raw_pressures[: len(points)]:
                pressures.append(_num(value, 0.0, 1.0, 0.5, 3))
        element.update(
            {
                "points": points,
                "pressures": pressures,
                "simulatePressure": _bool(raw.get("simulatePressure"), True),
                "lastCommittedPoint": _point(raw.get("lastCommittedPoint")),
            }
        )
    elif kind == "image":
        scale = raw.get("scale")
        flip = [1, 1]
        if isinstance(scale, (list, tuple)) and len(scale) == 2:
            flip = [
                -1 if (_number(scale[0]) or 1.0) < 0 else 1,
                -1 if (_number(scale[1]) or 1.0) < 0 else 1,
            ]
        element.update(
            {
                "fileId": file_id(raw.get("fileId")),
                "status": _pick(raw.get("status"), IMAGE_STATUSES, "pending"),
                "scale": flip,
                "crop": _crop(raw.get("crop")),
            }
        )
    elif kind == "frame":
        name = " ".join(_text(raw.get("name"), MAX_NAME_CHARS).split())
        element["name"] = name or None
    return element


def _files(raw: Any) -> dict[str, dict[str, Any]]:
    """The images' metadata: id, type and times. The bytes never live in the spec."""
    if not isinstance(raw, dict):
        return {}
    files: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        ident = file_id(value.get("id", key))
        if ident is None or ident != key or value.get("mimeType") not in IMAGE_MIME_TYPES:
            continue
        entry: dict[str, Any] = {
            "id": ident,
            "mimeType": value["mimeType"],
            "created": _int(value.get("created"), 0, _MS_LIMIT, 0),
        }
        if _number(value.get("lastRetrieved")) is not None:
            entry["lastRetrieved"] = _int(value.get("lastRetrieved"), 0, _MS_LIMIT, 0)
        files[ident] = entry
        if len(files) == MAX_FILES:
            break
    return files


def _app_state(raw: Any) -> dict[str, Any]:
    state = raw if isinstance(raw, dict) else {}
    return {
        "viewBackgroundColor": color(state.get("viewBackgroundColor"), DEFAULT_VIEW_BACKGROUND),
        "gridModeEnabled": _bool(state.get("gridModeEnabled"), False),
    }


def empty_scene() -> dict[str, Any]:
    """A board with nothing on it."""
    return {"format": "scene", "elements": [], "appState": _app_state(None), "files": {}}


def is_scene(raw: Any) -> bool:
    """Whether ``raw`` is meant as a scene (rather than the older board grammar)."""
    return isinstance(raw, dict) and (raw.get("format") == "scene" or "elements" in raw)


def normalize_scene(raw: Any) -> dict[str, Any]:
    """The scene, validated and bounded. Idempotent.

    Raises :class:`NodeError` with a sentence that says what to send instead
    when ``raw`` is no scene, an element is no object, has no usable id or an
    unknown type, or the board holds more than :data:`MAX_ELEMENTS` live
    elements. A later element with an id an earlier one has is dropped.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("elements", []), list):
        raise NodeError(_WHAT_TO_SEND)
    elements: list[dict[str, Any]] = []
    seen: set[str] = set()
    live = 0
    for position, entry in enumerate(raw.get("elements") or []):
        if not isinstance(entry, dict):
            raise NodeError(f"elements[{position}] must be an object with an 'id' and a 'type'.")
        kind = entry.get("type")
        if kind in DROPPED_TYPES:
            continue
        if kind not in ELEMENT_TYPES:
            raise NodeError(
                f"elements[{position}] has the type {str(kind)[:40]!r}; a board's elements are "
                f"of the types {', '.join(ELEMENT_TYPES)}."
            )
        ident = element_id(entry.get("id"))
        if ident is None:
            raise NodeError(
                f"elements[{position}] needs an 'id' of 1 to {MAX_ID_CHARS} letters, digits, "
                "'_', '-', '.' or ':'."
            )
        if ident in seen:
            continue
        seen.add(ident)
        element = _element(entry, kind, ident)
        if not element["isDeleted"]:
            live += 1
            if live > MAX_ELEMENTS:
                raise NodeError(
                    f"A board holds at most {MAX_ELEMENTS} elements; make a second board for "
                    "the rest, or group many small strokes into fewer shapes."
                )
        elements.append(element)
    tombstones = [element for element in elements if element["isDeleted"]]
    if len(tombstones) > MAX_TOMBSTONES:
        oldest = sorted(tombstones, key=lambda element: element["updated"])
        gone = {element["id"] for element in oldest[: len(tombstones) - MAX_TOMBSTONES]}
        elements = [element for element in elements if element["id"] not in gone]
    return {
        "format": "scene",
        "elements": elements,
        "appState": _app_state(raw.get("appState")),
        "files": _files(raw.get("files")),
    }


# --- merge ------------------------------------------------------------------------------------


def _wins(candidate: dict[str, Any], other: dict[str, Any]) -> bool:
    """Whether ``candidate`` beats ``other`` by the editor's rule (higher
    version; on a tie the lower ``versionNonce``)."""
    if candidate["version"] != other["version"]:
        return bool(candidate["version"] > other["version"])
    return bool(candidate["versionNonce"] < other["versionNonce"])


def _pruned(elements: list[dict[str, Any]], now_ms: int) -> list[dict[str, Any]]:
    """The elements with the oldest tombstones beyond :data:`KEEP_TOMBSTONES`
    removed, as long as they are older than :data:`TOMBSTONE_AGE_MS`.

    A young tombstone stays: an editor that has not saved since may still hold
    the element alive, and without the tombstone it would come back.
    """
    tombstones = [element for element in elements if element["isDeleted"]]
    excess = len(tombstones) - KEEP_TOMBSTONES
    if excess <= 0:
        return elements
    cutoff = now_ms - TOMBSTONE_AGE_MS
    old = sorted(
        (element for element in tombstones if element["updated"] < cutoff),
        key=lambda element: element["updated"],
    )
    gone = {element["id"] for element in old[:excess]}
    return [element for element in elements if element["id"] not in gone]


def merge_scene(
    stored: dict[str, Any], incoming: dict[str, Any], *, now_ms: int | None = None
) -> tuple[dict[str, Any], bool]:
    """Join the stored scene with an incoming one (both normalized).

    Per element id the newer element wins (:func:`_wins`; on a full tie the
    incoming one). An element only the stored scene has stays, placed after
    the element it follows in the stored order. The incoming scene sets the
    view state. Returns the merged scene and whether anything of the stored
    scene was newer than, or missing from, the incoming one: then the editor
    that sent ``incoming`` has to take the merged scene.
    """
    import time

    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    theirs = {element["id"]: element for element in stored.get("elements", [])}
    ours = {element["id"]: element for element in incoming.get("elements", [])}
    stored_newer = False
    chosen: dict[str, dict[str, Any]] = {}
    for ident, element in ours.items():
        other = theirs.get(ident)
        if other is not None and other != element and _wins(other, element):
            chosen[ident] = other
            stored_newer = True
        else:
            chosen[ident] = element
    # The stored-only elements follow the element they follow on disk.
    after: dict[str | None, list[dict[str, Any]]] = {}
    anchor: str | None = None
    for element in stored.get("elements", []):
        ident = element["id"]
        if ident in ours:
            anchor = ident
            continue
        after.setdefault(anchor, []).append(element)
        if not element["isDeleted"]:
            stored_newer = True
    order: list[dict[str, Any]] = list(after.get(None, []))
    for element in incoming.get("elements", []):
        order.append(chosen[element["id"]])
        order.extend(after.get(element["id"], []))
    files = dict(incoming.get("files") or {})
    for ident, entry in (stored.get("files") or {}).items():
        if ident not in files:
            files[ident] = entry
            stored_newer = True
    merged = {
        "format": "scene",
        "elements": _pruned(order, now),
        "appState": dict(incoming.get("appState") or _app_state(None)),
        "files": files,
    }
    return merged, stored_newer


# --- reading a scene ----------------------------------------------------------------------------


def live_elements(scene: Any) -> list[dict[str, Any]]:
    """The elements that are not deleted, in drawing order."""
    elements = scene.get("elements") if isinstance(scene, dict) else None
    if not isinstance(elements, list):
        return []
    return [
        element
        for element in elements
        if isinstance(element, dict) and not element.get("isDeleted")
    ]


def element_box(element: dict[str, Any]) -> tuple[float, float, float, float]:
    """The unrotated box of one element: ``(x0, y0, x1, y1)``.

    A line, an arrow and a stroke are as large as their points reach, not as
    their stored width says (an older or a hand-written element may not carry
    one that fits).
    """
    x = float(_number(element.get("x")) or 0.0)
    y = float(_number(element.get("y")) or 0.0)
    points = element.get("points")
    if element.get("type") in ("arrow", "line", "freedraw") and isinstance(points, list) and points:
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        return x + min(xs), y + min(ys), x + max(xs), y + max(ys)
    width = float(_number(element.get("width")) or 0.0)
    height = float(_number(element.get("height")) or 0.0)
    return x, y, x + width, y + height


def rotated_box(element: dict[str, Any]) -> tuple[float, float, float, float]:
    """The box of one element after its rotation about its centre."""
    x0, y0, x1, y1 = element_box(element)
    angle = float(_number(element.get("angle")) or 0.0)
    if not angle:
        return x0, y0, x1, y1
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    cos, sin = math.cos(angle), math.sin(angle)
    xs: list[float] = []
    ys: list[float] = []
    for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        dx, dy = px - cx, py - cy
        xs.append(cx + dx * cos - dy * sin)
        ys.append(cy + dx * sin + dy * cos)
    return min(xs), min(ys), max(xs), max(ys)


def scene_bounds(elements: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    """The box around every live element (rotation counted): ``(x0, y0, x1, y1)``.

    ``(0, 0, 0, 0)`` for a board with nothing on it.
    """
    boxes = [
        rotated_box(element)
        for element in elements
        if isinstance(element, dict) and not element.get("isDeleted")
    ]
    if not boxes:
        return 0.0, 0.0, 0.0, 0.0
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


__all__ = [
    "ARROWHEADS",
    "DEFAULT_FONT_FAMILY",
    "DROPPED_TYPES",
    "ELEMENT_TYPES",
    "FILL_STYLES",
    "FONT_FAMILIES",
    "IMAGE_MIME_TYPES",
    "LINEAR_TYPES",
    "LINE_HEIGHTS",
    "MAX_ELEMENTS",
    "MAX_SCENE_BYTES",
    "SHAPE_TYPES",
    "STROKE_STYLES",
    "color",
    "element_box",
    "element_id",
    "empty_scene",
    "file_id",
    "is_scene",
    "live_elements",
    "merge_scene",
    "normalize_scene",
    "rotated_box",
    "safe_link",
    "scene_bounds",
]
