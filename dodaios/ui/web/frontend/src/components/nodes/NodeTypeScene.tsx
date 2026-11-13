/**
 * The small scene on a type card: a hint of what a node of that type looks
 * like inside (lines of text, a slide, a grid of cells, …), drawn in the
 * type's ink on a 120 × 64 canvas.
 *
 * Every mark uses `currentColor` and an opacity, so the scene takes its hue
 * from the card it sits on and reads the same in the light and dark theme.
 */
import type { ReactNode } from "react";

import type { NodeType } from "./nodeModel";

/** One bar of a text line or a label: a rounded rectangle. */
function Bar({ x, y, w, h = 3, o }: { x: number; y: number; w: number; h?: number; o: number }) {
  return <rect x={x} y={y} width={w} height={h} rx={h / 2} fill="currentColor" opacity={o} />;
}

const SCENES: Record<NodeType, ReactNode> = {
  /* A page: a title, then lines of text of uneven length. */
  docs: (
    <>
      <Bar x={14} y={12} w={50} h={6} o={0.9} />
      <Bar x={14} y={26} w={92} o={0.38} />
      <Bar x={14} y={33} w={84} o={0.38} />
      <Bar x={14} y={40} w={90} o={0.38} />
      <Bar x={14} y={47} w={58} o={0.38} />
      <Bar x={14} y={57} w={80} o={0.38} />
    </>
  ),
  /* A slide: a title and a line on the left, a picture on the right. */
  slides: (
    <>
      <rect x={12} y={8} width={96} height={52} rx={4} fill="currentColor" opacity={0.12} />
      <rect x={12.5} y={8.5} width={95} height={51} rx={3.5} fill="none" stroke="currentColor" strokeOpacity={0.45} />
      <Bar x={22} y={20} w={40} h={5} o={0.9} />
      <Bar x={22} y={30} w={30} o={0.4} />
      <Bar x={22} y={36} w={24} o={0.4} />
      <circle cx={84} cy={35} r={12} fill="currentColor" opacity={0.42} />
      <circle cx={88} cy={31} r={4} fill="currentColor" opacity={0.85} />
    </>
  ),
  /* A grid of cells: a header row, and one cell picked. */
  sheets: (
    <>
      <rect x={10} y={8} width={100} height={11} rx={2} fill="currentColor" opacity={0.3} />
      {[30, 55, 80].map((x) => (
        <path key={x} d={`M${x} 8V64`} stroke="currentColor" strokeOpacity={0.32} />
      ))}
      {[19, 30, 41, 52, 63].map((y) => (
        <path key={y} d={`M10 ${y}H110`} stroke="currentColor" strokeOpacity={0.32} />
      ))}
      <path d="M10 8V64M110 8V64" stroke="currentColor" strokeOpacity={0.32} />
      <rect x={55.5} y={30.5} width={24} height={10} fill="currentColor" fillOpacity={0.3} stroke="currentColor" strokeWidth={1.4} />
      <Bar x={14} y={34} w={12} o={0.55} />
      <Bar x={34} y={45} w={16} o={0.55} />
      <Bar x={84} y={23} w={14} o={0.55} />
    </>
  ),
  /* Shapes laid over each other: a circle, a tilted square, a dot. */
  design: (
    <>
      <rect
        x={58}
        y={12}
        width={34}
        height={34}
        rx={8}
        fill="currentColor"
        opacity={0.3}
        transform="rotate(12 75 29)"
      />
      <circle cx={46} cy={38} r={20} fill="currentColor" opacity={0.55} />
      <circle cx={94} cy={54} r={6} fill="currentColor" opacity={0.9} />
      <path d="M16 20c8-10 18-10 22-2" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" opacity={0.7} />
    </>
  ),
  /* Bars rising, and the trend line over them. */
  data: (
    <>
      {[
        [14, 44],
        [30, 36],
        [46, 40],
        [62, 28],
        [78, 22],
        [94, 14],
      ].map(([x, y], index, all) => (
        <rect
          key={x}
          x={x}
          y={y}
          width={12}
          height={64 - y}
          rx={2.5}
          fill="currentColor"
          opacity={index === all.length - 1 ? 0.85 : 0.32}
        />
      ))}
      <path
        d="M20 34 36 26 52 30 68 18 84 13 100 5"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={100} cy={5} r={3} fill="currentColor" />
    </>
  ),
  /* Two notes on a board, joined by a line. */
  whiteboard: (
    <>
      <rect x={12} y={12} width={32} height={32} rx={3} fill="currentColor" opacity={0.55} transform="rotate(-6 28 28)" />
      <rect x={74} y={20} width={32} height={32} rx={3} fill="currentColor" opacity={0.32} transform="rotate(5 90 36)" />
      <Bar x={18} y={22} w={18} o={0.9} />
      <Bar x={19} y={29} w={12} o={0.9} />
      <path
        d="M46 30c10 0 12 14 26 12"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeDasharray="3 3.5"
      />
      <circle cx={30} cy={58} r={4} fill="none" stroke="currentColor" strokeWidth={1.6} opacity={0.6} />
    </>
  ),
  /* A frame with a play mark, and a timeline with its playhead. */
  motion: (
    <>
      <rect x={12} y={6} width={96} height={38} rx={4} fill="currentColor" opacity={0.14} />
      <rect x={12.5} y={6.5} width={95} height={37} rx={3.5} fill="none" stroke="currentColor" strokeOpacity={0.45} />
      <path d="M55 17.5v15l12-7.5Z" fill="currentColor" opacity={0.9} />
      <path d="M14 55H106" stroke="currentColor" strokeWidth={3} strokeLinecap="round" opacity={0.28} />
      <path d="M14 55H58" stroke="currentColor" strokeWidth={3} strokeLinecap="round" opacity={0.9} />
      <circle cx={58} cy={55} r={4.5} fill="currentColor" />
    </>
  ),
};

/** The scene of one node type, scaled to the width it is given. */
export function NodeTypeScene({ type, className }: { type: NodeType; className?: string }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 120 64"
      preserveAspectRatio="xMidYMin meet"
      data-node-type-scene={type}
      className={className}
    >
      {SCENES[type]}
    </svg>
  );
}
