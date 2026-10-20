/**
 * Every id the rank surfaces name has words in all five languages: ranks,
 * tiers, uniforms, ribbons, XP sources and rules, duty statuses and the
 * service record's pages. German keeps its umlauts.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { REWARD_IDS, XP_SOURCES, slotOf } from "../../progression/levelCatalog";
import { SERVICE_TABS } from "../../progression/progressionStore";
import { DUTY_STATUSES } from "./dutyStatus";
import { RANK_IDS, RANK_TIERS } from "./ranks";

const LANGS = ["en", "de", "es", "pt", "zh"] as const;
const DIR = join(__dirname, "..", "..", "..", "..", "i18n", "locales", "ship");

type Tree = Record<string, unknown>;

function ranksChunk(lang: string): Tree {
  const root = JSON.parse(readFileSync(join(DIR, `ranks.${lang}.json`), "utf8")) as Tree;
  return (root.verse as Tree).ranks as Tree;
}

function keysOf(value: unknown): string[] {
  return value && typeof value === "object" ? Object.keys(value as Tree).sort() : [];
}

describe("rank words", () => {
  it.each(LANGS)("%s names every id", (lang) => {
    const chunk = ranksChunk(lang);
    expect(keysOf(chunk.rank)).toEqual([...RANK_IDS].sort());
    expect(keysOf(chunk.tier)).toEqual([...RANK_TIERS].sort());
    expect(keysOf(chunk.uniform)).toEqual([...RANK_TIERS].sort());
    expect(keysOf(chunk.uniform_note)).toEqual([...RANK_TIERS].sort());
    const ribbons = REWARD_IDS.filter((id) => slotOf(id) === "ribbon");
    expect(keysOf(chunk.ribbon)).toEqual([...ribbons].sort());
    expect(keysOf(chunk.ribbon_note)).toEqual([...ribbons].sort());
    expect(keysOf(chunk.source)).toEqual([...XP_SOURCES, "retired"].sort());
    expect(keysOf(chunk.rule)).toEqual([...XP_SOURCES].sort());
    expect(keysOf(chunk.duty)).toEqual([...DUTY_STATUSES].sort());
    expect(keysOf((chunk.record as Tree).tabs)).toEqual([...SERVICE_TABS].sort());
    expect(keysOf((chunk.promo as Tree).salute)).toEqual([...RANK_TIERS].sort());
  });

  it("keeps every placeholder in every language", () => {
    const english = ranksChunk("en");
    const holes = (tree: unknown, path = ""): [string, string[]][] => {
      if (typeof tree === "string") return [[path, [...tree.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()]];
      return Object.entries(tree as Tree).flatMap(([k, v]) => holes(v, path ? `${path}.${k}` : k));
    };
    const expected = holes(english);
    for (const lang of LANGS) expect(holes(ranksChunk(lang)), lang).toEqual(expected);
  });

  it("has every literal key the rank surfaces ask for, and every key prefix they fill", () => {
    const flat = (tree: unknown, path: string): string[] =>
      typeof tree === "string" ? [path] : Object.entries(tree as Tree).flatMap(([k, v]) => flat(v, `${path}.${k}`));
    const known = new Set(flat(ranksChunk("en"), "verse.ranks"));
    const code = readdirSync(__dirname)
      .filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f))
      .map((f) => readFileSync(join(__dirname, f), "utf8"))
      .join("\n");
    const literal = [...code.matchAll(/"(verse\.ranks\.[a-z0-9_.]+)"/g)].map((m) => m[1]).filter((k) => !k.endsWith("."));
    expect(literal.length).toBeGreaterThan(30);
    expect(literal.filter((k) => !known.has(k))).toEqual([]);
    const prefixes = [...code.matchAll(/`(verse\.ranks\.[a-z0-9_.]+)\.\$\{/g)].map((m) => m[1]);
    for (const prefix of prefixes) expect([...known].some((k) => k.startsWith(`${prefix}.`)), prefix).toBe(true);
  });

  it("writes German with real umlauts", () => {
    const text = readFileSync(join(DIR, "ranks.de.json"), "utf8");
    expect(text).toMatch(/Fähnrich/); // i18n-allow: checks the German locale keeps real umlauts
    expect(text).not.toMatch(/\b(fuer|ueber|Schliessen|Faehnrich|naechste|hoechste|Stoerung|Kaempf)\w*/i); // i18n-allow: ASCII spellings that must never appear
  });
});
