/**
 * A design's colours -> the app's theme tokens (docs/designs.md).
 *
 * A design names a handful of colours per appearance; background, foreground
 * and accent are enough. Every other token the interface paints with is
 * derived here the way the standard look builds its own ladder: the room,
 * then one step lighter (dark) or darker (light) per layer, inks mixed from
 * the foreground toward the room, and a readable ink on every fill.
 *
 * The result is plain CSS that `designRuntime` puts in one <style> element.
 * It is unlayered, so it wins over the two token blocks in index.css (which
 * live in `@layer base`) without a specificity fight.
 */
import type { DesignPalette, Design } from "@/lib/designs/designsApi";

type Rgb = [number, number, number];
type Hsl = [number, number, number];

export function hexToRgb(hex: string): Rgb {
  const value = hex.replace("#", "");
  const full = value.length === 3 ? value.split("").map((c) => c + c).join("") : value;
  const n = Number.parseInt(full, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function rgbToHsl([r, g, b]: Rgb): Hsl {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l * 100];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  if (max === rn) h = (gn - bn) / d + (gn < bn ? 6 : 0);
  else if (max === gn) h = (bn - rn) / d + 2;
  else h = (rn - gn) / d + 4;
  return [h * 60, s * 100, l * 100];
}

function hslToRgb([h, s, l]: Hsl): Rgb {
  const sn = s / 100;
  const ln = l / 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = sn * Math.min(ln, 1 - ln);
  const f = (n: number) => ln - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [Math.round(f(0) * 255), Math.round(f(8) * 255), Math.round(f(4) * 255)];
}

const clamp = (v: number, lo = 0, hi = 100) => Math.min(hi, Math.max(lo, v));
const round1 = (v: number) => Math.round(v * 10) / 10;

/** `h s% l%`, the form every token in index.css has. */
function triple([h, s, l]: Hsl): string {
  return `${round1(h)} ${round1(s)}% ${round1(l)}%`;
}

function mixRgb(a: Rgb, b: Rgb, amount: number): Rgb {
  return [0, 1, 2].map((i) => Math.round(a[i] + (b[i] - a[i]) * amount)) as Rgb;
}

/** WCAG relative luminance. */
export function luminance([r, g, b]: Rgb): number {
  const lin = (c: number) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

export function contrast(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** White or near-black, whichever reads better on `fill`. */
function inkOn(fill: Rgb): Hsl {
  const white: Rgb = [255, 255, 255];
  const black: Rgb = [23, 23, 23];
  return contrast(fill, white) >= contrast(fill, black) ? [0, 0, 100] : [0, 0, 9];
}

/** A surface `steps` lightness points from the room, keeping its hue. */
function step(base: Hsl, steps: number, dark: boolean): Hsl {
  const [h, s, l] = base;
  // Saturation eases off as a dark surface rises, or the upper steps glow.
  const sat = dark ? s * Math.max(0.55, 1 - steps * 0.03) : s;
  return [h, sat, clamp(l + (dark ? steps : -steps))];
}

/**
 * Every token one appearance of a design sets, as `--name: value` pairs.
 * Keys the design gives win; the rest come from the ladder.
 */
export function paletteTokens(palette: DesignPalette): Record<string, string> {
  const bgRgb = hexToRgb(palette.background);
  const fgRgb = hexToRgb(palette.foreground);
  const accentRgb = hexToRgb(palette.accent);
  const bg = rgbToHsl(bgRgb);
  const fg = rgbToHsl(fgRgb);
  const dark = luminance(bgRgb) < luminance(fgRgb);

  const given = (key: keyof DesignPalette): Hsl | null => {
    const hex = palette[key];
    return hex ? rgbToHsl(hexToRgb(hex)) : null;
  };
  const pick = (key: keyof DesignPalette, fallback: Hsl): Hsl => given(key) ?? fallback;

  // The light ladder only goes down from the room; a white room keeps its
  // objects white, a tinted one lifts them a little toward white.
  const sidebar = pick("sidebar", step(bg, dark ? 2 : 2, dark));
  const card = pick("card", dark ? step(bg, 5, dark) : [bg[0], bg[1], clamp(bg[2] + 2)]);
  const popover = pick("popover", dark ? step(bg, 7, dark) : card);
  const surface = pick("surface", step(bg, dark ? 8 : 4, dark));
  const raised = step(surface, dark ? 3 : 3, dark);
  const border = pick("border", step(bg, dark ? 11 : 14, dark));
  const borderStrong = step(border, dark ? 7 : 12, dark);

  const mixInk = (amount: number): Hsl => rgbToHsl(mixRgb(fgRgb, bgRgb, amount));
  const muted = pick("muted", mixInk(dark ? 0.37 : 0.27));
  const secondaryInk = mixInk(dark ? 0.27 : 0.19);
  const faint = mixInk(dark ? 0.55 : 0.4);
  const strong: Hsl = [fg[0], fg[1], clamp(fg[2] + (dark ? 4 : -4))];

  const accent = rgbToHsl(accentRgb);
  const primary = pick("primary", fg);
  const primaryRgb = hslToRgb(primary);
  const userBubble = pick("user_bubble", step(bg, dark ? 12 : 5, dark));
  const bubbleOut = pick("bubble_out", accent);
  const bubbleIn = pick("bubble_in", step(bg, dark ? 11 : 8, dark));

  const tokens: Record<string, string> = {
    "--background": triple(bg),
    "--sidebar": triple(sidebar),
    "--card": triple(card),
    "--card-foreground": triple(fg),
    "--popover": triple(popover),
    "--popover-foreground": triple(fg),
    "--secondary": triple(surface),
    "--secondary-foreground": triple(fg),
    "--muted": triple(surface),
    "--input": triple(surface),
    "--surface-raised": triple(raised),
    "--border": triple(border),
    "--border-strong": triple(borderStrong),
    "--foreground-strong": triple(strong),
    "--foreground": triple(fg),
    "--muted-foreground": triple(muted),
    "--foreground-secondary": triple(secondaryInk),
    "--faint-foreground": triple(faint),
    "--foreground-faint": triple(faint),
    "--primary": triple(primary),
    "--primary-foreground": triple(inkOn(primaryRgb)),
    "--accent": triple(accent),
    "--accent-foreground": triple(inkOn(accentRgb)),
    "--ring": triple(accent),
    "--user-bubble": triple(userBubble),
    "--user-bubble-foreground": triple(fg),
    "--chat-bubble-out": triple(bubbleOut),
    "--chat-bubble-out-foreground": triple(inkOn(hslToRgb(bubbleOut))),
    "--chat-bubble-in": triple(bubbleIn),
    "--chat-bubble-in-foreground": triple(fg),
    "--accent-rgb": accentRgb.join(" "),
    "--shell-rgb": bgRgb.join(" "),
  };
  for (const key of ["success", "warning", "destructive"] as const) {
    const value = given(key);
    if (value) tokens[`--${key}`] = triple(value);
  }
  return tokens;
}

function block(selector: string, tokens: Record<string, string>): string {
  const body = Object.entries(tokens)
    .map(([name, value]) => `  ${name}: ${value};`)
    .join("\n");
  return `${selector} {\n${body}\n}`;
}

/**
 * The stylesheet for a design: one block per appearance it sets. An
 * appearance the design leaves out keeps the standard colours.
 */
export function designCss(design: Pick<Design, "dark" | "light">): string {
  const parts: string[] = [];
  if (design.light) parts.push(block(":root.dodaios-design:not(.dark)", paletteTokens(design.light)));
  if (design.dark) parts.push(block(":root.dodaios-design.dark", paletteTokens(design.dark)));
  return parts.join("\n");
}
