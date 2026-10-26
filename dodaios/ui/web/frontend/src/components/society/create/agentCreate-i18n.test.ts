/**
 * The New-agent dialog's own key block (`agent_create`) exists in all five
 * locales with the same keys, every key the dialog asks for is there, and
 * every starter in the backend catalogue has its translated copy and an icon
 * the gallery can draw.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, test } from "vitest";
import en from "@/i18n/locales/en.json";
import de from "@/i18n/locales/de.json";
import es from "@/i18n/locales/es.json";
import pt from "@/i18n/locales/pt.json";
import zh from "@/i18n/locales/zh.json";
import { KNOWN_STARTER_ICONS } from "./starterIcons";

const LOCALES: Record<string, Record<string, unknown>> = { en, de, es, pt, zh };
const STARTER_DIR = join(__dirname, "..", "..", "..", "..", "..", "..", "..", "society", "starters");

function flatten(obj: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return value && typeof value === "object" && !Array.isArray(value)
      ? flatten(value as Record<string, unknown>, path)
      : [path];
  });
}

function block(locale: Record<string, unknown>): Record<string, unknown> {
  return (locale.agent_create ?? {}) as Record<string, unknown>;
}

function lookup(locale: Record<string, unknown>, key: string): unknown {
  return key.split(".").reduce<unknown>((node, part) =>
    node && typeof node === "object" ? (node as Record<string, unknown>)[part] : undefined, locale);
}

interface StarterEntry { id: string; icon: string; routine?: { when: string } }

function starters(): StarterEntry[] {
  return readdirSync(STARTER_DIR).filter((name) => name.endsWith(".json")).flatMap((name) =>
    (JSON.parse(readFileSync(join(STARTER_DIR, name), "utf8")) as { starters: StarterEntry[] }).starters);
}

function sourceKeys(): string[] {
  const dir = __dirname;
  const keys = new Set<string>();
  for (const name of readdirSync(dir)) {
    if (!/\.tsx?$/.test(name) || /\.test\.tsx?$/.test(name)) continue;
    const text = readFileSync(join(dir, name), "utf8");
    for (const match of text.matchAll(/t\(\s*"(agent_create\.[a-z0-9_.]+)"/g)) keys.add(match[1]);
  }
  return [...keys];
}

describe("agent_create locale block", () => {
  const reference = flatten(block(en)).sort();

  test("every locale carries exactly the English keys, none empty", () => {
    expect(reference.length).toBeGreaterThan(100);
    for (const [lang, locale] of Object.entries(LOCALES)) {
      expect(flatten(block(locale)).sort(), lang).toEqual(reference);
      for (const key of reference) {
        const value = lookup(block(locale), key);
        expect(typeof value === "string" && value.trim().length > 0, `${lang}: ${key}`).toBe(true);
      }
    }
  });

  test("every literal key the dialog uses exists", () => {
    const used = sourceKeys();
    expect(used.length).toBeGreaterThan(20);
    for (const key of used) expect(lookup(en, key), key).toBeTypeOf("string");
  });

  test("every templated key the dialog builds exists", () => {
    const keys = [
      ...["quick", "starter", "import"].flatMap((mode) => [`agent_create.mode.${mode}`, `agent_create.mode.${mode}_hint`, `agent_create.footer.${mode}`]),
      ...["jarvis", "hermes", "openclaw"].map((runtime) => `agent_create.runtime_note.${runtime}`),
      ...["all", "coding", "research", "inbox", "writing", "ops", "personal"].map((area) => `agent_create.area.${area}`),
      ...["connected", "not_connected", "missing"].map((state) => `agent_create.preview.tool_${state}`),
    ];
    for (const key of keys) expect(lookup(en, key), key).toBeTypeOf("string");
  });

  test("every starter has translated copy, a known schedule and a drawable icon", () => {
    const all = starters();
    expect(all.length).toBeGreaterThanOrEqual(20);
    for (const entry of all) {
      const base = `agent_create.starter.${entry.id.replace(/-/g, "_")}`;
      for (const [lang, locale] of Object.entries(LOCALES)) {
        for (const field of ["name", "outcome", "first"]) {
          expect(lookup(locale, `${base}.${field}`), `${lang}: ${base}.${field}`).toBeTypeOf("string");
        }
        expect(lookup(locale, `${base}.routine`) !== undefined, `${lang}: ${base}.routine`).toBe(Boolean(entry.routine));
        if (entry.routine) expect(lookup(locale, `agent_create.when.${entry.routine.when}`)).toBeTypeOf("string");
      }
      expect(KNOWN_STARTER_ICONS, entry.icon).toContain(entry.icon);
    }
  });

  test("German copy uses real umlauts, never ae/oe/ue stand-ins", () => {
    const text = JSON.stringify(block(de));
    for (const word of ["fuer", "Pruef", "waehl", "Uebersicht", "koennen", "moechte", "Laeuft"]) { // i18n-allow: stand-in spellings the test forbids
      expect(text.includes(word), word).toBe(false);
    }
  });
});
