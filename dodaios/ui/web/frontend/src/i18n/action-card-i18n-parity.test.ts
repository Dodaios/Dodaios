/**
 * The action card's copy (`action_card.*`) exists in every locale with the
 * same keys and the same placeholders, and every key the card's sources ask
 * for is defined. Template keys (`action_card.source.${kind}`) are covered by
 * listing what they expand to.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import en from "./locales/en.json";
import de from "./locales/de.json";
import es from "./locales/es.json";
import pt from "./locales/pt.json";
import zh from "./locales/zh.json";

const LOCALES = { en, de, es, pt, zh } as Record<string, Record<string, unknown>>;

function flatten(obj: Record<string, unknown>, prefix: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(obj)) {
    const key = `${prefix}.${k}`;
    if (v && typeof v === "object" && !Array.isArray(v)) Object.assign(out, flatten(v as Record<string, unknown>, key));
    else out[key] = String(v);
  }
  return out;
}

const block = (loc: Record<string, unknown>) => flatten((loc.action_card ?? {}) as Record<string, unknown>, "action_card");
const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

const SRC = join(__dirname, "..");
const FILES = [
  ...readdirSync(join(SRC, "components", "agentchat", "actionCard"))
    .filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f))
    .map((f) => join(SRC, "components", "agentchat", "actionCard", f)),
  join(SRC, "components", "agentchat", "CredentialCard.tsx"),
  join(SRC, "components", "society", "chat", "AgentChatPanel.tsx"),
];

const TEMPLATES: Record<string, string[]> = {
  "action_card.source.": ["terminal", "files", "browser", "computer", "plan", "agent", "connector", "tool"],
  "action_card.title.": ["terminal", "files", "browser", "computer", "plan", "agent"],
  "action_card.caution.": ["irreversible", "security", "data_leaves"],
  "action_card.outcome.": ["allow", "allow_always", "deny", "expired", "cancel"],
  "action_card.outcome_note.": ["expired", "cancel", "deny"],
  "action_card.rule.scope_": ["agent", "chat"],
  "action_card.rule.": ["always_verb", "always_app", "always_generic", "ask_verb", "ask_app", "ask_generic"],
};

function usedKeys(): Set<string> {
  const found = new Set<string>();
  for (const file of FILES) {
    for (const m of readFileSync(file, "utf8").matchAll(/"(action_card\.[a-z0-9_.]+)"/g)) found.add(m[1]);
  }
  for (const [prefix, rest] of Object.entries(TEMPLATES)) for (const r of rest) found.add(prefix + r);
  return found;
}

describe("action card locale parity", () => {
  const base = block(en);

  it("defines every key the card asks for", () => {
    const missing = [...usedKeys()].filter((key) => !(key in base));
    expect(missing).toEqual([]);
  });

  it.each(Object.keys(LOCALES).filter((lang) => lang !== "en"))("%s carries exactly the English keys and placeholders", (lang) => {
    const other = block(LOCALES[lang]);
    expect(Object.keys(other).sort()).toEqual(Object.keys(base).sort());
    for (const [key, text] of Object.entries(base)) {
      expect([key, placeholders(other[key] ?? "")]).toEqual([key, placeholders(text)]);
      expect((other[key] ?? "").trim()).not.toBe("");
    }
  });

  it("writes German with real umlauts", () => {
    const german = Object.values(block(de)).join(" ");
    expect(german).not.toMatch(/\b(fuer|ueber|koennen|aendern|loesch\w*|zurueck)\b/i);
    expect(german).toMatch(/[äöüß]/);
  });
});
