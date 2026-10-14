/**
 * The courier's flight: a small rigid-body model with thrust, lift, pitch, yaw
 * and roll, two assist modes, boost and brake, collisions with the city, and an
 * autopilot that lands it on the sky pad. Pure and tested; the scene drives it
 * once per frame (SkyCourier.tsx).
 *
 * Frame: the ship's nose is its local -z, its top +y, its right +x (as the
 * exported model). Speeds are metres per second at the Verse's scale.
 *
 * - Arcade assist (the default): made for fun. The ship flies where it points,
 *   turns fast, climbs and dives as steeply as the pilot likes, and its lift
 *   thrusters push straight up or down whatever its attitude. It banks into
 *   turns and levels its wings (never its nose) when the stick is let go.
 * - Simulation: Newtonian. Thrust accelerates along the nose, the ship keeps
 *   its momentum and drifts; only light rotational dampers help.
 */
import { Quaternion, Vector3 } from "three";
import { sphereContact, type CourierWorld } from "./courierWorld";
import { COURIER } from "./skyPad";

export type FlightAssist = "arcade" | "simulation";

export interface FlightInput {
  /** -1..1: the throttle lever moves at its rate while held. */
  throttle: number;
  pitch: number;
  yaw: number;
  roll: number;
  /** -1..1: vertical thrusters, up and down. */
  lift: number;
  boost: boolean;
  brake: boolean;
}

export const NO_INPUT: FlightInput = { throttle: 0, pitch: 0, yaw: 0, roll: 0, lift: 0, boost: false, brake: false };

export type AutopilotPhase = "approach" | "hover" | "descend";

export interface FlightState {
  p: Vector3;
  v: Vector3;
  q: Quaternion;
  /** Body rates in radians per second: x pitch, y yaw, z roll. */
  w: Vector3;
  /** 0..1, the throttle lever. */
  throttle: number;
  /** 0 retracted .. 1 down. */
  gear: number;
  /** 0..1 boost charge, spent while boosting and recharged after. */
  charge: number;
  /** 0..1 shield flash after an impact, fading. */
  shield: number;
  /** Speed of the last impact (m/s), for the sound and the camera's shake; fades. */
  impact: number;
  landed: boolean;
  autopilot: AutopilotPhase | null;
  /** The autopilot's watch: the closest it came to its target, and how long it has gone without getting closer. */
  apBest: number;
  apStuck: number;
}

export const FLIGHT = {
  cruise: 85,
  boost: 170,
  /** Thrust along the nose (m/s²) in simulation, and the boost's factor on it. */
  thrust: 24,
  boostFactor: 2.4,
  /** Vertical thrust: arcade climbs and sinks at up to this speed (m/s); simulation accelerates with it. */
  lift: 30,
  /** Body rate at full stick (rad/s): pitch, yaw, roll. */
  rates: [1.9, 1.3, 2.8] as const,
  /** How fast arcade pulls the velocity onto the nose (1/s), and the simulation's linear drag. */
  grip: 2.6,
  drag: 0.025,
  /** The throttle lever's travel per second at full input. */
  leverRate: 1.1,
  /** Boost charge spent and regained per second. */
  boostDrain: 0.22,
  boostRecharge: 0.12,
  /** Below this height over the deck the gear comes down. */
  gearHeight: 14,
  /** The autopilot's hover height above the pad, the speed it approaches with and how fast it sinks. */
  hover: 16,
  approach: 45,
  sink: 3.2,
  /** Over every roof of the city (the tallest far ones stay below +45 m) and over the office: the approach's height. */
  safeHeight: 60,
} as const;

/** Collision spheres along the keel (local z, metres) and their radius. */
export const KEEL = { offsets: [-6.2, -2.1, 2.1, 6.2], radius: 1.7 } as const;

const _f = new Vector3(), _u = new Vector3(), _r = new Vector3(), _t = new Vector3(), _a = new Vector3(), _q = new Quaternion(), _s = new Vector3();

/** A ship standing on the pad, nose along `heading` (0 = -z, turning towards -x as it grows). */
export function parkedState(pad: { x: number; z: number; heading: number }): FlightState {
  return {
    p: new Vector3(pad.x, COURIER.standHeight, pad.z),
    v: new Vector3(), q: new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), pad.heading), w: new Vector3(),
    throttle: 0, gear: 1, charge: 1, shield: 0, impact: 0, landed: true, autopilot: null, apBest: Infinity, apStuck: 0,
  };
}

export function forwardOf(q: Quaternion, out = new Vector3()): Vector3 {
  return out.set(0, 0, -1).applyQuaternion(q);
}

function axes(q: Quaternion) {
  forwardOf(q, _f);
  _u.set(0, 1, 0).applyQuaternion(q);
  _r.set(1, 0, 0).applyQuaternion(q);
}

/** Advance the flight by dt seconds (callers pass at most 0.1 s). */
export function stepFlight(s: FlightState, raw: FlightInput, dt: number, assist: FlightAssist, world: CourierWorld,
  pad: { x: number; z: number; heading: number }): FlightState {
  let input = raw;
  // The shield's flash and the impact fade in every state: flying, landing itself or standing on the pad.
  s.shield = Math.max(0, s.shield - dt * 1.6);
  s.impact = Math.max(0, s.impact - dt * 30);
  if (s.autopilot) {
    // Any stick or lever input hands the ship back to the pilot.
    if (raw.throttle || raw.pitch || raw.yaw || raw.roll || raw.lift || raw.boost) s.autopilot = null;
    else return autopilot(s, dt, world, pad);
  }
  if (s.landed) {
    // Standing on the pad: only a lift or the throttle takes off.
    if (input.lift > 0.1 || input.throttle > 0.1) { s.landed = false; s.v.set(0, 4, 0); }
    else { s.v.set(0, 0, 0); s.w.set(0, 0, 0); s.throttle = 0; return s; }
  }
  s.throttle = Math.min(1, Math.max(0, s.throttle + input.throttle * FLIGHT.leverRate * dt));
  if (input.brake) s.throttle = Math.max(0, s.throttle - 1.5 * dt);
  const boosting = input.boost && s.charge > 0.02;
  s.charge = Math.min(1, Math.max(0, s.charge + (boosting ? -FLIGHT.boostDrain : FLIGHT.boostRecharge) * dt));
  axes(s.q);

  // Rotation: body rates follow the stick (arcade snaps, simulation accelerates and is damped).
  const target = _t.set(input.pitch * FLIGHT.rates[0], -input.yaw * FLIGHT.rates[1], -input.roll * FLIGHT.rates[2]);
  if (assist === "arcade") {
    // Bank into a turn, and level the wings when the stick is let go (the right wing's height is the bank).
    const bank = Math.asin(Math.max(-1, Math.min(1, _r.y)));
    const wanted = -input.yaw * 0.5;
    if (!input.roll) target.z += (wanted - bank) * 2.2;
    s.w.lerp(target, 1 - Math.exp(-10 * dt));
  } else {
    s.w.addScaledVector(_a.copy(target).sub(s.w), 1 - Math.exp(-3 * dt));
  }
  const turn = _q.setFromAxisAngle(_s.set(s.w.x, s.w.y, s.w.z).normalize(), s.w.length() * dt);
  if (s.w.lengthSq() > 1e-10) s.q.multiply(turn).normalize();
  axes(s.q);

  // Translation.
  const top = boosting ? FLIGHT.boost : FLIGHT.cruise;
  if (assist === "arcade") {
    // Lift thrusters push along the world's up, so Space always climbs and the sink key always sinks.
    const want = _t.copy(_f).multiplyScalar(s.throttle * top);
    want.y += input.lift * FLIGHT.lift;
    s.v.lerp(want, 1 - Math.exp(-FLIGHT.grip * (boosting ? 1.4 : 1) * dt));
  } else {
    s.v.addScaledVector(_f, s.throttle * FLIGHT.thrust * (boosting ? FLIGHT.boostFactor : 1) * dt);
    s.v.addScaledVector(_u, input.lift * FLIGHT.lift * dt);
    s.v.multiplyScalar(Math.exp(-FLIGHT.drag * dt));
    if (s.v.length() > FLIGHT.boost * 1.1) s.v.setLength(FLIGHT.boost * 1.1);
  }
  if (input.brake) s.v.multiplyScalar(Math.exp(-2.2 * dt));
  move(s, dt, world);
  steerHome(s, dt, world);
  s.gear += ((heightOverDeck(s, pad) < FLIGHT.gearHeight ? 1 : 0) - s.gear) * Math.min(1, dt * 1.5);
  return s;
}

/** Height of the ship's middle over the pad's deck while above it; Infinity elsewhere. */
export function heightOverDeck(s: FlightState, pad: { x: number; z: number }): number {
  return Math.hypot(s.p.x - pad.x, s.p.z - pad.z) < 30 ? s.p.y - COURIER.standHeight : Infinity;
}

/** Move by v·dt in sub-steps no longer than 1.5 m, pushing out of anything solid and bouncing off it. */
function move(s: FlightState, dt: number, world: CourierWorld) {
  const steps = Math.max(1, Math.ceil((s.v.length() * dt) / 1.5));
  const h = dt / steps;
  for (let i = 0; i < steps; i += 1) {
    s.p.addScaledVector(s.v, h);
    for (const offset of KEEL.offsets) {
      _s.set(0, 0, offset).applyQuaternion(s.q).add(s.p);
      const hit = sphereContact(world, _s.x, _s.y, _s.z, KEEL.radius);
      if (!hit) continue;
      s.p.x += hit.nx * hit.depth; s.p.y += hit.ny * hit.depth; s.p.z += hit.nz * hit.depth;
      const into = s.v.x * hit.nx + s.v.y * hit.ny + s.v.z * hit.nz;
      if (into < 0) {
        // Bounce off with a little give, and lose speed along the surface too.
        s.v.x -= 1.35 * into * hit.nx; s.v.y -= 1.35 * into * hit.ny; s.v.z -= 1.35 * into * hit.nz;
        s.v.multiplyScalar(0.8);
        s.shield = Math.min(1, s.shield + Math.min(1, -into / 25) + 0.15);
        s.impact = Math.max(s.impact, -into);
      }
    }
  }
}

/** Beyond the city's edge or above its ceiling the ship is turned back gently. */
function steerHome(s: FlightState, dt: number, world: CourierWorld) {
  const dx = s.p.x - world.centre.x, dz = s.p.z - world.centre.z, d = Math.hypot(dx, dz);
  if (d > world.border) s.v.addScaledVector(_t.set(-dx / d, 0, -dz / d), (d - world.border) * 0.8 * dt);
  if (s.p.y > world.ceiling) s.v.y -= (s.p.y - world.ceiling) * 0.8 * dt;
}

/** Start the autopilot that brings the ship home to the pad. */
export function engageAutopilot(s: FlightState): void {
  if (s.landed) return;
  s.autopilot = "approach";
  s.apBest = Infinity;
  s.apStuck = 0;
}

/**
 * The landing: climb to the safe height first, cross over to the pad there, come down to a hover point over it,
 * turn to the pad's heading and sink onto the deck with the gear down. Collisions still count on the way. A watch
 * notices when the ship stops getting closer (under the pad, against the tower) and sidesteps outwards before it
 * climbs on.
 */
function autopilot(s: FlightState, dt: number, world: CourierWorld, pad: { x: number; z: number; heading: number }): FlightState {
  const hover = _a.set(pad.x, COURIER.standHeight + FLIGHT.hover, pad.z);
  const to = _t.copy(hover).sub(s.p);
  const distance = to.length();
  const flat = Math.hypot(to.x, to.z);
  if (s.autopilot === "approach") {
    if (distance < s.apBest - 0.5) { s.apBest = distance; s.apStuck = 0; } else s.apStuck += dt;
    const want = _r;
    if (s.apStuck > 4) {
      // Stuck: out and away from the pad's middle (out from under it, off the tower's wall), then on again.
      const out = _u.set(s.p.x - pad.x, 0, s.p.z - pad.z);
      if (out.lengthSq() < 1) out.set(1, 0, 0);
      want.copy(out.normalize()).multiplyScalar(18);
      if (s.apStuck > 7) { s.apStuck = 0; s.apBest = distance; }
    } else if (flat > 25 && s.p.y < FLIGHT.safeHeight - 3) {
      // Climb first, barely moving sideways, so nothing of the city stands between the ship and the pad.
      want.set(to.x, 0, to.z).normalize().multiplyScalar(3).add(_u.set(0, 22, 0));
    } else if (flat > 25) {
      // Across at the safe height.
      want.set(to.x, 0, to.z).normalize().multiplyScalar(Math.min(FLIGHT.approach, flat * 0.7 + 2));
      want.y = (FLIGHT.safeHeight - s.p.y) * 1.2;
    } else {
      want.copy(to).normalize().multiplyScalar(Math.min(FLIGHT.approach, distance * 0.7 + 2));
    }
    s.v.lerp(want, 1 - Math.exp(-1.5 * dt));
    if (distance < 3 && s.v.length() < 4) s.autopilot = "hover";
  } else {
    s.v.lerp(_t.set(hover.x - s.p.x, 0, hover.z - s.p.z).multiplyScalar(1.5), 1 - Math.exp(-3 * dt));
    if (s.autopilot === "hover") {
      s.v.y += (hover.y - s.p.y) * 2 * dt - s.v.y * 2 * dt;
      if (alignedTo(s, pad.heading) && flat < 1) s.autopilot = "descend";
    } else {
      const above = s.p.y - COURIER.standHeight;
      s.v.y = -Math.min(FLIGHT.sink, Math.max(0.4, above * 0.6));
      if (above < 0.05) {
        s.p.set(pad.x, COURIER.standHeight, pad.z);
        s.q.setFromAxisAngle(_s.set(0, 1, 0), pad.heading);
        s.v.set(0, 0, 0); s.w.set(0, 0, 0);
        s.landed = true; s.autopilot = null; s.throttle = 0; s.gear = 1;
        return s;
      }
    }
  }
  // Turn to fly level towards the target (or to the pad's heading once there), wings level.
  const heading = s.autopilot === "approach" && flat > 8 ? Math.atan2(-(hover.x - s.p.x), -(hover.z - s.p.z)) : pad.heading;
  s.q.slerp(_q.setFromAxisAngle(_s.set(0, 1, 0), heading), 1 - Math.exp(-1.6 * dt));
  s.w.set(0, 0, 0);
  s.throttle += (Math.min(1, s.v.length() / FLIGHT.cruise) - s.throttle) * Math.min(1, dt * 2);
  move(s, dt, world);
  s.gear += ((heightOverDeck(s, pad) < FLIGHT.gearHeight ? 1 : 0) - s.gear) * Math.min(1, dt * 1.5);
  return s;
}

function alignedTo(s: FlightState, heading: number): boolean {
  const target = _q.setFromAxisAngle(_s.set(0, 1, 0), heading);
  return s.q.angleTo(target) < 0.05;
}

/** Ground speed for the HUD (m/s). */
export function speedOf(s: FlightState): number {
  return s.v.length();
}
