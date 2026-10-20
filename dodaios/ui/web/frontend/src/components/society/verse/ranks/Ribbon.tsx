/**
 * A commendation ribbon bar, 30 × 8 mm (style bible §7.2): a flat two-tone
 * stripe pattern from the ship's palette, no metallic thread and no gold
 * (gold belongs to the flag officers' pips alone), in a hairline frame. On a
 * uniform they sit in one row above the rank plate, at most four.
 */
import { memo } from "react";
import type { RibbonId } from "../../progression/levelCatalog";

/** Stripes left to right: [width in mm, colour]; every pattern sums to 30 and uses two colours. */
export const RIBBON_STRIPES: Readonly<Record<RibbonId, readonly (readonly [number, string])[]>> = {
  ribbon_good_conduct: [[9, "#5e6368"], [3, "#d9dde0"], [6, "#5e6368"], [3, "#d9dde0"], [9, "#5e6368"]],
  ribbon_meritorious: [[12, "#4d86d9"], [6, "#d9dde0"], [12, "#4d86d9"]],
  ribbon_distinguished: [[10, "#2a2d31"], [10, "#e3242b"], [10, "#2a2d31"]],
  ribbon_fleet_cross: [[3, "#f2f4f5"], [8, "#e3242b"], [8, "#f2f4f5"], [8, "#e3242b"], [3, "#f2f4f5"]],
};

export const Ribbon = memo(function Ribbon({ ribbon, height = 10, label }: { ribbon: RibbonId; height?: number; label?: string }) {
  let x = 0;
  return (
    <svg
      width={(height * 30) / 8}
      height={height}
      viewBox="0 0 30 8"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      data-ribbon={ribbon}
      shapeRendering="crispEdges"
    >
      {RIBBON_STRIPES[ribbon].map(([width, colour], index) => {
        const stripe = <rect key={index} x={x} y={0} width={width} height={8} fill={colour} />;
        x += width;
        return stripe;
      })}
      <rect x={0.25} y={0.25} width={29.5} height={7.5} fill="none" stroke="#0b0c0e" strokeWidth={0.5} opacity={0.8} />
    </svg>
  );
});
