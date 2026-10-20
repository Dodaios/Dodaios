/**
 * The gallery's rules — tabs, search, sort, date headings and where each tile
 * goes on the wall — pinned without rendering a single card.
 */
import { describe, expect, it } from "vitest";

import type { OutputSummary } from "@/hooks/useOutputs";
import type { VisualArtifact, VisualKind } from "@/hooks/useVisualArtifacts";
import {
  buildRailRows,
  countByFilter,
  dateGroupOf,
  featureIndex,
  filterRailRows,
  groupRailRows,
  layoutWall,
  searchRailRows,
  shapeForRatio,
  sortRailRows,
  suggestRows,
  tileShape,
  wallColumns,
} from "@/components/visualization/galleryModel";

const NOW = new Date(2026, 9, 1, 15, 0, 0).getTime();
const HOUR = 3600;
const nowS = NOW / 1000;

function visual(slug: string, title: string, kind: VisualKind, mtime: number): VisualArtifact {
  return {
    slug,
    path: `files/${title}`,
    name: title,
    title,
    kind,
    size: 1,
    mtime,
    url: `/x/${slug}`,
    status: "success",
    utterance: `Make ${title}`,
  };
}

function run(slug: string, over: Partial<OutputSummary> = {}): OutputSummary {
  return { slug, utterance: `Task ${slug}`, status: "success", completed_at: nowS - HOUR, ...over };
}

const VISUALS = [
  visual("a", "Sales map", "page", nowS - 2 * HOUR),
  visual("b", "Logo", "vector", nowS - 30 * HOUR),
  visual("c", "Report", "document", nowS - 40 * 24 * HOUR),
];
const RUNS = [run("a"), run("b"), run("c"), run("d", { summary: "Refactored the parser" })];

describe("gallery model", () => {
  it("counts and filters by category", () => {
    const rows = buildRailRows(RUNS, VISUALS, []);
    expect(countByFilter(rows)).toEqual({
      suggested: 4,
      favorites: 0,
      pages: 1,
      images: 1,
      documents: 1,
      outputs: 1,
      all: 4,
    });
    expect(filterRailRows(rows, "images").map((r) => r.key)).toEqual(["b::files/Logo"]);
  });

  it("keeps the starred cards under Favorites and counts them", () => {
    const rows = buildRailRows(RUNS, VISUALS, []);
    const picks = { favorites: new Set(["c::files/Report", "run:d"]), now: NOW };
    expect(filterRailRows(rows, "favorites", picks).map((r) => r.key)).toEqual([
      "run:d",
      "c::files/Report",
    ]);
    expect(countByFilter(rows, picks).favorites).toBe(2);
    // A star on something that is gone counts for nothing.
    expect(countByFilter(rows, { favorites: new Set(["gone::x"]), now: NOW }).favorites).toBe(0);
  });

  it("suggests what is in progress, starred or new, and tops a quiet library up", () => {
    const old = (index: number) =>
      visual(`old${index}`, `Old ${index}`, "page", nowS - (30 + index) * 24 * HOUR);
    const many = Array.from({ length: 20 }, (_, index) => old(index));
    const fresh = visual("new", "Fresh", "page", nowS - HOUR);
    const building = run("wip", { status: "running", utterance: "Artifact: Board\nDraw it" });
    const rows = buildRailRows([building], [fresh, ...many], [building]);

    // Twelve at least: the build, the fresh page, then the newest of the old.
    const quiet = suggestRows(rows, { favorites: new Set(), now: NOW });
    expect(quiet).toHaveLength(12);
    expect(quiet.slice(0, 2).map((r) => r.key)).toEqual(["build:wip", "new::files/Fresh"]);
    expect(quiet.some((r) => r.key === "old19::files/Old 19")).toBe(false);

    // A star pulls an old card in, wherever it sits.
    const starred = suggestRows(rows, { favorites: new Set(["old19::files/Old 19"]), now: NOW });
    expect(starred.some((r) => r.key === "old19::files/Old 19")).toBe(true);
    expect(starred).toHaveLength(12);
  });

  it("shapes a tile by what it shows", () => {
    const [page, vector, document] = buildRailRows([], VISUALS, []);
    expect(tileShape(page)).toBe("square");
    expect(tileShape(document)).toBe("tall");
    // A picture follows its own proportions once they are known.
    expect(tileShape(vector)).toBe("square");
    expect(tileShape(vector, 2.4)).toBe("wide");
    expect(tileShape(vector, 0.6)).toBe("tall");
    expect(shapeForRatio(1)).toBe("square");
    // A page stays a square whatever a stale measurement says.
    expect(tileShape(page, 3)).toBe("square");
  });

  it("leads the wall with its first page, picture or drawing, never a note or a PDF", () => {
    const building = run("wip", { status: "running", utterance: "Artifact: Board\nDraw it" });
    const rows = buildRailRows([...RUNS, building], VISUALS, [building]);
    // rows: the build, the note (run d), then the page.
    expect(rows.map((r) => r.kind)).toEqual(["build", "run", "visual", "visual", "visual"]);
    expect(featureIndex(rows)).toBe(2);
    expect(featureIndex(rows.filter((r) => r.kind !== "visual"))).toBe(-1);
    // A drawing leads; a PDF in front of it is passed over.
    const sheets = buildRailRows(
      [],
      [visual("p", "Deck", "document", nowS - HOUR), visual("v", "Mark", "vector", nowS - 2 * HOUR)],
      [],
    );
    expect(featureIndex(sheets)).toBe(1);
    expect(featureIndex(sheets.slice(0, 1))).toBe(-1);
    // Too far down to lead anything.
    const notes = Array.from({ length: 6 }, (_, index) => run(`n${index}`));
    const buried = buildRailRows(notes, [visual("late", "Late", "page", nowS - 9 * HOUR)], []);
    expect(buried[6].kind).toBe("visual");
    expect(featureIndex(buried)).toBe(-1);
  });

  it("fits as many columns as the tile size allows, one at least", () => {
    expect(wallColumns(1000, 228, 16)).toBe(4);
    expect(wallColumns(1204, 228, 16)).toBe(5);
    expect(wallColumns(120, 228, 16)).toBe(1);
  });

  it("puts each tile into the shortest column on one half-tile lattice", () => {
    // Three columns of 100 with a gap of 10.
    const { boxes, height } = layoutWall(["square", "wide", "tall", "wide", "square"], 320, 3, 10);
    expect(boxes[0]).toEqual({ x: 0, y: 0, width: 100, height: 100 });
    expect(boxes[1]).toEqual({ x: 110, y: 0, width: 100, height: 45 });
    expect(boxes[2]).toEqual({ x: 220, y: 0, width: 100, height: 155 });
    // The second wide tile goes under the first: two of them make one square.
    expect(boxes[3]).toEqual({ x: 110, y: 55, width: 100, height: 45 });
    expect(boxes[3].y + boxes[3].height).toBe(boxes[0].height);
    // Columns one and two are level again; the leftmost takes the next tile.
    expect(boxes[4]).toEqual({ x: 0, y: 110, width: 100, height: 100 });
    expect(height).toBe(210);
  });

  it("gives a lead tile two columns and two rows, and falls back when there is one column", () => {
    const { boxes } = layoutWall(["square", "feature", "square"], 320, 3, 10);
    expect(boxes[1]).toEqual({ x: 110, y: 0, width: 210, height: 210 });
    // The next tile goes under the first, beside the lead.
    expect(boxes[2]).toEqual({ x: 0, y: 110, width: 100, height: 100 });
    const narrow = layoutWall(["feature", "square"], 100, 1, 10);
    expect(narrow.boxes[0]).toEqual({ x: 0, y: 0, width: 100, height: 100 });
    expect(narrow.boxes[1].y).toBe(110);
  });

  it("searches titles, requests and summaries with every word", () => {
    const rows = buildRailRows(RUNS, VISUALS, []);
    expect(searchRailRows(rows, "sales MAP")).toHaveLength(1);
    expect(searchRailRows(rows, "parser")).toHaveLength(1);
    expect(searchRailRows(rows, "sales parser")).toHaveLength(0);
  });

  it("sorts by name and keeps work in progress first", () => {
    const building = run("e", { status: "running", utterance: "Artifact: Zebra board\nDraw it" });
    const rows = buildRailRows([...RUNS, building], VISUALS, [building]);
    const titles = sortRailRows(rows, "name").map((r) =>
      r.kind === "visual" ? r.visual.title : r.run.slug,
    );
    expect(titles[0]).toBe("e");
    expect(titles.slice(1, 4)).toEqual(["Logo", "Report", "Sales map"]);
  });

  it("groups by day, newest first, with work in progress on top", () => {
    const building = run("e", { status: "running", utterance: "Artifact: Board\nDraw it" });
    const rows = sortRailRows(buildRailRows([...RUNS, building], VISUALS, [building]), "newest");
    const groups = groupRailRows(rows, "newest", NOW);
    expect(groups.map((g) => g.id)).toEqual(["active", "today", "yesterday", "earlier"]);
    expect(groupRailRows(sortRailRows(rows, "name"), "name", NOW).map((g) => g.id)).toEqual([
      "active",
      "all",
    ]);
  });

  it("places moments under the right heading", () => {
    expect(dateGroupOf(nowS - 60, NOW)).toBe("today");
    expect(dateGroupOf(nowS - 24 * HOUR, NOW)).toBe("yesterday");
    expect(dateGroupOf(nowS - 4 * 24 * HOUR, NOW)).toBe("week");
    expect(dateGroupOf(nowS - 20 * 24 * HOUR, NOW)).toBe("month");
    expect(dateGroupOf(nowS - 90 * 24 * HOUR, NOW)).toBe("earlier");
  });
});
