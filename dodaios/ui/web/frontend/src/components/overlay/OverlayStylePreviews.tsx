import { VoiceOrb } from "@/components/agentic/VoiceOrb";
import type { OverlayStyle } from "@/hooks/useOverlayStyle";
import {
  PILL_H,
  PILL_R,
  PILL_W,
  PILL_X,
  PILL_Y,
  VIEW_H,
  VIEW_W,
} from "./voiceBars";

/**
 * Shared visual previews for the on-screen overlay styles (Bar / Voice orb /
 * None).
 *
 * Lifted out of ``views/settings/OverlayTaskbarGroup.tsx`` so the Settings panel
 * and the in-app dock (``DodaiosDock``) draw the same graphics.
 *
 * The bar preview is the bar's own small black pill with its white level bars.
 *
 * These are still previews, not instruments: they animate nothing. Three
 * thumbnails oscillating side by side on a settings screen is noise, and with
 * no microphone behind them any motion here would be invented.
 */

/** Maps an overlay style to its preview graphic. */
export function StylePreview({ style }: { style: OverlayStyle }) {
  // The voice orb is its own portrait: the very renderer the desktop overlay
  // runs, at thumbnail size. Held at "idle" so the picker shows the calm
  // resting look rather than pretending a session is live.
  if (style === "voice_orb") return <VoiceOrb state="idle" size={46} />;
  if (style === "jarvis_bar") return <BarPreview />;
  return <NonePreview />;
}

/** Resting heights of the preview's level bars: a voice, held still. */
const BAR_PREVIEW_LEVELS = [0.15, 0.35, 0.6, 0.85, 1, 0.75, 0.5, 0.3, 0.15];

/**
 * The Dodaios Bar as it looks while a voice runs: a small black pill with a
 * light rim and a row of short white bars.
 */
export function BarPreview() {
  const thick = 1.6;
  const gap = 2.2;
  const row = BAR_PREVIEW_LEVELS.length * thick + (BAR_PREVIEW_LEVELS.length - 1) * gap;
  const left = 23 - row / 2;
  return (
    <div className="flex h-10 w-24 shrink-0 items-center justify-center" data-testid="jarvis-bar-preview">
      <svg viewBox="0 0 46 18" width={46} height={18} aria-hidden>
        <rect x={0.5} y={0.5} width={45} height={17} rx={8.5} fill="#0c0c0c" stroke="#969696" />
        <g fill="#f4f4f4" data-testid="bar-preview-levels">
          {BAR_PREVIEW_LEVELS.map((level, i) => {
            const len = thick + (9 - thick) * level;
            return (
              <rect
                key={i}
                x={left + i * (thick + gap)}
                y={9 - len / 2}
                width={thick}
                height={len}
                rx={thick / 2}
              />
            );
          })}
        </g>
      </svg>
    </div>
  );
}

export function NonePreview() {
  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      className="w-20 opacity-50"
      aria-hidden="true"
    >
      <rect
        x={PILL_X}
        y={PILL_Y}
        width={PILL_W}
        height={PILL_H}
        rx={PILL_R}
        fill="none"
        stroke="#7c766b"
        strokeWidth="1.6"
        strokeDasharray="4 3"
      />
      {/* Diagonal "disabled" strike — kept inside the dashed box (y 11..29)
          and symmetric about its centre (50, 20) so it never juts out as a
          stub above/below the pill. */}
      <line x1="25" y1="25" x2="75" y2="15" stroke="#7c766b" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}
