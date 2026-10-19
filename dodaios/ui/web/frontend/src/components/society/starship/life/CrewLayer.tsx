/**
 * The crew on a deck: one android per agent, each living its day (crewLife)
 * and walking the deck (motion + navigation). Figures are imperative objects
 * updated in one frame callback; React only adds and removes them.
 */
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import { CylinderGeometry, Group, Mesh, MeshBasicMaterial, type Material } from "three";
import type { AgentRunState } from "../../data";
import { CrewFigure } from "../crew/figure";
import type { FaceAtlas, FaceLook, FaceMood } from "../crew/faceAtlas";
import type { Activity } from "../crew/rig";
import { findPath, isFree, nearestFree, type NavGrid } from "../nav/shipNav";
import type { DeckPlan, Vec2 } from "../plan/types";
import { captain } from "../shipStore";
import { seatedCrew } from "../../crewFeeds/seated";
import { decide, PlaceBook, type Intent, type RoundView } from "./crewLife";
import { BODY_GAP, stepAlong, turnTowards, type Body } from "./motion";

export interface CrewView {
  agentId: string;
  name: string;
  state: AgentRunState;
  division: string | null;
  face: FaceLook;
  accent: string;
  pips: number;
  gold: boolean;
  lead: boolean;
  ribbons: number;
}

export interface CrewPose { x: number; z: number; yaw: number; activity: Activity; headY: number; moving: boolean }

/** Where every crew member is, for name plates, the minimap and the captain's prompt. */
export const crewPoses = new Map<string, CrewPose>();

interface Walker extends Body {
  id: string;
  figure: CrewFigure;
  hit: Mesh;
  lookKey: string;
  intent: Intent | null;
  state: AgentRunState;
  turn: number;
  last: string | null;
  blockedS: number;
  arrived: boolean;
  seed: number;
  t: number;
}

const HIT_GEO = new CylinderGeometry(0.34, 0.34, 1.8, 8);
HIT_GEO.translate(0, 0.9, 0);
const HIT_MAT = new MeshBasicMaterial({ visible: false });

const PACE = 1.35;

function moodOf(state: AgentRunState, activity: Activity): FaceMood {
  if (activity === "talk") return "talking";
  if (state === "working") return "working";
  if (state === "waiting") return "waiting";
  if (state === "paused") return "paused";
  return "idle";
}

export function CrewLayer(props: {
  plan: DeckPlan;
  grid: NavGrid;
  crew: readonly CrewView[];
  rounds: ReadonlyMap<string, RoundView>;
  called: { place: string; agentIds: readonly string[] } | null;
  atlas: FaceAtlas;
  faceMaterial: Material;
  reduced: boolean;
  /** Agents that just joined: they beam in at the transporter and walk to their place. */
  newcomers: ReadonlySet<string>;
  onPick: (agentId: string) => void;
  onHover: (agentId: string | null) => void;
}) {
  const { plan, grid, crew, atlas, faceMaterial, reduced } = props;
  const group = useMemo(() => new Group(), []);
  const walkers = useRef(new Map<string, Walker>());
  const book = useMemo(() => new PlaceBook(), []);
  const ctxRef = useRef(props);
  ctxRef.current = props;

  useEffect(() => { book.retain(new Set(plan.places.map((p) => p.id))); }, [book, plan]);

  // Add, rebuild and remove figures as the crew changes.
  useEffect(() => {
    const live = walkers.current;
    const seen = new Set<string>();
    for (const member of crew) {
      seen.add(member.agentId);
      const lookKey = `${member.accent}|${member.pips}|${member.gold}|${member.lead}|${member.ribbons}`;
      const uv = atlas.cell(member.agentId, member.face);
      let w = live.get(member.agentId);
      if (w && w.lookKey !== lookKey) {
        group.remove(w.figure.group);
        w.figure.dispose();
        w.figure = new CrewFigure({ kind: "android", android: { accent: member.accent, pips: member.pips, gold: member.gold, lead: member.lead, ribbons: member.ribbons }, face: { material: faceMaterial, uv } });
        w.figure.group.add(w.hit);
        group.add(w.figure.group);
        w.lookKey = lookKey;
      }
      if (!w) {
        const figure = new CrewFigure({ kind: "android", android: { accent: member.accent, pips: member.pips, gold: member.gold, lead: member.lead, ribbons: member.ribbons }, face: { material: faceMaterial, uv } });
        const hit = new Mesh(HIT_GEO, HIT_MAT);
        hit.userData.agentId = member.agentId;
        figure.group.add(hit);
        group.add(figure.group);
        const fresh = props.newcomers.has(member.agentId);
        const start = fresh ? plan.arrival : (plan.seatOf.get(member.agentId) ?? nearestFree(grid, plan.arrival) ?? plan.arrival);
        w = {
          id: member.agentId, figure, hit, lookKey, x: start.x, z: start.z, yaw: Math.PI, path: [], speed: 0, phase: 0,
          intent: null, state: member.state, turn: 0, last: null, blockedS: 0, arrived: !fresh, seed: (hashSeed(member.agentId) % 1000) / 1000, t: 0,
        };
        live.set(member.agentId, w);
        // Everyone already aboard is simply at their place; a newcomer walks from the pad.
        settle(w, fresh);
      }
      w.state = member.state;
      atlas.setMood(member.agentId, moodOf(member.state, w.intent?.activity ?? "stand"));
    }
    for (const [id, w] of [...live]) {
      if (seen.has(id)) continue;
      group.remove(w.figure.group);
      w.figure.dispose();
      book.release(id);
      atlas.release(id);
      crewPoses.delete(id);
      seatedCrew.delete(id);
      live.delete(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [crew, atlas, faceMaterial, group]);

  // A rebuilt plan: everyone decides again (their places may have moved).
  useEffect(() => {
    for (const w of walkers.current.values()) { w.intent = null; w.path = []; }
  }, [plan]);

  useEffect(() => () => {
    for (const w of walkers.current.values()) { w.figure.dispose(); crewPoses.delete(w.id); seatedCrew.delete(w.id); }
    walkers.current.clear();
  }, []);

  function settle(w: Walker, walk: boolean) {
    const ctx = ctxRef.current;
    const member = ctx.crew.find((c) => c.agentId === w.id);
    if (!member) return;
    w.intent = decide({ agentId: w.id, state: member.state, division: member.division }, {
      plan: ctx.plan, book, nowMs: Date.now(), rounds: ctx.rounds, called: ctx.called, turn: w.turn++, last: w.last, at: { x: w.x, z: w.z },
    });
    w.last = w.intent.placeId;
    if (!walk || ctx.reduced) {
      w.x = w.intent.target.x; w.z = w.intent.target.z; w.yaw = w.intent.yaw; w.path = []; w.arrived = true;
    } else {
      w.path = findPath(ctx.grid, { x: w.x, z: w.z }, w.intent.target) ?? [];
      w.arrived = w.path.length === 0;
      if (w.arrived) { w.x = w.intent.target.x; w.z = w.intent.target.z; }
    }
  }

  const callKey = props.called ? `${props.called.place}|${props.called.agentIds.join(",")}` : "";
  const roundKey = [...props.rounds].map(([k, r]) => `${k}:${r.running}:${r.speakerId}`).join(",");
  // A change in state, rounds or calls makes the affected crew decide again.
  useEffect(() => {
    for (const member of crew) {
      const w = walkers.current.get(member.agentId);
      if (!w || !w.intent) continue;
      const stale = w.intent.reason === "work" ? member.state !== "working"
        : w.intent.reason === "wait" ? member.state !== "waiting"
          : w.intent.reason === "rest" ? member.state !== "paused"
            : member.state === "working" || member.state === "waiting" || member.state === "paused";
      if (stale) w.intent = null;
    }
  }, [crew]);
  useEffect(() => {
    for (const w of walkers.current.values()) {
      if (!w.intent) continue;
      if (w.intent.reason === "round" || w.intent.reason === "called" || w.intent.reason === "idle") w.intent = null;
    }
  }, [callKey, roundKey]);

  useFrame((_, rawDt) => {
    const dt = Math.min(0.1, rawDt);
    const now = Date.now();
    const list = [...walkers.current.values()];
    for (const w of list) {
      w.t += dt;
      if (!w.intent || (w.arrived && now > w.intent.untilMs)) {
        settle(w, true);
      }
      if (!w.arrived) {
        const arrived = stepAlong(w, dt, PACE, (nx, nz) => {
          if (Math.hypot(nx - captain.x, nz - captain.z) < BODY_GAP && Math.hypot(w.x - captain.x, w.z - captain.z) > Math.hypot(nx - captain.x, nz - captain.z)) return true;
          for (const o of list) {
            if (o === w || o.arrived) continue;
            const now2 = Math.hypot(nx - o.x, nz - o.z), before = Math.hypot(w.x - o.x, w.z - o.z);
            if (now2 < BODY_GAP && now2 < before) return true;
          }
          return false;
        });
        if (w.speed < 0.05 && !arrived) {
          w.blockedS += dt;
          if (w.blockedS > 1.4) {
            w.blockedS = 0;
            // Step aside and plan again from there.
            const side = { x: w.x + Math.cos(w.yaw) * 0.6, z: w.z - Math.sin(w.yaw) * 0.6 };
            if (isFree(grid, side) && w.intent) w.path = [side, ...(findPath(grid, side, w.intent.target) ?? [])];
          }
        } else w.blockedS = 0;
        if (arrived && w.intent) {
          w.arrived = true;
          w.x = w.intent.target.x; w.z = w.intent.target.z;
        }
      } else if (w.intent) {
        // Settle into the place's facing; a waiting agent turns to the captain when the captain comes close.
        let goal = w.intent.yaw;
        if (w.intent.reason === "wait" && Math.hypot(captain.x - w.x, captain.z - w.z) < 6) goal = Math.atan2(captain.x - w.x, captain.z - w.z);
        w.yaw = turnTowards(w.yaw, goal, dt, 5);
      }
      const activity: Activity = w.arrived ? (w.intent?.activity ?? "stand") : "walk";
      // Seated at its own console: its screen is worth reading.
      const atConsole = w.arrived && !!w.intent?.placeId && w.intent.placeId === ctxRef.current.plan.seatOf.get(w.id)?.id;
      if (atConsole) seatedCrew.add(w.id); else seatedCrew.delete(w.id);
      w.figure.apply({ activity, t: reduced ? 0 : w.t, phase: w.phase, speed: w.speed, seatY: w.intent?.seatY, seed: w.seed }, dt);
      w.figure.group.position.set(w.x, 0, w.z);
      w.figure.group.rotation.y = w.yaw;
      atlas.setMood(w.id, moodOf(w.state, activity));
      const pose = crewPoses.get(w.id);
      const headY = activity === "rest" ? 0.9 : activity === "sit" || activity === "type" ? 1.35 : 1.85;
      if (pose) { pose.x = w.x; pose.z = w.z; pose.yaw = w.yaw; pose.activity = activity; pose.headY = headY; pose.moving = !w.arrived; }
      else crewPoses.set(w.id, { x: w.x, z: w.z, yaw: w.yaw, activity, headY, moving: !w.arrived });
    }
    atlas.tick(now, reduced);
  });

  const pick = (e: ThreeEvent<MouseEvent>) => {
    const id = e.object.userData.agentId as string | undefined;
    if (!id) return;
    e.stopPropagation();
    props.onPick(id);
  };
  const over = (e: ThreeEvent<PointerEvent>) => {
    const id = e.object.userData.agentId as string | undefined;
    if (id) { e.stopPropagation(); props.onHover(id); }
  };
  return <primitive object={group} onClick={pick} onPointerOver={over} onPointerOut={() => props.onHover(null)} />;
}

function hashSeed(id: string): number {
  let h = 7;
  for (let i = 0; i < id.length; i += 1) h = (h * 33 + id.charCodeAt(i)) >>> 0;
  return h;
}

/** Points that a waiting body would turn to (for tests and the plates). */
export function facingCaptain(from: Vec2): number {
  return Math.atan2(captain.x - from.x, captain.z - from.z);
}
