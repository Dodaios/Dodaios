/**
 * What the Nodes library shows, as rules on plain lists.
 *
 * Contracts worth pinning:
 * - "All" is everything but the runs that left no page; those live under
 *   "Runs"; "Kept current" and "Favorites" cut across both,
 * - the counts on the tabs ignore search and type filter,
 * - a search matches every word, in the title, the request, the type or the
 *   file name,
 * - whatever is still building leads in every order,
 * - the "Make something new" row belongs to the untouched "All" tab only,
 * - a placeholder waits for ONE new card of its type and gives up after
 *   five minutes,
 * - a card's date is the time for today and the day otherwise.
 */
import { describe, expect, it } from "vitest";

import {
  PENDING_TTL_MS,
  cardWhen,
  countByTab,
  filterByTab,
  filterByType,
  isPendingCard,
  newPendingNode,
  nextPendingExpiry,
  pendingCard,
  pendingTitle,
  resolvePending,
  searchCards,
  showsNewRow,
  sortCards,
  typeFilterApplies,
  visibleCards,
} from "./libraryModel";
import type { NodeCard } from "./nodeModel";

function card(key: string, over: Partial<NodeCard> = {}): NodeCard {
  return {
    key,
    id: null,
    type: "docs",
    origin: "node",
    title: key,
    slug: key,
    path: "index.html",
    visual_kind: "page",
    created_at: 1_000,
    updated_at: 1_000,
    size: 10,
    version: 1,
    status: "ready",
    kept_current: false,
    refreshing: false,
    every_minutes: 0,
    request: "",
    preview: null,
    ...over,
  };
}

const keys = (cards: readonly NodeCard[]) => cards.map((item) => item.key);

const BRIEF = card("brief", { title: "Website brief", type: "docs", updated_at: 500, created_at: 100 });
const DECK = card("deck", { title: "Quarterly review", type: "slides", updated_at: 400, created_at: 400 });
const SHEET = card("sheet", {
  title: "Budget",
  type: "sheets",
  updated_at: 300,
  created_at: 50,
  kept_current: true,
  refreshing: true,
  request: "A budget for this year by month",
});
const LOGO = card("logo", {
  title: "Logo sketch",
  type: "design",
  origin: "file",
  path: "logo-sketch.png",
  visual_kind: "image",
  updated_at: 200,
  created_at: 200,
});
const RUN = card("run:tidy", {
  title: "Tidy the downloads",
  type: "output",
  origin: "run",
  path: null,
  visual_kind: null,
  updated_at: 600,
  created_at: 600,
});
const ALL = [BRIEF, DECK, SHEET, LOGO, RUN];
const NONE: ReadonlySet<string> = new Set();

describe("tabs", () => {
  it("keeps runs without a page out of All and under Runs", () => {
    expect(keys(filterByTab(ALL, "all", NONE))).toEqual(["brief", "deck", "sheet", "logo"]);
    expect(keys(filterByTab(ALL, "runs", NONE))).toEqual(["run:tidy"]);
  });

  it("shows what is kept current, and what is starred, whatever its type", () => {
    expect(keys(filterByTab(ALL, "kept", NONE))).toEqual(["sheet"]);
    expect(keys(filterByTab(ALL, "favorites", new Set(["deck", "run:tidy"])))).toEqual(["deck", "run:tidy"]);
  });

  it("counts every tab before search and type filter", () => {
    expect(countByTab(ALL, new Set(["deck", "run:tidy", "gone"]))).toEqual({
      all: 4,
      favorites: 2,
      kept: 1,
      runs: 1,
    });
    expect(countByTab([], NONE)).toEqual({ all: 0, favorites: 0, kept: 0, runs: 0 });
  });
});

describe("search and type filter", () => {
  it("matches every word across title, request, type and file name", () => {
    expect(keys(searchCards(ALL, "budget"))).toEqual(["sheet"]);
    expect(keys(searchCards(ALL, "BUDGET month"))).toEqual(["sheet"]);
    expect(keys(searchCards(ALL, "budget zebra"))).toEqual([]);
    expect(keys(searchCards(ALL, "slides"))).toEqual(["deck"]);
    expect(keys(searchCards(ALL, "sketch.png"))).toEqual(["logo"]);
    expect(keys(searchCards(ALL, "   "))).toEqual(keys(ALL));
  });

  it("narrows to one type, or leaves the list alone", () => {
    expect(keys(filterByType(ALL, "design"))).toEqual(["logo"]);
    expect(keys(filterByType(ALL, "all"))).toEqual(keys(ALL));
  });

  it("has no say on the Runs tab", () => {
    expect(typeFilterApplies("all", "sheets")).toBe(true);
    expect(typeFilterApplies("favorites", "sheets")).toBe(true);
    expect(typeFilterApplies("runs", "sheets")).toBe(false);
    expect(typeFilterApplies("all", "all")).toBe(false);
    const shown = visibleCards(ALL, { tab: "runs", favorites: NONE, query: "", type: "sheets", sort: "changed" });
    expect(keys(shown)).toEqual(["run:tidy"]);
  });
});

describe("order", () => {
  it("sorts by last change, by creation and by name", () => {
    expect(keys(sortCards(ALL, "changed"))).toEqual(["run:tidy", "brief", "deck", "sheet", "logo"]);
    expect(keys(sortCards(ALL, "newest"))).toEqual(["run:tidy", "deck", "logo", "brief", "sheet"]);
    expect(keys(sortCards(ALL, "name"))).toEqual(["sheet", "logo", "deck", "run:tidy", "brief"]);
  });

  it("lets whatever is still building lead in every order", () => {
    const building = card("zz", { title: "Zebra", status: "building", origin: "build", updated_at: 1 });
    for (const sort of ["changed", "newest", "name"] as const) {
      expect(keys(sortCards([...ALL, building], sort))[0]).toBe("zz");
    }
  });

  it("does not reorder the list it was given", () => {
    const input = [LOGO, BRIEF];
    sortCards(input, "changed");
    expect(keys(input)).toEqual(["logo", "brief"]);
  });

  it("applies tab, type, search and order together", () => {
    const shown = visibleCards(ALL, {
      tab: "all",
      favorites: NONE,
      query: "e",
      type: "all",
      sort: "name",
    });
    // "e" is in every title or type but the run's, which the tab leaves out.
    expect(keys(shown)).toEqual(["sheet", "logo", "deck", "brief"]);
    expect(
      keys(visibleCards(ALL, { tab: "all", favorites: NONE, query: "", type: "slides", sort: "changed" })),
    ).toEqual(["deck"]);
  });
});

describe("the new-row", () => {
  it("shows on the untouched All tab only", () => {
    expect(showsNewRow("all", "", "all")).toBe(true);
    expect(showsNewRow("all", "  ", "all")).toBe(true);
    expect(showsNewRow("all", "budget", "all")).toBe(false);
    expect(showsNewRow("all", "", "sheets")).toBe(false);
    expect(showsNewRow("favorites", "", "all")).toBe(false);
    expect(showsNewRow("runs", "", "all")).toBe(false);
  });
});

describe("placeholders", () => {
  const NOW = 1_800_000_000_000;

  it("is named after the first words of the request", () => {
    expect(pendingTitle("  A budget for this year  ")).toBe("A budget for this year");
    expect(pendingTitle("A budget for this year by month and by team")).toBe("A budget for this year by…");
    expect(pendingTitle("x".repeat(200))).toBe(`${"x".repeat(60)}…`);
  });

  it("is drawn as a building card of its type", () => {
    const pending = newPendingNode("sheets", " A budget ", ALL, NOW, 1);
    const shown = pendingCard(pending);
    expect(isPendingCard(shown)).toBe(true);
    expect(isPendingCard(SHEET)).toBe(false);
    expect(shown.type).toBe("sheets");
    expect(shown.status).toBe("building");
    expect(shown.title).toBe("A budget");
    expect(shown.request).toBe("A budget");
    expect(shown.id).toBeNull();
    expect(shown.path).toBeNull();
  });

  it("waits while nothing new of its type appears", () => {
    const pending = [newPendingNode("sheets", "A budget", ALL, NOW, 1)];
    // Unchanged lists come back as the same array: no state change, no render loop.
    expect(resolvePending(pending, ALL, NOW + 1_000)).toBe(pending);
    const otherType = [...ALL, card("new-deck", { type: "slides" })];
    expect(resolvePending(pending, otherType, NOW + 1_000)).toBe(pending);
  });

  it("is dropped when a new card of its type appears", () => {
    const pending = [newPendingNode("sheets", "A budget", ALL, NOW, 1)];
    const withNew = [card("new-sheet", { type: "sheets" }), ...ALL];
    expect(resolvePending(pending, withNew, NOW + 1_000)).toEqual([]);
  });

  it("gives up after five minutes", () => {
    const pending = [newPendingNode("sheets", "A budget", ALL, NOW, 1)];
    expect(resolvePending(pending, ALL, NOW + PENDING_TTL_MS - 1)).toBe(pending);
    expect(resolvePending(pending, ALL, NOW + PENDING_TTL_MS)).toEqual([]);
    expect(nextPendingExpiry(pending, NOW + 1_000)).toBe(PENDING_TTL_MS - 1_000);
    expect(nextPendingExpiry(pending, NOW + PENDING_TTL_MS + 5)).toBe(0);
    expect(nextPendingExpiry([], NOW)).toBeNull();
  });

  it("answers two requests of one type with two cards, not one", () => {
    const first = newPendingNode("sheets", "A budget", ALL, NOW, 1);
    const second = newPendingNode("sheets", "A tracker", ALL, NOW + 10, 2);
    const oneNew = [card("new-sheet", { type: "sheets" }), ...ALL];
    const afterOne = resolvePending([first, second], oneNew, NOW + 1_000);
    expect(afterOne.map((item) => item.title)).toEqual(["A tracker"]);
    // The card that answered the first request does not answer the second.
    expect(resolvePending(afterOne, oneNew, NOW + 2_000)).toBe(afterOne);
    const twoNew = [card("newer-sheet", { type: "sheets" }), ...oneNew];
    expect(resolvePending(afterOne, twoNew, NOW + 3_000)).toEqual([]);
  });
});

describe("the date on a card", () => {
  const now = new Date(2026, 10, 13, 15, 0).getTime();
  const at = (...parts: [number, number, number, number?, number?]) =>
    Math.floor(new Date(parts[0], parts[1], parts[2], parts[3] ?? 12, parts[4] ?? 0).getTime() / 1000);

  it("is the time for today", () => {
    expect(cardWhen(at(2026, 10, 13, 14, 20), now, "en-US", "Today, {0}")).toMatch(/^Today, 2:20\sPM$/);
    expect(cardWhen(at(2026, 10, 13, 14, 20), now, "de-DE", "Heute, {0}")).toBe("Heute, 14:20");
  });

  it("is the day otherwise, with the year once it is another one", () => {
    expect(cardWhen(at(2026, 10, 11), now, "en-US", "Today, {0}")).toBe("Nov 11");
    expect(cardWhen(at(2025, 2, 3), now, "en-US", "Today, {0}")).toBe("Mar 3, 2025");
  });

  it("is empty for a card without a time", () => {
    expect(cardWhen(0, now, "en-US", "Today, {0}")).toBe("");
  });
});
