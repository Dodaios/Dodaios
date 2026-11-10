import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The design tokens the consumer look rests on, read from index.css:
 * the dark surfaces derive from a base and a contrast step, the quieter inks
 * clear AA on a card, motion and the reading column are variables, and the
 * OS's reduced-transparency wish is honoured.
 */

const CSS = readFileSync(join(process.cwd(), "src", "index.css"), "utf8").replace(/\r\n/g, "\n");

/** The `.dark { … }` theme block. */
function darkBlock(): string {
  const start = CSS.indexOf("  .dark {\n    /* --- Dark:");
  expect(start).toBeGreaterThan(-1);
  return CSS.slice(start, CSS.indexOf("\n  }\n", start));
}

function token(block: string, name: string): string {
  const match = block.match(new RegExp(`\\n\\s*${name}:\\s*([^;]+);`));
  expect(match, name).not.toBeNull();
  return match![1].trim();
}

/** Evaluate a ladder lightness for base/contrast (the calc() in the token). */
function lightness(expr: string, base: number, contrast: number): number {
  const inner = expr.replace(/^0 0% calc\(/, "").replace(/ \* 1%\)$/, "");
  const js = inner.replaceAll("var(--theme-base)", String(base)).replaceAll("var(--theme-contrast)", String(contrast));
  expect(js).toMatch(/^[\d\s+*().]+$/);
  return Function(`return (${js});`)() as number;
}

/** WCAG contrast of two greys given as HSL lightness in percent. */
function contrast(l1: number, l2: number): number {
  const lum = (l: number) => {
    const c = l / 100;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const [a, b] = [lum(l1), lum(l2)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}

describe("the dark theme is derived from base, contrast and accent", () => {
  const dark = darkBlock();

  it("declares the inputs", () => {
    expect(token(dark, "--theme-base")).toBe("4");
    expect(token(dark, "--theme-contrast")).toBe("1");
    expect(token(dark, "--accent")).toMatch(/^\d+ \d+% \d+%$/);
  });

  it("lands every surface on the value it had when it was hand-written", () => {
    const expected: Record<string, number> = {
      "--background": 4,
      "--sidebar": 6,
      "--card": 9,
      "--popover": 11,
      "--secondary": 12,
      "--surface-raised": 15,
      "--border": 15,
      "--border-strong": 22,
    };
    for (const [name, value] of Object.entries(expected)) {
      expect(lightness(token(dark, name), 4, 1), name).toBeCloseTo(value);
    }
    expect(token(dark, "--muted")).toBe("var(--secondary)");
    expect(token(dark, "--input")).toBe("var(--secondary)");
  });

  it("keeps the ladder in order at any contrast", () => {
    const order = ["--background", "--sidebar", "--card", "--popover", "--secondary", "--surface-raised", "--border-strong"];
    for (const step of [0.5, 1, 1.5]) {
      const values = order.map((name) => lightness(token(dark, name), 4, step));
      expect([...values].sort((a, b) => a - b)).toEqual(values);
    }
  });

  it("gives the quieter inks AA contrast on a card", () => {
    const card = 9;
    const ink = (name: string) => Number(token(dark, name).match(/(\d+)%$/)![1]);
    expect(contrast(ink("--muted-foreground"), card)).toBeGreaterThanOrEqual(7);
    expect(contrast(ink("--foreground-secondary"), card)).toBeGreaterThanOrEqual(7);
    expect(contrast(ink("--faint-foreground"), card)).toBeGreaterThanOrEqual(4.5);
    expect(token(dark, "--foreground-faint")).toBe("var(--faint-foreground)");
  });
});

describe("motion and the reading column are variables", () => {
  it("defines a 150–300 ms scale whose exit is the shortest arrival", () => {
    const ms = (name: string) => Number(token(CSS, name).replace("ms", ""));
    for (const name of ["--motion-fast", "--motion-base", "--motion-slow", "--motion-exit"]) {
      expect(ms(name)).toBeGreaterThanOrEqual(150);
      expect(ms(name)).toBeLessThanOrEqual(300);
    }
    expect(ms("--motion-exit")).toBeLessThan(ms("--motion-slow"));
  });

  it("sets one 720 px column, a 15 px body and a line height of at least 1.6", () => {
    expect(token(CSS, "--reading-column")).toBe("720px");
    expect(token(CSS, "--reading-size")).toBe("15px");
    expect(Number(token(CSS, "--reading-leading"))).toBeGreaterThanOrEqual(1.6);
  });

  it("honours prefers-reduced-transparency", () => {
    const start = CSS.indexOf("@media (prefers-reduced-transparency: reduce)");
    expect(start).toBeGreaterThan(-1);
    expect(CSS.slice(start, start + 300)).toContain("backdrop-filter: none !important");
  });
});
