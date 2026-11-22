/**
 * An agent's presence over a node it is building: one look for every type.
 *
 * A small arrow cursor with the agent's name tag fixed to it, the way a
 * colleague's cursor looks in a shared document, and a thin frame around the
 * region being written. While the agent thinks between edits the tag says so
 * ("Dodaios is working…") with a slow sheen over the words; there is no
 * separate status pill. Black and white from the `--presence-*` tokens; a
 * muted tint only when several agents work at once.
 *
 * This component only draws the pieces. The player (`playback.ts`) moves
 * them, frame by frame, without re-rendering React. Nothing shows before the
 * player has placed the cursor on something written (`data-placed`).
 */
import { forwardRef, useLayoutEffect, useRef, type CSSProperties } from "react";

import type { PresenceElements } from "./playback";
import "./live.css";

/** The arrow, tip at (2, 1.5) in its own 16 x 18 box. */
const ARROW = "M2 1.5 L2 14.2 L5.3 11.1 L7.5 15.9 L9.7 14.9 L7.6 10.2 L12 10 Z";

export interface LivePresenceProps {
  /** The name on the tag. */
  name: string;
  /** What the tag says while the agent thinks between edits. */
  status: string;
  /** Shown at all (fades in and out). */
  visible: boolean;
  /** The agent is still at work: the tag may say so between edits. */
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
  useLayoutEffect(() => {
    if (cursor.current && frame.current && tag.current) {
      onReady({ cursor: cursor.current, frame: frame.current, tag: tag.current });
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
      data-placed="false"
      style={style}
    >
      <div ref={frame} className="live-presence-frame" data-shown="false" data-testid="live-presence-frame" />
      <div ref={cursor} className="live-presence-cursor" data-testid="live-presence-cursor">
        <svg width="16" height="18" viewBox="0 0 16 18" fill="none">
          <path d={ARROW} strokeWidth="1.2" strokeLinejoin="round" />
        </svg>
        <div ref={tag} className="live-presence-tag" data-side="right" data-vside="down" data-testid="live-presence-tag">
          <span className="live-presence-name" data-testid="live-presence-name">{name}</span>
          <span className="live-presence-status" data-testid="live-presence-status">
            {status}
          </span>
        </div>
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
