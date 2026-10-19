/**
 * The coding floor's ambience between the rooms: tree planters closing the
 * cross aisles at the windows; along the glass, beside every neighbourhood, a
 * phone booth in the team's colour and a planter trough; down the main street
 * a grove of tall trees ringed by oak benches; slim white pendants over every
 * long table with soft pools of light below; and one warm fill light.
 *
 * Every repeated part is one instanced mesh, so the whole dressing costs a
 * handful of draw calls. The solid pieces come from `codingAmbience`, which
 * the layout also adds to its obstacles; the pendants and light pools are out
 * of reach (overhead, or flat on the floor). The pendants hide whenever the
 * camera comes down to their height, so they never block a close view.
 */
import { useLayoutEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import {
  AdditiveBlending, Color, Euler, Group, InstancedMesh, Matrix4, MeshBasicMaterial, MeshStandardMaterial, PlaneGeometry, Quaternion, Vector3,
  type BufferGeometry, type Material,
} from "three";
import { cachedCanvasTexture } from "./canvasMaterials";
import { BOOTH, codingAmbience, GROVE_H, TROUGH_H, type AmbienceItem } from "./codingAmbience";
import { GEO, MAT, matte } from "./OfficeFurniture";
import type { Department, OfficeLayout } from "./officeLayout";
import { CODING_SCENE, codingTeam } from "./officePalette";

// ---------------------------------------------------------------------------
// Instancing
// ---------------------------------------------------------------------------

export interface Placement {
  position: [number, number, number];
  scale: [number, number, number];
  /** Rotation (x, y, z) in radians; absent = none. */
  rotation?: [number, number, number];
  color?: string;
}

const _m = new Matrix4(), _q = new Quaternion(), _e = new Euler(), _p = new Vector3(), _s = new Vector3(), _c = new Color();

/** One instanced mesh for every placement of a part (the agents floor's ambience uses it too). */
export function Instances({ geometry, material, items, cast = true }: {
  geometry: BufferGeometry; material: Material; items: readonly Placement[]; cast?: boolean;
}) {
  const ref = useRef<InstancedMesh>(null);
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    items.forEach((item, i) => {
      _e.set(...(item.rotation ?? [0, 0, 0]));
      _m.compose(_p.set(...item.position), _q.setFromEuler(_e), _s.set(...item.scale));
      mesh.setMatrixAt(i, _m);
      if (item.color) mesh.setColorAt(i, _c.set(item.color));
    });
    mesh.count = items.length;
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [items]);
  if (items.length === 0) return null;
  return <instancedMesh key={items.length} ref={ref} args={[geometry, material, items.length]} castShadow={cast} receiveShadow frustumCulled={false} />;
}

// ---------------------------------------------------------------------------
// Materials
// ---------------------------------------------------------------------------

const AMB = {
  /** Planters in pale fibre-cement with a white-oak rim. */
  planter: matte("#e4e1db", { roughness: 0.8 }),
  rim: matte(CODING_SCENE.oak.planks[0], { roughness: 0.55 }),
  oak: matte(CODING_SCENE.oak.planks[3], { roughness: 0.55 }),
  oakDark: matte(CODING_SCENE.oak.seam, { roughness: 0.6 }),
  steel: matte("#2a2c30", { roughness: 0.4, metalness: 0.5 }),
  glass: new MeshStandardMaterial({ color: "#dfeff5", transparent: true, opacity: 0.22, roughness: 0.05, depthWrite: false }),
  /** White, so each instance's colour is the team's felt. */
  felt: matte("#ffffff", { roughness: 0.95 }),
  shade: matte("#fff1d6", { emissive: "#ffe2b8", emissiveIntensity: 0.8, roughness: 0.6 }),
  olive: matte("#6f8a58", { flatShading: true }),
  pendant: matte(CODING_SCENE.pendant.body, { roughness: 0.4, metalness: 0.4 }),
  pendantGlow: matte(CODING_SCENE.pendant.glow, { emissive: CODING_SCENE.pendant.glow, emissiveIntensity: 2, toneMapped: false }),
};

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
// Trees
// ---------------------------------------------------------------------------

/** Crown clusters of a tree in its own space (x, y, z, radius) and which leaf tone each takes. */
const CROWN: readonly [number, number, number, number, 0 | 1 | 2 | 3][] = [
  [0, 1.95, 0, 0.36, 0], [0.24, 1.72, 0.1, 0.27, 1], [-0.22, 1.78, -0.08, 0.28, 2], [0.05, 2.18, 0.08, 0.26, 3],
  [-0.1, 1.55, 0.2, 0.22, 1], [0.16, 2.02, -0.2, 0.24, 2], [-0.2, 2.06, 0.16, 0.22, 0], [0.12, 1.5, -0.14, 0.2, 3],
];
const LEAVES = [MAT.leaf, MAT.leafDark, MAT.leafLight, AMB.olive];

/** A tall tree in a square fibre-cement planter with an oak rim, filling its TREE_BOX footprint. */
function Trees({ items }: { items: readonly AmbienceItem[] }) {
  const parts = useMemo(() => {
    const planter: Placement[] = [], rim: Placement[] = [], soil: Placement[] = [], trunk: Placement[] = [];
    const leaves: Placement[][] = LEAVES.map(() => []);
    for (const item of items) {
      const x = (item.minX + item.maxX) / 2, z = (item.minZ + item.maxZ) / 2, size = item.maxX - item.minX;
      const rand = lcg(seedOf(item.id));
      const turn = rand() * Math.PI * 2, s = 0.9 + rand() * 0.18;
      planter.push({ position: [x, 0.27, z], scale: [size - 0.06, 0.54, size - 0.06] });
      rim.push({ position: [x, 0.555, z], scale: [size, 0.03, size] });
      soil.push({ position: [x, 0.572, z], scale: [size - 0.14, 0.006, size - 0.14] });
      trunk.push({ position: [x, 1.1, z], scale: [0.045, 1.1, 0.045], rotation: [0.04, 0, -0.05] });
      for (const [cx, cy, cz, r, tone] of CROWN) {
        const lx = cx * Math.cos(turn) - cz * Math.sin(turn), lz = cx * Math.sin(turn) + cz * Math.cos(turn);
        leaves[tone].push({ position: [x + lx * s, 0.1 + cy * s, z + lz * s], scale: [r * s, r * s * 0.9, r * s] });
      }
    }
    return { planter, rim, soil, trunk, leaves };
  }, [items]);
  return (
    <group>
      <Instances geometry={GEO.box} material={AMB.planter} items={parts.planter} />
      <Instances geometry={GEO.box} material={AMB.rim} items={parts.rim} />
      <Instances geometry={GEO.box} material={MAT.soil} items={parts.soil} cast={false} />
      <Instances geometry={GEO.cyl} material={MAT.trunk} items={parts.trunk} />
      {parts.leaves.map((list, i) => <Instances key={i} geometry={GEO.blob} material={LEAVES[i]} items={list} />)}
    </group>
  );
}

// ---------------------------------------------------------------------------
// Phone booths along the glass
// ---------------------------------------------------------------------------

/**
 * A phone booth: a steel frame with glass walls, its back and floor lined in
 * the team's felt, a small bench seat and a lamp under the roof. The open
 * front faces into the office.
 */
function Booths({ items }: { items: readonly AmbienceItem[] }) {
  const parts = useMemo(() => {
    const frame: Placement[] = [], glass: Placement[] = [], felt: Placement[] = [], seat: Placement[] = [], lamp: Placement[] = [];
    for (const item of items) {
      const cx = (item.minX + item.maxX) / 2, cz = (item.minZ + item.maxZ) / 2;
      const d = item.maxX - item.minX, len = item.maxZ - item.minZ, h = BOOTH.h;
      // Which way is the back wall: away from the office.
      const back = item.facing === "east" ? -1 : 1;
      const colour = codingTeam(item.tint ?? 0).felt;
      frame.push({ position: [cx, h - 0.04, cz], scale: [d, 0.08, len] });
      frame.push({ position: [cx, 0.03, cz], scale: [d, 0.06, len] });
      for (const [dx, dz] of [[-1, -1], [-1, 1], [1, -1], [1, 1]] as const) {
        frame.push({ position: [cx + dx * (d / 2 - 0.025), h / 2, cz + dz * (len / 2 - 0.025)], scale: [0.05, h, 0.05] });
      }
      // Glass on the two short sides, felt on the back.
      for (const dz of [-1, 1]) glass.push({ position: [cx, h / 2, cz + dz * (len / 2 - 0.02)], scale: [d - 0.06, h - 0.14, 0.02] });
      felt.push({ position: [cx + back * (d / 2 - 0.03), h / 2, cz], scale: [0.04, h - 0.14, len - 0.08], color: colour });
      felt.push({ position: [cx, 0.065, cz], scale: [d - 0.08, 0.01, len - 0.08], color: colour });
      seat.push({ position: [cx + back * (d / 2 - 0.25), 0.44, cz], scale: [0.4, 0.08, len - 0.2] });
      seat.push({ position: [cx + back * (d / 2 - 0.25), 0.22, cz], scale: [0.36, 0.38, len - 0.3] });
      lamp.push({ position: [cx, h - 0.1, cz], scale: [0.18, 0.03, 0.18] });
    }
    return { frame, glass, felt, seat, lamp };
  }, [items]);
  return (
    <group>
      <Instances geometry={GEO.box} material={AMB.steel} items={parts.frame} />
      <Instances geometry={GEO.box} material={AMB.glass} items={parts.glass} cast={false} />
      <Instances geometry={GEO.box} material={AMB.felt} items={parts.felt} />
      <Instances geometry={GEO.box} material={AMB.oak} items={parts.seat} />
      <Instances geometry={GEO.cyl} material={AMB.shade} items={parts.lamp} cast={false} />
    </group>
  );
}

// ---------------------------------------------------------------------------
// Groves down the main street
// ---------------------------------------------------------------------------

/** A grove's crown in its own space (x, y, z, radius, leaf tone): broad and high, like a street tree. */
const GROVE_CROWN: readonly [number, number, number, number, 0 | 1 | 2 | 3][] = [
  [0, 3.5, 0, 0.95, 0], [0.7, 3.2, 0.2, 0.7, 1], [-0.65, 3.3, -0.25, 0.72, 2], [0.15, 4.0, 0.3, 0.65, 3],
  [-0.25, 3.0, 0.6, 0.6, 1], [0.4, 3.6, -0.6, 0.62, 2], [-0.6, 3.8, 0.35, 0.55, 0], [0.55, 2.9, -0.35, 0.5, 3],
];

/**
 * A grove: a round planter of pale fibre-cement ringed by an oak bench, a tall
 * tree in it whose crown spreads over the street, and low planting at its foot.
 */
function Groves({ items }: { items: readonly AmbienceItem[] }) {
  const parts = useMemo(() => {
    const planter: Placement[] = [], rim: Placement[] = [], soil: Placement[] = [], bench: Placement[] = [], trunk: Placement[] = [];
    const leaves: Placement[][] = LEAVES.map(() => []);
    for (const item of items) {
      const x = (item.minX + item.maxX) / 2, z = (item.minZ + item.maxZ) / 2, r = (item.maxX - item.minX) / 2;
      const rand = lcg(seedOf(item.id));
      bench.push({ position: [x, 0.2, z], scale: [r, 0.4, r] });
      bench.push({ position: [x, 0.43, z], scale: [r + 0.02, 0.05, r + 0.02] });
      planter.push({ position: [x, 0.36, z], scale: [r - 0.42, 0.72, r - 0.42] });
      rim.push({ position: [x, 0.73, z], scale: [r - 0.4, 0.03, r - 0.4] });
      soil.push({ position: [x, 0.745, z], scale: [r - 0.5, 0.01, r - 0.5] });
      trunk.push({ position: [x, 1.9, z], scale: [0.09, 2.4, 0.09], rotation: [0.03, 0, -0.04] });
      const turn = rand() * Math.PI * 2, s = 0.92 + rand() * 0.14;
      for (const [cx, cy, cz, cr, tone] of GROVE_CROWN) {
        const lx = cx * Math.cos(turn) - cz * Math.sin(turn), lz = cx * Math.sin(turn) + cz * Math.cos(turn);
        leaves[tone].push({ position: [x + lx * s, cy * s * (GROVE_H / 4.4), z + lz * s], scale: [cr * s, cr * s * 0.85, cr * s] });
      }
      // Low planting round the trunk.
      for (let k = 0; k < 6; k += 1) {
        const a = (k / 6) * Math.PI * 2 + rand(), d = (r - 0.6) * (0.5 + rand() * 0.4);
        leaves[k % LEAVES.length].push({ position: [x + Math.cos(a) * d, 0.84, z + Math.sin(a) * d], scale: [0.18, 0.14, 0.18] });
      }
    }
    return { planter, rim, soil, bench, trunk, leaves };
  }, [items]);
  return (
    <group>
      <Instances geometry={GEO.cyl} material={AMB.oak} items={parts.bench} />
      <Instances geometry={GEO.cyl} material={AMB.planter} items={parts.planter} />
      <Instances geometry={GEO.cyl} material={AMB.rim} items={parts.rim} />
      <Instances geometry={GEO.cyl} material={MAT.soil} items={parts.soil} cast={false} />
      <Instances geometry={GEO.cyl} material={MAT.trunk} items={parts.trunk} />
      {parts.leaves.map((list, i) => <Instances key={i} geometry={GEO.blob} material={LEAVES[i]} items={list} />)}
    </group>
  );
}

// ---------------------------------------------------------------------------
// Planter troughs along the glass
// ---------------------------------------------------------------------------

/** Long fibre-cement troughs on an oak plinth, planted with low foliage, kept low so they hide nothing. */
function Troughs({ items }: { items: readonly AmbienceItem[] }) {
  const parts = useMemo(() => {
    const body: Placement[] = [], plinth: Placement[] = [], soil: Placement[] = [];
    const leaves: Placement[][] = LEAVES.map(() => []);
    for (const item of items) {
      const rand = lcg(seedOf(item.id));
      const cx = (item.minX + item.maxX) / 2, depth = item.maxX - item.minX;
      const len = item.maxZ - item.minZ, cz = (item.minZ + item.maxZ) / 2;
      plinth.push({ position: [cx, 0.03, cz], scale: [depth - 0.04, 0.06, len - 0.04] });
      body.push({ position: [cx, 0.06 + (TROUGH_H - 0.06) / 2, cz], scale: [depth, TROUGH_H - 0.06, len] });
      soil.push({ position: [cx, TROUGH_H + 0.003, cz], scale: [depth - 0.06, 0.006, len - 0.06] });
      for (let z = item.minZ + 0.18; z < item.maxZ - 0.12; z += 0.2 + rand() * 0.08) {
        const r = 0.13 + rand() * 0.08;
        leaves[Math.floor(rand() * LEAVES.length)].push({ position: [cx + (rand() - 0.5) * 0.08, TROUGH_H + r * 0.7, z], scale: [r * 0.9, r * (1 + rand() * 0.6), r] });
      }
    }
    return { body, plinth, soil, leaves };
  }, [items]);
  return (
    <group>
      <Instances geometry={GEO.box} material={AMB.oak} items={parts.plinth} />
      <Instances geometry={GEO.box} material={AMB.planter} items={parts.body} />
      <Instances geometry={GEO.box} material={MAT.soil} items={parts.soil} cast={false} />
      {parts.leaves.map((list, i) => <Instances key={i} geometry={GEO.blob} material={LEAVES[i]} items={list} />)}
    </group>
  );
}

// ---------------------------------------------------------------------------
// Pendants over the benches
// ---------------------------------------------------------------------------

const PENDANT_Y = 3.0;
/** Below this camera height the pendants hide, so a close or low view never looks through them. */
const PENDANT_HIDE_BELOW = PENDANT_Y + 4;

interface Bench { x: number; z: number; length: number }

/** One bench per pair of desk rows: its centre and length from the desks it holds. */
export function benchesOf(departments: readonly Pick<Department, "id" | "desks">[]): Bench[] {
  const out: Bench[] = [];
  for (const dept of departments) {
    const groups = new Map<string, { xs: number[]; zs: number[] }>();
    for (const desk of dept.desks) {
      // Desk ids are "<dept>:<bench>:<facing>:<col>".
      const key = desk.id.split(":").slice(0, -2).join(":");
      const group = groups.get(key) ?? { xs: [], zs: [] };
      group.xs.push(desk.x);
      group.zs.push(desk.z);
      groups.set(key, group);
    }
    for (const { xs, zs } of groups.values()) {
      const minX = Math.min(...xs), maxX = Math.max(...xs);
      out.push({ x: (minX + maxX) / 2, z: zs.reduce((s, v) => s + v, 0) / zs.length, length: maxX - minX + 1.2 });
    }
  }
  return out;
}

let poolMaterial: MeshBasicMaterial | null = null;
/** A soft oval of warm light, added onto the floor. */
function pool(): MeshBasicMaterial {
  if (!poolMaterial) {
    const map = cachedCanvasTexture("coding:pool", 128, 128, (ctx, w, h) => {
      const g = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
      g.addColorStop(0, "rgba(255,255,255,1)");
      g.addColorStop(0.5, "rgba(255,255,255,0.45)");
      g.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
    });
    poolMaterial = new MeshBasicMaterial({
      color: CODING_SCENE.pendant.pool, map, transparent: true, opacity: map ? 0.16 : 0, blending: AdditiveBlending, depthWrite: false,
    });
  }
  return poolMaterial;
}
const POOL_GEOMETRY = new PlaneGeometry(1, 1).rotateX(-Math.PI / 2);

function Pendants({ departments }: { departments: readonly Department[] }) {
  const lamps = useRef<Group>(null);
  const parts = useMemo(() => {
    const body: Placement[] = [], glow: Placement[] = [], cable: Placement[] = [], pools: Placement[] = [];
    for (const bench of benchesOf(departments)) {
      const len = bench.length - 0.4;
      body.push({ position: [bench.x, PENDANT_Y, bench.z], scale: [len, 0.05, 0.07] });
      glow.push({ position: [bench.x, PENDANT_Y - 0.027, bench.z], scale: [len - 0.06, 0.006, 0.045] });
      for (const dx of [-len * 0.38, len * 0.38]) cable.push({ position: [bench.x + dx, PENDANT_Y + 0.6, bench.z], scale: [0.006, 1.2, 0.006] });
      pools.push({ position: [bench.x, 0.012, bench.z], scale: [bench.length + 1.6, 1, 3.6] });
    }
    return { body, glow, cable, pools };
  }, [departments]);
  useFrame(({ camera }) => {
    const group = lamps.current;
    if (group) group.visible = camera.position.y > PENDANT_HIDE_BELOW;
  });
  return (
    <group>
      <group ref={lamps}>
        <Instances geometry={GEO.box} material={AMB.pendant} items={parts.body} cast={false} />
        <Instances geometry={GEO.box} material={AMB.pendantGlow} items={parts.glow} cast={false} />
        <Instances geometry={GEO.box} material={AMB.pendant} items={parts.cable} cast={false} />
      </group>
      <Instances geometry={POOL_GEOMETRY} material={pool()} items={parts.pools} cast={false} />
    </group>
  );
}

// ---------------------------------------------------------------------------
// The floor's ambience
// ---------------------------------------------------------------------------

export function CodingFloorAmbience({ layout }: { layout: OfficeLayout }) {
  const items = useMemo(() => codingAmbience(layout), [layout]);
  const byKind = useMemo(() => ({
    tree: items.filter((i) => i.kind === "tree"),
    booth: items.filter((i) => i.kind === "booth"),
    trough: items.filter((i) => i.kind === "trough"),
    grove: items.filter((i) => i.kind === "grove"),
  }), [items]);
  const { minX, maxZ } = layout.bounds;
  return (
    <group>
      {/* Warm late-afternoon fill from the south-west, no shadows: the one extra light the floor pays for. */}
      <directionalLight position={[minX - 12, 12, maxZ + 6]} intensity={0.4} color="#ffc68a" />
      <Trees items={byKind.tree} />
      <Booths items={byKind.booth} />
      <Troughs items={byKind.trough} />
      <Groves items={byKind.grove} />
      <Pendants departments={layout.departments} />
    </group>
  );
}
