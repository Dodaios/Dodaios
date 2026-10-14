import { Color } from "three";

/**
 * The coding floor's palette: the Foundry deck (art/studies/coding-floor-foundry).
 *
 * Charcoal steel and gold carry the architecture, cool cyan marks anything
 * that is code, and every workspace bay owns one saturated signal colour. The
 * status colours (amber = asks, red = failed) are reserved: no bay wears them,
 * so a beam in either colour can only mean a pane that needs the person.
 */

export const FOUNDRY = {
  /** The night behind the deck when the sky has not drawn yet, and the fog. */
  fog: "#120f26",
  /** Hemisphere fill: a cool sky over a warm deck bounce. */
  sky: "#9fb4ff",
  ground: "#3a2c22",
  /** Deck plates: base, the tone variations a plate takes, the seams between them. */
  deck: { base: "#262a31", plates: ["#252930", "#2a2e36", "#23272d", "#2c3038", "#272b32"], seam: "#111317" },
  /** The deck slab's underside and its edge. */
  hull: "#15171c",
  steel: "#3b4049",
  steelDark: "#22252b",
  gold: "#d8ae52",
  /** Code light: rails, packets, the Core's heart. */
  code: "#5fe6ff",
  /** The Core's plasma, from its heart outwards. */
  plasma: { heart: "#e9fdff", inner: "#7af0ff", outer: "#3a7bff" },
  /** Pane states the floor draws as light. */
  status: { asking: "#ffb23d", failed: "#ff3b4e" },
  /** The nebula's colours, deep to bright, and the ringed planet below the deck. */
  nebula: { deep: "#07061a", violet: "#4b2a8f", magenta: "#b23a8a", teal: "#1d8f9c", glow: "#ffd2a8" },
  planet: { day: "#b0744c", band: "#6a3628", night: "#120b1e", rim: "#5fb8e6", ring: "#c9ad86" },
} as const;

/**
 * One signal colour per workspace bay, cycled by the department's tint index.
 * All six are far from the reserved status amber and red, and from each other.
 */
export const BAY_SIGNALS = ["#3fd8ff", "#f25cff", "#9dff5a", "#a07bff", "#2ff0a0", "#7aa8ff"] as const;

/**
 * A light colour scaled so its luminance is `luminance` (linear). Bloom picks
 * pixels by luminance, so a lime strip would glow and a magenta or red one at
 * the same intensity would not; scaled like this, every signal colour glows
 * alike whatever its hue. Self-lit materials take it with tone mapping off.
 */
export function glowColour(hex: string, luminance: number): Color {
  const c = new Color(hex);
  const own = 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;
  return c.multiplyScalar(luminance / Math.max(own, 0.02));
}

export function baySignal(index: number): string {
  const n = BAY_SIGNALS.length;
  return BAY_SIGNALS[((index % n) + n) % n];
}
