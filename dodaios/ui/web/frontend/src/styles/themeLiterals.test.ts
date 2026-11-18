import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The light theme breaks wherever a component writes a dark colour as a
 * literal instead of a token (index.css, "Theme tokens": "never write a
 * literal colour"). The app defaults to dark, so such a literal looks right to
 * whoever wrote it and only shows up as a black slab or an unreadable label
 * once someone switches to Light.
 *
 * This guards the two shapes that slipped in before: a dark hex background
 * utility (`bg-[#090909]/70` on dialog backdrops) and a black backdrop on a
 * full-screen overlay (`fixed inset-0 … bg-black/50`). Backdrops use
 * `bg-scrim/<alpha>`, which both themes define.
 */

const SRC = join(process.cwd(), "src");

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name === "__fixtures__" || name === "node_modules") continue;
      out.push(...sourceFiles(path));
    } else if (/\.(tsx|ts)$/.test(name) && !/\.test\.(tsx|ts)$/.test(name)) {
      out.push(path);
    }
  }
  return out;
}

/** A hex colour darker than #404040 in every channel. */
function isDarkHex(hex: string): boolean {
  const h = hex.length === 3 ? hex.replace(/./g, (c) => c + c) : hex.slice(0, 6);
  const channels = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return channels.every((c) => c < 0x40);
}

describe("no dark colour literal paints a surface", () => {
  const files = sourceFiles(SRC);

  it("finds the sources", () => {
    expect(files.length).toBeGreaterThan(100);
  });

  it("has no dark hex background utility", () => {
    const hits: string[] = [];
    for (const file of files) {
      const text = readFileSync(file, "utf8");
      for (const m of text.matchAll(/\bbg-\[#([0-9a-fA-F]{3,8})\]/g)) {
        if (isDarkHex(m[1])) hits.push(`${relative(SRC, file)}: ${m[0]}`);
      }
    }
    expect(hits).toEqual([]);
  });

  it("puts no black backdrop on a full-screen overlay", () => {
    const hits: string[] = [];
    for (const file of files) {
      const lines = readFileSync(file, "utf8").split("\n");
      lines.forEach((line, i) => {
        if (/fixed inset-0\b/.test(line) && /\bbg-black\/\d+/.test(line)) {
          // A presentation or video stage is black on purpose in both themes.
          if (/PresentView|AppshotEditor/.test(file)) return;
          hits.push(`${relative(SRC, file)}:${i + 1}`);
        }
      });
    }
    expect(hits).toEqual([]);
  });
});
