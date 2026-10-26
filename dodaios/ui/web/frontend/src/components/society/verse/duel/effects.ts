/**
 * The duel's light and fire, all pooled (nothing is allocated per shot):
 *
 * - bolts: a white-hot core inside a coloured glow with a tapering trail,
 *   bright enough (HDR) for the eye view's bloom and drawn additively so
 *   they read on the low tier too; the person's bolts amber, the opponent's
 *   red, a parried bolt nearly white and thicker;
 * - sparks: short-lived embers with gravity at impacts, hits and blocks;
 * - flashes: camera-facing glows for muzzle flashes, impacts and parries;
 * - scorch marks: dark burns on walls and floor that glow hot for a moment
 *   and fade after a while;
 * - steam: a venting blaster's plume.
 *
 * Coordinates are world (the arena's plus the deck floor height).
 */
import {
  AdditiveBlending, BufferAttribute, BufferGeometry, CanvasTexture, Color, CylinderGeometry, DoubleSide, Group, Mesh,
  MeshBasicMaterial, NormalBlending, PlaneGeometry, Points, PointsMaterial, Quaternion, ShaderMaterial, Sprite, SpriteMaterial,
  Vector3, type Texture,
} from "three";
import type { BoltView } from "../combat/view";
import { BOLT_COLOURS } from "./blaster";

/** HDR gain of the glowing parts (the bloom's threshold is 1.5). */
const CORE_GAIN = 14;
const GLOW_GAIN = 3.2;
const TRAIL_M = 3.2;

export function radialTexture(stops: readonly [number, string][], size = 64): Texture {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    for (const [at, colour] of stops) g.addColorStop(at, colour);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
  }
  return new CanvasTexture(canvas);
}

/** A scorch: a dark, ragged burn. */
function scorchTexture(): Texture {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const g = ctx.createRadialGradient(size / 2, size / 2, 2, size / 2, size / 2, size / 2);
    g.addColorStop(0, "rgba(0,0,0,0.95)");
    g.addColorStop(0.35, "rgba(8,6,5,0.8)");
    g.addColorStop(0.7, "rgba(12,10,9,0.3)");
    g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
    // Ragged streaks outward.
    let seed = 7;
    const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    ctx.strokeStyle = "rgba(0,0,0,0.5)";
    for (let i = 0; i < 18; i++) {
      const a = rnd() * Math.PI * 2;
      const r0 = size * 0.12;
      const r1 = size * (0.3 + rnd() * 0.18);
      ctx.lineWidth = 1 + rnd() * 3;
      ctx.beginPath();
      ctx.moveTo(size / 2 + Math.cos(a) * r0, size / 2 + Math.sin(a) * r0);
      ctx.lineTo(size / 2 + Math.cos(a) * r1, size / 2 + Math.sin(a) * r1);
      ctx.stroke();
    }
  }
  return new CanvasTexture(canvas);
}

const TRAIL_VERTEX = /* glsl */ `
varying float vAlong;
void main() {
  vAlong = uv.y;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;
const TRAIL_FRAGMENT = /* glsl */ `
uniform vec3 colour;
uniform float opacity;
varying float vAlong;
void main() {
  // MSAA can sample the varying just outside the triangle; pow of a negative is NaN, which bloom spreads over the frame.
  float a = pow(clamp(vAlong, 0.0, 1.0), 1.6) * opacity;
  gl_FragColor = vec4(colour * a, a);
}`;

interface BoltSlot {
  group: Group;
  core: Mesh;
  glow: Mesh;
  trail: Mesh<CylinderGeometry, ShaderMaterial>;
  coreMat: MeshBasicMaterial;
  glowMat: MeshBasicMaterial;
  id: number;
  kind: string;
  /** Where the bolt's current leg began (its muzzle or the shield that turned it). */
  ox: number;
  oy: number;
  oz: number;
  seen: boolean;
}

export class BoltPool {
  readonly group = new Group();
  private readonly slots: BoltSlot[] = [];
  private readonly byId = new Map<number, BoltSlot>();
  private readonly coreGeo = new CylinderGeometry(0.022, 0.022, 1, 8, 1).rotateX(Math.PI / 2);
  private readonly glowGeo = new CylinderGeometry(0.075, 0.075, 1, 10, 1, true).rotateX(Math.PI / 2);
  // The trail: a cone from the bolt (z 0, wide) back to a point (z -1), uv.y 1 at the front.
  private readonly trailGeo = new CylinderGeometry(0.05, 0.0, 1, 8, 1, true).rotateX(Math.PI / 2).translate(0, 0, -0.5);
  private readonly target = new Vector3();

  constructor(size = 48) {
    this.group.name = "DuelBolts";
    for (let i = 0; i < size; i++) {
      const coreMat = new MeshBasicMaterial({ color: 0xffffff, toneMapped: true });
      const glowMat = new MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.55, blending: AdditiveBlending, depthWrite: false, side: DoubleSide });
      const trailMat = new ShaderMaterial({
        uniforms: { colour: { value: new Color() }, opacity: { value: 0.9 } },
        vertexShader: TRAIL_VERTEX, fragmentShader: TRAIL_FRAGMENT,
        transparent: true, depthWrite: false, blending: AdditiveBlending, side: DoubleSide,
      });
      const group = new Group();
      const core = new Mesh(this.coreGeo, coreMat);
      const glow = new Mesh(this.glowGeo, glowMat);
      const trail = new Mesh(this.trailGeo, trailMat);
      for (const m of [core, glow, trail]) { m.frustumCulled = false; m.renderOrder = 40; group.add(m); }
      group.visible = false;
      this.group.add(group);
      this.slots.push({ group, core, glow, trail, coreMat, glowMat, id: -1, kind: "", ox: 0, oy: 0, oz: 0, seen: false });
    }
  }

  /** Show this frame's bolts (`floorY` lifts arena heights onto the deck). */
  update(bolts: readonly BoltView[], mySlot: number, floorY: number): void {
    for (const s of this.slots) s.seen = false;
    for (const b of bolts) {
      let s = this.byId.get(b.id);
      if (!s) {
        s = this.slots.find((x) => x.id < 0);
        if (!s) continue;
        s.id = b.id;
        s.kind = "";
        this.byId.set(b.id, s);
        // The leg starts where the bolt was fired: back along its flight by its age.
        const back = (b.speed * b.ageTicks) / 60;
        s.ox = b.x - b.dx * back;
        s.oy = b.y - b.dy * back;
        s.oz = b.z - b.dz * back;
      }
      s.seen = true;
      if (s.kind !== b.kind) {
        // Turned by a shield: the new leg starts here.
        if (s.kind) { s.ox = b.x; s.oy = b.y; s.oz = b.z; }
        s.kind = b.kind;
        const colour = b.kind === "parry" ? BOLT_COLOURS.parry : b.owner === mySlot ? BOLT_COLOURS.own : BOLT_COLOURS.foe;
        const tint = b.kind === "parry" ? (b.owner === mySlot ? BOLT_COLOURS.own : BOLT_COLOURS.foe) : colour;
        s.coreMat.color.copy(colour).lerp(new Color(1, 1, 1), 0.55).multiplyScalar(CORE_GAIN * (b.kind === "parry" ? 1.4 : 1));
        s.glowMat.color.copy(tint).multiplyScalar(GLOW_GAIN * (b.kind === "deflect" ? 0.6 : 1));
        s.trail.material.uniforms.colour.value.copy(tint).multiplyScalar(b.kind === "parry" ? 2.6 : 1.8);
        const thick = b.kind === "parry" ? 1.5 : b.kind === "deflect" ? 0.8 : 1;
        s.core.scale.set(thick, thick, 1);
        s.glow.scale.set(thick, thick, 1);
      }
      const y = b.y + floorY;
      s.group.visible = true;
      s.group.position.set(b.x, y, b.z);
      this.target.set(b.x + b.dx, y + b.dy, b.z + b.dz);
      s.group.lookAt(this.target);
      // The core is a 1.2 m streak behind the bolt's head, never longer than the leg flown so far.
      const flown = Math.hypot(b.x - s.ox, b.y + floorY - (s.oy + floorY), b.z - s.oz);
      const coreLen = Math.max(0.15, Math.min(1.2, flown));
      s.core.scale.z = coreLen;
      s.core.position.z = -coreLen / 2;
      s.glow.scale.z = coreLen * 1.1;
      s.glow.position.z = -coreLen / 2;
      s.trail.scale.z = Math.max(0.2, Math.min(TRAIL_M, flown));
    }
    for (const s of this.slots) {
      if (s.seen || s.id < 0) continue;
      this.byId.delete(s.id);
      s.id = -1;
      s.group.visible = false;
    }
  }

  clear(): void {
    for (const s of this.slots) { s.id = -1; s.group.visible = false; }
    this.byId.clear();
  }

  dispose(): void {
    this.coreGeo.dispose();
    this.glowGeo.dispose();
    this.trailGeo.dispose();
    for (const s of this.slots) { s.coreMat.dispose(); s.glowMat.dispose(); s.trail.material.dispose(); }
  }
}

/** Embers with gravity: impact sparks, hit sparks, the shield's crackle. */
export class Sparks {
  readonly points: Points;
  private readonly pos: Float32Array;
  private readonly col: Float32Array;
  private readonly vel: Float32Array;
  private readonly life: Float32Array;
  private readonly base: Float32Array;
  private next = 0;
  private readonly tex: Texture;

  constructor(private readonly size = 600) {
    this.pos = new Float32Array(size * 3);
    this.col = new Float32Array(size * 3);
    this.vel = new Float32Array(size * 3);
    this.life = new Float32Array(size);
    this.base = new Float32Array(size * 3);
    for (let i = 0; i < size; i++) this.pos[i * 3 + 1] = -1000;
    const geo = new BufferGeometry();
    geo.setAttribute("position", new BufferAttribute(this.pos, 3));
    geo.setAttribute("color", new BufferAttribute(this.col, 3));
    this.tex = radialTexture([[0, "rgba(255,255,255,1)"], [0.3, "rgba(255,255,255,0.8)"], [1, "rgba(255,255,255,0)"]], 32);
    const mat = new PointsMaterial({
      size: 0.05, map: this.tex, vertexColors: true, transparent: true, depthWrite: false, blending: AdditiveBlending, sizeAttenuation: true,
    });
    this.points = new Points(geo, mat);
    this.points.frustumCulled = false;
    this.points.renderOrder = 41;
  }

  /** `count` sparks from (x, y, z) around the normal (or in all directions), coloured `colour` × gain. */
  burst(x: number, y: number, z: number, nx: number, ny: number, nz: number, count: number, colour: Color, speed = 4, spread = 0.9, gain = 6): void {
    for (let k = 0; k < count; k++) {
      const i = this.next;
      this.next = (this.next + 1) % this.size;
      let vx = nx + (Math.random() * 2 - 1) * spread;
      let vy = ny + (Math.random() * 2 - 1) * spread + 0.3;
      let vz = nz + (Math.random() * 2 - 1) * spread;
      const l = Math.hypot(vx, vy, vz) || 1;
      const s = speed * (0.35 + Math.random() * 0.9);
      vx = (vx / l) * s; vy = (vy / l) * s; vz = (vz / l) * s;
      this.pos[i * 3] = x; this.pos[i * 3 + 1] = y; this.pos[i * 3 + 2] = z;
      this.vel[i * 3] = vx; this.vel[i * 3 + 1] = vy; this.vel[i * 3 + 2] = vz;
      this.life[i] = 0.25 + Math.random() * 0.45;
      const g = gain * (0.6 + Math.random() * 0.8);
      this.base[i * 3] = colour.r * g; this.base[i * 3 + 1] = colour.g * g; this.base[i * 3 + 2] = colour.b * g;
    }
  }

  update(dt: number, floorY: number): void {
    const p = this.pos;
    for (let i = 0; i < this.size; i++) {
      if (this.life[i] <= 0) continue;
      this.life[i] -= dt;
      if (this.life[i] <= 0) { p[i * 3 + 1] = -1000; this.col[i * 3] = this.col[i * 3 + 1] = this.col[i * 3 + 2] = 0; continue; }
      this.vel[i * 3 + 1] -= 9.8 * dt;
      p[i * 3] += this.vel[i * 3] * dt;
      p[i * 3 + 1] += this.vel[i * 3 + 1] * dt;
      p[i * 3 + 2] += this.vel[i * 3 + 2] * dt;
      if (p[i * 3 + 1] < floorY + 0.01) { p[i * 3 + 1] = floorY + 0.01; this.vel[i * 3 + 1] *= -0.35; this.vel[i * 3] *= 0.6; this.vel[i * 3 + 2] *= 0.6; }
      const f = Math.min(1, this.life[i] / 0.3);
      this.col[i * 3] = this.base[i * 3] * f;
      this.col[i * 3 + 1] = this.base[i * 3 + 1] * f * f;
      this.col[i * 3 + 2] = this.base[i * 3 + 2] * f * f * f;
    }
    this.points.geometry.attributes.position.needsUpdate = true;
    this.points.geometry.attributes.color.needsUpdate = true;
  }

  clear(): void {
    this.life.fill(0);
    for (let i = 0; i < this.size; i++) this.pos[i * 3 + 1] = -1000;
    this.points.geometry.attributes.position.needsUpdate = true;
  }

  dispose(): void {
    this.points.geometry.dispose();
    (this.points.material as PointsMaterial).dispose();
    this.tex.dispose();
  }
}

interface FlashSlot { sprite: Sprite; mat: SpriteMaterial; life: number; total: number; size0: number; size1: number; colour: Color; gain: number }

/** Short camera-facing glows: muzzle flashes, impact and hit flashes, the parry burst. */
export class Flashes {
  readonly group = new Group();
  private readonly slots: FlashSlot[] = [];
  private next = 0;
  private readonly tex: Texture;
  private readonly star: Texture;

  constructor(size = 40) {
    this.tex = radialTexture([[0, "rgba(255,255,255,1)"], [0.18, "rgba(255,255,255,0.75)"], [0.5, "rgba(255,255,255,0.18)"], [1, "rgba(255,255,255,0)"]]);
    this.star = starTexture();
    for (let i = 0; i < size; i++) {
      const mat = new SpriteMaterial({ map: this.tex, color: 0xffffff, transparent: true, blending: AdditiveBlending, depthWrite: false, depthTest: true });
      const sprite = new Sprite(mat);
      sprite.visible = false;
      sprite.renderOrder = 42;
      sprite.frustumCulled = false;
      this.group.add(sprite);
      this.slots.push({ sprite, mat, life: 0, total: 1, size0: 0, size1: 0, colour: new Color(), gain: 1 });
    }
  }

  spawn(x: number, y: number, z: number, colour: Color, gain: number, size0: number, size1: number, seconds: number, star = false): void {
    const s = this.slots[this.next];
    this.next = (this.next + 1) % this.slots.length;
    s.sprite.position.set(x, y, z);
    s.life = s.total = seconds;
    s.size0 = size0;
    s.size1 = size1;
    s.colour.copy(colour);
    s.gain = gain;
    s.mat.map = star ? this.star : this.tex;
    s.mat.rotation = Math.random() * Math.PI;
    s.sprite.visible = true;
  }

  update(dt: number): void {
    for (const s of this.slots) {
      if (s.life <= 0) continue;
      s.life -= dt;
      if (s.life <= 0) { s.sprite.visible = false; continue; }
      const k = 1 - s.life / s.total;
      const size = s.size0 + (s.size1 - s.size0) * Math.sqrt(k);
      s.sprite.scale.set(size, size, 1);
      s.mat.color.copy(s.colour).multiplyScalar(s.gain * (1 - k) * (1 - k));
    }
  }

  clear(): void {
    for (const s of this.slots) { s.life = 0; s.sprite.visible = false; }
  }

  dispose(): void {
    for (const s of this.slots) s.mat.dispose();
    this.tex.dispose();
    this.star.dispose();
  }
}

function starTexture(): Texture {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const c = size / 2;
    const g = ctx.createRadialGradient(c, c, 0, c, c, c);
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.25, "rgba(255,255,255,0.35)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
    ctx.globalCompositeOperation = "lighter";
    for (const [w, h] of [[size, 3], [3, size]] as const) {
      const lg = ctx.createLinearGradient(c - w / 2, c - h / 2, c + w / 2, c + h / 2);
      lg.addColorStop(0, "rgba(255,255,255,0)");
      lg.addColorStop(0.5, "rgba(255,255,255,0.9)");
      lg.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = lg;
      ctx.fillRect(c - w / 2, c - h / 2, w, h);
    }
  }
  return new CanvasTexture(canvas);
}

interface ScorchSlot { mesh: Mesh<PlaneGeometry, MeshBasicMaterial>; glow: Mesh<PlaneGeometry, MeshBasicMaterial>; age: number }

/** Burn marks where bolts strike walls and floor: a hot glow that cools, then a dark mark that fades after a while. */
export class Scorches {
  readonly group = new Group();
  private readonly slots: ScorchSlot[] = [];
  private next = 0;
  private readonly geo = new PlaneGeometry(1, 1);
  private readonly tex = scorchTexture();
  private readonly glowTex = radialTexture([[0, "rgba(255,255,255,1)"], [0.25, "rgba(255,255,255,0.5)"], [1, "rgba(255,255,255,0)"]]);
  private readonly q = new Quaternion();
  private readonly n = new Vector3();
  static readonly HOT_S = 1.6;
  static readonly LIFE_S = 24;

  constructor(size = 64) {
    for (let i = 0; i < size; i++) {
      const mesh = new Mesh(this.geo, new MeshBasicMaterial({
        map: this.tex, transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
        color: 0xffffff, blending: NormalBlending, toneMapped: false,
      }));
      const glow = new Mesh(this.geo, new MeshBasicMaterial({
        map: this.glowTex, transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -3, polygonOffsetUnits: -3,
        blending: AdditiveBlending, color: 0xffffff,
      }));
      mesh.visible = glow.visible = false;
      mesh.renderOrder = 30;
      glow.renderOrder = 31;
      this.group.add(mesh, glow);
      this.slots.push({ mesh, glow, age: Infinity });
    }
  }

  add(x: number, y: number, z: number, nx: number, ny: number, nz: number): void {
    const s = this.slots[this.next];
    this.next = (this.next + 1) % this.slots.length;
    const n = this.n.set(nx, ny, nz);
    if (n.lengthSq() < 1e-6) n.set(0, 1, 0);
    n.normalize();
    this.q.setFromUnitVectors(new Vector3(0, 0, 1), n);
    const size = 0.32 + Math.random() * 0.18;
    for (const m of [s.mesh, s.glow]) {
      m.position.set(x + n.x * 0.012, y + n.y * 0.012, z + n.z * 0.012);
      m.quaternion.copy(this.q);
      m.rotateZ(Math.random() * Math.PI * 2);
      m.visible = true;
    }
    s.mesh.scale.setScalar(size);
    s.glow.scale.setScalar(size * 0.75);
    s.age = 0;
  }

  update(dt: number): void {
    for (const s of this.slots) {
      if (!Number.isFinite(s.age)) continue;
      s.age += dt;
      if (s.age >= Scorches.LIFE_S) { s.age = Infinity; s.mesh.visible = s.glow.visible = false; continue; }
      const hot = Math.max(0, 1 - s.age / Scorches.HOT_S);
      s.glow.visible = hot > 0;
      s.glow.material.color.setRGB(4 * hot, 1.4 * hot * hot, 0.3 * hot * hot * hot);
      const fadeOut = Math.min(1, (Scorches.LIFE_S - s.age) / 4);
      s.mesh.material.opacity = 0.85 * fadeOut;
    }
  }

  clear(): void {
    for (const s of this.slots) { s.age = Infinity; s.mesh.visible = s.glow.visible = false; }
  }

  dispose(): void {
    this.geo.dispose();
    this.tex.dispose();
    this.glowTex.dispose();
    for (const s of this.slots) { s.mesh.material.dispose(); s.glow.material.dispose(); }
  }
}

/** A venting blaster's plume: soft grey puffs rising and spreading. */
export class Steam {
  readonly points: Points;
  private readonly pos: Float32Array;
  private readonly vel: Float32Array;
  private readonly life: Float32Array;
  private next = 0;
  private readonly tex: Texture;

  constructor(private readonly size = 160) {
    this.pos = new Float32Array(size * 3);
    this.vel = new Float32Array(size * 3);
    this.life = new Float32Array(size);
    for (let i = 0; i < size; i++) this.pos[i * 3 + 1] = -1000;
    const geo = new BufferGeometry();
    geo.setAttribute("position", new BufferAttribute(this.pos, 3));
    this.tex = radialTexture([[0, "rgba(255,255,255,0.55)"], [0.5, "rgba(255,255,255,0.2)"], [1, "rgba(255,255,255,0)"]], 32);
    this.points = new Points(geo, new PointsMaterial({
      size: 0.22, map: this.tex, color: 0x8a9096, transparent: true, opacity: 0.5, depthWrite: false, sizeAttenuation: true,
    }));
    this.points.frustumCulled = false;
    this.points.renderOrder = 43;
  }

  emit(x: number, y: number, z: number, count: number): void {
    for (let k = 0; k < count; k++) {
      const i = this.next;
      this.next = (this.next + 1) % this.size;
      this.pos[i * 3] = x + (Math.random() - 0.5) * 0.05;
      this.pos[i * 3 + 1] = y;
      this.pos[i * 3 + 2] = z + (Math.random() - 0.5) * 0.05;
      this.vel[i * 3] = (Math.random() - 0.5) * 0.5;
      this.vel[i * 3 + 1] = 0.6 + Math.random() * 0.6;
      this.vel[i * 3 + 2] = (Math.random() - 0.5) * 0.5;
      this.life[i] = 0.6 + Math.random() * 0.5;
    }
  }

  update(dt: number): void {
    for (let i = 0; i < this.size; i++) {
      if (this.life[i] <= 0) continue;
      this.life[i] -= dt;
      if (this.life[i] <= 0) { this.pos[i * 3 + 1] = -1000; continue; }
      this.pos[i * 3] += this.vel[i * 3] * dt;
      this.pos[i * 3 + 1] += this.vel[i * 3 + 1] * dt;
      this.pos[i * 3 + 2] += this.vel[i * 3 + 2] * dt;
      this.vel[i * 3 + 1] *= 1 - dt * 0.8;
    }
    this.points.geometry.attributes.position.needsUpdate = true;
  }

  clear(): void {
    this.life.fill(0);
    for (let i = 0; i < this.size; i++) this.pos[i * 3 + 1] = -1000;
    this.points.geometry.attributes.position.needsUpdate = true;
  }

  dispose(): void {
    this.points.geometry.dispose();
    (this.points.material as PointsMaterial).dispose();
    this.tex.dispose();
  }
}
