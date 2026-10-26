/**
 * The run view (activity line, work inspector, transcript aids) speaks from
 * one `run_view.*` block. Every key its sources ask for must exist in en, and
 * every locale must carry exactly en's keys with the same placeholders, so a
 * phrase added without its translations fails here, not in front of a person.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import en from "./locales/en.json";
import de from "./locales/de.json";
import es from "./locales/es.json";
import pt from "./locales/pt.json";
import zh from "./locales/zh.json";
import { VARIANTS } from "@/components/agentchat/activity/activityModel";

type Tree = Record<string, unknown>;

function flatten(obj: Tree, prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) for (const [kk, vv] of flatten(v as Tree, key)) out.set(kk, vv);
    else out.set(key, String(v));
  }
  return out;
}

const block = (loc: Tree) => flatten((loc.run_view ?? {}) as Tree, "run_view");
const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

const SRC = join(__dirname, "..");
const DIRS = [
  join(SRC, "components", "agentchat", "activity"),
  join(SRC, "components", "agentchat", "inspector"),
];
const FILES = [
  ...DIRS.flatMap((dir) => readdirSync(dir).filter((f) => /\.tsx?$/.test(f) && !/\.test\./.test(f)).map((f) => join(dir, f))),
  join(SRC, "components", "society", "chat", "AgentChatPanel.tsx"),
];

describe("run_view i18n", () => {
  const base = block(en as Tree);

  it("has every literal key the sources use", () => {
    const missing: string[] = [];
    for (const file of FILES) {
      for (const m of readFileSync(file, "utf8").matchAll(/"(run_view\.[a-z0-9_.]+)"/g)) {
        if (!base.has(m[1])) missing.push(`${m[1]} (${file})`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("has every phrasing variant of the generic families", () => {
    for (const [phrase, count] of Object.entries(VARIANTS)) {
      for (let i = 0; i < (count ?? 0); i++) expect(base.has(`run_view.phrase.${phrase}_${i}`)).toBe(true);
    }
  });

  it.each([["de", de], ["es", es], ["pt", pt], ["zh", zh]] as const)("%s carries exactly en's keys and placeholders", (_lang, loc) => {
    const other = block(loc as Tree);
    expect([...other.keys()].sort()).toEqual([...base.keys()].sort());
    for (const [key, text] of base) expect(placeholders(other.get(key) ?? "")).toEqual(placeholders(text));
  });

  it("never uses the assistant-name token and German keeps its umlauts", () => {
    for (const text of base.values()) expect(text).not.toContain("{name}");
    const german = [...block(de as Tree).values()].join(" ");
    expect(german).not.toMatch(/\b(fuer|ueber|schliessen|Aenderungen|naechsten)\b/);
    expect(german).toMatch(/[äöüß]/);
  });
});
