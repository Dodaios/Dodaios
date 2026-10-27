/**
 * The Agents shell (roster rail, search, "New agent") paints
 * before the lazy `society` chunk arrives, so its strings live in the main
 * locale files: no raw `society.shell.*` key may ever render on first load.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import de from "./locales/de.json";
import en from "./locales/en.json";
import es from "./locales/es.json";
import pt from "./locales/pt.json";
import zh from "./locales/zh.json";

const FIRST_PAINT_FILES = [
  join(__dirname, "..", "components", "society", "roster", "RosterRail.tsx"),
  join(__dirname, "..", "components", "society", "roster", "RosterRow.tsx"),
  join(__dirname, "..", "views", "society", "SocietyView.tsx"),
];

function lookup(locale: unknown, key: string): unknown {
  return key.split(".").reduce<unknown>((node, part) =>
    node && typeof node === "object" ? (node as Record<string, unknown>)[part] : undefined, locale);
}

describe("the Agents shell's first paint", () => {
  const keys = new Set<string>();
  for (const file of FIRST_PAINT_FILES) {
    for (const match of readFileSync(file, "utf8").matchAll(/"(society\.(?:shell|roster|world\.mode_[a-z]+|profile_card\.open)[a-z0-9_.]*)"/g)) {
      keys.add(match[1]);
    }
  }

  it("finds the shell's keys", () => {
    for (const key of ["society.shell.new_agent", "society.shell.section_agents", "society.shell.section_teams", "society.roster.search"]) {
      expect(keys.has(key)).toBe(true);
    }
  });

  it("has every one of them in the main locale of every UI language", () => {
    for (const locale of [en, de, es, pt, zh]) {
      for (const key of keys) expect(typeof lookup(locale, key), key).toBe("string");
    }
  });
});
