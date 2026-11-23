/**
 * The assistant's drawing, placed piece by piece on the shared live timing,
 * with the presence told where each piece lands.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@excalidraw/excalidraw", () => ({
  CaptureUpdateAction: { NEVER: "NEVER" },
  getCommonBounds: (elements: Array<{ x: number; y: number; width: number; height: number }>) => [
    Math.min(...elements.map((e) => e.x)),
    Math.min(...elements.map((e) => e.y)),
    Math.max(...elements.map((e) => e.x + e.width)),
    Math.max(...elements.map((e) => e.y + e.height)),
  ],
}));

import type { BoardElement } from "../boardApi";
import { LIVE_TIMING } from "../../live/playback";
import { LiveBuild, partialElement, strokeOf, type BuildListener, type GrowPiece } from "./liveBuild";

function el(id: string, over: Record<string, unknown> = {}): BoardElement {
  return { id, type: "rectangle", x: 0, y: 0, width: 10, height: 10, version: 1, versionNonce: 1, isDeleted: false, ...over } as unknown as BoardElement;
}

function setup() {
  let scene: BoardElement[] = [];
  const api = {
    getSceneElementsIncludingDeleted: () => scene,
    getSceneElements: () => scene,
    getAppState: () => ({ zoom: { value: 1 }, scrollX: 0, scrollY: 0, width: 1000, height: 800 }),
    scrollToContent: vi.fn(),
    updateScene: vi.fn((update: { elements?: BoardElement[] }) => {
      if (update.elements) scene = update.elements;
    }),
  };
  const events: string[] = [];
  const listener: BuildListener = {
    begin: (boxes) => {
      events.push(`begin:${boxes.map((b) => b.id).join(",")}`);
    },
    finished: () => events.push("finished"),
    done: () => events.push("done"),
  };
  const build = new LiveBuild({ api: () => api as never, personBusy: () => false });
  build.attach(listener);
  return { build, events, shown: () => scene.map((e) => e.id) };
}

const ORDER = [
  el("box", { x: 100, y: 100 }),
  el("label", { type: "text", containerId: "box", x: 100 }),
  el("arrow", { type: "arrow", x: 50 }),
  el("frame", { type: "frame", width: 400, height: 300 }),
];
const FRESH = new Set(["box", "label", "arrow", "frame"]);

describe("LiveBuild", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query }));
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("tells the presence the pieces in order, frame first, and lands them on the shared stagger", () => {
    const { build, events, shown } = setup();
    build.start(ORDER, FRESH);
    expect(events).toEqual(["begin:frame,box,arrow"]);
    vi.advanceTimersByTime(1);
    expect(shown()).toEqual(["frame"]);
    vi.advanceTimersByTime(LIVE_TIMING.staggerMs);
    expect(shown()).toEqual(["box", "label", "frame"].sort((a, b) => ORDER.findIndex((e) => e.id === a) - ORDER.findIndex((e) => e.id === b)));
    vi.advanceTimersByTime(LIVE_TIMING.staggerMs);
    expect(shown()).toHaveLength(4);
    expect(events.at(-1)).toBe("done");
  });

  it("lands everything at once when finished, and says so", () => {
    const { build, events, shown } = setup();
    build.start(ORDER, FRESH);
    build.finish();
    expect(shown()).toHaveLength(4);
    expect(events.at(-1)).toBe("finished");
    expect(build.playing).toBe(false);
  });

  it("shows the result at once with reduced motion, while the presence still moves", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), media: query }));
    const { build, events, shown } = setup();
    build.start(ORDER, FRESH);
    expect(shown()).toHaveLength(4);
    expect(events[0]).toMatch(/^begin:/);
    expect(events.at(-1)).toBe("done");
  });

  it("boxes each piece where it sits in the scene", () => {
    const boxes: Array<{ id: string; x: number; w: number }> = [];
    const { build } = setup();
    build.attach({ begin: (b) => { boxes.push(...b); }, finished: () => undefined, done: () => undefined });
    build.start(ORDER, FRESH);
    expect(boxes.find((b) => b.id === "frame")).toMatchObject({ x: 0, w: 400 });
    expect(boxes.find((b) => b.id === "box")).toMatchObject({ x: 100, w: 10 });
  });

  it("lets the presence's hand draw each piece: it grows under the hand and lands when it lets go", () => {
    const { build, shown } = setup();
    let grow: GrowPiece | null = null;
    build.attach({
      begin: (_boxes, _strokes, g) => {
        grow = g;
        return true;
      },
      finished: () => undefined,
      done: () => undefined,
    });
    build.start(ORDER, FRESH);
    // Driven: the board sets no timers of its own.
    vi.advanceTimersByTime(LIVE_TIMING.maxBatchMs * 2);
    expect(shown()).toEqual([]);
    // The frame lands first; then the box is half drawn, its label still waiting.
    grow!(0, 1);
    grow!(1, 0.5);
    expect(shown()).toEqual(expect.arrayContaining(["frame", "box"]));
    expect(shown()).not.toContain("label");
    grow!(1, 1);
    expect(shown()).toEqual(expect.arrayContaining(["frame", "box", "label"]));
  });
});

describe("the hand's drawing", () => {
  it("grows a shape from its corner, cuts a line along its points and types a text", () => {
    const box = partialElement(el("b", { width: 200, height: 100 }), 0.5) as unknown as { width: number; height: number };
    expect(box).toMatchObject({ width: 100, height: 50 });
    const line = partialElement(el("l", { type: "arrow", points: [[0, 0], [100, 0], [100, 100]] }), 0.75) as unknown as { points: number[][] };
    expect(line.points.at(-1)).toEqual([100, 50]);
    const text = partialElement(el("t", { type: "text", text: "Versand", originalText: "Versand" }), 0.5) as unknown as { text: string };
    expect(text.text.length).toBeGreaterThan(0);
    expect(text.text.length).toBeLessThan(7);
    expect(partialElement(el("lbl", { type: "text", containerId: "b" }), 0.5)).toBeNull();
  });

  it("drags a box corner to corner and an arrow along its points", () => {
    expect(strokeOf(el("b", { x: 10, y: 20, width: 30, height: 40 }))).toMatchObject({ kind: "shape", path: [[10, 20], [40, 60]] });
    expect(strokeOf(el("a", { type: "arrow", x: 5, y: 5, points: [[0, 0], [50, 0]] })).path).toEqual([[5, 5], [55, 5]]);
  });
});
