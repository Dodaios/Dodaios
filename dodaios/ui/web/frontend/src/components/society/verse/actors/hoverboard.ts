/**
 * The commander's hoverboard: a small grav board that folds out under their
 * feet (B) and carries them across the deck several times faster than a walk.
 *
 * The motion is a glide, not a walk: the board speeds up toward the held
 * direction, coasts to a stop when the keys are let go, and loses its speed
 * against a wall. The body stands still on it (idle clip), lifted a hand's
 * breadth off the floor with a slow hover bob, leaning into speed and turns.
 *
 * The motion helpers are pure; `HoverboardMesh` is the three.js body.
 */
import {
  AdditiveBlending, BoxGeometry, CanvasTexture, CapsuleGeometry, CylinderGeometry, Group, Mesh,
  MeshBasicMaterial, MeshStandardMaterial, PlaneGeometry, type Material, type BufferGeometry, type Texture,
} from "three";
import { RENDER_ORDER } from "../engine/renderOrder";

/** Cruising speed on the board, m/s (a walk is about 1.3). */
export const BOARD_SPEED = 5.5;
/** Shift on the board: boost, m/s. */
export const BOARD_BOOST = 8.5;
/** Path walks (a click on the deck) ride at this multiple of the body's walking pace. */
export const BOARD_PATH_FACTOR = 4;
/** How fast the board reaches the held velocity, 1/s (higher = snappier). */
export const BOARD_ACCEL = 3.2;
/** How fast it coasts down once the keys are let go, 1/s. */
export const BOARD_COAST = 2.2;
/** Below this speed a coasting board has stopped, m/s. */
export const BOARD_STOPPED = 0.05;
/** The rider's feet stand this high above the floor, metres. */
export const BOARD_LIFT = 0.16;
/** Folding out or away takes this long, seconds. */
export const BOARD_DEPLOY_S = 0.32;

export interface Velocity { x: number; z: number }

/** The speed the board wants for the held keys, m/s. Pure. */
export function boardSpeed(boost: boolean): number {
  return boost ? BOARD_BOOST : BOARD_SPEED;
}

/**
 * One step of the board's velocity toward the wanted one (`direction` unit
 * length, or null to coast), written into `v`. Pure apart from `v`.
 */
export function glide(v: Velocity, direction: Velocity | null, boost: boolean, dtS: number): Velocity {
  const target = direction ? boardSpeed(boost) : 0;
  const tx = direction ? direction.x * target : 0;
  const tz = direction ? direction.z * target : 0;
  const k = 1 - Math.exp(-(direction ? BOARD_ACCEL : BOARD_COAST) * Math.max(0, dtS));
  v.x += (tx - v.x) * k;
  v.z += (tz - v.z) * k;
  if (!direction && Math.hypot(v.x, v.z) < BOARD_STOPPED) {
    v.x = 0;
    v.z = 0;
  }
  return v;
}

/**
 * After a step that went only part of the way (a wall, a person), keep just
 * the velocity the board really travelled with, so it does not push on into
 * the wall. Pure apart from `v`.
 */
export function absorb(v: Velocity, wanted: Velocity, moved: Velocity, dtS: number): Velocity {
  if (dtS <= 0) return v;
  const want = Math.hypot(wanted.x, wanted.z);
  const got = Math.hypot(moved.x, moved.z);
  if (want < 1e-6 || got >= want * 0.98) return v;
  v.x = moved.x / dtS;
  v.z = moved.z / dtS;
  return v;
}

/** The fold-out share after a step toward `on` (0 folded away, 1 out). Pure. */
export function deployStep(share: number, on: boolean, dtS: number, reduced: boolean): number {
  if (reduced) return on ? 1 : 0;
  const step = dtS / BOARD_DEPLOY_S;
  return on ? Math.min(1, share + step) : Math.max(0, share - step);
}

/** Smooth 0..1 ease of the fold-out share (the board springs out a touch past full size). Pure. */
export function deployScale(share: number): number {
  const s = Math.max(0, Math.min(1, share));
  // easeOutBack, a light overshoot.
  const c = 1.4;
  const t = s - 1;
  return 1 + (c + 1) * t * t * t + c * t * t;
}

/** The rider's lift and hover bob above the floor, metres. Pure. */
export function hoverHeight(share: number, timeS: number, speed: number, reduced: boolean): number {
  const s = Math.max(0, Math.min(1, share));
  if (reduced) return BOARD_LIFT * s;
  // A slow float at rest, almost none at speed (the board planes).
  const calm = 1 - Math.min(1, speed / BOARD_SPEED) * 0.7;
  return (BOARD_LIFT + Math.sin(timeS * 2.4) * 0.018 * calm) * s;
}

/** Lean of the rider and board: pitch forward with speed, roll into a turn, radians. Pure. */
export function boardLean(speed: number, turnRate: number, reduced: boolean): { pitch: number; roll: number } {
  if (reduced) return { pitch: 0, roll: 0 };
  const pitch = Math.min(1, speed / BOARD_BOOST) * 0.12;
  const roll = Math.max(-0.2, Math.min(0.2, -turnRate * Math.min(1, speed / BOARD_SPEED) * 0.06));
  return { pitch, roll };
}

function glowTexture(): Texture {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.3, "rgba(255,255,255,0.45)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const tex = new CanvasTexture(canvas);
  tex.needsUpdate = true;
  return tex;
}

/** Charcoal deck, gold rim, two amber thrusters and an underglow on the floor. */
export class HoverboardMesh {
  /** The board itself; it rides at the rider's feet and turns with them. */
  readonly group = new Group();
  /** The light it throws on the floor, kept flat on the floor under the board. */
  readonly glow: Mesh<PlaneGeometry, MeshBasicMaterial>;
  private readonly thrusters: MeshBasicMaterial;
  private readonly geometries: BufferGeometry[] = [];
  private readonly owned: Material[] = [];
  private readonly textures: Texture[] = [];

  constructor() {
    const deckMat = this.keepMat(new MeshStandardMaterial({ color: 0x17191e, metalness: 0.75, roughness: 0.32 }));
    const goldMat = this.keepMat(new MeshStandardMaterial({ color: 0xc9a24a, metalness: 0.9, roughness: 0.28, emissive: 0x3a2a08, emissiveIntensity: 0.6 }));
    const gripMat = this.keepMat(new MeshStandardMaterial({ color: 0x0c0d10, metalness: 0.2, roughness: 0.85 }));
    this.thrusters = this.keepMat(new MeshBasicMaterial({ color: 0xffc65a, transparent: true, opacity: 0.95, blending: AdditiveBlending, depthWrite: false, toneMapped: false }));

    // The deck: a capsule laid along the board's length, flattened.
    const deckGeo = this.keepGeo(new CapsuleGeometry(0.17, 0.62, 6, 16));
    const deck = new Mesh(deckGeo, deckMat);
    deck.rotation.x = Math.PI / 2;
    deck.scale.set(1, 1, 0.16);
    deck.position.y = 0;
    // The gold rim: the same shape a little larger, thinner, just under the deck.
    const rim = new Mesh(deckGeo, goldMat);
    rim.rotation.x = Math.PI / 2;
    rim.scale.set(1.07, 1.04, 0.07);
    rim.position.y = -0.018;
    // Grip pad on top, inset.
    const grip = new Mesh(this.keepGeo(new BoxGeometry(0.24, 0.006, 0.68)), gripMat);
    grip.position.y = 0.028;
    // A thin gold spine down the middle of the grip.
    const spine = new Mesh(this.keepGeo(new BoxGeometry(0.018, 0.008, 0.6)), goldMat);
    spine.position.y = 0.031;
    this.group.add(deck, rim, grip, spine);

    // Two thruster pods under nose and tail, glowing nozzles pointing down.
    const podGeo = this.keepGeo(new CylinderGeometry(0.07, 0.085, 0.05, 18));
    const nozzleGeo = this.keepGeo(new CylinderGeometry(0.058, 0.03, 0.012, 18));
    for (const z of [-0.33, 0.33]) {
      const pod = new Mesh(podGeo, deckMat);
      pod.position.set(0, -0.045, z);
      const nozzle = new Mesh(nozzleGeo, this.thrusters);
      nozzle.position.set(0, -0.074, z);
      nozzle.renderOrder = RENDER_ORDER.actor + 1;
      this.group.add(pod, nozzle);
    }
    for (const m of this.group.children) {
      const mesh = m as Mesh;
      if (mesh.renderOrder === 0) mesh.renderOrder = RENDER_ORDER.actor;
      mesh.castShadow = false;
    }

    const tex = glowTexture();
    this.textures.push(tex);
    this.glow = new Mesh(this.keepGeo(new PlaneGeometry(1.5, 1.9)), this.keepMat(new MeshBasicMaterial({
      map: tex, color: 0xffb340, transparent: true, opacity: 0, blending: AdditiveBlending, depthWrite: false, toneMapped: false,
    })));
    this.glow.rotation.x = -Math.PI / 2;
    this.glow.renderOrder = RENDER_ORDER.contactShadow + 1;
    this.group.visible = false;
    this.glow.visible = false;
  }

  /**
   * Place the board under the rider's feet (`x`, `feetY`, `z`) facing `yaw`,
   * with the floor at `floorY`, folded out by `share`, leaning by `pitch` and `roll`.
   */
  update(x: number, feetY: number, floorY: number, z: number, yaw: number, share: number, pitch: number, roll: number, speed: number, timeS: number): void {
    const shown = share > 0.001;
    this.group.visible = shown;
    this.glow.visible = shown;
    if (!shown) return;
    const s = deployScale(share);
    this.group.position.set(x, feetY - 0.034 * s, z);
    this.group.rotation.set(pitch, yaw, roll, "YXZ");
    this.group.scale.set(s, s, s);
    const flicker = 0.85 + Math.sin(timeS * 31) * 0.08 + Math.sin(timeS * 17.3) * 0.07;
    const thrust = Math.min(1, 0.55 + speed / BOARD_BOOST);
    this.thrusters.opacity = Math.min(1, share) * flicker * thrust;
    this.glow.position.set(x, floorY + 0.008, z);
    this.glow.rotation.set(-Math.PI / 2, 0, yaw);
    this.glow.material.opacity = Math.min(1, share) * (0.32 + 0.22 * thrust) * flicker;
  }

  dispose(): void {
    for (const g of this.geometries) g.dispose();
    for (const m of this.owned) m.dispose();
    for (const t of this.textures) t.dispose();
  }

  private keepGeo<T extends BufferGeometry>(g: T): T { this.geometries.push(g); return g; }
  private keepMat<T extends Material>(m: T): T { this.owned.push(m); return m; }

  /** Every material of the board (the rider's room light patches the lit ones). */
  get materials(): readonly Material[] { return this.owned; }
}
