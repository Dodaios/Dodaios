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
 * and it stands where it is.
 */
import {
  AnimationMixer, Group, LoopOnce, LoopRepeat, Mesh, MeshBasicMaterial, PlaneGeometry, type AnimationAction, type Texture,
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
const SILHOUETTE = new Set(["M_Uniform", "M_Skin", "M_Hair", "M_Cap", "M_Shell", "M_Chassis"]);

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
  private readonly clipNames: ReadonlySet<string>;
  private readonly shadow: Mesh<PlaneGeometry, MeshBasicMaterial>;

  constructor(
    readonly id: string,
    readonly instance: CharacterInstance,
    private readonly grid: NavGrid,
    readonly pace: number,
    shadow: Texture,
  ) {
    this.mixer = new AnimationMixer(instance.root);
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

  /** Direct control: walk toward `direction` (unit length, on the floor) from the next update on; null lets go. */
  drive(direction: Point | null, run = false): void {
    this.steer = direction;
    this.steerRun = run;
  }

  /** Put the body somewhere at once (spawn, or a pose it already holds). */
  place(pose: Pose): void {
    this.x = pose.x;
    this.y = pose.y;
    this.z = pose.z;
    this.yaw = wrapAngle(pose.yaw);
    this.sync();
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
    const goal = this.goal;
    this.moving = false;
    if (this.steer) {
      this.driven(this.steer, dtS, ctx);
      this.light.update(ctx.deck, this.x, this.y, this.z, dtS);
      this.sync();
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
    this.speed = this.pace * steer.speed * turnPace(this.yaw, heading);
    let pos = f.advance({ x: this.x, z: this.z }, this.speed * dtS);
    pos = sidestep(this.grid, pos, this.yaw, steer.side * 0.6 * dtS);
    this.x = pos.x;
    this.z = pos.z;
    const ground = floorHeight(this.grid, this.x, this.z);
    this.y += (ground - this.y) * Math.min(1, dtS * 12);
    this.moving = true;
    if (this.action) this.action.timeScale = this.speed / Math.max(0.1, this.instance.walkSpeed);
    if (f.done) this.arrive(this.goal, ctx);
  }

  /** One frame under direct control: turn toward the held direction and walk it, sliding along walls. */
  private driven(direction: Point, dtS: number, ctx: ActorContext): void {
    if (this.phase !== "driven") {
      // The keys take over from any walk or settle in progress.
      this.phase = "driven";
      this.follower = null;
      this.settle = null;
      this.oneShotUntil = 0;
    }
    const heading = Math.atan2(direction.x, direction.z);
    this.yaw = turnToward(this.yaw, heading, DRIVE_TURN_RATE, dtS);
    const pace = this.pace * (this.steerRun ? RUN_FACTOR : 1) * turnPace(this.yaw, heading);
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
      if (this.action) this.action.timeScale = Math.max(0.3, this.speed / Math.max(0.1, this.instance.walkSpeed));
    } else {
      this.play(this.isDrone ? "hover" : "idle");
      if (this.action) this.action.timeScale = 1;
    }
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
    this.instance.root.position.set(this.x, this.y, this.z);
    this.instance.root.rotation.set(0, this.yaw, 0);
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
    disposeInstance(this.instance);
  }
}
