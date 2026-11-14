/** The deck model: reading a spec, new slides, layout switches and moves. */
import { describe, expect, it } from "vitest";

import {
  accentColor,
  blankSlide,
  indexAfterMove,
  LAYOUT_FIELDS,
  LAYOUTS,
  moveSlide,
  readAmount,
  readDeck,
  switchLayout,
  type Deck,
  type Slide,
  type Translate,
} from "./deckModel";
import { cssForShadow } from "./deckPage";

const t: Translate = (key, vars) => (vars ? `${key}:${JSON.stringify(vars)}` : key);

describe("readDeck", () => {
  it("keeps what the page draws and nothing it does not", () => {
    const deck = readDeck({
      theme: "neon",
      accent: "green",
      slides: [
        { layout: "bullets", title: "T", bullets: ["a", 3, null], extra: 1 },
        { layout: "nope", title: "dropped" },
        { layout: "table", table: { columns: ["A", "B"], rows: [["1"], ["2", "3", "4"]] } },
        { layout: "image", image: "data:image/png;base64,AA==", fit: "contain" },
        "not a slide",
      ],
    });
    expect(deck.theme).toBe("auto");
    expect(deck.accent).toBe("green");
    expect(deck.slides).toEqual([
      { layout: "bullets", title: "T", bullets: ["a", "3"] },
      { layout: "table", table: { columns: ["A", "B"], rows: [["1", ""], ["2", "3"]] } },
      { layout: "image", image: "data:image/png;base64,AA==", fit: "contain" },
    ]);
  });

  it("survives a spec that is not a deck at all", () => {
    expect(readDeck(null)).toEqual({ theme: "auto", slides: [] });
    expect(readDeck([1, 2])).toEqual({ theme: "auto", slides: [] });
  });
});

describe("blankSlide", () => {
  it("fills every layout's main field, so the server keeps the slide", () => {
    for (const layout of LAYOUTS) {
      const slide = blankSlide(layout, t);
      expect(slide.layout).toBe(layout);
      for (const key of Object.keys(slide)) expect([...LAYOUT_FIELDS[layout], "layout"]).toContain(key);
    }
    expect(blankSlide("stats", t).stats?.length).toBe(2);
    expect(blankSlide("chart", t).chart?.series?.[0].data).toEqual([12, 18, 24]);
    // An image slide gets its picture from the person before it is added.
    expect(blankSlide("image", t).image).toBeUndefined();
  });
});

describe("switchLayout", () => {
  const points: Slide = { layout: "bullets", kicker: "K", title: "Plan", text: "Why", bullets: ["Grow 18%", "Hire 4", "Ship app"], notes: "Say it" };

  it("moves points into steps, figures and closing points", () => {
    const steps = switchLayout(points, "steps", t);
    expect(steps).toEqual({
      layout: "steps",
      kicker: "K",
      title: "Plan",
      steps: [{ title: "Grow 18%" }, { title: "Hire 4" }, { title: "Ship app" }],
      notes: "Say it",
    });
    const stats = switchLayout(points, "stats", t);
    expect(stats.stats?.[0]).toEqual({ value: "18%", label: "Grow 18%" });
    expect(stats.stats?.[2]).toEqual({ value: "0", label: "Ship app" });
    const closing = switchLayout(points, "closing", t);
    expect(closing.bullets).toEqual(points.bullets);
    expect(closing.subtitle).toBe("Why");
  });

  it("shares many points over two columns and few points one per column", () => {
    const many = switchLayout({ ...points, bullets: ["a", "b", "c", "d", "e"] }, "columns", t);
    expect(many.columns).toEqual([{ bullets: ["a", "b", "c"] }, { bullets: ["d", "e"] }]);
    const few = switchLayout({ ...points, bullets: ["a", "b"] }, "columns", t);
    expect(few.columns).toEqual([{ title: "a" }, { title: "b" }]);
  });

  it("turns figures or a table into a chart and a chart into a table", () => {
    const figures: Slide = { layout: "stats", title: "Q", stats: [{ value: "€4.2M", label: "Q1" }, { value: "1,200", label: "Q2" }] };
    expect(switchLayout(figures, "chart", t).chart).toEqual({ type: "column", x: ["Q1", "Q2"], series: [{ data: [4.2, 1200] }] });
    const table: Slide = { layout: "table", title: "T", table: { columns: ["Month", "Sales", "Note"], rows: [["Jan", "10", "x"], ["Feb", "12", "y"]] } };
    expect(switchLayout(table, "chart", t).chart).toEqual({ type: "column", x: ["Jan", "Feb"], series: [{ name: "Sales", data: [10, 12] }] });
    const chart: Slide = { layout: "chart", title: "C", chart: { type: "line", x: ["a", "b"], series: [{ name: "S", data: [1, null] }] } };
    expect(switchLayout(chart, "table", t).table).toEqual({ columns: ["", "S"], rows: [["a", "1"], ["b", ""]] });
  });

  it("carries a short text between subtitle, text and quote", () => {
    const opening: Slide = { layout: "title", title: "Deck", subtitle: "The plan for Q4" };
    expect(switchLayout(opening, "bullets", t)).toEqual({ layout: "bullets", title: "Deck", text: "The plan for Q4" });
    expect(switchLayout(opening, "quote", t)).toEqual({ layout: "quote", quote: "The plan for Q4" });
    expect(switchLayout({ layout: "quote", quote: "Less is more", by: "M" }, "section", t)).toEqual({ layout: "section", title: "Less is more" });
  });

  it("keeps a picture and gives an empty main field the sample of a new slide", () => {
    const picture: Slide = { layout: "image", title: "Shot", image: "data:image/png;base64,AA==", fit: "contain", caption: "c" };
    expect(switchLayout(picture, "chart", t).chart).toEqual(blankSlide("chart", t).chart);
    expect(switchLayout(switchLayout(picture, "bullets", t), "image", t).image).toBeUndefined();
    expect(switchLayout(picture, "table", t)).toMatchObject({ layout: "table", title: "Shot", caption: "c" });
    expect(switchLayout(picture, "image", t)).toBe(picture);
  });

  it("never leaves a field the new layout does not show", () => {
    for (const from of LAYOUTS) {
      for (const to of LAYOUTS.filter((layout) => layout !== from)) {
        const next = switchLayout({ ...blankSlide(from, t), image: "data:image/png;base64,AA==", notes: "n" }, to, t);
        for (const key of Object.keys(next)) expect([...LAYOUT_FIELDS[to], "layout", "notes"]).toContain(key);
      }
    }
  });
});

describe("moves", () => {
  it("moves a slide and follows any index through the move", () => {
    const deck: Deck = { theme: "auto", slides: ["a", "b", "c", "d"].map((title) => ({ layout: "section" as const, title })) };
    moveSlide(deck, 0, 2);
    expect(deck.slides.map((s) => s.title)).toEqual(["b", "c", "a", "d"]);
    moveSlide(deck, 3, 0);
    expect(deck.slides.map((s) => s.title)).toEqual(["d", "b", "c", "a"]);
    moveSlide(deck, 1, 99);
    expect(deck.slides.map((s) => s.title)).toEqual(["d", "c", "a", "b"]);
    expect(indexAfterMove(0, 0, 2)).toBe(2);
    expect(indexAfterMove(1, 0, 2)).toBe(0);
    expect(indexAfterMove(3, 0, 2)).toBe(3);
    expect(indexAfterMove(1, 3, 0)).toBe(2);
  });
});

describe("helpers", () => {
  it("reads amounts the way people write them", () => {
    expect(readAmount("€4.2M")).toBe(4.2);
    expect(readAmount("1.200")).toBe(1200);
    expect(readAmount("1.234,5")).toBe(1234.5);
    expect(readAmount("40,62")).toBe(40.62);
    expect(readAmount("−3")).toBe(-3);
    expect(readAmount("n/a")).toBeNull();
  });

  it("maps accents to the page's colours and refuses anything else", () => {
    expect(accentColor("green")).toBe("var(--s3)");
    expect(accentColor("#e4572e")).toBe("#e4572e");
    expect(accentColor("red;background:url(x)")).toBe("");
    expect(accentColor(undefined)).toBe("");
  });

  it("moves the page's theme tokens from :root onto the shadow host", () => {
    expect(cssForShadow(':root{--bg:#fff}:root:not([data-theme="light"]){--bg:#000}:root[data-theme="dark"] .x{a:b}')).toBe(
      ':host{--bg:#fff}:host(:not([data-theme="light"])){--bg:#000}:host([data-theme="dark"]) .x{a:b}',
    );
  });
});
