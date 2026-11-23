/**
 * The agent's arrow, one look wherever an agent acts: over its browser
 * (`AgentCursor`) and over a node it builds (`nodes/live/LivePresence`).
 *
 * A rounded arrowhead without a tail, dark with a white rim, so it reads on a
 * light page and a dark one alike, under a soft glow in the app's signal
 * colour (`--accent`). A second agent at work sets `--agent-glow` to its own
 * muted hue on any parent.
 */
import "./agentArrow.css";

/** The tip, in the arrow's own pixels: the point it stands on. */
export const ARROW_TIP = { x: 3, y: 2.5 } as const;
/** The arrow's box, in CSS pixels. */
export const ARROW_SIZE = 24;

const ARROW_PATH = "M3 2.5 L20.5 10.2 L12.4 12.6 L9.6 20.8 Z";

export function AgentArrow({ className }: { className?: string }) {
  return (
    <svg
      className={className ? `agent-arrow ${className}` : "agent-arrow"}
      width={ARROW_SIZE}
      height={ARROW_SIZE}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      data-testid="agent-arrow"
    >
      <path d={ARROW_PATH} />
    </svg>
  );
}
