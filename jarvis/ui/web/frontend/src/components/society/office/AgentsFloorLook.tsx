/**
 * The agents floor's own look — the same company as the coding floor above,
 * but lighter and Scandinavian where that one is walnut and amber: wide
 * pale-oak planks framed by a warm limestone band along the windows with a
 * bronze inlay, a soft warm rim round the slab, and every team studio on a
 * bordered rug in its own colour in front of a pale-oak tambour wall capped
 * in that colour, the team's name lettered in ink on its west half (the
 * studio board hangs in front of the east half).
 *
 * Purely visual. The only solid part is the studio wall, which stays inside
 * the name-wall footprint the layout already walks round.
 */
import { useEffect, useMemo } from "react";
import type { ThreeEvent } from "@react-three/fiber";
import { AdditiveBlending, MeshBasicMaterial, MeshStandardMaterial, RepeatWrapping, Shape, type Texture } from "three";
import { useT } from "@/i18n";
import { cachedCanvasTexture, ownedCanvasTexture } from "./canvasMaterials";
import { Box, matte } from "./OfficeFurniture";
import { studioWallParts } from "./campusLayout";
import type { Department, OfficeLayout } from "./officeLayout";

/** The agents floor's surfaces and light. */
export const AGENTS_SCENE = {
  /** Warm daylight sky and a warm bounce off the oak. */
  sky: "#fff3e4",
  ground: "#8c7c6a",
  slabEdge: "#2e2925",
  rim: "#ffe2bd",
  /** Wide plank light oak: the joint colour and the plank tones. */
  oak: { seam: "#b39571", planks: ["#e4d0ae", "#dcc6a1", "#e9d8ba", "#d8bf98", "#e1caa5", "#ecdcc1"] },
  /** The limestone band along the windows, and its bronze inlay. */
  stone: { base: "#e7e0d4", cloud: ["#ddd5c7", "#efe9df", "#e2dace"], inlay: "#a8865a" },
  /** Tambour oak walls behind each department. */
  tambour: { flute: "#dec7a3", shade: "#b99d77", cap: "#cfb48d" },
  ink: "#2b2926",
  /** Felt clouds over the benches: their linear light and the pool it throws. */
  light: { glow: "#fff0d8", pool: "#ffe1b3" },
} as const;

export type RugWeave = "boucle" | "pinstripe" | "basket" | "chevron" | "windowpane" | "rib";

/** A department's rug: woven field, weave tone, border band, and the felt of its cloud and wall kick band. */
export interface AgentsRug { weave: RugWeave; field: string; thread: string; border: string; felt: string }

/**
 * One rug per department, cycled: linen, sage, clay and friends, woven
 * tone-on-tone, each in the hue family of its zone's desk screens and seats.
 */
export const AGENTS_RUGS: readonly AgentsRug[] = [
  { weave: "boucle", field: "#c9d1bd", thread: "#bac4ac", border: "#86997c", felt: "#9fb094" },
  { weave: "pinstripe", field: "#c8d0d8", thread: "#b9c3cd", border: "#74889c", felt: "#93a4b5" },
  { weave: "basket", field: "#e5dac5", thread: "#d8cab0", border: "#b49a74", felt: "#cbb592" },
  { weave: "chevron", field: "#e6d0c3", thread: "#dbc0b0", border: "#bb7f66", felt: "#cf9d88" },
  { weave: "windowpane", field: "#d2ccdc", thread: "#c4bdd1", border: "#8c84a6", felt: "#aaa3c0" },
  { weave: "rib", field: "#c5d7d0", thread: "#b5cbc3", border: "#6a988c", felt: "#8fb3a9" },
  // Mustard, rose, sky, olive, cocoa and indigo: a full campus of twelve studios never repeats a colour.
  { weave: "chevron", field: "#e6d7a6", thread: "#dccb93", border: "#b8963c", felt: "#cdb05f" },
  { weave: "boucle", field: "#dcc3cb", thread: "#d1b4be", border: "#a8647c", felt: "#bf8a9c" },
  { weave: "pinstripe", field: "#b9cfdc", thread: "#a9c2d1", border: "#4f86a6", felt: "#7ba5bf" },
  { weave: "basket", field: "#cfd3aa", thread: "#c2c798", border: "#868c4a", felt: "#a4a96c" },
  { weave: "rib", field: "#d9c4b4", thread: "#cdb5a3", border: "#9a6a4c", felt: "#b68b70" },
  { weave: "windowpane", field: "#bfc6d9", thread: "#b0b8ce", border: "#5c6aa0", felt: "#8590bb" },
];

/** The rug a department lies on: cycles through the set by the department's tint index. */
export function agentsRug(index: number): AgentsRug {
  const n = AGENTS_RUGS.length;
  return AGENTS_RUGS[((index % n) + n) % n];
}

/** Metres covered by one repeat of the plank tile and of a rug weave. */
const OAK_METRES = 3.2;
const WEAVE_METRES = 1.6;

/** Deterministic pseudo-random numbers, so the planks never shimmer between loads. */
function lcg(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x1_0000_0000;
  };
}

/**
 * Wide oak planks running east–west, 20 cm by 1.0–2.0 m, staggered row by row.
 * Each row's joints are laid round the tile's width, so the tile wraps.
 */
function drawPlanks(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const { seam, planks } = AGENTS_SCENE.oak;
  const rand = lcg(0x0a4e75);
  const rowH = 32;
  ctx.fillStyle = seam;
  ctx.fillRect(0, 0, w, h);
  for (let y = 0; y < h; y += rowH) {
    const start = rand() * w;
    let x = start;
    while (x < start + w) {
      const len = Math.min(160 + rand() * 160, start + w - x);
      const tone = planks[Math.floor(rand() * planks.length)];
      const grainSeed = rand() * 1000, knot = rand();
      // Drawn at its wrapped position and one tile to the left, so it continues past the edge.
      for (const dx of [0, -w]) {
        const px = x + dx;
        if (px > w || px + len < 0) continue;
        ctx.fillStyle = tone;
        ctx.fillRect(px + 1, y + 1, len - 1.5, rowH - 1.5);
        // Long, slightly wavy grain lines and now and then a small knot.
        for (let g = 0; g < 4; g += 1) {
          ctx.fillStyle = g % 2 === 0 ? "rgba(140,104,66,0.10)" : "rgba(255,248,232,0.16)";
          const gy = y + 4 + ((g * 7 + grainSeed) % (rowH - 8));
          for (let sx = 0; sx < len - 4; sx += 16) {
            ctx.fillRect(px + 2 + sx, gy + Math.sin((sx + grainSeed) * 0.05) * 1.4, 16, 0.9);
          }
        }
        if (knot < 0.18) {
          ctx.fillStyle = "rgba(120,86,52,0.28)";
          ctx.beginPath();
          ctx.ellipse(px + len * (0.2 + knot * 3), y + rowH / 2, 4, 2, 0, 0, Math.PI * 2);
          ctx.fill();
        }
      }
      x += len;
    }
  }
}

/** Warm limestone: soft clouds of tone and a fine fossil grain, seamless on both axes. */
function drawStone(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const { base, cloud } = AGENTS_SCENE.stone;
  const rand = lcg(0x5701e);
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, w, h);
  for (let i = 0; i < 36; i += 1) {
    const x = rand() * w, y = rand() * h, r = 18 + rand() * 46;
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
  for (let i = 0; i < 1400; i += 1) {
    ctx.fillStyle = rand() > 0.55 ? "rgba(255,255,255,0.16)" : "rgba(120,104,84,0.10)";
    const s = rand() > 0.9 ? 2 : 1;
    ctx.fillRect(Math.floor(rand() * w), Math.floor(rand() * h), s, s);
  }
}

/** A cached base texture, cloned per surface with its own repeat. */
export function repeated(base: Texture | null, repeatX: number, repeatZ: number): Texture | null {
  if (!base) return null;
  const map = base.clone();
  map.wrapS = map.wrapT = RepeatWrapping;
  map.anisotropy = 8;
  map.repeat.set(repeatX, repeatZ);
  map.needsUpdate = true;
  return map;
}

/** A limestone surface `along` × `across` metres, one repeat of the stone per 3 m. The caller owns (and disposes) it. */
export function limestone(along: number, across: number): MeshStandardMaterial {
  const map = repeated(cachedCanvasTexture("agents:stone", 256, 256, drawStone), along / 3, across / 3);
  return new MeshStandardMaterial({ color: map ? "#ffffff" : AGENTS_SCENE.stone.base, map, roughness: 0.45 });
}

/** Width of the limestone band along the slab's edge, and of its bronze inlay. */
const BAND_M = 1.35;
const INLAY_M = 0.03;

/**
 * The slab and floor of the agents floor: wide pale-oak planks, framed by a
 * limestone band with a bronze inlay along the windows, a warm stone edge and
 * a soft warm rim. The floor's edges (window walls, balustrades) are the
 * building shell's.
 */
export function AgentsSlab({ layout, onFloorClick }: { layout: OfficeLayout; onFloorClick: (event: ThreeEvent<MouseEvent>) => void }) {
  const { minX, maxX, minZ, maxZ } = layout.bounds;
  const w = maxX - minX, d = maxZ - minZ, cx = (minX + maxX) / 2, cz = (minZ + maxZ) / 2;
  const innerW = w - BAND_M * 2, innerD = d - BAND_M * 2;
  const floor = useMemo(() => {
    const map = repeated(cachedCanvasTexture("agents:planks", 512, 512, drawPlanks), w / OAK_METRES, d / OAK_METRES);
    return new MeshStandardMaterial({ color: map ? "#ffffff" : AGENTS_SCENE.oak.planks[0], map, roughness: 0.55 });
  }, [w, d]);
  // The band's strips: north and south run the full width, east and west fit between them; one repeat per 3 m.
  const band = useMemo(() => {
    const base = cachedCanvasTexture("agents:stone", 256, 256, drawStone);
    const strip = (along: number, across: number) => {
      const map = repeated(base, along / 3, across / 3);
      return new MeshStandardMaterial({ color: map ? "#ffffff" : AGENTS_SCENE.stone.base, map, roughness: 0.45 });
    };
    return { ns: strip(w, BAND_M), ew: strip(BAND_M, innerD) };
  }, [w, innerD]);
  const inlay = useMemo(() => matte(AGENTS_SCENE.stone.inlay, { roughness: 0.4, metalness: 0.45 }), []);
  const edge = useMemo(() => matte(AGENTS_SCENE.slabEdge, { roughness: 0.75 }), []);
  const rim = useMemo(() => new MeshStandardMaterial({
    color: AGENTS_SCENE.rim, emissive: AGENTS_SCENE.rim, emissiveIntensity: 0.9, roughness: 0.4, toneMapped: false,
  }), []);
  useEffect(() => () => {
    for (const m of [floor, band.ns, band.ew]) { m.map?.dispose(); m.dispose(); }
    inlay.dispose(); edge.dispose(); rim.dispose();
  }, [floor, band, inlay, edge, rim]);
  const glow = 0.05;
  return (
    <group>
      <Box size={[w, 0.6, d]} position={[cx, -0.3, cz]} material={edge} cast={false} />
      {/* The rim runs just below the floor's edge on all four sides. */}
      <Box size={[w + glow, glow, glow]} position={[cx, -0.06, minZ]} material={rim} cast={false} />
      <Box size={[w + glow, glow, glow]} position={[cx, -0.06, maxZ]} material={rim} cast={false} />
      <Box size={[glow, glow, d + glow]} position={[minX, -0.06, cz]} material={rim} cast={false} />
      <Box size={[glow, glow, d + glow]} position={[maxX, -0.06, cz]} material={rim} cast={false} />
      <mesh position={[cx, 0.001, cz]} rotation={[-Math.PI / 2, 0, 0]} material={floor} receiveShadow onClick={onFloorClick}>
        <planeGeometry args={[w, d]} />
      </mesh>
      {[minZ + BAND_M / 2, maxZ - BAND_M / 2].map((z) => (
        <mesh key={`ns${z}`} position={[cx, 0.002, z]} rotation={[-Math.PI / 2, 0, 0]} material={band.ns} receiveShadow onClick={onFloorClick}>
          <planeGeometry args={[w, BAND_M]} />
        </mesh>
      ))}
      {[minX + BAND_M / 2, maxX - BAND_M / 2].map((x) => (
        <mesh key={`ew${x}`} position={[x, 0.002, cz]} rotation={[-Math.PI / 2, 0, 0]} material={band.ew} receiveShadow onClick={onFloorClick}>
          <planeGeometry args={[BAND_M, innerD]} />
        </mesh>
      ))}
      {/* The bronze inlay where oak meets stone. */}
      <Box size={[innerW + INLAY_M, 0.004, INLAY_M]} position={[cx, 0.002, minZ + BAND_M]} material={inlay} cast={false} />
      <Box size={[innerW + INLAY_M, 0.004, INLAY_M]} position={[cx, 0.002, maxZ - BAND_M]} material={inlay} cast={false} />
      <Box size={[INLAY_M, 0.004, innerD]} position={[minX + BAND_M, 0.002, cz]} material={inlay} cast={false} />
      <Box size={[INLAY_M, 0.004, innerD]} position={[maxX - BAND_M, 0.002, cz]} material={inlay} cast={false} />
    </group>
  );
}

// ---------------------------------------------------------------------------
// Rugs
// ---------------------------------------------------------------------------

/** A tone-on-tone weave, 256 px per WEAVE_METRES, seamless on both axes. */
function drawWeave(rug: AgentsRug, ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const rand = lcg(rug.weave.length * 977 + rug.field.charCodeAt(1));
  ctx.fillStyle = rug.field;
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = rug.thread;
  ctx.strokeStyle = rug.thread;
  switch (rug.weave) {
    case "boucle":
      // Small loops of yarn scattered evenly.
      ctx.lineWidth = 1.6;
      for (let i = 0; i < 520; i += 1) {
        const x = rand() * w, y = rand() * h;
        ctx.beginPath();
        ctx.arc(x, y, 1.6 + rand() * 1.6, 0, Math.PI * 2);
        ctx.stroke();
      }
      break;
    case "pinstripe":
      for (let y = 0; y < h; y += 16) ctx.fillRect(0, y, w, 3);
      ctx.fillStyle = "rgba(255,255,255,0.18)";
      for (let y = 8; y < h; y += 32) ctx.fillRect(0, y, w, 1.5);
      break;
    case "basket":
      // 32-px squares of three threads, alternating direction like a basketweave.
      for (let y = 0; y < h; y += 32) {
        for (let x = 0; x < w; x += 32) {
          const across = ((x + y) / 32) % 2 === 0;
          for (let k = 0; k < 3; k += 1) {
            if (across) ctx.fillRect(x + 2, y + 4 + k * 10, 28, 5);
            else ctx.fillRect(x + 4 + k * 10, y + 2, 5, 28);
          }
        }
      }
      break;
    case "chevron":
      ctx.lineWidth = 6;
      for (let y = -32; y < h + 32; y += 32) {
        ctx.beginPath();
        for (let x = 0; x <= w; x += 32) ctx.lineTo(x, y + ((x / 32) % 2 === 0 ? 0 : 16));
        ctx.stroke();
      }
      break;
    case "windowpane":
      for (let at = 0; at < w; at += 64) { ctx.fillRect(at, 0, 3, h); ctx.fillRect(0, at, w, 3); }
      ctx.fillStyle = "rgba(255,255,255,0.14)";
      for (let at = 32; at < w; at += 64) { ctx.fillRect(at, 0, 1.5, h); ctx.fillRect(0, at, w, 1.5); }
      break;
    case "rib":
      // Soft raised ribs: a shaded band per 16 px.
      for (let x = 0; x < w; x += 16) {
        const g = ctx.createLinearGradient(x, 0, x + 16, 0);
        g.addColorStop(0, "rgba(255,255,255,0.20)");
        g.addColorStop(0.5, `${rug.thread}00`);
        g.addColorStop(1, "rgba(60,50,40,0.10)");
        ctx.fillStyle = g;
        ctx.fillRect(x, 0, 16, h);
      }
      break;
  }
  // A fine fibre grain over every weave.
  for (let i = 0; i < 1600; i += 1) {
    ctx.fillStyle = rand() > 0.5 ? "rgba(255,255,255,0.10)" : "rgba(60,50,40,0.06)";
    ctx.fillRect(Math.floor(rand() * w), Math.floor(rand() * h), 1, 1);
  }
}

/** Rug materials, one per style. Shape UVs are in metres, so one material fits every rug size. */
const rugMaterials = new Map<AgentsRug, { field: MeshStandardMaterial; border: MeshStandardMaterial; line: MeshStandardMaterial; felt: MeshStandardMaterial }>();
function rugKit(rug: AgentsRug) {
  let kit = rugMaterials.get(rug);
  if (!kit) {
    const base = cachedCanvasTexture(`agents:weave:${rug.weave}:${rug.field}`, 256, 256, (ctx, w, h) => drawWeave(rug, ctx, w, h));
    const map = repeated(base, 1 / WEAVE_METRES, 1 / WEAVE_METRES);
    kit = {
      field: new MeshStandardMaterial({ color: map ? "#ffffff" : rug.field, map, roughness: 0.97 }),
      border: matte(rug.border, { roughness: 1 }),
      line: matte("#f3ede2", { roughness: 1 }),
      felt: matte(rug.felt, { roughness: 1 }),
    };
    rugMaterials.set(rug, kit);
  }
  return kit;
}

/** A flat rounded rectangle in the XY plane, laid on the floor by its mesh's rotation. */
function roundedRect(w: number, d: number, r: number): Shape {
  const x = -w / 2, y = -d / 2;
  const shape = new Shape();
  shape.moveTo(x + r, y);
  shape.lineTo(x + w - r, y);
  shape.quadraticCurveTo(x + w, y, x + w, y + r);
  shape.lineTo(x + w, y + d - r);
  shape.quadraticCurveTo(x + w, y + d, x + w - r, y + d);
  shape.lineTo(x + r, y + d);
  shape.quadraticCurveTo(x, y + d, x, y + d - r);
  shape.lineTo(x, y + r);
  shape.quadraticCurveTo(x, y, x + r, y);
  return shape;
}

// ---------------------------------------------------------------------------
// Department wall
// ---------------------------------------------------------------------------

const WALL_H = 1.9;
const LETTERS = { w: 1024, h: 224 } as const;

/** Tambour: half-round oak flutes, four per 64-px repeat, lit from the upper left. */
function drawTambour(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const { flute, shade } = AGENTS_SCENE.tambour;
  for (let x = 0; x < w; x += 16) {
    const g = ctx.createLinearGradient(x, 0, x + 16, 0);
    g.addColorStop(0, shade);
    g.addColorStop(0.2, flute);
    g.addColorStop(0.45, "#f1e2c8");
    g.addColorStop(0.8, flute);
    g.addColorStop(1, shade);
    ctx.fillStyle = g;
    ctx.fillRect(x, 0, 16, h);
  }
  // A faint vertical grain.
  ctx.fillStyle = "rgba(140,104,66,0.08)";
  for (let x = 3; x < w; x += 7) ctx.fillRect(x, 0, 0.8, h);
}

const tambourMaterials = new Map<string, MeshStandardMaterial>();
/** Flutes about 4 cm wide: one texture repeat per 16 cm of wall. */
function tambourMaterial(width: number): MeshStandardMaterial {
  const key = width.toFixed(2);
  let material = tambourMaterials.get(key);
  if (!material) {
    const map = repeated(cachedCanvasTexture("agents:tambour", 64, 64, drawTambour), width / 0.16, 1);
    material = new MeshStandardMaterial({ color: map ? "#ffffff" : AGENTS_SCENE.tambour.flute, map, roughness: 0.7 });
    tambourMaterials.set(key, material);
  }
  return material;
}

/** Ink letters on a transparent ground: the studio's name, a short rule in its colour and a caption under it. */
function drawLetters(label: string, caption: string, accent: string, ctx: CanvasRenderingContext2D, w: number, h: number): void {
  ctx.clearRect(0, 0, w, h);
  const tracked = (text: string, font: string, y: number, spacing: number, fill: string) => {
    ctx.font = font;
    const chars = [...text];
    const widths = chars.map((ch) => ctx.measureText(ch).width);
    const total = widths.reduce((sum, cw) => sum + cw, 0) + spacing * Math.max(0, chars.length - 1);
    // Squeeze a long name to fit rather than cutting it off.
    const scale = Math.min(1, (w - 60) / total);
    ctx.save();
    ctx.translate(w / 2, y);
    ctx.scale(scale, 1);
    let x = -total / 2;
    ctx.fillStyle = fill;
    chars.forEach((ch, i) => {
      ctx.fillText(ch, x, 0);
      x += widths[i] + spacing;
    });
    ctx.restore();
  };
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  const name = label.length > 24 ? `${label.slice(0, 23)}…` : label;
  tracked(name, "600 104px Inter, system-ui, -apple-system, 'Segoe UI', sans-serif", 84, 4, AGENTS_SCENE.ink);
  ctx.fillStyle = accent;
  ctx.fillRect(w / 2 - 44, 154, 88, 5);
  tracked(caption.toLocaleUpperCase(), "600 32px Inter, system-ui, -apple-system, 'Segoe UI', sans-serif", 194, 10, "#5d564e");
}

/**
 * A studio's lettering. A team's name is whatever the person typed, so this is never cached by its text: the wall
 * that shows it owns the material and its texture, and disposes both when the name changes or the studio goes.
 */
function letterMaterial(label: string, caption: string, accent: string): MeshStandardMaterial {
  const map = ownedCanvasTexture(LETTERS.w, LETTERS.h, (ctx, w, h) => drawLetters(label, caption, accent, ctx, w, h));
  return new MeshStandardMaterial({ color: map ? "#ffffff" : AGENTS_SCENE.ink, map, transparent: true, alphaTest: 0.3, roughness: 0.6 });
}

let washCache: MeshBasicMaterial | null = null;
/** Soft warm light grazing down the flutes from the strip under the cap. */
function washMaterial(): MeshBasicMaterial {
  if (!washCache) {
    const map = cachedCanvasTexture("agents:wash", 64, 128, (ctx, w, h) => {
      const g = ctx.createLinearGradient(0, 0, 0, h);
      g.addColorStop(0, "rgba(255,236,206,0.9)");
      g.addColorStop(1, "rgba(255,236,206,0)");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
      ctx.globalCompositeOperation = "destination-in";
      const sides = ctx.createLinearGradient(0, 0, w, 0);
      sides.addColorStop(0, "rgba(0,0,0,0)");
      sides.addColorStop(0.08, "rgba(0,0,0,1)");
      sides.addColorStop(0.92, "rgba(0,0,0,1)");
      sides.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = sides;
      ctx.fillRect(0, 0, w, h);
    });
    washCache = new MeshBasicMaterial({ color: "#ffffff", map, transparent: true, opacity: map ? 0.3 : 0, blending: AdditiveBlending, depthWrite: false });
  }
  return washCache;
}

const WALL_MAT = {
  cap: matte(AGENTS_SCENE.tambour.cap, { roughness: 0.55 }),
  strip: new MeshStandardMaterial({ color: AGENTS_SCENE.light.glow, emissive: AGENTS_SCENE.light.glow, emissiveIntensity: 1.4, toneMapped: false }),
};

/**
 * A studio's name wall, centred on its front face: a pale-oak tambour panel
 * under a cap in the studio's colour with a warm light strip, a felt kick
 * band in the same colour, and the name in ink letters on the west half.
 */
function StudioWall({ label, caption, width, nameX, position, rug }: {
  label: string; caption: string; width: number; nameX: number; position: [number, number, number]; rug: AgentsRug;
}) {
  const kit = rugKit(rug);
  const plateW = Math.min(3.0, width / 2 - 0.5);
  const plateH = (plateW * LETTERS.h) / LETTERS.w;
  const accent = rug.border;
  const letters = useMemo(() => letterMaterial(label, caption, accent), [label, caption, accent]);
  useEffect(() => () => { letters.map?.dispose(); letters.dispose(); }, [letters]);
  return (
    <group position={position}>
      <Box size={[width, WALL_H, 0.1]} position={[0, WALL_H / 2, -0.02]} material={WALL_MAT.cap} />
      <mesh position={[0, WALL_H / 2 + 0.04, 0.031]} material={tambourMaterial(width - 0.06)} receiveShadow>
        <planeGeometry args={[width - 0.06, WALL_H - 0.16]} />
      </mesh>
      <Box size={[width - 0.06, 0.12, 0.02]} position={[0, 0.08, 0.04]} material={kit.felt} cast={false} />
      {/* The cap wears the studio's colour, so a team reads from across the campus. */}
      <Box size={[width + 0.04, 0.09, 0.16]} position={[0, WALL_H + 0.045, 0]} material={kit.border} />
      {/* The light strip tucked under the cap, washing down the flutes. */}
      <Box size={[width - 0.2, 0.012, 0.02]} position={[0, WALL_H - 0.012, 0.06]} material={WALL_MAT.strip} cast={false} />
      <mesh position={[0, WALL_H - 0.42, 0.035]} material={washMaterial()}>
        <planeGeometry args={[width - 0.1, 0.8]} />
      </mesh>
      <mesh position={[nameX, 1.3, 0.04]} material={letters}>
        <planeGeometry args={[plateW, plateH]} />
      </mesh>
    </group>
  );
}

/** One team studio's ground and name wall: a bordered, rounded rug in the studio's colour and the tambour wall. */
export function AgentsDepartment({ dept }: { dept: Department }) {
  const t = useT();
  const rug = agentsRug(dept.tint);
  const kit = rugKit(rug);
  const w = dept.maxX - dept.minX, d = dept.maxZ - dept.minZ;
  const cx = (dept.minX + dept.maxX) / 2, cz = (dept.minZ + dept.maxZ) / 2;
  const shapes = useMemo(() => ({
    border: roundedRect(w - 0.1, d - 0.1, 0.4),
    line: roundedRect(w - 0.36, d - 0.36, 0.28),
    field: roundedRect(w - 0.44, d - 0.44, 0.24),
  }), [w, d]);
  // The pool has no team name: the wall says what it is.
  const pool = dept.teamId === null || dept.teamId === undefined;
  return (
    <group>
      <mesh position={[cx, 0.005, cz]} rotation={[-Math.PI / 2, 0, 0]} material={kit.border} receiveShadow>
        <shapeGeometry args={[shapes.border, 6]} />
      </mesh>
      <mesh position={[cx, 0.006, cz]} rotation={[-Math.PI / 2, 0, 0]} material={kit.line} receiveShadow>
        <shapeGeometry args={[shapes.line, 6]} />
      </mesh>
      <mesh position={[cx, 0.007, cz]} rotation={[-Math.PI / 2, 0, 0]} material={kit.field} receiveShadow>
        <shapeGeometry args={[shapes.field, 6]} />
      </mesh>
      <StudioWall label={dept.label || t("society.office.studio_pool")}
        caption={t(pool ? "society.office.studio_sign_pool" : "society.office.studio_sign_team")}
        width={w - 0.4} nameX={studioWallParts(dept).nameX - cx} position={[cx, 0, dept.minZ + 0.1]} rug={rug} />
    </group>
  );
}
