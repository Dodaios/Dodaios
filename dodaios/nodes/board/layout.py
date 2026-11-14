"""Where things go on a whiteboard: automatic layouts and free places.

Why the assistant does not send coordinates for everything: a model that
writes positions produces boards that overlap, drift off a grid and have to be
redrawn whenever one box is added. So the model says WHAT is on the board and
how it is connected, and this module decides where it sits:

* ``grid``: equal cells in reading order, for a set of notes or cards.
* ``flow``: layered along the arrows (left to right, top to bottom, or the
  reverse), each step centred on the steps that lead to it. A loop back to an
  earlier step is left out of the layering, so a process reads in the
  direction it was written.
* ``tree``: a hierarchy, each parent centred over its children.
* ``mindmap``: a centre with its branches spread to both sides.
* ``pack``: blocks (a frame, a flow, a grid) in rows of a landscape shape.
* ``free_spot``: a place for something new that overlaps nothing, right of
  the content or next to a given element.

The layered flow, the grid and the row packing came from the first
whiteboard renderer, which laid out its own grammar; they work on plain boxes
here so the scene's actions, the diagrams and the old grammar share them.
All functions are pure: they set ``x``/``y`` on the boxes they get and touch
nothing else. Every position is snapped to the editor's 20 px grid.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

#: The editor's grid step; positions and sizes the assistant makes sit on it.
GRID: Final[float] = 20.0
#: Between two shapes along a flow, and across it.
FLOW_GAP: Final[float] = 80.0
FLOW_GAP_LABELED: Final[float] = 140.0
CROSS_GAP: Final[float] = 40.0
#: Between cells of a grid of notes.
GRID_GAP: Final[float] = 20.0
#: Between blocks (frames, flows) packed into rows, and between the rows.
BLOCK_GAP: Final[float] = 80.0
ROW_GAP: Final[float] = 80.0
#: The window a board is packed for, and the zoom at which it is still readable.
SHEET: Final[tuple[float, float]] = (1440.0, 860.0)
READABLE_ZOOM: Final[float] = 0.66
#: The clearance kept around existing content when something new is placed.
CLEARANCE: Final[float] = 40.0

DIRECTIONS: Final[tuple[str, ...]] = ("LR", "RL", "TB", "BT")
KINDS: Final[tuple[str, ...]] = ("grid", "flow", "tree", "mindmap")

Rect = tuple[float, float, float, float]


@dataclass
class Box:
    """One thing to place: its size, and the top-left corner a layout gives it.

    ``top`` is room the box needs above itself (a frame's name).
    """

    key: str
    w: float
    h: float
    x: float = 0.0
    y: float = 0.0
    top: float = 0.0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def rect(self) -> Rect:
        return (self.x, self.y - self.top, self.x + self.w, self.y + self.h)


def snap(value: float, grid: float = GRID) -> float:
    return round(value / grid) * grid if grid > 0 else value


def direction_of(value: object, default: str = "LR") -> str:
    """A layout direction from what a model or Mermaid says (``TD`` is ``TB``)."""
    name = str(value or "").strip().upper()
    name = {
        "TD": "TB",
        "DOWN": "TB",
        "UP": "BT",
        "RIGHT": "LR",
        "LEFT": "RL",
        "HORIZONTAL": "LR",
        "VERTICAL": "TB",
    }.get(name, name)
    return name if name in DIRECTIONS else default


# --- graph helpers -------------------------------------------------------------------


def layers(ids: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    """Longest-path layering: every link points to a later layer where it can.

    The links are taken in the order given, and one that would close a cycle
    with the links before it is left out of the layering (it is still drawn).
    """
    after: dict[str, list[str]] = {name: [] for name in ids}
    forward: list[tuple[str, str]] = []
    for start, end in edges:
        if start not in after or end not in after or start == end:
            continue
        seen = {end}
        trail = [end]
        while trail and start not in seen:
            for target in after[trail.pop()]:
                if target not in seen:
                    seen.add(target)
                    trail.append(target)
        if start in seen:
            continue  # closes a cycle
        after[start].append(end)
        forward.append((start, end))
    before: dict[str, list[str]] = {name: [] for name in ids}
    ahead: dict[str, list[str]] = {name: [] for name in ids}
    for start, end in forward:
        before[end].append(start)
        ahead[start].append(end)
    waiting = {name: len(before[name]) for name in ids}
    ready = [name for name in ids if not waiting[name]]
    layer: dict[str, int] = {name: 0 for name in ids}
    while ready:
        name = ready.pop(0)
        for target in ahead[name]:
            layer[target] = max(layer[target], layer[name] + 1)
            waiting[target] -= 1
            if not waiting[target]:
                ready.append(target)
    # A source that only feeds a late step sits right before that step.
    for name in ids:
        if not before[name] and ahead[name]:
            layer[name] = max(0, min(layer[target] for target in ahead[name]) - 1)
    return layer


def components(ids: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    """The linked clusters among ``ids``, each in the given order, by first member."""
    root: dict[str, str] = {name: name for name in ids}

    def find(name: str) -> str:
        while root[name] != name:
            root[name] = root[root[name]]
            name = root[name]
        return name

    position = {name: index for index, name in enumerate(ids)}
    for start, end in edges:
        if start not in root or end not in root:
            continue
        a, b = find(start), find(end)
        if a != b:
            first, second = (a, b) if position[a] < position[b] else (b, a)
            root[second] = first
    groups: dict[str, list[str]] = {}
    for name in ids:
        groups.setdefault(find(name), []).append(name)
    return list(groups.values())


def _normalize(boxes: Iterable[Box]) -> tuple[float, float]:
    """Move ``boxes`` so their bounds start at (0, 0); returns width and height."""
    items = list(boxes)
    if not items:
        return 0.0, 0.0
    min_x = min(b.x for b in items)
    min_y = min(b.y - b.top for b in items)
    for b in items:
        b.x -= min_x
        b.y -= min_y
    return max(b.x + b.w for b in items), max(b.y + b.h for b in items)


# --- grid ----------------------------------------------------------------------------


def default_columns(count: int) -> int:
    if count <= 3:
        return max(1, count)
    return min(6, math.ceil(math.sqrt(count)))


def grid(
    boxes: list[Box], *, columns: int | None = None, gap: float = GRID_GAP
) -> tuple[float, float]:
    """``boxes`` in a grid from (0, 0): even gaps, each centred in its cell."""
    if not boxes:
        return 0.0, 0.0
    cols = max(1, min(len(boxes), columns or default_columns(len(boxes))))
    rows = [boxes[start : start + cols] for start in range(0, len(boxes), cols)]
    col_w = [max((row[c].w for row in rows if c < len(row)), default=0.0) for c in range(cols)]
    top = 0.0
    for row in rows:
        row_h = max(b.h + b.top for b in row)
        left = 0.0
        for c, b in enumerate(row):
            b.x = left + (col_w[c] - b.w) / 2
            b.y = top + b.top + (row_h - b.h - b.top) / 2
            left += col_w[c] + gap
        top += row_h + gap
    return _normalize(boxes)


# --- flow ----------------------------------------------------------------------------


def flow(
    boxes: list[Box],
    edges: list[tuple[str, str]],
    *,
    direction: str = "LR",
    gap: float = FLOW_GAP,
    cross_gap: float = CROSS_GAP,
) -> tuple[float, float]:
    """Linked boxes in layers along ``direction``, each centred on what feeds it."""
    if not boxes:
        return 0.0, 0.0
    horizontal = direction in ("LR", "RL")

    def main(b: Box) -> float:
        return b.w if horizontal else b.h + b.top

    def cross(b: Box) -> float:
        return b.h + b.top if horizontal else b.w

    ids = [b.key for b in boxes]
    by_key = {b.key: b for b in boxes}
    layer = layers(ids, edges)
    feeds: dict[str, list[str]] = {name: [] for name in ids}
    for start, end in edges:
        if start in layer and end in layer and layer[start] < layer[end]:
            feeds[end].append(start)
    columns: dict[int, list[Box]] = {}
    for b in boxes:
        columns.setdefault(layer[b.key], []).append(b)
    pos_main: dict[str, float] = {}
    pos_cross: dict[str, float] = {}
    left = 0.0
    first = min(columns)
    for number in sorted(columns):
        column = columns[number]
        col_m = max(main(b) for b in column)
        wish: dict[str, float | None] = {}
        for b in column:
            sources = [pos_cross[k] + cross(by_key[k]) / 2 for k in feeds[b.key] if k in pos_cross]
            wish[b.key] = sum(sources) / len(sources) if sources else None
        ranked = sorted(
            enumerate(column),
            key=lambda pair: (wish[pair[1].key] is None, wish[pair[1].key] or 0.0, pair[0]),
        )
        bottom: float | None = None
        drift: list[float] = []
        placed: list[Box] = []
        for _, b in ranked:
            centre = wish[b.key]
            size = cross(b)
            if centre is not None:
                begin = centre - size / 2
            else:
                begin = 0.0 if bottom is None else bottom + cross_gap
            if bottom is not None:
                begin = max(begin, bottom + cross_gap)
            if centre is not None:
                drift.append(centre - (begin + size / 2))
            pos_main[b.key] = left + (col_m - main(b)) / 2
            pos_cross[b.key] = begin
            placed.append(b)
            bottom = begin + size
        if number == first:
            span = pos_cross[placed[-1].key] + cross(placed[-1]) - pos_cross[placed[0].key]
            shift = -span / 2 - pos_cross[placed[0].key]
        else:
            shift = sum(drift) / len(drift) if drift else 0.0
        for b in placed:
            pos_cross[b.key] += shift
        left += col_m + gap
    total_main = left - gap
    for b in boxes:
        m = pos_main[b.key]
        if direction in ("RL", "BT"):
            m = total_main - m - main(b)
        if horizontal:
            b.x, b.y = m, pos_cross[b.key] + b.top
        else:
            b.x, b.y = pos_cross[b.key], m + b.top
    return _normalize(boxes)


# --- tree and mind map -------------------------------------------------------------------


def _forest(
    ids: list[str], edges: list[tuple[str, str]], roots: list[str]
) -> tuple[list[str], dict[str, list[str]]]:
    """Roots and children of a spanning forest along ``edges`` (first parent wins)."""
    children: dict[str, list[str]] = {name: [] for name in ids}
    outgoing: dict[str, list[str]] = {name: [] for name in ids}
    incoming: set[str] = set()
    for start, end in edges:
        if start in outgoing and end in outgoing and start != end:
            outgoing[start].append(end)
            incoming.add(end)
    order = [r for r in roots if r in children]
    order += [name for name in ids if name not in incoming and name not in order]
    seen: set[str] = set()
    tops: list[str] = []
    pending = list(order) + [name for name in ids if name not in order]
    for start in pending:
        if start in seen:
            continue
        tops.append(start)
        seen.add(start)
        queue = [start]
        while queue:
            node = queue.pop(0)
            for target in outgoing[node]:
                if target not in seen:
                    seen.add(target)
                    children[node].append(target)
                    queue.append(target)
    return tops, children


def _tree_place(
    tops: list[str],
    children: dict[str, list[str]],
    main_size: dict[str, float],
    cross_size: dict[str, float],
    *,
    gap: float,
    cross_gap: float,
) -> tuple[dict[str, float], dict[str, float]]:
    """Main and cross positions (top-left) for a forest, each parent centred on its children."""
    depth: dict[str, int] = {}

    def walk(node: str, level: int) -> None:
        depth[node] = level
        for child in children[node]:
            walk(child, level + 1)

    for top in tops:
        walk(top, 0)
    level_size: dict[int, float] = {}
    for node, level in depth.items():
        level_size[level] = max(level_size.get(level, 0.0), main_size[node])
    level_at: dict[int, float] = {}
    offset = 0.0
    for level in sorted(level_size):
        level_at[level] = offset
        offset += level_size[level] + gap

    span: dict[str, float] = {}

    def measure(node: str) -> float:
        kids = children[node]
        inner = sum(measure(child) for child in kids) + cross_gap * max(0, len(kids) - 1)
        span[node] = max(cross_size[node], inner)
        return span[node]

    pos_main: dict[str, float] = {}
    pos_cross: dict[str, float] = {}

    def place(node: str, start: float) -> None:
        pos_cross[node] = start + (span[node] - cross_size[node]) / 2
        level = depth[node]
        pos_main[node] = level_at[level] + (level_size[level] - main_size[node]) / 2
        kids = children[node]
        inner = sum(span[child] for child in kids) + cross_gap * max(0, len(kids) - 1)
        cursor = start + (span[node] - inner) / 2
        for child in kids:
            place(child, cursor)
            cursor += span[child] + cross_gap

    cursor = 0.0
    for top in tops:
        measure(top)
        place(top, cursor)
        cursor += span[top] + cross_gap * 2
    return pos_main, pos_cross


def tree(
    boxes: list[Box],
    edges: list[tuple[str, str]],
    *,
    direction: str = "TB",
    gap: float = FLOW_GAP,
    cross_gap: float = CROSS_GAP,
    root: str | None = None,
) -> tuple[float, float]:
    """A hierarchy along ``direction``; ``root`` first, otherwise every box nothing points to."""
    if not boxes:
        return 0.0, 0.0
    horizontal = direction in ("LR", "RL")
    ids = [b.key for b in boxes]
    tops, children = _forest(ids, edges, [root] if root else [])
    main_size = {b.key: (b.w if horizontal else b.h + b.top) for b in boxes}
    cross_size = {b.key: (b.h + b.top if horizontal else b.w) for b in boxes}
    pos_main, pos_cross = _tree_place(
        tops, children, main_size, cross_size, gap=gap, cross_gap=cross_gap
    )
    total = max(pos_main[k] + main_size[k] for k in ids)
    for b in boxes:
        m = pos_main[b.key]
        if direction in ("RL", "BT"):
            m = total - m - main_size[b.key]
        if horizontal:
            b.x, b.y = m, pos_cross[b.key] + b.top
        else:
            b.x, b.y = pos_cross[b.key], m + b.top
    return _normalize(boxes)


def mindmap(
    boxes: list[Box],
    edges: list[tuple[str, str]],
    *,
    root: str | None = None,
    gap: float = FLOW_GAP,
    cross_gap: float = CROSS_GAP / 2,
) -> tuple[float, float]:
    """A centre (``root``, else the most connected box) with branches to both sides."""
    if not boxes:
        return 0.0, 0.0
    framed = any(b.top > 0 for b in boxes)
    if framed:
        # Frames side by side need the room a flow gives them, not a note's.
        cross_gap = max(cross_gap, CROSS_GAP)
    ids = [b.key for b in boxes]
    by_key = {b.key: b for b in boxes}
    if root not in by_key:
        degree = {name: 0 for name in ids}
        for start, end in edges:
            if start in degree and end in degree:
                degree[start] += 1
                degree[end] += 1
        root = max(ids, key=lambda name: (degree[name], -ids.index(name)))
    # Treat the links as undirected from the centre outwards.
    both = [*edges, *((end, start) for start, end in edges)]
    tops, children = _forest(ids, both, [root])
    centre = by_key[root]
    centre.x, centre.y = -centre.w / 2, -centre.h / 2
    branches = children[root]
    weight: dict[str, int] = {}

    def count(node: str) -> int:
        weight[node] = 1 + sum(count(child) for child in children[node])
        return weight[node]

    for branch in branches:
        count(branch)
    right: list[str] = []
    left: list[str] = []
    load = [0.0, 0.0]
    for branch in sorted(branches, key=lambda b: -weight[b]):
        side = 0 if load[0] <= load[1] else 1
        (right if side == 0 else left).append(branch)
        load[side] += weight[branch]
    right.sort(key=branches.index)
    left.sort(key=branches.index)
    for sign, members in ((1.0, right), (-1.0, left)):
        if not members:
            continue
        main_size = {k: by_key[k].w for k in ids}
        cross_size = {k: by_key[k].h + by_key[k].top for k in ids}
        pos_main, pos_cross = _tree_place(
            members, children, main_size, cross_size, gap=gap, cross_gap=cross_gap
        )
        placed = [k for k in pos_main]
        span_top = min(pos_cross[k] for k in placed)
        span_bottom = max(pos_cross[k] + cross_size[k] for k in placed)
        shift = -(span_top + span_bottom) / 2
        for k in placed:
            b = by_key[k]
            offset = centre.w / 2 + gap + pos_main[k]
            b.x = offset if sign > 0 else -offset - b.w
            b.y = pos_cross[k] + shift + b.top
    # Boxes unreachable from the centre go below, in a row.
    reached = {root, *(k for k in ids if k in _descendants(root, children))}
    loose = [by_key[k] for k in ids if k not in reached]
    if loose:
        bottom = max(b.y + b.h for b in boxes if b.key in reached) + ROW_GAP
        grid(loose, columns=min(6, len(loose)), gap=BLOCK_GAP if framed else GRID_GAP)
        left_edge = min(b.x for b in boxes if b.key in reached)
        for b in loose:
            b.x += left_edge
            b.y += bottom
    return _normalize(boxes)


def _descendants(node: str, children: dict[str, list[str]]) -> set[str]:
    out: set[str] = set()
    stack = list(children.get(node, []))
    while stack:
        current = stack.pop()
        if current in out:
            continue
        out.add(current)
        stack.extend(children.get(current, []))
    return out


# --- packing blocks ---------------------------------------------------------------------


def _rows(blocks: list[Box], limit: float, gap: float) -> list[list[Box]]:
    rows: list[list[Box]] = [[]]
    width = 0.0
    for block in blocks:
        need = block.w if not rows[-1] else width + gap + block.w
        if rows[-1] and need > limit + 0.5:
            rows.append([block])
            width = block.w
        else:
            rows[-1].append(block)
            width = need
    return rows


def _row_size(row: list[Box], gap: float) -> tuple[float, float]:
    width = sum(b.w for b in row) + gap * (len(row) - 1)
    return width, max(b.top for b in row) + max(b.h for b in row)


def pack(
    blocks: list[Box], *, gap: float = BLOCK_GAP, row_gap: float = ROW_GAP
) -> tuple[float, float]:
    """Place the blocks left to right, wrapped into rows of a landscape shape.

    Every row width that some run of neighbouring blocks would need is tried;
    the one whose board is largest when fitted into a landscape window wins,
    every board readable there counts the same, and fewer rows win a tie. So a
    board stays one row for as long as it can be read, and a wider one wraps
    where that keeps it largest.
    """
    if not blocks:
        return 0.0, 0.0
    widths = [b.w for b in blocks]
    limits: list[float] = []
    for run in range(1, len(blocks) + 1):
        window = sum(widths[:run]) + gap * (run - 1)
        widest = window
        for end in range(run, len(blocks)):
            window += widths[end] - widths[end - run]
            widest = max(widest, window)
        limits.append(widest)
    best: list[list[Box]] = []
    best_zoom = -1.0
    for limit in sorted(set(limits), reverse=True):
        rows = _rows(blocks, limit, gap)
        sizes = [_row_size(row, gap) for row in rows]
        board_w = max(size[0] for size in sizes)
        board_h = sum(size[1] for size in sizes) + row_gap * (len(rows) - 1)
        zoom = min(SHEET[0] / max(board_w, 1.0), SHEET[1] / max(board_h, 1.0), READABLE_ZOOM)
        if zoom > best_zoom + 1e-9:
            best, best_zoom = rows, zoom
    top = 0.0
    for row in best:
        title_room = max(b.top for b in row)
        left = 0.0
        for b in row:
            b.x = left
            b.y = top + title_room
            left += b.w + gap
        top += title_room + max(b.h for b in row) + row_gap
    return _normalize(blocks)


def arrange(
    boxes: list[Box],
    edges: list[tuple[str, str]],
    *,
    kind: str = "flow",
    direction: str = "LR",
    gap: float | None = None,
    columns: int | None = None,
    root: str | None = None,
) -> tuple[float, float]:
    """Lay out ``boxes`` by ``kind``; a flow lays out each linked cluster and packs them.

    Returns the size of the result, which starts at (0, 0).
    """
    keys = {b.key for b in boxes}
    edges = [(s, e) for s, e in edges if s in keys and e in keys and s != e]
    if kind == "grid":
        return grid(boxes, columns=columns, gap=gap if gap is not None else GRID_GAP)
    if kind == "tree":
        return tree(
            boxes,
            edges,
            direction=direction if direction else "TB",
            gap=gap if gap is not None else FLOW_GAP,
            root=root,
        )
    if kind == "mindmap":
        return mindmap(boxes, edges, root=root, gap=gap if gap is not None else FLOW_GAP)
    by_key = {b.key: b for b in boxes}
    linked = {name for pair in edges for name in pair}
    blocks: list[Box] = []
    members: list[list[Box]] = []
    clusters = components([b.key for b in boxes if b.key in linked], edges)
    for cluster in clusters:
        inside = set(cluster)
        parts = [by_key[k] for k in cluster]
        w, h = flow(
            parts,
            [(s, e) for s, e in edges if s in inside],
            direction=direction,
            gap=gap if gap is not None else FLOW_GAP,
        )
        blocks.append(Box(key=f"cluster:{cluster[0]}", w=w, h=h))
        members.append(parts)
    loose = [b for b in boxes if b.key not in linked]
    if loose and any(b.top > 0 for b in loose) and columns is None:
        # Frames are blocks, not notes: a grid would set them a note's gap
        # apart and centre them on each other, so neighbours almost touch and
        # their names stand at different heights. Packed, they are top-aligned
        # a block's gap apart.
        w, h = pack(loose)
        blocks.append(Box(key="loose", w=w, h=h))
        members.append(loose)
    elif loose:
        w, h = grid(loose, columns=columns)
        blocks.append(Box(key="loose", w=w, h=h))
        members.append(loose)
    if direction in ("LR", "RL") and len(blocks) > 1:
        # Flows that read sideways are stacked: one under the other.
        top = 0.0
        for block in blocks:
            block.x, block.y = 0.0, top
            top += block.h + ROW_GAP
    else:
        pack(blocks)
    for block, parts in zip(blocks, members, strict=True):
        for b in parts:
            b.x += block.x
            b.y += block.y
    return _normalize(boxes)


# --- free places -------------------------------------------------------------------------


def bounds(rects: Iterable[Rect]) -> Rect | None:
    items = list(rects)
    if not items:
        return None
    return (
        min(r[0] for r in items),
        min(r[1] for r in items),
        max(r[2] for r in items),
        max(r[3] for r in items),
    )


def overlaps(a: Rect, b: Rect, margin: float = 0.0) -> bool:
    return not (
        a[2] + margin <= b[0]
        or b[2] + margin <= a[0]
        or a[3] + margin <= b[1]
        or b[3] + margin <= a[1]
    )


def is_free(rect: Rect, occupied: Iterable[Rect], margin: float = CLEARANCE / 2) -> bool:
    return not any(overlaps(rect, other, margin) for other in occupied)


_SIDES: Final[dict[str, tuple[float, float]]] = {
    "right": (1.0, 0.0),
    "left": (-1.0, 0.0),
    "below": (0.0, 1.0),
    "above": (0.0, -1.0),
}


def _beside(anchor: Rect, w: float, h: float, side: str, gap: float) -> tuple[float, float]:
    ax0, ay0, ax1, ay1 = anchor
    acx, acy = (ax0 + ax1) / 2, (ay0 + ay1) / 2
    if side == "right":
        return ax1 + gap, acy - h / 2
    if side == "left":
        return ax0 - gap - w, acy - h / 2
    if side == "below":
        return acx - w / 2, ay1 + gap
    return acx - w / 2, ay0 - gap - h


def free_spot(
    occupied: list[Rect],
    w: float,
    h: float,
    *,
    anchor: Rect | None = None,
    side: str = "right",
    gap: float = CLEARANCE * 2,
) -> tuple[float, float]:
    """A top-left corner for a ``w`` × ``h`` thing that overlaps nothing in ``occupied``.

    With ``anchor``: on its ``side`` (``right``, ``left``, ``below``, ``above``,
    or ``near`` = the closest free of the four), centred on it, moving further
    out until free. Without: right of all content, aligned to its top, moving
    down until free. An empty board starts at (0, 0).
    """
    step = GRID
    if anchor is None:
        content = bounds(occupied)
        if content is None:
            return 0.0, 0.0
        x, y = snap(content[2] + gap), snap(content[1])
        for _ in range(2000):
            if is_free((x, y, x + w, y + h), occupied):
                return x, y
            y += step * 2
        return x, snap(content[3] + gap)
    sides = list(_SIDES) if side == "near" else [side if side in _SIDES else "right"]
    best: tuple[float, float, float] | None = None
    for name in sides:
        dx, dy = _SIDES[name]
        x, y = _beside(anchor, w, h, name, gap)
        x, y = snap(x), snap(y)
        for distance in range(400):
            cx, cy = x + dx * step * distance, y + dy * step * distance
            if is_free((cx, cy, cx + w, cy + h), occupied):
                if best is None or distance < best[0]:
                    best = (distance, cx, cy)
                break
        if best is not None and best[0] == 0:
            break
    if best is None:
        x, y = _beside(anchor, w, h, sides[0], gap)
        return snap(x), snap(y)
    return best[1], best[2]


__all__ = [
    "BLOCK_GAP",
    "CLEARANCE",
    "CROSS_GAP",
    "DIRECTIONS",
    "FLOW_GAP",
    "FLOW_GAP_LABELED",
    "GRID",
    "GRID_GAP",
    "KINDS",
    "ROW_GAP",
    "Box",
    "arrange",
    "bounds",
    "components",
    "default_columns",
    "direction_of",
    "flow",
    "free_spot",
    "grid",
    "is_free",
    "layers",
    "mindmap",
    "overlaps",
    "pack",
    "snap",
    "tree",
]
