import { afterEach, describe, expect, it } from "vitest";

import { diffDecks, elementChange, firstWritten, indexAfterRevision } from "../../editors/slides/deckDiff";
import type { Deck, Slide } from "../../editors/slides/deckModel";
import type { SlideElement } from "../../editors/slides/elementModel";
import { unitsFor } from "../playback";
import { slideSteps } from "./slides";

const slide = (title: string, extra: Partial<Slide> = {}): Slide => ({ layout: "title", title, ...extra }) as Slide;
const deck = (...slides: Slide[]): Deck => ({ theme: "auto", slides }) as unknown as Deck;
const box = (id: string, x: number, extra: Record<string, unknown> = {}): SlideElement =>
  ({ id, type: "shape", shape: "rect", x, y: 100, w: 200, h: 100, ...extra }) as unknown as SlideElement;

afterEach(() => {
  document.body.innerHTML = "";
});

describe("what a revision changed in a deck", () => {
  it("tells a new slide from an edited one and from untouched ones", () => {
    const before = deck(slide("One"), slide("Two"));
    const after = deck(slide("One"), slide("Two, rewritten"), slide("Three"));
    const diff = diffDecks(before, after);
    expect(diff.changes.map((c) => [c.kind, c.index])).toEqual([
      ["edited", 1],
      ["added", 2],
    ]);
    expect(firstWritten(diff)).toBe(1);
  });

  it("does not mistake element ids the editor invents on every load for a change", () => {
    const before = deck(slide("One", { elements: [box("a", 10)] }), slide("Two"));
    const after = deck(slide("One", { elements: [box("zzz", 10)] }), slide("Two"), slide("Three"));
    expect(diffDecks(before, after).changes.map((c) => [c.kind, c.index])).toEqual([["added", 2]]);
  });

  it("keeps the person's slide under them when a slide is put in before it", () => {
    const before = deck(slide("One"), slide("Two"));
    const after = deck(slide("New"), slide("One"), slide("Two"));
    const diff = diffDecks(before, after);
    expect(diff.changes.map((c) => [c.kind, c.index])).toEqual([["added", 0]]);
    expect(indexAfterRevision(diff, 1, 3)).toBe(2);
    expect(indexAfterRevision(diff, 0, 3)).toBe(1);
  });

  it("sees slides that were only put in another order", () => {
    const before = deck(slide("A"), slide("B"), slide("C"));
    const diff = diffDecks(before, deck(slide("C"), slide("A"), slide("B")), [{ op: "move" }]);
    expect(diff.reordered).toBe(true);
    expect(diff.changes.every((c) => c.kind === "moved")).toBe(true);
    expect(firstWritten(diff)).toBeNull();
  });

  it("treats every slide as new when the editor opened mid-build", () => {
    expect(diffDecks(null, deck(slide("A"), slide("B"))).changes.map((c) => c.kind)).toEqual(["added", "added"]);
  });

  it("tells a moved element from a restyled and a new one", () => {
    const list = [box("a", 10)];
    expect(elementChange(list, box("a", 10), 0)).toBeNull();
    expect(elementChange(list, box("a", 300), 0)).toBe("moved");
    expect(elementChange(list, box("a", 10, { fill: "#000" }), 0)).toBe("styled");
    expect(elementChange(list, box("b", 10, { shape: "ellipse" }), 1)).toBe("added");
  });
});

/** A strip with two thumbnails and a stage whose shadow root holds the slide's fields. */
function editorBody(stageSlide: number, fields: Record<string, string>, elements = 0): HTMLElement {
  const root = document.createElement("div");
  root.innerHTML = `
    <div>
      <div><div data-strip-item="0"><div data-strip-thumb="0">a</div></div><div data-strip-item="1"><div data-strip-thumb="1">b</div></div></div>
    </div>
    <div data-testid="slides-canvas" data-slide="${stageSlide}"></div>`;
  document.body.appendChild(root);
  const host = root.querySelector("[data-testid='slides-canvas']")!;
  const shadow = host.attachShadow({ mode: "open" });
  const entries = Object.entries(fields)
    .map(([key, text]) => `<p data-field="${key}">${text}</p>`)
    .join("");
  const els = Array.from({ length: elements }, (_, i) => `<div data-el="${i}">shape</div>`).join("");
  shadow.innerHTML = `<section class="sl"><div class="sl-bg"></div>${entries}${els}</section>`;
  return root;
}

describe("the slides reveal", () => {
  it("builds a new slide on the stage: strip, then background, texts in reading order, elements", () => {
    const before = deck(slide("One"));
    const added = slide("Roadmap", { text: "Three steps", elements: [box("s1", 10)] });
    const next = deck(slide("One"), added);
    const root = editorBody(1, { title: "Roadmap", text: "Three steps" }, 1);
    added.background = { color: "#101010" };
    const steps = slideSteps({ type: "slides", previous: before, next, ops: null, initial: false, root });
    const units = unitsFor(steps, root, []);
    const names = units.map((u) => {
      const el = u.elements[0] as HTMLElement;
      return el.dataset.stripThumb ? "thumb" : (el.getAttribute("data-field") ?? (el.className || el.dataset.el));
    });
    expect(names).toEqual(["thumb", "sl-bg", "title", "text", "0"]);
    expect(units.every((u) => u.solo)).toBe(true);
    expect(units.every((u) => !u.visible)).toBe(true);
  });

  it("plays only the thumbnail of a slide the person is not on", () => {
    const before = deck(slide("One"), slide("Two"));
    const next = deck(slide("One"), slide("Two, rewritten"));
    const root = editorBody(0, { title: "One" });
    const units = unitsFor(slideSteps({ type: "slides", previous: before, next, ops: null, initial: false, root }), root, []);
    expect(units).toHaveLength(1);
    expect((units[0].elements[0] as HTMLElement).dataset.stripThumb).toBe("1");
    expect(units[0].visible).toBe(true);
  });

  it("writes only the texts that changed on an edited slide", () => {
    const before = deck(slide("Same", { text: "old" }));
    const next = deck(slide("Same", { text: "new" }));
    const root = editorBody(0, { title: "Same", text: "new" });
    const units = unitsFor(slideSteps({ type: "slides", previous: before, next, ops: null, initial: false, root }), root, []);
    expect(units.map((u) => u.elements[0].getAttribute("data-field"))).toEqual(["text"]);
    expect(units[0].onReveal).toBeTypeOf("function");
  });

  it("glides a moved element without hiding it", () => {
    const before = deck(slide("S", { elements: [box("a", 10)] }));
    const next = deck(slide("S", { elements: [box("a", 400)] }));
    const root = editorBody(0, { title: "S" }, 1);
    const units = unitsFor(slideSteps({ type: "slides", previous: before, next, ops: null, initial: false, root }), root, []);
    expect(units).toHaveLength(1);
    expect(units[0].visible).toBe(true);
    expect(units[0].elements[0].getAttribute("data-el")).toBe("0");
  });

  it("glides slides that were put in another order in the strip", () => {
    const before = deck(slide("A"), slide("B"));
    const root = editorBody(0, { title: "B" });
    const units = unitsFor(
      slideSteps({ type: "slides", previous: before, next: deck(slide("B"), slide("A")), ops: [{ op: "move", path: "/slides/1", to: 0 }], initial: false, root }),
      root,
      [],
    );
    expect(units).toHaveLength(2);
    expect(units.every((u) => u.visible)).toBe(true);
  });

  it("brings every thumbnail in once when the editor opens mid-build", () => {
    const next = deck(slide("A"), slide("B"));
    const root = editorBody(0, { title: "A" });
    const units = unitsFor(slideSteps({ type: "slides", previous: null, next, ops: null, initial: true, root }), root, []);
    expect(units.map((u) => u.elements[0].getAttribute("data-field") ?? (u.elements[0] as HTMLElement).dataset.stripThumb ?? u.elements[0].className)).toEqual(["0", "1", "sl-bg", "title"]);
  });

  it("finds nothing to play when no part of the stage is drawn yet", () => {
    const root = document.createElement("div");
    document.body.appendChild(root);
    expect(slideSteps({ type: "slides", previous: deck(slide("A")), next: deck(slide("B")), ops: null, initial: false, root })).toEqual([]);
  });
});
