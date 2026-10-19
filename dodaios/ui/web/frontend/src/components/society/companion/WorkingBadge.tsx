import "./faceMotion.css";

/**
 * Three dots in a small bubble at the corner of an agent's face: the agent
 * is at work. Every look shows it the same way (a pixel creature, a shape, a
 * pet, the lead), so the roster reads at a glance, and the face itself stays
 * in the picture instead of turning into an indicator. The bubble sits on
 * the page's own surface colours; the dots rise one after the other, moved
 * by transforms only.
 *
 * Its host must be positioned (`position: relative`) and `size` pixels wide.
 * A face smaller than WORKING_BADGE_MIN_PX goes without: in a stack of small
 * faces or beside a name in running text the bubble would cover the face it
 * belongs to, and the face still nods at its work.
 */
export const WORKING_BADGE_MIN_PX = 30;

export function WorkingBadge({ size }: { size: number }) {
  if (size < WORKING_BADGE_MIN_PX) return null;
  return <span aria-hidden className="agent-working-badge" data-agent-working style={{ fontSize: size }}><i /><i /><i /></span>;
}
