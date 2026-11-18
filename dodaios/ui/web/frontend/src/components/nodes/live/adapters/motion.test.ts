import { afterEach, describe, expect, it, vi } from "vitest";

import { CLIP_LIVE_SEEK } from "../../editors/motion/clipLive";
import type { MotionSpec, Scene, TrackItem } from "../../editors/motion/motionModel";
import { unitsFor } from "../playback";
import { clipSteps, motionReveal } from "./motion";

const scene = (id: string, seconds = 3): Scene => ({ id, type: "title", seconds, transition: "cut", title: id });
const text = (id: string, start: number, seconds = 2): TrackItem => ({ id, start, seconds, text: id });
const spec = (over: Partial<MotionSpec> = {}): MotionSpec => ({
  format: "wide",
  theme: "dark",
  accent: "",
  loop: false,
  scenes: [],
  ...over,
});

const paths = (steps: ReturnType<typeof clipSteps>) => steps.map((s) => ("path" in s.target ? s.target.path : "?"));

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

describe("the Clips reveal", () => {
  it("plays a fresh clip in editing order: bin, main track, then each track left to right", () => {
    const next = spec({
      media: { m1: { kind: "video", name: "a.mp4", file: "a.mp4", seconds: 4, width: 1, height: 1, audio: false } },
      scenes: [scene("s1"), scene("s2")],
      tracks: [
        { id: "tr1", kind: "text", items: [text("t2", 4), text("t1", 0)] },
        { id: "tr2", kind: "overlay", items: [text("o1", 1)] },
      ],
    });
    expect(paths(clipSteps(null, next))).toEqual([
      "/media/m1",
      "/scenes/0",
      "/scenes/1",
      "/tracks/0",
      "/tracks/0/items/1",
      "/tracks/0/items/0",
      "/tracks/1",
      "/tracks/1/items/0",
    ]);
  });

  it("plays only what the batch changed", () => {
    const before = spec({ scenes: [scene("s1")], tracks: [{ id: "tr1", kind: "text", items: [text("t1", 0)] }] });
    const next = spec({
      scenes: [scene("s1"), scene("s2")],
      tracks: [{ id: "tr1", kind: "text", items: [text("t1", 0), text("t2", 3)] }],
    });
    expect(paths(clipSteps(before, next))).toEqual(["/scenes/1", "/tracks/0/items/1"]);
  });

  it("moves the playhead onto the clip being placed, at the clip's start", () => {
    const seen: number[] = [];
    const root = document.createElement("div");
    root.addEventListener(CLIP_LIVE_SEEK, (e) => seen.push((e as CustomEvent).detail.t));
    const el = document.createElement("div");
    root.appendChild(el);
    const steps = clipSteps(null, spec({ scenes: [scene("s1", 3), scene("s2", 2)] }));
    steps[1].onReveal!(el);
    expect(seen).toEqual([3]);
  });

  it("grows a new clip and glides a moved or trimmed one", () => {
    const before = spec({ tracks: [{ id: "tr1", kind: "text", items: [text("t1", 0, 2)] }] });
    const next = spec({ tracks: [{ id: "tr1", kind: "text", items: [text("t1", 4, 4), text("t2", 9)] }] });
    const [moved, fresh] = clipSteps(before, next);
    const el = document.createElement("div");
    vi.spyOn(el, "getBoundingClientRect").mockReturnValue({ width: 200 } as DOMRect);
    // 50 px per second: it moved 4 s right (200 px) and stretched from 100 px to 200 px.
    expect(moved.enter!(el)).toEqual([
      { transform: "translateX(-200.0px)", width: "100.0px" },
      { transform: "translateX(0)", width: "200.0px" },
    ]);
    expect(fresh.enter!(el)).toEqual([{ clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0 0 0)" }]);
  });

  it("slides a new track in and leaves an unchanged clip alone", () => {
    const track = { id: "tr1", kind: "text" as const, items: [text("t1", 0)] };
    const steps = clipSteps(spec({ tracks: [track] }), spec({ tracks: [track, { id: "tr2", kind: "audio", items: [] }] }));
    expect(paths(steps)).toEqual(["/tracks/1"]);
    expect(steps[0].enter!(document.createElement("div"))![0]).toEqual({ transform: "translateY(-8px)" });
  });

  it("does not play a spec-level change (the preview refreshes instead)", () => {
    expect(clipSteps(spec({ scenes: [scene("s1")] }), spec({ scenes: [scene("s1")], theme: "light" }))).toEqual([]);
  });

  it("resolves its steps to the marked timeline blocks", () => {
    const root = document.createElement("div");
    root.innerHTML = `<div data-live-path="/scenes/0">A</div><div data-live-path="/tracks/0"><i data-live-path="/tracks/0/items/0">T</i></div>`;
    document.body.appendChild(root);
    const next = spec({ scenes: [scene("s1")], tracks: [{ id: "tr1", kind: "text", items: [text("t1", 0)] }] });
    const steps = motionReveal.steps({ type: "motion", previous: null, next, ops: null, initial: true, root });
    const units = unitsFor(steps, root, []);
    expect(units.map((u) => u.elements[0].getAttribute("data-live-path"))).toEqual(["/scenes/0", "/tracks/0", "/tracks/0/items/0"]);
  });

  it("returns no steps for a spec it cannot read", () => {
    const root = document.createElement("div");
    expect(motionReveal.steps({ type: "motion", previous: null, next: {}, ops: null, initial: false, root })).toEqual([]);
  });
});
