/**
 * An agent's presence over a node it is building: one look for every type.
 *
 * An arrow cursor that glides to what is being written, a thin frame around
 * that region (growing as content arrives) with the agent's name tag on its
 * corner, and a small status pill beside the cursor while the agent thinks
 * between edits. Black and white from the `--presence-*` tokens; a muted tint
 * only when several agents work at once.
 *
 * This component only draws the pieces. The player (`playback.ts`) moves
 * them, frame by frame, without re-rendering React.
 */
import { forwardRef, useLayoutEffect, useRef, type CSSProperties } from "react";

import type { PresenceElements } from "./playback";
import "./live.css";

/** The arrow, the same outline as the agent's cursor over its browser. */
const ARROW = "M7.2 2.4 L4.6 28.8 L11.2 24.2 L15.4 39.2 L20.2 36.6 L16.2 22.2 L31.2 21.2 Z";

export interface LivePresenceProps {
  /** The name on the tag. */
  name: string;
  /** What the pill says while the agent thinks between edits. */
  status: string;
  /** Shown at all (fades in and out). */
  visible: boolean;
  /** The agent is still at work: the pill may show between edits. */
  building: boolean;
  /** A muted per-agent ink, only when several agents work at once (HSL channels). */
  tint?: string | null;
  /** The pieces, once drawn, for the player. */
  onReady: (elements: PresenceElements | null) => void;
}

export const LivePresence = forwardRef<HTMLDivElement, LivePresenceProps>(function LivePresence(
  { name, status, visible, building, tint, onReady },
  layer,
) {
  const cursor = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const tag = useRef<HTMLDivElement>(null);
  const pill = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (cursor.current && frame.current && tag.current && pill.current) {
      onReady({ cursor: cursor.current, frame: frame.current, tag: tag.current, pill: pill.current });
    }
    return () => onReady(null);
  }, [onReady]);
  const style = tint ? ({ "--presence-ink": tint } as CSSProperties) : undefined;
  return (
    <div
      ref={layer}
      aria-hidden="true"
      className="live-presence"
      data-testid="live-presence"
      data-visible={visible ? "true" : "false"}
      data-building={building ? "true" : "false"}
      data-phase="thinking"
      style={style}
    >
      <div ref={frame} className="live-presence-frame" data-shown="false" data-testid="live-presence-frame" />
      <div ref={cursor} className="live-presence-cursor" data-testid="live-presence-cursor">
        <svg width="34" height="42" viewBox="0 0 34 42" fill="none">
          <path d={ARROW} strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />
        </svg>
      </div>
      <div ref={tag} className="live-presence-tag" data-testid="live-presence-tag">
        {name}
      </div>
      <div ref={pill} className="live-presence-pill" data-testid="live-presence-status">
        <span className="live-presence-dot" />
        <span>{status}</span>
      </div>
    </div>
  );
});

/**
 * The muted ink of one agent among several (HSL channels), or null when one
 * agent is at work: a single agent is always black and white.
 */
export function presenceTint(authorId: string, activeAuthorIds: readonly string[], dark: boolean): string | null {
  if (new Set(activeAuthorIds).size < 2) return null;
  let hash = 0;
  for (const char of authorId) hash = (hash * 31 + char.charCodeAt(0)) | 0;
  const hue = Math.abs(hash) % 360;
  return dark ? `${hue} 22% 78%` : `${hue} 24% 30%`;
}
