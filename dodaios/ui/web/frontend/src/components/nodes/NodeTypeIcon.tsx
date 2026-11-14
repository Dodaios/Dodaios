/**
 * The Nodes library's own icons: one per node type, and the section's mark
 * for the navigation rail.
 *
 * Drawn in the family of `icons/sectionIcons.tsx`: a 24-unit grid with the
 * live area inside 3–21, a 1.6 stroke with round caps and joins, a 2.5 corner
 * radius on boxes, outlines only, one idea per glyph.
 */
import type { LucideIcon } from "lucide-react";

import { defineIcon } from "@/components/icons/sectionIcons";

import type { CardType } from "./nodeModel";

// The section's own mark lives with the other section icons (the navigation
// loads those up front); re-exported here for the library's own use.
export { NodesIcon } from "@/components/icons/sectionIcons";

/** A page with a folded corner. */
const DocsTypeIcon = defineIcon(
  "NodeDocsIcon",
  <>
    <path d="M7.5 3.5h6.25L18.5 8.25V18.5a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2Z" />
    <path d="M13.75 3.5v3.25a1.5 1.5 0 0 0 1.5 1.5h3.25" />
  </>,
);

/** A deck: the front slide, with the next one showing behind it. */
const SlidesTypeIcon = defineIcon(
  "NodeSlidesIcon",
  <>
    <rect x="3.5" y="8" width="13.5" height="10.5" rx="2.5" />
    <path d="M7 4.75h11a2.5 2.5 0 0 1 2.5 2.5v7.5" />
  </>,
);

/** A table: a header row over two rows, a first column beside them. */
const SheetsTypeIcon = defineIcon(
  "NodeSheetsIcon",
  <>
    <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
    <path d="M3.5 9.5h17" />
    <path d="M3.5 14.5h17" />
    <path d="M9.5 9.5v10" />
  </>,
);

/** A picture: a sun over a hill inside a frame. */
const DesignTypeIcon = defineIcon(
  "NodeDesignIcon",
  <>
    <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
    <circle cx="9" cy="9.75" r="1.75" />
    <path d="m3.75 17.5 4.75-4.5 3.5 3.25 3-2.75 5.25 4.75" />
  </>,
);

/** Three bars of uneven height, standing on a line. */
const DataTypeIcon = defineIcon(
  "NodeDataIcon",
  <>
    <rect x="5" y="11.5" width="3.2" height="6" rx="1" />
    <rect x="10.4" y="5" width="3.2" height="12.5" rx="1" />
    <rect x="15.8" y="8" width="3.2" height="9.5" rx="1" />
    <path d="M4.25 20.5h15.5" />
  </>,
);

/** Two notes on a board, joined by a line: a diagram. */
const WhiteboardTypeIcon = defineIcon(
  "NodeWhiteboardIcon",
  <>
    <rect x="3.5" y="3.5" width="7.5" height="6.5" rx="2" />
    <rect x="13" y="14" width="7.5" height="6.5" rx="2" />
    <path d="M11 6.75h3.75a2 2 0 0 1 2 2V14" />
  </>,
);

/** A video: a play button inside a screen. */
const MotionTypeIcon = defineIcon(
  "NodeMotionIcon",
  <>
    <rect x="3.5" y="5" width="17" height="14" rx="2.5" />
    <path d="M10.25 9.25v5.5L14.75 12Z" />
  </>,
);

/** Lines of an answer: a run that left text and no page. */
const OutputTypeIcon = defineIcon(
  "NodeOutputIcon",
  <>
    <path d="M5 7h14" />
    <path d="M5 12h14" />
    <path d="M5 17h8.5" />
  </>,
);

const ICON_BY_TYPE: Record<CardType, LucideIcon> = {
  docs: DocsTypeIcon,
  slides: SlidesTypeIcon,
  sheets: SheetsTypeIcon,
  design: DesignTypeIcon,
  data: DataTypeIcon,
  whiteboard: WhiteboardTypeIcon,
  motion: MotionTypeIcon,
  output: OutputTypeIcon,
};

/** The line icon of a node type (24-unit grid, drawn with `currentColor`). */
export function NodeTypeIcon({ type, className }: { type: CardType; className?: string }) {
  const Icon = ICON_BY_TYPE[type] ?? OutputTypeIcon;
  return <Icon data-node-type-icon={type} className={className} />;
}
