/**
 * The `local_models` locale chunks must agree: de/es/pt carry exactly the
 * keys en carries. (The Local models panels that read these keys are gone;
 * the chunks stay, so their parity is still held here.)
 */
import { describe, expect, it } from "vitest";
import en from "./locales/local_models/en.json";
import de from "./locales/local_models/de.json";
import es from "./locales/local_models/es.json";
import pt from "./locales/local_models/pt.json";

function flatten(obj: Record<string, unknown>, prefix = ""): string[] {
  const out: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      out.push(...flatten(v as Record<string, unknown>, key));
    } else {
      out.push(key);
    }
  }
  return out;
}

const keysFor = (loc: Record<string, unknown>): Set<string> =>
  new Set(flatten(loc));

describe("local models i18n parity", () => {
  it("en defines a non-trivial local_models key set", () => {
    expect(keysFor(en as Record<string, unknown>).size).toBeGreaterThan(200);
  });

  for (const [lang, loc] of [
    ["de", de],
    ["es", es],
    ["pt", pt],
  ] as const) {
    it(`${lang} has the same local_models keys as en`, () => {
      const enKeys = keysFor(en as Record<string, unknown>);
      const langKeys = keysFor(loc as Record<string, unknown>);
      const missing = [...enKeys].filter((k) => !langKeys.has(k));
      const extra = [...langKeys].filter((k) => !enKeys.has(k));
      expect({ missing, extra }).toEqual({ missing: [], extra: [] });
    });
  }
});
