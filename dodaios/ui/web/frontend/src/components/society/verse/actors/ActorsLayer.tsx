/**
 * Everyone alive on the deck on screen: crew, commander, companion drone and
 * the ship's company. The stage says who should be here and where they are
 * going (the cast); this layer loads and dresses their bodies, spawns
 * newcomers at the lift, sends leavers to the lift, and steps every body each
 * frame, publishing where they stand for the HUD and the screen feeds. In
 * third person it also hands the held keys to the commander and keeps the
 * camera on them.
 */
import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { CanvasTexture, Vector3, type Texture } from "three";
import { ArcStorm } from "../abilities/arcStorm";
import { ArcSound } from "../abilities/arcSound";
import type { Deck } from "../content/deck";
import type { StageRuntime } from "../runtime";
import { seatedCrew } from "../../crewFeeds/seated";
import { worldToPlate } from "../engine/plateMath";
import { bodyFacing } from "../engine/realtime/viewMode";
import { floorHeight, nearestWalkable } from "../nav/pathfind";
import { hash32 } from "../life/crew";
import { Actor, socketPose, type ActorContext, type Goal, type Pose } from "./actor";
import type { BodyKind, CharacterLibrary } from "./characters";
import { applyLook, type Look } from "./look";

export interface CastMember {
  id: string;
  body: BodyKind;
  /** A specific model of that kind (drones). */
  model?: string;
  look: Look | null;
  goal: Goal;
  /** Changes whenever the goal does. */
  goalKey: string;
  /** Walking pace, m/s. */
  pace: number;
  /** Where a body new to the deck appears: already in place, out of the lift, or at a spawn socket. */
  entry: "placed" | "lift" | "spawn";
}

interface Props {
  runtime: StageRuntime;
  deck: Deck;
  library: CharacterLibrary;
  cast: readonly CastMember[];
  commanderId: string;
  reduced: boolean;
  /** When the crew last had cause to salute (performance clock, ms); a new value makes them salute. */
  saluteAt: number;
}

function shadowTexture(): Texture {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, "rgba(255,255,255,0.9)");
  g.addColorStop(0.35, "rgba(255,255,255,0.55)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  return new CanvasTexture(canvas);
}

function liftPoint(deck: Deck): Pose | null {
  const lift = deck.sockets.find((s) => s.kind === "lift");
  return lift ? { x: lift.x, y: lift.y, z: lift.z, yaw: lift.yaw } : null;
}

/**
 * Which way a body placed at (x, z) faces: the spawn or lift it stands at
 * (a spawn's own facing; out of the lift doors), else toward −Z, the deck's
 * forward. Pure.
 */
export function arrivalYaw(deck: Pick<Deck, "sockets">, x: number, z: number): number {
  let best: { yaw: number; d: number } | null = null;
  for (const s of deck.sockets) {
    if (s.kind !== "spawn" && s.kind !== "lift") continue;
    const d = Math.hypot(s.x - x, s.z - z);
    if (d <= 2.5 && (!best || d < best.d)) best = { yaw: s.yaw, d };
  }
  return best ? best.yaw : Math.PI;
}

function spawnPoint(deck: Deck, entry: CastMember["entry"]): Pose | null {
  if (entry === "spawn") {
    const spawn = deck.sockets.find((s) => s.kind === "spawn" && s.id.startsWith("arrival")) ?? deck.sockets.find((s) => s.kind === "spawn");
    if (spawn) return { x: spawn.x, y: spawn.y, z: spawn.z, yaw: spawn.yaw };
  }
  return liftPoint(deck);
}

export function ActorsLayer({ runtime, deck, library, cast, commanderId, reduced, saluteAt }: Props) {
  const scene = useThree((s) => s.scene);
  const gl = useThree((s) => s.gl);
  // The commander's power: the bolts, their light and their sound.
  const power = useMemo(() => ({
    storm: new ArcStorm(), sound: new ArcSound(), aim: new Vector3(), left: new Vector3(), right: new Vector3(), hands: [] as Vector3[],
  }), []);
  useEffect(() => {
    scene.add(power.storm.group);
    return () => {
      scene.remove(power.storm.group);
      power.storm.dispose();
      power.sound.dispose();
    };
  }, [scene, power]);
  const actors = useRef(new Map<string, Actor>());
  const loading = useRef(new Set<string>());
  /** Cast members who walked off on purpose (to the lift) and must not be spawned again for the same goal. */
  const departed = useRef(new Set<string>());
  const castRef = useRef(cast);
  castRef.current = cast;
  const shadow = useMemo(shadowTexture, []);
  const alive = useRef(true);

  // Bring the bodies in line with the cast.
  useEffect(() => {
    const wanted = new Map(cast.map((m) => [m.id, m]));
    for (const key of departed.current) if (!cast.some((m) => `${m.id}|${m.goalKey}` === key)) departed.current.delete(key);
    for (const member of cast) {
      if (departed.current.has(`${member.id}|${member.goalKey}`)) continue;
      const actor = actors.current.get(member.id);
      if (actor) {
        if (member.look) applyLook(actor.instance, library.contract, member.look);
        actor.setGoal(member.goal, member.goalKey, deck);
        continue;
      }
      if (loading.current.has(member.id)) continue;
      const seed = hash32(member.id);
      const model = library.model(member.body, member.model, seed) ?? (member.body === "technician" ? library.model("officer", undefined, seed) : undefined);
      if (!model) continue;
      loading.current.add(member.id);
      library.instantiate(model).then((instance) => {
        loading.current.delete(member.id);
        const now = castRef.current.find((m) => m.id === member.id);
        if (!alive.current || !now || actors.current.has(member.id)) return;
        const actor = new Actor(member.id, instance, deck.nav, now.pace, shadow);
        actor.seatHeight = library.contract.seatHeight;
        if (now.look) applyLook(instance, library.contract, now.look);
        const arrive = now.entry === "placed" || reduced;
        const start = arrive ? null : spawnPoint(deck, now.entry);
        if (start) actor.place(start);
        else if (now.goal.kind === "socket") actor.place(socketPose(deck, now.goal.socket, now.goal.activity, actor.seatHeight));
        else if (now.goal.kind === "point") actor.place({ x: now.goal.x, y: 0, z: now.goal.z, yaw: arrivalYaw(deck, now.goal.x, now.goal.z) });
        else if (now.goal.kind === "follow") {
          // At the leader's heel: where the leader stands, or is about to.
          const leaderId = now.goal.leaderId;
          const leaderGoal = castRef.current.find((m) => m.id === leaderId)?.goal;
          const leader = runtime.poses.get(leaderId) ?? (leaderGoal?.kind === "point" ? { x: leaderGoal.x, y: 0, z: leaderGoal.z } : null);
          const at = leader ? nearestWalkable(deck.nav, { x: leader.x - 0.9, z: leader.z + 0.6 }, 3) : null;
          actor.place(at ? { x: at.x, y: floorHeight(deck.nav, at.x, at.z), z: at.z, yaw: 0 } : (liftPoint(deck) ?? { x: 0, y: 0, z: 0, yaw: 0 }));
        } else if (now.goal.kind === "route" && now.goal.points[0]) {
          const p = now.goal.points[0];
          actor.place({ x: p.x, y: p.y, z: p.z, yaw: p.yaw });
        }
        actor.setGoal(now.goal, now.goalKey, deck, !start);
        actors.current.set(member.id, actor);
        scene.add(actor.group);
      }, (error: unknown) => {
        loading.current.delete(member.id);
        console.warn("Verse body failed to load", member.id, error);
      });
    }
    // Whoever left the cast walks to the lift (or is simply gone with reduced motion).
    const lift = liftPoint(deck);
    for (const [id, actor] of actors.current) {
      if (wanted.has(id)) continue;
      if (lift && !reduced && id !== commanderId) actor.setGoal({ kind: "leave", at: { x: lift.x, z: lift.z } }, `leave:${id}`, deck);
      else actor.gone = true;
    }
  }, [cast, deck, library, scene, shadow, reduced, runtime, commanderId]);

  // A new deck or library: everyone goes.
  useEffect(() => {
    alive.current = true;
    const own = actors.current;
    return () => {
      alive.current = false;
      for (const actor of own.values()) {
        scene.remove(actor.group);
        actor.dispose();
        seatedCrew.delete(actor.id);
        runtime.poses.delete(actor.id);
      }
      own.clear();
    };
  }, [deck, library, scene, runtime]);

  useEffect(() => () => shadow.dispose(), [shadow]);

  useEffect(() => {
    if (!saluteAt || saluteAt < performance.now() || reduced) return;
    for (const [id, actor] of actors.current) if (id !== commanderId) actor.salute();
  }, [saluteAt, reduced, commanderId]);

  // Built once per deck: which seats have a screen (the feeds poll only consoles somebody sits at).
  const screenSeats = useMemo(() => new Set(deck.sockets.filter((s) => s.kind === "screen").map((s) => s.id)), [deck]);
  // The frame loop allocates nothing per actor: one shared context and neighbour list, actors as their own poses.
  const nearby = useRef<Actor[]>([]);
  const ctx = useMemo<ActorContext>(() => ({
    deck, now: 0, reduced, commanderId,
    neighbours: (self) => {
      const out = nearby.current;
      out.length = 0;
      for (const a of actors.current.values()) {
        if (a !== self && Math.abs(a.x - self.x) <= 1.5 && Math.abs(a.z - self.z) <= 1.5) out.push(a);
      }
      return out;
    },
    poseOf: (id) => actors.current.get(id) ?? null,
  }), [deck, reduced, commanderId]);
  // The commander's walking direction, refilled every frame (the actor reads it within the same frame).
  const steering = useMemo(() => ({ x: 0, z: 0 }), []);
  const facing = useMemo(() => ({ yaw: 0, reverse: false }), []);

  useFrame((_, dt) => {
    // A slow frame still moves people at their pace; a stall (a hidden tab) does not teleport them.
    const dtS = Math.min(dt, 0.25);
    ctx.now = performance.now();
    // Third person: the held movement keys walk the commander.
    const control = runtime.control;
    const lead = actors.current.get(commanderId);
    const steer = control.mode !== "follow" || runtime.duelActive ? null : runtime.eye ? control.directionFrom(runtime.shoulder, steering) : control.direction(steering);
    // At eye level the commander faces the view while walking (shooter strafing); on the plate, the way they walk.
    lead?.drive(steer, control.run, steer && runtime.eye ? bodyFacing(runtime.shoulder.yaw, steer, facing) : null);
    // A duel ended: the commander stands where they finished it, on the deck's walkable floor.
    const placed = runtime.placeCommander;
    if (lead && placed) {
      runtime.placeCommander = null;
      const at = nearestWalkable(deck.nav, { x: placed.x, z: placed.z }, 3) ?? placed;
      lead.halt();
      lead.place({ x: at.x, y: floorHeight(deck.nav, at.x, at.z), z: at.z, yaw: placed.yaw });
    }
    // In a duel the duellist's own body stands in for the commander's.
    if (lead) lead.group.visible = !runtime.duelActive && !(runtime.eye && runtime.commanderHidden);
    // Arc Storm: held, the arms rise toward the aim (the view's at eye level, the body's facing on the plate).
    const held = runtime.power && !runtime.duelActive && !!lead;
    const level = power.storm.rise(dtS, held);
    if (lead) {
      if (runtime.eye) {
        const sh = runtime.shoulder;
        power.aim.set(Math.sin(sh.yaw) * Math.cos(sh.pitch), -Math.sin(sh.pitch), Math.cos(sh.yaw) * Math.cos(sh.pitch));
      } else {
        power.aim.set(Math.sin(lead.yaw), -0.06, Math.cos(lead.yaw));
      }
      lead.cast = level > 0 ? { level, aim: power.aim } : null;
    }
    const area = runtime.duelActive ? runtime.duelArea : null;
    for (const actor of actors.current.values()) {
      actor.update(dtS, ctx);
      if (actor !== lead) actor.group.visible = !area || actor.x < area.x0 || actor.x > area.x1 || actor.z < area.z0 || actor.z > area.z1;
      if (actor.gone) {
        const member = castRef.current.find((m) => m.id === actor.id);
        if (member) departed.current.add(`${member.id}|${member.goalKey}`);
        scene.remove(actor.group);
        actor.dispose();
        actors.current.delete(actor.id);
        runtime.poses.delete(actor.id);
        seatedCrew.delete(actor.id);
        continue;
      }
      const pose = runtime.poses.get(actor.id);
      if (pose) {
        pose.x = actor.x; pose.y = actor.y; pose.z = actor.z; pose.yaw = actor.yaw; pose.height = actor.height; pose.moving = actor.moving;
      } else {
        runtime.poses.set(actor.id, { id: actor.id, x: actor.x, y: actor.y, z: actor.z, yaw: actor.yaw, height: actor.height, moving: actor.moving });
      }
      const at = actor.settledAt;
      if (at && at.kind === "seat" && screenSeats.has(at.id)) seatedCrew.add(actor.id);
      else seatedCrew.delete(actor.id);
    }
    power.hands.length = 0;
    const eyeCam = runtime.eye?.camera;
    if (lead && level > 0 && eyeCam && runtime.shoulder.firstShare > 0.5) {
      // First person: from where the person's own hands are on screen, low left and right of the view.
      eyeCam.updateMatrixWorld();
      power.left.set(-0.2, -0.2, -0.5).applyMatrix4(eyeCam.matrixWorld);
      power.right.set(0.2, -0.2, -0.5).applyMatrix4(eyeCam.matrixWorld);
      power.hands.push(power.left, power.right);
    } else if (lead && level > 0 && lead.fingertips(power.left, power.right)) power.hands.push(power.left, power.right);
    // Seen from far above (the plate) the bolts are drawn thicker to read at that scale.
    power.storm.update(dtS, held, power.hands, power.aim, lead?.y ?? 0, gl, runtime.eye ? 1 : 3);
    power.sound.update(reduced ? level * 0.6 : level, held);
    runtime.stats.actors = actors.current.size;
    // The third-person camera stays on the commander, leading them a little while they walk and easing back onto
    // them when they stop; a drag looks around until they walk again.
    const view = runtime.view;
    if (lead?.moving) control.looking = false;
    if (lead && !lead.gone && !runtime.eye && control.mode === "follow" && view.measured && (!control.looking || control.reframe || view.leading)) {
      const p = worldToPlate(deck.camera, lead.x, lead.y + lead.height * 0.5, lead.z);
      if (control.reframe) {
        control.reframe = false;
        control.looking = false;
        view.reframeOn(p.u, p.v);
      } else {
        view.follow(p.u, p.v, dtS);
      }
    }
  }, -1);

  return null;
}
