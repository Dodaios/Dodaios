/**
 * The hands on the slide: selecting, moving, resizing and rotating the free
 * elements, as in a presentation program.
 *
 * The slide itself is drawn by `SlideCanvas` + `SlideView` inside a shadow
 * root; this component wraps it and draws the selection on top, in the
 * light DOM, in canvas pixels (slide pixels times `k`):
 *
 * * a click on an element selects it (Shift or Cmd/Ctrl adds or removes),
 *   a drag moves the selection, snapping to the slide's edges and middle and
 *   to the other elements (guides show where; Alt drags freely);
 * * the eight handles resize (Shift keeps the proportions, rotation is
 *   respected), the round handle above rotates (Shift: 15° steps), a line
 *   has a handle at each end;
 * * a drag on the empty slide draws a selection frame;
 * * a double click writes into a text box, a shape or a table, opens a
 *   chart's editor or replaces a picture;
 * * the keys: arrows nudge (Shift: 10 px), Delete removes, Cmd/Ctrl+D
 *   duplicates, Cmd/Ctrl+A selects all, Enter writes, Escape lets go,
 *   Cmd/Ctrl+] and [ move forward and back (with Shift: to the front, back).
 *
 * A drag is one undo step: every move of the pointer replaces the previous
 * one in the same step, computed from where the drag began, so nothing drifts.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";

import {
  boundsOf,
  elementKey,
  hasText,
  placeIn,
  round1,
  SLIDE_H,
  SLIDE_W,
  translate,
  unionOf,
  type LineElement,
  type Rect,
  type SlideElement,
} from "./elementModel";

/** A change to the slide's elements: one labelled undo step (`coalesce` merges a drag's moves). */
export type ElementsChange = (label: string, change: (elements: SlideElement[]) => void, coalesce?: string) => void;

export interface CanvasEditorProps {
  elements: readonly SlideElement[];
  /** Canvas width in px; the slide's scale is width / 1280. */
  width: number;
  selection: readonly string[];
  onSelect: (keys: string[]) => void;
  writing: number;
  onWrite: (index: number) => void;
  onChange: ElementsChange;
  /** Double click on a chart or a picture. */
  onOpenElement: (index: number) => void;
  onContextMenu: (at: { x: number; y: number }, index: number | null) => void;
  /** Labels for the undo steps. */
  labels: { move: string; resize: string; rotate: string; nudge: string };
  /** Snap to edges, middles and other elements. */
  snap: boolean;
  /** Show the layout grid. */
  grid: boolean;
  children: ReactNode;
}

type Handle = "nw" | "n" | "ne" | "e" | "se" | "s" | "sw" | "w";
const HANDLES: readonly Handle[] = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
const HANDLE_DIR: Record<Handle, [number, number]> = {
  nw: [-1, -1],
  n: [0, -1],
  ne: [1, -1],
  e: [1, 0],
  se: [1, 1],
  s: [0, 1],
  sw: [-1, 1],
  w: [-1, 0],
};
const HANDLE_CURSOR: Record<Handle, string> = {
  nw: "nwse-resize",
  se: "nwse-resize",
  ne: "nesw-resize",
  sw: "nesw-resize",
  n: "ns-resize",
  s: "ns-resize",
  e: "ew-resize",
  w: "ew-resize",
};

type Drag =
  | { kind: "move"; startX: number; startY: number; moved: boolean; snapshot: Map<number, SlideElement>; id: string; duplicate: boolean }
  | { kind: "resize"; handle: Handle; startX: number; startY: number; snapshot: Map<number, SlideElement>; id: string }
  | { kind: "rotate"; index: number; cx: number; cy: number; id: string; snapshot: SlideElement }
  | { kind: "end"; index: number; which: 1 | 2; id: string; snapshot: LineElement }
  | { kind: "marquee"; startX: number; startY: number; add: string[] };

interface Guide {
  axis: "x" | "y";
  at: number;
}

/** The element at the start of an event's path inside the slide (its `data-el` box). */
function elementIndexOf(event: Event): number | null {
  for (const node of event.composedPath()) {
    if (!(node instanceof Element)) continue;
    if (node.hasAttribute("data-el")) return Number(node.getAttribute("data-el"));
    if (node.classList.contains("sl")) return null;
  }
  return null;
}

/** Whether the event happened in a text field of the layout (the canvas's own writing). */
function inField(event: Event): boolean {
  for (const node of event.composedPath()) {
    if (!(node instanceof HTMLElement)) continue;
    if (node.isContentEditable) return true;
    if (node.classList.contains("sl")) return false;
  }
  return false;
}

function rad(deg: number): number {
  return (deg * Math.PI) / 180;
}

/** Where an element of a drag's start is in the list now (it may have moved by a removal). */
function placeOf(list: readonly SlideElement[], index: number, original: SlideElement): number {
  if (original.id && list[index]?.id !== original.id) {
    const found = list.findIndex((element) => element.id === original.id);
    if (found >= 0) return found;
  }
  return index;
}

let dragCounter = 0;

export function CanvasEditor({
  elements,
  width,
  selection,
  onSelect,
  writing,
  onWrite,
  onChange,
  onOpenElement,
  onContextMenu,
  labels,
  snap,
  grid,
  children,
}: CanvasEditorProps) {
  const k = Math.max(1, Math.round(width)) / SLIDE_W;
  const height = Math.round(SLIDE_H * k);
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const [guides, setGuides] = useState<Guide[]>([]);
  const [marquee, setMarquee] = useState<Rect | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);

  const keys = useMemo(() => elements.map((element, index) => elementKey(element, index)), [elements]);
  const selected = useMemo(
    () => keys.map((key, index) => (selection.includes(key) ? index : -1)).filter((index) => index >= 0),
    [keys, selection],
  );
  const latest = useRef({ elements, selected, keys });
  latest.current = { elements, selected, keys };

  /** A pointer position in slide pixels. */
  const toSlide = useCallback(
    (clientX: number, clientY: number) => {
      const rect = box.current?.getBoundingClientRect();
      if (!rect) return { x: 0, y: 0 };
      return { x: (clientX - rect.left) / k, y: (clientY - rect.top) / k };
    },
    [k],
  );

  /** Where the boxes of the other elements and the slide's edges and middle are. */
  const targets = useCallback((exclude: readonly number[]) => {
    const xs = [0, SLIDE_W / 2, SLIDE_W];
    const ys = [0, SLIDE_H / 2, SLIDE_H];
    latest.current.elements.forEach((element, index) => {
      if (exclude.includes(index)) return;
      const b = boundsOf(element);
      xs.push(b.x, b.x + b.w / 2, b.x + b.w);
      ys.push(b.y, b.y + b.h / 2, b.y + b.h);
    });
    return { xs, ys };
  }, []);

  /** The shift that snaps a box (its edges and middle) to the nearest target, per axis. */
  const snapRect = useCallback(
    (rect: Rect, exclude: readonly number[], free: boolean): { dx: number; dy: number; found: Guide[] } => {
      if (!snap || free) return { dx: 0, dy: 0, found: [] };
      const { xs, ys } = targets(exclude);
      const limit = 6 / k;
      const best = (values: number[], points: number[]) => {
        let pick: { diff: number; at: number } | null = null;
        for (const value of values)
          for (const point of points) {
            const diff = point - value;
            if (Math.abs(diff) <= limit && (!pick || Math.abs(diff) < Math.abs(pick.diff))) pick = { diff, at: point };
          }
        return pick;
      };
      const x = best([rect.x, rect.x + rect.w / 2, rect.x + rect.w], xs);
      const y = best([rect.y, rect.y + rect.h / 2, rect.y + rect.h], ys);
      const found: Guide[] = [];
      if (x) found.push({ axis: "x", at: x.at });
      if (y) found.push({ axis: "y", at: y.at });
      return { dx: x?.diff ?? 0, dy: y?.diff ?? 0, found };
    },
    [k, snap, targets],
  );

  // --- the pointer -----------------------------------------------------------------------

  const startDrag = (next: Drag, event: ReactPointerEvent) => {
    drag.current = next;
    setDragging(true);
    try {
      box.current?.setPointerCapture(event.pointerId);
    } catch {
      /* the pointer is gone already */
    }
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    const native = event.nativeEvent;
    const index = elementIndexOf(native);
    const at = toSlide(event.clientX, event.clientY);
    if (index !== null && index === writing) return;
    if (index !== null && elements[index]) {
      const key = keys[index];
      const toggle = event.shiftKey || event.metaKey || event.ctrlKey;
      let next = selection.includes(key) ? [...selection] : [key];
      if (toggle) next = selection.includes(key) ? selection.filter((s) => s !== key) : [...selection, key];
      onSelect(next);
      if (writing >= 0) onWrite(-1);
      event.preventDefault();
      box.current?.focus({ preventScroll: true });
      if (toggle || elements[index].locked) return;
      const snapshot = new Map<number, SlideElement>();
      next.forEach((k2) => {
        const i = keys.indexOf(k2);
        if (i >= 0 && !elements[i].locked) snapshot.set(i, elements[i]);
      });
      startDrag({ kind: "move", startX: at.x, startY: at.y, moved: false, snapshot, id: `move:${++dragCounter}`, duplicate: event.altKey }, event);
      return;
    }
    if (writing >= 0) onWrite(-1);
    if (inField(native)) {
      if (selection.length) onSelect([]);
      return;
    }
    // The empty slide: a selection frame.
    event.preventDefault();
    box.current?.focus({ preventScroll: true });
    const add = event.shiftKey ? [...selection] : [];
    if (!event.shiftKey && selection.length) onSelect([]);
    startDrag({ kind: "marquee", startX: at.x, startY: at.y, add }, event);
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    const at = toSlide(event.clientX, event.clientY);
    if (!current) {
      const index = elementIndexOf(event.nativeEvent);
      setHover(index);
      return;
    }
    if (current.kind === "move") {
      let dx = at.x - current.startX;
      let dy = at.y - current.startY;
      if (!current.moved && Math.hypot(dx, dy) * k < 3) return;
      current.moved = true;
      if (event.shiftKey) {
        // Along one axis only.
        if (Math.abs(dx) > Math.abs(dy)) dy = 0;
        else dx = 0;
      }
      const indices = [...current.snapshot.keys()];
      const start = unionOf(indices.map((i) => boundsOf(current.snapshot.get(i)!)));
      if (!start) return;
      const snapped = snapRect({ ...start, x: start.x + dx, y: start.y + dy }, indices, event.altKey);
      dx += snapped.dx;
      dy += snapped.dy;
      setGuides(snapped.found);
      onChange(
        labels.move,
        (list) => {
          current.snapshot.forEach((original, i) => {
            const at = placeOf(list, i, original);
            if (!list[at]) return;
            const moved = JSON.parse(JSON.stringify(original)) as SlideElement;
            translate(moved, dx, dy);
            list[at] = moved;
          });
        },
        current.id,
      );
      return;
    }
    if (current.kind === "resize") {
      const indices = [...current.snapshot.keys()];
      const dx = at.x - current.startX;
      const dy = at.y - current.startY;
      const [hx, hy] = HANDLE_DIR[current.handle];
      if (indices.length === 1) {
        const index = indices[0];
        const original = current.snapshot.get(index)!;
        if (original.type === "line") return;
        const theta = rad(original.rotate ?? 0);
        const cos = Math.cos(theta);
        const sin = Math.sin(theta);
        const lx = dx * cos + dy * sin;
        const ly = -dx * sin + dy * cos;
        let w = Math.max(8, original.w + hx * lx);
        let h = Math.max(8, original.h + hy * ly);
        if (event.shiftKey && hx && hy) {
          const scale = Math.max(w / original.w, h / original.h);
          w = Math.max(8, original.w * scale);
          h = Math.max(8, original.h * scale);
        }
        const sx = (hx * (w - original.w)) / 2;
        const sy = (hy * (h - original.h)) / 2;
        let cx = original.x + original.w / 2 + sx * cos - sy * sin;
        let cy = original.y + original.h / 2 + sx * sin + sy * cos;
        let found: Guide[] = [];
        if (!original.rotate && snap && !event.altKey && !event.shiftKey) {
          // An unrotated box: the edges being dragged snap.
          const rect = { x: cx - w / 2, y: cy - h / 2, w, h };
          const { xs, ys } = targets([index]);
          const limit = 6 / k;
          const near = (value: number, points: number[]) => points.find((p) => Math.abs(p - value) <= limit);
          if (hx) {
            const edge = hx > 0 ? rect.x + rect.w : rect.x;
            const target = near(edge, xs);
            if (target !== undefined) {
              const delta = target - edge;
              w = Math.max(8, w + hx * delta);
              cx += delta / 2;
              found.push({ axis: "x", at: target });
            }
          }
          if (hy) {
            const edge = hy > 0 ? rect.y + rect.h : rect.y;
            const target = near(edge, ys);
            if (target !== undefined) {
              const delta = target - edge;
              h = Math.max(8, h + hy * delta);
              cy += delta / 2;
              found.push({ axis: "y", at: target });
            }
          }
        } else found = [];
        setGuides(found);
        onChange(
          labels.resize,
          (list) => {
            const target = list[placeOf(list, index, original)];
            if (!target || target.type === "line") return;
            target.x = round1(cx - w / 2);
            target.y = round1(cy - h / 2);
            target.w = round1(w);
            target.h = round1(h);
          },
          current.id,
        );
        return;
      }
      // Several: the frame around them scales, from the opposite corner.
      const start = unionOf(indices.map((i) => boundsOf(current.snapshot.get(i)!)));
      // A frame without width or height (lines on one axis) cannot scale.
      if (!start || start.w < 1 || start.h < 1) return;
      let w = Math.max(8, start.w + hx * dx);
      let h = Math.max(8, start.h + hy * dy);
      if (event.shiftKey || (hx && hy)) {
        const scale = Math.max(hx ? w / start.w : 0, hy ? h / start.h : 0);
        w = start.w * scale;
        h = start.h * scale;
      }
      const x = hx < 0 ? start.x + start.w - w : start.x;
      const y = hy < 0 ? start.y + start.h - h : start.y;
      const sx = w / start.w;
      const sy = h / start.h;
      onChange(
        labels.resize,
        (list) => {
          current.snapshot.forEach((original, i) => {
            const at = placeOf(list, i, original);
            if (!list[at]) return;
            const b = boundsOf(original);
            const next = JSON.parse(JSON.stringify(original)) as SlideElement;
            placeIn(next, b, { x: x + (b.x - start.x) * sx, y: y + (b.y - start.y) * sy, w: b.w * sx, h: b.h * sy });
            list[at] = next;
          });
        },
        current.id,
      );
      return;
    }
    if (current.kind === "rotate") {
      let angle = (Math.atan2(at.y - current.cy, at.x - current.cx) * 180) / Math.PI + 90;
      if (angle > 180) angle -= 360;
      angle = event.shiftKey ? Math.round(angle / 15) * 15 : Math.round(angle);
      if (Math.abs(angle) < 2 && !event.shiftKey) angle = 0;
      onChange(
        labels.rotate,
        (list) => {
          const target = list[placeOf(list, current.index, current.snapshot)];
          if (!target || target.type === "line") return;
          if (angle) target.rotate = angle;
          else delete target.rotate;
        },
        current.id,
      );
      return;
    }
    if (current.kind === "end") {
      const other = current.which === 1 ? { x: current.snapshot.x2, y: current.snapshot.y2 } : { x: current.snapshot.x1, y: current.snapshot.y1 };
      let x = at.x;
      let y = at.y;
      if (event.shiftKey) {
        // 45° steps.
        const angle = Math.round(Math.atan2(y - other.y, x - other.x) / (Math.PI / 4)) * (Math.PI / 4);
        const length = Math.hypot(x - other.x, y - other.y);
        x = other.x + Math.cos(angle) * length;
        y = other.y + Math.sin(angle) * length;
      } else if (snap && !event.altKey) {
        const { xs, ys } = targets([current.index]);
        const limit = 6 / k;
        const nx = xs.find((p) => Math.abs(p - x) <= limit);
        const ny = ys.find((p) => Math.abs(p - y) <= limit);
        const found: Guide[] = [];
        if (nx !== undefined) {
          x = nx;
          found.push({ axis: "x", at: nx });
        }
        if (ny !== undefined) {
          y = ny;
          found.push({ axis: "y", at: ny });
        }
        setGuides(found);
      }
      onChange(
        labels.resize,
        (list) => {
          const target = list[placeOf(list, current.index, current.snapshot)];
          if (!target || target.type !== "line") return;
          if (current.which === 1) {
            target.x1 = round1(x);
            target.y1 = round1(y);
          } else {
            target.x2 = round1(x);
            target.y2 = round1(y);
          }
        },
        current.id,
      );
      return;
    }
    // marquee
    const rect = {
      x: Math.min(current.startX, at.x),
      y: Math.min(current.startY, at.y),
      w: Math.abs(at.x - current.startX),
      h: Math.abs(at.y - current.startY),
    };
    setMarquee(rect);
  };

  const endDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    drag.current = null;
    setDragging(false);
    setGuides([]);
    try {
      box.current?.releasePointerCapture(event.pointerId);
    } catch {
      /* not captured */
    }
    if (current?.kind === "marquee") {
      const rect = marquee;
      setMarquee(null);
      if (!rect || (rect.w * k < 3 && rect.h * k < 3)) return;
      const hit = latest.current.elements
        .map((element, index) => ({ b: boundsOf(element), index }))
        .filter(({ b }) => b.x < rect.x + rect.w && b.x + b.w > rect.x && b.y < rect.y + rect.h && b.y + b.h > rect.y)
        .map(({ index }) => latest.current.keys[index]);
      onSelect([...new Set([...current.add, ...hit])]);
    }
  };

  const onDoubleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    const index = elementIndexOf(event.nativeEvent);
    if (index === null || !elements[index]) return;
    const element = elements[index];
    onSelect([keys[index]]);
    if (hasText(element) || element.type === "table") onWrite(index);
    else onOpenElement(index);
  };

  // A selection that no longer exists (undo, a revision) is let go.
  useEffect(() => {
    const live = selection.filter((key) => keys.includes(key));
    if (live.length !== selection.length) onSelect(live);
  }, [keys, selection, onSelect]);

  // --- drawing the selection ----------------------------------------------------------------------

  const startHandle = (event: ReactPointerEvent, handle: Handle) => {
    event.stopPropagation();
    event.preventDefault();
    const at = toSlide(event.clientX, event.clientY);
    const snapshot = new Map<number, SlideElement>();
    selected.forEach((i) => {
      if (!elements[i].locked) snapshot.set(i, elements[i]);
    });
    if (!snapshot.size) return;
    startDrag({ kind: "resize", handle, startX: at.x, startY: at.y, snapshot, id: `resize:${++dragCounter}` }, event);
  };

  const single = selected.length === 1 ? elements[selected[0]] : null;
  const scaled = (r: Rect): CSSProperties => ({ left: r.x * k, top: r.y * k, width: r.w * k, height: r.h * k });

  let frame: ReactNode = null;
  if (single && single.type === "line") {
    const index = selected[0];
    const end = (which: 1 | 2) => {
      const x = which === 1 ? single.x1 : single.x2;
      const y = which === 1 ? single.y1 : single.y2;
      return (
        <div
          key={which}
          className="absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 cursor-crosshair rounded-full border-2 border-accent bg-white shadow"
          style={{ left: x * k, top: y * k, pointerEvents: "auto" }}
          data-testid={`slides-line-end-${which}`}
          onPointerDown={(event) => {
            event.stopPropagation();
            event.preventDefault();
            startDrag({ kind: "end", index, which, id: `end:${++dragCounter}`, snapshot: single }, event);
          }}
        />
      );
    };
    frame = (
      <>
        <svg className="absolute inset-0 overflow-visible" width={width} height={height}>
          <line x1={single.x1 * k} y1={single.y1 * k} x2={single.x2 * k} y2={single.y2 * k} stroke="hsl(var(--accent))" strokeWidth={1} strokeDasharray="4 3" />
        </svg>
        {end(1)}
        {end(2)}
      </>
    );
  } else if (single) {
    const b = boundsOf(single);
    const index = selected[0];
    const locked = !!single.locked;
    frame = (
      <div
        className={cn2("absolute border border-accent", locked && "border-dashed")}
        style={{ ...scaled(b), rotate: `${single.rotate ?? 0}deg` }}
        data-testid="slides-selection"
      >
        {!locked &&
          HANDLES.map((handle) => {
            const [hx, hy] = HANDLE_DIR[handle];
            return (
              <div
                key={handle}
                className="absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-[2px] border border-accent bg-white shadow-sm"
                style={{ left: `${(hx + 1) * 50}%`, top: `${(hy + 1) * 50}%`, cursor: HANDLE_CURSOR[handle], pointerEvents: "auto" }}
                data-testid={`slides-handle-${handle}`}
                onPointerDown={(event) => startHandle(event, handle)}
              />
            );
          })}
        {!locked && (
          <>
            <div className="absolute left-1/2 top-[-22px] h-[18px] w-px bg-accent" />
            <div
              className="absolute left-1/2 top-[-28px] h-3 w-3 -translate-x-1/2 cursor-grab rounded-full border border-accent bg-white shadow-sm"
              style={{ pointerEvents: "auto" }}
              data-testid="slides-rotate"
              onPointerDown={(event) => {
                event.stopPropagation();
                event.preventDefault();
                startDrag({ kind: "rotate", index, cx: b.x + b.w / 2, cy: b.y + b.h / 2, id: `rotate:${++dragCounter}`, snapshot: single }, event);
              }}
            />
          </>
        )}
      </div>
    );
  } else if (selected.length > 1) {
    const union = unionOf(selected.map((i) => boundsOf(elements[i])))!;
    frame = (
      <>
        {selected.map((i) => (
          <div key={i} className="absolute border border-accent/70" style={{ ...scaled(boundsOf(elements[i])), rotate: `${elements[i].type === "line" ? 0 : (elements[i] as { rotate?: number }).rotate ?? 0}deg` }} />
        ))}
        <div className="absolute border border-dashed border-accent" style={scaled(union)} data-testid="slides-selection">
          {(["nw", "ne", "se", "sw"] as const).map((handle) => {
            const [hx, hy] = HANDLE_DIR[handle];
            return (
              <div
                key={handle}
                className="absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-[2px] border border-accent bg-white shadow-sm"
                style={{ left: `${(hx + 1) * 50}%`, top: `${(hy + 1) * 50}%`, cursor: HANDLE_CURSOR[handle], pointerEvents: "auto" }}
                onPointerDown={(event) => startHandle(event, handle)}
              />
            );
          })}
        </div>
      </>
    );
  }

  const hovered = hover !== null && !dragging && elements[hover] && !selected.includes(hover) && hover !== writing ? elements[hover] : null;

  return (
    <div
      ref={box}
      className="relative outline-none"
      style={{ width, height }}
      tabIndex={-1}
      data-testid="slides-canvas-editor"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onPointerLeave={() => setHover(null)}
      onDoubleClick={onDoubleClick}
      onContextMenu={(event) => {
        const index = elementIndexOf(event.nativeEvent);
        if (index === null && inField(event.nativeEvent)) return;
        event.preventDefault();
        if (index !== null && !selection.includes(keys[index])) onSelect([keys[index]]);
        onContextMenu({ x: event.clientX, y: event.clientY }, index);
      }}
    >
      {children}
      <div className="pointer-events-none absolute inset-0" aria-hidden>
        {grid && (
          <div
            className="absolute inset-0"
            style={{
              backgroundImage:
                "linear-gradient(to right, hsl(var(--accent) / .18) 1px, transparent 1px), linear-gradient(to bottom, hsl(var(--accent) / .18) 1px, transparent 1px)",
              backgroundSize: `${(SLIDE_W / 16) * k}px ${(SLIDE_H / 9) * k}px`,
            }}
          />
        )}
        {hovered && <div className="absolute border border-accent/50" style={{ ...scaled(boundsOf(hovered)), rotate: `${hovered.type === "line" ? 0 : (hovered.rotate ?? 0)}deg` }} />}
        {frame}
        {guides.map((guide, i) =>
          guide.axis === "x" ? (
            <div key={i} className="absolute top-0 h-full w-px bg-[#E5397F]" style={{ left: guide.at * k }} />
          ) : (
            <div key={i} className="absolute left-0 h-px w-full bg-[#E5397F]" style={{ top: guide.at * k }} />
          ),
        )}
        {marquee && <div className="absolute border border-accent bg-accent/10" style={scaled(marquee)} data-testid="slides-marquee" />}
      </div>
    </div>
  );
}

function cn2(...parts: (string | false | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}
