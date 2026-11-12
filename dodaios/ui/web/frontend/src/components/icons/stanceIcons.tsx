/**
 * The permission stances' own glyphs: what the assistant may do without
 * asking, drawn for the composer's permission pill and its menu.
 *
 * Same drawing system as the section icons (sectionIcons.tsx): a 24 × 24 grid
 * with the live area inside 3–21, a 1.6 stroke, round caps and joins,
 * outlines only, one idea per glyph. The stock picks they replace mixed a
 * five-part hand, a document with a pen and a line, and a shield, each at
 * its own weight and density; at 16–18 px that read as three icons from
 * three sets. These are single silhouettes that stay open at that size.
 *
 * Every glyph is shaped like a lucide icon (same props, same ref).
 */
import { defineIcon } from "@/components/icons/sectionIcons";

/** The one shield every guarded stance shares: soft shoulders, a pointed foot. */
const SHIELD =
  "M12 3.25c-1.9 1.55-4.2 2.4-6.75 2.6v5.65c0 4.3 2.7 7.6 6.75 9.25 4.05-1.65 6.75-4.95 6.75-9.25V5.85c-2.55-.2-4.85-1.05-6.75-2.6Z";

/** A raised hand: stops and asks before acting. */
export const StanceAskIcon = defineIcon(
  "StanceAskIcon",
  <>
    <path d="M7.2 15V6.6a1.65 1.65 0 0 1 3.3 0V4.65a1.65 1.65 0 0 1 3.3 0V5.9a1.65 1.65 0 0 1 3.3 0v3a1.65 1.65 0 0 1 3.3 0v5.35A6.75 6.75 0 0 1 13.65 21H12c-2.2 0-3.8-.75-5.1-2.05l-3.1-3.1a1.65 1.65 0 0 1 2.3-2.35Z" />
    <path d="M10.5 6.6v5.15M13.8 5.9v5.85M17.1 8.9v2.85" />
  </>,
);

/** A pencil: edits go through, everything else still asks. */
export const StanceEditsIcon = defineIcon(
  "StanceEditsIcon",
  <>
    <path d="M4 20l1.34-4.6L16.57 4.17a2.3 2.3 0 0 1 3.26 3.26L8.6 18.66Z" />
    <path d="m14.3 6.45 3.25 3.25" />
  </>,
);

/** The shield carrying a warning mark: nothing asks. */
export const StanceBypassIcon = defineIcon(
  "StanceBypassIcon",
  <>
    <path d={SHIELD} />
    <path d="M12 8.5v4.25" />
    <path d="M12 15.9h.01" />
  </>,
);

/** A list of steps, the first one ticked: reads and plans, changes nothing. */
export const StancePlanIcon = defineIcon(
  "StancePlanIcon",
  <>
    <path d="m3.75 7 1.4 1.4L7.6 5.6" />
    <circle cx="5.6" cy="12.2" r="1.15" />
    <circle cx="5.6" cy="17.6" r="1.15" />
    <path d="M11 6.8h9.25M11 12.2h9.25M11 17.6h9.25" />
  </>,
);

/** An eye: looks, touches nothing. */
export const StanceReadOnlyIcon = defineIcon(
  "StanceReadOnlyIcon",
  <>
    <path d="M2.9 12c1.9-3.9 5.2-6 9.1-6s7.2 2.1 9.1 6c-1.9 3.9-5.2 6-9.1 6s-7.2-2.1-9.1-6Z" />
    <circle cx="12" cy="12" r="2.75" />
  </>,
);

/** A spark with a small plus beside it: the runner decides on its own. */
export const StanceAutoIcon = defineIcon(
  "StanceAutoIcon",
  <>
    <path d="M10.5 4c.65 3.9 2.6 5.85 6.5 6.5-3.9.65-5.85 2.6-6.5 6.5-.65-3.9-2.6-5.85-6.5-6.5 3.9-.65 5.85-2.6 6.5-6.5Z" />
    <path d="M18.25 15.5v4.5M16 17.75h4.5" />
  </>,
);

/** The shield with a cross: never asks, and refuses what it would have asked about. */
export const StanceDenyIcon = defineIcon(
  "StanceDenyIcon",
  <>
    <path d={SHIELD} />
    <path d="m9.6 9.7 4.8 4.8M14.4 9.7l-4.8 4.8" />
  </>,
);

/** The bare shield: a stance this app has no drawing for yet. */
export const StanceUnknownIcon = defineIcon("StanceUnknownIcon", <path d={SHIELD} />);
