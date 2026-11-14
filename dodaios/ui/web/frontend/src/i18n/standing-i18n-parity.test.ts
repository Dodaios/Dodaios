/**
 * The standing tasks' strings (`standing.*`) are complete in every shipped
 * language: each key the source asks for exists in English, every other
 * language carries exactly the keys English carries, and every translation
 * keeps the placeholders of its English source. The keys are read from the
 * source files themselves, so a string added without its translations fails
 * here, not in front of a person. Modelled on agent-chat-i18n-parity.test.ts.
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

const blockOf = (locale: unknown): Block => ((locale as { standing?: Block }).standing ?? {});
const EN = blockOf(en);
const OTHERS: [string, Block][] = [["de", blockOf(de)], ["es", blockOf(es)], ["pt", blockOf(pt)], ["zh", blockOf(zh)]];

const SRC = join(__dirname, "..");
const SOURCE_FILES = [
  "views/assistant/StandingSection.tsx",
  "views/assistant/StandingTaskPage.tsx",
  "views/assistant/standingParts.tsx",
  "views/assistant/standingWords.ts",
  "components/agentchat/StandingProposalCard.tsx",
  "lib/skipReasons.ts",
].map((file) => join(SRC, file));

/** Keys built at run time (`standing.outcome_${outcome}`), listed by family. */
const FAMILIES: Record<string, readonly string[]> = {
  "state_": ["proposed", "active", "paused", "ended"],
  "outcome_": ["quiet", "reported", "prepared", "acted", "asked", "failed", "skipped"],
  "settled_": ["accepted", "declined", "ended"],
  "result_": ["done", "blocked", "skipped"],
  "autonomy_": ["watch", "prepare", "act", "watch_hint", "prepare_hint", "act_hint", "watch_does", "prepare_does", "act_does"],
};

function usedKeys(): Set<string> {
  const found = new Set<string>();
  for (const file of SOURCE_FILES) {
    const text = readFileSync(file, "utf8");
    for (const match of text.matchAll(/"standing\.([a-z0-9_]+)"/g)) found.add(match[1]);
    // A template key names its family: `standing.outcome_${…}`.
    for (const match of text.matchAll(/`standing\.([a-z0-9_]+)\$\{/g)) {
      const members = FAMILIES[match[1]];
      if (!members) throw new Error(`template key family not listed in this test: standing.${match[1]}`);
      for (const member of members) found.add(match[1] + member);
    }
  }
  return found;
}

const placeholders = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort().join("|");

describe("standing tasks i18n parity", () => {
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

  it("calls the feature by its German name", () => {
    expect(blockOf(de).title).toBe("Daueraufgaben"); // i18n-allow: German locale check
  });
});
