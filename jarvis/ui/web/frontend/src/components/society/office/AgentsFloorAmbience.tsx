/**
 * The agents floor's planting, fittings and light: olive trees in pale stone
 * pots at the end of every street and in a few deliberate groups, cushioned
 * oak benches, slatted oak planters of grasses (every studio's planted front
 * among them), the built fittings of studios and commons (`CampusFittings`),
 * a slim linear pendant light over every desk row with a soft pool of light
 * below, and one warm fill light for the whole floor.
 *
 * Every repeated part is one instanced mesh, so the whole dressing costs a
 * few dozen draw calls however large the campus grows. The solid pieces are
 * the plan's `ambience` items, which the layout also adds to its obstacles;
 * the pendants and light pools are out of reach (a metre over every head, or
 * flat on the floor), and nothing overhead is wide enough to hide a desk.
 */
import { useMemo } from "react";
import { AdditiveBlending, MeshBasicMaterial, MeshStandardMaterial, PlaneGeometry } from "three";
import { cachedCanvasTexture } from "./canvasMaterials";
import { BENCH_H, PLANTER_H, type AgentsAmbienceItem } from "./agentsAmbience";
import { FACADE } from "./BuildingShell";
import { AGENTS_SCENE } from "./AgentsFloorLook";
import { CampusFittings } from "./CampusFittings";
import { benchesOf, Instances, type Placement } from "./CodingFloorAmbience";
import { GEO, MAT, matte } from "./OfficeFurniture";
import type { Department, OfficeLayout } from "./officeLayout";

// ---------------------------------------------------------------------------
// Materials
// ---------------------------------------------------------------------------

const AMB = {
  stone: matte("#e4ddd1", { roughness: 0.8 }),
  stoneDark: matte("#cfc6b8", { roughness: 0.85 }),
  gravel: matte("#b9b0a3", { roughness: 1 }),
  bark: matte("#7a6a58", { roughness: 0.9 }),
  oak: matte("#d9bf97", { roughness: 0.6 }),
  oakDark: matte("#b89b74", { roughness: 0.65 }),
  linen: matte("#efe7d8", { roughness: 1 }),
  /** White, so each instance's colour is the fabric's or the felt's colour. */
  fabric: matte("#ffffff", { roughness: 1 }),
  plume: matte("#e9dcc0", { roughness: 1 }),
  stalk: matte("#b7a582", { roughness: 1 }),
};

/** Olive leaves: silvery sage greens, lighter than the office's other plants. */
const OLIVE_LEAVES = [
  matte("#8c9c6e", { flatShading: true }), matte("#9fae82", { flatShading: true }),
  matte("#77885d", { flatShading: true }), matte("#b0b995", { flatShading: true }),
];
/** Grasses in the planters: deeper greens, the office's own leaf tones. */
const GRASS = [MAT.leaf, MAT.leafDark, MAT.leafLight, OLIVE_LEAVES[0]];
/** Throw pillows on the benches: clay, sage, mustard, dusty blue and oat. */
const PILLOWS = ["#c07f63", "#8fa383", "#d2a650", "#7f93a8", "#d9c9ab"];

/** Deterministic pseudo-random numbers per seed, so the dressing never changes between loads. */
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

// ---------------------------------------------------------------------------
// Olive trees
// ---------------------------------------------------------------------------

/** An olive in a round stone pot: a leaning, forked trunk and an airy crown of small silvery clusters. */
function Olives({ items }: { items: readonly AgentsAmbienceItem[] }) {
  const parts = useMemo(() => {
    const pot: Placement[] = [], lip: Placement[] = [], gravel: Placement[] = [], trunk: Placement[] = [];
    const leaves: Placement[][] = OLIVE_LEAVES.map(() => []);
    for (const item of items) {
      const x = (item.minX + item.maxX) / 2, z = (item.minZ + item.maxZ) / 2, r = (item.maxX - item.minX) / 2;
      const rand = lcg(seedOf(item.id));
      pot.push({ position: [x, 0.3, z], scale: [r - 0.03, 0.6, r - 0.03] });
      lip.push({ position: [x, 0.61, z], scale: [r, 0.04, r] });
      // The gravel tops out 5 mm above the lip (0.63): flush tops fought in flickering bands up close.
      gravel.push({ position: [x, 0.63, z], scale: [r - 0.07, 0.01, r - 0.07] });
      // Two leaning stems that fork from a short trunk.
      const lean = (rand() - 0.5) * 0.3;
      trunk.push({ position: [x, 0.85, z], scale: [0.055, 0.5, 0.055], rotation: [lean * 0.5, 0, 0.06] });
      trunk.push({ position: [x - 0.08, 1.35, z + 0.02], scale: [0.035, 0.62, 0.035], rotation: [0.1, 0, 0.28] });
      trunk.push({ position: [x + 0.09, 1.4, z - 0.03], scale: [0.032, 0.66, 0.032], rotation: [-0.12, 0, -0.26] });
      // The crown: an open dome of small clusters, so the trunk shows through.
      for (let k = 0; k < 11; k += 1) {
        const a = (k / 11) * Math.PI * 2 + rand() * 0.6, ring = 0.15 + rand() * 0.42;
        const y = 1.55 + rand() * 0.7 - ring * 0.35;
        const s = 0.15 + rand() * 0.1;
        leaves[Math.floor(rand() * leaves.length)].push({
          position: [x + Math.cos(a) * ring, y, z + Math.sin(a) * ring], scale: [s * 1.3, s * 0.8, s * 1.3],
        });
      }
    }
    return { pot, lip, gravel, trunk, leaves };
  }, [items]);
  return (
    <group>
      <Instances geometry={GEO.potCyl} material={AMB.stone} items={parts.pot} />
      <Instances geometry={GEO.cyl} material={AMB.stoneDark} items={parts.lip} cast={false} />
      <Instances geometry={GEO.cyl} material={AMB.gravel} items={parts.gravel} cast={false} />
      <Instances geometry={GEO.cyl} material={AMB.bark} items={parts.trunk} />
      {/* Flat-shaded clusters: twenty faces each read the same as eighty. */}
      {/* Two of a crown's three tones throw its shadow; the third would only draw it again. */}
      {parts.leaves.map((list, i) => <Instances key={i} geometry={GEO.facet} material={OLIVE_LEAVES[i]} items={list} cast={i < 2} />)}
    </group>
  );
}

// ---------------------------------------------------------------------------
// Window benches
// ---------------------------------------------------------------------------

/**
 * A long oak bench against the glass: a recessed plinth, an oak seat box, a
 * linen seat cushion, back cushions leaning on the glass side, a few throw
 * pillows and now and then a book left behind.
 */
function Benches({ items }: { items: readonly AgentsAmbienceItem[] }) {
  const parts = useMemo(() => {
    const plinth: Placement[] = [], box: Placement[] = [], cushion: Placement[] = [], fabric: Placement[] = [];
    for (const item of items) {
      const rand = lcg(seedOf(item.id));
      const depth = item.maxX - item.minX, len = item.maxZ - item.minZ;
      const cx = (item.minX + item.maxX) / 2, cz = (item.minZ + item.maxZ) / 2;
      // The glass side: -1 (west) when the bench faces east, +1 when it faces west.
      const out = item.facing === "east" ? -1 : 1;
      const seatTop = BENCH_H - 0.1;
      plinth.push({ position: [cx + out * 0.03, 0.04, cz], scale: [depth - 0.1, 0.08, len - 0.1] });
      box.push({ position: [cx, 0.08 + (seatTop - 0.08) / 2, cz], scale: [depth, seatTop - 0.08, len] });
      cushion.push({ position: [cx - out * 0.02, seatTop + 0.05, cz], scale: [depth - 0.06, 0.1, len - 0.06] });
      // Back cushions, one per ~0.8 m, leaning back onto the glass.
      const backs = Math.max(1, Math.round(len / 0.8));
      const bw = (len - 0.1) / backs;
      for (let b = 0; b < backs; b += 1) {
        cushion.push({
          position: [cx + out * (depth / 2 - 0.07), seatTop + 0.3, item.minZ + 0.05 + bw * (b + 0.5)],
          scale: [0.1, 0.38, bw - 0.03], rotation: [0, 0, -out * 0.16],
        });
      }
      // Two or three throw pillows in front of the back cushions.
      const pillows = 2 + Math.floor(rand() * 2);
      for (let p = 0; p < pillows; p += 1) {
        const pz = item.minZ + 0.3 + rand() * (len - 0.6);
        fabric.push({
          position: [cx + out * (depth / 2 - 0.16), seatTop + 0.24, pz], scale: [0.1, 0.3, 0.32],
          rotation: [(rand() - 0.5) * 0.3, 0, -out * 0.3], color: PILLOWS[Math.floor(rand() * PILLOWS.length)],
        });
      }
      if (rand() < 0.5) {
        fabric.push({
          position: [cx - out * 0.06, seatTop + 0.115, item.minZ + len * (0.2 + rand() * 0.6)], scale: [0.16, 0.03, 0.22],
          rotation: [0, rand() * 0.8, 0], color: PILLOWS[Math.floor(rand() * PILLOWS.length)],
        });
      }
    }
    return { plinth, box, cushion, fabric };
  }, [items]);
  return (
    <group>
      <Instances geometry={GEO.box} material={AMB.oakDark} items={parts.plinth} cast={false} />
      <Instances geometry={GEO.box} material={AMB.oak} items={parts.box} />
      <Instances geometry={GEO.box} material={AMB.linen} items={parts.cushion} cast={false} />
      <Instances geometry={GEO.box} material={AMB.fabric} items={parts.fabric} cast={false} />
    </group>
  );
}

// ---------------------------------------------------------------------------
// Slatted planters
// ---------------------------------------------------------------------------

/** Long oak planters wrapped in vertical slats, planted with tall grasses and a few pale feather-grass plumes. */
function Planters({ items }: { items: readonly AgentsAmbienceItem[] }) {
  const parts = useMemo(() => {
    const liner: Placement[] = [], slats: Placement[] = [], cap: Placement[] = [], soil: Placement[] = [], plumes: Placement[] = [], stalks: Placement[] = [];
    const grass: Placement[][] = GRASS.map(() => []);
    const mounds: Placement[][] = GRASS.map(() => []);
    for (const item of items) {
      const rand = lcg(seedOf(item.id));
      const depth = item.maxX - item.minX, len = item.maxZ - item.minZ;
      const cx = (item.minX + item.maxX) / 2, cz = (item.minZ + item.maxZ) / 2;
      const bodyH = PLANTER_H - 0.03;
      liner.push({ position: [cx, bodyH / 2, cz], scale: [depth - 0.03, bodyH, len - 0.03] });
      // Slats every 7 cm down both long faces, and across both ends.
      for (let z = item.minZ + 0.035; z < item.maxZ - 0.02; z += 0.07) {
        for (const x of [item.minX + 0.012, item.maxX - 0.012]) slats.push({ position: [x, bodyH / 2, z], scale: [0.024, bodyH, 0.045] });
      }
      for (let x = item.minX + 0.05; x < item.maxX - 0.03; x += 0.07) {
        for (const z of [item.minZ + 0.012, item.maxZ - 0.012]) slats.push({ position: [x, bodyH / 2, z], scale: [0.045, bodyH, 0.024] });
      }
      cap.push({ position: [cx, PLANTER_H - 0.015, cz], scale: [depth + 0.01, 0.03, len + 0.01] });
      soil.push({ position: [cx, PLANTER_H + 0.002, cz], scale: [depth - 0.06, 0.006, len - 0.06] });
      // Clumps of fine blades fanning out of a low mound, and every so often a pale plume above them.
      // A planter runs along its longer side; the clumps follow it.
      const alongX = depth > len;
      const [from, to] = alongX ? [item.minX, item.maxX] : [item.minZ, item.maxZ];
      for (let at = from + 0.12; at < to - 0.08; at += 0.11 + rand() * 0.05) {
        const across = (alongX ? cz : cx) + (rand() - 0.5) * 0.1, tone = Math.floor(rand() * GRASS.length);
        const bx = alongX ? at : across, z = alongX ? across : at;
        mounds[tone].push({ position: [bx, PLANTER_H + 0.03, z], scale: [0.07, 0.06, 0.07] });
        let tallest = 0;
        for (let k = 0; k < 6; k += 1) {
          const h = 0.18 + rand() * 0.24, rx = (rand() - 0.5) * 0.9, rz = (rand() - 0.5) * 0.9;
          tallest = Math.max(tallest, h);
          grass[(tone + (k % 2)) % GRASS.length].push({
            // A blade's local +y leans to (-sin rz, cos rz · cos rx, sin rx): its centre sits one half-length up that line.
            position: [bx - Math.sin(rz) * h * 0.9, PLANTER_H + Math.cos(rz) * Math.cos(rx) * h * 0.9, z + Math.sin(rx) * h * 0.9],
            scale: [0.018 + rand() * 0.01, h, 0.028], rotation: [rx, 0, rz],
          });
        }
        if (rand() < 0.3) {
          // A plume on a thin stalk rising just above the clump.
          const top = tallest * 1.9 + 0.1;
          plumes.push({ position: [bx, PLANTER_H + top, z], scale: [0.03, 0.12, 0.03] });
          stalks.push({ position: [bx, PLANTER_H + top / 2, z], scale: [0.004, top, 0.004] });
        }
      }
    }
    return { liner, slats, cap, soil, grass, mounds, plumes, stalks };
  }, [items]);
  return (
    <group>
      <Instances geometry={GEO.box} material={AMB.oakDark} items={parts.liner} />
      <Instances geometry={GEO.box} material={AMB.oak} items={parts.slats} cast={false} />
      <Instances geometry={GEO.box} material={AMB.oak} items={parts.cap} cast={false} />
      <Instances geometry={GEO.box} material={MAT.soil} items={parts.soil} cast={false} />
      {/* Hundreds of blades per planter: each is a slim spindle of eight faces, the mound under them a facet. */}
      {parts.grass.map((list, i) => <Instances key={i} geometry={GEO.blade} material={GRASS[i]} items={list} cast={false} />)}
      {parts.mounds.map((list, i) => <Instances key={`m${i}`} geometry={GEO.facet} material={GRASS[i]} items={list} cast={false} />)}
      <Instances geometry={GEO.facet} material={AMB.plume} items={parts.plumes} cast={false} />
      <Instances geometry={GEO.cyl} material={AMB.stalk} items={parts.stalks} cast={false} />
    </group>
  );
}

// ---------------------------------------------------------------------------
// Pendant lights over the benches
// ---------------------------------------------------------------------------

/**
 * A slim linear pendant over each desk row: its height and its housing. Its two wires run up to the ceiling line.
 * A line five centimetres wide a metre over every head never stands between the camera and the people at the desks.
 */
const PENDANT = { y: 2.75, w: 0.05, h: 0.035 } as const;
const PENDANT_MAT = {
  housing: matte("#2a2724", { roughness: 0.5 }),
  glow: new MeshStandardMaterial({ color: AGENTS_SCENE.light.glow, emissive: AGENTS_SCENE.light.glow, emissiveIntensity: 1.5, toneMapped: false }),
};

let poolMaterial: MeshBasicMaterial | null = null;
/** A soft oval of warm light, added onto the floor. */
function pool(): MeshBasicMaterial {
  if (!poolMaterial) {
    const map = cachedCanvasTexture("agents:pool", 128, 128, (ctx, w, h) => {
      const g = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
      g.addColorStop(0, "rgba(255,255,255,1)");
      g.addColorStop(0.55, "rgba(255,255,255,0.4)");
      g.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
    });
    poolMaterial = new MeshBasicMaterial({
      color: AGENTS_SCENE.light.pool, map, transparent: true, opacity: map ? 0.13 : 0, blending: AdditiveBlending, depthWrite: false,
    });
  }
  return poolMaterial;
}
const POOL_GEOMETRY = new PlaneGeometry(1, 1).rotateX(-Math.PI / 2);

/** The housing of every pendant on the floor: its middle, its length along x, its height and its width. Pure. */
export function pendantHousings(departments: readonly Pick<Department, "id" | "desks">[]): { x: number; y: number; z: number; length: number; h: number; w: number }[] {
  return benchesOf(departments).flatMap((bench) => {
    const length = Math.max(1.2, bench.length - 1.3);
    // One over each desk row of the bench.
    return [-0.45, 0.45].map((dz) => ({ x: bench.x, y: PENDANT.y + PENDANT.h / 2, z: bench.z + dz, length, h: PENDANT.h, w: PENDANT.w }));
  });
}

function Pendants({ departments }: { departments: readonly Department[] }) {
  const parts = useMemo(() => {
    const housings: Placement[] = [], glows: Placement[] = [], wires: Placement[] = [], pools: Placement[] = [];
    const wire = FACADE.h - PENDANT.y - PENDANT.h;
    for (const { x, y, z, length: run, h, w } of pendantHousings(departments)) {
      housings.push({ position: [x, y, z], scale: [run, h, w] });
      glows.push({ position: [x, PENDANT.y - 0.006, z], scale: [run - 0.04, 0.012, w - 0.014] });
      for (const dx of [-run * 0.4, run * 0.4]) {
        wires.push({ position: [x + dx, PENDANT.y + h + wire / 2, z], scale: [0.006, wire, 0.006] });
      }
    }
    for (const bench of benchesOf(departments)) {
      pools.push({ position: [bench.x, 0.012, bench.z], scale: [bench.length + 1.4, 1, 3.4] });
    }
    // Housings and wires are the same steel: one mesh.
    return { steel: [...housings, ...wires], glows, pools };
  }, [departments]);
  return (
    <group>
      <Instances geometry={GEO.box} material={PENDANT_MAT.housing} items={parts.steel} cast={false} />
      <Instances geometry={GEO.box} material={PENDANT_MAT.glow} items={parts.glows} cast={false} />
      <Instances geometry={POOL_GEOMETRY} material={pool()} items={parts.pools} cast={false} />
    </group>
  );
}

// ---------------------------------------------------------------------------
// The floor's ambience
// ---------------------------------------------------------------------------

export function AgentsFloorAmbience({ layout }: { layout: OfficeLayout }) {
  const items = useMemo(() => layout.ambience ?? [], [layout]);
  const byKind = useMemo(() => ({
    olive: items.filter((i) => i.kind === "olive"),
    bench: items.filter((i) => i.kind === "bench"),
    planter: items.filter((i) => i.kind === "planter"),
  }), [items]);
  const { minX, maxZ } = layout.bounds;
  return (
    <group>
      {/* Soft warm daylight from the south-west, no shadows: the one extra light the floor pays for. */}
      <directionalLight position={[minX - 12, 14, maxZ + 8]} intensity={0.35} color="#ffdcb4" />
      <Olives items={byKind.olive} />
      <Benches items={byKind.bench} />
      <Planters items={byKind.planter} />
      {/* Studio screens, cabinets, sofas and tables, and the commons' step seating, kitchen, booths and large trees. */}
      <CampusFittings items={items} />
      <Pendants departments={layout.departments} />
    </group>
  );
}
