/**
 * The blocks the Visuals editor can add, and the choices it offers for the
 * page as a whole.
 *
 * A new block is plain markup on the kit's classes and the theme's tokens
 * (the same vocabulary the design GUIDE gives the assistant), so it takes
 * the design's own type and colours and reads in both themes. Its words are
 * placeholders in the reader's language, passed in by the editor.
 */
import type { LucideIcon } from "lucide-react";
import {
  AlignLeft,
  BarChart3,
  Heading,
  Image,
  LayoutPanelTop,
  List,
  Megaphone,
  Minus,
  MousePointerClick,
  Quote,
  Space,
  Tags,
} from "lucide-react";

export type BlockId =
  | "heading"
  | "text"
  | "button"
  | "image"
  | "list"
  | "quote"
  | "card"
  | "chips"
  | "metrics"
  | "callout"
  | "divider"
  | "spacer";

/** The placeholder words a block is made with (`nodes.editor.design.block_text.*`). */
export interface BlockWords {
  heading: string;
  text: string;
  button: string;
  item: string;
  quote: string;
  label: string;
  value: string;
}

export interface BlockTemplate {
  id: BlockId;
  icon: LucideIcon;
  /** The block's markup with the words filled in (escaped). */
  markup: (words: BlockWords) => string;
}

function esc(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export const BLOCKS: readonly BlockTemplate[] = [
  { id: "heading", icon: Heading, markup: (w) => `<h2>${esc(w.heading)}</h2>` },
  { id: "text", icon: AlignLeft, markup: (w) => `<p>${esc(w.text)}</p>` },
  { id: "button", icon: MousePointerClick, markup: (w) => `<a class="btn" href="#">${esc(w.button)}</a>` },
  // An image block is made from a picture the person picks; see `imageMarkup`.
  { id: "image", icon: Image, markup: () => "" },
  {
    id: "list",
    icon: List,
    markup: (w) => `<ul><li>${esc(w.item)}</li><li>${esc(w.item)}</li><li>${esc(w.item)}</li></ul>`,
  },
  { id: "quote", icon: Quote, markup: (w) => `<blockquote><p>${esc(w.quote)}</p></blockquote>` },
  {
    id: "card",
    icon: LayoutPanelTop,
    markup: (w) => `<div class="card"><h3>${esc(w.heading)}</h3><p>${esc(w.text)}</p></div>`,
  },
  {
    id: "chips",
    icon: Tags,
    markup: (w) =>
      `<div style="display:flex;flex-wrap:wrap;gap:8px"><span class="chip">${esc(w.label)}</span>` +
      `<span class="chip">${esc(w.label)}</span><span class="chip">${esc(w.label)}</span></div>`,
  },
  {
    id: "metrics",
    icon: BarChart3,
    markup: (w) => {
      const one = `<div class="metric"><div class="value">${esc(w.value)}</div><div class="label">${esc(w.label)}</div></div>`;
      return `<div class="metrics">${one}${one}${one}</div>`;
    },
  },
  { id: "callout", icon: Megaphone, markup: (w) => `<div class="callout"><p>${esc(w.text)}</p></div>` },
  { id: "divider", icon: Minus, markup: () => "<hr>" },
  { id: "spacer", icon: Space, markup: () => '<div style="height:48px" aria-hidden="true"></div>' },
];

/** An image block for a picture already embedded as a `data:` URI. */
export function imageMarkup(src: string, alt: string): string {
  return `<img src="${esc(src)}" alt="${esc(alt)}" style="display:block;max-width:100%;height:auto">`;
}

/* ------------------------------------------------------------ the page */

/** Artboard sizes offered in one click (px), as the GUIDE names them. */
export const SIZE_PRESETS = [
  { id: "portrait", width: 1080, height: 1350 },
  { id: "square", width: 1080, height: 1080 },
  { id: "story", width: 1080, height: 1920 },
  { id: "wide", width: 1920, height: 1080 },
  { id: "a4", width: 794, height: 1123 },
] as const;

/** Mirrors of `design.py`'s artboard bounds. */
export const ARTBOARD = { min: 320, maxWidth: 4000, maxHeight: 6000, width: 1080, height: 1350 } as const;

export const THEMES = ["auto", "light", "dark"] as const;
export type DesignTheme = (typeof THEMES)[number];

/** A colour the editor offers: the value written into the design, and a swatch to show for it. */
export interface ColorChoice {
  /** What is written: a token reference ("var(--ink)") or a spec colour name ("accent"). */
  value: string;
  /** The token's light-theme colour, for the swatch (the app's own page does not define the tokens). */
  swatch: string;
  /** The token's name as the person sees it. */
  name: string;
}

/**
 * The colours offered for text, grounds and shapes inside the design: the
 * theme's tokens (`design_guide.THEME_CSS`). They switch with light and dark,
 * which keeps the design readable in both; a free hex is offered beside them.
 */
export const TOKEN_COLORS: readonly ColorChoice[] = [
  { value: "var(--ink)", swatch: "#171717", name: "ink" },
  { value: "var(--ink-2)", swatch: "#62625E", name: "ink-2" },
  { value: "var(--ink-3)", swatch: "#8F8F8A", name: "ink-3" },
  { value: "var(--bg)", swatch: "#FDFDFC", name: "bg" },
  { value: "var(--bg-2)", swatch: "#F4F4F2", name: "bg-2" },
  { value: "var(--bg-3)", swatch: "#EAEAE7", name: "bg-3" },
  { value: "var(--line-2)", swatch: "#D4D4CF", name: "line-2" },
  { value: "var(--accent)", swatch: "#2A6FD0", name: "accent" },
  { value: "var(--accent-soft)", swatch: "#E8F0FC", name: "accent-soft" },
  { value: "var(--good)", swatch: "#17703F", name: "good" },
  { value: "var(--warn)", swatch: "#8A5200", name: "warn" },
  { value: "var(--bad)", swatch: "#B3352A", name: "bad" },
  { value: "var(--s1)", swatch: "#2A6FD0", name: "s1" },
  { value: "var(--s2)", swatch: "#D4532E", name: "s2" },
  { value: "var(--s3)", swatch: "#158F6B", name: "s3" },
  { value: "var(--s5)", swatch: "#5B46C2", name: "s5" },
];

/**
 * The named colours the spec itself accepts for `background` and `accent`
 * (`shell.NAMED_COLORS`); each maps to a token and switches with the theme.
 */
export const SPEC_COLORS: readonly ColorChoice[] = [
  { value: "accent", swatch: "#2A6FD0", name: "accent" },
  { value: "ink", swatch: "#171717", name: "ink" },
  { value: "muted", swatch: "#62625E", name: "muted" },
  { value: "blue", swatch: "#2A6FD0", name: "blue" },
  { value: "orange", swatch: "#D4532E", name: "orange" },
  { value: "green", swatch: "#158F6B", name: "green" },
  { value: "amber", swatch: "#A86B00", name: "amber" },
  { value: "violet", swatch: "#5B46C2", name: "violet" },
  { value: "pink", swatch: "#C23F86", name: "pink" },
  { value: "good", swatch: "#17703F", name: "good" },
  { value: "warn", swatch: "#8A5200", name: "warn" },
  { value: "bad", swatch: "#B3352A", name: "bad" },
];

/** Font weights offered for a text, in the kit's steps. */
export const WEIGHTS = ["400", "500", "600", "700"] as const;

/**
 * The largest picture a design may embed, in characters of its `data:` URI
 * (`shell.MAX_IMAGE_CHARS`). A larger picture is scaled down before it is
 * embedded rather than refused.
 */
export const MAX_IMAGE_CHARS = 400_000;
