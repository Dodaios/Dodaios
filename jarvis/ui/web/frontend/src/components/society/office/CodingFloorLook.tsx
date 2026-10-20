/**
 * The coding floor's own look: a tech campus floor in the tower. Polished
 * pale concrete is the ground; a terrazzo main street with brass edges runs
 * down the concourse; and every workspace is a team neighbourhood — an island
 * of white oak with long shared tables (CodingTables) and, along its north
 * edge, a living moss wall in a white-oak frame carrying the team's name on
 * an oak header with a stripe of the team's colour.
 *
 * Purely visual. The only solid part is the moss wall, which stays inside the
 * sign-wall footprint the layout already walks round.
 */
import { useEffect, useMemo } from "react";
import type { ThreeEvent } from "@react-three/fiber";
import { MeshStandardMaterial, RepeatWrapping, type Texture } from "three";
import { fill, useT } from "@/i18n";
import type { SocietyAgent } from "../data";
import { cachedCanvasTexture, ownedCanvasTexture } from "./canvasMaterials";
import { CodingTables } from "./CodingTables";
import { Box, matte } from "./OfficeFurniture";
import type { Department, OfficeLayout, Rect } from "./officeLayout";
import { CODING_SCENE, codingTeam } from "./officePalette";

/** Metres covered by one repeat of the concrete, the terrazzo and the oak. */
const CONCRETE_METRES = 4.5;
const TERRAZZO_METRES = 3;
const OAK_METRES = 3.6;

/** Deterministic pseudo-random numbers, so the surfaces never shimmer between loads. */
function lcg(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x1_0000_0000;
  };
}

/** A cached base texture, cloned per surface with its own repeat. */
function repeated(base: Texture | null, repeatX: number, repeatZ: number): Texture | null {
  if (!base) return null;
  const map = base.clone();
  map.wrapS = map.wrapT = RepeatWrapping;
  map.anisotropy = 8;
  map.repeat.set(repeatX, repeatZ);
  map.needsUpdate = true;
  return map;
}

/** Polished concrete: soft clouds of tone, a fine aggregate, and saw-cut joints every 1.5 m; seamless. */
function drawConcrete(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const { base, cloud, joint } = CODING_SCENE.concrete;
  const rand = lcg(0xc0c4e7e);
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, w, h);
  for (let i = 0; i < 46; i += 1) {
    const x = rand() * w, y = rand() * h, r = 20 + rand() * 70;
    const tone = cloud[i % cloud.length];
    for (const dx of [-w, 0, w]) {
      for (const dy of [-h, 0, h]) {
        const g = ctx.createRadialGradient(x + dx, y + dy, 0, x + dx, y + dy, r);
        g.addColorStop(0, `${tone}aa`);
        g.addColorStop(1, `${tone}00`);
        ctx.fillStyle = g;
        ctx.fillRect(x + dx - r, y + dy - r, r * 2, r * 2);
      }
    }
  }
  for (let i = 0; i < 3200; i += 1) {
    ctx.fillStyle = rand() > 0.5 ? "rgba(255,255,255,0.10)" : "rgba(90,84,76,0.07)";
    ctx.fillRect(Math.floor(rand() * w), Math.floor(rand() * h), 1, 1);
  }
  // Saw cuts: three per repeat (4.5 m), on both axes.
  ctx.fillStyle = joint;
  for (let i = 0; i < 3; i += 1) {
    ctx.fillRect((i * w) / 3, 0, 1.5, h);
    ctx.fillRect(0, (i * h) / 3, w, 1.5);
  }
}

/** Terrazzo: a warm pale ground with chips of stone in several sizes; seamless. */
function drawTerrazzo(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const { base, chips } = CODING_SCENE.terrazzo;
  const rand = lcg(0x7e4a);
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, w, h);
  for (let i = 0; i < 1900; i += 1) {
    ctx.fillStyle = chips[Math.floor(rand() * chips.length)];
    const s = 1 + rand() * (rand() > 0.92 ? 7 : 3);
    const x = rand() * w, y = rand() * h;
    ctx.beginPath();
    ctx.ellipse(x, y, s, s * (0.55 + rand() * 0.45), rand() * Math.PI, 0, Math.PI * 2);
    ctx.fill();
  }
}

/** White-oak planks, 18 cm wide, staggered ends, a fine grain; seamless along both axes. */
function drawOak(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const { seam, planks } = CODING_SCENE.oak;
  const rand = lcg(0x0a4);
  const rows = 20, rowH = h / rows;
  ctx.fillStyle = seam;
  ctx.fillRect(0, 0, w, h);
  for (let r = 0; r < rows; r += 1) {
    // One row is exactly one period long, drawn twice (at x and x + w), so it wraps without a seam.
    const start = -rand() * w * 0.5;
    let x = start;
    while (x < start + w - 1) {
      const len = Math.min(w * (0.35 + rand() * 0.4), start + w - x);
      const tone = planks[Math.floor(rand() * planks.length)];
      for (const dx of [0, w]) {
        ctx.fillStyle = tone;
        ctx.fillRect(x + dx + 1, r * rowH + 1, len - 2, rowH - 2);
        ctx.fillStyle = "rgba(120,92,58,0.08)";
        for (const gy of [0.3, 0.65]) ctx.fillRect(x + dx + 1, r * rowH + rowH * gy, len - 2, 1);
      }
      x += len;
    }
  }
}

/** Width of the concrete band's brass strip along the main street's edges. */
const STRIP_M = 0.04;

/** The concourse: the strip between the two neighbourhood columns, from the north rooms to the south strip. */
export function mainStreet(layout: Pick<OfficeLayout, "departments" | "rooms">): Rect | null {
  const depts = layout.departments;
  if (depts.length === 0) return null;
  const colMinX = Math.min(...depts.map((d) => d.minX)), colMaxX = Math.max(...depts.map((d) => d.maxX));
  const west = depts.filter((d) => d.minX <= colMinX + 1e-6);
  const east = depts.filter((d) => d.maxX >= colMaxX - 1e-6 && d.minX > colMinX + 1e-6);
  if (west.length === 0 || east.length === 0) return null;
  const firstZ = Math.min(...depts.map((d) => d.minZ)), lastZ = Math.max(...depts.map((d) => d.maxZ));
  const north = layout.rooms.filter((r) => r.maxZ <= firstZ + 1e-6).map((r) => r.maxZ);
  const south = layout.rooms.filter((r) => r.minZ >= lastZ - 1e-6).map((r) => r.minZ);
  return {
    minX: Math.max(...west.map((d) => d.maxX)), maxX: Math.min(...east.map((d) => d.minX)),
    minZ: north.length > 0 ? Math.max(...north) : firstZ, maxZ: south.length > 0 ? Math.min(...south) : lastZ,
  };
}

/**
 * The slab and floor of the coding floor: polished concrete everywhere, the
 * terrazzo main street with brass strips down the concourse, a dark edge and a
 * warm rim. The tower's window walls and balustrade stand round it (BuildingShell).
 */
export function CodingSlab({ layout, onFloorClick }: { layout: OfficeLayout; onFloorClick: (event: ThreeEvent<MouseEvent>) => void }) {
  const { minX, maxX, minZ, maxZ } = layout.bounds;
  const w = maxX - minX, d = maxZ - minZ, cx = (minX + maxX) / 2, cz = (minZ + maxZ) / 2;
  const street = useMemo(() => mainStreet(layout), [layout]);
  const floor = useMemo(() => {
    const map = repeated(cachedCanvasTexture("coding:concrete", 512, 512, drawConcrete), w / CONCRETE_METRES, d / CONCRETE_METRES);
    return new MeshStandardMaterial({ color: map ? "#ffffff" : CODING_SCENE.concrete.base, map, roughness: 0.42, metalness: 0.05 });
  }, [w, d]);
  const terrazzo = useMemo(() => {
    if (!street) return null;
    const map = repeated(cachedCanvasTexture("coding:terrazzo", 512, 512, drawTerrazzo),
      (street.maxX - street.minX) / TERRAZZO_METRES, (street.maxZ - street.minZ) / TERRAZZO_METRES);
    return new MeshStandardMaterial({ color: map ? "#ffffff" : CODING_SCENE.terrazzo.base, map, roughness: 0.35 });
  }, [street]);
  const brass = useMemo(() => matte(CODING_SCENE.brass, { roughness: 0.35, metalness: 0.55 }), []);
  const edge = useMemo(() => matte(CODING_SCENE.slabEdge, { roughness: 0.7 }), []);
  const rim = useMemo(() => new MeshStandardMaterial({
    color: CODING_SCENE.rim, emissive: CODING_SCENE.rim, emissiveIntensity: 0.9, roughness: 0.4, toneMapped: false,
  }), []);
  useEffect(() => () => {
    floor.map?.dispose(); floor.dispose(); terrazzo?.map?.dispose(); terrazzo?.dispose();
    brass.dispose(); edge.dispose(); rim.dispose();
  }, [floor, terrazzo, brass, edge, rim]);
  const glow = 0.05;
  return (
    <group>
      <Box size={[w, 0.6, d]} position={[cx, -0.3, cz]} material={edge} cast={false} />
      <Box size={[w + glow, glow, glow]} position={[cx, -0.06, minZ]} material={rim} cast={false} />
      <Box size={[w + glow, glow, glow]} position={[cx, -0.06, maxZ]} material={rim} cast={false} />
      <Box size={[glow, glow, d + glow]} position={[minX, -0.06, cz]} material={rim} cast={false} />
      <Box size={[glow, glow, d + glow]} position={[maxX, -0.06, cz]} material={rim} cast={false} />
      <mesh position={[cx, 0.001, cz]} rotation={[-Math.PI / 2, 0, 0]} material={floor} receiveShadow onClick={onFloorClick}>
        <planeGeometry args={[w, d]} />
      </mesh>
      {street && terrazzo && (
        <group>
          <mesh position={[(street.minX + street.maxX) / 2, 0.003, (street.minZ + street.maxZ) / 2]} rotation={[-Math.PI / 2, 0, 0]}
            material={terrazzo} receiveShadow onClick={onFloorClick}>
            <planeGeometry args={[street.maxX - street.minX, street.maxZ - street.minZ]} />
          </mesh>
          {[street.minX + 0.3, street.maxX - 0.3].map((x) => (
            <Box key={x} size={[STRIP_M, 0.004, street.maxZ - street.minZ]} position={[x, 0.004, (street.minZ + street.maxZ) / 2]}
              material={brass} cast={false} />
          ))}
        </group>
      )}
    </group>
  );
}

// ---------------------------------------------------------------------------
// The living wall
// ---------------------------------------------------------------------------

const WALL_H = 1.95;
const HEADER = { h: 0.42, w: 1024, px: 160 } as const;

/** Moss: dense tufts in several greens with fern sprays; seamless (white-free, lit by the scene). */
function drawMoss(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const { base, tones, fern } = CODING_SCENE.moss;
  const rand = lcg(0x3055);
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, w, h);
  for (let i = 0; i < 1400; i += 1) {
    const x = rand() * w, y = rand() * h, r = 2 + rand() * 7;
    ctx.fillStyle = tones[Math.floor(rand() * tones.length)];
    for (const dx of [-w, 0, w]) {
      for (const dy of [-h, 0, h]) {
        ctx.beginPath();
        ctx.arc(x + dx, y + dy, r, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }
  // Fern sprays: a stem with short leaflets either side.
  ctx.strokeStyle = fern;
  ctx.lineWidth = 1.4;
  for (let i = 0; i < 26; i += 1) {
    const x = rand() * w, y = rand() * h, len = 14 + rand() * 18, a = -Math.PI / 2 + (rand() - 0.5) * 1.2;
    for (let k = 0; k < len; k += 3) {
      const px = x + Math.cos(a) * k, py = y + Math.sin(a) * k, leaf = (len - k) * 0.35;
      ctx.beginPath();
      ctx.moveTo(px, py); ctx.lineTo(px + Math.cos(a + 1.1) * leaf, py + Math.sin(a + 1.1) * leaf);
      ctx.moveTo(px, py); ctx.lineTo(px + Math.cos(a - 1.1) * leaf, py + Math.sin(a - 1.1) * leaf);
      ctx.stroke();
    }
  }
}

/** The oak header: the team's name in dark capitals, the room number small beside it, a stripe of the team's colour below. */
function drawHeader(label: string, caption: string, accent: string, ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const { planks, seam } = CODING_SCENE.oak;
  ctx.fillStyle = planks[2];
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = "rgba(120,92,58,0.10)";
  for (let y = 6; y < h; y += 9) ctx.fillRect(0, y, w, 1);
  ctx.fillStyle = seam;
  ctx.fillRect(0, h - 3, w, 3);
  ctx.fillStyle = accent;
  ctx.fillRect(0, h - 18, w, 12);
  const name = label.length > 26 ? `${label.slice(0, 25)}…` : label;
  ctx.textBaseline = "middle";
  ctx.font = "700 72px system-ui, -apple-system, 'Segoe UI', sans-serif";
  const nameW = Math.min(ctx.measureText(name).width, w - 260);
  ctx.save();
  ctx.translate(48, (h - 18) / 2);
  ctx.scale(nameW / Math.max(1, ctx.measureText(name).width), 1);
  ctx.fillStyle = "#2b2622";
  ctx.fillText(name, 0, 2);
  ctx.restore();
  ctx.font = "600 30px system-ui, -apple-system, 'Segoe UI', sans-serif";
  ctx.fillStyle = "#6b5d4c";
  ctx.textAlign = "right";
  ctx.fillText(caption, w - 40, (h - 18) / 2 + 2);
}

const WALL_MAT = {
  frame: matte(CODING_SCENE.moss.frame, { roughness: 0.55 }),
  planter: matte(CODING_SCENE.oak.planks[3], { roughness: 0.55 }),
  leaf: matte(CODING_SCENE.moss.tones[2], { flatShading: true, roughness: 0.8 }),
};

const mossMaterials = new Map<string, MeshStandardMaterial>();
function mossMaterial(width: number, height: number): MeshStandardMaterial {
  const key = `${width.toFixed(2)}x${height.toFixed(2)}`;
  let material = mossMaterials.get(key);
  if (!material) {
    const map = repeated(cachedCanvasTexture("coding:moss", 256, 256, drawMoss), width / 1.1, height / 1.1);
    material = new MeshStandardMaterial({ color: map ? "#ffffff" : CODING_SCENE.moss.base, map, roughness: 1 });
    mossMaterials.set(key, material);
  }
  return material;
}

/**
 * A neighbourhood's living wall, centred on its front face: a white-oak frame
 * round a field of moss and ferns, an oak header carrying the team's name, and
 * an oak planter along its foot with trailing plants.
 */
function LivingWall({ label, caption, accent, width, position }: {
  label: string; caption: string; accent: string; width: number; position: [number, number, number];
}) {
  const header = useMemo(() => {
    const map = ownedCanvasTexture(HEADER.w, HEADER.px, (ctx, w, h) => drawHeader(label, caption, accent, ctx, w, h));
    return new MeshStandardMaterial({ color: map ? "#ffffff" : CODING_SCENE.oak.planks[2], map, roughness: 0.6 });
  }, [label, caption, accent]);
  useEffect(() => () => { header.map?.dispose(); header.dispose(); }, [header]);
  const mossH = WALL_H - HEADER.h - 0.42;
  const headerW = Math.min(width - 0.2, (HEADER.h * HEADER.w) / HEADER.px);
  const trailing = useMemo(() => {
    const count = Math.max(2, Math.floor(width / 0.7));
    return Array.from({ length: count }, (_, i) => -width / 2 + 0.35 + (i * (width - 0.7)) / (count - 1));
  }, [width]);
  return (
    <group position={position}>
      <Box size={[width, WALL_H, 0.12]} position={[0, WALL_H / 2, -0.02]} material={WALL_MAT.frame} />
      <mesh position={[0, 0.36 + mossH / 2, 0.041]} material={mossMaterial(width - 0.14, mossH)} receiveShadow>
        <planeGeometry args={[width - 0.14, mossH]} />
      </mesh>
      <mesh position={[0, WALL_H - HEADER.h / 2 - 0.04, 0.042]} material={header}>
        <planeGeometry args={[headerW, HEADER.h]} />
      </mesh>
      {/* The planter at the wall's foot, with trailing plants spilling over its lip. */}
      <Box size={[width, 0.36, 0.3]} position={[0, 0.18, 0.13]} material={WALL_MAT.planter} />
      {trailing.map((x) => (
        <mesh key={x} position={[x, 0.38, 0.18]} scale={[0.26, 0.14, 0.16]} material={WALL_MAT.leaf} castShadow>
          <icosahedronGeometry args={[1, 0]} />
        </mesh>
      ))}
    </group>
  );
}

// ---------------------------------------------------------------------------
// Neighbourhoods
// ---------------------------------------------------------------------------

const oakMaterials = new Map<string, MeshStandardMaterial>();
function oakMaterial(w: number, d: number): MeshStandardMaterial {
  const key = `${w.toFixed(2)}x${d.toFixed(2)}`;
  let material = oakMaterials.get(key);
  if (!material) {
    const map = repeated(cachedCanvasTexture("coding:oak", 512, 512, drawOak), w / OAK_METRES, d / OAK_METRES);
    material = new MeshStandardMaterial({ color: map ? "#ffffff" : CODING_SCENE.oak.planks[0], map, roughness: 0.55 });
    oakMaterials.set(key, material);
  }
  return material;
}

const EDGE_MAT = matte(CODING_SCENE.oak.seam, { roughness: 0.5 });

/** One workspace as a team neighbourhood: a white-oak island, its living wall with the team's name, and its long tables. */
export function CodingStudio({ dept, agents }: { dept: Department; agents: ReadonlyMap<string, SocietyAgent> }) {
  const t = useT();
  const team = codingTeam(dept.tint);
  const w = dept.maxX - dept.minX, d = dept.maxZ - dept.minZ;
  const cx = (dept.minX + dept.maxX) / 2, cz = (dept.minZ + dept.maxZ) / 2;
  const caption = fill(t("society.office.studio_n"), { number: String(dept.tint + 1).padStart(2, "0") });
  return (
    <group>
      <mesh position={[cx, 0.005, cz]} rotation={[-Math.PI / 2, 0, 0]} material={oakMaterial(w, d)} receiveShadow>
        <planeGeometry args={[w, d]} />
      </mesh>
      {/* A thin darker oak edge round the island. */}
      {([[cx, dept.minZ, w, 0.04], [cx, dept.maxZ, w, 0.04]] as const).map(([x, z, sx, sz]) => (
        <Box key={`z${z}`} size={[sx, 0.008, sz]} position={[x, 0.006, z]} material={EDGE_MAT} cast={false} />
      ))}
      {([[dept.minX, cz, 0.04, d], [dept.maxX, cz, 0.04, d]] as const).map(([x, z, sx, sz]) => (
        <Box key={`x${x}`} size={[sx, 0.008, sz]} position={[x, 0.006, z]} material={EDGE_MAT} cast={false} />
      ))}
      <LivingWall label={dept.label || t("society.office.open_space")} caption={caption} accent={team.accent}
        width={w - 0.4} position={[cx, 0, dept.minZ + 0.1]} />
      <CodingTables desks={dept.desks} agents={agents} team={team} />
    </group>
  );
}
