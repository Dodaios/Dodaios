/**
 * The Trust and privacy strings exist in every locale with the same keys and
 * the same placeholders: the startup-bundle part (`trust.nav`, `trust.undo.*`,
 * `trust.card.*` in the main files) and the lazy chunk (`locales/trust/*`,
 * which carries `trust.page.*` and `privacy.*`). Every key the views and the
 * card ask for is defined; template keys are listed by what they expand to.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import en from "./locales/en.json";
import de from "./locales/de.json";
import es from "./locales/es.json";
import pt from "./locales/pt.json";
import zh from "./locales/zh.json";
import chunkEn from "./locales/trust/en.json";
import chunkDe from "./locales/trust/de.json";
import chunkEs from "./locales/trust/es.json";
import chunkPt from "./locales/trust/pt.json";
import chunkZh from "./locales/trust/zh.json";

type Tree = Record<string, unknown>;
const MAIN = { en, de, es, pt, zh } as Record<string, Tree>;
const CHUNK = { en: chunkEn, de: chunkDe, es: chunkEs, pt: chunkPt, zh: chunkZh } as Record<string, Tree>;

function flatten(obj: Tree, prefix = ""): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) Object.assign(out, flatten(v as Tree, key));
    else out[key] = String(v);
  }
  return out;
}
const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
const mainBlock = (loc: Tree) => flatten({ trust: loc.trust } as Tree);
const chunkBlock = (loc: Tree) => flatten({ trust: loc.trust, privacy: loc.privacy } as Tree);

const SRC = join(__dirname, "..");
const FILES = [
  join(SRC, "views", "TrustView.tsx"),
  join(SRC, "components", "trust", "TrustRules.tsx"),
  join(SRC, "components", "trust", "PrivacyOverview.tsx"),
  join(SRC, "components", "trust", "SelfChanges.tsx"),
  join(SRC, "lib", "undoToast.ts"),
  join(SRC, "components", "agentchat", "actionCard", "ApprovalActionCard.tsx"),
];
const TEMPLATES: Record<string, string[]> = {
  "trust.card.limit.": ["money", "credentials", "permanent_delete", "new_recipient"],
  "trust.card.check.": ["secret", "unknown_recipient", "mistyped_domain", "tone"],
  "trust.page.kind_": ["tool", "action", "folder", "command"],
  "trust.page.limit_": ["money", "credentials", "permanent_delete", "new_recipient"],
  "trust.page.state_": ["proposed", "trial", "live", "reverted", "blocked"],
  "trust.page.surface_": ["skill", "prompt", "instructions", "tool", "code", "config", "routine", "agent"],
  "trust.page.changes_since_": ["hour", "day", "week"],
  "privacy.status_": ["connected", "needs_reauth"],
  "privacy.role_": ["brain", "realtime", "tts", "stt", "learning"],
};

function usedKeys(): Set<string> {
  const found = new Set<string>();
  for (const file of FILES) {
    for (const m of readFileSync(file, "utf8").matchAll(/"((?:trust|privacy)\.[a-z0-9_.]+)"/g)) found.add(m[1]);
  }
  for (const [prefix, rest] of Object.entries(TEMPLATES)) for (const r of rest) found.add(prefix + r);
  return found;
}

describe("trust and privacy locale parity", () => {
  const main = mainBlock(en);
  const chunk = chunkBlock(chunkEn);
  const all = { ...main, ...chunk };

  it("defines every key the views, the card and the undo toast ask for", () => {
    const missing = [...usedKeys()].filter((key) => !(key in all) && !key.endsWith("."));
    expect(missing).toEqual([]);
  });

  it("keeps the startup part small and the page part in the chunk", () => {
    expect(Object.keys(main).every((k) => /^trust\.(nav|undo\.|card\.)/.test(k))).toBe(true);
    expect(Object.keys(chunk).every((k) => k.startsWith("trust.page.") || k.startsWith("privacy."))).toBe(true);
  });

  for (const lang of ["de", "es", "pt", "zh"]) {
    it(`${lang} carries the same keys and placeholders as en`, () => {
      const theirs = { ...mainBlock(MAIN[lang]), ...chunkBlock(CHUNK[lang]) };
      expect(Object.keys(theirs).sort()).toEqual(Object.keys(all).sort());
      for (const [key, text] of Object.entries(all)) {
        expect(placeholders(theirs[key]), key).toEqual(placeholders(text));
        expect(theirs[key].trim(), key).not.toBe("");
      }
    });
  }
});
