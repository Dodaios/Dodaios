/**
 * An agent's presence over a node it is building: one look for every type.
 *
 * The agent's arrow (`AgentArrow`, the same as over its browser) with the
 * agent's name tag fixed under its tip, and a thin frame around the region
 * being written. While the agent thinks between edits the tag says so
 * ("Dodaios is working…") with a slow sheen over the words; there is no
 * separate status pill. The arrow leans as it travels, a ring opens where it
 * lands on a new block, and it gives a small shake when the agent starts to
 * think. The glow is the app's signal colour; several agents at once each
 * get a muted hue of their own.
 *
 * This component only draws the pieces. The player (`playback.ts`) moves
 * them, frame by frame, without re-rendering React. Nothing shows before the
 * player has placed the cursor on something written (`data-placed`).
 */
import { forwardRef, useLayoutEffect, useRef, type CSSProperties } from "react";

import { AgentArrow } from "@/components/society/card/AgentArrow";
import type { PresenceElements } from "./playback";
import "./live.css";

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
  const art = useRef<HTMLDivElement>(null);
  const arrow = useRef<HTMLDivElement>(null);
  const ring = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (cursor.current && frame.current && tag.current) {
      onReady({
        cursor: cursor.current,
        frame: frame.current,
        tag: tag.current,
        art: art.current ?? undefined,
        arrow: arrow.current ?? undefined,
        ring: ring.current ?? undefined,
      });
    }
    return () => onReady(null);
  }, [onReady]);
  const style = tint ? ({ "--presence-ink": tint, "--agent-glow": tint } as CSSProperties) : undefined;
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
        <div ref={ring} className="live-presence-ring" />
        <div ref={art} className="live-presence-art">
          <div ref={arrow} className="live-presence-arrow">
            <AgentArrow />
          </div>
        </div>
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
