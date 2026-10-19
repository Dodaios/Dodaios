/**
 * "Built for you" must be complete in every interface language: the lazy
 * `self_build` chunk and the blocks the main dictionary carries for it (the nav
 * row, the Settings group, the "built by" badge) hold exactly the keys English
 * holds, keep every placeholder, and every literal key the surfaces ask for
 * exists. Keys are read from the source files, so a string added without its
 * translations fails here, not in front of a person.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import en from "./locales/en.json";
import de from "./locales/de.json";
import es from "./locales/es.json";
import pt from "./locales/pt.json";
import zh from "./locales/zh.json";
import chunkEn from "./locales/self_build/en.json";
import chunkDe from "./locales/self_build/de.json";
import chunkEs from "./locales/self_build/es.json";
import chunkPt from "./locales/self_build/pt.json";
import chunkZh from "./locales/self_build/zh.json";

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

const mainBlocks = (tree: Tree) =>
  new Map([
    ["nav.self_build", (tree.nav as Tree).self_build],
    ["settings_view.nav.self_build", ((tree.settings_view as Tree).nav as Tree).self_build],
    ...leaves((tree.settings_view as Tree).self_build, "settings_view.self_build"),
    ...leaves(tree.self_build_badge, "self_build_badge"),
  ]);

const PLACEHOLDER = /\{\w+\}/g;
const placeholders = (text: unknown) =>
  typeof text === "string" ? (text.match(PLACEHOLDER) ?? []).sort() : [];

const LANGS: [string, Tree, Tree][] = [
  ["de", de as Tree, chunkDe as Tree],
  ["es", es as Tree, chunkEs as Tree],
  ["pt", pt as Tree, chunkPt as Tree],
  ["zh", zh as Tree, chunkZh as Tree],
];

describe("self-build strings", () => {
  const chunkSource = leaves(chunkEn);
  const mainSource = mainBlocks(en as Tree);

  for (const [lang, main, chunk] of LANGS) {
    it(`${lang}: the chunk carries every English key with its placeholders`, () => {
      const target = leaves(chunk);
      expect([...target.keys()].sort()).toEqual([...chunkSource.keys()].sort());
      for (const [key, text] of chunkSource) {
        expect(placeholders(target.get(key)), `${lang} ${key}`).toEqual(placeholders(text));
        expect(String(target.get(key)).trim(), `${lang} ${key}`).not.toBe("");
      }
    });

    it(`${lang}: the main dictionary carries the nav, settings and badge strings`, () => {
      const target = mainBlocks(main);
      expect([...target.keys()].sort()).toEqual([...mainSource.keys()].sort());
      for (const [key, text] of mainSource) {
        expect(typeof target.get(key), `${lang} ${key}`).toBe("string");
        expect(placeholders(target.get(key)), `${lang} ${key}`).toEqual(placeholders(text));
      }
    });
  }

  it("German uses real umlauts, never ae/oe/ue stand-ins", () => {
    const texts = [...leaves(chunkDe).values(), ...mainBlocks(de as Tree).values()].map(String);
    expect(texts.join(" ")).toMatch(/[äöüß]/);
    for (const text of texts) expect(text).not.toMatch(/\b(fuer|ueber|Rueck|zurueck|moeglich)\w*/i);
  });

  it("every literal self_build key the surfaces ask for exists in English", () => {
    const src = join(__dirname, "..");
    const files = [
      join(src, "views", "SelfBuildView.tsx"),
      join(src, "views", "settings", "SelfBuildGroup.tsx"),
      join(src, "components", "selfBuild", "BuiltByBadge.tsx"),
      ...walk(join(src, "views", "selfBuild")),
    ];
    const known = new Set([...chunkSource.keys(), ...mainSource.keys()]);
    const missing: string[] = [];
    for (const file of files) {
      const text = readFileSync(file, "utf-8");
      for (const match of text.matchAll(/t\("((?:self_build|settings_view\.self_build|self_build_badge)\.[\w.]+)"\)/g)) {
        if (!known.has(match[1])) missing.push(`${file}: ${match[1]}`);
      }
    }
    expect(missing).toEqual([]);
  });
});

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}
