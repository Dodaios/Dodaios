/**
 * The Self-improvement page must be complete in every interface language: the
 * lazy `self_improvement` chunk holds exactly the keys English holds and keeps
 * every placeholder, the nav label is in every main dictionary, every literal
 * key the page asks for exists, and every parameter the kernel can tune
 * (dodaios/rsi/params/catalog.py) has a plain title and sentence — so a
 * parameter added there without its words fails here, not in front of a person.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import en from "./locales/en.json";
import de from "./locales/de.json";
import es from "./locales/es.json";
import pt from "./locales/pt.json";
import zh from "./locales/zh.json";
import chunkEn from "./locales/self_improvement/en.json";
import chunkDe from "./locales/self_improvement/de.json";
import chunkEs from "./locales/self_improvement/es.json";
import chunkPt from "./locales/self_improvement/pt.json";
import chunkZh from "./locales/self_improvement/zh.json";
import { paramKey } from "@/views/selfImprovement/words";

type Tree = Record<string, unknown>;

function leaves(tree: unknown, prefix = ""): Map<string, unknown> {
  const out = new Map<string, unknown>();
  if (!tree || typeof tree !== "object") return out;
  for (const [key, value] of Object.entries(tree as Tree)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      for (const [k, v] of leaves(value, path)) out.set(k, v);
    } else {
      out.set(path, value);
    }
  }
  return out;
}

const PLACEHOLDER = /\{\w+\}/g;
const placeholders = (text: unknown) =>
  typeof text === "string" ? (text.match(PLACEHOLDER) ?? []).sort() : [];

const LANGS: [string, Tree, Tree][] = [
  ["de", de as Tree, chunkDe as Tree],
  ["es", es as Tree, chunkEs as Tree],
  ["pt", pt as Tree, chunkPt as Tree],
  ["zh", zh as Tree, chunkZh as Tree],
];

const SRC = join(__dirname, "..");
// src → frontend → web → ui → dodaios → the repository root.
const REPO = join(SRC, "..", "..", "..", "..", "..");

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}

describe("self-improvement strings", () => {
  const source = leaves(chunkEn);

  for (const [lang, main, chunk] of LANGS) {
    it(`${lang}: the chunk carries every English key with its placeholders`, () => {
      const target = leaves(chunk);
      expect([...target.keys()].sort()).toEqual([...source.keys()].sort());
      for (const [key, text] of source) {
        expect(placeholders(target.get(key)), `${lang} ${key}`).toEqual(placeholders(text));
        expect(String(target.get(key)).trim(), `${lang} ${key}`).not.toBe("");
      }
    });

    it(`${lang}: the main dictionary carries the nav label`, () => {
      expect(typeof (main.nav as Tree).self_improvement).toBe("string");
      expect(String((main.nav as Tree).self_improvement).trim()).not.toBe("");
    });
  }

  it("English carries the nav label", () => {
    expect((en as Tree & { nav: Tree }).nav.self_improvement).toBe("Self-improvement");
  });

  it("German uses real umlauts, never ae/oe/ue stand-ins", () => {
    const texts = [...leaves(chunkDe).values()].map(String);
    expect(texts.join(" ")).toMatch(/[äöüß]/);
    for (const text of texts) expect(text).not.toMatch(/\b(fuer|ueber|Rueck|zurueck|moeglich|naechst|Aenderung)\w*/i);
  });

  it("every parameter in the kernel's catalog has a title and a sentence", () => {
    const catalog = readFileSync(join(REPO, "dodaios", "rsi", "params", "catalog.py"), "utf-8");
    const names = [...catalog.matchAll(/Param\(\s*"([\w.]+)"/g)].map((m) => m[1]);
    expect(names.length).toBeGreaterThanOrEqual(13);
    for (const name of names) {
      expect(source.get(`self_improvement.param.${paramKey(name)}.title`), name).toBeTruthy();
      expect(source.get(`self_improvement.param.${paramKey(name)}.about`), name).toBeTruthy();
    }
  });

  it("every literal self_improvement key the page asks for exists in English", () => {
    const files = [join(SRC, "views", "SelfImprovementView.tsx"), ...walk(join(SRC, "views", "selfImprovement"))];
    const missing: string[] = [];
    let seen = 0;
    for (const file of files) {
      const text = readFileSync(file, "utf-8");
      for (const match of text.matchAll(/t\("(self_improvement\.[\w.]+)"\)/g)) {
        seen += 1;
        if (!source.has(match[1])) missing.push(`${file}: ${match[1]}`);
      }
    }
    expect(seen).toBeGreaterThan(20);
    expect(missing).toEqual([]);
  });

  it("every template key the page builds exists in English", () => {
    const expand: Record<string, string[]> = {
      "self_improvement.state.": ["running", "stopped", "readonly"],
      "self_improvement.area.badge_": ["better", "worse", "unclear"],
      "self_improvement.area.range_": ["better", "worse", "unclear"],
      "self_improvement.state_word.": ["proposed", "trial", "live", "reverted", "blocked"],
      "self_improvement.outcome.": ["admitted", "declined", "waiting", "kept", "taken_back"],
      "self_improvement.resting.": ["restale", "dormant"],
      "self_improvement.author.": ["tuner", "owner", "memory-learner"],
      "self_improvement.stack.": ["kinds", "note_title", "note_gone", "not_measured"],
      "self_improvement.detail.": ["admitted_on", "checked_on"],
      "self_improvement.how.": ["practise_title", "practise_body", "decide_title", "decide_body", "check_title", "check_body", "limits", "models", "measure_no_model", "privacy"],
      "self_improvement.nights.": ["built_one", "built_other", "erased_one", "erased_other", "deferred"],
      "self_improvement.daily.": ["title", "summary", "caveat", "col_week", "col_requests", "col_through", "week_of", "unrated"],
      "self_improvement.area.": ["building", "waiting", "range_unclear_cheaper", "shorter", "quality_label"],
      "self_improvement.domain.recall.": ["name", "about"],
    };
    for (const [prefix, suffixes] of Object.entries(expand)) {
      for (const suffix of suffixes) expect(source.has(`${prefix}${suffix}`), `${prefix}${suffix}`).toBe(true);
    }
  });
});
