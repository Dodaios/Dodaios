/**
 * Free elements on a slide, a slide's background and the deck's look, as the
 * editor holds them.
 *
 * The shapes mirror `dodaios/nodes/kinds/slide_elements.py` (`read_element`,
 * `read_background`, `read_slide_extras`, `read_deck_extras`): an element is
 * placed on the slide's logical 1280 x 720 px canvas, a background is a
 * colour, a gradient or a picture, and the deck carries a type pairing, a
 * default transition and whether slides show their footer. The server stays
 * the judge (its `normalize` runs on every save); these readers only make
 * sure the editor never meets a shape it cannot draw.
 *
 * Pure functions over plain JSON; changes are mutations of a draft.
 */

export const SLIDE_W = 1280;
export const SLIDE_H = 720;

export const ELEMENT_TYPES = ["text", "shape", "line", "image", "table", "chart"] as const;
export type ElementType = (typeof ELEMENT_TYPES)[number];

export const BOX_SHAPES = ["rect", "rounded", "ellipse"] as const;
/** Shapes drawn as an SVG path on a 100 x 100 box (`PATH_SHAPES`). */
export const PATH_SHAPES: Record<string, string> = {
  triangle: "M50 0L100 100L0 100Z",
  diamond: "M50 0L100 50L50 100L0 50Z",
  pentagon: "M50 0L100 38L81 100L19 100L0 38Z",
  hexagon: "M25 0L75 0L100 50L75 100L25 100L0 50Z",
  star: "M50 0L61.8 35.1L98.9 35.1L68.9 56.8L80.3 91.9L50 70.2L19.7 91.9L31.1 56.8L1.1 35.1L38.2 35.1Z",
  arrow: "M0 30L62 30L62 4L100 50L62 96L62 70L0 70Z",
  chevron: "M0 0L72 0L100 50L72 100L0 100L28 50Z",
  parallelogram: "M22 0L100 0L78 100L0 100Z",
  trapezoid: "M20 0L80 0L100 100L0 100Z",
  callout: "M0 0L100 0L100 76L42 76L22 100L24 76L0 76Z",
  plus: "M36 0L64 0L64 36L100 36L100 64L64 64L64 100L36 100L36 64L0 64L0 36L36 36Z",
};
export const SHAPES = [...BOX_SHAPES, ...Object.keys(PATH_SHAPES)] as readonly string[];

/** The font families an element may take (`FONTS`), in the order the menu offers them. */
export const FONTS = [
  "sans",
  "serif",
  "mono",
  "rounded",
  "condensed",
  "geometric",
  "classic",
  "arial",
  "helvetica",
  "verdana",
  "trebuchet",
  "tahoma",
  "segoe",
  "georgia",
  "times",
  "palatino",
  "courier",
  "impact",
] as const;
/** The same families as CSS, for the font menu's own previews. */
export const FONT_STACKS: Record<string, string> = {
  sans: "system-ui, sans-serif",
  serif: 'Georgia, "Times New Roman", serif',
  mono: 'ui-monospace, "Cascadia Mono", Consolas, monospace',
  rounded: 'ui-rounded, "Arial Rounded MT Bold", system-ui, sans-serif',
  condensed: '"Bahnschrift SemiCondensed", "Arial Narrow", sans-serif',
  geometric: '"Century Gothic", Futura, Avenir, sans-serif',
  classic: 'Garamond, "Palatino Linotype", Georgia, serif',
  arial: "Arial, Helvetica, sans-serif",
  helvetica: '"Helvetica Neue", Helvetica, Arial, sans-serif',
  verdana: "Verdana, sans-serif",
  trebuchet: '"Trebuchet MS", sans-serif',
  tahoma: "Tahoma, sans-serif",
  segoe: '"Segoe UI", sans-serif',
  georgia: "Georgia, serif",
  times: '"Times New Roman", serif',
  palatino: '"Palatino Linotype", Palatino, serif',
  courier: '"Courier New", monospace',
  impact: 'Impact, "Arial Black", sans-serif',
};
export const DECK_FONTS = ["sans", "serif", "editorial", "mono", "rounded", "condensed", "geometric", "classic"] as const;
export type DeckFont = (typeof DECK_FONTS)[number];
export const TRANSITIONS = ["none", "fade", "slide", "rise", "zoom"] as const;
export type Transition = (typeof TRANSITIONS)[number];
export const ANIMATIONS = ["fade", "rise", "slide", "zoom", "pop", "wipe"] as const;
export type Animation = (typeof ANIMATIONS)[number];
export const ALIGNS = ["left", "center", "right", "justify"] as const;
export const VALIGNS = ["top", "middle", "bottom"] as const;
export const LISTS = ["none", "bullet", "number"] as const;
export const DASHES = ["solid", "dash", "dot"] as const;
export const ENDS = ["none", "arrow", "dot"] as const;
export const FITS = ["cover", "contain", "fill"] as const;
export const TONES = ["light", "dark"] as const;

export const MAX_ELEMENTS = 40;
export const TEXT_CHARS = 2_000;
export const CELL_CHARS = 160;
export const MAX_TABLE_ROWS = 14;
export const MAX_TABLE_COLUMNS = 8;

export interface ElementBase {
  type: ElementType;
  id?: string;
  rotate?: number;
  /** 0..100; absent means fully opaque. */
  opacity?: number;
  link?: string;
  anim?: Animation;
  /** The animation waits for a click in the presentation. */
  click?: boolean;
  locked?: boolean;
}

export interface BoxElement extends ElementBase {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** The text style a text box and a shape share. */
export interface TextStyle {
  text?: string;
  size?: number;
  font?: string;
  color?: string;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  strike?: boolean;
  caps?: boolean;
  align?: (typeof ALIGNS)[number];
  valign?: (typeof VALIGNS)[number];
  line?: number;
  spacing?: number;
  list?: "bullet" | "number";
  padding?: number;
}

export interface Paint {
  fill?: string;
  stroke?: string;
  stroke_width?: number;
  dash?: "dash" | "dot";
  radius?: number;
  shadow?: boolean;
}

export interface TextElement extends BoxElement, TextStyle, Paint {
  type: "text";
}
export interface ShapeElement extends BoxElement, TextStyle, Paint {
  type: "shape";
  shape: string;
}
export interface ImageElement extends BoxElement, Paint {
  type: "image";
  image: string;
  fit?: "contain" | "fill";
  alt?: string;
}
export interface TableElement extends BoxElement {
  type: "table";
  rows: string[][];
  head?: false;
  size?: number;
  font?: string;
  color?: string;
  fill?: string;
  stroke?: string;
  align?: "center" | "right" | "justify";
}
export interface ChartElement extends BoxElement {
  type: "chart";
  chart: Record<string, unknown>;
}
export interface LineElement extends ElementBase {
  type: "line";
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color?: string;
  width?: number;
  dash?: "dash" | "dot";
  start?: "arrow" | "dot";
  end?: "arrow" | "dot";
}

export type SlideElement = TextElement | ShapeElement | ImageElement | TableElement | ChartElement | LineElement;
export type BoxedElement = Exclude<SlideElement, LineElement>;

export interface Background {
  color?: string;
  gradient?: { from: string; to: string; angle: number };
  image?: string;
  fit?: "contain";
  /** 0..90: how dark the veil over the background is, in percent. */
  dim?: number;
}

/** What a slide carries besides its layout's fields. */
export interface SlideExtras {
  background?: Background;
  tone?: "light" | "dark";
  transition?: Transition;
  hidden?: boolean;
  footer?: false;
  elements?: SlideElement[];
}

/** What the deck carries besides its theme, accent and slides. */
export interface DeckExtras {
  font?: Exclude<DeckFont, "sans">;
  background?: Background;
  transition?: Transition;
  footer?: false;
}

// --- colours ----------------------------------------------------------------------

/** The kit's named colours (`shell.NAMED_COLORS`); the accent is the deck's own. */
const NAMED: Record<string, string> = {
  blue: "var(--s1)",
  orange: "var(--s2)",
  green: "var(--s3)",
  amber: "var(--s4)",
  yellow: "var(--s4)",
  violet: "var(--s5)",
  purple: "var(--s5)",
  pink: "var(--s6)",
  accent: "var(--da)",
  ink: "var(--ink)",
  muted: "var(--ink-2)",
  good: "var(--good)",
  warn: "var(--warn)",
  bad: "var(--bad)",
};
const PLAIN: Record<string, string> = { white: "#ffffff", black: "#000000", transparent: "transparent" };
const COLOR_RE = /^(?:#[0-9a-fA-F]{3,8}|(?:rgb|rgba|hsl|hsla)\([0-9a-zA-Z.,%/\s-]{1,60}\))$/;

/** A colour as the spec keeps it, or "" (`spec_color`). */
export function specColor(value: unknown): string {
  if (typeof value !== "string") return "";
  const text = value.trim();
  const lower = text.toLowerCase();
  if (lower in PLAIN) return lower;
  if (!text || lower === "none" || lower === "default") return "";
  if (lower in NAMED) return lower;
  return COLOR_RE.test(text) ? text : "";
}

/** The CSS of a colour the spec keeps (`css_color`). */
export function cssColor(value: string | undefined): string {
  const text = value ?? "";
  const lower = text.toLowerCase();
  if (lower in NAMED) return NAMED[lower];
  if (lower in PLAIN) return PLAIN[lower];
  return COLOR_RE.test(text) ? text : "";
}

// --- reading ----------------------------------------------------------------------

function num(value: unknown): number | null {
  if (typeof value === "boolean" || value === null || value === undefined) return null;
  const parsed = typeof value === "number" ? value : Number(String(value).trim());
  return Number.isFinite(parsed) ? parsed : null;
}

/** A number in bounds, rounded to one decimal as the server keeps it. */
export function bounded(value: unknown, low: number, high: number): number | null {
  const found = num(value);
  if (found === null) return null;
  return Math.round(Math.max(low, Math.min(high, found)) * 10) / 10;
}

function word<T extends string>(value: unknown, allowed: readonly T[]): T | "" {
  const text = typeof value === "string" ? value.trim().toLowerCase() : "";
  return (allowed as readonly string[]).includes(text) ? (text as T) : "";
}

function text(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return "";
}

const IMAGE_RE = /^data:image\/(?:png|jpeg|jpg|gif|webp|avif);base64,[A-Za-z0-9+/=\s]+$/;

export function isImageData(value: unknown): value is string {
  return typeof value === "string" && value.length <= 400_000 && IMAGE_RE.test(value.trim());
}

function readCommon(raw: Record<string, unknown>, out: ElementBase): void {
  if (typeof raw.id === "string" && /^[A-Za-z0-9_-]{1,24}$/.test(raw.id)) out.id = raw.id;
  const rotate = bounded(raw.rotate, -360, 360);
  if (rotate) out.rotate = rotate;
  const opacity = bounded(raw.opacity, 0, 100);
  if (opacity !== null && opacity < 100) out.opacity = opacity;
  if (typeof raw.link === "string" && /^(https?:\/\/|mailto:)/i.test(raw.link.trim())) out.link = raw.link.trim();
  const anim = word(raw.anim, ANIMATIONS);
  if (anim) {
    out.anim = anim;
    if (raw.click === true) out.click = true;
  }
  if (raw.locked === true) out.locked = true;
}

function readBox(raw: Record<string, unknown>, out: BoxElement, w: number, h: number): void {
  out.x = bounded(raw.x, -SLIDE_W, 2 * SLIDE_W) ?? 0;
  out.y = bounded(raw.y, -SLIDE_H, 2 * SLIDE_H) ?? 0;
  out.w = bounded(raw.w, 4, 2 * SLIDE_W) ?? w;
  out.h = bounded(raw.h, 4, 2 * SLIDE_H) ?? h;
}

function readPaint(raw: Record<string, unknown>, out: Paint): void {
  const fill = specColor(raw.fill);
  if (fill) out.fill = fill;
  const stroke = specColor(raw.stroke);
  const width = bounded(raw.stroke_width, 0, 40);
  if (stroke && width !== 0) {
    out.stroke = stroke;
    out.stroke_width = width ?? 2;
    const dash = word(raw.dash, DASHES);
    if (dash && dash !== "solid") out.dash = dash;
  }
  const radius = bounded(raw.radius, 0, 400);
  if (radius) out.radius = radius;
  if (raw.shadow === true) out.shadow = true;
}

function readTextStyle(raw: Record<string, unknown>, out: TextStyle): void {
  out.text = text(raw.text).slice(0, TEXT_CHARS);
  const size = bounded(raw.size, 8, 240);
  if (size !== null) out.size = size;
  const font = word(raw.font, FONTS);
  if (font) out.font = font;
  const color = specColor(raw.color);
  if (color) out.color = color;
  for (const key of ["bold", "italic", "underline", "strike", "caps"] as const) if (raw[key] === true) out[key] = true;
  const align = word(raw.align, ALIGNS);
  if (align) out.align = align;
  const valign = word(raw.valign, VALIGNS);
  if (valign) out.valign = valign;
  const line = bounded(raw.line, 0.8, 3);
  if (line !== null) out.line = line;
  const spacing = bounded(raw.spacing, -0.1, 0.5);
  if (spacing) out.spacing = spacing;
  const list = word(raw.list, LISTS);
  if (list && list !== "none") out.list = list;
  const padding = bounded(raw.padding, 0, 120);
  if (padding !== null) out.padding = padding;
}

/** One element the editor can draw, or null. */
export function readElement(raw: unknown): SlideElement | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  const type = word(r.type, ELEMENT_TYPES);
  if (!type) return null;
  if (type === "line") {
    const out = { type } as LineElement;
    out.x1 = bounded(r.x1, -SLIDE_W, 2 * SLIDE_W) ?? 0;
    out.y1 = bounded(r.y1, -SLIDE_H, 2 * SLIDE_H) ?? 0;
    out.x2 = bounded(r.x2, -SLIDE_W, 2 * SLIDE_W) ?? 200;
    out.y2 = bounded(r.y2, -SLIDE_H, 2 * SLIDE_H) ?? 0;
    const color = specColor(r.color);
    if (color) out.color = color;
    const width = bounded(r.width, 1, 40);
    if (width !== null) out.width = width;
    const dash = word(r.dash, DASHES);
    if (dash && dash !== "solid") out.dash = dash;
    for (const key of ["start", "end"] as const) {
      const end = word(r[key], ENDS);
      if (end && end !== "none") out[key] = end;
    }
    readCommon(r, out);
    delete out.rotate;
    return out;
  }
  if (type === "text") {
    const out = { type } as TextElement;
    readBox(r, out, 480, 120);
    readTextStyle(r, out);
    readPaint(r, out);
    readCommon(r, out);
    return out;
  }
  if (type === "shape") {
    const out = { type } as ShapeElement;
    readBox(r, out, 240, 240);
    out.shape = SHAPES.includes(String(r.shape)) ? String(r.shape) : "rect";
    readTextStyle(r, out);
    if (!out.text) delete out.text;
    readPaint(r, out);
    if (out.shape !== "rect") delete out.radius;
    readCommon(r, out);
    return out;
  }
  if (type === "image") {
    if (!isImageData(r.image)) return null;
    const out = { type, image: r.image } as ImageElement;
    readBox(r, out, 480, 320);
    const fit = word(r.fit, FITS);
    if (fit === "contain" || fit === "fill") out.fit = fit;
    if (typeof r.alt === "string" && r.alt) out.alt = r.alt.slice(0, 140);
    readPaint(r, out);
    delete out.fill;
    readCommon(r, out);
    return out;
  }
  if (type === "table") {
    const rows = Array.isArray(r.rows)
      ? r.rows.filter(Array.isArray).slice(0, MAX_TABLE_ROWS).map((row) => (row as unknown[]).slice(0, MAX_TABLE_COLUMNS).map(text))
      : [];
    if (!rows.length) return null;
    const width = Math.max(1, ...rows.map((row) => row.length));
    const out = { type, rows: rows.map((row) => [...row, ...Array(width - row.length).fill("")]) } as TableElement;
    readBox(r, out, 720, 320);
    if (r.head === false) out.head = false;
    const size = bounded(r.size, 8, 72);
    if (size !== null) out.size = size;
    const font = word(r.font, FONTS);
    if (font) out.font = font;
    for (const key of ["color", "fill", "stroke"] as const) {
      const found = specColor(r[key]);
      if (found) out[key] = found;
    }
    const align = word(r.align, ALIGNS);
    if (align && align !== "left") out.align = align;
    readCommon(r, out);
    return out;
  }
  if (!r.chart || typeof r.chart !== "object" || Array.isArray(r.chart)) return null;
  const out = { type, chart: r.chart as Record<string, unknown> } as ChartElement;
  readBox(r, out, 720, 400);
  readCommon(r, out);
  return out;
}

export function readBackground(value: unknown): Background | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const r = value as Record<string, unknown>;
  const out: Background = {};
  const color = specColor(r.color);
  if (color) out.color = color;
  const gradient = r.gradient as Record<string, unknown> | undefined;
  if (gradient && typeof gradient === "object") {
    const from = specColor(gradient.from);
    const to = specColor(gradient.to);
    if (from && to) out.gradient = { from, to, angle: bounded(gradient.angle, 0, 360) ?? 135 };
  }
  if (isImageData(r.image)) {
    out.image = r.image;
    if (r.fit === "contain") out.fit = "contain";
  }
  const dim = bounded(r.dim, 0, 90);
  if (dim && (out.image || out.gradient || out.color)) out.dim = dim;
  return Object.keys(out).length ? out : undefined;
}

/** A slide's extras from a stored slide (on top of its layout's fields). */
export function readSlideExtras(raw: Record<string, unknown>): SlideExtras {
  const out: SlideExtras = {};
  const background = readBackground(raw.background);
  if (background) out.background = background;
  const tone = word(raw.tone, TONES);
  if (tone) out.tone = tone;
  const transition = word(raw.transition, TRANSITIONS);
  if (transition) out.transition = transition;
  if (raw.hidden === true) out.hidden = true;
  if (raw.footer === false) out.footer = false;
  if (Array.isArray(raw.elements)) {
    const elements = raw.elements.map(readElement).filter((e): e is SlideElement => e !== null).slice(0, MAX_ELEMENTS);
    if (elements.length) out.elements = elements;
  }
  return out;
}

export function readDeckExtras(raw: Record<string, unknown>): DeckExtras {
  const out: DeckExtras = {};
  const font = word(raw.font, DECK_FONTS);
  if (font && font !== "sans") out.font = font;
  const background = readBackground(raw.background);
  if (background) out.background = background;
  const transition = word(raw.transition, TRANSITIONS);
  if (transition) out.transition = transition;
  if (raw.footer === false) out.footer = false;
  return out;
}

// --- tone ------------------------------------------------------------------------

export function hexLuminance(value: string): number | null {
  const text = PLAIN[value.toLowerCase()] ?? value;
  const found = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?$/.exec(text) ?? /^#([0-9a-fA-F]{4})$/.exec(text);
  if (!found) return null;
  let digits = found[1];
  if (digits.length === 3 || digits.length === 4) digits = digits.slice(0, 3).split("").map((c) => c + c).join("");
  const channels = [0, 2, 4].map((i) => parseInt(digits.slice(i, i + 2), 16) / 255);
  const linear = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

/** The tone a background asks for by itself (`auto_tone`). */
export function autoTone(background: Background | undefined): "" | "light" | "dark" {
  if (!background) return "";
  if (background.image && (background.dim ?? 0) >= 35) return "dark";
  if (background.image) return "";
  let light: number | null;
  if (background.gradient) {
    const a = hexLuminance(background.gradient.from);
    const b = hexLuminance(background.gradient.to);
    if (a === null || b === null) return "";
    light = (a + b) / 2;
  } else if (background.color) {
    light = hexLuminance(background.color);
    if (light === null) return "";
  } else return "";
  if (background.dim) light *= 1 - background.dim / 100;
  return light < 0.22 ? "dark" : "light";
}

export interface SlideLook {
  background: Background | undefined;
  tone: "" | "light" | "dark";
  font: string;
  transition: string;
  footer: boolean;
}

/** How one slide is drawn besides its layout (`slide_look`). */
export function slideLook(slide: SlideExtras, deck: DeckExtras): SlideLook {
  const background = slide.background ?? deck.background;
  return {
    background,
    tone: slide.tone || autoTone(background),
    font: deck.font && (DECK_FONTS as readonly string[]).includes(deck.font) ? deck.font : "",
    transition: slide.transition || deck.transition || "",
    footer: deck.footer !== false && slide.footer !== false,
  };
}

// --- geometry --------------------------------------------------------------------

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** The box an element covers (a line: the box of its two ends). */
export function boundsOf(element: SlideElement): Rect {
  if (element.type === "line") {
    const x = Math.min(element.x1, element.x2);
    const y = Math.min(element.y1, element.y2);
    return { x, y, w: Math.abs(element.x2 - element.x1), h: Math.abs(element.y2 - element.y1) };
  }
  return { x: element.x, y: element.y, w: element.w, h: element.h };
}

/** The union of several boxes. */
export function unionOf(rects: readonly Rect[]): Rect | null {
  if (!rects.length) return null;
  const x = Math.min(...rects.map((r) => r.x));
  const y = Math.min(...rects.map((r) => r.y));
  const right = Math.max(...rects.map((r) => r.x + r.w));
  const bottom = Math.max(...rects.map((r) => r.y + r.h));
  return { x, y, w: right - x, h: bottom - y };
}

export function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

/** Move an element by (dx, dy) (on a draft). */
export function translate(element: SlideElement, dx: number, dy: number): void {
  if (element.type === "line") {
    element.x1 = round1(element.x1 + dx);
    element.y1 = round1(element.y1 + dy);
    element.x2 = round1(element.x2 + dx);
    element.y2 = round1(element.y2 + dy);
  } else {
    element.x = round1(element.x + dx);
    element.y = round1(element.y + dy);
  }
}

/** Put an element into the box `to` (a line keeps which end is where, scaled). */
export function placeIn(element: SlideElement, from: Rect, to: Rect): void {
  if (element.type === "line") {
    const sx = from.w ? to.w / from.w : 1;
    const sy = from.h ? to.h / from.h : 1;
    element.x1 = round1(to.x + (element.x1 - from.x) * sx);
    element.y1 = round1(to.y + (element.y1 - from.y) * sy);
    element.x2 = round1(to.x + (element.x2 - from.x) * sx);
    element.y2 = round1(to.y + (element.y2 - from.y) * sy);
    return;
  }
  element.x = round1(to.x);
  element.y = round1(to.y);
  element.w = round1(Math.max(4, to.w));
  element.h = round1(Math.max(4, to.h));
}

/** A short random id for a new element. */
export function newId(): string {
  return `e${Math.random().toString(36).slice(2, 9)}`;
}

/** A deep copy with a new id (for duplicate and paste). */
export function cloneElement(element: SlideElement): SlideElement {
  const copy = JSON.parse(JSON.stringify(element)) as SlideElement;
  copy.id = newId();
  return copy;
}

/** The key that identifies an element in the editor (its id, else its place). */
export function elementKey(element: SlideElement, index: number): string {
  return element.id ?? `#${index}`;
}

/** Whether an element shows a text the person writes on the canvas. */
export function hasText(element: SlideElement): element is TextElement | ShapeElement {
  return element.type === "text" || element.type === "shape";
}

/** The first line a slide's text elements show (a slide's name when it has no title). */
export function firstText(elements: readonly SlideElement[] | undefined): string {
  for (const element of elements ?? []) {
    if (hasText(element) && element.text) return element.text.split("\n")[0];
  }
  return "";
}
