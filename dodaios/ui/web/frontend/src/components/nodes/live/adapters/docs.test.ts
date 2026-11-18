import { afterEach, describe, expect, it, vi } from "vitest";

import { blocksBefore, blocksOf, diffBlocks, editedSpan, rememberBlocks } from "../../editors/docs/liveBlocks";
import { LivePlayer, schedule, unitsFor, type PresenceElements, type UnitMotion } from "../playback";
import { groupEnds, textWriting } from "../writing";
import { docsReveal } from "./docs";

function page(markup: string): { root: HTMLElement; content: HTMLElement } {
  const root = document.createElement("div");
  root.innerHTML = `<h1>Title</h1><div class="ProseMirror">${markup}</div>`;
  document.body.appendChild(root);
  return { root, content: root.querySelector(".ProseMirror") as HTMLElement };
}

function stepsFor(root: HTMLElement, initial = false) {
  return docsReveal.steps({ type: "docs", previous: null, next: {}, ops: null, initial, root });
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("reading the blocks", () => {
  it("splits lists into items and tables into rows, and keeps pictures as media", () => {
    const { content } = page(
      '<p data-doc-summary="">Sum</p><h2>Plans</h2><p>Intro text.</p><ul><li><p>One</p></li><li><p>Two</p></li></ul>' +
        "<table><tbody><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></tbody></table><p><img src='x.png'></p>",
    );
    expect(blocksOf(content).map((b) => `${b.kind}:${b.tag}`)).toEqual([
      "block:summary", "block:h2", "text:p", "block:li", "block:li", "block:tr", "block:tr", "media:media",
    ]);
  });
});

describe("what a revision changed", () => {
  it("finds appended blocks and an edited paragraph, in reading order", () => {
    const { content } = page("<h2>Plans</h2><p>Alpha costs 19 euro per seat.</p>");
    rememberBlocks(content);
    content.innerHTML = "<h2>Plans</h2><p>Alpha costs 21 euro per seat.</p><p>Beta is new.</p>";
    const changes = diffBlocks(blocksBefore(content)!, blocksOf(content));
    expect(changes.map((c) => c.type)).toEqual(["edit", "new"]);
    const edit = changes[0];
    if (edit.type !== "edit") throw new Error("expected an edit");
    const span = editedSpan(edit.before.raw, edit.block.raw);
    expect(span.removed).toBe("19");
    expect(edit.block.raw.slice(span.from, span.to)).toBe("21");
  });

  it("does not take two unrelated paragraphs for an edit", () => {
    const { content } = page("<p>The first paragraph is about hosting.</p>");
    rememberBlocks(content);
    content.innerHTML = "<p>Something else entirely, new.</p>";
    expect(diffBlocks(blocksBefore(content)!, blocksOf(content)).map((c) => c.type)).toEqual(["new"]);
  });
});

describe("the docs steps", () => {
  it("falls back to the default reveal when no earlier blocks were remembered", () => {
    const { root } = page("<p>Text</p>");
    expect(stepsFor(root)).toHaveLength(1);
    expect(stepsFor(root, false)).toEqual([{ target: { changed: true } }]);
  });

  it("opened mid-build, every block fades in", () => {
    const { root } = page("<h2>A</h2><p>B</p>");
    expect(stepsFor(root, true).map((s) => "element" in s.target)).toEqual([true, true]);
  });

  it("gives each new block its own step; pictures get a skeleton, paragraphs write in", () => {
    const { root, content } = page("<h2>Plans</h2>");
    rememberBlocks(content);
    content.innerHTML = "<h2>Plans</h2><p>A new paragraph of words.</p><p><img src='a.png'></p><ul><li>One</li><li>Two</li></ul>";
    vi.stubGlobal("CSS", { highlights: new Map() });
    vi.stubGlobal("Highlight", class {});
    const steps = stepsFor(root);
    expect(steps).toHaveLength(4);
    expect(steps[0].motion).toBeDefined(); // the paragraph
    expect(steps[1].motion).toBeDefined(); // the picture
    expect(steps[2].motion).toBeUndefined(); // list items arrive whole
    expect(steps[3].motion).toBeUndefined();
  });

  it("fades a paragraph whole where text cannot be hidden without touching the editor", () => {
    const { root, content } = page("<h2>Plans</h2>");
    rememberBlocks(content);
    content.innerHTML = "<h2>Plans</h2><p>A new paragraph.</p>";
    expect(stepsFor(root)[0].motion).toBeUndefined();
  });
});

describe("writing", () => {
  it("groups words and keeps a long text inside the groups' cap", () => {
    const text = Array.from({ length: 100 }, (_, i) => `w${i}`).join(" ");
    const ends = groupEnds(text, 0, text.length);
    expect(ends[ends.length - 1]).toBe(text.length);
    expect(ends.length).toBeLessThanOrEqual(41);
    expect(groupEnds("one two three four", 0, 18)).toEqual([14, 18]);
  });

  it("hides the unwritten words and shows them group by group, then all on finish", () => {
    const registry = new Map<string, unknown>();
    vi.stubGlobal("CSS", { highlights: { set: (k: string, v: unknown) => registry.set(k, v), delete: (k: string) => registry.delete(k) } });
    vi.stubGlobal("Highlight", class { ranges: Range[]; constructor(...r: Range[]) { this.ranges = r; } });
    const { content } = page("<p>one two three four five six</p>");
    const motion = textWriting(content.firstElementChild!, { from: 0 });
    const host = document.createElement("div");
    motion.prepare(host);
    const first = (registry.get("live-unwritten") as { ranges: Range[] }).ranges[0];
    expect(first.toString()).toBe("one two three four five six");
    motion.start();
    motion.advance(1);
    expect((registry.get("live-unwritten") as { ranges: Range[] }).ranges[0].toString()).toBe("four five six");
    motion.finish();
    expect(registry.has("live-unwritten")).toBe(false);
  });
});

describe("the schedule", () => {
  const motion = (durationMs: number): UnitMotion => ({
    durationMs, steps: 1, prepare() {}, start() {}, advance() {}, finish() {},
  });

  it("keeps a long paragraph inside the per-batch budget by compressing, not truncating", () => {
    const units = [{ elements: [], motion: motion(40 * 55) }, { elements: [] }, { elements: [], motion: motion(40 * 55) }];
    const { starts, lengths } = schedule(units);
    expect(starts[2] + lengths[2] + 220).toBeLessThanOrEqual(3000);
    expect(starts).toEqual([...starts].sort((a, b) => a - b));
  });

  it("plays plain units as before", () => {
    expect(schedule([{ elements: [] }, { elements: [] }, { elements: [] }]).starts).toEqual([0, 90, 180]);
  });
});

describe("the player with a unit's own motion", () => {
  function view(): { host: HTMLElement; elements: PresenceElements } {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const make = () => host.appendChild(document.createElement("div"));
    return { host, elements: { cursor: make(), frame: make(), tag: make(), pill: make() } };
  }

  it("runs prepare, start, each step and finish, and finishes at once when interrupted", () => {
    vi.useFakeTimers();
    const calls: string[] = [];
    const own: UnitMotion = {
      durationMs: 200, steps: 2,
      prepare: () => calls.push("prepare"), start: () => calls.push("start"),
      advance: (k) => calls.push(`advance${k}`), finish: () => calls.push("finish"),
    };
    const { host, elements } = view();
    const player = new LivePlayer(host, elements, () => false);
    const el = document.body.appendChild(document.createElement("p"));
    player.play([{ elements: [el], motion: own }]);
    expect(calls).toEqual(["prepare"]);
    vi.advanceTimersByTime(1);
    expect(calls).toEqual(["prepare", "start"]);
    vi.advanceTimersByTime(100);
    expect(calls).toEqual(["prepare", "start", "advance1"]);
    player.interrupt();
    expect(calls[calls.length - 1]).toBe("finish");
    vi.advanceTimersByTime(1000);
    expect(calls.filter((c) => c === "advance2")).toHaveLength(0);
    player.destroy();
  });

  it("passes a step's motion through to its unit", () => {
    const { root, content } = page("<p>x</p>");
    const own: UnitMotion = { durationMs: 1, steps: 1, prepare() {}, start() {}, advance() {}, finish() {} };
    const units = unitsFor([{ target: { element: content.firstElementChild! }, motion: own }], root, []);
    expect(units[0].motion).toBe(own);
  });
});
