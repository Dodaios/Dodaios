/**
 * Pure helpers for the starter gallery: the copy a person reads (translated,
 * with the catalogue's English as the fallback), filtering by area and
 * search, and which tools start ticked.
 */
import type { Starter, StarterArea, StarterTool } from "./startersApi";

type T = (key: string) => string;

export type AreaFilter = StarterArea | "all";

export interface StarterCopy {
  name: string;
  outcome: string;
  firstMessage: string;
  routineTitle: string;
}

/** A translated string, or `fallback` when the locale has no such key. */
export function translated(t: T, key: string, fallback: string): string {
  const value = t(key);
  return value && value !== key ? value : fallback;
}

export function starterCopy(t: T, starter: Starter): StarterCopy {
  const base = `agent_create.starter.${starter.id.replace(/-/g, "_")}`;
  return {
    name: translated(t, `${base}.name`, starter.name),
    outcome: translated(t, `${base}.outcome`, starter.outcome),
    firstMessage: translated(t, `${base}.first`, starter.first_message),
    routineTitle: starter.routine ? translated(t, `${base}.routine`, starter.routine.title) : "",
  };
}

function fold(text: string): string {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/** Starters in `area` whose name, outcome or tools match every word of `query`. */
export function filterStarters(
  starters: readonly Starter[],
  area: AreaFilter,
  query: string,
  copyOf: (starter: Starter) => StarterCopy,
): Starter[] {
  const words = fold(query).split(/\s+/).filter(Boolean);
  return starters.filter((starter) => {
    if (area !== "all" && starter.area !== area) return false;
    if (!words.length) return true;
    const copy = copyOf(starter);
    const haystack = fold([
      copy.name, copy.outcome, starter.name, starter.outcome, starter.title,
      ...starter.tools.map((tool) => tool.label),
    ].join(" "));
    return words.every((word) => haystack.includes(word));
  });
}

/** How many starters each area chip would show for the current search. */
export function areaCounts(
  starters: readonly Starter[],
  areas: readonly StarterArea[],
  query: string,
  copyOf: (starter: Starter) => StarterCopy,
): Record<AreaFilter, number> {
  const searched = filterStarters(starters, "all", query, copyOf);
  const counts = { all: searched.length } as Record<AreaFilter, number>;
  for (const area of areas) counts[area] = searched.filter((s) => s.area === area).length;
  return counts;
}

/** Only connected tools start ticked; nothing missing is ever pre-picked. */
export function defaultTools(tools: readonly StarterTool[]): string[] {
  return tools.filter((tool) => tool.connected).map((tool) => tool.id);
}
