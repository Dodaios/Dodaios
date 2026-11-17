/**
 * The board's own tools as geometry: the lasso, the paint bucket and draw to
 * shape.
 *
 * Contracts worth pinning:
 * - the lasso takes what its loop fully encloses, a whole group, never a
 *   label on its own or a locked thing,
 * - the bucket fills the topmost closed shape under the click, by the
 *   shape's real outline (an ellipse's corner is not the ellipse),
 * - a drawn loop reads as the rectangle, ellipse or diamond it looks like, a
 *   straight stroke as an arrow, and a scribble stays a drawing.
 */
import { describe, expect, it } from "vitest";

import { fillTarget, insidePolygon, lassoPick, recognizeStroke, type Point, type ToolElement } from "./boardTools";

function box(id: string, x: number, y: number, w = 100, h = 60, over: Partial<ToolElement> = {}): ToolElement {
  return { id, type: "rectangle", x, y, width: w, height: h, ...over };
}

const square = (x: number, y: number, size: number): Point[] => [
  { x, y },
  { x: x + size, y },
  { x: x + size, y: y + size },
  { x, y: y + size },
];

describe("the lasso", () => {
  it("takes what its loop fully encloses", () => {
    const loop = square(0, 0, 300);
    const picked = lassoPick([box("in", 20, 20), box("half", 250, 20), box("out", 400, 400)], loop);
    expect(picked).toEqual(["in"]);
  });

  it("takes a group whole, and leaves labels and locked things", () => {
    const loop = square(0, 0, 300);
    const elements = [
      box("a", 20, 20, 100, 60, { groupIds: ["g"] }),
      box("b", 500, 20, 100, 60, { groupIds: ["g"] }),
      box("label", 30, 30, 50, 20, { type: "text", containerId: "a" }),
      box("locked", 150, 150, 50, 50, { locked: true }),
    ];
    expect(lassoPick(elements, loop).sort()).toEqual(["a", "b"]);
  });

  it("reads a point in a loop by the even-odd rule", () => {
    expect(insidePolygon({ x: 5, y: 5 }, square(0, 0, 10))).toBe(true);
    expect(insidePolygon({ x: 15, y: 5 }, square(0, 0, 10))).toBe(false);
  });
});

describe("the paint bucket", () => {
  it("fills the topmost shape under the click", () => {
    const below = box("below", 0, 0, 200, 200);
    const above = box("above", 50, 50, 100, 100);
    expect(fillTarget([below, above], { x: 100, y: 100 })?.id).toBe("above");
    expect(fillTarget([below, above], { x: 10, y: 10 })?.id).toBe("below");
    expect(fillTarget([below, above], { x: 500, y: 500 })).toBeNull();
  });

  it("goes by the shape's outline, not its box", () => {
    const ellipse = box("e", 0, 0, 100, 100, { type: "ellipse" });
    const diamond = box("d", 200, 0, 100, 100, { type: "diamond" });
    expect(fillTarget([ellipse], { x: 50, y: 50 })?.id).toBe("e");
    expect(fillTarget([ellipse], { x: 4, y: 4 })).toBeNull();
    expect(fillTarget([diamond], { x: 250, y: 50 })?.id).toBe("d");
    expect(fillTarget([diamond], { x: 205, y: 5 })).toBeNull();
  });

  it("leaves frames, locked shapes and open lines alone", () => {
    expect(fillTarget([box("f", 0, 0, 100, 100, { type: "frame" })], { x: 50, y: 50 })).toBeNull();
    expect(fillTarget([box("l", 0, 0, 100, 100, { locked: true })], { x: 50, y: 50 })).toBeNull();
    const open = box("open", 0, 0, 100, 100, { type: "line", points: [[0, 0], [100, 0], [100, 100]] });
    expect(fillTarget([open], { x: 80, y: 20 })).toBeNull();
  });
});

describe("draw to shape", () => {
  const ring = (cx: number, cy: number, rx: number, ry: number, shape: (t: number) => [number, number]) =>
    Array.from({ length: 64 }, (_, i) => {
      const [u, v] = shape((i / 63) * Math.PI * 2);
      return { x: cx + u * rx, y: cy + v * ry };
    });

  it("reads a drawn loop as the ellipse, rectangle or diamond it looks like", () => {
    const ellipse = ring(100, 100, 80, 50, (t) => [Math.cos(t), Math.sin(t)]);
    expect(recognizeStroke(ellipse)?.kind).toBe("ellipse");

    const rect = [
      ...Array.from({ length: 16 }, (_, i) => ({ x: i * 10, y: 0 })),
      ...Array.from({ length: 10 }, (_, i) => ({ x: 160, y: i * 10 })),
      ...Array.from({ length: 16 }, (_, i) => ({ x: 160 - i * 10, y: 100 })),
      ...Array.from({ length: 11 }, (_, i) => ({ x: 0, y: 100 - i * 10 })),
    ];
    const read = recognizeStroke(rect);
    expect(read?.kind).toBe("rectangle");
    expect(read).toMatchObject({ x: 0, y: 0, width: 160, height: 100 });

    const diamond = ring(100, 100, 80, 60, (t) => {
      const c = Math.cos(t);
      const s = Math.sin(t);
      const k = 1 / (Math.abs(c) + Math.abs(s));
      return [c * k, s * k];
    });
    expect(recognizeStroke(diamond)?.kind).toBe("diamond");
  });

  it("reads a straight stroke as an arrow from where it started", () => {
    const line = Array.from({ length: 20 }, (_, i) => ({ x: 10 + i * 10, y: 20 + i * 3 + (i % 2) }));
    expect(recognizeStroke(line)).toMatchObject({ kind: "arrow", x: 10, y: 20 });
  });

  it("leaves a scribble and a dot as drawings", () => {
    const scribble = Array.from({ length: 40 }, (_, i) => ({ x: (i * 37) % 120, y: (i * 53) % 90 }));
    expect(recognizeStroke(scribble)).toBeNull();
    expect(recognizeStroke([{ x: 0, y: 0 }, { x: 2, y: 1 }, { x: 3, y: 3 }, { x: 1, y: 2 }])).toBeNull();
  });
});
