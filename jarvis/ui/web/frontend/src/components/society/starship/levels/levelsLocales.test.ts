/**
 * The level UI's strings (`locales/ship/levels.<lang>.json`) carry the same
 * keys and placeholders in all five languages, name every id the catalog
 * knows, and the German file writes its umlauts and ß as real letters. (i18n-allow)
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { REWARD_IDS, SLOTS, XP_SOURCES } from "../../progression/levelCatalog";
import { SERVICE_TABS } from "../../progression/progressionStore";
import { TIER_ORDER } from "./levelModel";
import { LEGACY_SOURCES } from "./levelText";

const DIR = join(__dirname, "..", "..", "..", "..", "i18n", "locales", "ship");
const LANGS = ["en", "de", "es", "pt", "zh"] as const;
type Tree = Record<string, unknown>;

const load = (lang: string) => JSON.parse(readFileSync(join(DIR, `levels.${lang}.json`), "utf8")) as { ship: { levels: Tree } };

function leaves(tree: Tree, prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object") for (const [k, v] of leaves(value as Tree, path)) out.set(k, v);
    else out.set(path, String(value));
  }
  return out;
}

const placeholders = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort();

describe("the level UI's locale files", () => {
  const en = leaves(load("en").ship.levels);

  it("have the same keys and placeholders in every language, none empty", () => {
    for (const lang of LANGS) {
      const other = leaves(load(lang).ship.levels);
      expect([...other.keys()].sort(), lang).toEqual([...en.keys()].sort());
      for (const [key, text] of other) {
        expect(text.trim(), `${lang}:${key}`).not.toBe("");
        expect(placeholders(text), `${lang}:${key}`).toEqual(placeholders(en.get(key) ?? ""));
      }
    }
  });

  it("name every reward, source, slot, tier and page", () => {
    const levels = load("en").ship.levels as Record<string, Tree>;
    expect(Object.keys(levels.reward).sort()).toEqual([...REWARD_IDS].sort());
    expect(Object.keys(levels.source).sort()).toEqual([...XP_SOURCES].sort());
    expect(Object.keys(levels.rule).sort()).toEqual([...XP_SOURCES].sort());
    expect(Object.keys(levels.slot).sort()).toEqual([...SLOTS].sort());
    expect(Object.keys(levels.tier).sort()).toEqual([...TIER_ORDER].sort());
    expect(Object.keys(levels.tier_about).sort()).toEqual([...TIER_ORDER].sort());
    expect(Object.keys(levels.legacy_source).sort()).toEqual([...LEGACY_SOURCES, "other"].sort());
    for (const tab of SERVICE_TABS) expect(levels.tabs[tab], tab).toBeTruthy();
  });

  it("writes German with real umlauts", () => {
    const raw = readFileSync(join(DIR, "levels.de.json"), "utf8");
    expect(raw).toMatch(/[äöüß]/); // i18n-allow
    expect(raw).not.toMatch(/\b(Schliessen|Naechst|fuer|Ruecken|Grosse|hoechst)/i); // i18n-allow
  });
});
