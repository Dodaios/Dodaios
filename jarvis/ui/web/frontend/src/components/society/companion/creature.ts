/**
 * A pixel creature: an agent face grown from three stored values (a number, a
 * colour world, an eye kind). The number seeds a mirrored 9 x 9 grid whose
 * middle is always filled, so every roll reads as a figure; the eyes sit in
 * the same cells on every creature, so each state plays on every shape.
 *
 * Everything here is pure: the grid, the poses of each state and the cubes
 * the painters draw. `creaturePaint.ts` draws them on a 2D canvas for the
 * profile faces, `CreatureModel.tsx` builds them for the Verse.
 */
import { z } from "zod";

export type Rgb = readonly [number, number, number];

function hexRgb(hex: string): Rgb {
  const n = parseInt(hex.slice(1), 16);
  return [n >> 16, (n >> 8) & 255, n & 255];
}

export function mixRgb(a: Rgb, b: Rgb, t: number): Rgb {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

const DARK_INK = "#15151d";

/** A colour world: three stops from the head down, and the ink of the face. */
export interface CreaturePalette {
  id: string;
  colors: readonly [string, string, string];
  rgb: readonly [Rgb, Rgb, Rgb];
  ink: Rgb;
}

function palette(id: string, top: string, middle: string, bottom: string, ink = DARK_INK): CreaturePalette {
  return { id, colors: [top, middle, bottom], rgb: [hexRgb(top), hexRgb(middle), hexRgb(bottom)], ink: hexRgb(ink) };
}

export const CREATURE_PALETTES: readonly CreaturePalette[] = [
  palette("lava", "#ffe45c", "#ff8a3c", "#ff3d6e"),
  palette("ocean", "#5ef2d6", "#2a9dff", "#5a48f0"),
  palette("neon", "#ff5fd2", "#a25bff", "#3fc8ff"),
  palette("moss", "#e2ff5a", "#4fdc7a", "#0c9c8c"),
  palette("glacier", "#d4f6ff", "#6fbcff", "#3d5fe0"),
  palette("gold", "#fff0a6", "#ffcd61", "#f08a2c"),
  palette("candy", "#ffc6ec", "#ff86b6", "#ff5a6e"),
  palette("midnight", "#8f9bff", "#5546d6", "#2a1e78", "#f1f3ff"),
];

export const CREATURE_EYES = ["dot", "tall", "wide", "visor"] as const;
export type CreatureEyes = typeof CREATURE_EYES[number];

export const CREATURE_SEED_MAX = 99_999;

/** `CompanionCreature` in `jarvis/society/companion.py` (a parity test pins the palette and eye ids). Ids stay open, so a newer catalog never invalidates a saved look. */
export const creatureSchema = z.object({
  seed: z.number().int().min(0).max(CREATURE_SEED_MAX),
  palette: z.string().regex(/^[a-z]{1,20}$/),
  eyes: z.string().regex(/^[a-z]{1,20}$/),
}).strict();
export type CreatureLook = z.infer<typeof creatureSchema>;

/** What a creature can act out; every surface maps its own vocabulary onto these. */
export const CREATURE_STATES = ["idle", "listening", "thinking", "working", "talking", "asking", "success", "error", "sleeping"] as const;
export type CreatureState = typeof CREATURE_STATES[number];

/** An unknown colour world (a look saved by a newer build) wears the first one. */
export function creaturePalette(id: string): CreaturePalette {
  return CREATURE_PALETTES.find((entry) => entry.id === id) ?? CREATURE_PALETTES[0]!;
}

function creatureEyes(id: string): CreatureEyes {
  return (CREATURE_EYES as readonly string[]).includes(id) ? id as CreatureEyes : "dot";
}

/** The creature a new agent starts with: any figure, any colour world, any eyes. */
export function randomCreature(random: () => number = Math.random): CreatureLook {
  const pick = <T>(list: readonly T[]): T => list[Math.floor(random() * list.length)]!;
  return { seed: Math.floor(random() * (CREATURE_SEED_MAX + 1)), palette: pick(CREATURE_PALETTES).id, eyes: pick(CREATURE_EYES) };
}

/** The one colour a surface that knows no gradient (a chat bubble) uses for this creature. */
export function creatureColor(creature: CreatureLook): string {
  return creaturePalette(creature.palette).colors[1];
}

function textHash(text: string): number {
  let hash = 2166136261;
  for (const character of text) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619) >>> 0;
  return hash;
}

/** The colour world closest to a plain colour, by its nearest stop. */
export function nearestPalette(color: string): string {
  const [r, g, b] = hexRgb(color);
  let best = CREATURE_PALETTES[0]!.id;
  let bestDistance = Infinity;
  for (const entry of CREATURE_PALETTES) for (const stop of entry.rgb) {
    const distance = (stop[0] - r) ** 2 + (stop[1] - g) ** 2 + (stop[2] - b) ** 2;
    if (distance < bestDistance) { bestDistance = distance; best = entry.id; }
  }
  return best;
}

/**
 * The creature an agent gets before anyone chose one: grown from its shape
 * look, so the same look gives the same creature on every surface, in the
 * colour world nearest its own colour.
 */
export function creatureFromShape(look: { shape: string; color: string; eyes: string; accessories?: Record<string, string> }): CreatureLook {
  const worn = Object.entries(look.accessories ?? {}).sort(([a], [b]) => a.localeCompare(b)).map((pair) => pair.join("=")).join(",");
  return {
    seed: textHash(`creature:${look.shape}:${look.color.toLowerCase()}:${look.eyes}:${worn}`) % (CREATURE_SEED_MAX + 1),
    palette: nearestPalette(look.color),
    eyes: look.eyes === "dots" ? "dot" : "tall",
  };
}

/* ---------- Growing the grid from one number ---------- */

export const GRID = 9;
const HALF = 5;
const ROWS = [0, 1, 2, 3, 4, 5, 6, 7, 8] as const;

function mulberry(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Chance of a filled cell, left half only (column 4 is the mirror axis): ornament, body, legs. */
const ODDS: readonly (readonly number[])[] = [
  [0, .22, .3, .18, .3], [.08, .45, .6, .5, .6], [.2, .8, 1, 1, 1], [.55, 1, 1, 1, 1], [.6, 1, 1, 1, 1],
  [.55, 1, 1, 1, 1], [.25, .85, 1, 1, 1], [.15, .6, .7, .45, .6], [.08, .4, .45, .25, .3],
];

/** The filled cells of a seed, rows top to bottom. Ornaments and legs only grow from a filled neighbour. */
export function growCreature(seed: number): boolean[][] {
  const next = mulberry(seed);
  const half = ODDS.map((row) => row.map((odds) => next() < odds));
  for (let r = 2; r <= 6; r++) half[r]![0] = half[r]![0]! && half[r]![1]!;
  for (let c = 0; c < HALF; c++) {
    half[1]![c] = half[1]![c]! && half[2]![c]!;
    half[0]![c] = half[0]![c]! && half[1]![c]!;
    half[7]![c] = half[7]![c]! && half[6]![c]!;
    half[8]![c] = half[8]![c]! && half[7]![c]!;
  }
  return half.map((row) => ROWS.map((c) => row[c < HALF ? c : GRID - 1 - c]!));
}

/** A creature ready to draw: its cells and the colour of each row. */
export interface CreatureBody {
  key: string;
  seed: number;
  palette: CreaturePalette;
  eyes: CreatureEyes;
  cells: boolean[][];
  rows: Rgb[];
  /** First and last row that holds a cell. */
  top: number;
  bottom: number;
}

const BODIES = new Map<string, CreatureBody>();
/** The picker rolls many seeds; the cache forgets them all once it grows past this. */
const BODY_CACHE = 256;

export function creatureBody(look: CreatureLook): CreatureBody {
  const key = `${look.seed}|${look.palette}|${look.eyes}`;
  const cached = BODIES.get(key);
  if (cached) return cached;
  const cells = growCreature(look.seed);
  const pal = creaturePalette(look.palette);
  const rows = ROWS.map((r) => {
    const t = r / (GRID - 1);
    return t < .5 ? mixRgb(pal.rgb[0], pal.rgb[1], t * 2) : mixRgb(pal.rgb[1], pal.rgb[2], (t - .5) * 2);
  });
  const filled = ROWS.filter((r) => cells[r]!.some(Boolean));
  const body: CreatureBody = {
    key, seed: look.seed, palette: pal, eyes: creatureEyes(look.eyes), cells, rows,
    top: filled[0]!, bottom: filled[filled.length - 1]!,
  };
  if (BODIES.size >= BODY_CACHE) BODIES.clear();
  BODIES.set(key, body);
  return body;
}

/* ---------- Poses: what one frame of a state looks like ---------- */

/** One animation frame lasts this long: whole cells at ten frames a second. */
export const CREATURE_TICK_MS = 100;

/**
 * The stage around the 9 x 9 grid, in cells: two spare columns on each side
 * and one spare row above and below, where signs and sparks play. The grid
 * itself starts at (STAGE_X, STAGE_Y).
 */
export const STAGE_W = 13;
export const STAGE_H = 11;
export const STAGE_X = 2;
export const STAGE_Y = 1;

export const SIGN_AMBER: Rgb = [255, 176, 32];
export const SIGN_GREEN: Rgb = [34, 197, 94];
export const SIGN_RED: Rgb = [255, 61, 84];

/** A loose cell beside the body, in grid coordinates: a palette stop or its own colour. */
export interface CreatureBit {
  x: number;
  y: number;
  color: 0 | 1 | 2 | Rgb;
  alpha: number;
}

export interface CreaturePose {
  dx: number;
  dy: number;
  /** Shifts the upper half sideways: a tilted head. */
  head: number;
  /** Drops the upper rows one cell: a landing, or a slow breath. */
  squash: boolean;
  eyes: "open" | "shut" | "wide" | "flat" | "happy";
  ex: number;
  ey: number;
  mouth: 0 | 1 | 2;
  /** 0..1 towards the error red. */
  tint: number;
  /** 0..1 towards a pale, sleeping body. */
  dim: number;
  /** The row a light wave is passing, or -1. */
  sweep: number;
  /** 0..1 strength of the ring around the body. */
  halo: number;
  bits: CreatureBit[];
}

const GLYPHS = {
  question: ["##.", "..#", ".#.", "...", ".#."],
  bang: ["##", "##", "##", "..", "##"],
  check: ["..#", "#.#", ".#."],
  z: ["###", ".#.", "###"],
} as const;

function stamp(bits: CreatureBit[], glyph: keyof typeof GLYPHS, x: number, y: number, color: CreatureBit["color"], alpha = 1): void {
  GLYPHS[glyph].forEach((row, j) => [...row].forEach((mark, i) => { if (mark === "#") bits.push({ x: x + i, y: y + j, color, alpha }); }));
}

const CONFETTI: readonly (readonly [number, number, 0 | 1 | 2])[] = [[-1.2, -.9, 0], [-.6, -1.3, 2], [.5, -1.4, 1], [1.1, -1, 0], [-1.6, -.3, 1], [1.6, -.4, 2]];
const SPARK_PATH: readonly (readonly [number, number, number])[] = [[-1, 8, 1], [-2, 7, 1], [-2, 6, .7], [-2, 5, .4]];

export function creaturePose(state: CreatureState, frame: number): CreaturePose {
  const f = Math.max(0, Math.floor(frame));
  const p: CreaturePose = { dx: 0, dy: 0, head: 0, squash: false, eyes: "open", ex: 0, ey: 0, mouth: 0, tint: 0, dim: 0, sweep: -1, halo: 0, bits: [] };
  switch (state) {
    case "idle": {
      const k = f % 60;
      if (k < 2) p.eyes = "shut"; else if (k >= 26 && k < 32) p.ex = -1; else if (k >= 36 && k < 42) p.ex = 1;
      break;
    }
    case "listening":
      p.eyes = "wide";
      p.halo = [.15, .35, .6, .8, .6, .35][Math.floor(f / 2) % 6]!;
      break;
    case "thinking": {
      p.ey = -1;
      p.ex = Math.floor(f / 14) % 2 ? 1 : -1;
      const wave = f % 16;
      if (wave < GRID) p.sweep = wave;
      // A thought trail beside the head: a dot, a second one, then the bubble.
      const k = Math.floor(f / 4) % 4;
      if (k >= 1) p.bits.push({ x: 9, y: 3, color: 1, alpha: 1 });
      if (k >= 2) p.bits.push({ x: 10, y: 2, color: 1, alpha: 1 });
      if (k >= 3) for (const [x, y] of [[9, -1], [10, -1], [9, 0], [10, 0]]) p.bits.push({ x: x!, y: y!, color: 1, alpha: 1 });
      break;
    }
    case "working": {
      p.dy = [0, 0, -1, -1][f % 4]!;
      p.ey = 1;
      const spark = SPARK_PATH[f % 6];
      if (spark) {
        const [x, y, alpha] = spark;
        p.bits.push({ x, y, color: 0, alpha }, { x: GRID - 1 - x, y, color: 0, alpha });
      }
      break;
    }
    case "talking": {
      p.mouth = ([0, 2, 1, 2, 0, 1, 2, 2, 1, 0, 2, 1] as const)[f % 12]!;
      const height = [1, 3, 2, 3, 1, 2][f % 6]!;
      for (const x of [-2, 10]) for (let i = 0; i < height; i++) p.bits.push({ x, y: 5 - Math.floor(height / 2) + i, color: 1, alpha: 1 });
      break;
    }
    case "asking":
      // Away from the sign, so the question mark never touches the head.
      p.head = -(Math.floor(f / 12) % 2);
      if (f % 10 < 8) stamp(p.bits, "question", 8, -1, SIGN_AMBER);
      break;
    case "success": {
      const k = f % 26;
      if (k < 6) p.dy = [0, -1, -1, -1, -1, 0][k]!;
      p.squash = k === 6 || k === 7;
      p.eyes = "happy";
      if (k >= 2) stamp(p.bits, "check", 8, -1, SIGN_GREEN);
      if (k >= 2 && k < 12) {
        const t = k - 2;
        for (const [vx, vy, color] of CONFETTI) {
          const x = Math.round(4 + vx * t), y = Math.round(1 + vy * t + .13 * t * t);
          if (x >= -STAGE_X && x < STAGE_W - STAGE_X && y >= -STAGE_Y && y < STAGE_H - STAGE_Y) p.bits.push({ x, y, color, alpha: 1 - t / 11 });
        }
      }
      break;
    }
    case "error": {
      const k = f % 22;
      if (k < 6) { p.dx = k % 2 ? -1 : 1; p.tint = .6; } else p.tint = .18;
      p.eyes = "flat";
      if (f % 6 < 4) stamp(p.bits, "bang", 9, -1, SIGN_RED);
      break;
    }
    case "sleeping": {
      p.dim = .55;
      p.eyes = "shut";
      p.squash = Math.floor(f / 16) % 2 === 1;
      const g = Math.floor(f / 5) % 8;
      if (g === 1 || g === 2) stamp(p.bits, "z", 8, 0, 1, g === 1 ? .6 : 1);
      if (g === 3 || g === 4) stamp(p.bits, "z", 8, -1, 1, g === 3 ? 1 : .45);
      break;
    }
  }
  return p;
}

/** One representative frame per state, for people who asked for less motion. */
export const CREATURE_STILL_FRAME: Readonly<Record<CreatureState, number>> = {
  idle: 5, listening: 6, thinking: 12, working: 1, talking: 1, asking: 0, success: 8, error: 7, sleeping: 10,
};

/** Eye cells per kind as [row, column]; the lower row is the one a lid closes. */
const EYE_CELLS: Readonly<Record<CreatureEyes, readonly (readonly [number, number])[]>> = {
  dot: [[4, 3], [4, 5]],
  tall: [[3, 3], [4, 3], [3, 5], [4, 5]],
  wide: [[4, 2], [4, 6]],
  visor: [[4, 2], [4, 3], [4, 4], [4, 5], [4, 6]],
};

type Cell = readonly [number, number];

function face(kind: CreatureEyes, p: CreaturePose): { ink: Cell[]; lid: Cell[] } {
  const base = EYE_CELLS[kind];
  const low = base.filter(([r]) => r === 4);
  let ink: Cell[] = [];
  let lid: Cell[] = [];
  if (p.eyes === "shut") lid = low;
  else if (p.eyes === "wide") ink = [...base, ...base.map(([r, c]) => [r - 1, c] as const)];
  else if (p.eyes === "flat") ink = kind === "visor" ? [...base] : low.flatMap(([r, c]) => [[r, c], [r, c < 4 ? c - 1 : c + 1]] as const);
  else if (p.eyes === "happy") ink = [...low.map(([, c]) => [3, c] as const), [5, 3], [6, 4], [5, 5]];
  else ink = base.map(([r, c]) => [r + p.ey, c + p.ex] as const);
  if (p.mouth === 1) ink.push([6, 4]);
  if (p.mouth === 2) ink.push([6, 3], [6, 4], [6, 5]);
  return { ink, lid };
}

/** A body cell after the pose moved it. `front` marks the cells the face paints. */
export interface PosedCell {
  x: number;
  y: number;
  /** The grid row it came from, which sets its colour. */
  row: number;
  front: "ink" | "lid" | null;
}

export function composeCreature(body: CreatureBody, p: CreaturePose): Map<string, PosedCell> {
  const map = new Map<string, PosedCell>();
  const X = (r: number, c: number) => c + p.dx + (r <= 4 ? p.head : 0);
  const Y = (r: number) => r + p.dy + (p.squash && r <= 3 ? 1 : 0);
  for (let r = 0; r < GRID; r++) for (let c = 0; c < GRID; c++) {
    if (!body.cells[r]![c]) continue;
    const x = X(r, c), y = Y(r);
    map.set(`${x},${y}`, { x, y, row: r, front: null });
  }
  const drawn = face(body.eyes, p);
  for (const [kind, list] of [["lid", drawn.lid], ["ink", drawn.ink]] as const) for (const [r, c] of list) {
    const cell = map.get(`${X(r, c)},${Y(r)}`);
    if (cell) cell.front = kind;
  }
  return map;
}

/** The empty cells that touch the body: where the listening ring lights up. */
export function creatureRim(cells: Map<string, PosedCell>): Cell[] {
  const out = new Map<string, Cell>();
  for (const cell of cells.values()) for (const [dx, dy] of [[0, -1], [0, 1], [-1, 0], [1, 0]] as const) {
    const key = `${cell.x + dx},${cell.y + dy}`;
    if (!cells.has(key)) out.set(key, [cell.x + dx, cell.y + dy]);
  }
  return [...out.values()];
}

const WHITE: Rgb = [255, 255, 255];
const BLACK: Rgb = [0, 0, 0];
const SLEEP: Rgb = [44, 44, 62];

export function creatureRowColor(body: CreatureBody, row: number, p: CreaturePose): Rgb {
  let color = body.rows[row]!;
  if (p.sweep >= 0) {
    const distance = Math.abs(row - p.sweep);
    if (distance < 2) color = mixRgb(color, WHITE, distance === 0 ? .55 : .22);
  }
  if (p.tint) color = mixRgb(color, SIGN_RED, p.tint);
  if (p.dim) {
    const grey = color[0] * .3 + color[1] * .59 + color[2] * .11;
    color = mixRgb(mixRgb(color, [grey, grey, grey], p.dim * .7), SLEEP, p.dim * .45);
  }
  return color;
}

/** One cube of a creature, in cells: x to the right, y down from the top row, z towards the viewer. */
export interface CreatureCube {
  x: number;
  y: number;
  z: number;
  color: Rgb;
  alpha: number;
}

/** How many cubes a creature reaches to the front and to the back of its middle layer. */
export const CREATURE_DEPTH = 1;

/**
 * The cubes of one pose: every cell is a column three cubes deep, so the
 * figure is a solid block with a flat front, and the face on that front
 * reads as clearly as on a flat sprite.
 */
export function creatureCubes(body: CreatureBody, p: CreaturePose): CreatureCube[] {
  const cells = composeCreature(body, p);
  const cubes: CreatureCube[] = [];
  for (const cell of cells.values()) {
    const color = creatureRowColor(body, cell.row, p);
    for (let z = -CREATURE_DEPTH; z <= CREATURE_DEPTH; z++) {
      const front = z === CREATURE_DEPTH ? cell.front : null;
      cubes.push({ x: cell.x, y: cell.y, z, alpha: 1, color: front === "ink" ? body.palette.ink : front === "lid" ? mixRgb(color, BLACK, .4) : color });
    }
  }
  if (p.halo) {
    const ring = mixRgb(body.palette.rgb[0], WHITE, .55);
    for (const [x, y] of creatureRim(cells)) cubes.push({ x, y, z: 0, color: ring, alpha: p.halo * .6 });
  }
  return cubes;
}

export function creatureBitColor(body: CreatureBody, bit: CreatureBit): Rgb {
  return typeof bit.color === "number" ? body.palette.rgb[bit.color] : bit.color;
}
