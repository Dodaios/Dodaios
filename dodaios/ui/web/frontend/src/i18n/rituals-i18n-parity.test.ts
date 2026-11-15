/**
 * The rituals' strings (`rituals.*`) are complete in every shipped language:
 * each key the source asks for exists in English, every other language
 * carries exactly the keys English carries, and every translation keeps the
 * placeholders of its English source. The keys are read from the source
 * files themselves, so a string added without its translations fails here,
 * not in front of a person. Modelled on standing-i18n-parity.test.ts.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import de from "./locales/de.json";
import en from "./locales/en.json";
import es from "./locales/es.json";
import pt from "./locales/pt.json";
import zh from "./locales/zh.json";

type Block = Record<string, string>;

const blockOf = (locale: unknown): Block => ((locale as { rituals?: Block }).rituals ?? {});
const EN = blockOf(en);
const OTHERS: [string, Block][] = [["de", blockOf(de)], ["es", blockOf(es)], ["pt", blockOf(pt)], ["zh", blockOf(zh)]];

const SRC = join(__dirname, "..");
const SOURCE_FILES = [
  "components/home/PanelRituals.tsx",
  "components/home/RitualDialog.tsx",
  "lib/skipReasons.ts",
].map((file) => join(SRC, file));

function usedKeys(): Set<string> {
  const found = new Set<string>();
  for (const file of SOURCE_FILES) {
    const text = readFileSync(file, "utf8");
    for (const match of text.matchAll(/"rituals\.([a-z0-9_]+)"/g)) found.add(match[1]);
    // Every key is written out in full, so each one can be found by its name.
    if (/`rituals\.[a-z0-9_]*\$\{/.test(text)) throw new Error(`a rituals key is built at run time in ${file}`);
  }
  return found;
}

const placeholders = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort().join("|");

describe("rituals i18n parity", () => {
  it("has every key the source asks for in English", () => {
    const missing = [...usedKeys()].filter((key) => typeof EN[key] !== "string").sort();
    expect(missing).toEqual([]);
  });

  it("carries no English key the source never asks for", () => {
    const used = usedKeys();
    expect(Object.keys(EN).filter((key) => !used.has(key)).sort()).toEqual([]);
  });

  for (const [lang, block] of OTHERS) {
    it(`${lang} carries exactly the keys en carries`, () => {
      expect(Object.keys(block).sort()).toEqual(Object.keys(EN).sort());
    });

    it(`${lang} keeps every placeholder of the English string`, () => {
      const broken = Object.keys(EN).filter((key) => placeholders(block[key] ?? "") !== placeholders(EN[key]));
      expect(broken).toEqual([]);
    });

    it(`${lang} leaves no string empty`, () => {
      expect(Object.keys(EN).filter((key) => !(block[key] ?? "").trim())).toEqual([]);
    });
  }

  it("fills no placeholder with the assistant's name by accident", () => {
    // `t()` itself puts the assistant's name into `{name}`; a ritual's own values go by other names.
    for (const [lang, block] of [["en", EN] as [string, Block], ...OTHERS]) {
      expect(Object.keys(block).filter((key) => block[key].includes("{name}")), lang).toEqual([]);
    }
  });

  it("calls the feature by its name in each language", () => {
    expect(EN.title).toBe("Rituals");
    expect(blockOf(de).title).toBe("Rituale");
    expect(blockOf(es).title).toBe("Rituales");
    expect(blockOf(zh).title).toBe("仪式");
    expect(blockOf(pt).title).toBe("Rituais");
  });
});
