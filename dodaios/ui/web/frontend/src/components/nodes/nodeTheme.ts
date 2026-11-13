/**
 * Each node type's identity in the library: its name, and its hue.
 *
 * A type's hue is how a reader finds "the sheets" at a glance on a wall of
 * cards. It tints the cover of a card and the tile that starts a new node;
 * it is never used for text, state or emphasis. The hues live in
 * `index.css` as `--node-<type>` (HSL triplets, one set per theme).
 */
import type { CSSProperties } from "react";

import type { CardType } from "./nodeModel";

/** i18n key of a type's name ("Docs", "Slides", …). */
export const NODE_TYPE_LABEL_KEY: Record<CardType, string> = {
  docs: "nodes.type.docs",
  slides: "nodes.type.slides",
  sheets: "nodes.type.sheets",
  design: "nodes.type.design",
  data: "nodes.type.data",
  whiteboard: "nodes.type.whiteboard",
  motion: "nodes.type.motion",
  output: "nodes.type.output",
};

/** The hue mixed into the room: an opaque pastel (light) or deep tint (dark). */
function hueOverRoom(share: string): string {
  return `color-mix(in srgb, hsl(var(--node-hue)) ${share}, hsl(var(--background)))`;
}

/**
 * Inline style that sets `--node-hue` to the type's hue triplet, so one set
 * of classes (`bg-[hsl(var(--node-hue)/0.14)]` …) tints any type.
 *
 * It also derives the two fills a cover or a tile paints itself with, as
 * finished colors: `--node-fill` (rest) and `--node-fill-hover` (one step
 * deeper). They are opaque, so a cover looks the same on any ground.
 */
export function nodeHueStyle(type: CardType): CSSProperties {
  return {
    "--node-hue": `var(--node-${type})`,
    "--node-fill": hueOverRoom("var(--node-cover-mix)"),
    "--node-fill-hover": hueOverRoom("var(--node-cover-mix-hover)"),
  } as CSSProperties;
}

/** Paints an element with the type's fill (needs `nodeHueStyle` on it or above). */
export const NODE_FILL_CLASS = "bg-[color:var(--node-fill)]";

/** The type's ink: the icon on a tile, a bar in a chart, a small tag. */
export const NODE_INK_CLASS = "text-[hsl(var(--node-hue))]";

/**
 * The faint diagonal sheen across a tile: two wide translucent stripes of
 * light. Its strength is a theme variable, so it stays barely visible on a
 * pastel and on a deep tint alike.
 */
export const NODE_SHEEN_STYLE: CSSProperties = {
  backgroundImage: [
    "linear-gradient(115deg,",
    "transparent 0 22%,",
    "hsl(var(--node-sheen) / var(--node-sheen-strength)) 22% 43%,",
    "transparent 43% 55%,",
    "hsl(var(--node-sheen) / calc(var(--node-sheen-strength) * 0.6)) 55% 68%,",
    "transparent 68%)",
  ].join(" "),
};
