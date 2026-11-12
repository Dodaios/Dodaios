import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The Voice section keeps its strings in `locales/voice/<tab>.<lang>.json`.
 * Every tab file exists in all five languages with the same keys, and every
 * key lives under the `voiceui` root so it cannot shadow a startup string.
 */
const DIR = join(__dirname, "locales", "voice");
const LANGS = ["en", "de", "es", "pt", "zh"] as const;

function read(area: string, lang: string): Record<string, unknown> {
  return JSON.parse(readFileSync(join(DIR, `${area}.${lang}.json`), "utf8")) as Record<string, unknown>;
}

function leaves(value: unknown, prefix = ""): [string, unknown][] {
  if (!value || typeof value !== "object") return [[prefix, value]];
  return Object.entries(value as Record<string, unknown>).flatMap(([k, v]) =>
    leaves(v, prefix ? `${prefix}.${k}` : k),
  );
}

function areas(): string[] {
  const found = new Set<string>();
  for (const name of readdirSync(DIR).filter((f) => f.endsWith(".json"))) {
    found.add(name.replace(/\.json$/, "").split(".").slice(0, -1).join("."));
  }
  return [...found];
}

describe("voice locale parity", () => {
  it("has at least one tab file", () => {
    expect(areas().length).toBeGreaterThan(0);
  });

  it.each(areas())("tab '%s' has the same keys in every language", (area) => {
    const english = leaves(read(area, "en")).map(([key]) => key).sort();
    for (const lang of LANGS) {
      const other = leaves(read(area, lang));
      expect(other.map(([key]) => key).sort(), `${area} ${lang}`).toEqual(english);
      for (const [key, value] of other) {
        expect(typeof value === "string" && value.trim().length > 0, `${area} ${lang} ${key}`).toBe(true);
      }
    }
  });

  it.each(areas())("tab '%s' keeps every key under the voiceui root", (area) => {
    for (const lang of LANGS) {
      expect(Object.keys(read(area, lang)), `${area} ${lang}`).toEqual(["voiceui"]);
    }
  });

  it("keeps German umlauts real", () => {
    const text = readdirSync(DIR)
      .filter((f) => f.endsWith(".de.json"))
      .map((f) => readFileSync(join(DIR, f), "utf8"))
      .join("\n");
    expect(text).not.toMatch(/\b(fuer|ueber|Schliessen|loeschen|zurueck|oeffnen|hinzufuegen)\b/i);
  });
});
