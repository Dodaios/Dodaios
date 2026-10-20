import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** Every ship locale file exists in all five languages with the same keys. */
const DIR = join(__dirname, "locales", "ship");
const LANGS = ["en", "de", "es", "pt", "zh"] as const;

function keys(value: unknown, prefix = ""): string[] {
  if (!value || typeof value !== "object") return [prefix];
  return Object.entries(value as Record<string, unknown>).flatMap(([k, v]) => keys(v, prefix ? `${prefix}.${k}` : k));
}

function areas(): string[] {
  const names = readdirSync(DIR).filter((f) => f.endsWith(".json"));
  const found = new Set<string>();
  for (const name of names) {
    const parts = name.replace(/\.json$/, "").split(".");
    found.add(parts.length === 1 ? "" : parts.slice(0, -1).join("."));
  }
  return [...found];
}

describe("ship locale parity", () => {
  it.each(areas())("area '%s' has the same keys in every language", (area) => {
    const file = (lang: string) => join(DIR, area ? `${area}.${lang}.json` : `${lang}.json`);
    const english = keys(JSON.parse(readFileSync(file("en"), "utf8"))).sort();
    for (const lang of LANGS) {
      const other = keys(JSON.parse(readFileSync(file(lang), "utf8"))).sort();
      expect(other, `${area || "core"} ${lang}`).toEqual(english);
    }
  });

  it("never uses {name} for anything but the assistant (the resolver fills it with the assistant's name)", () => {
    for (const f of readdirSync(DIR).filter((n) => n.endsWith(".json") && !n.startsWith("levels."))) {
      expect(readFileSync(join(DIR, f), "utf8"), f).not.toContain("{name}");
    }
  });

  it("keeps German umlauts real", () => {
    const text = readdirSync(DIR).filter((f) => f.endsWith("de.json")).map((f) => readFileSync(join(DIR, f), "utf8")).join("\n");
    expect(text).not.toMatch(/\b(fuer|ueber|Schliessen|Bruecke|zurueck|oeffnen)\b/);
  });
});
