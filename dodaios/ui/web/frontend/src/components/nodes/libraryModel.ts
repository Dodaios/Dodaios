/**
 * What the Nodes library shows, as pure functions: which cards a tab holds,
 * what a search and a type filter leave of them, in what order, and what
 * happens to the placeholder of a node the assistant was just asked to make.
 *
 * Nothing here reads a clock, a store or the network: the hook
 * (`useNodesLibrary`) hands everything in, so every rule can be tested on
 * plain lists.
 */
import { NODE_TYPES, type NodeCard, type NodeType } from "./nodeModel";

export const LIBRARY_TABS = ["all", "favorites", "kept", "runs"] as const;
export type LibraryTab = (typeof LIBRARY_TABS)[number];

export const LIBRARY_SORTS = ["changed", "newest", "name"] as const;
export type LibrarySort = (typeof LIBRARY_SORTS)[number];

export const LIBRARY_VIEWS = ["grid", "list"] as const;
export type LibraryView = (typeof LIBRARY_VIEWS)[number];

/** The type filter: one of the seven node types, or no filter. */
export const TYPE_FILTERS = ["all", ...NODE_TYPES] as const;
export type TypeFilter = "all" | NodeType;

/**
 * The cards of one tab. "All" is the library proper: a run that left nothing
 * to look at (`type "output"`) lives under "Runs" and nowhere else, unless
 * the reader starred it.
 */
export function filterByTab(
  cards: readonly NodeCard[],
  tab: LibraryTab,
  favorites: ReadonlySet<string>,
): NodeCard[] {
  switch (tab) {
    case "favorites":
      return cards.filter((card) => favorites.has(card.key));
    case "kept":
      return cards.filter((card) => card.kept_current);
    case "runs":
      return cards.filter((card) => card.type === "output");
    default:
      return cards.filter((card) => card.type !== "output");
  }
}

/** How many cards each tab holds, before any search or type filter. */
export function countByTab(
  cards: readonly NodeCard[],
  favorites: ReadonlySet<string>,
): Record<LibraryTab, number> {
  const counts: Record<LibraryTab, number> = { all: 0, favorites: 0, kept: 0, runs: 0 };
  for (const card of cards) {
    if (card.type === "output") counts.runs += 1;
    else counts.all += 1;
    if (card.kept_current) counts.kept += 1;
    if (favorites.has(card.key)) counts.favorites += 1;
  }
  return counts;
}

/** The cards of one type; "all" leaves the list as it is. */
export function filterByType(cards: readonly NodeCard[], type: TypeFilter): NodeCard[] {
  if (type === "all") return [...cards];
  return cards.filter((card) => card.type === type);
}

/** The type filter has no say on the "Runs" tab: a run has no node type. */
export function typeFilterApplies(tab: LibraryTab, type: TypeFilter): boolean {
  return type !== "all" && tab !== "runs";
}

/** Cards whose title, request, type or file name contain every search word. */
export function searchCards(cards: readonly NodeCard[], query: string): NodeCard[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [...cards];
  return cards.filter((card) => {
    const haystack = [card.title, card.request, card.type, card.path ?? ""].join(" ").toLowerCase();
    return words.every((word) => haystack.includes(word));
  });
}

/**
 * The cards in the chosen order. Whatever is still being built leads in
 * every order: it is what the reader is waiting for.
 */
export function sortCards(cards: readonly NodeCard[], sort: LibrarySort): NodeCard[] {
  const sorted = [...cards];
  sorted.sort((a, b) => {
    const building = Number(b.status === "building") - Number(a.status === "building");
    if (building !== 0) return building;
    if (sort === "name") {
      const byName = a.title.localeCompare(b.title, undefined, { sensitivity: "base", numeric: true });
      if (byName !== 0) return byName;
    } else if (sort === "newest") {
      if (a.created_at !== b.created_at) return b.created_at - a.created_at;
    }
    if (a.updated_at !== b.updated_at) return b.updated_at - a.updated_at;
    return a.key.localeCompare(b.key);
  });
  return sorted;
}

export interface LibraryQuery {
  tab: LibraryTab;
  favorites: ReadonlySet<string>;
  query: string;
  type: TypeFilter;
  sort: LibrarySort;
}

/** The library as shown: the tab, then the type, then the search, then the order. */
export function visibleCards(cards: readonly NodeCard[], q: LibraryQuery): NodeCard[] {
  const inTab = filterByTab(cards, q.tab, q.favorites);
  const ofType = typeFilterApplies(q.tab, q.type) ? filterByType(inTab, q.type) : inTab;
  return sortCards(searchCards(ofType, q.query), q.sort);
}

/**
 * The shelf of types narrows the library by type, so it is shown wherever a
 * type means something: on every tab but "Runs" (a run has no node type).
 */
export function showsTypeRow(tab: LibraryTab): boolean {
  return tab !== "runs";
}

/** How many cards of each node type a list holds (runs are not counted). */
export function countByType(cards: readonly NodeCard[]): Partial<Record<NodeType, number>> {
  const counts: Partial<Record<NodeType, number>> = {};
  for (const card of cards) {
    if (card.type === "output") continue;
    counts[card.type] = (counts[card.type] ?? 0) + 1;
  }
  return counts;
}

/* --- a node the assistant was asked to make, before it exists ------------- */

/** How long a placeholder waits for its node before it gives up. */
export const PENDING_TTL_MS = 5 * 60_000;
const PENDING_KEY_PREFIX = "pending:";
const PENDING_TITLE_WORDS = 6;
const PENDING_TITLE_CHARS = 60;

export interface PendingNode {
  key: string;
  type: NodeType;
  title: string;
  /** What the reader asked for, in full. */
  request: string;
  /** Milliseconds since the epoch. */
  createdAt: number;
  /** The cards that were already there, so a NEW one of the type is recognised. */
  knownKeys: string[];
}

/** The first words of a request: what the placeholder is called meanwhile. */
export function pendingTitle(request: string): string {
  const words = request.trim().split(/\s+/).filter(Boolean);
  const head = words.slice(0, PENDING_TITLE_WORDS).join(" ");
  const clipped = head.length > PENDING_TITLE_CHARS ? head.slice(0, PENDING_TITLE_CHARS).trimEnd() : head;
  return words.length > PENDING_TITLE_WORDS || clipped.length < head.length ? `${clipped}…` : clipped;
}

export function newPendingNode(
  type: NodeType,
  request: string,
  cards: readonly NodeCard[],
  now: number,
  serial: number,
): PendingNode {
  return {
    key: `${PENDING_KEY_PREFIX}${now}:${serial}`,
    type,
    title: pendingTitle(request),
    request: request.trim(),
    createdAt: now,
    knownKeys: cards.map((card) => card.key),
  };
}

export function isPendingCard(card: NodeCard): boolean {
  return card.key.startsWith(PENDING_KEY_PREFIX);
}

/** The placeholder in the shape of a card, so the grid draws it like one. */
export function pendingCard(pending: PendingNode): NodeCard {
  const seconds = Math.floor(pending.createdAt / 1000);
  return {
    key: pending.key,
    id: null,
    type: pending.type,
    origin: "build",
    title: pending.title,
    slug: "",
    path: null,
    visual_kind: null,
    created_at: seconds,
    updated_at: seconds,
    size: 0,
    version: 0,
    status: "building",
    kept_current: false,
    refreshing: false,
    every_minutes: 0,
    request: pending.request,
    preview: null,
  };
}

/**
 * The placeholders still waiting. One is dropped when a card of its type
 * appears that was not there when it was registered, or when it has waited
 * `PENDING_TTL_MS`. A new card answers ONE placeholder (the oldest): two
 * requests for a sheet wait for two sheets.
 *
 * Returns the same array when nothing changed, so a caller can keep it in
 * state without a render loop.
 */
export function resolvePending(
  pending: readonly PendingNode[],
  cards: readonly NodeCard[],
  now: number,
): readonly PendingNode[] {
  if (pending.length === 0) return pending;
  const claimed = new Set<string>();
  let changed = false;
  const waiting: PendingNode[] = [];
  for (const item of [...pending].sort((a, b) => a.createdAt - b.createdAt)) {
    if (now - item.createdAt >= PENDING_TTL_MS) {
      changed = true;
      continue;
    }
    const known = new Set(item.knownKeys);
    const answer = cards.find(
      (card) => card.type === item.type && !known.has(card.key) && !claimed.has(card.key),
    );
    if (answer) {
      claimed.add(answer.key);
      changed = true;
      continue;
    }
    waiting.push(item);
  }
  if (!changed) return pending;
  if (claimed.size === 0) return waiting;
  // A card that answered one placeholder is old news to the ones still waiting.
  return waiting.map((item) => ({ ...item, knownKeys: [...item.knownKeys, ...claimed] }));
}

/** When the next placeholder gives up, in ms from `now` (null: none waits). */
export function nextPendingExpiry(pending: readonly PendingNode[], now: number): number | null {
  if (pending.length === 0) return null;
  const earliest = Math.min(...pending.map((item) => item.createdAt));
  return Math.max(0, earliest + PENDING_TTL_MS - now);
}

/* --- the date on a card --------------------------------------------------- */

function startOfDay(ms: number): number {
  const day = new Date(ms);
  day.setHours(0, 0, 0, 0);
  return day.getTime();
}

/**
 * The date on a card: the time for today ("Today, 14:20", from
 * `todayTemplate` with `{0}` for the time), the day otherwise ("Nov 11"),
 * with the year once it is no longer obvious.
 */
export function cardWhen(seconds: number, now: number, locale: string, todayTemplate: string): string {
  if (!seconds) return "";
  const ms = seconds * 1000;
  const date = new Date(ms);
  if (ms >= startOfDay(now) && ms < startOfDay(now) + 86_400_000) {
    const time = date.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
    return todayTemplate.replace("{0}", time);
  }
  const sameYear = date.getFullYear() === new Date(now).getFullYear();
  return date.toLocaleDateString(locale, {
    month: "short",
    day: "numeric",
    year: sameYear ? undefined : "numeric",
  });
}
