/**
 * The pure model behind the Artifacts gallery — which cards exist, which a
 * category or a search lets through, in what order, under which date heading.
 *
 * No React and no fetching: the view hands in the runs and visuals it read,
 * this module turns them into cards. Kept separate so the ordering rules are
 * testable without rendering a single iframe.
 */
import type { OutputSummary } from "@/hooks/useOutputs";
import { cleanRequest, requestHeadline } from "@/lib/runRequest";
import { visualId, type VisualArtifact } from "@/hooks/useVisualArtifacts";

/** One card — a build in progress, an artifact, or a run without one. */
export type RailRow =
  | { kind: "build"; run: OutputSummary; key: string }
  | { kind: "visual"; run: OutputSummary | null; visual: VisualArtifact; key: string }
  | { kind: "run"; run: OutputSummary; key: string };

/**
 * The library's tabs. Two are picks ("suggested": what is in progress, what is
 * starred and what is new; "favorites": what the reader starred), four are
 * kinds, and "all" is everything.
 */
export type RailFilter =
  | "suggested"
  | "favorites"
  | "pages"
  | "images"
  | "documents"
  | "outputs"
  | "all";

export const RAIL_FILTERS: readonly RailFilter[] = [
  "suggested",
  "favorites",
  "pages",
  "images",
  "documents",
  "outputs",
  "all",
];

/** The kind a card belongs to — every tab that is not a pick or "all". */
export type RailCategory = "pages" | "images" | "documents" | "outputs";

/** What the two pick tabs need to know: the starred cards and the time. */
export interface PickContext {
  favorites: ReadonlySet<string>;
  /** Epoch milliseconds. */
  now: number;
}

const NO_PICKS: PickContext = { favorites: new Set(), now: 0 };

/** How the gallery orders its cards. */
export type GallerySort = "newest" | "oldest" | "name";

/** The date headings the gallery groups by when it sorts by time. */
export type GalleryGroupId = "active" | "today" | "yesterday" | "week" | "month" | "earlier" | "all";

export interface GalleryGroup {
  id: GalleryGroupId;
  rows: RailRow[];
}

/**
 * A `create_artifact` mission's prompt leads with `Artifact: <title>` and the
 * user's request right after (jarvis/artifacts/brief.py). The run list
 * already strips the quality lead, so the run's `utterance` starts with that
 * line — which is how a running build is recognised and labelled here.
 */
export function parseArtifactUtterance(
  utterance: string | undefined,
): { title: string; request: string } | null {
  const text = (utterance ?? "").trim();
  const match = /^Artifact:[ \t]*([^\n]+)/.exec(text);
  if (!match) return null;
  const rest = text.slice(match[0].length).trim();
  const request = rest.split(/\n\s*\n/)[0]?.trim() ?? "";
  return { title: match[1].trim(), request };
}

/** What a run is called when it has no page title of its own. */
export function runTitle(run: OutputSummary): string {
  return (
    parseArtifactUtterance(run.utterance)?.title || requestHeadline(run.utterance ?? "") || run.slug
  );
}

/** The run's moment for ordering — when it ended, else when it began. */
export function runWhen(run: OutputSummary): number {
  return run.completed_at ?? run.started_at ?? 0;
}

/** A card's moment, in epoch seconds. */
export function rowWhen(row: RailRow): number {
  return row.kind === "visual" ? row.visual.mtime : runWhen(row.run);
}

/** A card's title — the page's own `<title>`, the brief's title, or the request. */
export function rowTitle(row: RailRow): string {
  if (row.kind === "visual") return row.visual.title;
  return runTitle(row.run);
}

/** The user's words behind a card, cleaned of the brief's scaffolding. */
export function rowRequest(row: RailRow): string {
  const utterance = row.kind === "visual" ? row.visual.utterance : row.run.utterance;
  return parseArtifactUtterance(utterance)?.request || cleanRequest(utterance) || "";
}

/** Still being made — a build, or a run (or a run's page) that is running. */
export function isActiveRow(row: RailRow): boolean {
  if (row.kind === "build") return true;
  if (row.kind === "visual") return row.visual.status === "running";
  return row.run.status === "running";
}

/** The category a card belongs to (besides "all"). */
export function rowCategory(row: RailRow): RailCategory {
  if (row.kind === "build") return "pages";
  if (row.kind === "run") return "outputs";
  switch (row.visual.kind) {
    case "page":
      return "pages";
    case "document":
      return "documents";
    default:
      return "images";
  }
}

/**
 * The cards, in their natural order: builds in progress, then running runs,
 * then every artifact and every artifact-less run newest first. A run with at
 * least one artifact is reached through its artifact cards (its other files
 * sit behind the stage's Files tab), so it gets no card of its own.
 */
export function buildRailRows(
  runs: OutputSummary[],
  visuals: VisualArtifact[],
  building: OutputSummary[],
): RailRow[] {
  const bySlug = new Map(runs.map((run) => [run.slug, run]));
  const visualSlugs = new Set(visuals.map((v) => v.slug));
  const buildSlugs = new Set(building.map((r) => r.slug));

  const rest: Array<{ row: RailRow; running: boolean; when: number }> = [];
  for (const visual of visuals) {
    rest.push({
      row: { kind: "visual", run: bySlug.get(visual.slug) ?? null, visual, key: visualId(visual) },
      running: visual.status === "running",
      when: visual.mtime,
    });
  }
  for (const run of runs) {
    if (visualSlugs.has(run.slug) || buildSlugs.has(run.slug)) continue;
    rest.push({
      row: { kind: "run", run, key: `run:${run.slug}` },
      running: run.status === "running",
      when: runWhen(run),
    });
  }
  rest.sort((a, b) => Number(b.running) - Number(a.running) || b.when - a.when);

  return [
    ...building.map((run): RailRow => ({ kind: "build", run, key: `build:${run.slug}` })),
    ...rest.map((entry) => entry.row),
  ];
}

/** A week of work counts as new; a quiet library still suggests this many. */
const SUGGEST_WINDOW_S = 7 * 86_400;
const SUGGEST_MINIMUM = 12;

/**
 * The "Suggested" pick: everything in progress, everything starred and
 * everything from the last week — topped up with the newest older cards so a
 * library nobody touched this week still opens on a full wall. The order of
 * `rows` is kept.
 */
export function suggestRows(rows: RailRow[], picks: PickContext): RailRow[] {
  const since = picks.now / 1000 - SUGGEST_WINDOW_S;
  const chosen = new Set<string>();
  for (const row of rows) {
    if (isActiveRow(row) || picks.favorites.has(row.key) || rowWhen(row) >= since) {
      chosen.add(row.key);
    }
  }
  if (chosen.size < SUGGEST_MINIMUM) {
    const newest = [...rows].sort((a, b) => rowWhen(b) - rowWhen(a));
    for (const row of newest) {
      if (chosen.size >= SUGGEST_MINIMUM) break;
      chosen.add(row.key);
    }
  }
  return rows.filter((row) => chosen.has(row.key));
}

/** The cards a tab lets through. */
export function filterRailRows(
  rows: RailRow[],
  filter: RailFilter,
  picks: PickContext = NO_PICKS,
): RailRow[] {
  if (filter === "all") return rows;
  if (filter === "suggested") return suggestRows(rows, picks);
  if (filter === "favorites") return rows.filter((row) => picks.favorites.has(row.key));
  return rows.filter((row) => rowCategory(row) === filter);
}

/** How many cards each tab holds. */
export function countByFilter(
  rows: RailRow[],
  picks: PickContext = NO_PICKS,
): Record<RailFilter, number> {
  const counts: Record<RailFilter, number> = {
    suggested: suggestRows(rows, picks).length,
    favorites: 0,
    pages: 0,
    images: 0,
    documents: 0,
    outputs: 0,
    all: rows.length,
  };
  for (const row of rows) {
    counts[rowCategory(row)] += 1;
    if (picks.favorites.has(row.key)) counts.favorites += 1;
  }
  return counts;
}

/* ------------------------------------------------------------------------- */

/**
 * The shapes a tile on the wall can take. All of them sit on one half-tile
 * lattice — a wide tile is half a square, a tall one a square and a half — so
 * columns of mixed tiles keep falling back into line.
 */
export type TileShape = "wide" | "square" | "tall" | "feature";

/** The shape a picture of this width/height ratio is shown in. */
export function shapeForRatio(ratio: number): Exclude<TileShape, "feature"> {
  if (ratio >= 1.4) return "wide";
  if (ratio <= 0.8) return "tall";
  return "square";
}

/**
 * A card's shape on the wall. A picture follows its own proportions once they
 * are known (`ratio`), a PDF stands like the sheet it is, everything else is a
 * square.
 */
export function tileShape(row: RailRow, ratio?: number): Exclude<TileShape, "feature"> {
  if (row.kind !== "visual") return "square";
  if (row.visual.kind === "document") return "tall";
  const picture = row.visual.kind === "image" || row.visual.kind === "vector";
  if (picture && ratio !== undefined && ratio > 0) return shapeForRatio(ratio);
  return "square";
}

/** How far into the wall the lead tile may sit — behind work in progress, not behind half a row. */
const FEATURE_WITHIN = 3;

/**
 * Which card leads the wall as a tile of four: the first page or picture,
 * when it sits right at the top. -1 when nothing does — a wall that opens on
 * notes has no picture worth four tiles.
 */
export function featureIndex(rows: RailRow[]): number {
  const limit = Math.min(rows.length, FEATURE_WITHIN);
  for (let index = 0; index < limit; index += 1) {
    const row = rows[index];
    if (row.kind === "visual" && (row.visual.kind === "page" || row.visual.kind === "image")) {
      return index;
    }
  }
  return -1;
}

export interface TileBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** How many columns of at least `minimum` px fit into `width`. */
export function wallColumns(width: number, minimum: number, gap: number): number {
  return Math.max(1, Math.floor((width + gap) / (minimum + gap)));
}

/**
 * Where every tile goes: each one into the column that is shortest so far,
 * leftmost on a tie — reading order stays roughly left to right, top to
 * bottom, and no column runs away from the others. A "feature" tile takes two
 * columns side by side and is two squares high.
 */
export function layoutWall(
  shapes: TileShape[],
  width: number,
  columns: number,
  gap: number,
): { boxes: TileBox[]; height: number } {
  const count = Math.max(1, columns);
  const column = (width - gap * (count - 1)) / count;
  const heights = new Array<number>(count).fill(0);
  const boxes: TileBox[] = [];
  for (const wanted of shapes) {
    const shape = wanted === "feature" && count < 2 ? "square" : wanted;
    if (shape === "feature") {
      let at = 0;
      let top = Number.POSITIVE_INFINITY;
      for (let index = 0; index < count - 1; index += 1) {
        const candidate = Math.max(heights[index], heights[index + 1]);
        if (candidate < top) {
          top = candidate;
          at = index;
        }
      }
      const size = column * 2 + gap;
      boxes.push({ x: at * (column + gap), y: top, width: size, height: size });
      heights[at] = heights[at + 1] = top + size + gap;
      continue;
    }
    let at = 0;
    for (let index = 1; index < count; index += 1) {
      if (heights[index] < heights[at] - 0.5) at = index;
    }
    const height =
      shape === "wide" ? (column - gap) / 2 : shape === "tall" ? column * 1.5 + gap / 2 : column;
    boxes.push({ x: at * (column + gap), y: heights[at], width: column, height });
    heights[at] += height + gap;
  }
  return { boxes, height: Math.max(0, Math.max(...heights) - gap) };
}

/** Cards whose title, request, summary or filename contain every search word. */
export function searchRailRows(rows: RailRow[], query: string): RailRow[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return rows;
  return rows.filter((row) => {
    const haystack = [
      rowTitle(row),
      rowRequest(row),
      row.kind === "visual" ? row.visual.name : "",
      row.run?.summary ?? "",
      row.run?.slug ?? "",
    ]
      .join(" ")
      .toLowerCase();
    return words.every((word) => haystack.includes(word));
  });
}

/** The cards in the chosen order; work in progress always leads. */
export function sortRailRows(rows: RailRow[], sort: GallerySort): RailRow[] {
  const sorted = [...rows];
  sorted.sort((a, b) => {
    const active = Number(isActiveRow(b)) - Number(isActiveRow(a));
    if (active !== 0) return active;
    if (sort === "name") return rowTitle(a).localeCompare(rowTitle(b), undefined, { sensitivity: "base" });
    return sort === "oldest" ? rowWhen(a) - rowWhen(b) : rowWhen(b) - rowWhen(a);
  });
  return sorted;
}

function startOfDay(ms: number): number {
  const day = new Date(ms);
  day.setHours(0, 0, 0, 0);
  return day.getTime();
}

/** Which date heading a moment falls under, seen from `now`. */
export function dateGroupOf(seconds: number, now: number): GalleryGroupId {
  const ms = seconds * 1000;
  const today = startOfDay(now);
  const DAY = 86_400_000;
  if (ms >= today) return "today";
  if (ms >= today - DAY) return "yesterday";
  if (ms >= today - 6 * DAY) return "week";
  if (ms >= today - 29 * DAY) return "month";
  return "earlier";
}

/**
 * Sorted cards cut into headed groups: work in progress on top, then by date
 * when the order is by time. Sorting by name is one flat group — a date
 * heading over an alphabetical list would split it in random places.
 */
export function groupRailRows(rows: RailRow[], sort: GallerySort, now: number): GalleryGroup[] {
  const active = rows.filter(isActiveRow);
  const rest = rows.filter((row) => !isActiveRow(row));
  const groups: GalleryGroup[] = [];
  if (active.length > 0) groups.push({ id: "active", rows: active });
  if (sort === "name") {
    if (rest.length > 0) groups.push({ id: "all", rows: rest });
    return groups;
  }
  const byId = new Map<GalleryGroupId, RailRow[]>();
  for (const row of rest) {
    const id = dateGroupOf(rowWhen(row), now);
    const list = byId.get(id);
    if (list) list.push(row);
    else byId.set(id, [row]);
  }
  // Rows arrive sorted, so the groups appear in the same direction.
  for (const [id, list] of byId) groups.push({ id, rows: list });
  return groups;
}

/** "12 min ago" in the UI language — what tells two same-named cards apart. */
export function relativeWhen(seconds: number, now: number, language: string): string {
  if (!seconds) return "";
  const diff = Math.round(seconds - now / 1000);
  const abs = Math.abs(diff);
  const rtf = new Intl.RelativeTimeFormat(language, { numeric: "auto" });
  if (abs < 60) return rtf.format(0, "second");
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86_400) return rtf.format(Math.round(diff / 3600), "hour");
  if (abs < 7 * 86_400) return rtf.format(Math.round(diff / 86_400), "day");
  return new Date(seconds * 1000).toLocaleDateString(language, {
    month: "short",
    day: "numeric",
    year: abs > 300 * 86_400 ? "numeric" : undefined,
  });
}
