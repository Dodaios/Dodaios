/**
 * Arc Storm, the Sovereign's signature power: while it is held, violet-white
 * lightning crackles from both hands toward where the commander aims.
 *
 * Every bolt is a jagged polyline (midpoint displacement, a few forks) drawn
 * twice with fat lines: a thin white-hot core and a wide violet glow, both
 * additive. The bolts re-strike many times a second, a light at the hands
 * flickers with them and sparks burst where they land. Pure geometry
 * (`boltPoints`) is separate from the three.js drawing.
 */
import {
  AdditiveBlending, Color, Group, PointLight, Vector2, Vector3, type WebGLRenderer,
} from "three";
import { LineSegments2 } from "three/examples/jsm/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/examples/jsm/lines/LineSegmentsGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";

/** Tuning of the power (seconds, metres). */
export const ARC = {
  /** How far the bolts reach. */
  reach: 5.2,
  /** Seconds between strikes (each strike redraws every bolt). */
  restrike: 0.045,
  /** Bolts per hand per strike. */
  bolts: 3,
  /** Segments of a main bolt (a power of two). */
  segments: 16,
  /** Sideways jitter of the midpoints, as a share of the segment's length. */
  jitter: 0.2,
  /** The arms rise into the cast pose over this long. */
  raise: 0.18,
  core: "#f4ecff",
  glow: "#8b5cff",
};

/** A small deterministic random generator (mulberry32). */
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * A lightning bolt from `a` to `b`: `segments + 1` points, the ends exact, the
 * inside displaced at random across the line (larger at the middle). Pure.
 */
export function boltPoints(a: Vector3, b: Vector3, segments: number, jitter: number, rand: () => number): Vector3[] {
  const pts: Vector3[] = [a.clone(), b.clone()];
  const dir = new Vector3().subVectors(b, a);
  const len = dir.length();
  if (len < 1e-6) return [a.clone(), b.clone()];
  dir.multiplyScalar(1 / len);
  // Two directions across the bolt.
  const helper = Math.abs(dir.y) < 0.9 ? new Vector3(0, 1, 0) : new Vector3(1, 0, 0);
  const u = new Vector3().crossVectors(dir, helper).normalize();
  const v = new Vector3().crossVectors(dir, u).normalize();
  let span = len * jitter;
  let out = pts;
  while (out.length - 1 < segments) {
    const next: Vector3[] = [];
    for (let i = 0; i < out.length - 1; i++) {
      const p = out[i];
      const q = out[i + 1];
      next.push(p);
      const m = new Vector3().addVectors(p, q).multiplyScalar(0.5);
      m.addScaledVector(u, (rand() - 0.5) * span).addScaledVector(v, (rand() - 0.5) * span);
      next.push(m);
    }
    next.push(out[out.length - 1]);
    out = next;
    span *= 0.5;
  }
  return out;
}

const tmpA = new Vector3();
const tmpB = new Vector3();
const tmpDir = new Vector3();

export class ArcStorm {
  readonly group = new Group();
  private readonly core: LineSegments2;
  private readonly glow: LineSegments2;
  private readonly coreMat: LineMaterial;
  private readonly glowMat: LineMaterial;
  private readonly light = new PointLight(new Color(ARC.glow), 0, 7, 1.6);
  private readonly impact = new PointLight(new Color(ARC.glow), 0, 4, 1.8);
  private untilStrike = 0;
  private seed = 1;
  private readonly size = new Vector2();
  /** 0..1: how far the power is up (the arms rise, the bolts thicken). */
  level = 0;

  constructor() {
    const mat = (color: string, width: number, opacity: number) => new LineMaterial({
      color: new Color(color).getHex(), linewidth: width, worldUnits: true, transparent: true, opacity,
      blending: AdditiveBlending, depthWrite: false, toneMapped: false,
    });
    this.coreMat = mat(ARC.core, 0.008, 1);
    this.glowMat = mat(ARC.glow, 0.036, 0.5);
    this.core = new LineSegments2(new LineSegmentsGeometry(), this.coreMat);
    this.glow = new LineSegments2(new LineSegmentsGeometry(), this.glowMat);
    for (const l of [this.glow, this.core]) {
      l.frustumCulled = false;
      l.renderOrder = 50;
      this.group.add(l);
    }
    this.group.add(this.light, this.impact);
    this.group.visible = false;
  }

  /** Raise or drop the power for this frame (call before the caster's body is posed). */
  rise(dtS: number, held: boolean): number {
    const dt = Math.min(0.1, Math.max(0, dtS));
    this.level = Math.max(0, Math.min(1, this.level + (held ? dt / ARC.raise : -dt / 0.12)));
    return this.level;
  }

  /**
   * One frame. `hands` are the fingertips the bolts leave from (none: the power is down), `aim` the unit direction
   * they go, `floorY` the floor under the caster.
   */
  update(
    dtS: number, held: boolean, hands: readonly Vector3[], aim: Vector3, floorY: number, renderer: WebGLRenderer | null, thickness = 1,
  ): void {
    const dt = Math.min(0.1, Math.max(0, dtS));
    const on = held && this.level > 0.6 && hands.length > 0;
    this.group.visible = on || this.light.intensity > 0.01;
    if (renderer) {
      renderer.getSize(this.size);
      this.coreMat.resolution.copy(this.size);
      this.glowMat.resolution.copy(this.size);
    }
    if (!on) {
      this.core.visible = this.glow.visible = false;
      this.light.intensity *= 0.6;
      this.impact.intensity *= 0.6;
      return;
    }
    this.core.visible = this.glow.visible = true;
    this.untilStrike -= dt;
    if (this.untilStrike > 0) {
      // Between strikes the light still flickers.
      this.light.intensity = 3 + Math.random() * 5;
      return;
    }
    this.untilStrike = ARC.restrike * (0.6 + Math.random() * 0.8);
    const rand = rng(this.seed++);
    const seg: number[] = [];
    const hit = new Vector3();
    tmpDir.copy(aim).normalize();
    for (const hand of hands) {
      for (let k = 0; k < ARC.bolts; k++) {
        // Each bolt lands somewhere in a cone ahead, the first one straightest.
        const spread = k === 0 ? 0.25 : 0.9;
        const reach = ARC.reach * (0.65 + rand() * 0.45);
        tmpB.copy(hand).addScaledVector(tmpDir, reach);
        tmpB.x += (rand() - 0.5) * spread * 2;
        tmpB.z += (rand() - 0.5) * spread * 2;
        tmpB.y += (rand() - 0.6) * spread;
        tmpB.y = Math.max(floorY + 0.05, tmpB.y);
        hit.add(tmpB);
        const pts = boltPoints(hand, tmpB, ARC.segments, ARC.jitter, rand);
        pushPolyline(seg, pts);
        // Forks: short side bolts off the main one.
        for (let f = 0; f < 2; f++) {
          const i = 2 + Math.floor(rand() * (pts.length - 4));
          const from = pts[i];
          tmpA.subVectors(tmpB, from).multiplyScalar(0.25 + rand() * 0.3);
          tmpA.x += (rand() - 0.5) * 0.9;
          tmpA.y += (rand() - 0.5) * 0.7;
          tmpA.z += (rand() - 0.5) * 0.9;
          pushPolyline(seg, boltPoints(from, tmpA.add(from), 4, 0.4, rand));
        }
      }
    }
    for (const l of [this.core, this.glow]) {
      const g = l.geometry as LineSegmentsGeometry;
      g.setPositions(seg);
      l.computeLineDistances();
    }
    this.coreMat.linewidth = (0.005 + 0.006 * Math.random()) * thickness;
    this.glowMat.linewidth = 0.036 * thickness;
    this.glowMat.opacity = 0.35 + 0.25 * Math.random();
    const mid = hands.reduce((acc, h) => acc.add(h), tmpA.set(0, 0, 0)).multiplyScalar(1 / hands.length);
    this.light.position.copy(mid).addScaledVector(tmpDir, 0.4);
    this.light.intensity = 6 + Math.random() * 8;
    this.impact.position.copy(hit.multiplyScalar(1 / (hands.length * ARC.bolts)));
    this.impact.intensity = 3 + Math.random() * 5;
  }

  dispose(): void {
    this.core.geometry.dispose();
    this.glow.geometry.dispose();
    this.coreMat.dispose();
    this.glowMat.dispose();
    this.light.dispose();
    this.impact.dispose();
  }
}

function pushPolyline(out: number[], pts: readonly Vector3[]): void {
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i];
    const b = pts[i + 1];
    out.push(a.x, a.y, a.z, b.x, b.y, b.z);
  }
}
