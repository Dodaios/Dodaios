/**
 * One skeleton for every figure on the ship (the android crew and the
 * captain), and the poses it takes. Poses are pure functions of time, so
 * they are tested without a GPU; the renderer copies them onto bones.
 *
 * Bones rotate in their parent's frame. A limb hangs along -y at rest; a
 * figure faces +z. Positive x rotation tips a part's forward direction down
 * (a nod) and swings a hanging limb backwards; negative swings it forwards.
 */

export const BONES = [
  "hips", "chest", "neck", "head",
  "armL", "forearmL", "handL", "armR", "forearmR", "handR",
  "thighL", "shinL", "footL", "thighR", "shinR", "footR",
] as const;
export type BoneName = typeof BONES[number];

export const PARENT: Record<BoneName, BoneName | null> = {
  hips: null, chest: "hips", neck: "chest", head: "neck",
  armL: "chest", forearmL: "armL", handL: "forearmL", armR: "chest", forearmR: "armR", handR: "forearmR",
  thighL: "hips", shinL: "thighL", footL: "shinL", thighR: "hips", shinR: "thighR", footR: "shinR",
};

/** Bone offsets from the parent at rest (metres). Left is +x (the figure's own left when it faces +z). */
export const OFFSET: Record<BoneName, [number, number, number]> = {
  hips: [0, 0.94, 0],
  chest: [0, 0.1, 0],
  neck: [0, 0.44, -0.01],
  head: [0, 0.08, 0.01],
  armL: [0.215, 0.38, -0.01], forearmL: [0, -0.29, 0], handL: [0, -0.26, 0.01],
  armR: [-0.215, 0.38, -0.01], forearmR: [0, -0.29, 0], handR: [0, -0.26, 0.01],
  thighL: [0.1, -0.03, 0], shinL: [0, -0.44, 0], footL: [0, -0.43, 0],
  thighR: [-0.1, -0.03, 0], shinR: [0, -0.44, 0], footR: [0, -0.43, 0],
};

/** Hip height above the floor when standing. */
export const HIP_Y = OFFSET.hips[1];

export type Euler3 = [number, number, number];

export interface PoseFrame {
  /** Hips position offset from the figure's origin (y absolute). */
  root: [number, number, number];
  /** Extra rotation of the whole body (lying down). */
  rootRot: Euler3;
  bones: Partial<Record<BoneName, Euler3>>;
}

export type Activity = "stand" | "walk" | "sit" | "type" | "wave" | "rest" | "talk" | "listen" | "lean";

export interface PoseInput {
  activity: Activity;
  /** Seconds, for loops. */
  t: number;
  /** Walk cycle phase in cycles (grows with distance walked). */
  phase?: number;
  /** Walking speed in m/s (sets the swing). */
  speed?: number;
  /** Seat height for sit/type, couch height for rest. */
  seatY?: number;
  /** 0..1 per figure, so a crowd is out of step. */
  seed?: number;
}

const R = (x = 0, y = 0, z = 0): Euler3 => [x, y, z];

function breathe(t: number, seed: number): number {
  return Math.sin((t + seed * 7) * 1.6) * 0.02;
}

export function pose(input: PoseInput): PoseFrame {
  const { activity, t } = input;
  const seed = input.seed ?? 0;
  const b = breathe(t, seed);
  const base: PoseFrame = {
    root: [0, HIP_Y, 0], rootRot: R(),
    bones: {
      chest: R(b, 0, 0), head: R(-b * 0.5, Math.sin((t + seed * 11) * 0.37) * 0.12, 0),
      armL: R(0.04, 0, 0.09), armR: R(0.04, 0, -0.09), forearmL: R(-0.12), forearmR: R(-0.12),
    },
  };
  switch (activity) {
    case "walk": {
      const speed = Math.min(2.6, Math.max(0.3, input.speed ?? 1.3));
      const amp = 0.28 + speed * 0.14;
      const w = (input.phase ?? 0) * Math.PI * 2;
      const s = Math.sin(w), c = Math.cos(w);
      base.root = [0, HIP_Y - 0.02 + Math.abs(c) * 0.03, 0];
      base.bones.thighL = R(-s * amp, 0, 0);
      base.bones.thighR = R(s * amp, 0, 0);
      base.bones.shinL = R(Math.max(0, -c) * amp * 1.4 + 0.05);
      base.bones.shinR = R(Math.max(0, c) * amp * 1.4 + 0.05);
      base.bones.footL = R(-0.1 + s * 0.2);
      base.bones.footR = R(-0.1 - s * 0.2);
      base.bones.armL = R(s * amp * 0.8, 0, 0.08);
      base.bones.armR = R(-s * amp * 0.8, 0, -0.08);
      base.bones.forearmL = R(-0.25 - Math.max(0, s) * 0.3);
      base.bones.forearmR = R(-0.25 - Math.max(0, -s) * 0.3);
      base.bones.chest = R(0.04 + speed * 0.02, s * 0.06, 0);
      base.bones.hips = R(0, -s * 0.06, 0);
      base.bones.head = R(-0.04, 0, 0);
      return base;
    }
    case "sit":
    case "type": {
      const seatY = input.seatY ?? 0.5;
      base.root = [0, seatY + 0.07, -0.04];
      base.bones.thighL = R(-1.52, 0, 0.04);
      base.bones.thighR = R(-1.52, 0, -0.04);
      base.bones.shinL = R(1.45);
      base.bones.shinR = R(1.45);
      base.bones.footL = R(0.05);
      base.bones.footR = R(0.05);
      if (activity === "type") {
        // Forearms on the desk, fingers working: small, fast, out of step.
        const k = (t + seed * 3) * 9;
        base.bones.chest = R(0.14 + b, 0, 0);
        base.bones.head = R(0.22, Math.sin((t + seed) * 0.5) * 0.1, 0);
        base.bones.armL = R(-0.62, 0, 0.16);
        base.bones.armR = R(-0.62, 0, -0.16);
        base.bones.forearmL = R(-0.95 + Math.sin(k) * 0.05, 0, -0.18);
        base.bones.forearmR = R(-0.95 + Math.sin(k * 1.13 + 1) * 0.05, 0, 0.18);
        base.bones.handL = R(0.2 + Math.max(0, Math.sin(k * 1.7)) * 0.25);
        base.bones.handR = R(0.2 + Math.max(0, Math.sin(k * 1.9 + 2)) * 0.25);
      } else {
        base.bones.chest = R(-0.06 + b, 0, 0);
        base.bones.armL = R(-0.35, 0, 0.12);
        base.bones.armR = R(-0.35, 0, -0.12);
        base.bones.forearmL = R(-0.9, 0, -0.1);
        base.bones.forearmR = R(-0.9, 0, 0.1);
      }
      return base;
    }
    case "wave": {
      const k = Math.sin((t + seed) * 7);
      base.bones.armR = R(0, 0, -2.55);
      base.bones.forearmR = R(0, 0, -0.3 + k * 0.4);
      base.bones.handR = R(0, 0, k * 0.2);
      base.bones.head = R(-0.1, 0, 0.08);
      base.bones.chest = R(-0.03, -0.1, 0);
      return base;
    }
    case "talk": {
      const k = (t + seed * 5) * 2.2;
      base.bones.armR = R(-0.35 + Math.sin(k) * 0.15, 0, -0.2);
      base.bones.forearmR = R(-1.0 + Math.sin(k * 1.3) * 0.25, 0.3, 0);
      base.bones.armL = R(-0.2 + Math.sin(k * 0.8 + 1) * 0.1, 0, 0.18);
      base.bones.forearmL = R(-0.7 + Math.sin(k * 1.1 + 2) * 0.2, -0.3, 0);
      base.bones.head = R(-0.05 + Math.sin(k * 0.7) * 0.05, Math.sin(k * 0.4) * 0.15, 0);
      return base;
    }
    case "listen": {
      base.bones.armL = R(-0.15, 0, 0.22);
      base.bones.armR = R(-0.15, 0, -0.22);
      base.bones.forearmL = R(-1.2, 0, -0.5);
      base.bones.forearmR = R(-1.2, 0, 0.5);
      base.bones.head = R(-0.06, Math.sin((t + seed * 9) * 0.6) * 0.1, Math.sin((t + seed) * 0.3) * 0.06);
      return base;
    }
    case "lean": {
      base.root = [0, HIP_Y - 0.03, 0];
      base.bones.chest = R(0.18 + b, 0, 0);
      base.bones.armL = R(-0.7, 0, 0.1);
      base.bones.armR = R(-0.7, 0, -0.1);
      base.bones.forearmL = R(-0.5);
      base.bones.forearmR = R(-0.5);
      base.bones.head = R(0.25, 0, 0);
      return base;
    }
    case "rest": {
      const seatY = input.seatY ?? 0.6;
      base.root = [0, seatY + 0.12, 0];
      base.rootRot = R(-Math.PI / 2, 0, 0);
      base.bones.chest = R(b * 0.5, 0, 0);
      base.bones.head = R(-0.15, 0.3, 0);
      base.bones.armL = R(0, 0, 0.18);
      base.bones.armR = R(0, 0, -0.18);
      base.bones.forearmL = R(-0.4, 0, -0.5);
      base.bones.forearmR = R(-0.4, 0, 0.5);
      base.bones.thighL = R(0, 0, 0.03);
      base.bones.thighR = R(0, 0, -0.03);
      base.bones.footL = R(-0.5);
      base.bones.footR = R(-0.5);
      return base;
    }
    default:
      return base;
  }
}

/** Blend two frames: `k` = 0 gives `a`, 1 gives `b`. */
export function blendPose(a: PoseFrame, b: PoseFrame, k: number): PoseFrame {
  const lerp = (x: number, y: number) => x + (y - x) * k;
  const bones: Partial<Record<BoneName, Euler3>> = {};
  for (const name of BONES) {
    const ra = a.bones[name] ?? [0, 0, 0], rb = b.bones[name] ?? [0, 0, 0];
    bones[name] = [lerp(ra[0], rb[0]), lerp(ra[1], rb[1]), lerp(ra[2], rb[2])];
  }
  return {
    root: [lerp(a.root[0], b.root[0]), lerp(a.root[1], b.root[1]), lerp(a.root[2], b.root[2])],
    rootRot: [lerp(a.rootRot[0], b.rootRot[0]), lerp(a.rootRot[1], b.rootRot[1]), lerp(a.rootRot[2], b.rootRot[2])],
    bones,
  };
}

/** World positions of every bone at rest (the bind pose). */
export function restPositions(): Record<BoneName, [number, number, number]> {
  const out = {} as Record<BoneName, [number, number, number]>;
  for (const name of BONES) {
    const parent = PARENT[name];
    const o = OFFSET[name];
    const p = parent ? out[parent] : [0, 0, 0];
    out[name] = [p[0] + o[0], p[1] + o[1], p[2] + o[2]];
  }
  return out;
}
