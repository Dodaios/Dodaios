import { describe, expect, it } from "vitest";

import { elementForPath } from "../playback";
import { piecePath, whiteboardReveal, type WhiteboardPlan } from "./whiteboard";

function steps(plan: WhiteboardPlan) {
  return whiteboardReveal.steps({
    type: "whiteboard",
    previous: null,
    next: plan,
    ops: null,
    initial: false,
    root: document.createElement("div"),
  });
}

describe("the whiteboard reveal", () => {
  it("plays the pieces in the order the board planned them", () => {
    const out = steps({ pieces: [["frame"], ["box", "label"], ["arrow"]] });
    expect(out.map((step) => step.target)).toEqual([
      { path: "/elements/frame" },
      { path: "/elements/box" },
      { path: "/elements/arrow" },
    ]);
  });

  it("skips an empty piece and has nothing to play for an empty plan", () => {
    expect(steps({ pieces: [[], ["box"]] })).toHaveLength(1);
    expect(steps({ pieces: [] })).toEqual([]);
  });

  it("names a piece by its first element, which a marker can carry", () => {
    const root = document.createElement("div");
    const marker = document.createElement("div");
    marker.setAttribute("data-live-path", piecePath(["box", "label"]));
    root.appendChild(marker);
    expect(elementForPath(root, "/elements/box")).toBe(marker);
  });
});
