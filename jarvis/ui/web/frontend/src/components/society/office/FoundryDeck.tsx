/**
 * The Foundry deck: the coding floor's slab, its concourse, the parapet, the
 * data rails and the workspace bays (art/studies/coding-floor-foundry).
 *
 * Steel plates with gold trim on a hull floating in the nebula; the concourse
 * between the bay columns runs to the Core at the spawn point; each bay is a
 * plate framed by a light strip in its signal colour, with a truss gantry and
 * its workspace's name as a holographic sign; and from every bay a data rail
 * runs like a circuit trace to the Core's ring.
 *
 * Purely visual: the only solid part is the gantry, which stands inside the
 * strip along each bay's north edge the layout already walks round.
 */
import { useEffect, useMemo, useRef } from "react";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import {
  AdditiveBlending, CanvasTexture, Color, DoubleSide, MeshBasicMaterial, MeshStandardMaterial, RepeatWrapping, SRGBColorSpace, type Texture,
} from "three";
import { fill, useT } from "@/i18n";
import { cachedCanvasTexture, ownedCanvasTexture } from "./canvasMaterials";
import { Instances, type Placement } from "./Instances";
import { CORE_RING, type FoundryFrame, type Rail } from "./foundryLayout";
import { baySignal, FOUNDRY, glowColour } from "./foundryPalette";
import { GEO, matte } from "./OfficeFurniture";
import type { Department, OfficeLayout } from "./officeLayout";

/** Metres covered by one repeat of the deck plate texture and of a bay's grid. */
const DECK_METRES = 4;
const GRID_METRES = 2;

/** Deterministic pseudo-random numbers, so plates and scuffs never shimmer between loads. */
function lcg(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x1_0000_0000;
  };
}

/**
 * Steel deck plates, 2 m × 1 m, laid like bricks: each plate its own tone with
 * a lit upper bevel and a shadowed lower one, rivets in the corners, a vent
 * grille now and then and fine scuffs. 512 px cover 4 m and wrap on both axes.
 */
function drawDeck(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const { plates, seam } = FOUNDRY.deck;
  const rand = lcg(0xdec4);
  const px = w / DECK_METRES;
  ctx.fillStyle = seam;
  ctx.fillRect(0, 0, w, h);
  const plateW = 2 * px, plateH = 1 * px;
  for (let row = 0; row < DECK_METRES; row += 1) {
    const offset = row % 2 === 0 ? 0 : plateW / 2;
    for (let col = -1; col < DECK_METRES / 2 + 1; col += 1) {
      const x = col * plateW + offset, y = row * plateH;
      const tone = plates[Math.floor(rand() * plates.length)];
      const vent = rand() < 0.12;
      for (const dx of [-w, 0, w]) {
        const x0 = x + dx + 2, y0 = y + 2, pw = plateW - 4, ph = plateH - 4;
        if (x0 > w || x0 + pw < 0) continue;
        ctx.fillStyle = tone;
        ctx.fillRect(x0, y0, pw, ph);
        // Bevel: light along the top and left edges, dark along the bottom and right.
        ctx.fillStyle = "rgba(255,255,255,0.06)";
        ctx.fillRect(x0, y0, pw, 2);
        ctx.fillRect(x0, y0, 2, ph);
        ctx.fillStyle = "rgba(0,0,0,0.28)";
        ctx.fillRect(x0, y0 + ph - 2, pw, 2);
        ctx.fillRect(x0 + pw - 2, y0, 2, ph);
        // Rivets in the corners.
        for (const [rx, ry] of [[8, 8], [pw - 8, 8], [8, ph - 8], [pw - 8, ph - 8]]) {
          ctx.fillStyle = "rgba(0,0,0,0.45)";
          ctx.beginPath(); ctx.arc(x0 + rx + 0.6, y0 + ry + 0.6, 2.4, 0, Math.PI * 2); ctx.fill();
          ctx.fillStyle = "rgba(200,205,215,0.35)";
          ctx.beginPath(); ctx.arc(x0 + rx, y0 + ry, 1.8, 0, Math.PI * 2); ctx.fill();
        }
        if (vent) {
          // A vent grille: slots across the plate's middle.
          ctx.fillStyle = "rgba(0,0,0,0.5)";
          for (let s = 0; s < 9; s += 1) ctx.fillRect(x0 + pw * 0.25 + s * (pw * 0.5 / 9), y0 + ph * 0.3, pw * 0.5 / 18, ph * 0.4);
        }
      }
    }
  }
  // Fine scuffs and grain.
  for (let i = 0; i < 2600; i += 1) {
    ctx.fillStyle = rand() > 0.5 ? "rgba(255,255,255,0.035)" : "rgba(0,0,0,0.12)";
    ctx.fillRect(Math.floor(rand() * w), Math.floor(rand() * h), 1 + Math.floor(rand() * 3), 1);
  }
}

/** A bay's tech grid: dark field, a line every 0.5 m and a brighter one every 2 m (white; the material tints it). */
function drawGrid(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  ctx.fillStyle = "#16181d";
  ctx.fillRect(0, 0, w, h);
  const step = w / (GRID_METRES * 2);
  ctx.fillStyle = "rgba(255,255,255,0.10)";
  for (let i = 0; i < GRID_METRES * 2; i += 1) {
    ctx.fillRect(i * step, 0, 1.5, h);
    ctx.fillRect(0, i * step, w, 1.5);
  }
  ctx.fillStyle = "rgba(255,255,255,0.28)";
  ctx.fillRect(0, 0, 3, h);
  ctx.fillRect(0, 0, w, 3);
  // Small crosses where the major lines meet.
  ctx.fillStyle = "rgba(255,255,255,0.5)";
  ctx.fillRect(0, 0, 12, 3);
  ctx.fillRect(0, 0, 3, 12);
  ctx.fillRect(w - 9, 0, 9, 3);
  ctx.fillRect(0, h - 9, 3, 9);
}

/** The concourse floor: long steel planks along its length with gold chevrons pointing at the Core every 4 m. */
function drawConcourse(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const rand = lcg(0xc0c0);
  ctx.fillStyle = FOUNDRY.deck.seam;
  ctx.fillRect(0, 0, w, h);
  const planks = 8, pw = w / planks;
  for (let i = 0; i < planks; i += 1) {
    ctx.fillStyle = ["#2d3139", "#30353d", "#2a2e35"][Math.floor(rand() * 3)];
    ctx.fillRect(i * pw + 1.5, 0, pw - 3, h);
    ctx.fillStyle = "rgba(255,255,255,0.05)";
    ctx.fillRect(i * pw + 1.5, 0, 1.5, h);
  }
  for (let i = 0; i < 1600; i += 1) {
    ctx.fillStyle = rand() > 0.5 ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.1)";
    ctx.fillRect(Math.floor(rand() * w), Math.floor(rand() * h), 1, 2 + Math.floor(rand() * 4));
  }
}

/** The Core's floor ring: a segmented gold band with tick marks, two thin code-cyan rings inside it. */
function drawCoreRing(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  ctx.clearRect(0, 0, w, h);
  const c = w / 2, scale = w / (CORE_RING.outer * 2);
  const ring = (r: number, width: number, colour: string, dash: number[] = []) => {
    ctx.strokeStyle = colour; ctx.lineWidth = width; ctx.setLineDash(dash);
    ctx.beginPath(); ctx.arc(c, c, r * scale, 0, Math.PI * 2); ctx.stroke();
  };
  ring(CORE_RING.outer - 0.12, 0.16 * scale, FOUNDRY.gold, [0.55 * scale, 0.12 * scale]);
  ring(CORE_RING.outer - 0.32, 0.03 * scale, "rgba(216,174,82,0.7)");
  for (let i = 0; i < 72; i += 1) {
    const a = (i / 72) * Math.PI * 2, r0 = (CORE_RING.outer - 0.5) * scale, r1 = r0 - (i % 6 === 0 ? 0.22 : 0.1) * scale;
    ctx.strokeStyle = "rgba(216,174,82,0.55)"; ctx.lineWidth = 2; ctx.setLineDash([]);
    ctx.beginPath(); ctx.moveTo(c + Math.cos(a) * r0, c + Math.sin(a) * r0); ctx.lineTo(c + Math.cos(a) * r1, c + Math.sin(a) * r1); ctx.stroke();
  }
  ring(CORE_RING.inner + 0.25, 0.04 * scale, FOUNDRY.code);
  ring(CORE_RING.inner + 0.05, 0.02 * scale, "rgba(95,230,255,0.6)", [0.2 * scale, 0.1 * scale]);
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

/** A self-lit part at this luminance (above 1 = past the bloom threshold, whatever its hue); tone mapping stays off. */
function glow(colour: string, luminance = 1.4): MeshBasicMaterial {
  return new MeshBasicMaterial({ color: glowColour(colour, luminance), toneMapped: false });
}

const DECK_MAT = {
  hull: matte(FOUNDRY.hull, { roughness: 0.7, metalness: 0.4 }),
  steel: matte(FOUNDRY.steel, { roughness: 0.45, metalness: 0.6 }),
  steelDark: matte(FOUNDRY.steelDark, { roughness: 0.55, metalness: 0.5 }),
  gold: matte(FOUNDRY.gold, { roughness: 0.3, metalness: 0.85 }),
  glass: new MeshStandardMaterial({ color: "#9fd8ff", transparent: true, opacity: 0.12, roughness: 0.05, metalness: 0.2, side: DoubleSide, depthWrite: false }),
  edgeLight: glow(FOUNDRY.code, 1.15),
  porthole: glow("#ffd9a0", 1.25),
  trim: glow(FOUNDRY.gold, 1.05),
};

/** The parapet's posts along the slab's edge, one every ~2.4 m, and the glass between them. */
const POST_SPACING = 2.4;

function edgePlacements(layout: OfficeLayout) {
  const { minX, maxX, minZ, maxZ } = layout.bounds;
  const inset = 0.2;
  const x0 = minX + inset, x1 = maxX - inset, z0 = minZ + inset, z1 = maxZ - inset;
  const posts: Placement[] = [];
  const sides: [number, number, number, number][] = [[x0, z0, x1, z0], [x1, z0, x1, z1], [x1, z1, x0, z1], [x0, z1, x0, z0]];
  for (const [ax, az, bx, bz] of sides) {
    const len = Math.hypot(bx - ax, bz - az), n = Math.max(1, Math.round(len / POST_SPACING));
    for (let i = 0; i < n; i += 1) {
      const t = i / n;
      posts.push({ position: [ax + (bx - ax) * t, 0.55, az + (bz - az) * t], scale: [0.09, 1.1, 0.09] });
    }
  }
  // Portholes along the hull's south and east faces, where the camera looks at them.
  const portholes: Placement[] = [];
  for (let x = minX + 1; x < maxX - 0.5; x += 1.6) portholes.push({ position: [x, -0.55, maxZ + 0.005], scale: [0.7, 0.12, 0.02] });
  for (let z = minZ + 1; z < maxZ - 0.5; z += 1.6) portholes.push({ position: [maxX + 0.005, -0.55, z], scale: [0.02, 0.12, 0.7] });
  return { posts, portholes, x0, x1, z0, z1 };
}

/** The slab, its hull, the parapet and the concourse: everything of the deck that is not a bay or a rail. */
export function FoundrySlab({ layout, frame, onFloorClick }: {
  layout: OfficeLayout; frame: FoundryFrame | null; onFloorClick: (event: ThreeEvent<MouseEvent>) => void;
}) {
  const { minX, maxX, minZ, maxZ } = layout.bounds;
  const w = maxX - minX, d = maxZ - minZ, cx = (minX + maxX) / 2, cz = (minZ + maxZ) / 2;
  const floor = useMemo(() => {
    const map = repeated(cachedCanvasTexture("foundry:deck", 512, 512, drawDeck), w / DECK_METRES, d / DECK_METRES);
    return new MeshStandardMaterial({ color: map ? "#ffffff" : FOUNDRY.deck.base, map, roughness: 0.62, metalness: 0.35 });
  }, [w, d]);
  const concourse = frame?.concourse ?? null;
  const runway = useMemo(() => {
    if (!concourse) return null;
    const cw = concourse.maxX - concourse.minX, cd = concourse.maxZ - concourse.minZ;
    const map = repeated(cachedCanvasTexture("foundry:concourse", 256, 256, drawConcourse), cw / 3.2, cd / 3.2);
    return new MeshStandardMaterial({ color: map ? "#ffffff" : FOUNDRY.steel, map, roughness: 0.4, metalness: 0.5 });
  }, [concourse]);
  useEffect(() => () => { floor.map?.dispose(); floor.dispose(); }, [floor]);
  useEffect(() => () => { runway?.map?.dispose(); runway?.dispose(); }, [runway]);
  const edge = useMemo(() => edgePlacements(layout), [layout]);
  const glassRun = (from: [number, number], to: [number, number]) => {
    const len = Math.hypot(to[0] - from[0], to[1] - from[1]), angle = Math.atan2(to[1] - from[1], to[0] - from[0]);
    return (
      <group key={`${from}-${to}`} position={[(from[0] + to[0]) / 2, 0, (from[1] + to[1]) / 2]} rotation={[0, -angle, 0]}>
        <mesh geometry={GEO.box} material={DECK_MAT.glass} position={[0, 0.58, 0]} scale={[len, 0.96, 0.025]} />
        <mesh geometry={GEO.box} material={DECK_MAT.gold} position={[0, 1.08, 0]} scale={[len, 0.04, 0.07]} castShadow />
        <mesh geometry={GEO.box} material={DECK_MAT.steelDark} position={[0, 0.05, 0]} scale={[len, 0.1, 0.12]} />
        <mesh geometry={GEO.box} material={DECK_MAT.edgeLight} position={[0, 0.105, 0.065]} scale={[len, 0.018, 0.01]} />
      </group>
    );
  };
  const { x0, x1, z0, z1 } = edge;
  return (
    <group>
      {/* The hull: a thick dark slab with a gold lip and portholes along the faces the camera sees. */}
      <mesh geometry={GEO.box} material={DECK_MAT.hull} position={[cx, -0.7, cz]} scale={[w, 1.4, d]} receiveShadow />
      <mesh geometry={GEO.box} material={DECK_MAT.gold} position={[cx, -0.04, cz]} scale={[w + 0.06, 0.08, d + 0.06]} />
      <mesh geometry={GEO.box} material={DECK_MAT.hull} position={[cx, -1.55, cz]} scale={[w * 0.82, 0.3, d * 0.82]} />
      <Instances geometry={GEO.box} material={DECK_MAT.porthole} items={edge.portholes} cast={false} />
      <mesh position={[cx, 0.001, cz]} rotation={[-Math.PI / 2, 0, 0]} material={floor} receiveShadow onClick={onFloorClick}>
        <planeGeometry args={[w, d]} />
      </mesh>
      {concourse && runway && (
        <group>
          <mesh position={[(concourse.minX + concourse.maxX) / 2, 0.003, (concourse.minZ + concourse.maxZ) / 2]} rotation={[-Math.PI / 2, 0, 0]}
            material={runway} receiveShadow onClick={onFloorClick}>
            <planeGeometry args={[concourse.maxX - concourse.minX, concourse.maxZ - concourse.minZ]} />
          </mesh>
          {/* Gold trim along both edges of the concourse. */}
          {[concourse.minX + 0.05, concourse.maxX - 0.05].map((x) => (
            <mesh key={x} geometry={GEO.box} material={DECK_MAT.trim} position={[x, 0.005, (concourse.minZ + concourse.maxZ) / 2]}
              scale={[0.05, 0.004, concourse.maxZ - concourse.minZ]} />
          ))}
        </group>
      )}
      <Instances geometry={GEO.box} material={DECK_MAT.steel} items={edge.posts} />
      {glassRun([x0, z0], [x1, z0])}
      {glassRun([x1, z0], [x1, z1])}
      {glassRun([x1, z1], [x0, z1])}
      {glassRun([x0, z1], [x0, z0])}
    </group>
  );
}

// ---------------------------------------------------------------------------
// Data rails and the Core's ring
// ---------------------------------------------------------------------------

const railMaterials = new Map<number, MeshBasicMaterial>();
function railMaterial(tint: number): MeshBasicMaterial {
  let m = railMaterials.get(tint);
  if (!m) { m = glow(baySignal(tint), 1.1); railMaterials.set(tint, m); }
  return m;
}

const RAIL_W = 0.06;

/** One rail as flat glowing strips, a via pad where it leaves its bay and a joint at every turn. */
function RailTrace({ rail }: { rail: Rail }) {
  const material = railMaterial(rail.tint);
  const segments = rail.points.slice(1).map((b, i) => {
    const a = rail.points[i];
    const len = Math.hypot(b.x - a.x, b.z - a.z);
    return { key: i, x: (a.x + b.x) / 2, z: (a.z + b.z) / 2, len, angle: Math.atan2(b.z - a.z, b.x - a.x) };
  });
  const start = rail.points[0];
  return (
    <group>
      {segments.map((s) => (
        <mesh key={s.key} geometry={GEO.box} material={material} position={[s.x, 0.006, s.z]} rotation={[0, -s.angle, 0]}
          scale={[s.len + RAIL_W, 0.004, RAIL_W]} />
      ))}
      <mesh geometry={GEO.cyl} material={DECK_MAT.gold} position={[start.x, 0.006, start.z]} scale={[0.13, 0.006, 0.13]} />
      <mesh geometry={GEO.cyl} material={material} position={[start.x, 0.009, start.z]} scale={[0.07, 0.006, 0.07]} />
    </group>
  );
}

/** Every bay's rail and the Core's ring on the floor round the spawn terminal. */
export function FoundryRails({ frame }: { frame: FoundryFrame }) {
  const ringMaterial = useMemo(() => {
    const map = cachedCanvasTexture("foundry:core-ring", 512, 512, drawCoreRing);
    return new MeshBasicMaterial({ map, transparent: true, depthWrite: false, toneMapped: false, color: new Color("#ffffff").multiplyScalar(1.15) });
  }, []);
  useEffect(() => () => ringMaterial.dispose(), [ringMaterial]);
  return (
    <group>
      {frame.rails.map((rail) => <RailTrace key={rail.deptId} rail={rail} />)}
      <mesh position={[frame.core.x, 0.008, frame.core.z]} rotation={[-Math.PI / 2, 0, 0]} material={ringMaterial}>
        <planeGeometry args={[CORE_RING.outer * 2, CORE_RING.outer * 2]} />
      </mesh>
    </group>
  );
}

// ---------------------------------------------------------------------------
// Bays
// ---------------------------------------------------------------------------

const GANTRY = { h: 3.0, post: 0.16, panelH: 1.15, beamH: 0.18 } as const;
const SIGN = { w: 1024, h: 256 } as const;

/** The holographic sign: the workspace's name in tracked capitals, the bay number above it, scan lines over both (white; tinted). */
function drawSign(label: string, caption: string, ctx: CanvasRenderingContext2D, w: number, h: number): void {
  ctx.clearRect(0, 0, w, h);
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  const tracked = (text: string, font: string, y: number, spacing: number, alpha: number) => {
    ctx.font = font;
    const chars = [...text];
    const widths = chars.map((ch) => ctx.measureText(ch).width);
    const total = widths.reduce((s, cw) => s + cw, 0) + spacing * Math.max(0, chars.length - 1);
    const scale = Math.min(1, (w - 80) / total);
    ctx.save();
    ctx.translate(w / 2, y);
    ctx.scale(scale, 1);
    let x = -total / 2;
    ctx.fillStyle = `rgba(255,255,255,${alpha})`;
    chars.forEach((ch, i) => { ctx.fillText(ch, x, 0); x += widths[i] + spacing; });
    ctx.restore();
  };
  const name = label.length > 22 ? `${label.slice(0, 21)}…` : label;
  tracked(caption, "600 30px system-ui, -apple-system, 'Segoe UI', sans-serif", 44, 14, 0.75);
  tracked(name.toUpperCase(), "800 104px system-ui, -apple-system, 'Segoe UI', sans-serif", 144, 8, 1);
  // Bracket corners and an underline, like a heads-up display.
  ctx.fillStyle = "rgba(255,255,255,0.8)";
  for (const [x, y, sx, sy] of [[16, 16, 1, 1], [w - 16, 16, -1, 1], [16, h - 16, 1, -1], [w - 16, h - 16, -1, -1]] as const) {
    ctx.fillRect(x, y, 46 * sx, 4 * sy);
    ctx.fillRect(x, y, 4 * sx, 46 * sy);
  }
  ctx.fillRect(w / 2 - 120, 214, 240, 4);
  // Scan lines.
  ctx.globalCompositeOperation = "destination-out";
  ctx.fillStyle = "rgba(0,0,0,0.35)";
  for (let y = 0; y < h; y += 4) ctx.fillRect(0, y, w, 1.5);
  ctx.globalCompositeOperation = "source-over";
}

/** A soft vertical fade from the projector up into the sign (white; tinted). */
function drawBeam(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const g = ctx.createLinearGradient(0, h, 0, 0);
  g.addColorStop(0, "rgba(255,255,255,0.55)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
  ctx.globalCompositeOperation = "destination-in";
  const sides = ctx.createLinearGradient(0, 0, w, 0);
  sides.addColorStop(0, "rgba(0,0,0,0)");
  sides.addColorStop(0.2, "rgba(0,0,0,1)");
  sides.addColorStop(0.8, "rgba(0,0,0,1)");
  sides.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = sides;
  ctx.fillRect(0, 0, w, h);
}

/** A warm pool of light thrown down in front of a gantry (white centre fading out). */
function drawPool(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const g = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
  g.addColorStop(0, "rgba(255,255,255,0.5)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
}

interface BayKit { strip: MeshBasicMaterial; plate: MeshStandardMaterial; sign: MeshBasicMaterial; beam: MeshBasicMaterial; pool: MeshBasicMaterial; texture: CanvasTexture | null }

/** The gantry with the holographic sign, the plate and its light strip, for one bay. */
function useBayKit(dept: Department, label: string, caption: string): BayKit {
  const colour = baySignal(dept.tint);
  const w = dept.maxX - dept.minX, d = dept.maxZ - dept.minZ;
  const kit = useMemo<BayKit>(() => {
    const plateMap = repeated(cachedCanvasTexture("foundry:grid", 256, 256, drawGrid), w / GRID_METRES, d / GRID_METRES);
    const texture = ownedCanvasTexture(SIGN.w, SIGN.h, (ctx, cw, ch) => drawSign(label, caption, ctx, cw, ch)) as CanvasTexture | null;
    if (texture) texture.colorSpace = SRGBColorSpace;
    const tinted = new Color(colour);
    return {
      strip: glow(colour, 1.15),
      plate: new MeshStandardMaterial({
        color: plateMap ? new Color("#ffffff").lerp(tinted, 0.2) : "#16181d", map: plateMap, roughness: 0.5, metalness: 0.4,
        emissive: tinted, emissiveMap: plateMap, emissiveIntensity: plateMap ? 0.08 : 0,
      }),
      sign: new MeshBasicMaterial({
        map: texture, color: glowColour(colour, 1.5), transparent: true, depthWrite: false, blending: AdditiveBlending,
        toneMapped: false, side: DoubleSide,
      }),
      beam: new MeshBasicMaterial({
        map: cachedCanvasTexture("foundry:beam", 64, 128, drawBeam), color: glowColour(colour, 0.6), transparent: true,
        depthWrite: false, blending: AdditiveBlending, toneMapped: false, side: DoubleSide,
      }),
      pool: new MeshBasicMaterial({
        map: cachedCanvasTexture("foundry:pool", 128, 128, drawPool), color: new Color("#ffe2b8").multiplyScalar(0.45), transparent: true,
        depthWrite: false, blending: AdditiveBlending, toneMapped: false,
      }),
      texture,
    };
  }, [colour, w, d, label, caption]);
  useEffect(() => () => {
    kit.strip.dispose(); kit.plate.map?.dispose(); kit.plate.dispose(); kit.sign.dispose(); kit.beam.dispose(); kit.pool.dispose(); kit.texture?.dispose();
  }, [kit]);
  return kit;
}

const STRIP = 0.045;

/**
 * One workspace as a bay: a grid plate framed by a light strip in its signal
 * colour with gold corner brackets, and on its north edge a truss gantry: a
 * dark back panel with a light slit, two posts, a beam with a downlight, and
 * the workspace's name as a hologram over a gold projector bar.
 */
export function FoundryBay({ dept, animate }: { dept: Department; animate: boolean }) {
  const t = useT();
  const label = dept.label || t("society.office.bay_free");
  const caption = fill(t("society.office.bay_n"), { number: String(dept.tint + 1).padStart(2, "0") });
  const kit = useBayKit(dept, label, caption);
  const w = dept.maxX - dept.minX, d = dept.maxZ - dept.minZ;
  const cx = (dept.minX + dept.maxX) / 2, cz = (dept.minZ + dept.maxZ) / 2;
  const gw = w - 0.4, gz = dept.minZ + 0.11;
  const signW = Math.min(gw * 0.78, 5.2), signH = (signW * SIGN.h) / SIGN.w;
  const signRef = useRef<MeshBasicMaterial>(kit.sign);
  signRef.current = kit.sign;
  const seed = useMemo(() => dept.tint * 1.37 + 0.5, [dept.tint]);
  useFrame(({ clock }) => {
    if (!animate) return;
    // A hologram hums: a slow breath and, now and then, a short flicker.
    const time = clock.elapsedTime + seed;
    const flicker = Math.sin(time * 37) > 0.97 ? 0.55 : 1;
    signRef.current.opacity = (0.86 + Math.sin(time * 1.3) * 0.08) * flicker;
  });
  const corners: [number, number, number, number][] = [
    [dept.minX, dept.minZ, 1, 1], [dept.maxX, dept.minZ, -1, 1], [dept.minX, dept.maxZ, 1, -1], [dept.maxX, dept.maxZ, -1, -1],
  ];
  return (
    <group>
      <mesh position={[cx, 0.005, cz]} rotation={[-Math.PI / 2, 0, 0]} material={kit.plate} receiveShadow>
        <planeGeometry args={[w, d]} />
      </mesh>
      {/* The light strip round the plate. */}
      <mesh geometry={GEO.box} material={kit.strip} position={[cx, 0.008, dept.minZ + STRIP / 2]} scale={[w, 0.006, STRIP]} />
      <mesh geometry={GEO.box} material={kit.strip} position={[cx, 0.008, dept.maxZ - STRIP / 2]} scale={[w, 0.006, STRIP]} />
      <mesh geometry={GEO.box} material={kit.strip} position={[dept.minX + STRIP / 2, 0.008, cz]} scale={[STRIP, 0.006, d]} />
      <mesh geometry={GEO.box} material={kit.strip} position={[dept.maxX - STRIP / 2, 0.008, cz]} scale={[STRIP, 0.006, d]} />
      {corners.map(([x, z, sx, sz]) => (
        <group key={`${x}:${z}`}>
          <mesh geometry={GEO.box} material={DECK_MAT.gold} position={[x + sx * 0.35, 0.012, z + sz * 0.06]} scale={[0.7, 0.012, 0.12]} />
          <mesh geometry={GEO.box} material={DECK_MAT.gold} position={[x + sx * 0.06, 0.012, z + sz * 0.35]} scale={[0.12, 0.012, 0.7]} />
        </group>
      ))}
      {/* Gantry */}
      <group position={[cx, 0, gz]}>
        <mesh geometry={GEO.box} material={DECK_MAT.steelDark} position={[0, GANTRY.panelH / 2, -0.02]} scale={[gw, GANTRY.panelH, 0.1]} castShadow receiveShadow />
        <mesh geometry={GEO.box} material={kit.strip} position={[0, GANTRY.panelH - 0.16, 0.035]} scale={[gw - 0.3, 0.025, 0.01]} />
        <mesh geometry={GEO.box} material={DECK_MAT.gold} position={[0, GANTRY.panelH + 0.015, -0.02]} scale={[gw + 0.02, 0.03, 0.13]} />
        {[-1, 1].map((side) => (
          <group key={side} position={[side * (gw / 2 - GANTRY.post / 2), 0, 0]}>
            <mesh geometry={GEO.box} material={DECK_MAT.steel} position={[0, GANTRY.h / 2, 0]} scale={[GANTRY.post, GANTRY.h, GANTRY.post]} castShadow />
            <mesh geometry={GEO.box} material={kit.strip} position={[-side * (GANTRY.post / 2 + 0.006), GANTRY.h / 2 + 0.3, 0]}
              scale={[0.01, GANTRY.h - 1.2, 0.04]} />
          </group>
        ))}
        <mesh geometry={GEO.box} material={DECK_MAT.steel} position={[0, GANTRY.h, 0]} scale={[gw, GANTRY.beamH, 0.24]} castShadow />
        <mesh geometry={GEO.box} material={DECK_MAT.porthole} position={[0, GANTRY.h - GANTRY.beamH / 2 - 0.006, 0.06]} scale={[gw - 0.4, 0.012, 0.05]} />
        {/* The projector bar, its fan of light, and the sign it throws. */}
        <mesh geometry={GEO.box} material={DECK_MAT.gold} position={[0, GANTRY.panelH + 0.08, 0.06]} scale={[signW * 0.5, 0.05, 0.08]} />
        <mesh position={[0, GANTRY.panelH + 0.1 + 0.3, 0.07]} material={kit.beam}>
          <planeGeometry args={[signW * 0.9, 0.6]} />
        </mesh>
        <mesh position={[0, GANTRY.panelH + 0.18 + signH / 2 + 0.12, 0.08]} material={kit.sign} renderOrder={2}>
          <planeGeometry args={[signW, signH]} />
        </mesh>
      </group>
      {/* The downlight's pool in front of the gantry. */}
      <mesh position={[cx, 0.011, gz + 1.4]} rotation={[-Math.PI / 2, 0, 0]} material={kit.pool}>
        <planeGeometry args={[gw * 0.95, 2.8]} />
      </mesh>
    </group>
  );
}
