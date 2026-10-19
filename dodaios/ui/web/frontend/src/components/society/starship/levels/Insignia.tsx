/**
 * The ship's rank insignia as SVG, original to Dodaios (no franchise insignia
 * is copied): silver chevrons for the enlisted ranks, gold pips on a dark bar
 * for the warrant officer and the officers, a gold bar under stars for the
 * flag officers. Drawn on a 48-unit grid with chunky shapes and real gaps, so
 * it stays crisp from 20 to 96 px. `levelModel.insigniaFor` says what each
 * rank wears.
 */
import { useId, type ReactElement } from "react";
import { insigniaFor } from "./levelModel";

export interface InsigniaProps {
  /** A rank id (`ship.rank.<id>`); an unknown id wears the cadet's bar. */
  rank: string;
  /** Edge length in px (default 32). */
  size?: number;
  /** "muted": a flat grey silhouette, for ranks not reached yet. */
  tone?: "metal" | "muted";
  /** Accessible name; without it the insignia is decorative (aria-hidden). */
  title?: string;
  className?: string;
}

const MUTED = "#4b5461";
const BAR_FILL = "#0c1118";

/** A chevron pointing up whose apex sits at `y`. */
const chevron = (y: number) => `7,${y + 11} 24,${y} 41,${y + 11} 41,${y + 16.5} 24,${y + 5.5} 7,${y + 16.5}`;

function star(cx: number, cy: number, r: number): string {
  const pts: string[] = [];
  for (let i = 0; i < 10; i += 1) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    const rr = i % 2 === 0 ? r : r * 0.45;
    pts.push(`${(cx + Math.cos(a) * rr).toFixed(2)},${(cy + Math.sin(a) * rr).toFixed(2)}`);
  }
  return pts.join(" ");
}

/** Centres of `n` marks spaced `step` apart round x = 24. */
const row = (n: number, step: number) => Array.from({ length: n }, (_, i) => 24 + (i - (n - 1) / 2) * step);

export function Insignia({ rank, size = 32, tone = "metal", title, className }: InsigniaProps) {
  const uid = useId().replace(/:/g, "");
  const spec = insigniaFor(rank);
  const muted = tone === "muted";
  const silver = muted ? MUTED : `url(#${uid}s)`;
  const gold = muted ? MUTED : `url(#${uid}g)`;
  const goldLine = muted ? MUTED : "#c8963c";
  const edge = "rgba(0,0,0,0.45)";

  let body: ReactElement;
  if (spec.kind === "bar") {
    body = <rect x="6" y="19" width="36" height="10" rx="3" fill={BAR_FILL} stroke={silver} strokeWidth="1.8" />;
  } else if (spec.kind === "chevrons") {
    const step = 8.5;
    const height = 16.5 + (spec.count - 1) * step + (spec.rocker ? 13 : 0);
    const top = (48 - height) / 2;
    const rockerY = top + (spec.count - 1) * step + 16.5 + 2.5;
    body = (
      <g fill={silver} stroke={edge} strokeWidth="0.6" strokeLinejoin="miter">
        {Array.from({ length: spec.count }, (_, i) => <polygon key={i} points={chevron(top + i * step)} />)}
        {spec.rocker && <path d={`M7 ${rockerY} Q24 ${rockerY + 10} 41 ${rockerY} L41 ${rockerY + 5.5} Q24 ${rockerY + 15.5} 7 ${rockerY + 5.5} Z`} />}
      </g>
    );
  } else if (spec.kind === "pips") {
    const xs = row(spec.solid + spec.hollow, 10);
    body = (
      <g>
        <rect x="3" y="16" width="42" height="16" rx="4" fill={BAR_FILL} stroke={spec.warrant ? silver : goldLine} strokeWidth="1.3" />
        {xs.map((x, i) => (i < spec.solid
          ? <circle key={i} cx={x} cy="24" r="3.9" fill={gold} stroke={edge} strokeWidth="0.5" />
          : <circle key={i} cx={x} cy="24" r="3.2" fill={BAR_FILL} stroke={gold} strokeWidth="1.7" />))}
      </g>
    );
  } else {
    const n = spec.stars;
    const r = n === 1 ? 6.2 : 4.7;
    body = (
      <g fill={gold} stroke={edge} strokeWidth="0.5" strokeLinejoin="round">
        {row(n, 10.4).map((x, i) => <polygon key={i} points={star(x, 19, r)} />)}
        <rect x="5" y="30" width="38" height="7" rx="2" />
      </g>
    );
  }

  return (
    <svg className={className} width={size} height={size} viewBox="0 0 48 48" shapeRendering="geometricPrecision"
      role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      {!muted && (
        <defs>
          <linearGradient id={`${uid}s`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#f6f8fb" />
            <stop offset="0.55" stopColor="#b9c1cc" />
            <stop offset="1" stopColor="#848e9b" />
          </linearGradient>
          <linearGradient id={`${uid}g`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#fbe6a6" />
            <stop offset="0.5" stopColor="#e1b04f" />
            <stop offset="1" stopColor="#a8741f" />
          </linearGradient>
        </defs>
      )}
      {body}
    </svg>
  );
}
