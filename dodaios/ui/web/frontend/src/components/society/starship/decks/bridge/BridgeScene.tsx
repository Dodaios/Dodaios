/**
 * What the bridge adds to the shared deck: the sunken-looking command well,
 * the live console screens (course, destination, crew, the service record:
 * real data only), the viewscreen's holographic overlay over the forward
 * window (the stage renders the sky itself), the star chart's turning galaxy
 * with the destinations the captain's level opens, and the warp jump: stars
 * streak past while `useShip().warpingTo` is set, a flash covers the change
 * of sky, then everything settles. With reduced motion nothing turns and
 * the jump is a cut.
 */
import { useFrame } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  AdditiveBlending, BufferAttribute, BufferGeometry, CircleGeometry, Color, CylinderGeometry, DoubleSide, Group, LineBasicMaterial,
  LineSegments, Matrix4, Mesh, MeshBasicMaterial, OctahedronGeometry, PlaneGeometry, Points, PointsMaterial, RingGeometry, ShaderMaterial,
  Vector3,
} from "three";
import { findLead, type SocietyAgent } from "../../../data";
import { useProgression } from "../../../progression/progressionStore";
import { rankFor } from "../../levels/ranks";
import type { DeckPlan, Prop } from "../../plan/types";
import { ConsoleScreens, textPlane } from "../../render/deck/DeckScene";
import type { ScreenContent, ScreenState } from "../../render/deck/screens";
import { annulus, GeoBatch } from "../../render/kit/geo";
import { castsShadow, finishMaterial, receivesShadow } from "../../render/kit/materials";
import { SHIP } from "../../render/kit/palette";
import { captain, useShip } from "../../shipStore";
import { DESTINATIONS, destinationById, openDestinations, type Destination } from "../../space/destinations";
import type { DeckSceneProps, ShipActions } from "../registry";
import { BOW, COMMAND, STAR_CHART, VIEWSCREEN_INSET, VIEWSCREEN_SPAN, WELL_R } from "./bridgeDeck";
import { bridgeRuntime, WARP_MS } from "./bridgeRuntime";

const TAU = Math.PI * 2;
const SCREEN_KINDS: readonly Prop["kind"][] = ["helmConsole", "console"];

export function BridgeScene({ plan, reduced, quality, agents, actions }: DeckSceneProps) {
  useEffect(() => {
    bridgeRuntime.leadId = findLead([...agents.values()])?.agentId ?? null;
  }, [agents]);
  useEffect(() => () => { bridgeRuntime.seatRequestedMs = 0; }, []);
  return (
    <>
      <CommandWell />
      <BridgeScreens plan={plan} agents={agents} actions={actions} />
      <ViewscreenHolo reduced={reduced} t={actions.t} />
      <StarChartHolo reduced={reduced} quality={quality} t={actions.t} />
      <SitOnArrival plan={plan} actions={actions} />
      {!reduced && <WarpJump plan={plan} />}
    </>
  );
}

function destinationName(t: ShipActions["t"], d: Destination): string {
  return t(`ship.bridge.destination.${d.id}.name`);
}

// ── the command well ─────────────────────────────────────────────────

/** A flat disc with uvs in world metres (so the carpet's weave keeps its scale). */
function disc(radius: number, at: { x: number; z: number }, y: number): BufferGeometry {
  const g = new CircleGeometry(radius, 72);
  g.rotateX(-Math.PI / 2);
  g.translate(at.x, y, at.z);
  const pos = g.attributes.position;
  const uv = g.attributes.uv as BufferAttribute;
  for (let i = 0; i < pos.count; i += 1) uv.setXY(i, pos.getX(i), pos.getZ(i));
  return g;
}

/**
 * The well round the captain's chair reads as a step down: a warm carpet, a
 * shadowed band at the riser's foot, a dark nosing with a light line on its
 * edge. The floor itself stays flat, so walking needs no ramps.
 */
function CommandWell() {
  const meshes = useMemo(() => {
    const batch = new GeoBatch();
    const root = batch.frame(new Matrix4());
    root.geo("carpet", disc(WELL_R, COMMAND, 0.014), "#e6c8a2");
    root.geo("carpet", annulus(WELL_R - 0.42, WELL_R, 0, TAU, 96), "#6e5a4c", { x: COMMAND.x, y: 0.016, z: COMMAND.z });
    root.geo("structure", annulus(WELL_R, WELL_R + 0.26, 0, TAU, 96), SHIP.panelDark, { x: COMMAND.x, y: 0.018, z: COMMAND.z });
    root.geo("glow", annulus(WELL_R + 0.005, WELL_R + 0.03, 0, TAU, 96), SHIP.lightWarm, { x: COMMAND.x, y: 0.021, z: COMMAND.z });
    // A gold inlay round the chair.
    root.geo("glowSoft", annulus(1.5, 1.52, 0, TAU, 72), SHIP.goldDeep, { x: COMMAND.x, y: 0.02, z: COMMAND.z + 0.4 });
    return batch.merged().map(({ finish, geometry }) => {
      const mesh = new Mesh(geometry, finishMaterial(finish));
      mesh.castShadow = castsShadow(finish);
      mesh.receiveShadow = receivesShadow(finish);
      mesh.raycast = () => undefined;
      return mesh;
    });
  }, []);
  useEffect(() => () => { for (const m of meshes) m.geometry.dispose(); }, [meshes]);
  return <>{meshes.map((m, i) => <primitive key={i} object={m} />)}</>;
}

// ── the console screens ──────────────────────────────────────────────

/** "LABEL     value", in the screens' monospace rows. */
function row(label: string, value: string): string {
  return `${label.toUpperCase().padEnd(10)} ${value}`;
}

const STATE_ORDER: Record<SocietyAgent["state"], number> = { waiting: 0, working: 1, idle: 2, paused: 3 };

function BridgeScreens({ plan, agents, actions }: { plan: DeckPlan; agents: ReadonlyMap<string, SocietyAgent>; actions: ShipActions }) {
  const { t } = actions;
  const destinationId = useShip((s) => s.destination);
  const warpingTo = useShip((s) => s.warpingTo);
  const person = useProgression((s) => s.subjects.person);
  const level = person?.level ?? 1;
  const crew = useMemo(() => [...agents.values()].sort((a, b) => STATE_ORDER[a.state] - STATE_ORDER[b.state] || a.name.localeCompare(b.name)), [agents]);
  const lead = useMemo(() => findLead(crew), [crew]);

  const content = useCallback((p: Prop): ScreenContent => {
    const accent = p.accent ?? SHIP.cyan;
    const here = destinationById(destinationId);
    const base = (title: string, state: ScreenState, stateLabel: string, rows: string[]): ScreenContent => ({
      title, state, accent, rows, stateLabel, standby: t("ship.screen.standby"),
    });
    switch (p.id) {
      case "helm-console": {
        const to = warpingTo ? destinationById(warpingTo) : null;
        const next = DESTINATIONS.find((d) => d.level > level);
        return base(t("ship.bridge.screen.helm"), to ? "working" : "idle", to ? t("ship.bridge.screen.warp") : t("ship.bridge.screen.holding"), [
          row(t("ship.bridge.screen.course"), to ? `${destinationName(t, here)} → ${destinationName(t, to)}` : destinationName(t, here)),
          row(t("ship.bridge.screen.charted"), `${openDestinations(level).length} / ${DESTINATIONS.length}`),
          next ? row(t("ship.bridge.screen.next"), `${destinationName(t, next)} · L${next.level}`) : t("ship.bridge.screen.all_charted"),
        ]);
      }
      case "ops-console": {
        if (crew.length === 0) return base(t("ship.bridge.screen.ops"), "vacant", t("ship.state.vacant"), [t("ship.bridge.screen.no_crew")]);
        const n = { working: 0, waiting: 0, idle: 0, paused: 0 };
        for (const a of crew) n[a.state] += 1;
        const state: ScreenState = n.waiting ? "waiting" : n.working ? "working" : "idle";
        return base(t("ship.bridge.screen.ops"), state, t(`ship.state.${state}`), [
          t("ship.crew.working").replace("{count}", String(n.working)),
          t("ship.crew.waiting").replace("{count}", String(n.waiting)),
          t("ship.crew.idle").replace("{count}", String(n.idle + n.paused)),
          ...crew.filter((a) => a.state === "waiting").slice(0, 3).map((a) => `! ${a.name}`),
        ]);
      }
      case "personnel-console": {
        if (crew.length === 0) return base(t("ship.bridge.screen.personnel"), "vacant", t("ship.state.vacant"), [t("ship.bridge.screen.no_crew")]);
        const shown = crew.slice(0, crew.length > 7 ? 6 : 7).map((a) => `${a.name.slice(0, 20).padEnd(21)}${t(`ship.state.${a.state}`)}`);
        if (crew.length > 7) shown.push(t("ship.bridge.screen.more").replace("{count}", String(crew.length - 6)));
        return base(t("ship.bridge.screen.personnel"), "idle", String(crew.length), shown);
      }
      case "comms-console":
        if (!lead) return base(t("ship.bridge.screen.comms"), "vacant", t("ship.state.vacant"), [t("ship.bridge.screen.no_lead")]);
        return base(t("ship.bridge.screen.comms"), lead.state, t(`ship.state.${lead.state}`), [lead.name, lead.title, t("ship.bridge.screen.comms_hint")].filter(Boolean));
      case "science-console": {
        const facts = [
          destinationName(t, here),
          t(`ship.bridge.body.${here.planet.kind}`),
          here.sun.twin ? t("ship.bridge.screen.twin_suns") : t("ship.bridge.screen.one_sun"),
          here.planet.rings ? t("ship.bridge.screen.rings") : "",
          here.planet.cityLights ? t("ship.bridge.screen.cities") : "",
          here.singularity ? t("ship.bridge.screen.singularity") : "",
        ].filter(Boolean);
        return base(t("ship.bridge.screen.science"), "idle", t("ship.bridge.screen.live"), facts);
      }
      case "navigation-console": {
        const others = DESTINATIONS.filter((d) => d.id !== here.id).slice(0, 6);
        return base(t("ship.bridge.screen.navigation"), "idle", `${openDestinations(level).length} / ${DESTINATIONS.length}`, [
          `▸ ${destinationName(t, here)}`,
          ...others.map((d) => (d.level <= level ? `  ${destinationName(t, d)}` : `  ${destinationName(t, d).padEnd(22)}L${d.level}`)),
        ]);
      }
      case "ready-desk": {
        const rank = rankFor(level);
        return base(t("ship.bridge.screen.record"), "idle", t("ship.level").replace("{n}", String(level)), [
          t(`ship.rank.${rank.id}`),
          person ? `${person.xpIntoLevel} / ${person.xpForNext} XP` : "",
        ].filter(Boolean));
      }
      default:
        return base("", "vacant", t("ship.screen.vacant"), []);
    }
  }, [t, destinationId, warpingTo, level, person, crew, lead]);

  const onScreen = useCallback((p: Prop) => {
    if (p.id === "helm-console") actions.openPanel("helm");
    else if (p.id === "ops-console" || p.id === "personnel-console") actions.openLedger();
    else if (p.id === "comms-console" && lead) actions.openAgent(lead.agentId);
  }, [actions, lead]);

  return <ConsoleScreens plan={plan} content={content} onScreen={onScreen} kinds={SCREEN_KINDS} />;
}

// ── the viewscreen overlay ───────────────────────────────────────────

const GRID_VERT = /* glsl */ `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const GRID_FRAG = /* glsl */ `uniform float uTime; uniform float uWarp; uniform vec3 uColour; varying vec2 vUv;
  float line(float x, float w) { float d = abs(fract(x) - 0.5); return smoothstep(0.5 - w, 0.5, d); }
  void main() {
    vec2 g = vec2(vUv.x * 28.0 + uTime * 0.05, vUv.y * 5.0);
    float grid = max(line(g.x, 0.035), line(g.y, 0.05)) * 0.55;
    float horizon = smoothstep(0.012, 0.0, abs(vUv.y - 0.42));
    float sweep = smoothstep(0.06, 0.0, abs(fract(vUv.x - uTime * 0.03) - 0.5)) * 0.35;
    float ticks = step(0.5 - 0.06, abs(fract(vUv.x * 56.0) - 0.5)) * smoothstep(0.03, 0.0, abs(vUv.y - 0.42)) * 0.8;
    float edge = smoothstep(0.0, 0.08, vUv.x) * smoothstep(1.0, 0.92, vUv.x) * smoothstep(0.0, 0.12, vUv.y) * smoothstep(1.0, 0.85, vUv.y);
    float a = (grid + horizon * 0.8 + ticks + sweep * (0.4 + uWarp)) * edge * (0.22 + uWarp * 0.5);
    gl_FragColor = vec4(uColour * a, a);
  }`;

/**
 * A framed hologram over the middle of the bow window: a slow tactical grid
 * with a bearing line, the destination's name above it (the jump's target
 * while the ship is at warp). Hidden while the camera is out beyond the bow.
 */
function ViewscreenHolo({ reduced, t }: { reduced: boolean; t: ShipActions["t"] }) {
  const destinationId = useShip((s) => s.destination);
  const warpingTo = useShip((s) => s.warpingTo);
  const group = useRef<Group>(null);
  const radius = BOW.radius - VIEWSCREEN_INSET - 0.24;
  const grid = useMemo(() => {
    const geo = new CylinderGeometry(radius, radius, 1.12, 64, 1, true, -VIEWSCREEN_SPAN, VIEWSCREEN_SPAN * 2);
    const mat = new ShaderMaterial({
      vertexShader: GRID_VERT, fragmentShader: GRID_FRAG, transparent: true, blending: AdditiveBlending, depthWrite: false, side: DoubleSide,
      uniforms: { uTime: { value: 0 }, uWarp: { value: 0 }, uColour: { value: new Color(SHIP.cyan).multiplyScalar(1.5) } },
    });
    const mesh = new Mesh(geo, mat);
    mesh.position.set(BOW.centre.x, 1.58, BOW.centre.z);
    mesh.rotation.y = Math.PI;
    mesh.raycast = () => undefined;
    return mesh;
  }, [radius]);
  useEffect(() => () => { grid.geometry.dispose(); (grid.material as ShaderMaterial).dispose(); }, [grid]);

  const target = warpingTo ? destinationById(warpingTo) : destinationById(destinationId);
  const name = destinationName(t, target);
  const eyebrow = (warpingTo ? t("ship.bridge.viewscreen.warp") : t("ship.bridge.viewscreen.destination")).toUpperCase();
  const labels = useMemo(() => {
    const at = { x: BOW.centre.x, z: BOW.centre.z - radius + 0.05 };
    const title = textPlane(name, SHIP.cyan, { size: 0.28 });
    title.position.set(at.x, 1.86, at.z);
    const over = textPlane(eyebrow, SHIP.gold, { size: 0.13, font: "600 64px 'Space Grotesk', 'Inter Variable', sans-serif" });
    over.position.set(at.x, 2.07, at.z);
    return [title, over];
  }, [name, eyebrow, radius]);
  useEffect(() => () => {
    for (const m of labels) { m.geometry.dispose(); const mat = m.material as MeshBasicMaterial; mat.map?.dispose(); mat.dispose(); }
  }, [labels]);

  const warp = useRef(0);
  useFrame(({ camera, clock }, dt) => {
    const g = group.current;
    if (!g) return;
    // Beyond the bow the frame has sunk with the hull: no picture without its frame.
    g.visible = Math.hypot(camera.position.x - BOW.centre.x, camera.position.z - BOW.centre.z) < BOW.radius || camera.position.z > BOW.centre.z;
    const u = (grid.material as ShaderMaterial).uniforms;
    warp.current += ((useShip.getState().warpingTo ? 1 : 0) - warp.current) * Math.min(1, dt * 2.5);
    u.uTime.value = reduced ? 0 : clock.elapsedTime;
    u.uWarp.value = reduced ? 0 : warp.current;
  });
  return (
    <group ref={group}>
      <primitive object={grid} />
      {labels.map((m, i) => <primitive key={i} object={m} />)}
    </group>
  );
}

// ── the star chart ───────────────────────────────────────────────────

const GALAXY_R = 1.05;
const CHART_Y = 1.34;

function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}

/** Where a destination lies on the chart: home out on an arm, the galactic core at the heart. */
export function chartPosition(d: Destination, index: number): { x: number; y: number; z: number } {
  const r = GALAXY_R * Math.max(0.08, 0.92 - (d.level / 44) * 0.86);
  const a = index * 2.25 + 0.6;
  return { x: Math.sin(a) * r, y: 0.025, z: Math.cos(a) * r };
}

/**
 * The hologram over the star chart table: a two-armed galaxy of points
 * turning slowly, each destination a marker (gold where the ship is, cyan
 * when the captain's level opens it, dim when it is still locked), the
 * current one ringed and named.
 */
function StarChartHolo({ reduced, quality, t }: { reduced: boolean; quality: "high" | "low"; t: ShipActions["t"] }) {
  const level = useProgression((s) => s.subjects.person?.level ?? 1);
  const destinationId = useShip((s) => s.destination);
  const spin = useRef<Group>(null);
  const galaxy = useMemo(() => {
    const n = quality === "high" ? 2600 : 1200;
    const r = rng(11);
    const pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
    const warm = new Color("#ffe2b8"), cool = new Color("#7fcfff"), deep = new Color("#3c6fd8"), c = new Color();
    for (let i = 0; i < n; i += 1) {
      const bulge = i < n * 0.18;
      const f = bulge ? Math.pow(r(), 2) * 0.22 : 0.12 + Math.pow(r(), 0.8) * 0.88;
      const arm = (i % 2) * Math.PI;
      const a = bulge ? r() * TAU : arm + f * 3.4 + (r() - 0.5) * (0.5 - f * 0.25);
      const rad = f * GALAXY_R;
      const thick = (r() - 0.5) * (bulge ? 0.16 : 0.05) * (1.2 - f);
      pos[i * 3] = Math.sin(a) * rad; pos[i * 3 + 1] = thick; pos[i * 3 + 2] = Math.cos(a) * rad;
      c.copy(warm).lerp(f < 0.35 ? cool : deep, Math.min(1, f * 1.3)).multiplyScalar(0.55 + r() * 0.6);
      col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
    }
    const g = new BufferGeometry();
    g.setAttribute("position", new BufferAttribute(pos, 3));
    g.setAttribute("color", new BufferAttribute(col, 3));
    const m = new PointsMaterial({ size: 0.03, sizeAttenuation: true, vertexColors: true, transparent: true, depthWrite: false, blending: AdditiveBlending, toneMapped: false });
    m.color.setScalar(1.7);
    const p = new Points(g, m);
    p.raycast = () => undefined;
    return p;
  }, [quality]);
  const markers = useMemo(() => DESTINATIONS.map((d, i) => {
    const mesh = new Mesh(new OctahedronGeometry(0.035, 0), new MeshBasicMaterial({ toneMapped: false, transparent: true, depthWrite: false }));
    const at = chartPosition(d, i);
    mesh.position.set(at.x, at.y + 0.02, at.z);
    mesh.raycast = () => undefined;
    return { d, mesh };
  }), []);
  const ring = useMemo(() => {
    const m = new Mesh(new RingGeometry(0.075, 0.09, 40), new MeshBasicMaterial({ color: new Color(SHIP.gold).multiplyScalar(2), toneMapped: false, transparent: true, depthWrite: false, side: DoubleSide }));
    m.rotation.x = -Math.PI / 2;
    m.raycast = () => undefined;
    return m;
  }, []);
  const cone = useMemo(() => {
    const m = new Mesh(new CylinderGeometry(GALAXY_R * 1.02, 0.62, CHART_Y - 0.93, 48, 1, true),
      new MeshBasicMaterial({ color: new Color(SHIP.cyan).multiplyScalar(0.5), transparent: true, opacity: 0.07, blending: AdditiveBlending, depthWrite: false, side: DoubleSide, toneMapped: false }));
    m.position.set(STAR_CHART.x, (CHART_Y + 0.93) / 2, STAR_CHART.z);
    m.raycast = () => undefined;
    return m;
  }, []);
  const here = destinationById(destinationId);
  const label = useMemo(() => {
    const m = textPlane(destinationName(t, here), SHIP.gold, { size: 0.14 });
    m.position.set(STAR_CHART.x, CHART_Y + 0.42, STAR_CHART.z);
    return m;
  }, [t, here]);

  useEffect(() => {
    for (const { d, mesh } of markers) {
      const mat = mesh.material as MeshBasicMaterial;
      const open = d.level <= Math.max(1, level);
      mat.color.set(d.id === here.id ? SHIP.gold : open ? SHIP.cyan : SHIP.steel).multiplyScalar(d.id === here.id ? 2.4 : open ? 1.8 : 0.5);
      mat.opacity = open ? 1 : 0.45;
      mesh.scale.setScalar(d.id === here.id ? 1.5 : open ? 1 : 0.75);
      if (d.id === here.id) ring.position.set(mesh.position.x, mesh.position.y, mesh.position.z);
    }
  }, [markers, ring, level, here]);

  useEffect(() => () => {
    galaxy.geometry.dispose(); (galaxy.material as PointsMaterial).dispose();
    for (const { mesh } of markers) { mesh.geometry.dispose(); (mesh.material as MeshBasicMaterial).dispose(); }
    ring.geometry.dispose(); (ring.material as MeshBasicMaterial).dispose();
    cone.geometry.dispose(); (cone.material as MeshBasicMaterial).dispose();
  }, [galaxy, markers, ring, cone]);
  useEffect(() => () => { label.geometry.dispose(); const m = label.material as MeshBasicMaterial; m.map?.dispose(); m.dispose(); }, [label]);

  const tmp = useMemo(() => new Vector3(), []);
  useFrame(({ camera, clock }, dt) => {
    const t2 = reduced ? 0 : clock.elapsedTime;
    if (spin.current && !reduced) spin.current.rotation.y += dt * 0.06;
    ring.scale.setScalar(1 + Math.sin(t2 * 2.4) * 0.15);
    for (const { mesh } of markers) mesh.rotation.y = t2 * 0.8;
    label.getWorldPosition(tmp);
    label.lookAt(camera.position.x, tmp.y, camera.position.z);
  });

  return (
    <>
      <primitive object={cone} />
      <group position={[STAR_CHART.x, CHART_Y, STAR_CHART.z]} rotation={[0.12, 0, 0]}>
        <group ref={spin}>
          <primitive object={galaxy} />
          {markers.map(({ d, mesh }) => <primitive key={d.id} object={mesh} />)}
          <primitive object={ring} />
        </group>
      </group>
      <primitive object={label} />
    </>
  );
}

// ── sitting down on arrival ──────────────────────────────────────────

/** A captain sent to the chair from afar sits down on arriving (any other stop cancels it). */
function SitOnArrival({ plan, actions }: { plan: DeckPlan; actions: ShipActions }) {
  useFrame(() => {
    const asked = bridgeRuntime.seatRequestedMs;
    if (!asked || performance.now() - asked < 400 || captain.moving || captain.path.length > 0) return;
    bridgeRuntime.seatRequestedMs = 0;
    const station = plan.stations.find((s) => s.kind === "captain");
    const seat = plan.places.find((p) => p.kind === "captain");
    if (!station || !seat || Math.hypot(captain.x - station.x, captain.z - station.z) > station.radius) return;
    actions.sit({ x: seat.x, z: seat.z, yaw: seat.yaw, seatY: seat.seatY });
  });
  return null;
}

// ── the warp jump ────────────────────────────────────────────────────

const STREAKS = 340;
const FIELD_LEN = 420;

const FLASH_VERT = /* glsl */ `void main() { gl_Position = vec4(position.xy, 0.0, 1.0); }`;
const FLASH_FRAG = /* glsl */ `uniform float uAmount; void main() { gl_FragColor = vec4(vec3(0.92, 0.96, 1.0) * (1.0 + uAmount), uAmount); }`;

/**
 * Stars streaking past the ship from bow to stern: a field of a few hundred
 * additive lines round the deck that grow longer and faster with the jump's
 * progress, then a flash that hides the change of sky, then the field fades
 * as the ship drops out at the new destination.
 */
function WarpJump({ plan }: { plan: DeckPlan }) {
  const warpingTo = useShip((s) => s.warpingTo);
  const clock = useRef({ start: 0, end: 0, peak: 0 });
  useEffect(() => {
    const now = performance.now();
    if (warpingTo) { clock.current.start = now; clock.current.end = 0; }
    else if (clock.current.start) { clock.current.end = now; }
  }, [warpingTo]);

  const field = useMemo(() => {
    const r = rng(29);
    const seeds = Array.from({ length: STREAKS }, () => {
      const a = r() * TAU, rad = 22 + Math.pow(r(), 0.7) * 150;
      return { x: Math.cos(a) * rad, y: Math.sin(a) * rad * 0.65, z: r() * FIELD_LEN, speed: 0.6 + r() * 0.8, tint: r() };
    });
    const g = new BufferGeometry();
    g.setAttribute("position", new BufferAttribute(new Float32Array(STREAKS * 6), 3));
    g.setAttribute("color", new BufferAttribute(new Float32Array(STREAKS * 6), 3));
    const m = new LineBasicMaterial({ vertexColors: true, transparent: true, blending: AdditiveBlending, depthWrite: false, toneMapped: false });
    const lines = new LineSegments(g, m);
    lines.frustumCulled = false;
    lines.visible = false;
    lines.raycast = () => undefined;
    return { lines, seeds, offset: 0 };
  }, []);
  const flash = useMemo(() => {
    const m = new Mesh(new PlaneGeometry(2, 2), new ShaderMaterial({
      vertexShader: FLASH_VERT, fragmentShader: FLASH_FRAG, transparent: true, depthTest: false, depthWrite: false, toneMapped: false,
      uniforms: { uAmount: { value: 0 } },
    }));
    m.frustumCulled = false;
    m.renderOrder = 999;
    m.visible = false;
    m.raycast = () => undefined;
    return m;
  }, []);
  useEffect(() => () => {
    field.lines.geometry.dispose(); (field.lines.material as LineBasicMaterial).dispose();
    flash.geometry.dispose(); (flash.material as ShaderMaterial).dispose();
  }, [field, flash]);

  const cx = (plan.bounds.x0 + plan.bounds.x1) / 2, cz = (plan.bounds.z0 + plan.bounds.z1) / 2;
  const blue = useMemo(() => new Color("#9fd4ff"), []), white = useMemo(() => new Color("#f4f8ff"), []), c = useMemo(() => new Color(), []);
  useFrame((_, rawDt) => {
    const dt = Math.min(0.1, rawDt);
    const now = performance.now();
    const k = clock.current;
    let progress = 0, flashAmount = 0;
    if (k.start && !k.end) {
      const s = Math.min(1, (now - k.start) / WARP_MS);
      progress = s * s;
      k.peak = progress;
      flashAmount = Math.min(1, Math.max(0, (s - 0.86) / 0.11));
    } else if (k.end) {
      const out = (now - k.end) / 900;
      progress = k.peak * Math.max(0, 1 - out);
      flashAmount = Math.max(0, 1 - (now - k.end) / 650);
      if (out >= 1 && flashAmount <= 0) { k.start = 0; k.end = 0; k.peak = 0; }
    }
    const fm = flash.material as ShaderMaterial;
    fm.uniforms.uAmount.value = flashAmount;
    flash.visible = flashAmount > 0.001;
    const lines = field.lines;
    lines.visible = progress > 0.002;
    if (!lines.visible) return;
    field.offset += dt * (25 + 1500 * progress * progress);
    const len = 0.4 + 95 * Math.pow(progress, 1.5);
    const bright = Math.min(1, progress * 3) * 2.2;
    const pos = lines.geometry.attributes.position as BufferAttribute;
    const col = lines.geometry.attributes.color as BufferAttribute;
    field.seeds.forEach((s, i) => {
      // Bow to stern: the ship flies towards -z, so the stars run towards +z.
      const z = cz - FIELD_LEN / 2 + ((s.z + field.offset * s.speed) % FIELD_LEN);
      const x = cx + s.x, y = s.y;
      pos.setXYZ(i * 2, x, y, z);
      pos.setXYZ(i * 2 + 1, x, y, z - len * s.speed);
      c.copy(blue).lerp(white, s.tint).multiplyScalar(bright);
      col.setXYZ(i * 2, c.r, c.g, c.b);
      col.setXYZ(i * 2 + 1, 0, 0, 0);
    });
    pos.needsUpdate = true;
    col.needsUpdate = true;
  });
  return (
    <>
      <primitive object={field.lines} />
      <primitive object={flash} />
    </>
  );
}
