/**
 * The chest rank plate as a flat SVG, drawn to the style bible
 * (art/verse/style-bible.md §7.2) in millimetres: a brushed-steel plate
 * 54 × 22 mm with 45° chamfered ends (an elongated hexagon), a steel pin head
 * at each end, and six elongated-hexagon sockets 12 × 7 mm in two rows of
 * three (pitch 15 mm across, 9 mm down). The rank's pattern (`ranks.ts`)
 * decides which sockets hold a raised enamel pip; the tier decides its
 * colour, one colour per plate. Flat fills and hairlines only: no gradient,
 * no glow.
 *
 * `size` is the plate's height in CSS pixels; the width follows the plate's
 * proportions. `revealed` (0..6) hides the pips past that count, for the
 * promotion notice to set them one by one.
 */
import { memo } from "react";
import { PLATE_EDGE, PLATE_RECESS, PLATE_STEEL, plateTiles, type RankId } from "./ranks";

/** Plate geometry in millimetres. */
const W = 54;
const H = 22;
const MID = H / 2;
const PITCH_X = 15;
const PITCH_Y = 9;
const SLOT_W = 12;
const SLOT_H = 7;

export const PLATE_ASPECT = W / H;

/** Centre of slot `index` (top row 0..2, bottom row 3..5, as seen facing the wearer). */
export function slotCentre(index: number): { x: number; y: number } {
  return { x: W / 2 + ((index % 3) - 1) * PITCH_X, y: MID + (index < 3 ? -1 : 1) * (PITCH_Y / 2) };
}

/** An elongated hexagon centred on (cx, cy): pointed ends at 45°. */
function hexagon(cx: number, cy: number, w: number, h: number): string {
  const half = h / 2;
  const left = cx - w / 2;
  const right = cx + w / 2;
  return `M${left} ${cy}L${left + half} ${cy - half}H${right - half}L${right} ${cy}L${right - half} ${cy + half}H${left + half}Z`;
}

const OUTLINE = hexagon(W / 2, MID, W, H);

export interface RankPlateProps {
  rank: RankId;
  /** Height in CSS pixels. */
  size?: number;
  /** Accessible name; without one the plate is decorative. */
  label?: string;
  /** How many of the lit pips to show, in slot order (default: all). */
  revealed?: number;
  className?: string;
}

export const RankPlate = memo(function RankPlate({ rank, size = 16, label, revealed, className }: RankPlateProps) {
  const { lit, colour, tier } = plateTiles(rank);
  let shown = 0;
  return (
    <svg
      className={className}
      width={size * PLATE_ASPECT}
      height={size}
      viewBox={`0 0 ${W} ${H}`}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      data-rank={rank}
      data-tier={tier}
    >
      <path d={OUTLINE} fill={PLATE_STEEL} />
      {/* Brushing: two faint lines along the plate. */}
      <path d={`M${MID} 1.2H${W - MID}M${MID} ${H - 1.2}H${W - MID}`} stroke="#ffffff" strokeWidth={0.5} opacity={0.18} />
      <path d={OUTLINE} fill="none" stroke={PLATE_EDGE} strokeWidth={0.8} />
      {/* The two pin heads. */}
      <circle cx={3.4} cy={MID} r={1.3} fill={PLATE_EDGE} />
      <circle cx={W - 3.4} cy={MID} r={1.3} fill={PLATE_EDGE} />
      {lit.map((on, index) => {
        const { x, y } = slotCentre(index);
        const show = on && (revealed === undefined || shown++ < revealed);
        return (
          <g key={index} data-slot={index} data-lit={show ? "true" : "false"}>
            <path d={hexagon(x, y, SLOT_W, SLOT_H)} fill={PLATE_RECESS} stroke={PLATE_EDGE} strokeWidth={0.5} />
            {show && (
              <>
                <path d={hexagon(x, y, SLOT_W - 2, SLOT_H - 2)} fill={colour} />
                <path d={`M${x - 2.5} ${y - 1.9}H${x + 2.5}`} stroke="#ffffff" strokeWidth={0.6} opacity={0.35} />
              </>
            )}
          </g>
        );
      })}
    </svg>
  );
});
