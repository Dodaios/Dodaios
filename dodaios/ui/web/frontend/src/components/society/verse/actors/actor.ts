/**
 * One live body on a deck: a cloned, tinted character with its own animation
 * mixer, walking the nav grid to where crew life sends it and doing what its
 * duty says once there.
 *
 * A body moves through phases: it stands up if it was seated, walks the path
 * (feet matched to the walk clip, easing round corners, stepping aside for
 * others), settles into the exact pose of its socket (seat, console stand,
 * bunk) with a short blend, then plays its activity. Waiting crew keep turning
 * toward the commander.
 *
 * The commander can also be driven directly (third person): while a
 * direction is held the body walks that way over the floor, sliding along
 * walls and stopping short of other people, whatever its goal says; let go
 * and it stands where it is. On the hoverboard (`ride`) the same keys glide
 * instead of walk: faster, coasting to a stop, lifted off the floor.
 */
import {
  AnimationMixer, Group, LoopOnce, LoopRepeat, Mesh, MeshBasicMaterial, PlaneGeometry, Quaternion, Vector3,
  type AnimationAction, type Bone, type Texture,
} from "three";
import type { Deck, NavGrid, Socket } from "../content/deck";
import { findPath, floorHeight, nearestWalkable, type Point } from "../nav/pathfind";
import { driveStep, type FreeAt } from "../nav/drive";
import type { Activity } from "../life/planner";
import { RENDER_ORDER, XRAY_LAYER } from "../engine/renderOrder";
import { disposeInstance, type CharacterInstance } from "./characters";
import { clipFor, SEATED, type Motion } from "./clips";
import { avoidance, BODY_RADIUS, lerpAngle, PathFollower, sidestep, turnPace, turnToward, wrapAngle, yawTo, type Neighbour } from "./locomotion";
import { RoomLight } from "./roomLight";
import { CloakRig } from "./cloak";
import { aimBone, solveElbow } from "../duel/figure";
import { absorb, BOARD_PATH_FACTOR, boardLean, deployStep, glide, HoverboardMesh, hoverHeight } from "./hoverboard";
import { hash32 } from "../life/crew";

export type Goal =
  | { kind: "socket"; socket: Socket; activity: Activity; faceCommander: boolean }
  | { kind: "point"; x: number; z: number }
  | { kind: "route"; points: readonly Socket[] }
  | { kind: "follow"; leaderId: string }
  | { kind: "leave"; at: Point };

export interface Pose { x: number; y: number; z: number; yaw: number }

export interface ActorContext {
  deck: Deck;
  now: number;
  reduced: boolean;
  /** Other bodies near this one. */
  neighbours: (self: Actor) => Neighbour[];
  /** Where another actor is (the companion follows the commander, waiting crew face them). */
  poseOf: (id: string) => (Pose & { moving: boolean; speed: number }) | null;
  commanderId: string;
}

/** The seat's root sits this far behind the seat centre (character contract). */
const SEAT_ROOT_BACK = 0.06;
/** Standing at a seat (waiting, talking) is this far behind the chair. */
const BESIDE_SEAT = 0.62;
const TURN_RATE = 5.5;
const FADE_S = 0.3;
const SETTLE_S = 0.45;
const REPLAN_FOLLOW_S = 0.4;
const HEEL_DISTANCE = 1.1;
/** A driven body turns this fast toward the held direction, rad/s. */
const DRIVE_TURN_RATE = 9;
/** Shift: a driven body hurries at this multiple of its pace. */
const RUN_FACTOR = 1.75;
/** A driven body walks above this speed and stands below the lower one, with no flicker in between, m/s. */
const DRIVE_WALK_ABOVE = 0.2;
const DRIVE_STAND_BELOW = 0.08;
/** A driven body stops this close to another person, metres between centres. */
const DRIVE_PERSONAL_SPACE = BODY_RADIUS * 1.7;
/** Materials whose surfaces make up a body's x-ray silhouette (character contract names). */
const SILHOUETTE = new Set(["M_Uniform", "M_Skin", "M_Hair", "M_Cap", "M_Shell", "M_Chassis", "M_SovCloak", "M_SovRobe"]);

type Phase = "idle" | "standing_up" | "walking" | "settling" | "settled" | "driven";

/** Seat surface height above the body's root (character contract `seatHeight`). */
export const SEAT_HEIGHT = 0.46;

/** Floor height near a point, from the nearest walkable cell (a chair's own cell is blocked). */
function floorNear(nav: NavGrid, x: number, z: number): number {
  const at = nearestWalkable(nav, { x, z }, 1.5);
  return at ? floorHeight(nav, at.x, at.z) : 0;
}

/**
 * The pose a body takes at a socket for an activity. A seat socket marks the
 * seat surface, so the seated root sits `seatHeight` below it (on the floor);
 * a seat socket on the floor is taken as the root itself. Pure.
 */
export function socketPose(deck: Pick<Deck, "sockets" | "nav">, socket: Socket, activity: Activity, seatHeight = SEAT_HEIGHT): Pose {
  const fx = Math.sin(socket.yaw);
  const fz = Math.cos(socket.yaw);
  if (socket.kind === "seat") {
    const floor = floorNear(deck.nav, socket.x, socket.z);
    if (SEATED.has(activity)) {
      const y = socket.y - floor > seatHeight * 0.5 ? socket.y - seatHeight : socket.y;
      return { x: socket.x - fx * SEAT_ROOT_BACK, y, z: socket.z - fz * SEAT_ROOT_BACK, yaw: socket.yaw };
    }
    // A console's own stand socket when the cook placed one, else behind the chair.
    const stand = deck.sockets.find((s) => s.kind === "stand" && s.id === socket.id);
    if (stand) return { x: stand.x, y: stand.y, z: stand.z, yaw: stand.yaw };
    const x = socket.x - fx * BESIDE_SEAT;
    const z = socket.z - fz * BESIDE_SEAT;
    return { x, y: floorNear(deck.nav, x, z), z, yaw: socket.yaw };
  }
  return { x: socket.x, y: socket.y, z: socket.z, yaw: socket.yaw };
}

const CAST_TMP = {
  a: new Vector3(), b: new Vector3(), aim: new Vector3(), flat: new Vector3(), lat: new Vector3(),
  s: new Vector3(), e: new Vector3(), h: new Vector3(), target: new Vector3(), pole: new Vector3(),
  elbow: new Vector3(), tip: new Vector3(), q0: new Quaternion(), q1: new Quaternion(), q2: new Quaternion(),
};

export class Actor {
  readonly group = new Group();
  readonly mixer: AnimationMixer;
  readonly light = new RoomLight();
  x = 0;
  y = 0;
  z = 0;
  yaw = 0;
  speed = 0;
  moving = false;
  /** Walked off the deck (to the lift); the layer removes it. */
  gone = false;
  /** The character contract's seat height. */
  seatHeight = SEAT_HEIGHT;
  /** Settled at its goal's socket. */
  get settledAt(): Socket | null {
    return this.phase === "settled" && this.goal?.kind === "socket" ? this.goal.socket : null;
  }

  private phase: Phase = "idle";
  private goal: Goal | null = null;
  private goalKey = "";
  private follower: PathFollower | null = null;
  private settle: { from: Pose; to: Pose; t: number } | null = null;
  private action: AnimationAction | null = null;
  private motion: Motion | null = null;
  private oneShotUntil = 0;
  private routeIndex = 0;
  private lastPlan = 0;
  private steer: Point | null = null;
  private steerRun = false;
  /** Shooter views: the way the body faces while driven (the view, `viewMode.bodyFacing`), and a walk played backwards. */
  private steerFace: { yaw: number; reverse: boolean } | null = null;
  private readonly clipNames: ReadonlySet<string>;
  /** The hoverboard, made the first time this body rides one. */
  private board: HoverboardMesh | null = null;
  private boardOn = false;
  /** Fold-out share of the board, 0..1. */
  private boardShare = 0;
  /** The board's velocity, m/s (it glides, so it is kept between frames). */
  private readonly boardV = { x: 0, z: 0 };
  private lean = { pitch: 0, roll: 0 };
  private turnRate = 0;
  private hover = 0;
  private clock = 0;
  private lastSync = 0;
  private lastYaw = 0;
  private reducedMotion = false;
  private readonly shadow: Mesh<PlaneGeometry, MeshBasicMaterial>;
  /** The skin's cloak, when its skeleton carries one (it trails the body's motion). */
  private readonly cloak: CloakRig | null;
  /**
   * A power being cast (Arc Storm): `level` 0..1 raises both arms toward `aim` (a unit direction in the world),
   * over whatever the clip plays. Null: the clip alone.
   */
  cast: { level: number; aim: Vector3 } | null = null;
  private castBones: Record<string, Bone> | null = null;

  constructor(
    readonly id: string,
    readonly instance: CharacterInstance,
    private readonly grid: NavGrid,
    readonly pace: number,
    shadow: Texture,
  ) {
    this.mixer = new AnimationMixer(instance.root);
    this.cloak = CloakRig.find(instance.root);
    const bones: Record<string, Bone> = {};
    for (const side of ["L", "R"]) {
      for (const n of ["UpperArm", "ForeArm", "Hand", "Fingers"]) {
        const b = instance.root.getObjectByName(`${n}_${side}`) as Bone | undefined;
        if (b) bones[`${n}_${side}`] = b;
      }
    }
    const chest = instance.root.getObjectByName("Chest") as Bone | undefined;
    if (chest && Object.keys(bones).length === 8) this.castBones = { ...bones, Chest: chest };
    this.clipNames = new Set(instance.clips.keys());
    // The silhouette needs the body's big shapes only, a few draw calls rather than every material.
    const outline = instance.meshes.filter((m) => !Array.isArray(m.material) && SILHOUETTE.has(m.material.name));
    for (const mesh of outline.length > 0 ? outline : instance.meshes) mesh.layers.enable(XRAY_LAYER);
    for (const mesh of instance.meshes) mesh.renderOrder = RENDER_ORDER.actor;
    this.group.add(instance.root);
    this.light.attach([...instance.materials.values()].flat());
    const drone = instance.model.kind === "drone" || instance.model.kind === "companion";
    const size = drone ? Math.max(0.5, Math.min(0.8, instance.model.height * 0.7)) : 0.95;
    this.shadow = new Mesh(new PlaneGeometry(size, size), new MeshBasicMaterial({
      map: shadow, color: 0x000000, transparent: true, opacity: 0.55, depthWrite: false, toneMapped: false,
    }));
    this.shadow.rotation.x = -Math.PI / 2;
    this.shadow.renderOrder = RENDER_ORDER.contactShadow;
    this.group.add(this.shadow);
  }

  private get isDrone(): boolean {
    return this.instance.model.kind === "drone" || this.instance.model.kind === "companion";
  }

  /** Top of the head above the root right now: lower seated, lowest in a bunk. */
  get height(): number {
    const standing = this.instance.model.height;
    if (this.motion === "sleep") return 0.45;
    if (this.motion && SEATED.has(this.motion)) return standing * 0.74;
    return standing;
  }

  /** A standing crew member at their post salutes once (the commander was promoted). */
  salute(): void {
    if (this.phase !== "settled" || this.isDrone || !this.motion || SEATED.has(this.motion) || this.motion === "sleep") return;
    if (this.goal?.kind !== "socket" || !clipFor("salute", this.clipNames)) return;
    this.oneShotUntil = this.playOnce("salute");
  }

  /**
   * Direct control: walk toward `direction` (unit length, on the floor) from
   * the next update on; null lets go. `face` turns the body that way instead
   * of along the walk (a shooter view: strafing, walking backwards).
   */
  drive(direction: Point | null, run = false, face: { yaw: number; reverse: boolean } | null = null): void {
    this.steer = direction;
    this.steerRun = run;
    this.steerFace = direction ? face : null;
  }

  /** Step onto the hoverboard (true) or fold it away (false). Drones never ride. */
  ride(on: boolean): void {
    if (on === this.boardOn) return;
    if (on && this.isDrone) return;
    if (on && !this.board) {
      this.board = new HoverboardMesh();
      this.light.attach(this.board.materials);
      this.group.add(this.board.group, this.board.glow);
    }
    this.boardOn = on;
    if (!on) { this.boardV.x = 0; this.boardV.z = 0; }
  }

  /** On the board (folded out or folding out). */
  get riding(): boolean {
    return this.boardOn;
  }

  /** Stop whatever walk or settle is in progress and stand where the body is (until the next goal). */
  halt(): void {
    this.steer = null;
    this.follower = null;
    this.settle = null;
    this.phase = "settled";
    this.speed = 0;
    this.boardV.x = 0;
    this.boardV.z = 0;
    this.play(this.isDrone ? "hover" : "idle");
  }

  /** Put the body somewhere at once (spawn, or a pose it already holds). */
  place(pose: Pose): void {
    this.x = pose.x;
    this.y = pose.y;
    this.z = pose.z;
    this.yaw = wrapAngle(pose.yaw);
    this.sync();
    this.cloak?.reset();
  }

  /** Change where the body is going; the same key keeps the current walk. `arrive` takes the pose at once. */
  setGoal(goal: Goal, key: string, deck: Pick<Deck, "sockets" | "nav">, arrive = false): void {
    if (key === this.goalKey) return;
    const wasSeated = this.phase === "settled" && this.motion !== null && SEATED.has(this.motion);
    this.goal = goal;
    this.goalKey = key;
    this.follower = null;
    this.settle = null;
    this.routeIndex = 0;
    if (arrive) {
      // Already there: take the pose without walking (the first look at a deck).
      if (goal.kind === "socket") {
        this.place(socketPose(deck, goal.socket, goal.activity, this.seatHeight));
        this.phase = "settled";
        this.play(goal.activity, true);
        return;
      }
    }
    if (wasSeated && clipFor("stand_up", this.clipNames)) {
      this.phase = "standing_up";
      this.oneShotUntil = this.playOnce("stand_up");
      return;
    }
    this.phase = "idle";
  }

  update(dtS: number, ctx: ActorContext): void {
    this.mixer.update(dtS);
    // Casting turns the body to face the way the power goes (unless the keys steer its facing).
    const cast = this.cast;
    if (cast && cast.level > 0.05 && !this.steerFace) {
      this.yaw = turnToward(this.yaw, Math.atan2(cast.aim.x, cast.aim.z), DRIVE_TURN_RATE, dtS);
    }
    const goal = this.goal;
    this.moving = false;
    this.clock = ctx.now / 1000;
    this.reducedMotion = ctx.reduced;
    this.boardShare = deployStep(this.boardShare, this.boardOn, dtS, ctx.reduced);
    const coasting = this.boardOn && (this.boardV.x !== 0 || this.boardV.z !== 0);
    if (this.steer || coasting) {
      this.driven(this.steer, dtS, ctx);
      this.light.update(ctx.deck, this.x, this.y, this.z, dtS);
      this.sync();
      this.castArms();
      this.cloak?.update(dtS, this.x, this.z, this.yaw, ctx.reduced);
      return;
    }
    if (this.phase === "driven") {
      // Let go: stand where the keys left the body until the next order.
      this.phase = "settled";
      this.speed = 0;
      this.play(this.isDrone ? "hover" : "idle");
    }
    if (goal && this.phase === "standing_up" && ctx.now >= this.oneShotUntil) this.phase = "idle";
    if (goal && this.phase === "idle") this.plan(goal, ctx);
    if (goal?.kind === "follow") this.follow(goal, dtS, ctx);
    if (this.phase === "walking") this.walk(dtS, ctx);
    if (this.phase === "settling") this.settleStep(dtS);
    if (this.phase === "settled" && goal?.kind === "socket") {
      if (goal.faceCommander) {
        const c = ctx.poseOf(ctx.commanderId);
        if (c) this.yaw = turnToward(this.yaw, yawTo(this.x, this.z, c.x, c.z), TURN_RATE * 0.5, dtS);
      }
      if (this.oneShotUntil && ctx.now >= this.oneShotUntil) {
        this.oneShotUntil = 0;
        this.play(goal.activity);
      }
    }
    this.light.update(ctx.deck, this.x, this.y, this.z, dtS);
    this.sync();
    this.castArms();
    this.cloak?.update(dtS, this.x, this.z, this.yaw, ctx.reduced);
  }

  /** Both fingertips in the world (for the power's bolts); false when the body has no arms. */
  fingertips(left: Vector3, right: Vector3): boolean {
    const b = this.castBones;
    if (!b) return false;
    for (const [side, out] of [["L", left], ["R", right]] as const) {
      const fingers = b[`Fingers_${side}`];
      const hand = b[`Hand_${side}`];
      fingers.getWorldPosition(out);
      // A little beyond the finger bone's root: the tips.
      hand.getWorldPosition(CAST_TMP.a);
      out.addScaledVector(CAST_TMP.b.subVectors(out, CAST_TMP.a).normalize(), 0.07);
    }
    return true;
  }

  /** Raise both arms toward the cast's aim, blended over the clip by its level. */
  private castArms(): void {
    const cast = this.cast;
    const b = this.castBones;
    if (!cast || !b || cast.level <= 0.001) return;
    const w = cast.level * cast.level * (3 - 2 * cast.level);
    const root = this.instance.root;
    root.updateMatrixWorld(true);
    const t = CAST_TMP;
    const aim = t.aim.copy(cast.aim);
    aim.y = Math.max(-0.35, Math.min(0.5, aim.y));
    aim.normalize();
    const flat = t.flat.set(aim.x, 0, aim.z).normalize();
    const lateral = t.lat.set(flat.z, 0, -flat.x); // the body's left
    for (const side of ["L", "R"] as const) {
      const upper = b[`UpperArm_${side}`];
      const fore = b[`ForeArm_${side}`];
      const hand = b[`Hand_${side}`];
      const fingers = b[`Fingers_${side}`];
      t.q0.copy(upper.quaternion);
      t.q1.copy(fore.quaternion);
      t.q2.copy(hand.quaternion);
      const s = upper.getWorldPosition(t.s);
      const e = fore.getWorldPosition(t.e);
      const h = hand.getWorldPosition(t.h);
      const a = s.distanceTo(e);
      const len = e.distanceTo(h);
      const sx = side === "L" ? 1 : -1;
      // Hands forward at chest height, a little apart, palms toward the target.
      const target = t.target.copy(s).addScaledVector(aim, (a + len) * 0.86).addScaledVector(lateral, -sx * 0.06);
      target.y -= 0.1;
      const pole = t.pole.set(0, -0.8, 0).addScaledVector(lateral, sx * 0.6).normalize();
      const elbow = solveElbow(s, target, a, len, pole, t.elbow);
      aimBone(upper, fore, elbow);
      aimBone(fore, hand, target);
      aimBone(hand, fingers, t.tip.copy(target).addScaledVector(aim, 0.3).addScaledVector(lateral, sx * 0.05));
      upper.quaternion.copy(t.q0.slerp(upper.quaternion, w));
      fore.quaternion.copy(t.q1.slerp(fore.quaternion, w));
      hand.quaternion.copy(t.q2.slerp(hand.quaternion, w));
      upper.updateMatrixWorld(true);
    }
  }

  private plan(goal: Goal, ctx: ActorContext): void {
    let to: Point | null = null;
    switch (goal.kind) {
      case "socket": {
        // The cook may name the aisle-side point to step in from (a bunk, a bench); else the floor nearest the pose.
        const approach = goal.socket.props.approach;
        const pose = socketPose(ctx.deck, goal.socket, goal.activity, this.seatHeight);
        to = Array.isArray(approach) && approach.length === 2 && approach.every((n) => typeof n === "number")
          ? nearestWalkable(this.grid, { x: approach[0] as number, z: approach[1] as number }, 2)
          : nearestWalkable(this.grid, { x: pose.x, z: pose.z }, 2);
        break;
      }
      case "point": to = { x: goal.x, z: goal.z }; break;
      case "leave": to = goal.at; break;
      case "route": {
        const next = goal.points[this.routeIndex % goal.points.length];
        to = next ? { x: next.x, z: next.z } : null;
        break;
      }
      case "follow": return;
    }
    const path = to ? findPath(this.grid, { x: this.x, z: this.z }, to) : null;
    if (!path || path.length < 2) {
      this.arrive(goal, ctx);
      return;
    }
    this.follower = new PathFollower(path);
    this.phase = "walking";
    this.play("walk");
  }

  private walk(dtS: number, ctx: ActorContext): void {
    const f = this.follower;
    if (!f || f.done) { this.arrive(this.goal, ctx); return; }
    const next = f.next as Point;
    const heading = yawTo(this.x, this.z, next.x, next.z);
    this.yaw = turnToward(this.yaw, heading, TURN_RATE, dtS);
    const steer = avoidance({ x: this.x, z: this.z, yaw: this.yaw }, ctx.neighbours(this));
    // Slow into tight turns so the feet stay under the body.
    this.speed = this.pace * (this.boardOn ? BOARD_PATH_FACTOR : 1) * steer.speed * turnPace(this.yaw, heading);
    let pos = f.advance({ x: this.x, z: this.z }, this.speed * dtS);
    pos = sidestep(this.grid, pos, this.yaw, steer.side * 0.6 * dtS);
    this.x = pos.x;
    this.z = pos.z;
    const ground = floorHeight(this.grid, this.x, this.z);
    this.y += (ground - this.y) * Math.min(1, dtS * 12);
    this.moving = true;
    if (this.boardOn) {
      // On the board the body stands and the board carries it.
      this.play("idle");
      if (this.action) this.action.timeScale = 1;
    } else {
      this.play("walk");
      if (this.action) this.action.timeScale = this.speed / Math.max(0.1, this.instance.walkSpeed);
    }
    if (f.done) this.arrive(this.goal, ctx);
  }

  /**
   * One frame under direct control: turn toward the held direction and walk it, sliding along walls.
   * On the board: glide toward it (or coast, with no direction).
   */
  private driven(direction: Point | null, dtS: number, ctx: ActorContext): void {
    if (this.phase !== "driven") {
      // The keys take over from any walk or settle in progress.
      this.phase = "driven";
      this.follower = null;
      this.settle = null;
      this.oneShotUntil = 0;
    }
    if (this.boardOn) { this.glideStep(direction, dtS, ctx); return; }
    if (!direction) return;
    const face = this.steerFace;
    const heading = face ? face.yaw : Math.atan2(direction.x, direction.z);
    this.yaw = turnToward(this.yaw, heading, DRIVE_TURN_RATE, dtS);
    const pace = this.pace * (this.steerRun ? RUN_FACTOR : 1) * turnPace(this.yaw, heading);
    const stride = face?.reverse ? -1 : 1;
    const from = { x: this.x, z: this.z };
    const near = ctx.neighbours(this);
    // Nobody walks through a person; drones are small enough to pass.
    const free: FreeAt = (p) => {
      for (const n of near) {
        if (n instanceof Actor && n.isDrone) continue;
        const d = Math.hypot(n.x - p.x, n.z - p.z);
        if (d < DRIVE_PERSONAL_SPACE && d < Math.hypot(n.x - from.x, n.z - from.z)) return false;
      }
      return true;
    };
    const to = driveStep(this.grid, from, direction.x * pace * dtS, direction.z * pace * dtS, free);
    const moved = Math.hypot(to.x - from.x, to.z - from.z);
    this.x = to.x;
    this.z = to.z;
    const ground = floorHeight(this.grid, this.x, this.z);
    this.y += (ground - this.y) * Math.min(1, dtS * 12);
    const speed = dtS > 0 ? moved / dtS : 0;
    this.speed += (speed - this.speed) * Math.min(1, dtS * 14);
    this.moving = moved > 1e-4;
    const walking = this.motion === "walk" || this.motion === "drive";
    if (this.speed > DRIVE_WALK_ABOVE || (walking && this.speed > DRIVE_STAND_BELOW)) {
      this.play("walk");
      if (this.action) this.action.timeScale = stride * Math.max(0.3, this.speed / Math.max(0.1, this.instance.walkSpeed));
    } else {
      this.play(this.isDrone ? "hover" : "idle");
      if (this.action) this.action.timeScale = 1;
    }
  }

  /** One frame on the board: speed toward the held direction, slide along walls, lose speed against them. */
  private glideStep(direction: Point | null, dtS: number, ctx: ActorContext): void {
    const v = glide(this.boardV, direction, this.steerRun, dtS);
    const fast = Math.hypot(v.x, v.z);
    const face = this.steerFace;
    const heading = face ? face.yaw : fast > 0.3 ? Math.atan2(v.x, v.z) : direction ? Math.atan2(direction.x, direction.z) : this.yaw;
    this.yaw = turnToward(this.yaw, heading, DRIVE_TURN_RATE, dtS);
    const from = { x: this.x, z: this.z };
    const near = ctx.neighbours(this);
    // Nobody rides through a person; drones are small enough to pass.
    const free: FreeAt = (p) => {
      for (const n of near) {
        if (n instanceof Actor && n.isDrone) continue;
        const d = Math.hypot(n.x - p.x, n.z - p.z);
        if (d < DRIVE_PERSONAL_SPACE && d < Math.hypot(n.x - from.x, n.z - from.z)) return false;
      }
      return true;
    };
    const wanted = { x: v.x * dtS, z: v.z * dtS };
    const to = driveStep(this.grid, from, wanted.x, wanted.z, free);
    const moved = { x: to.x - from.x, z: to.z - from.z };
    absorb(v, wanted, moved, dtS);
    this.x = to.x;
    this.z = to.z;
    const ground = floorHeight(this.grid, this.x, this.z);
    this.y += (ground - this.y) * Math.min(1, dtS * 12);
    const step = Math.hypot(moved.x, moved.z);
    const speed = dtS > 0 ? step / dtS : 0;
    this.speed += (speed - this.speed) * Math.min(1, dtS * 14);
    this.moving = step > 1e-4;
    this.play("idle");
    if (this.action) this.action.timeScale = 1;
  }

  private arrive(goal: Goal | null, ctx: ActorContext): void {
    this.follower = null;
    if (!goal) { this.phase = "idle"; this.play("idle"); return; }
    switch (goal.kind) {
      case "socket": {
        const to = socketPose(ctx.deck, goal.socket, goal.activity, this.seatHeight);
        this.settle = { from: { x: this.x, y: this.y, z: this.z, yaw: this.yaw }, to, t: ctx.reduced ? SETTLE_S : 0 };
        this.phase = "settling";
        if (SEATED.has(goal.activity) && clipFor("sit_down", this.clipNames) && !ctx.reduced) this.oneShotUntil = this.playOnce("sit_down");
        else this.play(goal.activity);
        return;
      }
      case "route":
        this.routeIndex++;
        this.phase = "idle";
        return;
      case "leave":
        this.gone = true;
        return;
      default:
        this.phase = "settled";
        this.play(this.isDrone ? "hover" : "idle");
    }
  }

  private settleStep(dtS: number): void {
    const s = this.settle;
    if (!s) { this.phase = "settled"; return; }
    s.t = Math.min(SETTLE_S, s.t + dtS);
    const k = s.t / SETTLE_S;
    const e = k * k * (3 - 2 * k);
    this.x = s.from.x + (s.to.x - s.from.x) * e;
    this.y = s.from.y + (s.to.y - s.from.y) * e;
    this.z = s.from.z + (s.to.z - s.from.z) * e;
    this.yaw = lerpAngle(s.from.yaw, s.to.yaw, e);
    if (k >= 1) {
      this.settle = null;
      this.phase = "settled";
      if (!this.oneShotUntil && this.goal?.kind === "socket") this.play(this.goal.activity);
    }
  }

  private follow(goal: Extract<Goal, { kind: "follow" }>, dtS: number, ctx: ActorContext): void {
    if (this.phase === "idle") {
      // At heel from the start: hover in place until the leader moves off.
      this.phase = "settled";
      this.play("hover");
    }
    const leader = ctx.poseOf(goal.leaderId);
    if (!leader) return;
    const d = Math.hypot(leader.x - this.x, leader.z - this.z);
    if (this.phase !== "walking" && d > HEEL_DISTANCE * 1.5 && ctx.now - this.lastPlan > REPLAN_FOLLOW_S * 1000) {
      this.lastPlan = ctx.now;
      // Heel: just behind the leader's shoulder.
      const back = { x: leader.x - Math.sin(leader.yaw) * HEEL_DISTANCE + Math.cos(leader.yaw) * 0.45, z: leader.z - Math.cos(leader.yaw) * HEEL_DISTANCE - Math.sin(leader.yaw) * 0.45 };
      const path = findPath(this.grid, { x: this.x, z: this.z }, back);
      if (path && path.length > 1) {
        this.follower = new PathFollower(path);
        this.phase = "walking";
        this.play("follow");
      }
    }
    if (this.phase === "walking" && this.follower && !this.follower.done && d < HEEL_DISTANCE) {
      this.follower = null;
      this.phase = "settled";
      this.play("hover");
    }
    if (this.phase === "settled") this.yaw = turnToward(this.yaw, leader.moving ? leader.yaw : yawTo(this.x, this.z, leader.x, leader.z), TURN_RATE * 0.4, dtS);
  }

  private play(motion: Motion, immediate = false): void {
    const resolved: Motion = motion === "walk" && this.isDrone
      ? (clipFor("drive", this.clipNames) ? "drive" : "follow")
      : motion;
    if (this.motion === resolved && this.action) return;
    const name = clipFor(resolved, this.clipNames) ?? clipFor("idle", this.clipNames) ?? clipFor("hover", this.clipNames);
    this.motion = resolved;
    if (!name) return;
    const clip = this.instance.clips.get(name);
    if (!clip) return;
    const next = this.mixer.clipAction(clip);
    next.reset();
    next.setLoop(LoopRepeat, Infinity);
    next.clampWhenFinished = false;
    next.timeScale = 1;
    // Crew idling side by side must not breathe in step.
    if (resolved !== "walk") next.time = ((hash32(this.id) % 1000) / 1000) * clip.duration;
    next.play();
    if (this.action && this.action !== next) {
      if (immediate) this.action.stop();
      else next.crossFadeFrom(this.action, FADE_S, false);
    }
    this.action = next;
  }

  /** Play a one-shot clip; returns when it ends (ms, performance clock). */
  private playOnce(motion: Motion): number {
    const name = clipFor(motion, this.clipNames);
    const clip = name ? this.instance.clips.get(name) : undefined;
    if (!clip) return 0;
    const next = this.mixer.clipAction(clip);
    next.reset();
    next.setLoop(LoopOnce, 1);
    next.clampWhenFinished = true;
    next.play();
    if (this.action && this.action !== next) next.crossFadeFrom(this.action, FADE_S * 0.6, false);
    this.action = next;
    this.motion = motion;
    return performance.now() + clip.duration * 1000;
  }

  private sync(): void {
    const board = this.board;
    if (board && (this.boardShare > 0 || board.group.visible)) {
      // Lean into speed and turns; the yaw change since the last frame gives the turn rate.
      const dt = this.clock - this.lastSync;
      if (dt > 0 && dt < 0.5) {
        const rate = wrapAngle(this.yaw - this.lastYaw) / dt;
        this.turnRate += (rate - this.turnRate) * Math.min(1, dt * 6);
      }
      const want = boardLean(this.speed, this.turnRate, this.reducedMotion);
      const k = Math.min(1, Math.max(0, dt) * 6);
      this.lean.pitch += (want.pitch - this.lean.pitch) * k;
      this.lean.roll += (want.roll - this.lean.roll) * k;
      this.hover = hoverHeight(this.boardShare, this.clock, this.speed, this.reducedMotion);
      const share = Math.min(1, this.boardShare);
      const pitch = this.lean.pitch * share;
      const roll = this.lean.roll * share;
      board.update(this.x, this.y + this.hover, this.y, this.z, this.yaw, this.boardShare, pitch, roll, this.speed, this.clock);
      this.instance.root.position.set(this.x, this.y + this.hover, this.z);
      this.instance.root.rotation.set(pitch, this.yaw, roll, "YXZ");
    } else {
      this.hover = 0;
      this.instance.root.position.set(this.x, this.y, this.z);
      this.instance.root.rotation.set(0, this.yaw, 0);
    }
    this.lastYaw = this.yaw;
    this.lastSync = this.clock;
    const lying = this.motion === "sleep";
    this.shadow.visible = !lying;
    // The root stands on the floor (seated too: the seat height is in the clip), so the shadow goes there.
    this.shadow.position.set(this.x, this.y + 0.006, this.z);
  }

  dispose(): void {
    this.mixer.stopAllAction();
    this.mixer.uncacheRoot(this.instance.root);
    this.shadow.geometry.dispose();
    this.shadow.material.dispose();
    this.board?.dispose();
    disposeInstance(this.instance);
  }
}
