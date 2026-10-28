/**
 * The duel's dynamic light: a fixed pool of a few point lights that the
 * bolts and the short flashes (muzzle pops, impacts, parries, hits) share,
 * so a bolt flying past a wall tints it and a shot lights the room for a
 * frame or two.
 *
 * The pool's size never changes while the duel is on (three.js recompiles
 * every lit material when the number of lights changes), unused lights only
 * go dark. Each frame the brightest requests near the camera win the lights;
 * a request is a position, a colour and an intensity, with flashes decaying
 * over their lifetime and a slight flicker on bolts.
 *
 * `pickLights` is pure (tested); `DuelLights` applies it to three.js lights.
 */
import { Color, Group, PointLight } from "three";

export const DUEL_LIGHTS = {
  /** Point lights in the pool (each one adds a little to every lit pixel's cost). */
  count: 4,
  /** How far a light reaches, metres, and its decay exponent. */
  distance: 7,
  decay: 1.7,
  /** A bolt's light, candela-ish (scaled by the colour). */
  boltIntensity: 2.2,
  /** Requests farther than this from the camera are not lit, metres. */
  maxCameraDistance: 30,
} as const;

export interface LightRequest {
  x: number;
  y: number;
  z: number;
  r: number;
  g: number;
  b: number;
  intensity: number;
  /** Seconds left (flashes); Infinity for a bolt's light, renewed each frame. */
  life: number;
  total: number;
}

/**
 * The requests that get a light this frame: score = intensity over the
 * distance to the camera (close and bright first), at most `count`, the
 * dark and the far ones dropped. Pure; returns indices into `requests`.
 */
export function pickLights(requests: readonly LightRequest[], cx: number, cy: number, cz: number, count: number, maxDistance: number = DUEL_LIGHTS.maxCameraDistance): number[] {
  const scored: { i: number; s: number }[] = [];
  for (let i = 0; i < requests.length; i++) {
    const q = requests[i];
    const level = q.intensity * (Number.isFinite(q.life) ? q.life / q.total : 1);
    if (level <= 0.01) continue;
    const d = Math.hypot(q.x - cx, q.y - cy, q.z - cz);
    if (d > maxDistance) continue;
    scored.push({ i, s: level / (1 + d * 0.35) });
  }
  scored.sort((a, b) => b.s - a.s);
  return scored.slice(0, count).map((x) => x.i);
}

export class DuelLights {
  readonly group = new Group();
  private readonly lights: PointLight[] = [];
  private readonly flashes: LightRequest[] = [];
  private readonly frame: LightRequest[] = [];
  private time = 0;

  constructor(count: number = DUEL_LIGHTS.count) {
    this.group.name = "DuelLights";
    for (let i = 0; i < count; i++) {
      const l = new PointLight(0xffffff, 0, DUEL_LIGHTS.distance, DUEL_LIGHTS.decay);
      l.castShadow = false;
      this.lights.push(l);
      this.group.add(l);
    }
  }

  /** A short light: muzzle pop, impact, parry. */
  flash(x: number, y: number, z: number, colour: Color, intensity: number, seconds: number): void {
    if (this.flashes.length > 24) this.flashes.shift();
    this.flashes.push({ x, y, z, r: colour.r, g: colour.g, b: colour.b, intensity, life: seconds, total: seconds });
  }

  /** Start a frame: the bolts' lights are requested again each frame (`bolt`), the flashes age. */
  begin(dt: number): void {
    this.time += dt;
    this.frame.length = 0;
    for (let i = this.flashes.length - 1; i >= 0; i--) {
      const f = this.flashes[i];
      f.life -= dt;
      if (f.life <= 0) this.flashes.splice(i, 1);
    }
  }

  /** A bolt's own light for this frame (it flickers a little). */
  bolt(x: number, y: number, z: number, colour: Color, gain = 1): void {
    const flicker = 0.82 + 0.18 * Math.sin(this.time * 97 + x * 3.1 + z * 1.7);
    this.frame.push({ x, y, z, r: colour.r, g: colour.g, b: colour.b, intensity: DUEL_LIGHTS.boltIntensity * gain * flicker, life: Infinity, total: 1 });
  }

  /** Give the lights to the strongest requests near the camera. */
  apply(cx: number, cy: number, cz: number): void {
    for (const f of this.flashes) this.frame.push(f);
    const picked = pickLights(this.frame, cx, cy, cz, this.lights.length);
    for (let i = 0; i < this.lights.length; i++) {
      const l = this.lights[i];
      const q = i < picked.length ? this.frame[picked[i]] : null;
      if (!q) { l.intensity = 0; continue; }
      const k = Number.isFinite(q.life) ? (q.life / q.total) * (q.life / q.total) : 1;
      l.position.set(q.x, q.y, q.z);
      l.color.setRGB(q.r, q.g, q.b);
      l.intensity = q.intensity * k;
    }
  }

  clear(): void {
    this.flashes.length = 0;
    this.frame.length = 0;
    for (const l of this.lights) l.intensity = 0;
  }

  dispose(): void {
    for (const l of this.lights) l.dispose();
  }
}
