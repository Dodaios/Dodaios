/**
 * The board's own canvas logic without a canvas: the smooth view, the order
 * the assistant's work lands in, and what the inspector may change.
 *
 * Contracts worth pinning:
 * - zooming keeps the point under the pointer where it is, and a mouse notch
 *   is told apart from a trackpad's stream,
 * - the assistant's new work lands frames first, boxes with their labels,
 *   arrows last, within a few seconds however much it is,
 * - only what the assistant drew in the last moments plays again on opening,
 * - the inspector offers each kind of element only the styles it has.
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("@excalidraw/excalidraw", () => ({
  CaptureUpdateAction: { IMMEDIATELY: "IMMEDIATELY", NEVER: "NEVER" },
  getCommonBounds: () => [0, 0, 0, 0],
  newElementWith: (element: object, update: object) => ({ ...element, ...update }),
  restoreElements: (elements: unknown[]) => elements,
}));

import type { BoardElement } from "../boardApi";
import { FRESH_MS, freshAssistantIds, planPieces, stepDelay } from "./liveBuild";
import { currentItemState, keysFor } from "./styleOps";
import { MAX_ZOOM, MIN_ZOOM, clampZoom, isNotch, zoomAround } from "./viewport";

function el(id: string, over: Partial<BoardElement> & Record<string, unknown> = {}): BoardElement {
  return { id, type: "rectangle", version: 1, versionNonce: 1, isDeleted: false, ...over } as BoardElement;
}

describe("the smooth view", () => {
  it("keeps the scene point under the pointer when zooming", () => {
    const view = { scrollX: -100, scrollY: 40, zoom: 1 };
    const pointer = { x: 300, y: 200 };
    const before = { x: pointer.x / view.zoom - view.scrollX, y: pointer.y / view.zoom - view.scrollY };
    const next = zoomAround(view, 2, pointer.x, pointer.y);
    expect(next.zoom).toBe(2);
    expect(pointer.x / next.zoom - next.scrollX).toBeCloseTo(before.x);
    expect(pointer.y / next.zoom - next.scrollY).toBeCloseTo(before.y);
  });

  it("tells a mouse notch from a trackpad's stream", () => {
    expect(isNotch({ deltaMode: 0, deltaX: 0, deltaY: 100 })).toBe(true);
    expect(isNotch({ deltaMode: 1, deltaX: 0, deltaY: 3 })).toBe(true);
    expect(isNotch({ deltaMode: 0, deltaX: 0, deltaY: 4.5 })).toBe(false);
    expect(isNotch({ deltaMode: 0, deltaX: 12, deltaY: 100 })).toBe(false);
  });

  it("keeps the zoom between the editor's bounds", () => {
    expect(clampZoom(0.01)).toBe(MIN_ZOOM);
    expect(clampZoom(99)).toBe(MAX_ZOOM);
    expect(clampZoom(1.5)).toBe(1.5);
  });
});

describe("watching the assistant draw", () => {
  it("lands frames first, each box with its label, arrows last", () => {
    const order = [
      el("box", { boundElements: [{ id: "label", type: "text" }] }),
      el("label", { type: "text", containerId: "box" }),
      el("arrow", { type: "arrow" }),
      el("frame", { type: "frame" }),
      el("other"),
      el("old"),
    ];
    const fresh = new Set(["box", "label", "arrow", "frame", "other"]);
    expect(planPieces(order, fresh).map((piece) => piece.ids)).toEqual([["frame"], ["box", "label"], ["other"], ["arrow"]]);
  });

  it("plays a large drawing within a few seconds and a small one calmly", () => {
    expect(stepDelay(1)).toBeGreaterThan(0);
    expect(stepDelay(4)).toBeLessThanOrEqual(260);
    expect(stepDelay(500) * 500).toBeLessThan(30_000);
    expect(stepDelay(10)).toBeGreaterThan(stepDelay(100));
  });

  it("plays on opening only what the assistant drew in the last moments", () => {
    const now = 1_000_000_000;
    const elements = [
      el("fresh", { customData: { by: "assistant" }, updated: now - 5_000 }),
      el("fresh-label", { type: "text", containerId: "fresh", updated: now - 5_000 }),
      el("old", { customData: { by: "assistant" }, updated: now - FRESH_MS - 1 }),
      el("mine", { updated: now - 1_000 }),
      el("gone", { customData: { by: "assistant" }, updated: now - 1_000, isDeleted: true }),
    ];
    expect([...freshAssistantIds(elements, now)].sort()).toEqual(["fresh", "fresh-label"]);
  });
});

describe("the inspector", () => {
  it("offers each kind only the styles it has", () => {
    expect(keysFor("rectangle").has("backgroundColor")).toBe(true);
    expect(keysFor("rectangle").has("roundness")).toBe(true);
    expect(keysFor("ellipse").has("roundness")).toBe(false);
    expect(keysFor("text").has("fontSize")).toBe(true);
    expect(keysFor("text").has("backgroundColor")).toBe(false);
    expect(keysFor("arrow").has("endArrowhead")).toBe(true);
    expect(keysFor("line").has("endArrowhead")).toBe(false);
    expect(keysFor("image").has("strokeColor")).toBe(false);
    expect(keysFor("frame").size).toBe(0);
  });

  it("makes a change the default for what is drawn next", () => {
    expect(currentItemState({ strokeColor: "#e03131", roundness: null, fontSize: 28 })).toEqual({
      currentItemStrokeColor: "#e03131",
      currentItemRoundness: "sharp",
      currentItemFontSize: 28,
    });
  });
});
