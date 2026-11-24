/**
 * The Self-improvement page speaks of learning rounds, never of nights: a round
 * runs whenever the person has been away for a while, at any time of day. The
 * code and the API may keep the old name (`nights`, `col_night`); what the
 * person reads may not.
 */
import { describe, expect, it } from "vitest";
import en from "./locales/self_improvement/en.json";
import de from "./locales/self_improvement/de.json";
import es from "./locales/self_improvement/es.json";
import pt from "./locales/self_improvement/pt.json";
import zh from "./locales/self_improvement/zh.json";

type Tree = Record<string, unknown>;

function texts(tree: unknown): string[] {
  if (typeof tree === "string") return [tree];
  if (!tree || typeof tree !== "object") return [];
  return Object.values(tree as Tree).flatMap(texts);
}

function at(tree: unknown, path: string): string {
  return String(path.split(".").reduce<unknown>((node, key) => (node as Tree)?.[key], tree));
}

/** The word for "night" in each language, and the word the page uses instead. */
const LANGUAGES = [
  ["en", en, /\bnights?\b|\bnightly\b|\btonight\b/i, "round"],
  ["de", de, /nacht|nächte|nachts/i, "Lernrunde"],
  ["es", es, /\bnoches?\b/i, "ronda"],
  ["pt", pt, /\bnoites?\b/i, "ronda"],
  ["zh", zh, /夜/, "轮"],
] as const;

describe("self-improvement: rounds, not nights", () => {
  for (const [lang, chunk, night, round] of LANGUAGES) {
    it(`${lang}: no text says night`, () => {
      const said = texts(chunk).filter((text) => night.test(text));
      expect(said).toEqual([]);
    });

    it(`${lang}: the state line and the list name the round`, () => {
      expect(at(chunk, "self_improvement.state.running_first")).toContain(round);
      expect(at(chunk, "self_improvement.nights.title")).toContain(round);
    });

    it(`${lang}: the foot says when a round runs and what it may spend`, () => {
      const limits = at(chunk, "self_improvement.how.limits");
      for (const slot of ["{minutes}", "{hours}"]) expect(limits).toContain(slot);
      const budget = at(chunk, "self_improvement.how.budget");
      for (const slot of ["{full}", "{share}"]) expect(budget).toContain(slot);
      const fallback = at(chunk, "self_improvement.how.fallback");
      for (const slot of ["{calls}", "{ramp}", "{replays}", "{ceiling}"]) expect(fallback).toContain(slot);
      for (const key of ["how.last_round", "nights.spent"]) {
        const text = at(chunk, `self_improvement.${key}`);
        for (const slot of ["{calls}", "{share}"]) expect(text, key).toContain(slot);
      }
    });
  }

  it("German uses real umlauts and its own word for the round", () => {
    expect(at(de, "self_improvement.curve.title")).toBe("Vorsprung, Lernrunde für Lernrunde");
    expect(at(de, "self_improvement.how.limits")).toContain("Schließen");
  });
});
