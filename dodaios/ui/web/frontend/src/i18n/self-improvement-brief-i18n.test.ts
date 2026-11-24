/**
 * The words of the brief area and of the brief line's wordings, in every
 * interface language. The page builds these keys from data (a domain name, a
 * parameter name and its value), so the literal-key check of the page cannot
 * see them; this one names them.
 *
 * The wordings are the kernel's (dodaios/rsi/lines.py and the catalog's
 * `lead.brief_line`, 0 to 2; pinned by tests/unit/rsi/test_brief_domain.py).
 */
import { describe, expect, it } from "vitest";
import en from "./locales/self_improvement/en.json";
import de from "./locales/self_improvement/de.json";
import es from "./locales/self_improvement/es.json";
import pt from "./locales/self_improvement/pt.json";
import zh from "./locales/self_improvement/zh.json";
import { costWords, lineSentence, paramKey, valueWords } from "@/views/selfImprovement/words";

type Tree = Record<string, unknown>;

const WORDING = "lead.brief_line";
const WORDINGS = [0, 1, 2];

function at(tree: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((node, key) => (node && typeof node === "object" ? (node as Tree)[key] : undefined), tree);
}

const KEYS = [
  "self_improvement.domain.brief.name",
  "self_improvement.domain.brief.about",
  "self_improvement.domain.brief.building",
  "self_improvement.domain.brief.no_tasks",
  "self_improvement.domain.brief.cost_label",
  "self_improvement.domain.brief.effect_shorter",
  "self_improvement.domain.brief.effect_longer",
  "self_improvement.domain.brief.range_unclear_cheaper",
  `self_improvement.param.${paramKey(WORDING)}.title`,
  `self_improvement.param.${paramKey(WORDING)}.about`,
  ...WORDINGS.flatMap((n) => [
    `self_improvement.line.${paramKey(WORDING)}.v${n}`,
    `self_improvement.wording.${paramKey(WORDING)}.v${n}`,
  ]),
];

const LOCALES = [
  ["en", en],
  ["de", de],
  ["es", es],
  ["pt", pt],
  ["zh", zh],
] as const;

describe("self-improvement: the brief area's words", () => {
  for (const [lang, chunk] of LOCALES) {
    it(`${lang}: the area, the wordings and their sentences are there`, () => {
      for (const key of KEYS) {
        const text = at(chunk, key);
        expect(typeof text, `${lang} ${key}`).toBe("string");
        expect(String(text).trim(), `${lang} ${key}`).not.toBe("");
      }
      const building = String(at(chunk, "self_improvement.domain.brief.building"));
      const range = String(at(chunk, "self_improvement.domain.brief.range_unclear_cheaper"));
      for (const slot of ["{low}", "{high}", "{pct}"]) expect(range, lang).toContain(slot);
      for (const slot of ["{n}", "{need}", "{have}"]) expect(building, lang).toContain(slot);
      for (const way of ["shorter", "longer"]) {
        expect(String(at(chunk, `self_improvement.domain.brief.effect_${way}`)), lang).toContain("{tokens}");
      }
      const how = String(at(chunk, "self_improvement.how.measure_first_move"));
      for (const slot of ["{calls}", "{share}"]) expect(how, lang).toContain(slot);
    });
  }

  it("a wording reads as its sentence and its name, never as a bare number", () => {
    const t = (key: string) => {
      const text = at(en, key);
      return typeof text === "string" ? text : key;
    };
    expect(lineSentence(t, WORDING, 2)).toBe(String(at(en, "self_improvement.line.lead_brief_line.v2")));
    expect(lineSentence(t, WORDING, true)).toBe(""); // the brief line has no on/off
    expect(lineSentence(t, "recall.turn_limit", 3)).toBe(""); // a number that is no line
    expect(valueWords(t, 1, "en", WORDING)).toBe("shorter look-up");
    expect(valueWords(t, 3, "en", "recall.turn_limit")).toBe("3");
    // The brief area's cost is the message and the brief, not the prompt.
    expect(costWords(t, "brief", -40, "en")).toBe("message and brief 40 tokens shorter");
    expect(costWords(t, "first_move", -40, "en")).toBe("prompt 40 tokens shorter");
  });
});
