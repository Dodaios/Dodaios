"""A board's self-check: what looks wrong on it, in a few lines a model can act on.

Why: a model that draws a board cannot see it. The layouts keep what they
place tidy, but a model also moves things by hand, sets sizes, adds a frame
next to a diagram or types a long label into a small box, and then answers
without knowing that two panels overlap or that a label spills out of its
card. So after every ``create`` and ``edit`` the whiteboard tool reads the
final scene with :func:`report` and hands back one line per problem, naming
the ids and the action that fixes it, or one line saying all is fine.

What it looks for:

* things that overlap (at the top level of the board, or inside one frame);
* a label that does not fit its box;
* an element that sticks out of its frame (the editor clips it there);
* frames side by side in one row whose tops differ;
* a box far larger than its label needs;
* an arrow that passes through a shape it does not join.

Only problems that involve something the call created or changed are named
(``focus``): the person's own drawing is theirs, and a line about it every
turn would be noise. Sizes of text are the same estimates the layouts use
(:mod:`.elements`), which lean wide, so a box the assistant sized never fails
its own check.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Final

from dodaios.nodes.board import convert as cv
from dodaios.nodes.board import elements as el

#: Most problem lines one report names; the rest are counted.
MAX_LINES: Final[int] = 8
#: Pixels two things may touch before they count as overlapping.
_TOUCH: Final[float] = 2.0
#: How much of a shape an arrow may graze at its edge without "passing through".
_GRAZE: Final[float] = 6.0
_SHAPES: Final[frozenset[str]] = frozenset({"rectangle", "ellipse", "diamond"})
_SOLID: Final[frozenset[str]] = frozenset({"rectangle", "ellipse", "diamond", "image", "text"})

Rect = tuple[float, float, float, float]


def changed_ids(before: dict[str, Any] | None, after: dict[str, Any]) -> set[str]:
    """Ids of the live elements of ``after`` that are new or have a new version."""
    old = {
        e.get("id"): e.get("version")
        for e in (before or {}).get("elements") or []
        if isinstance(e, dict) and not e.get("isDeleted")
    }
    return {
        str(e["id"])
        for e in after.get("elements") or []
        if isinstance(e, dict)
        and e.get("id")
        and not e.get("isDeleted")
        and (e["id"] not in old or old[e["id"]] != e.get("version"))
    }


def problems(scene: dict[str, Any], focus: Iterable[str] | None = None) -> list[str]:
    """One line per problem on ``scene`` that involves an element in ``focus``
    (every element when ``focus`` is ``None``)."""
    live = [
        e
        for e in scene.get("elements") or []
        if isinstance(e, dict) and e.get("id") and not e.get("isDeleted")
    ]
    by_id = {e["id"]: e for e in live}
    labels = {e["containerId"]: e for e in live if e.get("type") == "text" and e.get("containerId")}
    wanted = None if focus is None else set(focus)

    def seen(*ids: str | None) -> bool:
        if wanted is None:
            return True
        for ident in ids:
            if not ident:
                continue
            if ident in wanted:
                return True
            label = labels.get(ident)
            if label is not None and label["id"] in wanted:
                return True
        return False

    units = [
        e
        for e in live
        if e.get("type") not in ("arrow", "line", "freedraw")
        and not (e.get("type") == "text" and e.get("containerId"))
    ]
    lines: list[str] = []
    lines += _overlaps(units, seen)
    lines += _label_fit(units, labels, seen)
    lines += _outside_frames(live, by_id, seen)
    lines += _frame_rows(units, seen)
    lines += _oversized(units, labels, seen)
    lines += _arrows_through(live, units, by_id, seen)
    return lines


def report(scene: dict[str, Any], focus: Iterable[str] | None = None) -> str:
    """The ``Check:`` section of a tool result: the problems, or that there are none."""
    found = problems(scene, focus)
    if not found:
        return "Check: all clear (no overlaps, labels fit, frames aligned)."
    head = (
        f"Check: {len(found)} issue{'s' if len(found) != 1 else ''}; fix "
        f"{'them' if len(found) != 1 else 'it'} with one more 'edit' before you answer:"
    )
    shown = [f"- {line}" for line in found[:MAX_LINES]]
    if len(found) > MAX_LINES:
        shown.append(f"- and {len(found) - MAX_LINES} more of the same kinds.")
    return "\n".join([head, *shown])


# --- the checks ------------------------------------------------------------------------


def _rect(item: dict[str, Any]) -> Rect:
    """What an element covers; a frame's name above it counts."""
    x0, y0, x1, y1 = el.box_of(item)
    if item.get("type") == "frame":
        y0 -= cv.FRAME_NAME_ROOM
    return x0, y0, x1, y1


def _overlap(a: Rect, b: Rect) -> tuple[float, float]:
    return min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])


def _overlaps(units: list[dict[str, Any]], seen: Any) -> list[str]:
    out: list[str] = []
    siblings: dict[str | None, list[dict[str, Any]]] = {}
    for item in units:
        holder = item.get("frameId") if item.get("type") != "frame" else None
        siblings.setdefault(holder, []).append(item)
    for members in siblings.values():
        rects = [(m, _rect(m)) for m in members[:400]]
        for i, (a, ra) in enumerate(rects):
            for b, rb in rects[i + 1 :]:
                if not seen(a["id"], b["id"]):
                    continue
                if set(a.get("groupIds") or []) & set(b.get("groupIds") or []):
                    continue  # grouped on purpose
                dx, dy = _overlap(ra, rb)
                if dx > _TOUCH and dy > _TOUCH:
                    mover = b if seen(b["id"]) else a
                    other = a if mover is b else b
                    out.append(
                        f"overlap: {a['id']} and {b['id']} overlap by {round(dx)}x{round(dy)} px; "
                        f"move {mover['id']} (move below/right_of {other['id']}) or run layout."
                    )
    return out


def _label_fit(
    units: list[dict[str, Any]], labels: dict[str, dict[str, Any]], seen: Any
) -> list[str]:
    out: list[str] = []
    for item in units:
        label = labels.get(item["id"])
        if label is None or item.get("type") not in _SHAPES or not seen(item["id"]):
            continue
        size = float(label.get("fontSize") or el.DEFAULT_FONT_SIZE)
        family = int(label.get("fontFamily") or el.DEFAULT_FONT)
        width, height = float(item.get("width") or 0), float(item.get("height") or 0)
        room_w, room_h = el.label_room(item["type"], width, height)
        original = str(label.get("originalText") or "")
        wrapped = el.wrap_text(original, max(room_w, size), size, family)
        _, need_h = el.estimate_text(wrapped, size, family)
        if need_h > room_h + _TOUCH:
            _, total_h = el.container_for_text(item["type"], room_w, need_h)
            out.append(
                f"label does not fit: {item['id']} is {round(width)}x{round(height)} but its "
                f"label needs ~{round(need_h)} px of height; resize {item['id']} "
                f"h={round(el.snap_up(total_h + 16, 20))} or shorten the label."
            )
    return out


def _outside_frames(live: list[dict[str, Any]], by_id: dict[str, Any], seen: Any) -> list[str]:
    out: list[str] = []
    for item in live:
        holder = by_id.get(item.get("frameId") or "")
        if holder is None or holder.get("type") != "frame":
            continue
        if item.get("type") == "text" and item.get("containerId"):
            continue
        if not seen(item["id"], holder["id"]):
            continue
        x0, y0, x1, y1 = el.box_of(item)
        fx0, fy0, fx1, fy1 = el.box_of(holder)
        spill = max(fx0 - x0, fy0 - y0, x1 - fx1, y1 - fy1)
        if spill > _TOUCH:
            out.append(
                f"outside its frame: {item['id']} sticks out of frame {holder['id']} by "
                f"{round(spill)} px (the editor clips it); move it inside or run "
                f"layout with frame {holder['id']}."
            )
    return out


def _frame_rows(units: list[dict[str, Any]], seen: Any) -> list[str]:
    frames = sorted(
        (u for u in units if u.get("type") == "frame"), key=lambda f: float(f.get("x") or 0)
    )
    rows: list[list[dict[str, Any]]] = []
    for frame in frames:
        _, fy0, _, fy1 = el.box_of(frame)
        home = None
        for row in rows:
            for other in row:
                ox0, oy0, ox1, oy1 = el.box_of(other)
                fx0, _, fx1, _ = el.box_of(frame)
                side_by_side = fx0 >= ox1 - _TOUCH or ox0 >= fx1 - _TOUCH
                shared = min(fy1, oy1) - max(fy0, oy0)
                if side_by_side and shared > 0.5 * min(fy1 - fy0, oy1 - oy0):
                    home = row
                    break
            if home is not None:
                break
        if home is None:
            rows.append([frame])
        else:
            home.append(frame)
    out: list[str] = []
    for row in rows:
        tops = {round(float(f.get("y") or 0)) for f in row}
        if len(row) < 2 or len(tops) < 2 or not seen(*(f["id"] for f in row)):
            continue
        ids = [f["id"] for f in row]
        out.append(
            f"frames not aligned: {', '.join(ids)} stand in one row but their tops differ "
            f"({', '.join(str(t) for t in sorted(tops))}); align ids {ids} to top, or lay "
            "them out with layout kind grid."
        )
    return out


def _kind_of_shape(item: dict[str, Any]) -> str:
    kind = item.get("type")
    if kind == "ellipse":
        return "ellipse"
    if kind == "diamond":
        return "diamond"
    fill = str(item.get("backgroundColor") or "").lower()
    if float(item.get("strokeWidth") or 2) <= 1 and any(
        fill == shades[el.FILL_SHADE] for shades in el.PALETTE.values()
    ):
        return "note"
    return "box"


def _oversized(
    units: list[dict[str, Any]], labels: dict[str, dict[str, Any]], seen: Any
) -> list[str]:
    out: list[str] = []
    for item in units:
        label = labels.get(item["id"])
        if label is None or item.get("type") not in _SHAPES or not seen(item["id"]):
            continue
        text = str(label.get("originalText") or "").strip()
        if not text:
            continue
        kind = _kind_of_shape(item)
        style = {
            "size": float(label.get("fontSize") or el.DEFAULT_FONT_SIZE),
            "font": int(label.get("fontFamily") or el.DEFAULT_FONT),
        }
        width, height = float(item.get("width") or 0), float(item.get("height") or 0)
        need_w, _ = cv.node_size(kind, text, style)
        _, need_h = cv.node_size(kind, text, style, width=width)
        tall = height >= 2 * need_h and height - need_h >= 80
        wide = width >= 2 * need_w and width - need_w >= 160
        if tall or wide:
            out.append(
                f"too big for its label: {item['id']} is {round(width)}x{round(height)}, its "
                f"label needs about {round(min(width, need_w) if wide else width)}x"
                f"{round(need_h)}; resize it (or give it more to say)."
            )
    return out


def _arrows_through(
    live: list[dict[str, Any]], units: list[dict[str, Any]], by_id: dict[str, Any], seen: Any
) -> list[str]:
    out: list[str] = []
    solids = [u for u in units if u.get("type") in _SOLID]
    for arrow in live:
        if arrow.get("type") not in ("arrow", "line") or len(arrow.get("points") or []) < 2:
            continue
        ends = {(arrow.get(side) or {}).get("elementId") for side in ("startBinding", "endBinding")}
        ends.discard(None)
        points = el.absolute_points(arrow)
        hit: list[str] = []
        for shape in solids:
            if shape["id"] in ends or not seen(arrow["id"], shape["id"]):
                continue
            x0, y0, x1, y1 = el.box_of(shape)
            if x1 - x0 <= 2 * _GRAZE or y1 - y0 <= 2 * _GRAZE:
                continue
            inner = (x0 + _GRAZE, y0 + _GRAZE, x1 - _GRAZE, y1 - _GRAZE)
            segments = zip(points, points[1:], strict=False)
            if any(cv._segment_hits(p, q, inner) for p, q in segments):
                hit.append(shape["id"])
        if hit:
            out.append(
                f"arrow through a shape: {arrow['id']} passes through {', '.join(hit[:4])}; "
                "move what is in the way or run layout so the arrow runs clear."
            )
    return out


__all__ = ["MAX_LINES", "changed_ids", "problems", "report"]
