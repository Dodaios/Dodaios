/**
 * The board's own tools that the editor package does not ship: the lasso,
 * the paint bucket, and turning a drawn stroke into a clean shape.
 *
 * These are pure geometry on the editor's elements, kept apart from the
 * component so they can be tested without a canvas:
 * - `lassoPick` says which elements a drawn loop encloses,
 * - `fillTarget` finds the closed shape under a point (for the bucket),
 * - `recognizeStroke` reads a freehand stroke as a rectangle, an ellipse, a
 *   diamond or an arrow, or as nothing when it is none of them.
 */

export interface Point {
  x: number;
  y: number;
}

/** An element as these tools read it. */
export interface ToolElement {
  id: string;
  type: string;
  x: number;
  y: number;
  width: number;
  height: number;
  angle?: number;
  isDeleted?: boolean;
  locked?: boolean;
  containerId?: string | null;
  frameId?: string | null;
  groupIds?: readonly string[];
  points?: readonly (readonly [number, number])[];
  backgroundColor?: string;
}

/* ------------------------------------------------------------------------ */
/* Lasso                                                                     */
/* ------------------------------------------------------------------------ */

/** Is `point` inside the closed `polygon` (even-odd rule)? */
export function insidePolygon(point: Point, polygon: readonly Point[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const a = polygon[i];
    const b = polygon[j];
    if (a.y > point.y !== b.y > point.y && point.x < ((b.x - a.x) * (point.y - a.y)) / (b.y - a.y || 1e-9) + a.x) {
      inside = !inside;
    }
  }
  return inside;
}

/** Points of an element the lasso must enclose: its corners, or its line's points. */
function outline(element: ToolElement): Point[] {
  if (element.points && element.points.length > 0 && (element.type === "arrow" || element.type === "line" || element.type === "freedraw")) {
    const step = Math.max(1, Math.floor(element.points.length / 24));
    const picked: Point[] = [];
    for (let i = 0; i < element.points.length; i += step) {
      picked.push({ x: element.x + element.points[i][0], y: element.y + element.points[i][1] });
    }
    const last = element.points[element.points.length - 1];
    picked.push({ x: element.x + last[0], y: element.y + last[1] });
    return picked;
  }
  const { x, y, width: w, height: h } = element;
  return [
    { x, y },
    { x: x + w, y },
    { x, y: y + h },
    { x: x + w, y: y + h },
  ];
}

/**
 * The elements a lasso loop takes: every one whose outline it encloses
 * fully, a frame only when its whole box is inside. A label goes with its
 * box (the editor selects it through the box), and locked things stay out.
 */
export function lassoPick(elements: readonly ToolElement[], loop: readonly Point[]): string[] {
  if (loop.length < 3) return [];
  const picked: string[] = [];
  for (const element of elements) {
    if (element.isDeleted || element.locked || element.containerId) continue;
    if (outline(element).every((point) => insidePolygon(point, loop))) picked.push(element.id);
  }
  // A group goes whole: when the lasso took part of one, it takes the rest.
  const groups = new Set<string>();
  const byId = new Map(elements.map((element) => [element.id, element]));
  for (const id of picked) for (const group of byId.get(id)?.groupIds ?? []) groups.add(group);
  if (groups.size > 0) {
    for (const element of elements) {
      if (element.isDeleted || element.containerId || picked.includes(element.id)) continue;
      if ((element.groupIds ?? []).some((group) => groups.has(group))) picked.push(element.id);
    }
  }
  return picked;
}

/* ------------------------------------------------------------------------ */
/* Paint bucket                                                              */
/* ------------------------------------------------------------------------ */

/** `point` in the element's own frame: unrotated, relative to its centre. */
function local(element: ToolElement, point: Point): Point {
  const cx = element.x + element.width / 2;
  const cy = element.y + element.height / 2;
  const angle = -(element.angle ?? 0);
  const dx = point.x - cx;
  const dy = point.y - cy;
  return { x: dx * Math.cos(angle) - dy * Math.sin(angle), y: dx * Math.sin(angle) + dy * Math.cos(angle) };
}

const FILLABLE = new Set(["rectangle", "ellipse", "diamond", "frame", "line", "freedraw"]);

/** Is `point` inside the shape of `element` (not only its box)? */
export function insideShape(element: ToolElement, point: Point): boolean {
  const p = local(element, point);
  const rx = Math.abs(element.width) / 2;
  const ry = Math.abs(element.height) / 2;
  if (rx < 1 || ry < 1) return false;
  if (element.type === "ellipse") return (p.x / rx) ** 2 + (p.y / ry) ** 2 <= 1;
  if (element.type === "diamond") return Math.abs(p.x) / rx + Math.abs(p.y) / ry <= 1;
  if (element.type === "rectangle" || element.type === "frame") return Math.abs(p.x) <= rx && Math.abs(p.y) <= ry;
  if ((element.type === "line" || element.type === "freedraw") && element.points && element.points.length > 2) {
    // A closed line or stroke: its own points form the outline.
    const loop = element.points.map(([x, y]) => ({ x: element.x + x, y: element.y + y }));
    const first = loop[0];
    const last = loop[loop.length - 1];
    const closed = Math.hypot(first.x - last.x, first.y - last.y) <= Math.max(12, 0.2 * Math.max(rx, ry) * 2);
    return closed && insidePolygon(point, loop);
  }
  return false;
}

/**
 * The topmost closed shape under `point` the bucket fills: the editor's
 * order is bottom to top, so the last hit wins. Frames are left alone (a
 * frame has no fill) and so are locked things.
 */
export function fillTarget(elements: readonly ToolElement[], point: Point): ToolElement | null {
  for (let i = elements.length - 1; i >= 0; i -= 1) {
    const element = elements[i];
    if (element.isDeleted || element.locked || !FILLABLE.has(element.type) || element.type === "frame") continue;
    if (insideShape(element, point)) return element;
  }
  return null;
}

/* ------------------------------------------------------------------------ */
/* Draw to shape                                                             */
/* ------------------------------------------------------------------------ */

export type Recognized =
  | { kind: "rectangle" | "ellipse" | "diamond"; x: number; y: number; width: number; height: number }
  | { kind: "arrow"; x: number; y: number; dx: number; dy: number };

function pathLength(points: readonly Point[]): number {
  let total = 0;
  for (let i = 1; i < points.length; i += 1) total += Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
  return total;
}

/**
 * What a freehand stroke was meant to be. A stroke that comes back near its
 * start is a closed shape: the one whose outline lies closest to the drawn
 * points wins (rectangle, ellipse or diamond), sized to the stroke's box. A
 * stroke that runs nearly straight is an arrow from its start to its end.
 * Anything else stays a drawing (null).
 */
export function recognizeStroke(points: readonly Point[]): Recognized | null {
  if (points.length < 4) return null;
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const w = maxX - minX;
  const h = maxY - minY;
  const size = Math.max(w, h);
  if (size < 16) return null;
  const first = points[0];
  const last = points[points.length - 1];
  const length = pathLength(points);
  const gap = Math.hypot(last.x - first.x, last.y - first.y);

  if (gap > 0.3 * size || length < 2.2 * size) {
    // Open: an arrow when it runs (nearly) straight.
    return gap / Math.max(length, 1) > 0.88 ? { kind: "arrow", x: first.x, y: first.y, dx: last.x - first.x, dy: last.y - first.y } : null;
  }
  if (w < 8 || h < 8) return null;
  const cx = minX + w / 2;
  const cy = minY + h / 2;
  let ellipse = 0;
  let rectangle = 0;
  let diamond = 0;
  for (const p of points) {
    const u = (p.x - cx) / (w / 2);
    const v = (p.y - cy) / (h / 2);
    ellipse += Math.abs(Math.hypot(u, v) - 1);
    rectangle += Math.abs(Math.max(Math.abs(u), Math.abs(v)) - 1);
    diamond += Math.abs(Math.abs(u) + Math.abs(v) - 1);
  }
  const scores: [Recognized["kind"], number][] = [
    ["ellipse", ellipse],
    ["rectangle", rectangle],
    ["diamond", diamond],
  ];
  scores.sort((a, b) => a[1] - b[1]);
  const [kind, error] = scores[0];
  // A scribble fits nothing well: it stays a drawing.
  if (error / points.length > 0.22) return null;
  return { kind: kind as "rectangle" | "ellipse" | "diamond", x: minX, y: minY, width: w, height: h };
}

/** A freehand element's points in scene coordinates. */
export function strokePoints(element: ToolElement): Point[] {
  return (element.points ?? []).map(([x, y]) => ({ x: element.x + x, y: element.y + y }));
}
