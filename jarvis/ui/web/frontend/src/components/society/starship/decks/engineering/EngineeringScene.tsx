/**
 * Engineering's own scene: what moves or changes beyond the shared kit.
 *
 * The reactor's plasma column pulses with the work on the deck (slow and dim
 * when every pane is idle, quick and bright when they all work; still with
 * reduced motion). Energy runs down the floor feed of every bay with a
 * working pane, the master systems display shows each bay's load as a
 * hologram, and every seated pane's console shows its live terminal (polled
 * only while the stage is awake, only for the panes sitting at their
 * consoles). A click on a screen opens that pane in the IDE.
 */
import { useFrame } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  AdditiveBlending, BoxGeometry, BufferAttribute, BufferGeometry, Color, CylinderGeometry, DoubleSide, InstancedMesh, Mesh,
  Matrix4, MeshBasicMaterial, Object3D, PlaneGeometry, ShaderMaterial, TorusGeometry, type PointLight,
} from "three";
import type { PaneScreen } from "@/lib/paneScreensApi";
import type { AgentDotKind } from "@/components/agentic/sidePanel/agentStatus";
import type { PaneOccupant } from "../../../crewFeeds/codingFloor";
import { MAX_SCREEN_TARGETS, usePaneScreens, type PaneScreenTarget } from "../../../crewFeeds/usePaneScreens";
import { visibleRows } from "../../../crewFeeds/terminalScreen";
import { seatedCrew } from "../../../crewFeeds/seated";
import type { DeckSceneProps, ShipActions } from "../registry";
import { COMMAND_GOLD, HOLO_CYAN } from "../../plan/builder";
import type { DeckPlan, Prop, Vec2 } from "../../plan/types";
import { ConsoleScreens } from "../../render/deck/DeckScene";
import type { ScreenContent, ScreenState } from "../../render/deck/screens";
import { annulus, floorQuad, GeoBatch } from "../../render/kit/geo";
import { castsShadow, finishMaterial, receivesShadow } from "../../render/kit/materials";
import { STATE } from "../../render/kit/palette";
import { crewPoses } from "../../life/CrewLayer";
import { CORE_R, engineeringLayout, RAIL_R, ROW_R, TABLE_AT, type EngineeringLayout } from "./engineeringDeck";
import { PLASMA } from "./props";

const BAY_KINDS: readonly Prop["kind"][] = ["bayConsole"];
/** Rows a console screen shows (the screen atlas fits seven under its header). */
const SCREEN_FIT = 7;
/** Live terminals at once: this many polls of MAX_SCREEN_TARGETS panes each. */
const SCREEN_CHUNKS = 4;

interface Busy { working: number; waiting: number; total: number }

export function EngineeringScene({ plan, reduced, quality, awake, panes, actions }: DeckSceneProps) {
  const layout = engineeringLayout(plan);
  const dotOf = useMemo(() => new Map(panes.map((o) => [o.agent.agentId, o.dot])), [panes]);
  const busy = useMemo<Busy>(() => {
    let working = 0, waiting = 0;
    for (const o of panes) { if (o.dot === "working") working += 1; else if (o.dot === "waiting" || o.dot === "error") waiting += 1; }
    return { working, waiting, total: panes.length };
  }, [panes]);
  return (
    <>
      {layout && <FloorTrims plan={plan} layout={layout} />}
      {layout && <ReactorCore at={layout.centre} busy={busy} reduced={reduced} light={quality === "high"} />}
      {layout && <PowerFeeds plan={plan} layout={layout} dotOf={dotOf} reduced={reduced} />}
      <SystemsHolo plan={plan} dotOf={dotOf} reduced={reduced} />
      <BayScreens plan={plan} panes={panes} awake={awake} actions={actions} />
      <SeatWatch plan={plan} />
    </>
  );
}

// ── reactor ──────────────────────────────────────────────────────────

const PLASMA_VERT = /* glsl */ `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const PLASMA_FRAG = /* glsl */ `uniform float uPhase; uniform float uTime; uniform float uLevel; uniform vec3 uColour; uniform vec3 uHot; varying vec2 vUv;
  void main() {
    float y = vUv.y;
    float bands = pow(0.5 + 0.5 * sin(y * 24.0 - uPhase * 6.2831), 4.0);
    float swirl = 0.5 + 0.5 * sin(vUv.x * 18.85 + y * 9.0 - uTime * 0.9);
    float beat = 0.5 + 0.5 * sin(uPhase * 3.1416);
    float ends = smoothstep(0.0, 0.06, y) * (1.0 - smoothstep(0.94, 1.0, y));
    float g = (0.32 + 0.68 * bands * (0.55 + 0.45 * swirl)) * (0.8 + 0.2 * beat) * uLevel * ends;
    gl_FragColor = vec4(mix(uColour, uHot, bands * 0.7) * g, g);
  }`;

/** How fast and bright the core runs for the work on the deck. */
function coreDrive(busy: Busy): { speed: number; level: number } {
  if (busy.total === 0) return { speed: 0.25, level: 0.5 };
  const share = busy.working / busy.total;
  return { speed: 0.35 + 1.9 * share + Math.min(0.6, busy.working * 0.06), level: 0.7 + 0.6 * Math.min(1, busy.working / 4) };
}

function ReactorCore({ at, busy, reduced, light }: { at: Vec2; busy: Busy; reduced: boolean; light: boolean }) {
  const drive = useMemo(() => coreDrive(busy), [busy]);
  const height = PLASMA.y1 - PLASMA.y0;
  const parts = useMemo(() => {
    const plasma = new ShaderMaterial({
      vertexShader: PLASMA_VERT, fragmentShader: PLASMA_FRAG, transparent: true, blending: AdditiveBlending, depthWrite: false, side: DoubleSide,
      uniforms: {
        uPhase: { value: 0 }, uTime: { value: 0 }, uLevel: { value: 0.5 },
        uColour: { value: new Color(HOLO_CYAN).multiplyScalar(1.5) }, uHot: { value: new Color("#e6fbff").multiplyScalar(2.2) },
      },
    });
    const column = new CylinderGeometry(PLASMA.r, PLASMA.r, height, 32, 1, true);
    column.translate(0, PLASMA.y0 + height / 2, 0);
    const heart = new CylinderGeometry(0.16, 0.16, height - 0.2, 16, 1, false);
    heart.translate(0, PLASMA.y0 + height / 2, 0);
    const heartMat = new MeshBasicMaterial({ color: new Color("#d8f6ff"), toneMapped: false });
    const ringGeo = new TorusGeometry(0.78, 0.028, 6, 48);
    ringGeo.rotateX(Math.PI / 2);
    const ringMat = new MeshBasicMaterial({ color: new Color(HOLO_CYAN).multiplyScalar(2.2), toneMapped: false, transparent: true, depthWrite: false });
    const rings = [0, 1, 2].map(() => { const m = new Mesh(ringGeo, ringMat); m.raycast = () => undefined; return m; });
    const columnMesh = new Mesh(column, plasma);
    const heartMesh = new Mesh(heart, heartMat);
    columnMesh.raycast = heartMesh.raycast = () => undefined;
    return { plasma, column, heart, heartMat, ringGeo, ringMat, rings, columnMesh, heartMesh };
  }, [height]);
  useEffect(() => () => {
    parts.plasma.dispose(); parts.column.dispose(); parts.heart.dispose(); parts.heartMat.dispose(); parts.ringGeo.dispose(); parts.ringMat.dispose();
  }, [parts]);
  const state = useRef({ speed: drive.speed, level: drive.level, phase: 0 });
  const lamp = useRef<PointLight>(null);
  const base = useMemo(() => new Color("#bfefff"), []);
  useFrame(({ clock }, dt) => {
    const s = state.current;
    const k = Math.min(1, dt * 1.2);
    s.speed += (drive.speed - s.speed) * k;
    s.level += (drive.level - s.level) * k;
    if (!reduced) s.phase += dt * s.speed;
    const u = parts.plasma.uniforms;
    u.uPhase.value = s.phase;
    u.uTime.value = reduced ? 0 : clock.elapsedTime;
    u.uLevel.value = s.level;
    const beat = reduced ? 0.5 : 0.5 + 0.5 * Math.sin(s.phase * Math.PI);
    parts.heartMat.color.copy(base).multiplyScalar(s.level * (1.5 + 0.7 * beat));
    // Rings rise through the cage, quicker with the work.
    parts.rings.forEach((ring, i) => {
      const t = reduced ? (i + 0.5) / 3 : (s.phase * 0.35 + i / 3) % 1;
      ring.position.y = PLASMA.y0 + 0.25 + t * (height - 0.5);
      ring.scale.setScalar(1 - 0.12 * Math.sin(t * Math.PI));
    });
    parts.ringMat.opacity = 0.35 + 0.45 * Math.min(1, s.level);
    if (lamp.current) lamp.current.intensity = 9 * s.level * (0.85 + 0.3 * beat);
  });
  return (
    <group position={[at.x, 0, at.z]}>
      <primitive object={parts.columnMesh} />
      <primitive object={parts.heartMesh} />
      {parts.rings.map((r, i) => <primitive key={i} object={r} />)}
      {light && <pointLight ref={lamp} position={[0, 2.6, 0]} color={HOLO_CYAN} intensity={6} distance={16} decay={2} />}
    </group>
  );
}

// ── floor trims ──────────────────────────────────────────────────────

/** A flat ring on the floor with uvs in metres, for tiled finishes (the grating round the core). */
function tiledRing(inner: number, outer: number, segments = 64): BufferGeometry {
  const g = annulus(inner, outer, 0, Math.PI * 2, segments);
  const pos = g.attributes.position;
  const uv = new Float32Array(pos.count * 2);
  for (let i = 0; i < pos.count; i += 1) { uv[i * 2] = pos.getX(i); uv[i * 2 + 1] = pos.getZ(i); }
  g.setAttribute("uv", new BufferAttribute(uv, 2));
  return g;
}

/** The pit grating round the core, the walkway's edge with each bay's colour, and gold guide lines from the turbolift. */
function FloorTrims({ plan, layout }: { plan: DeckPlan; layout: EngineeringLayout }) {
  const meshes = useMemo(() => {
    const batch = new GeoBatch();
    const c = layout.centre;
    const f = batch.frame(new Matrix4().makeTranslation(c.x, 0, c.z));
    f.geo("grate", tiledRing(CORE_R - 0.05, RAIL_R - 0.04), "#ffffff", { y: 0.013 });
    f.geo("glowSoft", annulus(RAIL_R + 0.28, RAIL_R + 0.33), HOLO_CYAN, { y: 0.016 });
    const edge = ROW_R[0] - 0.95;
    f.geo("structure", annulus(edge - 0.08, edge + 0.08, 0, Math.PI * 2, 96), "#2b3038", { y: 0.014 });
    for (const bay of layout.bays) {
      const inset = 0.6 / edge;
      f.geo("glowSoft", annulus(edge - 0.025, edge + 0.025, bay.a0 + inset, Math.max(0.05, bay.a1 - bay.a0 - 2 * inset), 32), bay.accent, { y: 0.018 });
    }
    // Two gold lines lead from the turbolift to the systems display.
    const systems = plan.props.find((p) => p.id === "systems");
    const lift = plan.lift;
    if (systems) {
      const z0 = systems.z + systems.d / 2 + 1.0, z1 = lift.z - 0.6;
      if (z1 > z0) for (const s of [-1, 1]) {
        batch.frame(new Matrix4().makeTranslation(lift.x + s * 1.5, 0.016, (z0 + z1) / 2)).geo("glowSoft", floorQuad(0.05, z1 - z0), COMMAND_GOLD);
      }
    }
    return batch.merged().map(({ finish, geometry }) => {
      const mesh = new Mesh(geometry, finishMaterial(finish));
      mesh.castShadow = castsShadow(finish);
      mesh.receiveShadow = receivesShadow(finish);
      mesh.raycast = () => undefined;
      return mesh;
    });
  }, [plan, layout]);
  useEffect(() => () => { for (const m of meshes) m.geometry.dispose(); }, [meshes]);
  return <>{meshes.map((m, i) => <primitive key={i} object={m} />)}</>;
}

// ── power feeds ──────────────────────────────────────────────────────

const PULSES = 3;

/** Energy running from the core down each bay's floor feed while one of its panes works. */
function PowerFeeds({ plan, layout, dotOf, reduced }: { plan: DeckPlan; layout: EngineeringLayout; dotOf: ReadonlyMap<string, AgentDotKind>; reduced: boolean }) {
  const feeds = useMemo(() => layout.bays.map((bay) => ({
    bay,
    members: plan.divisions.find((d) => d.room === bay.room)?.members ?? [],
    colour: new Color(bay.accent).multiplyScalar(2.4),
    phase: 0,
  })), [plan, layout]);
  const mesh = useMemo(() => {
    const m = new InstancedMesh(new BoxGeometry(0.2, 0.02, 0.36), new MeshBasicMaterial({ toneMapped: false }), Math.max(1, feeds.length * PULSES));
    m.raycast = () => undefined;
    m.frustumCulled = false;
    return m;
  }, [feeds]);
  useEffect(() => () => { mesh.geometry.dispose(); (mesh.material as MeshBasicMaterial).dispose(); }, [mesh]);
  const tmp = useMemo(() => new Object3D(), []);
  const from = RAIL_R + 0.4, to = TABLE_AT - 1.1;
  useFrame((_, dt) => {
    const c = layout.centre;
    let i = 0;
    for (const feed of feeds) {
      const working = feed.members.reduce((n, id) => n + (dotOf.get(id) === "working" ? 1 : 0), 0);
      if (!reduced) feed.phase = (feed.phase + dt * (0.35 + 0.08 * working)) % 1;
      for (let k = 0; k < PULSES; k += 1) {
        const t = (feed.phase + k / PULSES) % 1;
        const r = from + (to - from) * t;
        tmp.position.set(c.x + Math.sin(feed.bay.mid) * r, 0.06, c.z + Math.cos(feed.bay.mid) * r);
        tmp.rotation.set(0, feed.bay.mid, 0);
        tmp.scale.setScalar(working > 0 ? 1 - 0.5 * t : 0.0001);
        tmp.updateMatrix();
        mesh.setMatrixAt(i, tmp.matrix);
        mesh.setColorAt(i, feed.colour);
        i += 1;
      }
    }
    mesh.count = i;
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  });
  return <primitive object={mesh} />;
}

// ── master systems display ───────────────────────────────────────────

/** Each bay's load as a bar over the systems table: its colour, its height the share of its panes at work, a state cap. */
function SystemsHolo({ plan, dotOf, reduced }: { plan: DeckPlan; dotOf: ReadonlyMap<string, AgentDotKind>; reduced: boolean }) {
  const table = plan.props.find((p) => p.id === "systems");
  const divisions = plan.divisions;
  const parts = useMemo(() => {
    const n = Math.max(1, divisions.length);
    const bars = new InstancedMesh(new BoxGeometry(1, 1, 1), new MeshBasicMaterial({ toneMapped: false, transparent: true, opacity: 0.75, depthWrite: false }), n);
    const caps = new InstancedMesh(new BoxGeometry(1, 1, 1), new MeshBasicMaterial({ toneMapped: false }), n);
    const sheet = new Mesh(new PlaneGeometry(2.7, 0.8), new MeshBasicMaterial({
      color: new Color(HOLO_CYAN).multiplyScalar(0.5), transparent: true, opacity: 0.35, blending: AdditiveBlending, depthWrite: false, toneMapped: false, side: DoubleSide,
    }));
    sheet.rotation.x = -Math.PI / 2;
    for (const m of [bars, caps, sheet]) { m.raycast = () => undefined; m.frustumCulled = false; }
    return { bars, caps, sheet, colours: divisions.map((d) => new Color(d.colour).multiplyScalar(1.8)) };
  }, [divisions]);
  useEffect(() => () => {
    for (const m of [parts.bars, parts.caps, parts.sheet]) { m.geometry.dispose(); (m.material as MeshBasicMaterial).dispose(); }
  }, [parts]);
  const tmp = useMemo(() => new Object3D(), []);
  const cap = useMemo(() => new Color(), []);
  useFrame(({ clock }) => {
    const n = divisions.length;
    const width = Math.min(0.3, 2.3 / Math.max(1, n));
    const shimmer = reduced ? 1 : 0.94 + 0.06 * Math.sin(clock.elapsedTime * 2.2);
    divisions.forEach((d, i) => {
      let working = 0, waiting = 0;
      for (const id of d.members) { const dot = dotOf.get(id); if (dot === "working") working += 1; else if (dot === "waiting" || dot === "error") waiting += 1; }
      const share = d.members.length ? working / d.members.length : 0;
      const h = (0.08 + 0.62 * share) * shimmer;
      const x = (i - (n - 1) / 2) * (2.3 / Math.max(1, n));
      tmp.position.set(x, h / 2, 0);
      tmp.scale.set(width * 0.7, h, width * 0.7);
      tmp.updateMatrix();
      parts.bars.setMatrixAt(i, tmp.matrix);
      parts.bars.setColorAt(i, parts.colours[i]);
      tmp.position.set(x, h + 0.05, 0);
      tmp.scale.set(width * 0.7, 0.04, width * 0.7);
      tmp.updateMatrix();
      parts.caps.setMatrixAt(i, tmp.matrix);
      cap.set(waiting ? STATE.waiting : working ? STATE.working : STATE.idle).multiplyScalar(2);
      parts.caps.setColorAt(i, cap);
    });
    parts.bars.count = parts.caps.count = n;
    for (const m of [parts.bars, parts.caps]) {
      m.instanceMatrix.needsUpdate = true;
      if (m.instanceColor) m.instanceColor.needsUpdate = true;
    }
  });
  if (!table) return null;
  return (
    <group position={[table.x, 1.32, table.z - 0.15]} rotation={[0, table.yaw, 0]}>
      <primitive object={parts.sheet} />
      <primitive object={parts.bars} />
      <primitive object={parts.caps} />
    </group>
  );
}

// ── live terminals ───────────────────────────────────────────────────

function screenState(dot: AgentDotKind): ScreenState {
  return dot === "working" ? "working" : dot === "waiting" ? "waiting" : dot === "error" ? "error" : "idle";
}

/** Every bay console's screen: the seated pane's live terminal, a standby page, or "vacant". */
function BayScreens({ plan, panes, awake, actions }: { plan: DeckPlan; panes: readonly PaneOccupant[]; awake: boolean; actions: ShipActions }) {
  const { t, openAgent } = actions;
  const byId = useMemo(() => new Map(panes.map((o) => [o.agent.agentId, o])), [panes]);
  const chunks = useMemo(() => {
    const targets: PaneScreenTarget[] = [];
    for (const id of plan.seatOf.keys()) {
      const o = byId.get(id);
      if (o) targets.push({ agentId: id, workspaceId: o.pane.workspace_id, key: o.pane.key });
    }
    return Array.from({ length: SCREEN_CHUNKS }, (_, k) => targets.slice(k * MAX_SCREEN_TARGETS, (k + 1) * MAX_SCREEN_TARGETS));
  }, [plan, byId]);
  // A fixed number of polls, each for its own slice of the seated panes.
  const s0 = usePaneScreens(chunks[0], awake);
  const s1 = usePaneScreens(chunks[1], awake);
  const s2 = usePaneScreens(chunks[2], awake);
  const s3 = usePaneScreens(chunks[3], awake);
  const rowsOf = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const screens of [s0, s1, s2, s3]) for (const [id, screen] of screens as ReadonlyMap<string, PaneScreen>) {
      m.set(id, visibleRows(screen.lines, SCREEN_FIT, screen.cursor).rows);
    }
    return m;
  }, [s0, s1, s2, s3]);
  const content = useCallback((p: Prop): ScreenContent => {
    const accent = p.accent ?? HOLO_CYAN;
    const o = p.ref ? byId.get(p.ref) : undefined;
    if (!o) return { title: t("ship.screen.vacant"), state: "vacant", accent, stateLabel: t("ship.screen.vacant"), standby: t("ship.screen.vacant") };
    const state = screenState(o.dot);
    const live = rowsOf.get(o.agent.agentId);
    const rows = live?.length ? live : state !== "idle" && o.pane.last_prompt ? [`> ${o.pane.last_prompt}`] : undefined;
    return { title: o.agent.title || o.agent.name, state, accent, rows, stateLabel: t(`ship.state.${state}`), standby: t("ship.screen.standby") };
  }, [byId, rowsOf, t]);
  const onScreen = useCallback((p: Prop) => { if (p.ref) openAgent(p.ref); }, [openAgent]);
  return <ConsoleScreens plan={plan} kinds={BAY_KINDS} content={content} onScreen={onScreen} />;
}

/**
 * The terminal feed polls only panes that sit at their console (the shared
 * `seatedCrew` set the office used); the crew layer knows who sits, so
 * this mirrors it every frame and takes its own entries back on the way out.
 */
function SeatWatch({ plan }: { plan: DeckPlan }) {
  const mine = useRef(new Set<string>());
  useFrame(() => {
    for (const [id, seat] of plan.seatOf) {
      const pose = crewPoses.get(id);
      const at = !!pose && !pose.moving && Math.hypot(pose.x - seat.x, pose.z - seat.z) < 0.6;
      if (at) { seatedCrew.add(id); mine.current.add(id); }
      else if (mine.current.has(id)) { seatedCrew.delete(id); mine.current.delete(id); }
    }
  });
  useEffect(() => {
    const own = mine.current;
    return () => { for (const id of own) seatedCrew.delete(id); own.clear(); };
  }, [plan]);
  return null;
}
