/**
 * Pure helpers for the Memory section: what each area lists, how a page
 * body becomes readable Markdown, and how wikilinks become clickable.
 */
import type {
  MemoryAgent,
  MemoryGroup,
  MemoryKind,
  MemoryPageSummary,
  OutgoingRef,
} from "@/lib/memoryApi";

export type MemoryArea = "entities" | "projects" | "concepts" | "journal" | "agents" | "system";

export interface AreaDef {
  id: MemoryArea;
  labelKey: string;
  descriptionKey: string;
  matches: (page: MemoryPageSummary) => boolean;
}

export const KNOWLEDGE_AREAS: AreaDef[] = [
  {
    id: "entities",
    labelKey: "memory_view.area_entities",
    descriptionKey: "memory_view.area_entities_hint",
    matches: (p) => p.group === "knowledge" && (p.kind === "entity" || p.kind === "person" || p.kind === "note"),
  },
  {
    id: "projects",
    labelKey: "memory_view.area_projects",
    descriptionKey: "memory_view.area_projects_hint",
    matches: (p) => p.group === "knowledge" && p.kind === "project",
  },
  {
    id: "concepts",
    labelKey: "memory_view.area_concepts",
    descriptionKey: "memory_view.area_concepts_hint",
    matches: (p) => p.group === "knowledge" && p.kind === "concept",
  },
  {
    id: "journal",
    labelKey: "memory_view.area_journal",
    descriptionKey: "memory_view.area_journal_hint",
    matches: (p) => p.group === "journal",
  },
];

export const SYSTEM_AREA: AreaDef = {
  id: "system",
  labelKey: "memory_view.area_system",
  descriptionKey: "memory_view.area_system_hint",
  matches: (p) => p.group === "system",
};

export function areaOf(page: Pick<MemoryPageSummary, "group" | "kind">): MemoryArea {
  if (page.group === "agents") return "agents";
  if (page.group === "system") return "system";
  for (const area of KNOWLEDGE_AREAS) {
    if (area.matches(page as MemoryPageSummary)) return area.id;
  }
  return "entities";
}

export const KIND_LABEL_KEY: Record<MemoryKind, string> = {
  entity: "memory_view.kind_entity",
  person: "memory_view.kind_person",
  project: "memory_view.kind_project",
  concept: "memory_view.kind_concept",
  session: "memory_view.kind_session",
  note: "memory_view.kind_note",
  memory: "memory_view.kind_memory",
  profile: "memory_view.kind_profile",
  shared: "memory_view.kind_shared",
  system: "memory_view.kind_system",
  template: "memory_view.kind_template",
};

export const GROUP_LABEL_KEY: Record<MemoryGroup, string> = {
  knowledge: "memory_view.group_knowledge",
  agents: "memory_view.group_agents",
  journal: "memory_view.group_journal",
  system: "memory_view.group_system",
};

export type SortKey = "recent" | "name" | "links";

export function sortPages(pages: MemoryPageSummary[], key: SortKey): MemoryPageSummary[] {
  const out = [...pages];
  if (key === "name") out.sort((a, b) => a.title.localeCompare(b.title));
  else if (key === "links")
    out.sort((a, b) => b.links_in + b.links_out - (a.links_in + a.links_out) || b.mtime - a.mtime);
  else out.sort((a, b) => b.mtime - a.mtime);
  return out;
}

export function matchesQuery(page: Pick<MemoryPageSummary, "title" | "summary" | "path">, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return (
    page.title.toLowerCase().includes(needle) ||
    page.summary.toLowerCase().includes(needle) ||
    page.path.toLowerCase().includes(needle)
  );
}

/** Agents the reader lists by default: live ones, and any that left real notes. */
export function visibleAgents(agents: MemoryAgent[], showAll: boolean): MemoryAgent[] {
  const ranked = [...agents].sort(
    (a, b) =>
      Number(b.state === "active") - Number(a.state === "active") ||
      Number(a.empty) - Number(b.empty) ||
      a.name.localeCompare(b.name),
  );
  return showAll ? ranked : ranked.filter((agent) => agent.state === "active" || !agent.empty);
}

// ------------------------------------------------------------------ markdown

export const LINK_SCHEME = "#memory:";
export const MISSING_SCHEME = "#memory-missing:";

const WIKILINK_RE = /(!?)\[\[([^\]\n|]+)(?:\|([^\]\n]+))?\]\]/g;
const COMMENT_RE = /<!--[\s\S]*?-->/g;

/**
 * Remove HTML comments (notebook entry bookkeeping) completely.
 *
 * One pass can leave a comment opener behind when comments are nested or
 * split (`<!<!-- -->-- x -->`), so this repeats until nothing changes and then
 * drops any opener that never closed. The renderer shows no raw HTML anyway;
 * this keeps the text itself clean.
 */
export function stripComments(text: string, replacement = ""): string {
  let current = text;
  for (;;) {
    const next = current.replace(COMMENT_RE, replacement);
    if (next === current) break;
    current = next;
  }
  return current.split("<!--").join(replacement);
}
const HEADING_RE = /^(#{1,6})\s+(.*?)\s*#*\s*$/;
const FENCE_RE = /^\s{0,3}(```|~~~)/;
const EMPTY_BULLET_RE = /^\s*(?:[-*+]|\d+[.)])\s*(?:\[[ xX]?\]\s*)?$/;

function linkKey(raw: string): string {
  return raw.split("|")[0].split("#")[0].trim().replace(/\\/g, "/").replace(/\.md$/i, "").toLowerCase();
}

function displayOf(raw: string): string {
  const target = raw.split("#")[0].trim();
  const last = target.split("/").pop() ?? target;
  return last.replace(/\.md$/i, "");
}

/**
 * The page body as the reader should see it:
 *
 * - HTML comments (notebook entry bookkeeping) removed;
 * - a leading `# Title` that repeats the page title dropped;
 * - headings with nothing under them removed, so a skeleton of empty
 *   sections does not read as content;
 * - `[[wikilinks]]` turned into Markdown links the renderer can route.
 */
export function prepareBody(body: string, title: string, outgoing: OutgoingRef[]): string {
  const resolved = new Map<string, OutgoingRef>();
  for (const link of outgoing) resolved.set(linkKey(link.raw), link);

  let text = stripComments(body).replace(/\r\n/g, "\n");
  text = stripLeadingTitle(text, title);
  text = pruneEmptySections(text);
  // An embed (`![[page]]`) reads as a plain link here: the reader shows one
  // page at a time.
  return text.replace(WIKILINK_RE, (_match, _embed: string, target: string, alias?: string) => {
    const link = resolved.get(linkKey(target));
    const path = link?.path ?? null;
    // Without an alias a resolved link reads as the page's title, not its file name.
    const text = alias ?? (path && link ? link.title : displayOf(target));
    const label = text.replace(/\\/g, "\\\\").replace(/([[\]])/g, "\\$1");
    const href = path
      ? `${LINK_SCHEME}${encodeURIComponent(path)}`
      : `${MISSING_SCHEME}${encodeURIComponent(displayOf(target))}`;
    return `[${label}](${href})`;
  }).trim();
}

export function stripLeadingTitle(body: string, title: string): string {
  const match = /^\s*#\s+(.+?)\s*#*\s*(?:\n|$)/.exec(body);
  if (!match) return body;
  const normalise = (value: string) => value.replace(/[*_`"]/g, "").trim().toLowerCase();
  return normalise(match[1]) === normalise(title) ? body.slice(match[0].length) : body;
}

/** Remove headings whose section (up to the next heading of any level) is blank. */
export function pruneEmptySections(body: string): string {
  const lines = body.split("\n");
  const keep = new Array<boolean>(lines.length).fill(true);
  let inFence = false;
  const headings: { index: number; level: number }[] = [];
  lines.forEach((line, index) => {
    if (FENCE_RE.test(line)) inFence = !inFence;
    if (inFence) return;
    // A bullet with no text is a placeholder, not content.
    if (EMPTY_BULLET_RE.test(line)) keep[index] = false;
    const match = HEADING_RE.exec(line);
    if (match) headings.push({ index, level: match[1].length });
  });
  // Walk bottom-up so a parent whose only children were empty goes too.
  const hasContent = new Map<number, boolean>();
  for (let h = headings.length - 1; h >= 0; h -= 1) {
    const { index, level } = headings[h];
    let end = lines.length;
    for (let n = h + 1; n < headings.length; n += 1) {
      if (headings[n].level <= level) {
        end = headings[n].index;
        break;
      }
    }
    let content = false;
    for (let i = index + 1; i < end && !content; i += 1) {
      const sub = headings.find((item) => item.index === i);
      if (sub) {
        content = hasContent.get(i) ?? false;
        continue;
      }
      const stripped = lines[i].trim();
      if (stripped && !EMPTY_BULLET_RE.test(stripped) && !/^(?:[-*_]\s*){3,}$/.test(stripped)) {
        content = true;
      }
    }
    hasContent.set(index, content);
    if (!content) keep[index] = false;
  }
  return lines
    .filter((_, index) => keep[index])
    .join("\n")
    .replace(/\n{3,}/g, "\n\n");
}

/** Notebook entries keep their own Markdown; this flattens one for a list row. */
export function plainText(markdown: string, max = 200): string {
  const text = stripComments(markdown, " ")
    .replace(WIKILINK_RE, (_m, _e, target: string, alias?: string) => alias ?? displayOf(target))
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[#*_`>]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > max ? `${text.slice(0, max).replace(/\s+\S*$/, "")}…` : text;
}

/** A counted label: `<key>_one` for exactly one, `<key>` with `{count}` otherwise. */
export function countText(t: (key: string) => string, key: string, count: number): string {
  return (count === 1 ? t(`${key}_one`) : t(key)).replace("{count}", String(count));
}

/** "3 days ago" in the reader's language, from a POSIX mtime in seconds. */
export function relativeAge(mtimeSeconds: number, language: string, nowMs = Date.now()): string {
  if (!Number.isFinite(mtimeSeconds) || mtimeSeconds <= 0) return "";
  const diff = mtimeSeconds - nowMs / 1000;
  const abs = Math.abs(diff);
  const steps: [number, Intl.RelativeTimeFormatUnit][] = [
    [60 * 60 * 24 * 365, "year"],
    [60 * 60 * 24 * 30, "month"],
    [60 * 60 * 24 * 7, "week"],
    [60 * 60 * 24, "day"],
    [60 * 60, "hour"],
    [60, "minute"],
  ];
  try {
    const format = new Intl.RelativeTimeFormat(language, { numeric: "auto" });
    for (const [size, unit] of steps) {
      if (abs >= size) return format.format(Math.round(diff / size), unit);
    }
    return format.format(0, "minute");
  } catch {
    return "";
  }
}

/** Frontmatter keys the header already shows, or that are bookkeeping only. */
export const HIDDEN_PROPERTIES = new Set([
  "title",
  "slug",
  "type",
  "aliases",
  "search_aliases",
  "tags",
  "trace",
  "purpose",
]);

export function formatProperty(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map(formatProperty).filter(Boolean).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
