/**
 * The ship's finishes. One material per finish for the whole session; parts
 * carry their tint in vertex colours. Textures are drawn on canvases at
 * start-up (no image files): deck plating, wall panels with seams, a grate,
 * carpet and the holodeck grid.
 */
import {
  AdditiveBlending, CanvasTexture, Color, DoubleSide, MeshBasicMaterial, MeshPhysicalMaterial, MeshStandardMaterial, RepeatWrapping,
  SRGBColorSpace, type Material, type Texture,
} from "three";
import type { Finish } from "./geo";
import { withCutaway } from "./cutaway";

function canvas(size: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement("canvas");
  c.width = size; c.height = size;
  const ctx = c.getContext("2d");
  if (!ctx) throw new Error("2d canvas unavailable");
  return [c, ctx];
}

function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}

function tiled(c: HTMLCanvasElement, metres: number, color = true): Texture {
  const t = new CanvasTexture(c);
  t.wrapS = t.wrapT = RepeatWrapping;
  t.repeat.set(1 / metres, 1 / metres);
  t.anisotropy = 8;
  if (color) t.colorSpace = SRGBColorSpace;
  return t;
}

/** Deck plating: 1.2 m plates with recessed seams, a faint wear pattern and rivets at the corners. Tiles every 2.4 m. */
function deckPlates(): { map: Texture; rough: Texture } {
  const [c, ctx] = canvas(512);
  const [rc, rctx] = canvas(512);
  const r = rng(7);
  ctx.fillStyle = "#3a3f47"; ctx.fillRect(0, 0, 512, 512);
  rctx.fillStyle = "#9a9a9a"; rctx.fillRect(0, 0, 512, 512);
  const plate = 256;
  for (let py = 0; py < 2; py += 1) for (let px = 0; px < 2; px += 1) {
    const x = px * plate, y = py * plate;
    const tone = 52 + Math.floor(r() * 10);
    ctx.fillStyle = `rgb(${tone},${tone + 4},${tone + 10})`;
    ctx.fillRect(x + 3, y + 3, plate - 6, plate - 6);
    // Brushed streaks.
    for (let k = 0; k < 90; k += 1) {
      const a = r() * 0.06;
      ctx.fillStyle = `rgba(255,255,255,${a})`;
      ctx.fillRect(x + 4 + r() * (plate - 8), y + 4 + r() * (plate - 8), 30 + r() * 80, 1);
      rctx.fillStyle = `rgba(0,0,0,${a * 1.5})`;
      rctx.fillRect(x + 4 + r() * (plate - 8), y + 4 + r() * (plate - 8), 30 + r() * 80, 1);
    }
    // Inset panel in the middle of each plate.
    ctx.strokeStyle = "rgba(0,0,0,0.35)"; ctx.lineWidth = 2;
    ctx.strokeRect(x + 40, y + 40, plate - 80, plate - 80);
    ctx.strokeStyle = "rgba(255,255,255,0.05)"; ctx.lineWidth = 1;
    ctx.strokeRect(x + 42, y + 42, plate - 84, plate - 84);
    for (const [ox, oy] of [[14, 14], [plate - 14, 14], [14, plate - 14], [plate - 14, plate - 14]]) {
      ctx.fillStyle = "#23262b"; ctx.beginPath(); ctx.arc(x + ox, y + oy, 4, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "rgba(255,255,255,0.12)"; ctx.beginPath(); ctx.arc(x + ox - 1, y + oy - 1, 1.6, 0, Math.PI * 2); ctx.fill();
    }
  }
  // Seams.
  ctx.fillStyle = "#24272d";
  for (let k = 0; k <= 2; k += 1) { ctx.fillRect(k * plate - 1.5, 0, 3, 512); ctx.fillRect(0, k * plate - 1.5, 512, 3); }
  rctx.fillStyle = "#ffffff";
  for (let k = 0; k <= 2; k += 1) { rctx.fillRect(k * plate - 2, 0, 4, 512); rctx.fillRect(0, k * plate - 2, 512, 4); }
  return { map: tiled(c, 4.8), rough: tiled(rc, 4.8, false) };
}

/** Wall panels: 1.2 m wide, a horizontal seam at waist height and another near the top. */
function wallPanels(): Texture {
  const [c, ctx] = canvas(256);
  ctx.fillStyle = "#e9e6e0"; ctx.fillRect(0, 0, 256, 256);
  const g = ctx.createLinearGradient(0, 0, 0, 256);
  g.addColorStop(0, "rgba(0,0,0,0.05)"); g.addColorStop(1, "rgba(0,0,0,0.0)");
  ctx.fillStyle = g; ctx.fillRect(0, 0, 256, 256);
  ctx.fillStyle = "rgba(40,40,46,0.55)";
  ctx.fillRect(0, 0, 3, 256);
  ctx.fillRect(0, 160, 256, 2);
  ctx.fillRect(0, 40, 256, 2);
  ctx.fillStyle = "rgba(255,255,255,0.5)";
  ctx.fillRect(3, 0, 1, 256);
  ctx.fillRect(0, 162, 256, 1);
  const t = new CanvasTexture(c);
  t.wrapS = t.wrapT = RepeatWrapping;
  t.colorSpace = SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}

function carpet(): Texture {
  const [c, ctx] = canvas(256);
  const r = rng(3);
  ctx.fillStyle = "#3b3f4e"; ctx.fillRect(0, 0, 256, 256);
  for (let k = 0; k < 9000; k += 1) {
    const v = r();
    ctx.fillStyle = v > 0.5 ? `rgba(255,255,255,${r() * 0.05})` : `rgba(0,0,0,${r() * 0.08})`;
    ctx.fillRect(r() * 256, r() * 256, 1.5, 1.5);
  }
  // A quiet geometric weave every half metre.
  ctx.strokeStyle = "rgba(255,255,255,0.035)"; ctx.lineWidth = 2;
  for (let k = 0; k < 4; k += 1) { ctx.beginPath(); ctx.moveTo(0, k * 64 + 32); ctx.lineTo(256, k * 64 + 32); ctx.stroke(); }
  return tiled(c, 2);
}

function grate(): Texture {
  const [c, ctx] = canvas(256);
  ctx.fillStyle = "#1d2025"; ctx.fillRect(0, 0, 256, 256);
  ctx.fillStyle = "#4a5059";
  for (let y = 0; y < 256; y += 16) for (let x = 0; x < 256; x += 16) ctx.fillRect(x + 2, y + 2, 12, 12);
  ctx.fillStyle = "#0b0c0f";
  for (let y = 0; y < 256; y += 16) for (let x = 0; x < 256; x += 16) ctx.fillRect(x + 5, y + 5, 6, 6);
  return tiled(c, 0.8);
}

function ceramic(): Texture {
  const [c, ctx] = canvas(256);
  ctx.fillStyle = "#cfd2d6"; ctx.fillRect(0, 0, 256, 256);
  ctx.fillStyle = "rgba(0,0,0,0.18)";
  for (let k = 0; k <= 4; k += 1) { ctx.fillRect(k * 64 - 1, 0, 2, 256); ctx.fillRect(0, k * 64 - 1, 256, 2); }
  return tiled(c, 2.4);
}

function holoGrid(): Texture {
  const [c, ctx] = canvas(256);
  ctx.fillStyle = "#050607"; ctx.fillRect(0, 0, 256, 256);
  ctx.fillStyle = "#e3b341";
  ctx.fillRect(0, 0, 256, 2); ctx.fillRect(0, 0, 2, 256);
  return tiled(c, 1.0);
}

function radial(): Texture {
  const [c, ctx] = canvas(128);
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.35, "rgba(255,255,255,0.45)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  return t;
}

let cache: Map<Finish, Material> | null = null;

export function finishMaterial(finish: Finish): Material {
  if (!cache) cache = buildMaterials();
  const m = cache.get(finish);
  if (!m) throw new Error(`unknown finish ${finish}`);
  return m;
}

function buildMaterials(): Map<Finish, Material> {
  const plates = deckPlates();
  const map = new Map<Finish, Material>();
  map.set("panel", new MeshStandardMaterial({ vertexColors: true, map: wallPanels(), roughness: 0.55, metalness: 0.05, envMapIntensity: 0.6 }));
  map.set("structure", new MeshStandardMaterial({ vertexColors: true, roughness: 0.45, metalness: 0.55, envMapIntensity: 0.9 }));
  map.set("metal", new MeshStandardMaterial({ vertexColors: true, roughness: 0.28, metalness: 0.9, envMapIntensity: 1.2 }));
  map.set("deck", new MeshStandardMaterial({ vertexColors: true, map: plates.map, roughnessMap: plates.rough, roughness: 0.7, metalness: 0.45, envMapIntensity: 0.8 }));
  map.set("carpet", new MeshStandardMaterial({ vertexColors: true, map: carpet(), roughness: 0.95, metalness: 0 }));
  map.set("grate", new MeshStandardMaterial({ vertexColors: true, map: grate(), roughness: 0.6, metalness: 0.7 }));
  map.set("ceramic", new MeshStandardMaterial({ vertexColors: true, map: ceramic(), roughness: 0.35, metalness: 0.0, envMapIntensity: 0.7 }));
  map.set("fabric", new MeshStandardMaterial({ vertexColors: true, roughness: 0.9, metalness: 0 }));
  map.set("glass", new MeshPhysicalMaterial({
    vertexColors: true, roughness: 0.05, metalness: 0, transmission: 0, transparent: true, opacity: 0.22,
    envMapIntensity: 1.4, side: DoubleSide, depthWrite: false,
  }));
  // Light sources: unlit, above 1 so the bloom pass picks them up.
  map.set("glow", new MeshBasicMaterial({ vertexColors: true, toneMapped: false, color: new Color(1.9, 1.9, 1.9) }));
  map.set("glowSoft", new MeshBasicMaterial({ vertexColors: true, toneMapped: false, color: new Color(0.95, 0.95, 0.95) }));
  map.set("screen", new MeshBasicMaterial({ vertexColors: true, toneMapped: false, color: new Color(1.0, 1.0, 1.0) }));
  map.set("holoFloor", new MeshStandardMaterial({ vertexColors: true, map: holoGrid(), emissiveMap: holoGrid(), emissive: new Color(0.62, 0.46, 0.16), roughness: 0.4, metalness: 0.3 }));
  map.set("pool", new MeshBasicMaterial({ vertexColors: true, map: radial(), transparent: true, blending: AdditiveBlending, depthWrite: false }));
  for (const [finish, m] of map) withCutaway(m, finish === "glass" ? 0 : 0.14, finish === "glass" ? 0.2 : 0);
  return map;
}

/** True for finishes that throw a shadow. */
export function castsShadow(finish: Finish): boolean {
  return finish !== "glow" && finish !== "glowSoft" && finish !== "glass" && finish !== "screen" && finish !== "deck" && finish !== "pool"
    && finish !== "carpet" && finish !== "grate" && finish !== "ceramic" && finish !== "holoFloor";
}

export function receivesShadow(finish: Finish): boolean {
  return finish !== "glow" && finish !== "glowSoft" && finish !== "screen" && finish !== "glass" && finish !== "pool";
}
