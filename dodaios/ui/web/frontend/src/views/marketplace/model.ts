/**
 * The marketplace as data: one flat entry shape for the three published kinds,
 * and the pure rules the store applies to it (search, filter, order).
 *
 * Nothing here renders. The view files draw what these functions decide, so
 * the rules can be tested without a DOM.
 */
import type { AgentTemplateWire } from "@/lib/agentShare";
import type { SectionId } from "@/store/events";
import type {
  CommunityAgentWire,
  CommunityPluginWire,
  CommunityResponse,
  CommunitySkillWire,
} from "@/views/PluginsCommunity";

export type Kind = "plugin" | "skill" | "agent";
export type StoreFilter = "all" | Kind | "installed" | "mine";

export const KINDS: readonly Kind[] = ["plugin", "skill", "agent"];

/** One entry of any kind, flattened into what the store draws. */
export interface Entry {
  kind: Kind;
  /** The registry name — the id every API route takes. */
  name: string;
  title: string;
  /** Null when the index carries nothing readable (a leaked `|`, a blank). */
  description: string | null;
  publisher?: string | null;
  /** The publisher's numeric GitHub id, when the index carries it. */
  publisherId?: number | null;
  version?: string | null;
  publishedAt?: string | null;
  categories: string[];
  sourceUrl?: string | null;
  installed: boolean;
  /** Plugins only: the installed version differs from the published one. */
  updateAvailable?: boolean;
  installedVersion?: string | null;
  featured?: boolean;
  /** Plugins only — the brand tile. */
  logoSlug?: string | null;
  logoUrl?: string | null;
  logoColor?: string | null;
  /** An entry whose manifest this client could not read. */
  broken?: boolean;
  problem?: string | null;
  /**
   * Where installing this would eventually send data, or what it would run.
   *
   * The registry merges submissions that pass automated checks, so the only
   * honest consent is showing the destination verbatim before the button is
   * pressed (hosted URL / local command / neither).
   */
  mcp?: { transport?: string; url?: string; install?: string[] } | null;
  /** How connecting works, once installed. Plugins only. */
  authMode?: string | null;
  /** A plugin the shipped catalog already carries under this name. */
  seedConflict?: boolean;
  /** Skills only: a portable Agent Skill states the agents it also runs in. */
  portableAgents?: string[] | null;
  /** Agents only: the template the install turns into a new teammate. */
  agent?: AgentTemplateWire | null;
  /** Plugins only: the publisher's note on what to do after installing. */
  postInstallHint?: string | null;
  /**
   * This install just published it and the live feed does not list it yet:
   * the registry checks are running ("checking"), refused it ("failed"), or
   * passed and the feed is catching up ("published"). Not installable yet.
   */
  pending?: "checking" | "failed" | "published" | null;
  pendingProblems?: string[];
}

/** Where an installed entry of this kind lives in the app. */
export const HOME_SECTION: Record<Kind, SectionId> = {
  plugin: "plugins",
  skill: "skills",
  agent: "agents",
};

/**
 * A description worth printing, or null.
 *
 * The index generator has served a bare YAML block marker (`"|"`) as a
 * description; a row that prints one stray bar reads as broken. Anything with
 * no letter or digit in it is treated as missing.
 */
export function readableText(raw: string | null | undefined): string | null {
  const text = (raw ?? "").trim();
  return /[\p{L}\p{N}]/u.test(text) ? text : null;
}

function publisherId(raw: unknown): number | null {
  return typeof raw === "number" && Number.isFinite(raw) && raw > 0 ? raw : null;
}

export function pluginEntry(p: CommunityPluginWire): Entry {
  const raw = (p.logo_color ?? "").trim();
  const installedVersion = p.installed_version ?? null;
  return {
    kind: "plugin",
    name: p.id ?? p.name,
    title: p.display_name ?? p.name,
    description: readableText(p.description),
    publisher: p.publisher,
    publisherId: publisherId(p.publisher_id),
    version: p.version,
    publishedAt: p.published_at ?? null,
    categories: p.category ? [p.category] : [],
    sourceUrl: p.source_url,
    installed: Boolean(p.installed),
    installedVersion,
    updateAvailable: Boolean(
      p.installed && installedVersion && p.version && installedVersion !== p.version,
    ),
    featured: Boolean(p.featured),
    logoSlug: p.logo_slug ?? null,
    logoUrl: p.logo_url ?? null,
    logoColor: /^[0-9a-fA-F]{6}$/.test(raw) ? `#${raw}` : null,
    broken: !p.valid,
    problem: p.error ?? null,
    mcp: p.mcp_server ?? null,
    authMode: p.auth?.mode ?? null,
    seedConflict: Boolean(p.seed_conflict),
    postInstallHint: readableText(p.post_install_hint_md),
    pending: p.pending ?? null,
    pendingProblems: p.pending_problems ?? [],
  };
}

export function skillEntry(s: CommunitySkillWire): Entry {
  return {
    kind: "skill",
    name: s.name,
    title: s.title || s.name,
    description: readableText(s.description),
    publisher: s.publisher,
    publisherId: publisherId(s.publisher_id),
    version: s.version,
    publishedAt: s.published_at ?? null,
    categories: s.categories ?? [],
    sourceUrl: s.source_url,
    installed: Boolean(s.installed),
    featured: Boolean(s.featured),
    portableAgents: s.flavor === "portable" ? (s.compatible_agents ?? []) : null,
    pending: s.pending ?? null,
    pendingProblems: s.pending_problems ?? [],
  };
}

export function agentEntry(a: CommunityAgentWire): Entry {
  return {
    kind: "agent",
    name: a.name,
    title: a.title || a.name,
    description: readableText(a.description),
    publisher: a.publisher,
    publisherId: publisherId(a.publisher_id),
    version: a.version,
    publishedAt: a.published_at ?? null,
    categories: a.categories ?? [],
    sourceUrl: a.source_url,
    installed: Boolean(a.installed),
    featured: Boolean(a.featured),
    broken: !a.valid,
    problem: a.error ?? null,
    agent: a.agent,
  };
}

/** Featured first, then the newest publication, then by name. */
export function storeOrder(a: Entry, b: Entry): number {
  // What you just published comes first, so you see it the moment you return.
  if (Boolean(a.pending) !== Boolean(b.pending)) return a.pending ? -1 : 1;
  if (Boolean(a.featured) !== Boolean(b.featured)) return a.featured ? -1 : 1;
  const at = a.publishedAt ? Date.parse(a.publishedAt) : 0;
  const bt = b.publishedAt ? Date.parse(b.publishedAt) : 0;
  if (at !== bt) return bt - at;
  return a.title.localeCompare(b.title);
}

/** Every published entry of an index answer, in store order. */
export function entriesOf(data: CommunityResponse | undefined): Entry[] {
  if (!data) return [];
  return [
    ...(data.plugins ?? []).map(pluginEntry),
    ...(data.skills ?? []).map(skillEntry),
    ...(data.agents ?? []).map(agentEntry),
  ].sort(storeOrder);
}

/** The stable key of an entry: a plugin and a skill may share a name. */
export function entryKey(entry: Pick<Entry, "kind" | "name">): string {
  return `${entry.kind}:${entry.name}`;
}

/**
 * How well an entry answers a search, or 0 when it does not.
 *
 * Every word of the query has to appear somewhere. A hit in the title outranks
 * one in the description, and a title that starts with the query outranks
 * both, so typing a name brings that entry to the top rather than every entry
 * that mentions it.
 */
export function searchScore(entry: Entry, query: string): number {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return 1;
  const title = entry.title.toLowerCase();
  const name = entry.name.toLowerCase();
  const rest = [entry.description ?? "", entry.publisher ?? "", entry.categories.join(" ")]
    .join(" ")
    .toLowerCase();
  let score = 0;
  for (const word of words) {
    if (title.startsWith(word) || name.startsWith(word)) score += 8;
    else if (title.includes(word) || name.includes(word)) score += 4;
    else if (rest.includes(word)) score += 1;
    else return 0;
  }
  return score;
}

/** The entries a search leaves, best match first; store order when unsearched. */
export function searchEntries(entries: Entry[], query: string): Entry[] {
  if (!query.trim()) return entries;
  return entries
    .map((entry, index) => ({ entry, index, score: searchScore(entry, query) }))
    .filter((hit) => hit.score > 0)
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map((hit) => hit.entry);
}

export function passesFilter(entry: Entry, filter: StoreFilter, login: string | null): boolean {
  switch (filter) {
    case "all":
      return true;
    case "installed":
      return entry.installed;
    case "mine":
      return login !== null && entry.publisher === login;
    default:
      return entry.kind === filter;
  }
}

/** How many entries each filter would show — after the search, so it never lies. */
export function filterCounts(entries: Entry[], login: string | null): Record<StoreFilter, number> {
  const count = (filter: StoreFilter) =>
    entries.filter((entry) => passesFilter(entry, filter, login)).length;
  return {
    all: entries.length,
    plugin: count("plugin"),
    skill: count("skill"),
    agent: count("agent"),
    installed: count("installed"),
    mine: login ? count("mine") : 0,
  };
}

/** Registry category slugs ("productivity") read as labels ("Productivity"). */
export function categoryLabel(category: string): string {
  const spaced = category.replace(/[-_]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Up to two letters that stand for a title: "Three Bullet Brief" → "TB". */
export function monogram(title: string): string {
  const words = title.trim().split(/[\s._-]+/).filter(Boolean);
  if (words.length === 0) return "?";
  const first = Array.from(words[0])[0] ?? "";
  const second = words.length > 1 ? (Array.from(words[1])[0] ?? "") : "";
  return (first + second).toUpperCase();
}

/** A hue that belongs to a name: the same entry is the same colour everywhere. */
export function nameHue(name: string): number {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + (ch.codePointAt(0) ?? 0)) % 360;
  // Twelve steps: enough to tell neighbours apart, few enough to stay a palette.
  return Math.round(hash / 30) * 30;
}

/** What `POST /community/install/{name}` answers — the honest landing report. */
export interface InstallResultWire {
  ok: boolean;
  kind: Kind;
  id?: string;
  title?: string;
  location?: string;
  state?: string;
  ready?: boolean;
  problem?: string | null;
  next_action?: string | null;
}
