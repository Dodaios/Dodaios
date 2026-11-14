/**
 * The clip model: reading a spec, the scene actions, lengths, type switches
 * and the preview's one-value edits, each checked against the grammar of
 * `dodaios/nodes/kinds/motion.py`.
 */
import { describe, expect, it } from "vitest";

import { produce } from "../produce";
import {
  FIELDS,
  MAX_SCENES,
  MAX_SECONDS,
  MIN_SECONDS,
  SCENE_KINDS,
  clampSeconds,
  convertScene,
  defaultSeconds,
  dropIndex,
  duplicateScene,
  formatClock,
  insertScene,
  moveScene,
  newScene,
  readAtPointer,
  readMotionSpec,
  readNumber,
  removeScene,
  sceneAt,
  sceneProblem,
  sceneStarts,
  sceneSummary,
  setAtPointer,
  setSeconds,
  totalSeconds,
  type MotionSpec,
  type SceneSamples,
} from "./motionModel";

const SAMPLES: SceneSamples = {
  title: "Heading",
  text: "A statement",
  point: (n) => `Point ${n}`,
  statLabel: "share",
  barLabel: (n) => `Item ${n}`,
  quote: "Said so",
  by: "Someone",
  step: (n) => `Step ${n}`,
  end: "Thanks",
};

function film(): MotionSpec {
  return readMotionSpec({
    format: "wide",
    theme: "dark",
    accent: "green",
    loop: false,
    scenes: [
      { type: "title", title: "Hello", seconds: 4, transition: "fade" },
      { type: "bullets", title: "Points", bullets: ["a", "b"], seconds: 3.5, transition: "slide" },
      { type: "end", title: "Bye", seconds: 2.5, transition: "zoom" },
    ],
  });
}

describe("reading a spec", () => {
  it("passes a normalized spec through and repairs a broken one", () => {
    const spec = film();
    expect(spec.accent).toBe("green");
    expect(spec.scenes.map((scene) => scene.type)).toEqual(["title", "bullets", "end"]);

    const broken = readMotionSpec({ format: "cinema", scenes: [{ type: "nope", text: "x" }, 42, { type: "stat", value: 7 }] });
    expect(broken.format).toBe("wide");
    expect(broken.theme).toBe("dark");
    expect(broken.scenes).toHaveLength(2);
    // An unknown type reads as a statement; a length nobody gave follows the content.
    expect(broken.scenes[0]).toMatchObject({ type: "text", text: "x", transition: "fade" });
    expect(broken.scenes[0].seconds).toBe(defaultSeconds(broken.scenes[0]));
    expect(broken.scenes[1].value).toBe("7");
    expect(readMotionSpec(null).scenes).toEqual([]);
  });

  it("keeps only the fields a scene type keeps", () => {
    const spec = readMotionSpec({ scenes: [{ type: "quote", quote: "Q", by: "B", title: "dropped", seconds: 3 }] });
    expect(Object.keys(spec.scenes[0]).sort()).toEqual(["by", "quote", "seconds", "transition", "type"]);
  });
});

describe("time", () => {
  it("adds up the lengths and knows which scene plays when", () => {
    const spec = film();
    expect(totalSeconds(spec)).toBe(10);
    expect(sceneStarts(spec)).toEqual([0, 4, 7.5]);
    expect([0, 3.99, 4, 7.4, 7.5, 99].map((t) => sceneAt(spec, t))).toEqual([0, 0, 1, 1, 2, 2]);
    expect(formatClock(0)).toBe("0:00");
    expect(formatClock(65.4)).toBe("1:05");
  });

  it("keeps a length in the spec's bounds, to a tenth", () => {
    expect(clampSeconds(0.2)).toBe(MIN_SECONDS);
    expect(clampSeconds(400)).toBe(MAX_SECONDS);
    expect(clampSeconds(2.26)).toBe(2.3);
    expect(clampSeconds(Number.NaN)).toBe(MIN_SECONDS);
  });

  it("gives a scene the default length the server would", () => {
    // The server's own numbers (`_default_seconds`): 3 + 0.6 per point, capped at 6.
    expect(defaultSeconds({ type: "bullets", bullets: ["a"], seconds: 0, transition: "fade" })).toBe(3.6);
    expect(defaultSeconds({ type: "bullets", bullets: ["a", "b", "c", "d", "e"], seconds: 0, transition: "fade" })).toBe(6);
    expect(defaultSeconds({ type: "title", title: "T", seconds: 0, transition: "fade" })).toBe(4);
    expect(defaultSeconds({ type: "chart", seconds: 0, transition: "fade" })).toBe(5);
    expect(defaultSeconds({ type: "text", text: "x".repeat(90), seconds: 0, transition: "fade" })).toBe(5);
  });
});

describe("scene actions", () => {
  it("adds, duplicates, moves and removes scenes as immutable steps", () => {
    const before = film();
    const added = produce(before, (draft) => void insertScene(draft, 1, newScene("stat", SAMPLES)));
    expect(added.scenes.map((scene) => scene.type)).toEqual(["title", "stat", "bullets", "end"]);
    // The untouched scenes are the very same objects (cheap undo history).
    expect(added.scenes[0]).toBe(before.scenes[0]);
    expect(before.scenes).toHaveLength(3);

    const copied = produce(added, (draft) => void duplicateScene(draft, 2));
    expect(copied.scenes[3]).toEqual(copied.scenes[2]);
    expect(copied.scenes[3]).not.toBe(copied.scenes[2]);

    const moved = produce(copied, (draft) => void moveScene(draft, 0, 4));
    expect(moved.scenes.map((scene) => scene.type)).toEqual(["stat", "bullets", "bullets", "end", "title"]);

    const removed = produce(moved, (draft) => void removeScene(draft, 4));
    expect(removed.scenes.map((scene) => scene.type)).toEqual(["stat", "bullets", "bullets", "end"]);
  });

  it("keeps at least one scene and at most forty", () => {
    const one = readMotionSpec({ scenes: [{ type: "text", text: "only", seconds: 3 }] });
    expect(produce(one, (draft) => void removeScene(draft, 0))).toBe(one);

    const full = readMotionSpec({ scenes: Array.from({ length: MAX_SCENES }, () => ({ type: "text", text: "x", seconds: 2 })) });
    expect(produce(full, (draft) => void insertScene(draft, 0, newScene("title", SAMPLES)))).toBe(full);
    expect(produce(full, (draft) => void duplicateScene(draft, 0))).toBe(full);
  });

  it("drops a dragged scene where the gap it was let go over is", () => {
    // Dragged right, the scene's own place closes up: slot 3 is index 2.
    expect(dropIndex(0, 3)).toBe(2);
    expect(dropIndex(2, 0)).toBe(0);
    expect(dropIndex(1, 1)).toBe(1);
    expect(dropIndex(1, 2)).toBe(1);
    const spec = film();
    expect(produce(spec, (draft) => void moveScene(draft, 1, dropIndex(1, 2)))).toBe(spec);
  });

  it("sets a length in bounds", () => {
    const spec = produce(film(), (draft) => setSeconds(draft, 1, 25));
    expect(spec.scenes[1].seconds).toBe(MAX_SECONDS);
  });
});

describe("new scenes and type switches", () => {
  it("makes every scene type valid at once, as the server would accept it", () => {
    for (const kind of SCENE_KINDS) {
      const scene = newScene(kind, SAMPLES);
      expect(scene.type).toBe(kind);
      expect(sceneProblem(scene)).toBeNull();
      // Nothing the type does not keep.
      for (const key of Object.keys(scene)) {
        if (!["type", "seconds", "transition"].includes(key)) expect(FIELDS[kind]).toContain(key);
      }
      expect(scene.seconds).toBe(defaultSeconds(scene));
    }
  });

  it("carries the words over when the type changes, and fills what is missing", () => {
    const points = newScene("bullets", SAMPLES);
    points.bullets = ["Plan", "Build", "Ship"];
    points.title = "How";
    points.kicker = "Q4";

    const steps = convertScene(points, "steps", SAMPLES);
    expect(steps.steps?.map((step) => step.title)).toEqual(["Plan", "Build", "Ship"]);
    expect(steps).toMatchObject({ title: "How", kicker: "Q4" });

    const bars = convertScene(steps, "bars", SAMPLES);
    expect(bars.items?.map((item) => item.label)).toEqual(["Plan", "Build", "Ship"]);

    const quote = convertScene({ type: "text", text: "Words", seconds: 5, transition: "cut" }, "quote", SAMPLES);
    expect(quote).toMatchObject({ quote: "Words", by: "Someone", seconds: 5, transition: "cut" });

    for (const kind of SCENE_KINDS) {
      for (const from of SCENE_KINDS) {
        expect(sceneProblem(convertScene(newScene(from, SAMPLES), kind, SAMPLES))).toBeNull();
      }
    }
  });

  it("refits a length nobody changed, and keeps one the person chose", () => {
    const fitted = newScene("title", SAMPLES);
    expect(convertScene(fitted, "image", SAMPLES).seconds).toBe(5);
    const chosen = { ...fitted, seconds: 9 };
    expect(convertScene(chosen, "image", SAMPLES).seconds).toBe(9);
  });
});

describe("checking and naming", () => {
  it("says what a scene lacks", () => {
    expect(sceneProblem({ type: "title", title: "  ", seconds: 4, transition: "fade" })).toBe("title");
    expect(sceneProblem({ type: "bullets", bullets: ["", " "], seconds: 4, transition: "fade" })).toBe("bullets");
    expect(sceneProblem({ type: "bars", items: [], seconds: 4, transition: "fade" })).toBe("items");
    expect(sceneProblem({ type: "chart", chart: { type: "line", x: ["a"], series: [] }, seconds: 4, transition: "fade" })).toBe("chart");
    expect(sceneProblem(newScene("chart", SAMPLES))).toBeNull();
  });

  it("names a block by its first text", () => {
    expect(sceneSummary({ type: "stat", value: "42", unit: "%", seconds: 4, transition: "fade" })).toBe("42 %");
    expect(sceneSummary({ type: "bullets", bullets: ["", "b"], seconds: 4, transition: "fade" })).toBe("b");
    expect(sceneSummary({ type: "steps", steps: [{ title: "Ask", text: "" }], seconds: 4, transition: "fade" })).toBe("Ask");
  });
});

describe("one value at a place", () => {
  it("writes only where the spec already has a value", () => {
    const spec = film();
    expect(readAtPointer(spec, "/scenes/1/bullets/1")).toBe("b");
    expect(readAtPointer(spec, "/scenes/0/kicker")).toBeUndefined();
    const next = produce(spec, (draft) => void setAtPointer(draft, "/scenes/1/bullets/1", "B"));
    expect(next.scenes[1].bullets).toEqual(["a", "B"]);
    expect(produce(spec, (draft) => void setAtPointer(draft, "/scenes/0/kicker", "x"))).toBe(spec);
    expect(produce(spec, (draft) => void setAtPointer(draft, "/scenes/9/title", "x"))).toBe(spec);
    expect(produce(spec, (draft) => void setAtPointer(draft, "scenes/0/title", "x"))).toBe(spec);
  });

  it("reads a typed number the way the server does", () => {
    expect(readNumber("1.234,5")).toBe(1234.5);
    expect(readNumber("1,234.5")).toBe(1234.5);
    expect(readNumber("40,62")).toBe(40.62);
    expect(readNumber("1.200")).toBe(1200);
    expect(readNumber("1 200")).toBe(1200);
    expect(readNumber("€ 12")).toBe(12);
    expect(readNumber("-3.5")).toBe(-3.5);
    expect(readNumber("0.250")).toBe(0.25);
    expect(readNumber("many")).toBeNaN();
    expect(readNumber("")).toBeNaN();
    expect(readNumber("1,2,3.4,5")).toBeNaN();
  });
});
