import { describe, expect, it } from "vitest";

import { produce } from "../produce";
import type { Deck } from "./deckModel";
import { findInDeck, replaceAll } from "./findReplace";

const DECK: Deck = {
  theme: "auto",
  slides: [
    { layout: "bullets", title: "Acme plan", bullets: ["acme one", "two"], notes: "Say ACME" },
    { layout: "table", title: "T", table: { columns: ["Acme"], rows: [["x acme"]] } },
    {
      layout: "blank",
      elements: [
        { type: "text", x: 0, y: 0, w: 10, h: 10, text: "Acme rocks" },
        { type: "table", x: 0, y: 0, w: 10, h: 10, rows: [["acme"]] },
        { type: "line", x1: 0, y1: 0, x2: 1, y2: 1 },
      ],
    },
    { layout: "closing", title: "Thanks" },
  ],
};

describe("find and replace", () => {
  it("finds a text in every field, list, table, element and note", () => {
    expect(findInDeck(DECK, "acme")).toEqual({ count: 7, slides: [0, 1, 2] });
    expect(findInDeck(DECK, "Acme", true).count).toBe(3);
    expect(findInDeck(DECK, "").count).toBe(0);
  });

  it("replaces everywhere on a draft and leaves the rest as it was", () => {
    let count = 0;
    const next = produce(DECK, (draft) => {
      count = replaceAll(draft, "acme", "Globex");
    });
    expect(count).toBe(7);
    expect(next.slides[0].title).toBe("Globex plan");
    expect(next.slides[0].notes).toBe("Say Globex");
    expect(next.slides[2].elements?.[0]).toMatchObject({ text: "Globex rocks" });
    expect(next.slides[3]).toBe(DECK.slides[3]);
    expect(findInDeck(next, "acme").count).toBe(0);
  });

  it("treats the query as plain text, not a pattern", () => {
    const deck: Deck = { theme: "auto", slides: [{ layout: "title", title: "a.b (c)" }] };
    expect(findInDeck(deck, ".").count).toBe(1);
    expect(findInDeck(deck, "(c)").count).toBe(1);
  });
});
