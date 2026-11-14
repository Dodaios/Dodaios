/**
 * A design's moving background (docs/designs.md).
 *
 * The app's surfaces are opaque, so a layer BEHIND them would never be seen.
 * The backdrop therefore lies OVER the whole window, ignores the pointer and
 * blends into what is under it: `screen` on a dark appearance (it can only
 * add light, so white text stays white), `multiply` on a light one (it can
 * only add tint, so dark text stays dark). Its opacity is the design's
 * strength. Every motion is a transform on a few large layers that are drawn
 * once, so the page under it never repaints for the animation, and reduced
 * motion holds every layer still.
 */
import { useMemo, type CSSProperties } from "react";
import type { DesignBackground } from "@/lib/designs/designsApi";
import { hexToRgb, rgbToHsl } from "@/lib/designs/tokens";
import "./designBackdrop.css";

const SPEED_FACTOR: Record<DesignBackground["speed"], number> = { slow: 1, medium: 0.6, fast: 0.35 };

/** The colour as the blend needs it: deep on dark, soft on light. */
function tune(hex: string, dark: boolean, style: DesignBackground["style"]): string {
  const [h, s, l] = rgbToHsl(hexToRgb(hex));
  let light: number;
  if (dark) light = style === "stars" ? Math.max(l, 70) : Math.min(l, 48);
  else light = style === "stars" ? Math.min(Math.max(l, 35), 60) : Math.max(l, 82);
  return `hsl(${h.toFixed(1)} ${s.toFixed(1)}% ${light.toFixed(1)}%)`;
}

/** A fixed pseudo-random sequence, so the stars stand still across renders. */
function seeded(seed: number): () => number {
  let x = seed;
  return () => {
    x = (x * 1664525 + 1013904223) % 4294967296;
    return x / 4294967296;
  };
}

interface Props {
  background: DesignBackground;
  dark: boolean;
  /** Fill the parent (a preview card) instead of the window. */
  contained?: boolean;
  /** Hold still (previews in a long list, or a paused setting). */
  still?: boolean;
}

export function DesignBackdrop({ background, dark, contained = false, still = false }: Props) {
  const { style, speed, strength } = background;
  const colors = useMemo(
    () => background.colors.map((c) => tune(c, dark, style)),
    [background.colors, dark, style],
  );
  // Three layers of stars, each drawn once as the shadows of one point and
  // faded as a whole: a few animated layers instead of one per star.
  const starLayers = useMemo(() => {
    if (style !== "stars") return [];
    const rand = seeded(7);
    const perLayer = contained ? 9 : 40;
    return [0, 1, 2].map((layer) =>
      Array.from({ length: perLayer }, (_, i) => {
        const x = (rand() * 100).toFixed(2);
        const y = (rand() * 100).toFixed(2);
        const size = (0.4 + rand() * (contained ? 0.6 : 1)).toFixed(2);
        const color = colors[(i + layer) % Math.max(1, colors.length)] ?? "white";
        return `${x}cqw ${y}cqh ${(Number(size) * 3).toFixed(1)}px ${size}px ${color}`;
      }).join(", "),
    );
  }, [style, colors, contained]);

  if (style === "none" || colors.length === 0 || strength <= 0) return null;

  const factor = SPEED_FACTOR[speed] ?? 1;
  const rootStyle = {
    opacity: Math.min(1, Math.max(0, strength)),
    mixBlendMode: dark ? "screen" : "multiply",
    "--design-speed": String(factor),
  } as CSSProperties;
  const ring = (i: number) => colors[i % colors.length];

  return (
    <div
      aria-hidden
      data-testid="design-backdrop"
      data-style={style}
      data-still={still ? "true" : undefined}
      className={contained ? "design-backdrop design-backdrop--contained" : "design-backdrop"}
      style={rootStyle}
    >
      {style === "glow" &&
        [0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className={`design-glow design-glow-${i}`}
            style={{ background: `radial-gradient(closest-side, ${ring(i)}, transparent)` }}
          />
        ))}
      {style === "waves" &&
        [0, 1, 2].map((i) => (
          <span
            key={i}
            className={`design-wave design-wave-${i}`}
            style={{ background: `radial-gradient(ellipse 50% 50% at 50% 50%, ${ring(i)}, transparent 70%)` }}
          />
        ))}
      {style === "gradient" && (
        <span
          className="design-sweep"
          style={{
            background: `linear-gradient(90deg, ${[...colors, colors[0]].join(", ")})`,
          }}
        />
      )}
      {style === "stars" &&
        starLayers.map((shadow, i) => (
          <span key={i} className={`design-stars design-stars-${i}`} style={{ boxShadow: shadow }} />
        ))}
    </div>
  );
}
