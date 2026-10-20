/**
 * The ship's rank insignia, drawn on a 2D canvas: silver chevrons for the
 * enlisted ranks, a gold bar for the warrant officer, gold pips for officers
 * (a hollow pip is the half step between two full ones) and gold stars over
 * a bar for the flag ranks. Original marks, deliberately plain, so they read
 * at a plaque's size from across the hall.
 */
import type { Rank } from "../../levels/ranks";

export const SILVER = "#cfd5dc";
export const SILVER_DEEP = "#7d8794";
export const GOLD = "#e1b04f";
export const GOLD_DEEP = "#9c6d22";

/** What a rank's mark is made of. */
export interface InsigniaSpec {
  kind: "candidate" | "chevrons" | "bar" | "pips" | "stars";
  /** Chevrons, pips or stars. */
  count: number;
  /** Officers: how many of the pips are hollow (the half steps). */
  hollow: number;
  /** Chevrons: a rocker arc under them (the chief). */
  rocker: boolean;
}

const SPECS: Record<string, InsigniaSpec> = {
  cadet: { kind: "candidate", count: 0, hollow: 0, rocker: false },
  crewman: { kind: "chevrons", count: 1, hollow: 0, rocker: false },
  specialist: { kind: "chevrons", count: 2, hollow: 0, rocker: false },
  petty_officer: { kind: "chevrons", count: 3, hollow: 0, rocker: false },
  chief_petty_officer: { kind: "chevrons", count: 3, hollow: 0, rocker: true },
  warrant_officer: { kind: "bar", count: 1, hollow: 0, rocker: false },
  ensign: { kind: "pips", count: 1, hollow: 0, rocker: false },
  lieutenant_junior_grade: { kind: "pips", count: 2, hollow: 1, rocker: false },
  lieutenant: { kind: "pips", count: 2, hollow: 0, rocker: false },
  lieutenant_commander: { kind: "pips", count: 3, hollow: 1, rocker: false },
  commander: { kind: "pips", count: 3, hollow: 0, rocker: false },
  captain: { kind: "pips", count: 4, hollow: 0, rocker: false },
  commodore: { kind: "stars", count: 1, hollow: 0, rocker: false },
  rear_admiral: { kind: "stars", count: 2, hollow: 0, rocker: false },
  vice_admiral: { kind: "stars", count: 3, hollow: 0, rocker: false },
  admiral: { kind: "stars", count: 4, hollow: 0, rocker: false },
};

/** The mark of a rank; a rank the table does not know falls back by its tier. */
export function insigniaSpec(rank: Rank): InsigniaSpec {
  const known = SPECS[rank.id];
  if (known) return known;
  if (rank.tier === "flag") return { kind: "stars", count: Math.max(1, rank.pips), hollow: 0, rocker: false };
  if (rank.tier === "enlisted") return { kind: "chevrons", count: Math.max(1, rank.pips), hollow: 0, rocker: false };
  return { kind: "pips", count: Math.max(1, rank.pips), hollow: 0, rocker: false };
}

function metal(ctx: CanvasRenderingContext2D, x: number, y0: number, y1: number, light: string, deep: string): CanvasGradient {
  const g = ctx.createLinearGradient(x, y0, x, y1);
  g.addColorStop(0, light); g.addColorStop(0.55, light); g.addColorStop(1, deep);
  return g;
}

function star(ctx: CanvasRenderingContext2D, cx: number, cy: number, r: number): void {
  ctx.beginPath();
  for (let i = 0; i < 10; i += 1) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    const rr = i % 2 ? r * 0.42 : r;
    ctx.lineTo(cx + Math.cos(a) * rr, cy + Math.sin(a) * rr);
  }
  ctx.closePath();
  ctx.fill();
}

/**
 * Draw a rank's insignia centred on (cx, cy), `size` pixels across. `dim`
 * draws it as an unlit outline-grey (a rank still ahead).
 */
export function drawInsignia(ctx: CanvasRenderingContext2D, rank: Rank, cx: number, cy: number, size: number, dim = false): void {
  const spec = insigniaSpec(rank);
  const u = size / 100;
  ctx.save();
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  const silver = dim ? "#59606a" : metal(ctx, cx, cy - 30 * u, cy + 30 * u, SILVER, SILVER_DEEP);
  const gold = dim ? "#5f5644" : metal(ctx, cx, cy - 30 * u, cy + 30 * u, GOLD, GOLD_DEEP);
  if (!dim) { ctx.shadowColor = spec.kind === "chevrons" || spec.kind === "candidate" ? "rgba(220,230,240,0.45)" : "rgba(240,190,90,0.55)"; ctx.shadowBlur = 8 * u; }

  if (spec.kind === "candidate") {
    // An open diamond: on the ladder, no stripe yet.
    ctx.strokeStyle = silver; ctx.lineWidth = 7 * u;
    ctx.beginPath(); ctx.moveTo(cx, cy - 24 * u); ctx.lineTo(cx + 20 * u, cy); ctx.lineTo(cx, cy + 24 * u); ctx.lineTo(cx - 20 * u, cy); ctx.closePath(); ctx.stroke();
  } else if (spec.kind === "chevrons") {
    ctx.strokeStyle = silver; ctx.lineWidth = 9 * u;
    const gap = 15 * u;
    const top = cy - ((spec.count - 1) * gap) / 2 - (spec.rocker ? 8 * u : 0) - 6 * u;
    for (let i = 0; i < spec.count; i += 1) {
      const y = top + i * gap;
      ctx.beginPath(); ctx.moveTo(cx - 30 * u, y + 16 * u); ctx.lineTo(cx, y); ctx.lineTo(cx + 30 * u, y + 16 * u); ctx.stroke();
    }
    if (spec.rocker) {
      const y = top + spec.count * gap + 8 * u;
      ctx.beginPath(); ctx.moveTo(cx - 30 * u, y); ctx.quadraticCurveTo(cx, y + 18 * u, cx + 30 * u, y); ctx.stroke();
    }
  } else if (spec.kind === "bar") {
    ctx.fillStyle = gold;
    ctx.fillRect(cx - 34 * u, cy - 8 * u, 68 * u, 16 * u);
    // The warrant's break: a dark notch in the middle of the bar.
    ctx.shadowBlur = 0;
    ctx.fillStyle = dim ? "#2a2c30" : "#1a1c22";
    ctx.fillRect(cx - 5 * u, cy - 8 * u, 10 * u, 16 * u);
  } else if (spec.kind === "pips") {
    const r = 9 * u, gap = 25 * u;
    const x0 = cx - ((spec.count - 1) * gap) / 2;
    for (let i = 0; i < spec.count; i += 1) {
      const x = x0 + i * gap;
      const hollow = i >= spec.count - spec.hollow;
      ctx.beginPath(); ctx.arc(x, cy, hollow ? r - 2.5 * u : r, 0, Math.PI * 2);
      if (hollow) { ctx.strokeStyle = gold; ctx.lineWidth = 4.5 * u; ctx.stroke(); }
      else { ctx.fillStyle = gold; ctx.fill(); }
    }
  } else {
    const r = 12 * u, gap = 25 * u;
    const x0 = cx - ((spec.count - 1) * gap) / 2;
    ctx.fillStyle = gold;
    for (let i = 0; i < spec.count; i += 1) star(ctx, x0 + i * gap, cy - 6 * u, r);
    ctx.fillRect(cx - 44 * u, cy + 12 * u, 88 * u, 7 * u);
  }
  ctx.restore();
}
