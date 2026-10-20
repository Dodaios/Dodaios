/**
 * Agents living in the office. Working agents sit at their screens, waiting
 * agents stand and wave at their desk, paused agents nap, and idle agents
 * live round their team's studio: their desk, the studio board, a teammate's
 * desk, now and then a coffee or the couch. A running round of a team brings
 * its free members to their studio board, and a message one agent sent
 * another is walked over (teamwork.ts): both are real, nothing is staged.
 *
 * The office is a projection of the roster: run state comes from the backend,
 * everything else is client-side choreography that costs no tokens and never
 * starts or stops work.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { DoubleSide, Vector3, type Group, type Mesh, type MeshBasicMaterial } from "three";
import { useT } from "@/i18n";
import type { SocietyAgent } from "../data";
import type { FigureDrive, FigureMode } from "../figures/FigureRig";
import { ToyFigure } from "./ToyFigure";
import { GigiFlyer } from "./GigiFlyer";
import { followAnchor, type GigiFlightMode } from "./gigiFlight";
import { useEventStore } from "@/store/events";
import { SEAT_HEIGHT, toyLookFor } from "./toyFigureModel";
import { OFFICE } from "./officePalette";
import type { DeskSlot, OfficeLayout, Point } from "./officeLayout";
import { findPath, isWalkable, type NavGrid } from "./officeNav";
import { AgentFollower } from "../companion/AgentFollower";
import { useCompanionPet } from "../companion/companionPetStore";
import { companionFlies } from "../companion/petCompanions";
import { resolveCompanion } from "../companion/appearance";
import type { TrailPoint } from "../companion/trail";
import { clearOfBodies, hurryPaceFor, stepMover, turnToward, WALK_SPEED, type Mover } from "./officeMotion";
import { advanceWalk, beginWalk, type Walk } from "./officeWalk";
import {
  createRng, dwellAfter, HANDOFF_DWELL_MS, PERSON_CROWD_M, planFor, planStillValid, shownActivity, type ActivityKind, type Plan, type Pose, type SpotBook,
} from "./officeBehavior";
import { homeStudio, mateDesks, studiosOf } from "./officeTeams";
import { boardWatch, pendingHandoff, roundFor, roundRole, steadyRole, useTeamwork, type RoleMemory } from "./teamwork";
import { useTeamRounds } from "./useTeamRounds";
import { StudioBoards } from "./StudioBoards";
import { player, useOfficeStore, type Summon } from "./officeStore";
import { agentPositions, bodiesNear, companions, placeAgent, seatedAtDesk, walkerDebug } from "./walkerRegistry";
import { AgentBubble } from "./OfficeBubbles";
import type { ChatLine } from "./deskChat";
import type { DeskChat } from "./useDeskChats";
import { officeTalkChat, useOfficeTalk } from "./officeTalk";
import { deliverySpot, ERRAND_SPEED, useErrandFeed, useGigiErrands } from "./gigiErrands";
import { isPaneAgentId, plateTitle } from "./codingFloor";
import { agentLogoAsset } from "@/components/agentic/AgentMark";
import { LevelChip } from "../progression/LevelHud";
import { plateDetail, type PlateDetail } from "./namePlate";
import type { Camera } from "three";
import { useThree } from "@react-three/fiber";
import { joinPlates, plateSeating, reportPlate, type ScreenRect } from "./plateCrowd";
import { isSpeaking, lastSpokeBy, SPOKE_LINGER_MS } from "./teamwork";
import { agentSubject, petSubject } from "../progression/progressionApi";
import { useProgression } from "../progression/progressionStore";
import { useDressedFigure } from "../progression/regalia/dress";

/** The agent's symbol walks behind it as a little pet, about a fifth of its height. */
export const PET_SIZE_M = 0.26;
const PET_FOLLOW_M = 0.7;

/** The person's character as a mover for Gigi to follow (the body object itself, mutated every frame). */
const PLAYER_OWNER = { current: player };
/** Farther than this from the person's shoulder and Gigi flies back first instead of hovering beside them. */
const FOLLOW_CATCH_M = 1;

/** Height of the lead's nameplate: above a flying companion, or low above a pet on the floor. */
const LEAD_PLATE_FLYING_M = 1.75;
const LEAD_PLATE_ON_FLOOR_M = 0.85;

/** The person's pet keeps this far from every agent while it follows the person. */
const PET_CLEAR_M = 0.5;
/** Bodies further than this from a walker play no part in its steering or its detours. */
const BODY_RANGE_M = 7;

// Dev-only: what every walker, team round and studio board is doing right now.
//   __officeLife.walkers()   one row per agent: team, role in a running round, plan, phase, target, stuck seconds,
//                            walkS / speed (seconds and average m/s on the current walk, by the frame time the
//                            walker really got: with the frame loop running, __officeStep's dtMs is not that time),
//                            and how often it took a detour (replans), was placed (rescues), gave a walk up (blocked)
//                            or had its route repaired (repaths)
//   __officeLife.walker(id)  the same for one agent
//   __officeLife.stuck()     the walkers that needed a detour or a placement, or gave a walk up, so far
//   __officeLife.teamwork()  rounds by team (running, speaker, lines) and the messages still to be walked over
//   __officeLife.boards()    the team ids whose studio board is live (near the camera)
if (import.meta.env.DEV && typeof window !== "undefined") {
  Object.assign(window, { __officeLife: {
    walkers: () => [...walkerDebug.values()],
    walker: (id: string) => walkerDebug.get(id) ?? null,
    stuck: () => [...walkerDebug.values()].filter((w) => w.replans + w.rescues + w.blocked > 0),
    teamwork: () => { const { rounds, handoffs } = useTeamwork.getState(); return { rounds, handoffs }; },
    boards: () => [...boardWatch.near()],
    store: useTeamwork,
  } });
}

/** Every figure shares one toy scale, so desks and couches read the same everywhere. */
export const OFFICE_FIGURE_HEIGHT_M = 1.3;

/** Pose → animation clip. Seated work uses the seated clip; the monitor shows the typing. */
export const POSE_CLIP: Record<Pose, FigureMode> = { sit: "sit", work: "sit", stand: "idle", wave: "wave", talk: "talk", sleep: "sleep" };

/** The seat-top height under a seated agent, per activity; the figure puts its hips exactly there. */
export function seatHeightFor(kind: ActivityKind): number {
  if (kind === "couch" || kind === "nap") return SEAT_HEIGHT.couch;
  if (kind === "beanbag") return SEAT_HEIGHT.beanbag;
  if (kind === "meeting") return SEAT_HEIGHT.meeting;
  return SEAT_HEIGHT.chair;
}

/** Nameplate scale by camera distance: readable up close, compact in the overview, never huge. */
export function plateScale(distance: number): number {
  return Math.min(1.05, Math.max(0.8, 24 / Math.max(1, distance)));
}

const RING_COLOUR = { working: OFFICE.ringWorking, idle: OFFICE.ringIdle, waiting: OFFICE.ringWaiting, paused: OFFICE.ringPaused } as const;

/** Jarvis is not a person in the office: it is the person's pet (Gigi by default), flying or on the floor. */
function gigiModeFor(pose: Pose | null, travelling: boolean): GigiFlightMode {
  if (travelling || !pose) return "idle";
  if (pose === "sit" || pose === "work") return "work";
  if (pose === "stand") return "idle";
  return pose;
}

function Nameplate({ agent, activity, selected, onSelect, height = OFFICE_FIGURE_HEIGHT_M + 0.35 }: {
  agent: SocietyAgent; activity: ActivityKind | null; selected: boolean; onSelect: (id: string) => void; height?: number;
}) {
  const t = useT();
  const plate = useRef<HTMLButtonElement>(null);
  const wrap = useRef<HTMLSpanElement>(null);
  const anchor = useRef<Group>(null);
  const last = useRef(0);
  const world = useMemo(() => new Vector3(), []);
  const [open, setOpen] = useState(false);
  // The pointer on the figure itself counts like the pointer on its plate.
  const pointedAt = useOfficeStore((s) => s.hover?.kind === "agent" && s.hover.id === agent.agentId);
  const shown = useRef<PlateDetail>("dot");
  // What the distance rule alone says (it has its own memory); a crowd may still keep the plate a dot.
  const ruled = useRef<PlateDetail>("dot");
  const wanted = useRef({ pointed: false, selected: false });
  wanted.current = { pointed: open || pointedAt, selected };
  // Whoever speaks in a team round keeps its plate in a crowd, with room for the bubble above it.
  const speaking = useTeamwork((s) => isSpeaking(s.rounds, agent.agentId));
  const spokeAt = useTeamwork((s) => lastSpokeBy(s.rounds, agent.agentId)?.atMs ?? 0);
  const voice = useRef({ speaking, spokeAt });
  voice.current = { speaking, spokeAt };
  const measured = useRef({ w: 0, h: 0, tick: 0 });
  const scene = useThree((s) => s.scene);
  const onScreen = useMemo(() => new Vector3(), []);
  // Plates are seated per stage (two offices can be awake at once); this one leaves its stage's seating on unmount.
  useEffect(() => joinPlates(scene), [scene]);
  useFrame(({ camera, size, clock }) => {
    if (!anchor.current || !plate.current || !wrap.current) return;
    anchor.current.getWorldPosition(world);
    const cameraDistance = camera.position.distanceTo(world);
    const personDistance = Math.hypot(world.x - player.x, world.z - player.z);
    const scale = plateScale(cameraDistance);
    // Far away the agent is a dot; the plate opens near the camera or the person, and for the one pointed at or selected.
    ruled.current = plateDetail(ruled.current, { cameraDistance, personDistance, ...wanted.current });
    let detail = ruled.current;
    if (detail === "full") {
      // In a crowd only the plates that do not cover one another open (plateCrowd.ts); the rest stay dots.
      const m = measured.current;
      if (m.w === 0 || m.tick % PLATE_MEASURE_FRAMES === 0) {
        m.w = plate.current.offsetWidth || PLATE_FALLBACK_PX.w;
        m.h = plate.current.offsetHeight || PLATE_FALLBACK_PX.h;
      }
      m.tick += 1;
      onScreen.copy(world).project(camera);
      if (onScreen.z < 1) {
        const pinned = wanted.current.pointed || wanted.current.selected;
        const taken = () => personPlate(camera, size);
        if (!pinned && !plateSeating(scene, clock.elapsedTime, taken).has(agent.agentId)) detail = "dot";
        reportPlate(scene, {
          id: agent.agentId, x: (onScreen.x * 0.5 + 0.5) * size.width, y: (0.5 - onScreen.y * 0.5) * size.height,
          w: m.w * scale, h: m.h * scale, pinned, distance: personDistance, shown: shown.current === "full",
          speaker: voice.current.speaking || Date.now() - voice.current.spokeAt < SPOKE_LINGER_MS,
        });
      }
    }
    if (detail !== shown.current || wrap.current.dataset.detail !== detail) {
      shown.current = detail;
      wrap.current.dataset.detail = detail;
    }
    if (Math.abs(scale - last.current) < 0.02) return;
    last.current = scale;
    plate.current.style.transform = `scale(${scale.toFixed(2)})`;
  });
  const detail = agent.state !== "idle" ? t(`society.office.state_${agent.state}`) : activity ? t(`society.office.activity_${activity}`) : "";
  const pane = isPaneAgentId(agent.agentId);
  const logo = pane ? agentLogoAsset(agent.provider) : null;
  const state = (
    <span className="office-plate-state" title={t(`society.office.state_${agent.state}`)}>
      <i aria-hidden />{detail ? <em>{detail}</em> : null}
    </span>
  );
  return (
    <group ref={anchor} position={[0, height, 0]}>
      {/* Hover/focus raises a plate above its neighbours. Only the dot and the open plate take the pointer: the
          wrapper is as wide as the plate even while it shows a dot, and must not swallow clicks meant for the floor. */}
      <Html center zIndexRange={open ? [40, 30] : [20, 0]} style={PLATE_PASS_THROUGH}>
        <span ref={wrap} className="office-plate-wrap" data-office-ui data-state={agent.state} data-detail={shown.current}
          onPointerEnter={() => setOpen(true)} onPointerLeave={() => setOpen(false)}>
        <i className="office-plate-dot" aria-hidden onClick={(event) => { event.stopPropagation(); onSelect(agent.agentId); }} />
        <button ref={plate} type="button" className="office-plate" data-state={agent.state} data-selected={selected || undefined}
          data-pane={pane || undefined} data-open={pane || open || undefined}
          onClick={(event) => { event.stopPropagation(); onSelect(agent.agentId); }}
          onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
          aria-label={t("society.office.open_agent").replace("{0}", agent.name)}>
          {pane && logo ? <PaneLogo url={logo.url} ground={logo.ground} /> : (
            <span className="office-plate-badge" style={{ background: agent.palette.primary }} aria-hidden>
              {agent.tier === "lead" ? "★" : (pane ? agent.provider : agent.name).slice(0, 1).toUpperCase()}
            </span>
          )}
          {pane ? <PanePlateText agent={agent} state={state} /> : (
            <>
              <span className="office-plate-name" title={agent.name}>{agent.name}</span>
              <PlateLevel agent={agent} />
              {state}
            </>
          )}
        </button>
        </span>
      </Html>
    </group>
  );
}

/** The plate's wrapper never takes the pointer itself; the dot and the open plate inside it do. */
const PLATE_PASS_THROUGH = { pointerEvents: "none" } as const;
/** A plate's size on screen is read from the DOM now and then, not every frame; before the first reading it is assumed. */
const PLATE_MEASURE_FRAMES = 45;
const PLATE_FALLBACK_PX = { w: 150, h: 22 } as const;
/** The person's own plate (OfficePlayer draws it) is always there: agents' plates keep clear of it. */
const PERSON_PLATE_PX = { w: 150, h: 26 } as const;
const personAt = new Vector3();

function personPlate(camera: Camera, size: { width: number; height: number }): ScreenRect[] {
  personAt.set(player.x, OFFICE_FIGURE_HEIGHT_M + 0.35, player.z).project(camera);
  if (personAt.z >= 1) return [];
  return [{ x: (personAt.x * 0.5 + 0.5) * size.width, y: (0.5 - personAt.y * 0.5) * size.height, ...PERSON_PLATE_PX }];
}

/** An agent's level on its plate; the lead shows its pet's level, since the lead IS the pet. */
function PlateLevel({ agent }: { agent: SocietyAgent }) {
  const lead = agent.tier === "lead";
  const level = useProgression((s) => {
    if (!s.snapshot) return null;
    return s.subjects[lead ? petSubject(s.petId) : agentSubject(agent.agentId)]?.level ?? 1;
  });
  return level === null ? null : <LevelChip kind={lead ? "pet" : "agent"} level={level} />;
}

/**
 * The coding CLI's own mark in front of a pane's plate, instead of a lettered
 * hexagon: a floor of Claude panes read "C", "C", "C", which named nothing.
 * Drawn here rather than with `AgentMark`, whose `ink` marks follow the app
 * theme's text colour — the plate is dark in both themes, so a light-mode ink
 * mark would vanish on it. An `ink` mark is masked in the plate's own white;
 * a full-colour lockup keeps its colours on a dark tile it can sit on.
 */
function PaneLogo({ url, ground }: { url: string; ground: "ink" | "dark" | "any" }) {
  if (ground === "ink") {
    const mask = { WebkitMaskImage: `url("${url}")`, maskImage: `url("${url}")` };
    return <span className="office-plate-logo" data-ground="ink" aria-hidden><i style={mask} /></span>;
  }
  return <span className="office-plate-logo" data-ground={ground} aria-hidden><img src={url} alt="" draggable={false} /></span>;
}

/**
 * A coding pane's plate shows only its whole title (subject, then result) and
 * run state. The logo in front already names the CLI, so neither its
 * call-sign nor the opening of the last prompt is repeated here.
 */
function PanePlateText({ agent, state }: { agent: SocietyAgent; state: ReactNode }) {
  const { subject, result } = plateTitle(agent.name);
  return (
    <span className="office-plate-text">
      <span className="office-plate-name">{subject}</span>
      <span className="office-plate-line">
        {result ? <span className="office-plate-result">{result}</span> : null}
        {state}
      </span>
    </span>
  );
}

/** The sealed envelope Gigi carries on an errand, bobbing under it. */
function ErrandEnvelope() {
  const env = useRef<Group>(null);
  useFrame(({ clock }) => {
    if (!env.current) return;
    env.current.position.y = 0.62 + Math.sin(clock.elapsedTime * 5) * 0.04;
    env.current.rotation.y = clock.elapsedTime * 1.6;
  });
  return (
    <group ref={env}>
      <mesh castShadow>
        <boxGeometry args={[0.26, 0.17, 0.02]} />
        <meshStandardMaterial color="#fffaf0" roughness={0.6} />
      </mesh>
      <mesh position={[0, 0.02, 0.012]} rotation={[0, 0, Math.PI / 4]}>
        <boxGeometry args={[0.13, 0.13, 0.004]} />
        <meshStandardMaterial color="#efe3c8" roughness={0.7} />
      </mesh>
      <mesh position={[0, -0.01, 0.016]}>
        <circleGeometry args={[0.03, 16]} />
        <meshStandardMaterial color="#c0392b" roughness={0.4} />
      </mesh>
    </group>
  );
}

export interface WalkerContext {
  layout: OfficeLayout;
  grid: NavGrid;
  book: SpotBook;
  /** Busy colleagues someone idle may visit, refreshed with the roster. */
  colleagues: () => { agentId: string; desk: DeskSlot }[];
  spawn: Point;
}

function Walker({ agent, desk, ctx, deskOf, arrivesByElevator, awake, reduced, selected, lines, onSelect }: {
  agent: SocietyAgent; desk: DeskSlot | null; ctx: WalkerContext; deskOf: ReadonlyMap<string, DeskSlot>; arrivesByElevator: boolean;
  awake: boolean; reduced: boolean; selected: boolean; lines: readonly ChatLine[] | undefined; onSelect: (id: string) => void;
}) {
  const look = useMemo(() => toyLookFor(agent.figure, agent.agentId), [agent.figure, agent.agentId]);
  const group = useRef<Group>(null);
  const body = useRef<Group>(null);
  const ring = useRef<Mesh>(null);
  const drive = useRef<FigureDrive>({ mode: "idle", speed: 0 });
  const dressed = useDressedFigure("agent", agentSubject(agent.agentId), look);
  const rng = useMemo(() => createRng(agent.agentId), [agent.agentId]);
  const mover = useRef<Mover>({ ...(arrivesByElevator ? ctx.spawn : { x: 0, z: 0 }), heading: Math.PI, path: [] });
  const plan = useRef<Plan | null>(null);
  const phase = useRef<"travel" | "dwell">("dwell");
  const dwellUntil = useRef(0);
  const placed = useRef(arrivesByElevator);
  const planState = useRef("");
  // The desk the current plan was made for: a roster change can move an agent to another desk.
  const planDesk = useRef<string | null>(null);
  const summonKey = useRef("");
  // The walk in progress (its route, stuck watch and time budget), and the floor plan the current plan was made on.
  const walk = useRef<Walk | null>(null);
  const planGrid = useRef<NavGrid | null>(null);
  // Team life: the studio the agent belongs to, its part in a running round, and the message it is walking over.
  const home = useMemo(() => homeStudio(ctx.layout, agent.agentId, desk), [ctx.layout, agent.agentId, desk]);
  const roleMemory = useRef<RoleMemory>({ role: "none", busySinceMs: null });
  const roundKey = useRef("");
  const handoffKey = useRef("");
  const nearby = useRef<Point[]>([]);
  const tally = useRef({ replans: 0, rescues: 0, repaths: 0, near: 0, blocked: 0, lost: 0 });
  // Walks in a row that were given up because the way stayed closed.
  const givenUp = useRef(0);
  // The keys a plan is made for, built when the desk or the call changes and not on every frame.
  const deskKey = useMemo(() => (desk ? `${desk.id}@${desk.x.toFixed(2)},${desk.z.toFixed(2)}` : null), [desk]);
  const called = useRef<{ summon: Summon | undefined; key: string }>({ summon: undefined, key: "" });
  // Seconds the person has stood right beside this agent at a board (negative: it just made room, give it a moment).
  const crowded = useRef(0);
  const [activity, setActivity] = useState<ActivityKind | null>(null);
  const [seatHeight, setSeatHeight] = useState<number>(SEAT_HEIGHT.chair);
  const isGigi = agent.tier === "lead";
  const [gigiPose, setGigiPose] = useState<{ pose: Pose | null; travelling: boolean }>({ pose: null, travelling: false });
  const speaking = useEventStore((s) => isGigi && s.voiceState === "speaking");
  const errandKey = useRef("");
  const carrying = useGigiErrands((s) => isGigi && s.current?.phase === "fly");
  const [following, setFollowing] = useState(false);
  const followingRef = useRef(false);
  const gigiSide = useRef<1 | -1>(1);
  const airClear = useMemo(() => (x: number, z: number) => isWalkable(ctx.grid, { x, z }), [ctx.grid]);
  // Where the pet keeps the person company: free floor that is nobody's, so it never sits in a seated agent or on a chair.
  const petSpot = useMemo(() => {
    const around: Point[] = [];
    return (x: number, z: number) => isWalkable(ctx.grid, { x, z }) && clearOfBodies({ x, z }, bodiesNear(agent.agentId, { x, z }, 1, null, around), PET_CLEAR_M);
  }, [ctx.grid, agent.agentId]);
  // The lead is drawn as the person's pet; one that walks takes floor routes instead of flying over desks.
  const petOnFloor = useCompanionPet((s) => isGigi && !companionFlies(s.pet));
  const onFloorRef = useRef(petOnFloor);
  onFloorRef.current = petOnFloor;
  const routeGoal = useRef<Point | null>(null);

  // Leaving the office releases the agent's spot and its registry entry.
  useEffect(() => () => {
    ctx.book.release(agent.agentId);
    agentPositions.delete(agent.agentId);
    seatedAtDesk.delete(agent.agentId);
    companions.delete(agent.agentId);
    walkerDebug.delete(agent.agentId);
  }, [ctx.book, agent.agentId]);
  const pet = useMemo(() => ({ ...resolveCompanion(agent.agentId, agent.figure?.companion), sizeM: PET_SIZE_M, followDistanceM: PET_FOLLOW_M }),
    [agent.agentId, agent.figure?.companion]);
  const petClear = useMemo(() => (point: TrailPoint, radius: number) =>
    isWalkable(ctx.grid, { x: point[0] - radius, z: point[2] }) && isWalkable(ctx.grid, { x: point[0] + radius, z: point[2] })
    && isWalkable(ctx.grid, { x: point[0], z: point[2] - radius }) && isWalkable(ctx.grid, { x: point[0], z: point[2] + radius }), [ctx.grid]);

  useFrame((_, rawDt) => {
    const dt = Math.min(rawDt, 0.1);
    const now = Date.now();
    const m = mover.current;
    // A flyer heads straight for its goal; a pet on the floor walks a route, re-planned only when the goal moves.
    const headFor = (goal: Point) => {
      if (!onFloorRef.current) { m.path = [goal]; return; }
      const last = routeGoal.current;
      if (last && m.path.length > 0 && Math.hypot(last.x - goal.x, last.z - goal.z) < 0.4) return;
      routeGoal.current = { x: goal.x, z: goal.z };
      m.path = findPath(ctx.grid, m, goal) ?? [goal];
    };
    // Gigi on an errand: fly straight to the recipient, hover and deliver, then back to its day.
    const errand = isGigi ? useGigiErrands.getState().current : null;
    const recipient = errand ? agentPositions.get(errand.to) : undefined;
    if (errand && !recipient) useGigiErrands.getState().finish(errand.id);
    if (errand && recipient) {
      if (followingRef.current) { followingRef.current = false; setFollowing(false); }
      companions.delete(agent.agentId);
      const key = `${errand.id}:${errand.phase}`;
      if (errand.phase === "fly") {
        const spot = deliverySpot(recipient, m);
        if (errandKey.current !== key) routeGoal.current = null;
        if (onFloorRef.current) headFor(spot);
        else {
          const end = m.path[m.path.length - 1];
          if (errandKey.current !== key || !end || Math.hypot(end.x - spot.x, end.z - spot.z) > 0.4) m.path = [spot];
        }
        if (reduced) { m.x = spot.x; m.z = spot.z; m.path = []; }
        const { arrived } = stepMover(m, ERRAND_SPEED, dt);
        if (arrived) useGigiErrands.getState().arrive(errand.id);
      } else {
        m.heading = turnToward(m.heading, Math.atan2(recipient.x - m.x, recipient.z - m.z), 8 * dt);
        if (now >= errand.untilMs) useGigiErrands.getState().finish(errand.id);
      }
      if (errandKey.current !== key) {
        errandKey.current = key;
        setGigiPose({ pose: errand.phase === "deliver" ? "talk" : null, travelling: errand.phase === "fly" });
      }
      // The day resumes from wherever the errand ended.
      plan.current = null;
      placeAgent(agent.agentId, m.x, m.z);
      seatedAtDesk.delete(agent.agentId);
      if (group.current) group.current.position.set(m.x, 0, m.z);
      return;
    }
    errandKey.current = "";
    const summon = useOfficeStore.getState().summons[agent.agentId];
    const calledTo = summon && summon.untilMs > now ? summon.target : null;
    if (isGigi && !calledTo) {
      // Gigi keeps the person company, as on the coding floor; an errand or a summons still takes it away.
      const anchor = followAnchor(player.x, player.z, player.heading, gigiSide.current, petSpot, onFloorRef.current);
      gigiSide.current = anchor.side;
      const far = Math.hypot(anchor.x - m.x, anchor.z - m.z) > FOLLOW_CATCH_M;
      if (!placed.current || reduced || !far) {
        m.x = anchor.x; m.z = anchor.z; m.path = [];
        placed.current = true;
      } else if (awake) {
        // Back from an errand or a meeting: fly (or run) over to the person, then fall in beside them.
        headFor(anchor);
        stepMover(m, ERRAND_SPEED, dt);
      }
      const nowFollowing = Math.hypot(anchor.x - m.x, anchor.z - m.z) <= FOLLOW_CATCH_M;
      if (nowFollowing) { m.heading = player.heading; companions.add(agent.agentId); } else companions.delete(agent.agentId);
      if (followingRef.current !== nowFollowing || plan.current) {
        followingRef.current = nowFollowing;
        setFollowing(nowFollowing);
        setGigiPose({ pose: null, travelling: !nowFollowing });
        setActivity(null);
      }
      // The day resumes from wherever the person leaves Gigi (a summons).
      plan.current = null;
      summonKey.current = "";
      placeAgent(agent.agentId, m.x, m.z);
      seatedAtDesk.delete(agent.agentId);
      if (group.current) group.current.position.set(m.x, 0, m.z);
      return;
    }
    if (followingRef.current) { followingRef.current = false; setFollowing(false); }
    companions.delete(agent.agentId);
    const calledSeat = calledTo ? summon.spotId ?? null : null;
    if (called.current.summon !== summon) {
      called.current = { summon, key: summon ? `${summon.target.x.toFixed(2)},${summon.target.z.toFixed(2)},${summon.spotId ?? ""}` : "" };
    }
    const sKey = calledTo ? called.current.key : "";
    // Team life, from what is real right now: a running round of the agent's team, and a message it sent a colleague.
    const teamwork = useTeamwork.getState();
    const round = isGigi ? undefined : roundFor(teamwork.rounds, agent.agentId, home?.teamId ?? null);
    const role = steadyRole(roleMemory.current, roundRole(agent, round), now);
    const inRound = !!round && !calledTo && (role === "gather" || role === "speaker");
    const rKey = inRound && round ? round.teamId : "";
    // The stay with the receiver is over: the message has been delivered.
    if (plan.current?.kind === "handoff" && handoffKey.current && phase.current === "dwell" && now >= dwellUntil.current) {
      teamwork.finishHandoff(handoffKey.current);
    }
    // Only a free agent walks a message over; a working one keeps its screen (its bubble still says what it sent).
    const handoff = isGigi || reduced || agent.state !== "idle" || calledTo || inRound
      ? null : pendingHandoff(useTeamwork.getState().handoffs, agent.agentId, now);
    const hKey = handoff ? handoff.id : "";
    // A rebuilt floor plan: the plan holds only if its place still exists there, and its spot is still this agent's.
    let stale = false;
    if (plan.current && planGrid.current !== ctx.grid) {
      const held = plan.current;
      stale = !planStillValid(held, ctx.layout, ctx.grid) || (held.spotId !== null && !ctx.book.claim(held.spotId, agent.agentId));
      planGrid.current = ctx.grid;
    }
    // The person walked into the group at the board: the agent beside them makes room (another place in the arc).
    let makeRoom = false;
    if (plan.current?.kind === "huddle" && phase.current === "dwell" && Math.hypot(player.x - m.x, player.z - m.z) < PERSON_CROWD_M) {
      crowded.current += dt;
      if (crowded.current > 0.4) { makeRoom = true; crowded.current = -3; }
    } else if (crowded.current > 0) crowded.current = 0;
    else crowded.current = Math.min(0, crowded.current + dt);
    const needsPlan = !plan.current || planState.current !== agent.state || summonKey.current !== sKey
      || planDesk.current !== deskKey || roundKey.current !== rKey || handoffKey.current !== hKey || stale || makeRoom
      || (phase.current === "dwell" && now >= dwellUntil.current);
    if (needsPlan) {
      const seatedMates = home ? mateDesks(ctx.layout, home, agent.agentId).filter((d) => seatedAtDesk.has(d.agentId as string)) : [];
      const next = planFor({
        agentId: agent.agentId, state: agent.state, desk, layout: ctx.layout, grid: ctx.grid, rng, book: ctx.book,
        previous: plan.current?.kind ?? null, workingColleagues: ctx.colleagues().filter((c) => c.agentId !== agent.agentId), calledTo, calledSeat,
        position: placed.current ? { x: m.x, z: m.z } : null,
        // The member contributing right now reads "working"; it is the one working member a round places.
        round: inRound && round ? { speaker: role === "speaker" || agent.state === "working", teamId: round.teamId } : null,
        // A receiver that works is at its screen, or on its way there: its desk is where to find it.
        handoff: handoff ? {
          to: handoff.to, desk: deskOf.get(handoff.to) ?? null, at: agentPositions.get(handoff.to) ?? null,
          seated: seatedAtDesk.has(handoff.to) || ctx.colleagues().some((c) => c.agentId === handoff.to),
        } : null,
        matesAtDesk: seatedMates.map((d) => ({ agentId: d.agentId as string, desk: d })),
        backToDesk: roundKey.current !== "" && rKey === "",
        bodies: bodiesNear(agent.agentId, m, Infinity, player, nearby.current),
        person: player,
      });
      // Reduced motion: no idle wandering — a placement holds until the state changes.
      if (reduced && !calledTo) next.dwellMs = Infinity;
      plan.current = next;
      planState.current = agent.state;
      planDesk.current = deskKey;
      summonKey.current = sKey;
      roundKey.current = rKey;
      handoffKey.current = hKey;
      planGrid.current = ctx.grid;
      walk.current = null;
      if (!placed.current || reduced) {
        // First sight (or reduced motion): already there, no walk across the floor.
        m.x = next.target.x; m.z = next.target.z; m.path = [];
        if (next.facing !== null) m.heading = next.facing;
        placed.current = true;
        phase.current = "dwell";
      } else if (isGigi) {
        m.path = findPath(ctx.grid, m, next.target) ?? [];
        // Gigi flies: after an errand it may hover over a desk, where no floor path starts.
        if (m.path.length === 0 && !onFloorRef.current && Math.hypot(next.target.x - m.x, next.target.z - m.z) > 0.05) m.path = [next.target];
        if (m.path.length === 0) { m.x = next.target.x; m.z = next.target.z; }
        phase.current = m.path.length > 0 ? "travel" : "dwell";
      } else {
        walk.current = beginWalk(ctx.grid, m, next.target, bodiesNear(agent.agentId, m, BODY_RANGE_M, player, nearby.current));
        // No way there on this floor plan: the agent is simply there.
        if (!walk.current) { m.x = next.target.x; m.z = next.target.z; m.path = []; }
        phase.current = m.path.length > 0 ? "travel" : "dwell";
      }
      if (phase.current === "dwell") {
        dwellUntil.current = now + next.dwellMs;
        if (next.kind === "handoff" && hKey) teamwork.deliverHandoff(hKey, now, HANDOFF_DWELL_MS);
      }
      // The plate says "at the team board" only for a gathering that is real: a running round, or a meeting the person called.
      const shown = shownActivity(next.kind, inRound || calledTo !== null);
      if (shown !== activity) setActivity(shown);
      if (isGigi) setGigiPose({ pose: next.pose, travelling: phase.current === "travel" });
      const nextSeat = seatHeightFor(next.kind);
      if (nextSeat !== seatHeight) setSeatHeight(nextSeat);
    }
    const p = plan.current!;
    if (phase.current === "travel") {
      // Walkers steer round other people and never through them or the furniture; Gigi flies over everyone.
      let moved = 0, arrived = false;
      const going = walk.current;
      if (!awake) { /* A sleeping stage holds every walk where it is. */ }
      else if (isGigi || !going) ({ moved, arrived } = stepMover(m, WALK_SPEED, dt));
      else {
        // Nobody is moved across the floor, with one exception: a place the agent's real state demands (its screen
        // while it works, the board while its round runs) that it failed to reach twice.
        const step = advanceWalk(going, m, ctx.grid, dt, bodiesNear(agent.agentId, m, BODY_RANGE_M, player, nearby.current),
          { far: givenUp.current >= 2 && !Number.isFinite(p.dwellMs), ...(p.kind === "work" ? { speed: hurryPaceFor(going.remaining) } : {}) });
        ({ moved, arrived } = step);
        if (step.event === "replan") tally.current.replans += 1;
        else if (step.event === "rescue") tally.current.rescues += 1;
        else if (step.event === "repath") tally.current.repaths += 1;
        else if (step.event === "near") tally.current.near += 1;
        else if (step.event === "lost" || step.event === "blocked") {
          // No way to this place (a new floor plan walled it off, or the way stays closed): plan again next frame.
          if (step.event === "lost") tally.current.lost += 1;
          else { tally.current.blocked += 1; givenUp.current += 1; }
          plan.current = null;
        }
      }
      // Waiting for someone to pass is standing, not walking on the spot.
      drive.current.mode = moved > 1e-4 ? "walk" : "idle";
      drive.current.speed = moved / Math.max(dt, 1e-3);
      if (arrived) {
        phase.current = "dwell";
        givenUp.current = 0;
        // A long way earns a long stay, so a large floor shows people being somewhere.
        dwellUntil.current = now + dwellAfter(p, going?.length ?? 0);
        if (p.kind === "handoff" && handoffKey.current) teamwork.deliverHandoff(handoffKey.current, now, HANDOFF_DWELL_MS);
        if (isGigi) setGigiPose({ pose: p.pose, travelling: false });
      }
    } else {
      if (p.facing !== null) m.heading = turnToward(m.heading, p.facing, 8 * dt);
      // At the board the member contributing right now talks; everyone else listens.
      drive.current.mode = POSE_CLIP[p.kind === "huddle" && role === "speaker" ? "talk" : p.pose];
      drive.current.speed = 0;
    }
    if (import.meta.env.DEV) {
      walkerDebug.set(agent.agentId, {
        id: agent.agentId, name: agent.name, state: agent.state, team: home?.teamId ?? null, studio: home?.deptId ?? null, role,
        plan: plan.current?.kind ?? null, phase: phase.current, target: plan.current?.target ?? null, spot: plan.current?.spotId ?? null,
        with: plan.current?.with ?? null, at: { x: m.x, z: m.z }, pathLength: m.path.length, remainingM: walk.current?.remaining ?? 0,
        stuckS: phase.current === "travel" ? walk.current?.watch.idleS ?? 0 : 0,
        walkS: phase.current === "travel" ? walk.current?.elapsedS ?? 0 : 0,
        speed: phase.current === "travel" && walk.current && walk.current.elapsedS > 0
          ? (walk.current.length - walk.current.remaining) / walk.current.elapsedS : 0,
        ...tally.current,
      });
    }
    placeAgent(agent.agentId, m.x, m.z);
    if (plan.current && phase.current === "dwell" && (p.kind === "work" || p.kind === "desk")) seatedAtDesk.add(agent.agentId);
    else seatedAtDesk.delete(agent.agentId);
    if (group.current) group.current.position.set(m.x, 0, m.z);
    if (body.current) body.current.rotation.y = m.heading;
    if (ring.current) {
      const material = ring.current.material as MeshBasicMaterial;
      material.opacity = agent.state === "working" && awake && !reduced ? 0.55 + Math.sin(now / 330) * 0.3 : 0.8;
      ring.current.visible = isGigi ? onFloorRef.current : phase.current === "dwell" || selected;
    }
  });

  // A pet on the floor carries its name low, just above its head; a flyer's sits above its hover height.
  const leadPlate = petOnFloor ? LEAD_PLATE_ON_FLOOR_M : LEAD_PLATE_FLYING_M;
  const presentation = (
    // The lead inherits GigiFlyer's rendered ground anchor. Only ordinary
    // walkers bind the group that the navigation frame positions directly.
    <group ref={isGigi ? undefined : group} userData={{ agentId: agent.agentId }}>
      <mesh ref={ring} visible={!isGigi || petOnFloor} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.015, 0]}>
        <ringGeometry args={[selected ? 0.4 : 0.46, 0.54, 40]} />
        <meshBasicMaterial color={selected ? "#93c5fd" : RING_COLOUR[agent.state]} transparent opacity={0.8} side={DoubleSide} depthWrite={false} />
      </mesh>
      <group ref={body}
        onClick={(event) => { event.stopPropagation(); onSelect(agent.agentId); }}
        onPointerOver={() => { document.body.style.cursor = "pointer"; useOfficeStore.getState().setHover({ kind: "agent", id: agent.agentId }); }}
        onPointerOut={() => {
          document.body.style.cursor = "";
          const hover = useOfficeStore.getState().hover;
          if (hover?.kind === "agent" && hover.id === agent.agentId) useOfficeStore.getState().setHover(null);
        }}>
        {!isGigi && <ToyFigure look={dressed.look} drive={drive} paused={!awake} heightM={OFFICE_FIGURE_HEIGHT_M} seatHeight={seatHeight}
          regalia={dressed.regalia} />}
      </group>
      <Nameplate agent={agent} activity={activity} selected={selected} onSelect={onSelect} height={isGigi ? leadPlate : undefined} />
      <AgentBubble agent={agent} lines={lines} selected={selected} onSelect={onSelect} listening={activity === "huddle"}
        height={(isGigi ? leadPlate : OFFICE_FIGURE_HEIGHT_M + 0.35) + 0.14} />
      {carrying && <ErrandEnvelope />}
    </group>
  );
  return isGigi
    // One flyer for both roles, so switching keeps its flight state instead of re-spawning it.
    ? <GigiFlyer owner={following ? PLAYER_OWNER : mover} mode={following ? "follow" : gigiModeFor(gigiPose.pose, gigiPose.travelling)}
        speaking={speaking} paused={!awake} reduced={reduced} clear={following ? airClear : undefined}>
        {presentation}
      </GigiFlyer>
    : <>{presentation}<AgentFollower owner={group} appearance={pet} paused={!awake || reduced} clear={petClear} /></>;
}

export function OfficeAgents({ desks, agents, ctx, newcomers, awake, reduced, selectedId, chats, onSelect }: {
  desks: DeskSlot[]; agents: ReadonlyMap<string, SocietyAgent>; ctx: WalkerContext; newcomers: ReadonlySet<string>;
  awake: boolean; reduced: boolean; selectedId: string | null; chats?: ReadonlyMap<string, DeskChat>; onSelect: (id: string) => void;
}) {
  const deskOf = useMemo(() => new Map(desks.filter((d) => d.agentId).map((d) => [d.agentId as string, d])), [desks]);
  useErrandFeed(agents, awake);
  // Team rounds and messages between agents exist only where there are team studios (the agents floor).
  const studios = studiosOf(ctx.layout);
  useTeamRounds(studios, agents, awake && studios.length > 0);
  // Leaving the office hangs up: the talk socket closes, the chat keeps running on the server.
  useEffect(() => () => { officeTalkChat.getState().disconnect(); useOfficeTalk.getState().setAgent(null); }, []);
  return (
    <group>
      {[...agents.values()].map((agent) => (
        <Walker key={agent.agentId} agent={agent} desk={deskOf.get(agent.agentId) ?? null} ctx={ctx} deskOf={deskOf}
          arrivesByElevator={newcomers.has(agent.agentId)} awake={awake} reduced={reduced}
          selected={selectedId === agent.agentId} lines={chats?.get(agent.agentId)?.lines} onSelect={onSelect} />
      ))}
      {studios.length > 0 && <StudioBoards layout={ctx.layout} agents={agents} awake={awake} />}
    </group>
  );
}
