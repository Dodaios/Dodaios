"""The assistant's hands on a whiteboard: actions on a scene, and a reading of it.

A board is the element JSON of the embedded editor. Writing that JSON by hand
is long and fragile for a model (a label is a second element bound to its
box, an arrow is bound at both ends and its points are relative), so the
model sends ACTIONS instead: ``{"do": "add", "type": "note", "label": "…"}``,
``{"do": "connect", "from": "a", "to": "b"}``, a whole ``diagram`` or a
Mermaid flowchart. :func:`apply_actions` turns them into valid elements, and
:func:`describe` reads a board back compactly enough for a model's turn.

Rules every action keeps:

* All or nothing. The actions of one call run on a copy; the first one that
  cannot be done raises ``NodeError`` naming its index and what to fix, and
  the scene stays as it was.
* Ids the model picks are kept, so one call can add ``a`` and ``b`` and then
  connect them. Things without an id get a short readable one (``note-3``).
  A new thing with the id of a deleted one takes its place with a higher
  version, so the editor's merge sees the newer element.
* Nothing new overlaps what is there: without a position a thing goes to a
  free place right of the content (things added in one call flow in rows),
  ``near``/``right_of``/``below`` put it beside an element, ``inside`` into
  a frame (which grows when it must).
* Arrows stay attached: moving, resizing, aligning or laying out a shape
  re-routes every arrow bound to it, and deleting it deletes them.
* Versions: an element changed by a call gets ``version + 1``, a fresh
  ``versionNonce`` and ``updated`` once, a new one starts at 1, a deleted one
  stays as a tombstone, so the editor's own reconciliation merges the
  assistant's edits with the person's.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Final

from dodaios.nodes import shell
from dodaios.nodes.board import convert as cv
from dodaios.nodes.board import elements as el
from dodaios.nodes.board import layout as lay
from dodaios.nodes.board import mermaid
from dodaios.nodes.types import NodeError

MAX_ACTIONS: Final[int] = 200
MAX_NEW_ELEMENTS: Final[int] = 3_000
MAX_POINTS: Final[int] = 5_000
#: How wide a row of things added in one call gets before the next row starts.
AUTO_ROW_WIDTH: Final[float] = 1_000.0
AUTO_GAP: Final[float] = 40.0
DEFAULT_FRAME_SIZE: Final[tuple[float, float]] = (480.0, 320.0)
#: How much of a board ``describe`` lists before it summarizes the rest.
DESCRIBE_LIMIT: Final[int] = 400
RAW_LIMIT: Final[int] = 60

ACTIONS: Final[tuple[str, ...]] = (
    "add",
    "update",
    "delete",
    "move",
    "resize",
    "connect",
    "group",
    "ungroup",
    "frame",
    "align",
    "distribute",
    "layout",
    "diagram",
    "mermaid",
    "style",
    "order",
    "lock",
    "unlock",
    "clear",
    "background",
    "grid",
)
_ACTION_ALIASES: Final[dict[str, str]] = {
    "create": "add",
    "insert": "add",
    "remove": "delete",
    "edit": "update",
    "set": "update",
    "link": "connect",
    "arrange": "layout",
    "flowchart": "mermaid",
    "restyle": "style",
    "z": "order",
}
_PREFIX: Final[dict[str, str]] = {
    "box": "box",
    "rect": "box",
    "rounded": "box",
    "ellipse": "ellipse",
    "circle": "circle",
    "diamond": "diamond",
    "note": "note",
    "text": "text",
    "frame": "frame",
    "arrow": "arrow",
    "line": "line",
    "image": "image",
    "freedraw": "drawing",
}
_SHAPES: Final[frozenset[str]] = frozenset({"rectangle", "ellipse", "diamond"})
_BINDABLE: Final[frozenset[str]] = frozenset(
    {"rectangle", "ellipse", "diamond", "image", "frame", "text"}
)
_FRIENDLY: Final[dict[str, str]] = {"rectangle": "box", "freedraw": "drawing"}


class _Problem(ValueError):
    """An action that cannot be done; the message says what to fix."""


def _fail(message: str) -> _Problem:
    return _Problem(message)


def _ids(value: Any, field: str = "ids") -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return [str(value)]
    if isinstance(value, list) and all(
        isinstance(v, (str, int)) and not isinstance(v, bool) for v in value
    ):
        return [str(v) for v in value]
    raise _fail(f"'{field}' must be an id or a list of ids")


def _pair(value: Any, field: str) -> tuple[float, float]:
    """``[x, y]`` or ``{"x", "y"}`` as two numbers."""
    if isinstance(value, dict):
        value = [value.get("x", value.get("dx", 0)), value.get("y", value.get("dy", 0))]
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise _fail(f"'{field}' must be [x, y]")
    return el.number_of(value[0], field), el.number_of(value[1], field)


def _points(value: Any, field: str = "points") -> list[tuple[float, float]]:
    if not isinstance(value, list) or len(value) < 2:
        raise _fail(f"'{field}' must be a list of at least two [x, y] points")
    if len(value) > MAX_POINTS:
        raise _fail(f"'{field}' holds at most {MAX_POINTS} points")
    return [_pair(point, field) for point in value]


class _Board:
    """A working copy of a scene with the helpers the actions share."""

    def __init__(self, scene: dict[str, Any], now_ms: int) -> None:
        source = scene if isinstance(scene, dict) else {}
        self.elements: list[dict[str, Any]] = copy.deepcopy(
            [e for e in source.get("elements") or [] if isinstance(e, dict) and e.get("id")]
        )
        self.app: dict[str, Any] = dict(source.get("appState") or {})
        self.app.setdefault("viewBackgroundColor", el.WHITE)
        self.app.setdefault("gridModeEnabled", False)
        self.files: dict[str, Any] = copy.deepcopy(source.get("files") or {})
        self.before: dict[str, dict[str, Any]] = {e["id"]: copy.deepcopy(e) for e in self.elements}
        self.now = now_ms
        self.created = 0
        self.auto: dict[str, float] | None = None
        self._reroute: set[str] = set()

    # ---------------------------------------------------------------- lookup

    def by_id(self) -> dict[str, dict[str, Any]]:
        return {e["id"]: e for e in self.elements}

    def find(self, ref: Any, *, what: str = "element") -> dict[str, Any]:
        name = str(ref or "").strip()
        if not name:
            raise _fail(f"a {what} id is missing")
        for item in self.elements:
            if item["id"] == name and not item.get("isDeleted"):
                if item.get("type") == "text" and item.get("containerId"):
                    container = self._live(item["containerId"])
                    if container is not None:
                        return container
                return item
        lowered = name.casefold()
        matches = [
            item
            for item in self.live()
            if not (item.get("type") == "text" and item.get("containerId"))
            and self.label_text(item).casefold() == lowered
        ]
        if len(matches) == 1:
            return matches[0]
        hint = " (several things carry that label; use the id)" if matches else ""
        raise _fail(f"there is no {what} {name!r} on the board{hint}; 'read' lists the ids")

    def _live(self, element_id: str) -> dict[str, Any] | None:
        for item in self.elements:
            if item["id"] == element_id and not item.get("isDeleted"):
                return item
        return None

    def live(self) -> list[dict[str, Any]]:
        return [e for e in self.elements if not e.get("isDeleted")]

    def label_of(self, container: dict[str, Any]) -> dict[str, Any] | None:
        for entry in container.get("boundElements") or []:
            if entry.get("type") == "text":
                found = self._live(entry.get("id", ""))
                if found is not None and found.get("containerId") == container["id"]:
                    return found
        return None

    def label_text(self, item: dict[str, Any]) -> str:
        if item.get("type") == "text":
            return str(item.get("originalText") or item.get("text") or "")
        if item.get("type") == "frame":
            return str(item.get("name") or "")
        label = self.label_of(item)
        return str(label.get("originalText") or label.get("text") or "") if label else ""

    def arrows_of(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        out = []
        for entry in item.get("boundElements") or []:
            if entry.get("type") == "arrow":
                found = self._live(entry.get("id", ""))
                if found is not None:
                    out.append(found)
        ident = item["id"]
        for other in self.live():
            if other.get("type") in ("arrow", "line") and other not in out:
                for side in ("startBinding", "endBinding"):
                    if (other.get(side) or {}).get("elementId") == ident:
                        out.append(other)
                        break
        return out

    def children(self, frame_item: dict[str, Any]) -> list[dict[str, Any]]:
        return [e for e in self.live() if e.get("frameId") == frame_item["id"]]

    def taken(self) -> set[str]:
        return {e["id"] for e in self.elements}

    def new_id(self, kind: str) -> str:
        prefix = _PREFIX.get(kind, "item")
        taken = self.taken()
        counter = 1
        while f"{prefix}-{counter}" in taken:
            counter += 1
        return f"{prefix}-{counter}"

    def claim(self, wanted: Any, kind: str) -> str:
        """The id a new element gets: the model's (if free) or a generated one."""
        if wanted in (None, ""):
            return self.new_id(kind)
        try:
            ident = el.check_model_id(wanted)
        except ValueError as exc:
            raise _fail(str(exc)) from None
        if self._live(ident) is not None:
            raise _fail(f"the id {ident!r} is already on the board; pick another or 'update' it")
        return ident

    # ---------------------------------------------------------------- writing

    def insert(self, items: list[dict[str, Any]]) -> None:
        """Add new elements on top; one with a deleted element's id replaces it."""
        self.created += len(items)
        if self.created > MAX_NEW_ELEMENTS:
            raise _fail(
                f"one call makes at most {MAX_NEW_ELEMENTS} elements; split it into several calls"
            )
        for item in items:
            for position, existing in enumerate(self.elements):
                if existing["id"] == item["id"]:
                    if not existing.get("isDeleted"):
                        raise _fail(f"the id {item['id']!r} is already on the board")
                    del self.elements[position]
                    break
            self.elements.append(item)

    def tombstone(self, item: dict[str, Any]) -> None:
        if item.get("isDeleted"):
            return
        item["isDeleted"] = True
        item["boundElements"] = None
        for side in ("startBinding", "endBinding"):
            if item.get(side):
                target = self._live(item[side]["elementId"])
                if target is not None:
                    el.drop_bound(target, item["id"])
        if item.get("containerId"):
            container = self._live(item["containerId"])
            if container is not None:
                el.drop_bound(container, item["id"])

    def occupied(self, skip: set[str] | None = None) -> list[lay.Rect]:
        """What new things must not overlap: every live thing but arrows and labels."""
        skip = skip or set()
        rects: list[lay.Rect] = []
        for item in self.live():
            if item["id"] in skip or item.get("type") in ("arrow",):
                continue
            if item.get("type") == "text" and item.get("containerId"):
                continue
            if item.get("frameId") and item["frameId"] not in skip:
                continue  # inside a frame: the frame's rectangle covers it
            x0, y0, x1, y1 = el.box_of(item)
            top = cv.FRAME_NAME_ROOM if item.get("type") == "frame" else 0.0
            rects.append((x0, y0 - top, x1, y1))
        return rects

    def reroute_later(self, item: dict[str, Any]) -> None:
        for arrow in self.arrows_of(item):
            self._reroute.add(arrow["id"])

    def reroute(self) -> None:
        """Draw every arrow bound to something that moved again, label included."""
        index = self.by_id()
        for arrow_id in sorted(self._reroute):
            arrow = index.get(arrow_id)
            if arrow is None or arrow.get("isDeleted"):
                continue
            start = self._end(arrow, "startBinding")
            end = self._end(arrow, "endBinding")
            points = el.absolute_points(arrow)
            if start is not None and end is not None:
                skip = {start["id"], end["id"]}
                if start.get("type") == "frame" or end.get("type") == "frame":
                    blockers: list[lay.Rect] = []
                else:
                    blockers = cv.obstacle_rects(self.live(), skip)
                new = cv.route(start, end, blockers)
            elif start is not None:
                new = [el.outline_point(start, points[-1], cv.ARROW_GAP), *points[1:]]
            elif end is not None:
                new = [*points[:-1], el.outline_point(end, points[0], cv.ARROW_GAP)]
            else:
                continue
            el.set_points(arrow, new)
            arrow["roundness"] = (
                el.ROUND_PROPORTIONAL if arrow.get("type") == "arrow" or len(new) > 2 else None
            )
            label = self.label_of(arrow)
            if label is not None:
                el.place_label(label, arrow)
        self._reroute.clear()

    def _end(self, arrow: dict[str, Any], side: str) -> dict[str, Any] | None:
        bound = arrow.get(side)
        return self._live(bound["elementId"]) if bound else None

    # ---------------------------------------------------------------- moving

    def carried(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """``items`` with what moves along: labels, a frame's children and their labels."""
        out: dict[str, dict[str, Any]] = {}
        for item in items:
            out[item["id"]] = item
            if item.get("type") == "frame":
                for child in self.children(item):
                    out[child["id"]] = child
        for item in list(out.values()):
            label = self.label_of(item)
            if label is not None:
                out[label["id"]] = label
        return list(out.values())

    def translate(self, items: list[dict[str, Any]], dx: float, dy: float) -> None:
        """Move ``items`` (and what they carry) by ``dx``/``dy``; arrows follow."""
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return
        moving = self.carried(items)
        moved_ids = {m["id"] for m in moving}
        for item in moving:
            item["x"] = el.tidy(float(item["x"]) + dx)
            item["y"] = el.tidy(float(item["y"]) + dy)
        for item in moving:
            for arrow in self.arrows_of(item):
                if arrow["id"] in moved_ids:
                    continue
                ends = [self._end(arrow, side) for side in ("startBinding", "endBinding")]
                if all(end is not None and end["id"] in moved_ids for end in ends):
                    # Both ends moved together: the arrow moves as it is.
                    arrow["x"] = el.tidy(float(arrow["x"]) + dx)
                    arrow["y"] = el.tidy(float(arrow["y"]) + dy)
                    moved_ids.add(arrow["id"])
                    label = self.label_of(arrow)
                    if label is not None:
                        label["x"] = el.tidy(float(label["x"]) + dx)
                        label["y"] = el.tidy(float(label["y"]) + dy)
                        moved_ids.add(label["id"])
                else:
                    self._reroute.add(arrow["id"])

    def group_box(self, items: list[dict[str, Any]]) -> lay.Rect:
        rects = [el.box_of(i) for i in items]
        found = lay.bounds(rects)
        assert found is not None
        return found

    # ---------------------------------------------------------------- placing

    def place(
        self, spec: dict[str, Any], w: float, h: float, *, skip: set[str] | None = None
    ) -> tuple[float, float, dict[str, Any] | None]:
        """Where a ``w`` × ``h`` thing goes, by its spec; and the frame it lands in."""
        if spec.get("x") is not None and spec.get("y") is not None:
            return el.number_of(spec["x"], "x"), el.number_of(spec["y"], "y"), None
        if spec.get("x") is not None or spec.get("y") is not None:
            raise _fail("give both 'x' and 'y', or neither")
        occupied = self.occupied(skip)
        for side, key in (
            ("right", "right_of"),
            ("left", "left_of"),
            ("below", "below"),
            ("above", "above"),
            ("near", "near"),
        ):
            if spec.get(key) not in (None, ""):
                anchor = self.find(spec[key])
                gap = (
                    el.number_of(spec["gap"], "gap")
                    if spec.get("gap") is not None
                    else lay.CLEARANCE * 2
                )
                x0, y0, x1, y1 = el.box_of(anchor)
                x, y = lay.free_spot(occupied, w, h, anchor=(x0, y0, x1, y1), side=side, gap=gap)
                frame_id = anchor.get("frameId")
                holder = self._live(frame_id) if frame_id else None
                return x, y, holder
        if spec.get("inside") not in (None, ""):
            holder = self.find(spec["inside"], what="frame")
            if holder.get("type") != "frame":
                raise _fail(f"'inside' must name a frame; {holder['id']!r} is a {holder['type']}")
            x, y = self.spot_in_frame(holder, w, h, skip or set())
            return x, y, holder
        return (*self.auto_spot(w, h, occupied), None)

    def auto_spot(self, w: float, h: float, occupied: list[lay.Rect]) -> tuple[float, float]:
        """The next free place for things added without a position in this call."""
        if self.auto is None:
            x, y = lay.free_spot(occupied, w, h)
            self.auto = {"x0": x, "x": x, "y": y, "bottom": y + h}
        else:
            x, y = self.auto["x"], self.auto["y"]
            if x + w - self.auto["x0"] > AUTO_ROW_WIDTH and x > self.auto["x0"]:
                x, y = self.auto["x0"], lay.snap(self.auto["bottom"] + AUTO_GAP)
                self.auto["bottom"] = y
            tries = 0
            while not lay.is_free((x, y, x + w, y + h), occupied) and tries < 400:
                y += lay.GRID * 2
                tries += 1
        self.auto["x"] = lay.snap(x + w + AUTO_GAP)
        self.auto["y"] = y
        self.auto["bottom"] = max(self.auto["bottom"], y + h)
        return x, y

    def spot_in_frame(
        self, holder: dict[str, Any], w: float, h: float, skip: set[str]
    ) -> tuple[float, float]:
        """A free place inside ``holder``; the frame grows downwards when it is full."""
        pad = cv.FRAME_PAD
        fx, fy = float(holder["x"]), float(holder["y"])
        fw, fh = float(holder["width"]), float(holder["height"])
        inside = [
            el.box_of(c)
            for c in self.children(holder)
            if c["id"] not in skip
            and not (c.get("type") == "text" and c.get("containerId"))
            and c.get("type") != "arrow"
        ]
        y = fy + pad
        while y + h <= fy + fh - pad + 0.5:
            x = fx + pad
            while x + w <= fx + fw - pad + 0.5:
                if lay.is_free((x, y, x + w, y + h), inside, margin=lay.GRID_GAP / 2):
                    return x, y
                x += lay.GRID
            y += lay.GRID
        bottom = max([fy + pad - lay.GRID_GAP, *(r[3] for r in inside)])
        x, y = fx + pad, lay.snap(bottom + lay.GRID_GAP)
        holder["height"] = el.tidy(max(fh, y + h + pad - fy))
        holder["width"] = el.tidy(max(fw, w + 2 * pad))
        return x, y

    def fit_frame(self, holder: dict[str, Any], members: list[dict[str, Any]]) -> None:
        """Grow ``holder`` so ``members`` sit inside with the frame's padding."""
        if not members:
            return
        x0, y0, x1, y1 = self.group_box(members)
        pad = cv.FRAME_PAD
        fx0 = min(float(holder["x"]), x0 - pad)
        fy0 = min(float(holder["y"]), y0 - pad)
        fx1 = max(float(holder["x"]) + float(holder["width"]), x1 + pad)
        fy1 = max(float(holder["y"]) + float(holder["height"]), y1 + pad)
        holder.update(
            x=el.tidy(fx0), y=el.tidy(fy0), width=el.tidy(fx1 - fx0), height=el.tidy(fy1 - fy0)
        )

    def adopt(self, holder: dict[str, Any], items: list[dict[str, Any]]) -> None:
        """Make ``items`` (and their labels) children of the frame ``holder``."""
        for item in self.carried(items):
            if item.get("type") == "frame":
                raise _fail(f"a frame cannot go into another frame ({item['id']!r})")
            item["frameId"] = holder["id"]
        inside = {i["id"] for i in self.carried(items)} | {c["id"] for c in self.children(holder)}
        for item in items:
            for arrow in self.arrows_of(item):
                ends = [self._end(arrow, side) for side in ("startBinding", "endBinding")]
                if all(end is not None and end["id"] in inside for end in ends):
                    arrow["frameId"] = holder["id"]
                    label = self.label_of(arrow)
                    if label is not None:
                        label["frameId"] = holder["id"]

    # ---------------------------------------------------------------- finishing

    def finish(self) -> dict[str, Any]:
        self.reroute()
        self._tidy_order()
        el.sync_indices(self.elements)
        for item in self.elements:
            old = self.before.get(item["id"])
            if old is None:
                item["version"] = 1
                item["updated"] = self.now
                continue
            if _differs(item, old):
                item["version"] = int(old.get("version") or 1) + 1
                item["versionNonce"] = el.new_nonce()
                item["updated"] = self.now
        return {
            "format": "scene",
            "elements": self.elements,
            "appState": self.app,
            "files": self.files,
        }

    def _tidy_order(self) -> None:
        """Labels right after their container, a frame after its children (the
        editor keeps that order)."""
        index = self.by_id()
        labels: dict[str, list[dict[str, Any]]] = {}
        attached: set[str] = set()
        for item in self.elements:
            container = item.get("containerId")
            if item.get("type") == "text" and container in index and not item.get("isDeleted"):
                labels.setdefault(container, []).append(item)
                attached.add(item["id"])
        ordered: list[dict[str, Any]] = []
        for item in self.elements:
            if item["id"] in attached:
                continue
            ordered.append(item)
            ordered.extend(labels.get(item["id"], []))
        frames = [i for i in ordered if i.get("type") == "frame" and not i.get("isDeleted")]
        for holder in frames:
            position = ordered.index(holder)
            last = max(
                (
                    p
                    for p, i in enumerate(ordered)
                    if i.get("frameId") == holder["id"] and not i.get("isDeleted")
                ),
                default=-1,
            )
            if last > position:
                ordered.pop(position)
                ordered.insert(last, holder)
        self.elements[:] = ordered


_VOLATILE: Final[frozenset[str]] = frozenset({"version", "versionNonce", "updated"})


def _differs(new: dict[str, Any], old: dict[str, Any]) -> bool:
    keys = (set(new) | set(old)) - _VOLATILE
    return any(new.get(k) != old.get(k) for k in keys)


# --- the actions ---------------------------------------------------------------------------


class _Actions:
    def __init__(self, board: _Board) -> None:
        self.b = board

    # ------------------------------------------------------------------ add

    def add(self, action: dict[str, Any]) -> str:
        items = action.get("items")
        if items is not None:
            if not isinstance(items, list) or not items:
                raise _fail("'items' must be a non-empty list of things to add")
            made: list[str] = []
            for position, item in enumerate(items):
                if not isinstance(item, dict):
                    raise _fail(f"items[{position}] must be an object")
                try:
                    made.append(
                        self._add_one(
                            {
                                **{k: v for k, v in action.items() if k not in ("items", "do")},
                                **item,
                            }
                        )
                    )
                except _Problem as exc:
                    raise _fail(f"items[{position}]: {exc}") from None
            return f"added {len(made)}: " + ", ".join(made)
        return "added " + self._add_one(action)

    def _add_one(self, spec: dict[str, Any]) -> str:
        b = self.b
        raw_kind = spec.get("type") or spec.get("shape") or spec.get("kind")
        if raw_kind in (None, ""):
            raw_kind = (
                "arrow"
                if spec.get("from") or spec.get("to")
                else ("freedraw" if spec.get("points") else "box")
            )
        kind = cv.kind_of(raw_kind)
        if kind in ("arrow", "line"):
            return self._add_linear(kind, spec)
        style = cv.parse_style(spec)
        label = cv._text(spec.get("label", spec.get("text", spec.get("name", ""))))
        if kind == "frame":
            return self._add_frame(spec, label)
        if kind == "freedraw":
            points = _points(spec.get("points"))
            ident = b.claim(spec.get("id"), kind)
            stroke = style.get("stroke") or (
                el.resolve_color(style["color"], "stroke") if style.get("color") else el.BLACK
            )
            item = el.freedraw(
                points,
                now_ms=b.now,
                element_id=ident,
                stroke=stroke,
                stroke_width=style.get("stroke_width", el.DEFAULT_STROKE_WIDTH),
                opacity=style.get("opacity", 100),
                roughness=style.get("roughness", 0),
            )
            b.insert([item])
            return f"drawing {ident!r}"
        if kind == "image":
            file_id = str(spec.get("file") or spec.get("file_id") or "")
            if file_id not in b.files:
                raise _fail("an image needs 'file': the id of a picture uploaded to this board")
        if kind == "text" and not label:
            raise _fail("a text needs 'text'")
        w, h = cv.node_size(kind, label, style)
        if spec.get("w", spec.get("width")) is not None:
            w = max(10.0, el.number_of(spec.get("w", spec.get("width")), "w"))
        if spec.get("h", spec.get("height")) is not None:
            h = max(10.0, el.number_of(spec.get("h", spec.get("height")), "h"))
        if kind == "circle":
            w = h = max(w, h)
        x, y, holder = b.place(spec, w, h)
        ident = b.claim(spec.get("id"), kind)
        parts = cv.build_node(
            kind,
            label,
            x=x,
            y=y,
            w=w,
            h=h,
            style=style,
            now_ms=b.now,
            element_id=ident,
            file_id=str(spec.get("file") or spec.get("file_id") or "") or None,
        )
        self._common(parts[0], spec)
        b.insert(parts)
        if holder is not None:
            b.adopt(holder, [parts[0]])
            b.fit_frame(holder, b.children(holder))
        size = f"{round(w)}x{round(h)}"
        return f"{_FRIENDLY.get(kind, kind)} {ident!r} at ({round(x)}, {round(y)}) {size}"

    def _common(self, item: dict[str, Any], spec: dict[str, Any]) -> None:
        if spec.get("link") not in (None, ""):
            link = shell.safe_link(spec["link"])
            if not link:
                raise _fail("'link' must start with https://, http:// or mailto:")
            item["link"] = link
        if spec.get("locked") is not None:
            item["locked"] = bool(spec["locked"])
        if spec.get("angle") is not None:
            item["angle"] = el.tidy(
                math.radians(el.number_of(spec["angle"], "angle")) % (2 * math.pi)
            )

    def _add_frame(self, spec: dict[str, Any], label: str) -> str:
        b = self.b
        members = [b.find(ref) for ref in _ids(spec.get("children", spec.get("ids")), "children")]
        ident = b.claim(spec.get("id"), "frame")
        if members:
            return self._frame_around(members, label, ident)
        w = el.number_of(spec.get("w", spec.get("width", DEFAULT_FRAME_SIZE[0])), "w")
        h = el.number_of(spec.get("h", spec.get("height", DEFAULT_FRAME_SIZE[1])), "h")
        x, y, holder = b.place(spec, w, h)
        if holder is not None:
            raise _fail("a frame cannot go into another frame")
        item = el.frame(
            label or None,
            x=x,
            y=y + (cv.FRAME_NAME_ROOM if spec.get("x") is None else 0),
            width=w,
            height=h,
            now_ms=b.now,
            element_id=ident,
        )
        b.insert([item])
        return f"frame {ident!r} at ({round(x)}, {round(item['y'])}) {round(w)}x{round(h)}"

    def _frame_around(self, members: list[dict[str, Any]], label: str, ident: str) -> str:
        b = self.b
        for member in members:
            if member.get("type") == "frame":
                raise _fail(f"a frame cannot go into another frame ({member['id']!r})")
        x0, y0, x1, y1 = b.group_box(b.carried(members))
        pad = cv.FRAME_PAD
        item = el.frame(
            label or None,
            x=x0 - pad,
            y=y0 - pad,
            width=x1 - x0 + 2 * pad,
            height=y1 - y0 + 2 * pad,
            now_ms=b.now,
            element_id=ident,
        )
        b.insert([item])
        b.adopt(item, members)
        return f"frame {ident!r} around {len(members)} thing(s)"

    def _add_linear(self, kind: str, spec: dict[str, Any]) -> str:
        b = self.b
        if spec.get("from") not in (None, "") or spec.get("to") not in (None, ""):
            if spec.get("from") in (None, "") or spec.get("to") in (None, ""):
                raise _fail("an arrow between things needs both 'from' and 'to'")
            return self._connect_pair(b.find(spec["from"]), b.find(spec["to"]), spec, kind)
        points = _points(spec.get("points"))
        style = cv.edge_style(spec)
        heads = cv.edge_heads(
            spec.get("arrow", "end" if kind == "arrow" else "none"),
            spec.get("start"),
            spec.get("end"),
        )
        ident = b.claim(spec.get("id"), kind)
        stroke = style.get("stroke") or (
            el.resolve_color(style["color"], "stroke") if style.get("color") else el.BLACK
        )
        item = el.linear(
            kind,
            points,
            now_ms=b.now,
            element_id=ident,
            stroke=stroke,
            stroke_width=style.get("stroke_width", el.DEFAULT_STROKE_WIDTH),
            stroke_style=style.get("stroke_style", "solid"),
            roughness=style.get("roughness", el.DEFAULT_ROUGHNESS),
            opacity=style.get("opacity", 100),
            start_head=heads[0],
            end_head=heads[1],
            curved=bool(spec.get("curved")),
        )
        parts = [item]
        label = cv._text(spec.get("label", ""), 200)
        if label:
            size, family = cv.label_font(style, cv.EDGE_LABEL_SIZE)
            parts.append(
                el.label_for(item, label, now_ms=b.now, font_size=size, font_family=family)
            )
        b.insert(parts)
        return f"{kind} {ident!r} through {len(points)} points"

    def _connect_pair(
        self, start: dict[str, Any], end: dict[str, Any], spec: dict[str, Any], kind: str = "arrow"
    ) -> str:
        b = self.b
        for item in (start, end):
            if item.get("type") not in _BINDABLE:
                raise _fail(
                    f"{item['id']!r} is a {item.get('type')}; arrows join shapes, texts, "
                    "pictures or frames"
                )
        if start["id"] == end["id"]:
            raise _fail("an arrow must join two different things")
        style = cv.edge_style(spec)
        heads = cv.edge_heads(
            spec.get("arrow", "end" if kind == "arrow" else "none"),
            spec.get("start"),
            spec.get("end"),
        )
        ident = b.claim(spec.get("id"), kind)
        existing = sum(
            1
            for a in b.arrows_of(start)
            if {
                (a.get("startBinding") or {}).get("elementId"),
                (a.get("endBinding") or {}).get("elementId"),
            }
            == {start["id"], end["id"]}
        )
        bend = 0.0 if not existing else 40.0 * ((existing + 1) // 2) * (1 if existing % 2 else -1)
        skip = {start["id"], end["id"]}
        blockers = (
            []
            if "frame" in (start.get("type"), end.get("type"))
            else cv.obstacle_rects(b.live(), skip)
        )
        parts = cv.arrow_between(
            start,
            end,
            now_ms=b.now,
            obstacles=blockers,
            label=cv._text(spec.get("label", ""), 200),
            style=style,
            start_head=heads[0],
            end_head=heads[1],
            kind=kind,
            element_id=ident,
            bend=bend,
        )
        if start.get("frameId") and start.get("frameId") == end.get("frameId"):
            for part in parts:
                part["frameId"] = start["frameId"]
        b.insert(parts)
        return f"{kind} {ident!r} {start['id']} -> {end['id']}"

    # ------------------------------------------------------------------ connect

    def connect(self, action: dict[str, Any]) -> str:
        b = self.b
        chain = action.get("chain")
        if chain is not None:
            names = _ids(chain, "chain")
            if len(names) < 2:
                raise _fail("'chain' needs at least two ids")
            if action.get("id"):
                raise _fail("a chain makes several arrows; leave out 'id'")
            made = [
                self._connect_pair(b.find(a), b.find(c), action)
                for a, c in zip(names, names[1:], strict=False)
            ]
            return "connected " + "; ".join(made)
        sources = _ids(action.get("from"), "from")
        targets = _ids(action.get("to"), "to")
        if not sources or not targets:
            raise _fail("'connect' needs 'from' and 'to' (ids), or 'chain'")
        if (len(sources) > 1 or len(targets) > 1) and action.get("id"):
            raise _fail("several arrows cannot share one 'id'")
        made = [
            self._connect_pair(
                b.find(s),
                b.find(t),
                action,
                cv.kind_of(action.get("type"), "arrow")
                if action.get("type") in ("line", "arrow")
                else "arrow",
            )
            for s in sources
            for t in targets
        ]
        return "connected " + "; ".join(made)

    # ------------------------------------------------------------------ update / style

    def update(self, action: dict[str, Any]) -> str:
        targets = self._targets(action)
        changed = [self._update_one(item, action) for item in targets]
        return "updated " + ", ".join(changed)

    def style(self, action: dict[str, Any]) -> str:
        allowed = {
            k: v
            for k, v in action.items()
            if k in cv._STYLE_KEYS or k in ("do", "id", "ids", "style", "start", "end", "arrow")
        }
        targets = self._targets(action)
        for item in targets:
            self._update_one(item, allowed)
        return f"styled {len(targets)}: " + ", ".join(i["id"] for i in targets)

    def _targets(self, action: dict[str, Any], *, allow_all: bool = False) -> list[dict[str, Any]]:
        names = _ids(action.get("ids", action.get("id")))
        if not names:
            if allow_all:
                return [
                    i
                    for i in self.b.live()
                    if not (i.get("type") == "text" and i.get("containerId"))
                ]
            raise _fail("name the things with 'id' or 'ids'")
        found: list[dict[str, Any]] = []
        for name in names:
            item = self.b.find(name)
            if item not in found:
                found.append(item)
        return found

    def _update_one(self, item: dict[str, Any], spec: dict[str, Any]) -> str:
        b = self.b
        kind = item.get("type")
        style = cv.parse_style(spec)
        if spec.get("type") not in (None, "") and cv.kind_of(spec["type"]) != _kind_name(item, b):
            raise _fail(f"{item['id']!r} cannot change its type; delete it and add a new one")
        if kind in ("arrow", "line"):
            self._style_linear(item, style, spec)
        elif kind == "text":
            self._style_text(item, style)
        elif kind == "frame":
            if style:
                raise _fail("a frame has no style; give it a 'name'")
        else:
            self._style_shape(item, style)
        for key in ("label", "text", "name"):
            if key in spec:
                self._set_text(item, cv._text(spec[key]), style)
                break
        self._common(item, spec)
        if spec.get("locked") is not None:
            item["locked"] = bool(spec["locked"])
        if spec.get("from") is not None or spec.get("to") is not None:
            if kind not in ("arrow", "line"):
                raise _fail("'from'/'to' re-attach an arrow; this is not one")
            self._rebind(item, spec)
        if spec.get("x") is not None or spec.get("y") is not None:
            x = el.number_of(spec.get("x", item["x"]), "x")
            y = el.number_of(spec.get("y", item["y"]), "y")
            x0, y0, _, _ = el.box_of(item)
            b.translate([item], x - x0, y - y0)
        if any(spec.get(k) is not None for k in ("w", "h", "width", "height")):
            self._resize_one(item, spec)
        return item["id"]

    def _style_shape(self, item: dict[str, Any], style: dict[str, Any]) -> None:
        if not style:
            return
        if style.get("color"):
            note = _looks_like_note(item)
            item["strokeColor"] = el.resolve_color(style["color"], "stroke")
            item["backgroundColor"] = (
                el.resolve_color(style["color"] if note else f"light {style['color']}", "fill")
                if cv._is_palette(style["color"])
                else el.TRANSPARENT
            )
        for key, field in (
            ("stroke", "strokeColor"),
            ("fill", "backgroundColor"),
            ("fill_style", "fillStyle"),
            ("stroke_width", "strokeWidth"),
            ("stroke_style", "strokeStyle"),
            ("roughness", "roughness"),
            ("opacity", "opacity"),
        ):
            if key in style:
                item[field] = style[key]
        if "rounded" in style and item.get("type") in ("rectangle", "diamond"):
            item["roundness"] = (
                (el.ROUND_ADAPTIVE if item["type"] == "rectangle" else el.ROUND_PROPORTIONAL)
                if style["rounded"]
                else None
            )
        label = self.b.label_of(item)
        if label is not None:
            self._style_text(
                label,
                {
                    k: v
                    for k, v in style.items()
                    if k in ("font", "size", "align", "text_color", "opacity")
                },
                container=item,
            )

    def _style_text(
        self, item: dict[str, Any], style: dict[str, Any], container: dict[str, Any] | None = None
    ) -> None:
        if not style:
            return
        if "text_color" in style:
            item["strokeColor"] = style["text_color"]
        elif container is None and ("color" in style or "stroke" in style):
            item["strokeColor"] = style.get("stroke") or el.resolve_color(style["color"], "stroke")
        if "font" in style:
            item["fontFamily"] = style["font"]
            item["lineHeight"] = el.line_height(style["font"])
        if "size" in style:
            item["fontSize"] = style["size"]
        if "align" in style:
            item["textAlign"] = style["align"]
        if "opacity" in style:
            item["opacity"] = style["opacity"]
        self._refit_text(item)

    def _refit_text(self, item: dict[str, Any]) -> None:
        container = self.b._live(item["containerId"]) if item.get("containerId") else None
        if container is not None:
            self._grow_for_label(container, item)
            el.place_label(item, container)
            return
        width, height = el.estimate_text(
            str(item.get("text") or ""), float(item["fontSize"]), int(item["fontFamily"])
        )
        item["width"], item["height"] = width, height

    def _grow_for_label(self, container: dict[str, Any], label: dict[str, Any]) -> None:
        """A box keeps its size unless its label no longer fits: then it grows down."""
        if container.get("type") not in _SHAPES:
            return
        size, family = float(label["fontSize"]), int(label["fontFamily"])
        room_w, room_h = el.label_room(
            container["type"], float(container["width"]), float(container["height"])
        )
        wrapped = el.wrap_text(
            str(label.get("originalText") or ""), max(room_w, size), size, family
        )
        _, need_h = el.estimate_text(wrapped, size, family)
        if need_h > room_h:
            _, total_h = el.container_for_text(container["type"], room_w, need_h + 8)
            container["height"] = el.tidy(
                el.snap_up(max(float(container["height"]), total_h), lay.GRID)
            )
            self.b.reroute_later(container)

    def _style_linear(
        self, item: dict[str, Any], style: dict[str, Any], spec: dict[str, Any]
    ) -> None:
        line = spec.get("style")
        if isinstance(line, str) and line:
            style = {**cv.edge_style({"style": line}), **style}
        if style.get("color"):
            item["strokeColor"] = el.resolve_color(style["color"], "stroke")
        for key, field in (
            ("stroke", "strokeColor"),
            ("stroke_width", "strokeWidth"),
            ("stroke_style", "strokeStyle"),
            ("roughness", "roughness"),
            ("opacity", "opacity"),
        ):
            if key in style:
                item[field] = style[key]
        if item.get("type") == "arrow" and any(
            spec.get(k) is not None for k in ("arrow", "start", "end")
        ):
            current = (
                "both"
                if item.get("startArrowhead") and item.get("endArrowhead")
                else (
                    "start"
                    if item.get("startArrowhead")
                    else "end"
                    if item.get("endArrowhead")
                    else "none"
                )
            )
            start, end = cv.edge_heads(
                spec.get("arrow", current), spec.get("start"), spec.get("end")
            )
            item["startArrowhead"], item["endArrowhead"] = start, end
        label = self.b.label_of(item)
        if label is not None:
            self._style_text(
                label,
                {k: v for k, v in style.items() if k in ("font", "size", "text_color")},
                container=item,
            )

    def _set_text(self, item: dict[str, Any], value: str, style: dict[str, Any]) -> None:
        b = self.b
        kind = item.get("type")
        if kind == "frame":
            item["name"] = value or None
            return
        if kind == "text":
            if not value:
                raise _fail("a text cannot be empty; delete it instead")
            item["text"] = item["originalText"] = value
            self._refit_text(item)
            return
        if kind not in _SHAPES and kind not in ("arrow", "line"):
            raise _fail(f"a {kind} has no label")
        label = b.label_of(item)
        if not value:
            if label is not None:
                b.tombstone(label)
                el.drop_bound(item, label["id"])
            return
        if label is None:
            size, family = cv.label_font(
                style, cv.EDGE_LABEL_SIZE if kind in ("arrow", "line") else cv.LABEL_SIZE
            )
            label = el.label_for(
                item,
                value,
                now_ms=b.now,
                font_size=size,
                font_family=family,
                color=style.get("text_color", el.BLACK),
            )
            if item.get("frameId"):
                label["frameId"] = item["frameId"]
            b.insert([label])
            self._grow_for_label(item, label)
            el.place_label(label, item)
            return
        label["originalText"] = value
        label["text"] = value
        self._grow_for_label(item, label)
        el.place_label(label, item)

    def _rebind(self, arrow: dict[str, Any], spec: dict[str, Any]) -> None:
        b = self.b
        for side, key in (("startBinding", "from"), ("endBinding", "to")):
            if spec.get(key) in (None, ""):
                continue
            target = b.find(spec[key])
            if target.get("type") not in _BINDABLE:
                raise _fail(f"{target['id']!r} cannot hold an arrow")
            old = arrow.get(side)
            if old:
                previous = b._live(old["elementId"])
                if previous is not None:
                    el.drop_bound(previous, arrow["id"])
            arrow[side] = el.binding(target["id"], cv.ARROW_GAP)
            el.add_bound(target, arrow["id"], "arrow")
        b._reroute.add(arrow["id"])

    # ------------------------------------------------------------------ delete / clear

    def delete(self, action: dict[str, Any]) -> str:
        targets = self._targets(action)
        keep_arrows = bool(action.get("keep_arrows"))
        keep_contents = bool(action.get("keep_contents"))
        gone: list[str] = []
        for item in targets:
            self._delete_one(item, keep_arrows=keep_arrows, keep_contents=keep_contents, gone=gone)
        return f"deleted {len(gone)}: " + ", ".join(gone[:30]) + (" …" if len(gone) > 30 else "")

    def _delete_one(
        self, item: dict[str, Any], *, keep_arrows: bool, keep_contents: bool, gone: list[str]
    ) -> None:
        b = self.b
        if item.get("isDeleted"):
            return
        if item.get("type") == "frame":
            for child in b.children(item):
                if keep_contents:
                    child["frameId"] = None
                elif not (child.get("type") == "text" and child.get("containerId")):
                    self._delete_one(child, keep_arrows=keep_arrows, keep_contents=False, gone=gone)
        for arrow in b.arrows_of(item):
            if keep_arrows:
                for side in ("startBinding", "endBinding"):
                    if (arrow.get(side) or {}).get("elementId") == item["id"]:
                        arrow[side] = None
            else:
                self._delete_one(arrow, keep_arrows=True, keep_contents=False, gone=gone)
        label = b.label_of(item)
        if label is not None:
            b.tombstone(label)
        b.tombstone(item)
        if not (item.get("type") == "text" and item.get("containerId")):
            gone.append(item["id"])

    def clear(self, action: dict[str, Any]) -> str:
        count = 0
        for item in self.b.live():
            self.b.tombstone(item)
            count += 1
        self.b.auto = None
        return f"cleared the board ({count} elements)"

    # ------------------------------------------------------------------ move / resize

    def move(self, action: dict[str, Any]) -> str:
        b = self.b
        targets = self._targets(action)
        x0, y0, x1, y1 = b.group_box(b.carried(targets))
        if action.get("by") is not None:
            dx, dy = _pair(action["by"], "by")
        elif action.get("dx") is not None or action.get("dy") is not None:
            dx = el.number_of(action.get("dx", 0), "dx")
            dy = el.number_of(action.get("dy", 0), "dy")
        elif action.get("to") is not None:
            tx, ty = _pair(action["to"], "to")
            dx, dy = tx - x0, ty - y0
        elif any(
            action.get(k) not in (None, "")
            for k in ("right_of", "left_of", "below", "above", "near")
        ):
            skip = {i["id"] for i in b.carried(targets)}
            tx, ty, _ = b.place(
                {
                    k: v
                    for k, v in action.items()
                    if k in ("right_of", "left_of", "below", "above", "near", "gap")
                },
                x1 - x0,
                y1 - y0,
                skip=skip,
            )
            dx, dy = tx - x0, ty - y0
        else:
            raise _fail(
                "'move' needs 'by' [dx, dy], 'to' [x, y], or 'right_of'/'below'/'near' an id"
            )
        b.translate(targets, dx, dy)
        self._keep_in_frames(targets)
        return f"moved {len(targets)} by ({round(dx)}, {round(dy)})"

    def _keep_in_frames(self, items: list[dict[str, Any]]) -> None:
        """A child moved past its frame's edge stretches the frame (the editor
        hides what lies outside a frame)."""
        b = self.b
        for item in items:
            holder = b._live(item.get("frameId") or "") if item.get("frameId") else None
            if holder is not None:
                b.fit_frame(holder, b.children(holder))

    def resize(self, action: dict[str, Any]) -> str:
        targets = self._targets(action)
        for item in targets:
            self._resize_one(item, action)
        return f"resized {len(targets)}: " + ", ".join(i["id"] for i in targets)

    def _resize_one(self, item: dict[str, Any], spec: dict[str, Any]) -> None:
        b = self.b
        old_w, old_h = float(item.get("width") or 0), float(item.get("height") or 0)
        if spec.get("scale") is not None:
            factor = el.number_of(spec["scale"], "scale")
            if not 0.05 <= factor <= 20:
                raise _fail("'scale' must be between 0.05 and 20")
            new_w, new_h = old_w * factor, old_h * factor
        else:
            w = spec.get("w", spec.get("width"))
            h = spec.get("h", spec.get("height"))
            if w is None and h is None:
                raise _fail("'resize' needs 'w', 'h' or 'scale'")
            new_w = max(10.0, el.number_of(w, "w")) if w is not None else old_w
            new_h = max(10.0, el.number_of(h, "h")) if h is not None else old_h
        kind = item.get("type")
        if kind == "text":
            factor = (
                new_w / old_w
                if old_w and spec.get("w", spec.get("width", spec.get("scale"))) is not None
                else (new_h / old_h if old_h else 1.0)
            )
            if spec.get("scale") is not None:
                factor = el.number_of(spec["scale"], "scale")
            item["fontSize"] = el.tidy(
                max(el.MIN_FONT_SIZE, min(el.MAX_FONT_SIZE, float(item["fontSize"]) * factor))
            )
            self._refit_text(item)
            b.reroute_later(item)
            return
        if kind in ("arrow", "line", "freedraw"):
            sx = new_w / old_w if old_w else 1.0
            sy = new_h / old_h if old_h else 1.0
            pts = el.absolute_points(item)
            ox, oy = pts[0]
            scaled = [(ox + (px - ox) * sx, oy + (py - oy) * sy) for px, py in pts]
            if kind == "freedraw":
                rel = [[el.tidy(px - ox), el.tidy(py - oy)] for px, py in scaled]
                item["points"] = rel
                item["width"], item["height"] = el.tidy(old_w * sx), el.tidy(old_h * sy)
            else:
                el.set_points(item, scaled)
            return
        item["width"], item["height"] = el.tidy(new_w), el.tidy(new_h)
        label = b.label_of(item)
        if label is not None:
            self._grow_for_label(item, label)
            el.place_label(label, item)
        b.reroute_later(item)
        if item.get("frameId"):
            self._keep_in_frames([item])

    # ------------------------------------------------------------------ groups / frames

    def group(self, action: dict[str, Any]) -> str:
        targets = self._targets(action)
        if len(targets) < 2:
            raise _fail("'group' needs at least two ids")
        group_id = el.new_id()
        for item in self.b.carried(targets):
            item["groupIds"] = [*(item.get("groupIds") or []), group_id]
        return f"grouped {len(targets)} as group {group_id!r}"

    def ungroup(self, action: dict[str, Any]) -> str:
        b = self.b
        wanted = _ids(action.get("group"), "group")
        if not wanted:
            for item in self._targets(action):
                if item.get("groupIds"):
                    wanted.append(item["groupIds"][-1])
        if not wanted:
            raise _fail("those things are not grouped")
        count = 0
        for item in b.live():
            kept = [g for g in item.get("groupIds") or [] if g not in wanted]
            if kept != list(item.get("groupIds") or []):
                item["groupIds"] = kept
                count += 1
        return f"ungrouped {count} element(s)"

    def frame(self, action: dict[str, Any]) -> str:
        b = self.b
        members = (
            self._targets(action) if action.get("ids") or action.get("children") is None else []
        )
        if action.get("children") is not None:
            members = [b.find(ref) for ref in _ids(action["children"], "children")]
        if not members:
            raise _fail("'frame' needs 'ids': the things to put into the frame")
        name = cv._text(action.get("name", action.get("label", "")), 200)
        into = action.get("into")
        if into not in (None, ""):
            holder = b.find(into, what="frame")
            if holder.get("type") != "frame":
                raise _fail(f"'into' must name a frame; {holder['id']!r} is a {holder['type']}")
            b.adopt(holder, members)
            b.fit_frame(holder, b.children(holder))
            if name:
                holder["name"] = name
            return f"put {len(members)} thing(s) into frame {holder['id']!r}"
        ident = b.claim(action.get("frame_id", action.get("new_id")), "frame")
        return self._frame_around(members, name, ident)

    # ------------------------------------------------------------------ align / distribute

    def align(self, action: dict[str, Any]) -> str:
        b = self.b
        targets = self._targets(action)
        if len(targets) < 2:
            raise _fail("'align' needs at least two ids")
        side = str(action.get("to") or action.get("side") or "").strip().lower()
        if side not in ("left", "center", "right", "top", "middle", "bottom"):
            raise _fail("'to' must be left, center, right, top, middle or bottom")
        boxes = {i["id"]: el.box_of(i) for i in targets}
        x0 = min(r[0] for r in boxes.values())
        y0 = min(r[1] for r in boxes.values())
        x1 = max(r[2] for r in boxes.values())
        y1 = max(r[3] for r in boxes.values())
        for item in targets:
            r = boxes[item["id"]]
            dx = dy = 0.0
            if side == "left":
                dx = x0 - r[0]
            elif side == "right":
                dx = x1 - r[2]
            elif side == "center":
                dx = (x0 + x1) / 2 - (r[0] + r[2]) / 2
            elif side == "top":
                dy = y0 - r[1]
            elif side == "bottom":
                dy = y1 - r[3]
            else:
                dy = (y0 + y1) / 2 - (r[1] + r[3]) / 2
            b.translate([item], dx, dy)
        self._keep_in_frames(targets)
        return f"aligned {len(targets)} to the {side}"

    def distribute(self, action: dict[str, Any]) -> str:
        b = self.b
        targets = self._targets(action)
        if len(targets) < 3 and action.get("gap") is None:
            raise _fail("'distribute' needs at least three ids (or two with a 'gap')")
        axis = str(action.get("axis") or action.get("direction") or "horizontal").strip().lower()
        if axis not in ("horizontal", "vertical", "x", "y"):
            raise _fail("'axis' must be horizontal or vertical")
        horizontal = axis in ("horizontal", "x")
        lo, hi = (0, 2) if horizontal else (1, 3)
        boxes = sorted(((el.box_of(i), i) for i in targets), key=lambda pair: pair[0][lo])
        sizes = [r[hi] - r[lo] for r, _ in boxes]
        if action.get("gap") is not None:
            gap = el.number_of(action["gap"], "gap")
        else:
            span = boxes[-1][0][hi] - boxes[0][0][lo]
            gap = (span - sum(sizes)) / (len(boxes) - 1)
        cursor = boxes[0][0][lo]
        for (r, item), size in zip(boxes, sizes, strict=True):
            delta = cursor - r[lo]
            b.translate([item], delta if horizontal else 0.0, 0.0 if horizontal else delta)
            cursor += size + gap
        self._keep_in_frames(targets)
        return f"distributed {len(targets)} {'horizontally' if horizontal else 'vertically'}"

    # ------------------------------------------------------------------ layout

    def layout(self, action: dict[str, Any]) -> str:
        b = self.b
        kind = (
            str(action.get("kind") or action.get("layout") or action.get("type") or "flow")
            .strip()
            .lower()
        )
        if kind not in lay.KINDS:
            raise _fail(f"'kind' must be one of {', '.join(lay.KINDS)}")
        holder: dict[str, Any] | None = None
        if action.get("frame") not in (None, ""):
            holder = b.find(action["frame"], what="frame")
            if holder.get("type") != "frame":
                raise _fail(f"'frame' must name a frame; {holder['id']!r} is a {holder['type']}")
            units = [c for c in b.children(holder) if _is_unit(c)]
        elif action.get("ids") not in (None, ""):
            units = [i for i in self._targets(action) if _is_unit(i)]
        else:
            units = [i for i in b.live() if _is_unit(i) and not i.get("frameId")]
        if not units:
            raise _fail("there is nothing to lay out")
        frames_in = {u["id"] for u in units if u.get("type") == "frame"}
        if holder is None:
            parents = {u.get("frameId") for u in units}
            if len(parents) == 1 and None not in parents:
                holder = b._live(parents.pop() or "")
        unit_of: dict[str, str] = {u["id"]: u["id"] for u in units}
        for u in units:
            if u.get("type") == "frame":
                for child in b.children(u):
                    unit_of.setdefault(child["id"], u["id"])
        edges: list[tuple[str, str]] = []
        for arrow in b.live():
            if arrow.get("type") not in ("arrow", "line"):
                continue
            s = unit_of.get((arrow.get("startBinding") or {}).get("elementId", ""))
            e = unit_of.get((arrow.get("endBinding") or {}).get("elementId", ""))
            if s and e and s != e and (s, e) not in edges:
                edges.append((s, e))
        # A large free text nothing points to is a heading: it stays on top of
        # what is laid out instead of joining the grid of loose things.
        linked = {name for pair in edges for name in pair}
        headings = [
            u
            for u in units
            if holder is None
            and u.get("type") == "text"
            and u["id"] not in linked
            and float(u.get("fontSize") or 0) >= el.FONT_SIZES["l"]
        ]
        if headings and len(headings) < len(units):
            units = [u for u in units if u not in headings]
        else:
            headings = []
        boxes = []
        for u in units:
            x0, y0, x1, y1 = el.box_of(u)
            boxes.append(
                lay.Box(
                    u["id"],
                    x1 - x0,
                    y1 - y0,
                    top=cv.FRAME_NAME_ROOM if u["id"] in frames_in else 0.0,
                )
            )
        before = b.group_box(units + headings)
        labeled = any(b.label_of(a) for a in b.live() if a.get("type") == "arrow")
        gap = (
            el.number_of(action["gap"], "gap")
            if action.get("gap") is not None
            else (lay.FLOW_GAP_LABELED if labeled and kind == "flow" else None)
        )
        columns = (
            int(el.number_of(action["columns"], "columns"))
            if action.get("columns") is not None
            else None
        )
        root = b.find(action["root"])["id"] if action.get("root") not in (None, "") else None
        direction = lay.direction_of(action.get("direction"), "TB" if kind == "tree" else "LR")
        lay.arrange(
            boxes,
            edges,
            kind=kind,
            direction=direction,
            gap=gap,
            columns=columns,
            root=unit_of.get(root, root) if root else None,
        )
        if holder is not None:
            ox, oy = float(holder["x"]) + cv.FRAME_PAD, float(holder["y"]) + cv.FRAME_PAD
        else:
            ox, oy = lay.snap(before[0]), lay.snap(before[1])
        for heading in headings:
            x0, y0, _, y1 = el.box_of(heading)
            b.translate([heading], ox - x0, oy - y0)
            oy = lay.snap(oy + (y1 - y0) + lay.CROSS_GAP)
        by_key = {u["id"]: u for u in units}
        for box in boxes:
            item = by_key[box.key]
            x0, y0, _, _ = el.box_of(item)
            b.translate([item], lay.snap(ox + box.x) - x0, lay.snap(oy + box.y) - y0)
        if holder is not None:
            self._shrink_frame(holder)
        if holder is None and len(units) + len(headings) < len(
            [i for i in b.live() if _is_unit(i) and not i.get("frameId")]
        ):
            self._clear_of_others(units + headings)
        return f"laid out {len(units)} as a {kind}" + (
            f" ({direction})" if kind in ("flow", "tree") else ""
        )

    def _shrink_frame(self, holder: dict[str, Any]) -> None:
        members = [c for c in self.b.children(holder) if c.get("type") != "arrow"]
        if not members:
            return
        x0, y0, x1, y1 = self.b.group_box(members)
        pad = cv.FRAME_PAD
        holder.update(
            x=el.tidy(x0 - pad),
            y=el.tidy(y0 - pad),
            width=el.tidy(x1 - x0 + 2 * pad),
            height=el.tidy(y1 - y0 + 2 * pad),
        )
        self.b.reroute_later(holder)

    def _clear_of_others(self, units: list[dict[str, Any]]) -> None:
        """Laid-out things that now overlap the rest of the board move clear of it, as one block."""
        b = self.b
        moving = {i["id"] for i in b.carried(units)}
        others = b.occupied(moving)
        x0, y0, x1, y1 = b.group_box(b.carried(units))
        if lay.is_free((x0, y0, x1, y1), others):
            return
        x, y = lay.free_spot(others, x1 - x0, y1 - y0)
        b.translate(units, x - x0, y - y0)

    # ------------------------------------------------------------------ diagram / mermaid

    def diagram(self, action: dict[str, Any]) -> str:
        given = action.get("diagram")
        keys = ("nodes", "edges", "links", "groups", "direction", "layout", "root", "title")
        raw: dict[str, Any] = (
            given if isinstance(given, dict) else {k: v for k, v in action.items() if k in keys}
        )
        return self._place_diagram(raw, action, "diagram")

    def mermaid(self, action: dict[str, Any]) -> str:
        source = action.get("source", action.get("mermaid", action.get("text")))
        diagram = mermaid.parse(source)
        if action.get("direction"):
            diagram["direction"] = action["direction"]
        if action.get("layout"):
            diagram["layout"] = action["layout"]
        for key in ("title", "root"):
            if action.get(key):
                diagram[key] = action[key]
        return self._place_diagram(diagram, action, "flowchart")

    def _place_diagram(self, raw: dict[str, Any], action: dict[str, Any], what: str) -> str:
        b = self.b
        spec = cv.normalize_diagram(raw)
        placement = cv.layout_diagram(spec)
        w, h = placement["size"]
        position = {
            k: action[k]
            for k in ("x", "y", "right_of", "left_of", "below", "above", "near", "gap")
            if action.get(k) not in (None, "")
        }
        x, y, holder = b.place(position, w, h)
        if holder is not None and spec["groups"]:
            raise _fail("a diagram with groups cannot go into a frame (frames do not nest)")
        items, ids = cv.diagram_to_elements(
            spec,
            origin=(x, y),
            now_ms=b.now,
            taken=b.taken(),
            obstacles=b.occupied(),
            laid_out=placement,
        )
        b.insert(items)
        if holder is not None:
            shapes = [
                i
                for i in items
                if not (i.get("type") == "text" and i.get("containerId"))
                and i.get("type") != "arrow"
            ]
            b.adopt(holder, shapes)
            b.fit_frame(holder, b.children(holder))
        renamed = [f"{a}->{c}" for a, c in ids.items() if a != c]
        arrows = sum(1 for i in items if i.get("type") == "arrow")
        frames = sum(1 for i in items if i.get("type") == "frame")
        text = (
            f"{what}: {len(spec['nodes'])} nodes, {arrows} arrows, {frames} frames at "
            f"({round(x)}, {round(y)}) {round(w)}x{round(h)}"
        )
        if renamed:
            text += "; ids taken on the board were renamed: " + ", ".join(renamed[:40])
        return text

    # ------------------------------------------------------------------ order / lock / board

    def order(self, action: dict[str, Any]) -> str:
        b = self.b
        targets = self._targets(action)
        where = str(action.get("to") or "front").strip().lower()
        if where not in ("front", "back", "forward", "backward"):
            raise _fail("'to' must be front, back, forward or backward")
        moving = b.carried(targets)
        ids = {m["id"] for m in moving}
        rest = [e for e in b.elements if e["id"] not in ids]
        block = [e for e in b.elements if e["id"] in ids]
        if where == "front":
            b.elements[:] = rest + block
        elif where == "back":
            b.elements[:] = block + rest
        else:
            first = min(p for p, e in enumerate(b.elements) if e["id"] in ids)
            last = max(p for p, e in enumerate(b.elements) if e["id"] in ids)
            if where == "forward":
                after = [
                    p
                    for p, e in enumerate(b.elements)
                    if p > last and e["id"] not in ids and not e.get("isDeleted")
                ]
                cut = after[0] + 1 if after else len(b.elements)
                at = len([e for e in b.elements[:cut] if e["id"] not in ids])
            else:
                before = [
                    p
                    for p, e in enumerate(b.elements)
                    if p < first and e["id"] not in ids and not e.get("isDeleted")
                ]
                cut = before[-1] if before else 0
                at = len([e for e in b.elements[:cut] if e["id"] not in ids])
            b.elements[:] = rest[:at] + block + rest[at:]
        return f"moved {len(targets)} to the {where}"

    def lock(self, action: dict[str, Any]) -> str:
        targets = self._targets(action, allow_all=True)
        for item in self.b.carried(targets):
            item["locked"] = True
        return f"locked {len(targets)}"

    def unlock(self, action: dict[str, Any]) -> str:
        targets = self._targets(action, allow_all=True)
        for item in self.b.carried(targets):
            item["locked"] = False
        return f"unlocked {len(targets)}"

    def background(self, action: dict[str, Any]) -> str:
        value = action.get("color", action.get("value"))
        name = str(value or "").strip().lower()
        color = el.resolve_color(f"light {name}" if name in el.PALETTE else value, "fill")
        if color == el.TRANSPARENT:
            color = el.WHITE
        self.b.app["viewBackgroundColor"] = color
        return f"background {color}"

    def grid(self, action: dict[str, Any]) -> str:
        value = action.get("on", action.get("value", True))
        on = (
            value
            if isinstance(value, bool)
            else str(value).strip().lower() in ("on", "true", "yes", "1")
        )
        self.b.app["gridModeEnabled"] = on
        return f"grid {'on' if on else 'off'}"


def _kind_name(item: dict[str, Any], board: _Board) -> str:
    kind = item.get("type", "")
    if kind == "rectangle":
        if _looks_like_note(item):
            return "note"
        return "box" if item.get("roundness") else "rect"
    return {"freedraw": "freedraw"}.get(kind, kind)


def _looks_like_note(item: dict[str, Any]) -> bool:
    if item.get("type") != "rectangle":
        return False
    fill = str(item.get("backgroundColor") or "").lower()
    return fill == el.NOTE_FILL or (
        float(item.get("strokeWidth") or 2) <= 1
        and any(fill == shades[el.FILL_SHADE] for shades in el.PALETTE.values())
    )


def _is_unit(item: dict[str, Any]) -> bool:
    """Whether ``item`` is placed by a layout on its own (not a label, not an arrow)."""
    if item.get("isDeleted") or item.get("type") in ("arrow", "line"):
        return False
    return not (item.get("type") == "text" and item.get("containerId"))


# --- entry points ------------------------------------------------------------------------------


def _normalize(scene: dict[str, Any]) -> dict[str, Any]:
    from dodaios.nodes.board.scene import normalize_scene

    return normalize_scene(scene)


def apply_actions(
    scene: dict[str, Any], actions: list[dict[str, Any]], *, now_ms: int | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Run ``actions`` on ``scene``; returns the new scene and one report line per action.

    All or nothing: raises ``NodeError`` naming the first action that cannot be
    done (``actions[2] (connect): …``); the scene passed in is never changed.
    """
    if isinstance(actions, dict):
        actions = [actions]
    if not isinstance(actions, list) or not actions:
        raise NodeError('\'actions\' must be a list of 1 to 200 actions like {"do": "add", ...}.')
    if len(actions) > MAX_ACTIONS:
        raise NodeError(
            f"One call takes at most {MAX_ACTIONS} actions; split them over several calls."
        )
    board = _Board(scene, now_ms if now_ms is not None else el.now_millis())
    runner = _Actions(board)
    report: list[str] = []
    for position, action in enumerate(actions):
        if not isinstance(action, dict):
            raise NodeError(
                f'actions[{position}] must be an object like {{"do": "add", ...}}. '
                "Nothing was changed."
            )
        name = (
            str(action.get("do") or action.get("action") or action.get("op") or "").strip().lower()
        )
        name = _ACTION_ALIASES.get(name, name)
        if name not in ACTIONS:
            raise NodeError(
                f"actions[{position}]: 'do' must be one of {', '.join(ACTIONS)} "
                f"(got {str(name)[:30]!r}). Nothing was changed."
            )
        try:
            report.append(f"{position}: {getattr(runner, name)(action)}")
        except NodeError as exc:
            raise NodeError(f"actions[{position}] ({name}): {exc} Nothing was changed.") from None
        except ValueError as exc:  # _Problem and the element helpers' ValueError
            text = str(exc).rstrip(".")
            raise NodeError(f"actions[{position}] ({name}): {text}. Nothing was changed.") from None
    result = board.finish()
    try:
        clean = _normalize(result)
    except NodeError as exc:
        raise NodeError(f"{exc} Nothing was changed.") from None
    return clean, report


def _round_box(item: dict[str, Any]) -> list[int]:
    x0, y0, x1, y1 = el.box_of(item)
    return [round(x0), round(y0), round(x1 - x0), round(y1 - y0)]


def describe(
    scene: dict[str, Any],
    *,
    ids: list[str] | None = None,
    raw: bool = False,
    query: str | None = None,
) -> dict[str, Any]:
    """A compact reading of a board for a model.

    Every live element except labels (they are their container's ``label``):
    ``id``, ``type`` (box, rect, note, ellipse, diamond, text, arrow, line,
    frame, image, drawing), ``label``, ``box`` ``[x, y, w, h]``, colours by
    palette name where they have one, ``frame``, ``groups``, and for an arrow
    ``from``/``to``. Plus the board's bounds, counts, background and grid.
    ``ids`` or ``query`` (a word in an id or a label) narrow the list; ``raw``
    gives the full element JSON of what is listed instead (labels included).
    """
    board = _Board(scene if isinstance(scene, dict) else {}, 0)
    live = board.live()
    visible = [i for i in live if not (i.get("type") == "text" and i.get("containerId"))]
    chosen = visible
    if ids:
        wanted = set(ids)
        chosen = [i for i in visible if i["id"] in wanted]
        missing = sorted(wanted - {i["id"] for i in chosen})
    else:
        missing = []
    if query:
        needle = str(query).casefold()
        chosen = [
            i
            for i in chosen
            if needle in i["id"].casefold() or needle in board.label_text(i).casefold()
        ]
    counts: dict[str, int] = {}
    for item in visible:
        name = _describe_type(item)
        counts[name] = counts.get(name, 0) + 1
    rects = [el.box_of(i) for i in live]
    found = lay.bounds(rects)
    summary: dict[str, Any] = {
        "bounds": [round(v) for v in found] if found else None,
        "counts": counts,
        "elements_total": len(visible),
        "background": board.app.get("viewBackgroundColor", el.WHITE),
        "grid": bool(board.app.get("gridModeEnabled")),
    }
    if missing:
        summary["not_found"] = missing
    if raw:
        listed: list[dict[str, Any]] = []
        for item in chosen[:RAW_LIMIT]:
            listed.append(item)
            label = board.label_of(item)
            if label is not None:
                listed.append(label)
        summary["raw"] = listed
        if len(chosen) > RAW_LIMIT:
            summary["more"] = f"{len(chosen) - RAW_LIMIT} more; narrow with 'ids' or 'query'"
        return summary
    out: list[dict[str, Any]] = []
    for item in chosen[:DESCRIBE_LIMIT]:
        entry: dict[str, Any] = {"id": item["id"], "type": _describe_type(item)}
        caption = board.label_text(item)
        if caption:
            entry["label"] = caption if len(caption) <= 300 else caption[:300] + "…"
        entry["box"] = _round_box(item)
        kind = item.get("type")
        if kind in ("arrow", "line"):
            for side, key in (("startBinding", "from"), ("endBinding", "to")):
                bound = item.get(side)
                if bound:
                    entry[key] = bound.get("elementId")
            if item.get("strokeStyle") not in (None, "solid"):
                entry["style"] = item["strokeStyle"]
            heads = (item.get("startArrowhead"), item.get("endArrowhead"))
            if kind == "arrow" and heads != (None, "arrow"):
                entry["heads"] = [h or "none" for h in heads]
        if kind not in ("frame", "image") and item.get("strokeColor") not in (el.BLACK, None):
            entry["stroke"] = el.color_name(item["strokeColor"])
        if item.get("backgroundColor") not in (el.TRANSPARENT, None) and kind not in (
            "text",
            "arrow",
            "line",
        ):
            entry["fill"] = el.color_name(item["backgroundColor"])
        if kind == "text":
            entry["size"] = item.get("fontSize")
        if item.get("frameId"):
            entry["frame"] = item["frameId"]
        if item.get("groupIds"):
            entry["groups"] = item["groupIds"]
        if item.get("locked"):
            entry["locked"] = True
        if item.get("link"):
            entry["link"] = item["link"]
        if kind == "image":
            entry["file"] = item.get("fileId")
        out.append(entry)
    summary["elements"] = out
    if len(chosen) > DESCRIBE_LIMIT:
        summary["more"] = f"{len(chosen) - DESCRIBE_LIMIT} more; narrow with 'ids' or 'query'"
    return summary


def _describe_type(item: dict[str, Any]) -> str:
    kind = item.get("type", "")
    if kind == "rectangle":
        if _looks_like_note(item):
            return "note"
        return "box" if item.get("roundness") else "rect"
    return _FRIENDLY.get(kind, kind)


__all__ = ["ACTIONS", "MAX_ACTIONS", "apply_actions", "describe"]
