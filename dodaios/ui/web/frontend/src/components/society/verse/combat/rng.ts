/**
 * Seeded randomness for the combat simulation. Nothing in combat/ calls
 * Math.random or reads a clock.
 *
 * Two kinds:
 * - `hashN` / `rand01`: counter-based. A draw is a pure function of
 *   (match seed, who, which shot, salt), so a client predicting its own shot
 *   gets the same spread as the server without sharing an RNG stream.
 * - `Rng`: a small sequential generator (mulberry32) with a one-number state,
 *   for the bots and the harness, which own their stream.
 */

/** 32-bit avalanche hash (lowbias32). */
export function hash32(x: number): number {
  x >>>= 0;
  x ^= x >>> 16;
  x = Math.imul(x, 0x7feb352d);
  x ^= x >>> 15;
  x = Math.imul(x, 0x846ca68b);
  x ^= x >>> 16;
  return x >>> 0;
}

export function hash2(a: number, b: number): number {
  return hash32(hash32(a) ^ Math.imul(b | 0, 0x9e3779b1));
}

export function hash3(a: number, b: number, c: number): number {
  return hash32(hash2(a, b) ^ Math.imul(c | 0, 0x85ebca77));
}

export function hash4(a: number, b: number, c: number, d: number): number {
  return hash32(hash3(a, b, c) ^ Math.imul(d | 0, 0xc2b2ae3d));
}

/** Uniform in [0, 1) from four integers. */
export function rand01(a: number, b: number, c: number, d: number): number {
  return hash4(a, b, c, d) / 4294967296;
}

/** Salts so different draws for the same event never correlate. */
export const SALT = {
  spreadA: 1,
  spreadB: 2,
  spreadC: 3,
  recoilYaw: 4,
  deflectRoll: 5,
  deflectYaw: 6,
  deflectPitch: 7,
  parryYaw: 8,
  parryPitch: 9,
} as const;

/** Sequential seeded generator (mulberry32). `state` is the whole state. */
export class Rng {
  state: number;

  constructor(seed: number) {
    this.state = hash32(seed ^ 0x6d2b79f5) >>> 0;
  }

  /** Uniform in [0, 1). */
  next(): number {
    let t = (this.state = (this.state + 0x6d2b79f5) >>> 0);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  range(lo: number, hi: number): number {
    return lo + (hi - lo) * this.next();
  }

  int(n: number): number {
    return Math.floor(this.next() * n);
  }

  chance(p: number): boolean {
    return this.next() < p;
  }

  /** Normal deviate (Box-Muller). */
  normal(mean = 0, sd = 1): number {
    const u = Math.max(this.next(), 1e-12);
    const v = this.next();
    return mean + sd * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  }

  /** A fresh generator split off this one (for a sub-system that needs its own stream). */
  fork(salt: number): Rng {
    return new Rng(hash2(this.state, salt));
  }
}
