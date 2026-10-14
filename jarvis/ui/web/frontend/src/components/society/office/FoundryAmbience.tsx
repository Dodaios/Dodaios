/**
 * The Foundry deck's dressing along the glass, in the footprints
 * `codingAmbience` gives the layout as obstacles: a bio dome where each cross
 * aisle meets the windows (a tree under glass with a violet grow light),
 * archive racks with running lights along the west glass, and coolant lines
 * with glowing bands and valve wheels along the east glass. Plus the deck's
 * two fill lights: a cool rim from the nebula and a warm bounce from below.
 *
 * Every repeated part is one instanced mesh.
 */
import { useEffect, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import { Color, MeshBasicMaterial, MeshStandardMaterial, RepeatWrapping, TorusGeometry } from "three";
import { cachedCanvasTexture } from "./canvasMaterials";
import { codingAmbience, LIBRARY_H, TROUGH_H, type AmbienceItem } from "./codingAmbience";
import { Instances, type Placement } from "./Instances";
import { FOUNDRY, glowColour } from "./foundryPalette";
import { GEO, MAT, matte } from "./OfficeFurniture";
import type { OfficeLayout } from "./officeLayout";

const AMB = {
  steel: matte(FOUNDRY.steel, { roughness: 0.4, metalness: 0.65 }),
  steelDark: matte(FOUNDRY.steelDark, { roughness: 0.5, metalness: 0.5 }),
  gold: matte(FOUNDRY.gold, { roughness: 0.28, metalness: 0.85 }),
  glass: new MeshStandardMaterial({ color: "#bfe6ff", transparent: true, opacity: 0.16, roughness: 0.05, metalness: 0.1, depthWrite: false }),
  soil: matte("#1c1714"),
  growLight: new MeshBasicMaterial({ color: glowColour("#d07bff", 1.3), toneMapped: false }),
  coolant: new MeshBasicMaterial({ color: new Color(FOUNDRY.code).multiplyScalar(1.7), toneMapped: false }),
  pipe: matte("#4a505b", { roughness: 0.3, metalness: 0.8 }),
  valve: matte("#c0392b", { roughness: 0.5, metalness: 0.3 }),
};

const VALVE = new TorusGeometry(0.09, 0.018, 6, 16);

/** Deterministic pseudo-random numbers per item. */
function rng(id: string): () => number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i += 1) h = Math.imul(h ^ id.charCodeAt(i), 16777619);
  let state = h >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x1_0000_0000;
  };
}

// ---------------------------------------------------------------------------
// Bio domes
// ---------------------------------------------------------------------------

const CROWN: readonly [number, number, number, number][] = [
  [0, 1.25, 0, 0.3], [0.18, 1.08, 0.08, 0.22], [-0.17, 1.12, -0.06, 0.23], [0.04, 1.45, 0.06, 0.2], [-0.08, 0.95, 0.15, 0.17],
];
const LEAVES = [MAT.leaf, MAT.leafDark, MAT.leafLight];

function BioDomes({ items }: { items: readonly AmbienceItem[] }) {
  const parts = useMemo(() => {
    const base: Placement[] = [], band: Placement[] = [], soil: Placement[] = [], glass: Placement[] = [], cap: Placement[] = [];
    const ring: Placement[] = [], trunk: Placement[] = [];
    const leaves: Placement[][] = LEAVES.map(() => []);
    for (const item of items) {
      const x = (item.minX + item.maxX) / 2, z = (item.minZ + item.maxZ) / 2, r = (item.maxX - item.minX) / 2;
      const rand = rng(item.id);
      base.push({ position: [x, 0.2, z], scale: [r, 0.4, r] });
      band.push({ position: [x, 0.36, z], scale: [r + 0.01, 0.04, r + 0.01] });
      soil.push({ position: [x, 0.405, z], scale: [r - 0.05, 0.01, r - 0.05] });
      glass.push({ position: [x, 1.25, z], scale: [r - 0.03, 1.7, r - 0.03] });
      cap.push({ position: [x, 2.15, z], scale: [r, 0.1, r] });
      ring.push({ position: [x, 2.08, z], scale: [r - 0.06, 0.025, r - 0.06] });
      trunk.push({ position: [x, 0.7, z], scale: [0.035, 0.6, 0.035] });
      const turn = rand() * Math.PI * 2;
      CROWN.forEach(([cx, cy, cz, cr], i) => {
        const px = cx * Math.cos(turn) - cz * Math.sin(turn), pz = cx * Math.sin(turn) + cz * Math.cos(turn);
        leaves[i % LEAVES.length].push({ position: [x + px, cy, z + pz], scale: [cr, cr * 0.9, cr] });
      });
    }
    return { base, band, soil, glass, cap, ring, trunk, leaves };
  }, [items]);
  return (
    <group>
      <Instances geometry={GEO.cyl} material={AMB.steelDark} items={parts.base} />
      <Instances geometry={GEO.cyl} material={AMB.gold} items={parts.band} cast={false} />
      <Instances geometry={GEO.cyl} material={AMB.soil} items={parts.soil} cast={false} />
      <Instances geometry={GEO.cyl} material={MAT.trunk} items={parts.trunk} />
      {parts.leaves.map((list, i) => <Instances key={i} geometry={GEO.blob} material={LEAVES[i]} items={list} />)}
      <Instances geometry={GEO.cyl} material={AMB.glass} items={parts.glass} cast={false} />
      <Instances geometry={GEO.cyl} material={AMB.steel} items={parts.cap} />
      <Instances geometry={GEO.cyl} material={AMB.growLight} items={parts.ring} cast={false} />
    </group>
  );
}

// ---------------------------------------------------------------------------
// Archive racks
// ---------------------------------------------------------------------------

function drawRackFront(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  ctx.fillStyle = "#1a1c21";
  ctx.fillRect(0, 0, w, h);
  let seed = 0xa4c1;
  const rand = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 0x1_0000_0000; };
  // Drive bays in rows, each with a status LED.
  for (let y = 6; y < h - 8; y += 16) {
    for (let x = 4; x < w - 4; x += 30) {
      ctx.fillStyle = "#2a2e36";
      ctx.fillRect(x, y, 26, 12);
      ctx.fillStyle = "#121418";
      ctx.fillRect(x + 2, y + 9, 22, 1);
      const on = rand();
      ctx.fillStyle = on > 0.6 ? "#ffffff" : on > 0.3 ? "#6b7480" : "#2f343c";
      ctx.fillRect(x + 20, y + 3, 3, 3);
    }
  }
}

function ArchiveRacks({ items, animate }: { items: readonly AmbienceItem[]; animate: boolean }) {
  const front = useMemo(() => {
    const base = cachedCanvasTexture("foundry:rack", 128, 128, drawRackFront);
    const map = base?.clone() ?? null;
    if (map) { map.wrapS = map.wrapT = RepeatWrapping; map.repeat.set(1, 1); map.needsUpdate = true; }
    return new MeshStandardMaterial({
      color: map ? "#ffffff" : FOUNDRY.steelDark, map, roughness: 0.45, metalness: 0.4,
      emissive: new Color("#7dffb0"), emissiveMap: map, emissiveIntensity: map ? 1.3 : 0,
    });
  }, []);
  useEffect(() => () => { front.map?.dispose(); front.dispose(); }, [front]);
  useFrame(({ clock }) => {
    // The drive lights wander: the front texture steps along now and then.
    if (animate && front.map) front.map.offset.x = Math.floor(clock.elapsedTime * 1.5) * 0.37 % 1;
  });
  const parts = useMemo(() => {
    const body: Placement[] = [], face: Placement[] = [], cap: Placement[] = [];
    for (const item of items) {
      const x = (item.minX + item.maxX) / 2, z = (item.minZ + item.maxZ) / 2, d = item.maxX - item.minX, len = item.maxZ - item.minZ;
      const out = item.facing === "east" ? 1 : -1;
      body.push({ position: [x, LIBRARY_H / 2, z], scale: [d, LIBRARY_H, len] });
      face.push({ position: [x + out * (d / 2 + 0.003), LIBRARY_H * 0.48, z], scale: [0.006, LIBRARY_H * 0.8, len - 0.1] });
      cap.push({ position: [x, LIBRARY_H + 0.015, z], scale: [d + 0.02, 0.03, len + 0.02] });
    }
    return { body, face, cap };
  }, [items]);
  return (
    <group>
      <Instances geometry={GEO.box} material={AMB.steelDark} items={parts.body} />
      <Instances geometry={GEO.box} material={front} items={parts.face} cast={false} />
      <Instances geometry={GEO.box} material={AMB.gold} items={parts.cap} cast={false} />
    </group>
  );
}

// ---------------------------------------------------------------------------
// Coolant lines
// ---------------------------------------------------------------------------

function CoolantLines({ items }: { items: readonly AmbienceItem[] }) {
  const parts = useMemo(() => {
    const base: Placement[] = [], pipe: Placement[] = [], band: Placement[] = [], valve: Placement[] = [], flange: Placement[] = [];
    for (const item of items) {
      const x = (item.minX + item.maxX) / 2, z = (item.minZ + item.maxZ) / 2, d = item.maxX - item.minX, len = item.maxZ - item.minZ;
      base.push({ position: [x, 0.09, z], scale: [d, 0.18, len] });
      for (const [dx, y] of [[-d * 0.22, 0.27], [d * 0.22, 0.35]] as const) {
        pipe.push({ position: [x + dx, y, z], scale: [0.065, len, 0.065], rotation: [Math.PI / 2, 0, 0] });
        for (let s = -len / 2 + 0.4; s < len / 2 - 0.2; s += 0.8) {
          band.push({ position: [x + dx, y, z + s], scale: [0.072, 0.05, 0.072], rotation: [Math.PI / 2, 0, 0] });
        }
      }
      flange.push({ position: [x, TROUGH_H - 0.05, z - len / 2 + 0.12], scale: [d * 0.9, 0.1, 0.1] });
      flange.push({ position: [x, TROUGH_H - 0.05, z + len / 2 - 0.12], scale: [d * 0.9, 0.1, 0.1] });
      valve.push({ position: [x, TROUGH_H + 0.04, z], scale: [1, 1, 1], rotation: [Math.PI / 2, 0, 0] });
    }
    return { base, pipe, band, valve, flange };
  }, [items]);
  return (
    <group>
      <Instances geometry={GEO.box} material={AMB.steelDark} items={parts.base} />
      <Instances geometry={GEO.cyl} material={AMB.pipe} items={parts.pipe} />
      <Instances geometry={GEO.cyl} material={AMB.coolant} items={parts.band} cast={false} />
      <Instances geometry={GEO.box} material={AMB.steel} items={parts.flange} />
      <Instances geometry={VALVE} material={AMB.valve} items={parts.valve} />
    </group>
  );
}

/** The deck's dressing along the glass, and its two fill lights. */
export function FoundryAmbience({ layout, animate }: { layout: OfficeLayout; animate: boolean }) {
  // One list per kind, kept while the plan stands: each piece below memoises its placements on it.
  const { domes, racks, lines } = useMemo(() => {
    const items = codingAmbience({ departments: layout.departments, rooms: layout.rooms });
    return {
      domes: items.filter((i) => i.kind === "tree"),
      racks: items.filter((i) => i.kind === "library"),
      lines: items.filter((i) => i.kind === "trough"),
    };
  }, [layout]);
  const { minX, maxX, minZ, maxZ } = layout.bounds;
  return (
    <group>
      {/* A cool rim from the nebula in the north-west, a warm bounce from the planet below. */}
      <directionalLight position={[minX - 20, 14, minZ - 16]} intensity={0.55} color="#a98bff" />
      <directionalLight position={[maxX + 8, -10, maxZ + 8]} intensity={0.25} color="#ffb27a" />
      <BioDomes items={domes} />
      <ArchiveRacks items={racks} animate={animate} />
      <CoolantLines items={lines} />
    </group>
  );
}
