/**
 * Find and replace across a whole deck: every text a person wrote, in the
 * layouts' fields, the lists, the tables, the free elements and the speaker
 * notes. Pure functions over the deck; `replaceAll` mutates a draft.
 */
import type { Deck, Slide } from "./deckModel";

function escapeRe(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function finder(query: string, matchCase: boolean): RegExp | null {
  if (!query) return null;
  return new RegExp(escapeRe(query), matchCase ? "g" : "gi");
}

/** Every string place of a slide, as [holder, key] pairs (so a draft can be written). */
function places(slide: Slide): [Record<string | number, unknown>, string | number][] {
  const found: [Record<string | number, unknown>, string | number][] = [];
  const add = (holder: unknown, key: string | number) => {
    if (holder && typeof holder === "object" && typeof (holder as Record<string | number, unknown>)[key] === "string") {
      found.push([holder as Record<string | number, unknown>, key]);
    }
  };
  const record = slide as unknown as Record<string, unknown>;
  for (const key of ["kicker", "title", "subtitle", "text", "quote", "by", "caption", "notes"]) add(record, key);
  slide.bullets?.forEach((_, i) => add(slide.bullets, i));
  slide.columns?.forEach((column) => {
    add(column, "title");
    add(column, "text");
    column.bullets?.forEach((_, i) => add(column.bullets, i));
  });
  slide.stats?.forEach((stat) => ["value", "label", "detail"].forEach((key) => add(stat, key)));
  slide.steps?.forEach((step) => ["title", "text"].forEach((key) => add(step, key)));
  slide.table?.columns.forEach((_, i) => add(slide.table!.columns, i));
  slide.table?.rows.forEach((row) => row.forEach((_, i) => add(row, i)));
  slide.elements?.forEach((element) => {
    if (element.type === "text" || element.type === "shape") add(element, "text");
    if (element.type === "table") element.rows.forEach((row) => row.forEach((_, i) => add(row, i)));
  });
  return found;
}

/** How often `query` occurs in the deck, and on which slides (indices). */
export function findInDeck(deck: Deck, query: string, matchCase = false): { count: number; slides: number[] } {
  const re = finder(query, matchCase);
  if (!re) return { count: 0, slides: [] };
  let count = 0;
  const slides: number[] = [];
  deck.slides.forEach((slide, index) => {
    let here = 0;
    for (const [holder, key] of places(slide)) here += (String(holder[key]).match(re) ?? []).length;
    if (here) slides.push(index);
    count += here;
  });
  return { count, slides };
}

/** Replace every occurrence of `query` with `replacement` (on a draft); returns how many. */
export function replaceAll(deck: Deck, query: string, replacement: string, matchCase = false): number {
  const re = finder(query, matchCase);
  if (!re) return 0;
  let count = 0;
  for (const slide of deck.slides) {
    for (const [holder, key] of places(slide)) {
      const text = String(holder[key]);
      const hits = (text.match(re) ?? []).length;
      if (!hits) continue;
      count += hits;
      holder[key] = text.replace(re, () => replacement);
    }
  }
  return count;
}
