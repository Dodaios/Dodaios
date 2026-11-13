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

/** A presentation board on its stand. */
const SlidesTypeIcon = defineIcon(
  "NodeSlidesIcon",
  <>
    <path d="M12 3v2.25" />
    <rect x="3.75" y="5.25" width="16.5" height="10.75" rx="2" />
    <path d="M12 16v2.5" />
    <path d="m8.75 20.75 3.25-2.25 3.25 2.25" />
  </>,
);

/** A grid of cells: three columns, three rows. */
const SheetsTypeIcon = defineIcon(
  "NodeSheetsIcon",
  <>
    <rect x="3.5" y="5" width="17" height="14" rx="2" />
    <path d="M3.5 9.67h17" />
    <path d="M3.5 14.33h17" />
    <path d="M9.17 5v14" />
    <path d="M14.83 5v14" />
  </>,
);

/** A painter's palette with three dabs of paint. */
const DesignTypeIcon = defineIcon(
  "NodeDesignIcon",
  <>
    <path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.05 0 1.9-.85 1.9-1.9 0-.5-.2-.95-.5-1.3-.3-.35-.5-.8-.5-1.3 0-1.05.85-1.9 1.9-1.9H17a3.5 3.5 0 0 0 3.5-3.5c0-3.9-3.8-7.1-8.5-7.1Z" />
    <circle cx="7.6" cy="12.6" r="0.9" fill="currentColor" stroke="none" />
    <circle cx="10.6" cy="8" r="0.9" fill="currentColor" stroke="none" />
    <circle cx="15.2" cy="8.4" r="0.9" fill="currentColor" stroke="none" />
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

/** A square with a circle laid over its corner: shapes on a board. */
const WhiteboardTypeIcon = defineIcon(
  "NodeWhiteboardIcon",
  <>
    <path d="M9.4 14H6.5A2.5 2.5 0 0 1 4 11.5v-5A2.5 2.5 0 0 1 6.5 4h5A2.5 2.5 0 0 1 14 6.5v2.9" />
    <circle cx="15" cy="15" r="5.5" />
  </>,
);

/** Three speed lines trailing a circle: something moving. */
const MotionTypeIcon = defineIcon(
  "NodeMotionIcon",
  <>
    <circle cx="16" cy="12" r="4.75" />
    <path d="M3.5 8.25h6" />
    <path d="M5.5 12h4" />
    <path d="M3.5 15.75h6" />
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
