/**
 * The words of the lead's first-move area and of a switched standing line, in
 * every interface language. The page builds these keys from data (a domain
 * name, a parameter name and its value), so the literal-key check of the page
 * cannot see them; this one names them.
 *
 * The switches are the kernel's learnable lines (dodaios/rsi/lines.py, pinned by
 * tests/unit/rsi/test_first_move.py): today one.
 */
import { describe, expect, it } from "vitest";
import en from "./locales/self_improvement/en.json";
import de from "./locales/self_improvement/de.json";
import es from "./locales/self_improvement/es.json";
import pt from "./locales/self_improvement/pt.json";
import zh from "./locales/self_improvement/zh.json";
import { paramKey } from "@/views/selfImprovement/words";

type Tree = Record<string, unknown>;

const LINE_SWITCHES = ["lead.first_line"];

function at(tree: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((node, key) => (node && typeof node === "object" ? (node as Tree)[key] : undefined), tree);
}

const KEYS = [
  "self_improvement.domain.first_move.name",
  "self_improvement.domain.first_move.about",
  "self_improvement.domain.first_move.building",
  "self_improvement.domain.first_move.no_tasks",
  "self_improvement.value.on",
  "self_improvement.value.off",
  "self_improvement.how.measure_first_move",
  "self_improvement.author.lines",
  ...LINE_SWITCHES.flatMap((name) => [
    `self_improvement.param.${paramKey(name)}.title`,
    `self_improvement.param.${paramKey(name)}.about`,
    `self_improvement.line.${paramKey(name)}.off`,
    `self_improvement.line.${paramKey(name)}.on`,
  ]),
];

describe("self-improvement: the first move's words", () => {
  for (const [lang, chunk] of [
    ["en", en],
    ["de", de],
    ["es", es],
    ["pt", pt],
    ["zh", zh],
  ] as const) {
    it(`${lang}: the area, the switch and its sentences are there`, () => {
      for (const key of KEYS) {
        const text = at(chunk, key);
        expect(typeof text, `${lang} ${key}`).toBe("string");
        expect(String(text).trim(), `${lang} ${key}`).not.toBe("");
      }
    });
  }

  it("the building sentence keeps the numbers it is filled with", () => {
    for (const chunk of [en, de, es, pt, zh]) {
      const text = String(at(chunk, "self_improvement.domain.first_move.building"));
      for (const slot of ["{n}", "{need}", "{have}"]) expect(text).toContain(slot);
      const budget = String(at(chunk, "self_improvement.how.budget"));
      for (const slot of ["{full}", "{share}"]) expect(budget).toContain(slot);
      const fallback = String(at(chunk, "self_improvement.how.fallback"));
      for (const slot of ["{calls}", "{ramp}", "{replays}", "{ceiling}"]) expect(fallback).toContain(slot);
    }
  });
});
