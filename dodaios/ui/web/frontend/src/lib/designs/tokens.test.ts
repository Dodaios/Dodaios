import { describe, expect, it } from "vitest";
import { contrast, designCss, hexToRgb, paletteTokens, rgbToHsl } from "@/lib/designs/tokens";

function rgbOf(triple: string): [number, number, number] {
  const [h, s, l] = triple.replace(/%/g, "").split(" ").map(Number);
  // Back through the browser's own formula, small enough to inline here.
  const sn = s / 100;
  const ln = l / 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = sn * Math.min(ln, 1 - ln);
  const f = (n: number) => ln - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [Math.round(f(0) * 255), Math.round(f(8) * 255), Math.round(f(4) * 255)];
}

const DARK = { background: "#0b1020", foreground: "#e8ecf8", accent: "#7c9cff" };
const LIGHT = { background: "#f6f7fb", foreground: "#141a2e", accent: "#3a5bd9" };

describe("paletteTokens", () => {
  it("turns hex into the h s% l% triples index.css uses", () => {
    expect(rgbToHsl(hexToRgb("#ffffff"))).toEqual([0, 0, 100]);
    expect(paletteTokens(DARK)["--background"]).toMatch(/^\d+(\.\d)? \d+(\.\d)?% \d+(\.\d)?%$/);
  });

  it("builds the dark ladder upward from the room, in order", () => {
    const t = paletteTokens(DARK);
    const light = (name: string) => Number(t[name].split(" ")[2].replace("%", ""));
    expect(light("--background")).toBeLessThan(light("--sidebar"));
    expect(light("--sidebar")).toBeLessThan(light("--card"));
    expect(light("--card")).toBeLessThan(light("--secondary"));
    expect(light("--secondary")).toBeLessThan(light("--border-strong"));
  });

  it("builds the light ladder downward from the room", () => {
    const t = paletteTokens(LIGHT);
    const light = (name: string) => Number(t[name].split(" ")[2].replace("%", ""));
    expect(light("--secondary")).toBeLessThan(light("--background"));
    expect(light("--border")).toBeLessThan(light("--secondary"));
  });

  it("keeps every ink readable on the room", () => {
    for (const palette of [DARK, LIGHT]) {
      const t = paletteTokens(palette);
      const room = rgbOf(t["--background"]);
      expect(contrast(rgbOf(t["--foreground"]), room)).toBeGreaterThan(7);
      expect(contrast(rgbOf(t["--muted-foreground"]), room)).toBeGreaterThan(4.5);
      expect(contrast(rgbOf(t["--faint-foreground"]), room)).toBeGreaterThan(3);
    }
  });

  it("puts a readable ink on every fill", () => {
    const yellow = paletteTokens({ ...DARK, accent: "#ffd400" });
    expect(yellow["--accent-foreground"]).toBe("0 0% 9%");
    const navy = paletteTokens({ ...LIGHT, accent: "#1b2a6b" });
    expect(navy["--accent-foreground"]).toBe("0 0% 100%");
  });

  it("lets a colour the design names win over the ladder", () => {
    const t = paletteTokens({ ...LIGHT, card: "#fffdf8", success: "#2e7d32" });
    expect(t["--card"]).toBe(paletteTokens({ ...LIGHT, background: "#fffdf8" })["--background"]);
    expect(t["--success"]).toBeDefined();
    expect(paletteTokens(LIGHT)["--success"]).toBeUndefined();
  });
});

describe("designCss", () => {
  it("writes one block per appearance the design sets", () => {
    const both = designCss({ dark: DARK, light: LIGHT });
    expect(both).toContain(":root.dodaios-design.dark {");
    expect(both).toContain(":root.dodaios-design:not(.dark) {");
    const darkOnly = designCss({ dark: DARK, light: null });
    expect(darkOnly).toContain(".dark {");
    expect(darkOnly).not.toContain(":not(.dark)");
  });
});
