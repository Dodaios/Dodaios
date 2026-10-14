/**
 * The agents floor's built fittings: what encloses and furnishes a team
 * studio (low felt-and-glass screens, a storage cabinet, a sofa, a standing
 * table) and what furnishes the commons (the atrium's step seating, the
 * café's kitchen run and island, focus booths, large trees).
 *
 * Every piece is assembled from a handful of shapes, and every shape of one
 * material is one instanced mesh for the whole floor: a campus of twelve
 * furnished studios costs the same sixteen draw calls as an empty one. Each
 * piece is built inside the box the plan (`layout.ambience`) gives it, which
 * is also what navigation walks round; a studio's pieces wear its colour.
 */
import { useMemo } from "react";
import { MeshStandardMaterial } from "three";
import {
  BOOTH, CABINET, COUNTER, CRATE, HIGH_TABLE, ISLAND, SCREEN, SOFA, STEPS, ownSize, stepsSeats, yawOf, type AgentsAmbienceItem,
} from "./agentsAmbience";
import { agentsRug, AGENTS_RUGS } from "./AgentsFloorLook";
import { Instances, type Placement } from "./CodingFloorAmbience";
import { GEO, MAT, matte } from "./OfficeFurniture";

const FIT = {
  oak: matte("#d9bf97", { roughness: 0.6 }),
  oakDark: matte("#b89b74", { roughness: 0.65 }),
  /** White, so each instance's colour is its felt, fabric or paint. */
  tint: matte("#ffffff", { roughness: 0.95 }),
  steel: matte("#23262b", { roughness: 0.45, metalness: 0.4 }),
  stone: matte("#e4ddd1", { roughness: 0.6 }),
  bark: matte("#6f5d4b", { roughness: 0.9 }),
  glass: new MeshStandardMaterial({ color: "#d6ecff", transparent: true, opacity: 0.28, roughness: 0.08, depthWrite: false }),
  glow: new MeshStandardMaterial({ color: "#fff0d8", emissive: "#fff0d8", emissiveIntensity: 1.5, toneMapped: false }),
};

/** Neutral tones for pieces that belong to no team, and the small things that stand on them. */
const NEUTRAL = { felt: "#cfc7ba", fabric: "#d6cfc2", paint: "#f3f1ec", linen: "#e9e1d2", sage: "#9fb094", ceramic: "#f2ece2" } as const;
const ACCENTS = ["#c07f63", "#8fa383", "#d2a650", "#7f93a8", "#d9c9ab"] as const;

function lcg(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x1_0000_0000;
  };
}

function seedOf(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i += 1) h = Math.imul(h ^ id.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** The shapes of the whole floor, sorted by the instanced mesh that draws them. */
interface Parts {
  oak: Placement[]; oakDark: Placement[]; tint: Placement[]; steel: Placement[]; stone: Placement[]; glass: Placement[]; glow: Placement[];
  roundOak: Placement[]; roundSteel: Placement[]; roundTint: Placement[]; roundStone: Placement[]; pot: Placement[]; bark: Placement[];
  leaf: Placement[]; leafDark: Placement[]; leafLight: Placement[];
}

/**
 * Places a shape given in a piece's own frame (x along its front, z towards
 * its front, origin on the floor under its middle) into the world.
 */
function frameOf(item: AgentsAmbienceItem) {
  const yaw = yawOf(item.facing), cos = Math.cos(yaw), sin = Math.sin(yaw);
  const cx = (item.minX + item.maxX) / 2, cz = (item.minZ + item.maxZ) / 2;
  return (lx: number, y: number, lz: number, sx: number, sy: number, sz: number, color?: string): Placement => ({
    position: [cx + lx * cos + lz * sin, y, cz - lx * sin + lz * cos], scale: [sx, sy, sz], rotation: [0, yaw, 0], ...(color ? { color } : {}),
  });
}

const feltOf = (item: AgentsAmbienceItem) => (item.tint === undefined ? NEUTRAL.felt : agentsRug(item.tint).felt);
const accentOf = (item: AgentsAmbienceItem) => (item.tint === undefined ? "#8e8a84" : agentsRug(item.tint).border);

/** A low screen: a felt panel in the studio's colour on a steel shoe, a band of glass above it and a slim steel cap. */
function buildScreen(item: AgentsAmbienceItem, p: Parts): void {
  const dx = item.maxX - item.minX, dz = item.maxZ - item.minZ, alongX = dx > dz;
  const cx = (item.minX + item.maxX) / 2, cz = (item.minZ + item.maxZ) / 2;
  const felt = 0.92, glass = SCREEN.h - felt - 0.09;
  p.steel.push({ position: [cx, 0.03, cz], scale: [dx + (alongX ? 0 : 0.02), 0.06, dz + (alongX ? 0.02 : 0)] });
  p.tint.push({ position: [cx, 0.06 + felt / 2, cz], scale: [dx, felt, dz], color: feltOf(item) });
  p.glass.push({ position: [cx, 0.06 + felt + glass / 2, cz], scale: alongX ? [dx, glass, 0.02] : [0.02, glass, dz] });
  p.steel.push({ position: [cx, SCREEN.h - 0.015, cz], scale: alongX ? [dx, 0.03, 0.05] : [0.05, 0.03, dz] });
}

/** A storage cabinet: white fronts on a recessed plinth under an oak top, a line in the studio's colour, books and a plant on it. */
function buildCabinet(item: AgentsAmbienceItem, p: Parts): void {
  const at = frameOf(item), { w, d } = CABINET;
  p.oakDark.push(at(0, 0.03, 0, w - 0.06, 0.06, d - 0.06));
  p.tint.push(at(0, 0.46, 0, w, 0.8, d - 0.02, NEUTRAL.paint));
  p.oak.push(at(0, 0.8775, 0, w + 0.02, 0.035, d + 0.02));
  p.tint.push(at(0, 0.78, d / 2 - 0.004, w - 0.1, 0.05, 0.012, accentOf(item)));
  p.tint.push(at(-0.45, 0.92, 0, 0.3, 0.05, 0.22, ACCENTS[0]));
  p.tint.push(at(-0.43, 0.97, 0, 0.26, 0.05, 0.2, ACCENTS[4]));
  p.roundTint.push(at(0.5, 0.965, 0, 0.09, 0.14, 0.09, NEUTRAL.ceramic));
  p.leafLight.push(at(0.5, 1.13, 0, 0.16, 0.14, 0.16));
}

/** A two-seat sofa on a recessed plinth: a deep base, two seat cushions, a back and two arms, in the studio's felt. */
function buildSofa(item: AgentsAmbienceItem, p: Parts): void {
  const at = frameOf(item), { w, d } = SOFA;
  const fabric = item.tint === undefined ? NEUTRAL.fabric : agentsRug(item.tint).felt;
  p.oakDark.push(at(0, 0.06, 0, w - 0.12, 0.12, d - 0.14));
  p.tint.push(at(0, 0.22, 0, w, 0.2, d, fabric));
  for (const lx of [-0.44, 0.44]) p.tint.push(at(lx, 0.39, 0.08, w / 2 - 0.2, 0.14, d - 0.3, fabric));
  p.tint.push(at(0, 0.57, -d / 2 + 0.11, w - 0.28, 0.42, 0.2, fabric));
  for (const lx of [-(w / 2 - 0.07), w / 2 - 0.07]) p.tint.push(at(lx, 0.44, 0, 0.14, 0.32, d - 0.02, fabric));
  p.tint.push(at(0.62, 0.58, -0.12, 0.32, 0.26, 0.1, ACCENTS[seedOf(item.id) % ACCENTS.length]));
}

/** A round standing table: an oak top on a steel stem, a cup left on it. */
function buildHighTable(item: AgentsAmbienceItem, p: Parts): void {
  const x = (item.minX + item.maxX) / 2, z = (item.minZ + item.maxZ) / 2, { r, h } = HIGH_TABLE;
  p.roundSteel.push({ position: [x, 0.015, z], scale: [0.24, 0.03, 0.24] });
  p.roundSteel.push({ position: [x, (h - 0.04) / 2, z], scale: [0.03, h - 0.04, 0.03] });
  p.roundOak.push({ position: [x, h - 0.02, z], scale: [r, 0.04, r] });
  p.roundTint.push({ position: [x + 0.14, h + 0.045, z - 0.06], scale: [0.04, 0.09, 0.04], color: NEUTRAL.ceramic });
}

/** A focus booth: oak walls and roof round a felt back panel with a shelf and a light, a glass sidelight beside the doorway. */
function buildBooth(item: AgentsAmbienceItem, p: Parts): void {
  const at = frameOf(item), { w, d, h, wall } = BOOTH;
  const wallH = h - 0.04, wallY = 0.04 + wallH / 2;
  p.oakDark.push(at(0, 0.02, 0, w, 0.04, d));
  p.oak.push(at(0, wallY, -d / 2 + wall / 2, w, wallH, wall));
  for (const lx of [-(w / 2 - wall / 2), w / 2 - wall / 2]) p.oak.push(at(lx, wallY, wall / 2, wall, wallH, d - wall));
  p.oak.push(at(0, h - 0.04, 0, w, 0.08, d));
  p.tint.push(at(0, 1.35, -d / 2 + wall + 0.01, w - 0.2, 1.3, 0.02, feltOf(item)));
  p.oak.push(at(0, 1.02, -d / 2 + wall + 0.15, w - 0.24, 0.035, 0.3));
  p.glow.push(at(0, h - 0.1, 0, w - 0.3, 0.02, 0.05));
  p.glass.push(at(-(w / 2 - wall - 0.15), 0.04 + (h - 0.3) / 2, d / 2 - 0.02, 0.3, h - 0.3, 0.02));
}

/**
 * Step seating, the atrium's own furniture. Each tier is a dark riser under a pale timber tread that noses out
 * over it. The lowest tier is plainly a seat: a linen pad per place and a back cushion against the next riser.
 * Higher up lie loose cushions in the studios' colours, as if the teams had left them there.
 */
function buildSteps(item: AgentsAmbienceItem, p: Parts): void {
  const at = frameOf(item), { w, d } = ownSize(item);
  const tread = 0.05, nose = 0.035;
  for (let k = 0; k < STEPS.tiers; k += 1) {
    const top = STEPS.rise * (k + 1), front = d / 2 - STEPS.tier * k;
    // The riser: the tier's body, set back a little under the tread and darker, so every step casts a line.
    p.oakDark.push(at(0, (top - tread) / 2, front - STEPS.tier / 2 - 0.01, w - 0.04, top - tread, STEPS.tier - 0.02));
    p.oak.push(at(0, top - tread / 2, front - STEPS.tier / 2 + nose / 2, w, tread, STEPS.tier + nose));
  }
  // Steel cheeks close both ends.
  for (const lx of [-w / 2 + 0.012, w / 2 - 0.012]) p.steel.push(at(lx, STEPS.rise / 2, d / 2 - STEPS.tier / 2, 0.024, STEPS.rise, STEPS.tier));
  const seats = stepsSeats(item).length, seatZ = d / 2 - STEPS.tier / 2;
  for (let i = 0; i < seats; i += 1) {
    const lx = (i - (seats - 1) / 2) * 0.9;
    // A thin pad: a seated figure's height is the tread's.
    p.tint.push(at(lx, STEPS.rise + 0.0125, seatZ + 0.06, 0.74, 0.025, 0.58, NEUTRAL.linen));
    p.tint.push(at(lx, STEPS.rise + 0.2, seatZ - STEPS.tier / 2 + 0.07, 0.7, 0.3, 0.1, NEUTRAL.fabric));
  }
  const rand = lcg(seedOf(item.id));
  const count = Math.max(3, Math.round(w / 1.3));
  for (let i = 0; i < count; i += 1) {
    const tier = 1 + (i % 2), top = STEPS.rise * (tier + 1);
    const lx = -w / 2 + 0.5 + ((w - 1) * (i + rand() * 0.6)) / count;
    p.tint.push(at(lx, top + 0.05, d / 2 - STEPS.tier * tier - STEPS.tier / 2 + (rand() - 0.5) * 0.2, 0.44, 0.1, 0.44,
      AGENTS_RUGS[Math.floor(rand() * AGENTS_RUGS.length)].border));
  }
}

/** Two moving crates, one on the other and a little askew, with dark handles and a label. */
function buildCrate(item: AgentsAmbienceItem, p: Parts): void {
  const at = frameOf(item), { w, d, h } = CRATE;
  const half = h / 2 - 0.01;
  p.oak.push(at(0, half / 2, 0, w, half, d));
  p.oak.push(at(0.06, half + 0.01 + half / 2, -0.03, w - 0.14, half, d - 0.08));
  for (const y of [half / 2, half + 0.01 + half / 2]) p.oakDark.push(at(y < half ? 0 : 0.06, y, d / 2 - 0.02 - (y < half ? 0 : 0.07), 0.24, 0.05, 0.012));
  p.tint.push(at(-0.2, half * 0.55, d / 2 + 0.002, 0.2, 0.13, 0.006, NEUTRAL.paint));
}

/** The café's kitchen run: white base units under a stone top, an oak back wall with two shelves of cups and jars, a coffee machine. */
function buildCounter(item: AgentsAmbienceItem, p: Parts): void {
  const at = frameOf(item), { w, d } = ownSize(item);
  const top = 0.92, back = -d / 2 + 0.025, shelfZ = -d / 2 + 0.18;
  p.oakDark.push(at(0, 0.04, 0.02, w, 0.08, d - 0.12));
  p.tint.push(at(0, 0.48, 0, w, 0.8, d - 0.04, NEUTRAL.paint));
  p.stone.push(at(0, 0.9, 0, w + 0.02, 0.04, d + 0.02));
  p.oak.push(at(0, top + (COUNTER.h - top) / 2, back, w, COUNTER.h - top, 0.05));
  for (const y of [1.42, 1.78]) p.oak.push(at(0, y, shelfZ, w - 0.3, 0.035, 0.26));
  p.glow.push(at(0, 1.75, shelfZ + 0.1, w - 0.4, 0.015, 0.03));
  p.steel.push(at(-w / 4, top + 0.23, -0.05, 0.5, 0.46, 0.42));
  for (let i = 0; i < 6; i += 1) p.roundTint.push(at(0.2 + i * 0.17, 1.42 + 0.0175 + 0.045, shelfZ, 0.04, 0.09, 0.04, NEUTRAL.ceramic));
  for (let i = 0; i < 5; i += 1) p.roundTint.push(at(-w / 2 + 0.5 + i * 0.26, 1.78 + 0.0175 + 0.08, shelfZ, 0.06, 0.16, 0.06, ACCENTS[i % ACCENTS.length]));
}

/** The café's island: a sage base under an oak top that overhangs it, a bowl and a plant on it. */
function buildIsland(item: AgentsAmbienceItem, p: Parts): void {
  const at = frameOf(item), { w, d, h } = ISLAND;
  p.tint.push(at(0, (h - 0.05) / 2, 0, w - 0.3, h - 0.05, d - 0.24, NEUTRAL.sage));
  p.oak.push(at(0, h - 0.025, 0, w, 0.05, d));
  p.roundTint.push(at(-0.7, h + 0.03, 0, 0.17, 0.06, 0.17, NEUTRAL.ceramic));
  p.roundTint.push(at(0.75, h + 0.07, 0.05, 0.08, 0.14, 0.08, ACCENTS[0]));
  p.leaf.push(at(0.75, h + 0.24, 0.05, 0.17, 0.15, 0.17));
}

/** A large tree: a round stone planter, a tall trunk with two boughs and a full crown that spreads above head height. */
function buildTree(item: AgentsAmbienceItem, p: Parts): void {
  const x = (item.minX + item.maxX) / 2, z = (item.minZ + item.maxZ) / 2, r = (item.maxX - item.minX) / 2;
  const rand = lcg(seedOf(item.id));
  p.pot.push({ position: [x, 0.35, z], scale: [r - 0.05, 0.7, r - 0.05] });
  p.roundStone.push({ position: [x, 0.72, z], scale: [r - 0.02, 0.05, r - 0.02] });
  p.bark.push({ position: [x, 1.85, z], scale: [0.09, 2.2, 0.09], rotation: [(rand() - 0.5) * 0.08, 0, (rand() - 0.5) * 0.08] });
  p.bark.push({ position: [x - 0.3, 2.9, z + 0.1], scale: [0.05, 1.0, 0.05], rotation: [0.15, 0, 0.55] });
  p.bark.push({ position: [x + 0.32, 3.0, z - 0.12], scale: [0.045, 1.1, 0.045], rotation: [-0.18, 0, -0.5] });
  const crowns = [p.leaf, p.leafDark, p.leafLight];
  // A crown of a few large clusters reads as one tree; many small ones only cost triangles.
  for (let k = 0; k < 14; k += 1) {
    const a = (k / 14) * Math.PI * 2 + rand() * 0.5, ring = 0.2 + rand() * 1.0;
    const y = 3.45 + (rand() - 0.5) * 0.8 - ring * 0.35;
    const s = 0.46 + rand() * 0.26;
    crowns[Math.floor(rand() * 2.4)].push({ position: [x + Math.cos(a) * ring, y, z + Math.sin(a) * ring], scale: [s * 1.25, s * 0.85, s * 1.25] });
  }
}

const BUILDERS: Partial<Record<AgentsAmbienceItem["kind"], (item: AgentsAmbienceItem, parts: Parts) => void>> = {
  screen: buildScreen, cabinet: buildCabinet, sofa: buildSofa, hightable: buildHighTable,
  booth: buildBooth, steps: buildSteps, counter: buildCounter, island: buildIsland, tree: buildTree, crate: buildCrate,
};

/** Every built fitting of the floor, drawn by sixteen instanced meshes. */
export function CampusFittings({ items }: { items: readonly AgentsAmbienceItem[] }) {
  const p = useMemo(() => {
    const parts: Parts = {
      oak: [], oakDark: [], tint: [], steel: [], stone: [], glass: [], glow: [],
      roundOak: [], roundSteel: [], roundTint: [], roundStone: [], pot: [], bark: [], leaf: [], leafDark: [], leafLight: [],
    };
    for (const item of items) BUILDERS[item.kind]?.(item, parts);
    return parts;
  }, [items]);
  return (
    <group>
      <Instances geometry={GEO.box} material={FIT.oak} items={p.oak} />
      <Instances geometry={GEO.box} material={FIT.oakDark} items={p.oakDark} cast={false} />
      <Instances geometry={GEO.box} material={FIT.tint} items={p.tint} />
      <Instances geometry={GEO.box} material={FIT.steel} items={p.steel} />
      <Instances geometry={GEO.box} material={FIT.stone} items={p.stone} />
      <Instances geometry={GEO.box} material={FIT.glass} items={p.glass} cast={false} />
      <Instances geometry={GEO.box} material={FIT.glow} items={p.glow} cast={false} />
      <Instances geometry={GEO.cyl} material={FIT.oak} items={p.roundOak} />
      <Instances geometry={GEO.cyl} material={FIT.steel} items={p.roundSteel} />
      <Instances geometry={GEO.cyl} material={FIT.tint} items={p.roundTint} cast={false} />
      <Instances geometry={GEO.cyl} material={FIT.stone} items={p.roundStone} />
      <Instances geometry={GEO.potCyl} material={FIT.stone} items={p.pot} />
      <Instances geometry={GEO.cyl} material={FIT.bark} items={p.bark} />
      <Instances geometry={GEO.blob} material={MAT.leaf} items={p.leaf} />
      <Instances geometry={GEO.blob} material={MAT.leafDark} items={p.leafDark} />
      {/* Two of a crown's three tones throw its shadow. */}
      <Instances geometry={GEO.blob} material={MAT.leafLight} items={p.leafLight} cast={false} />
    </group>
  );
}
