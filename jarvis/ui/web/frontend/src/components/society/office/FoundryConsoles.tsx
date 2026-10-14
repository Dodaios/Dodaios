/**
 * The coding floor's workstations: dark steel consoles with a light edge in
 * the bay's colour, a signal bar between each back-to-back pair, the monitor
 * the pane's terminal is drawn on, and a pilot's chair. Node towers with
 * running lights close every bench's ends (the layout's bench-planter
 * footprints).
 *
 * The signal bar is the desk's status light, read from the pane:
 * working = the bay's colour, breathing; asking = amber, blinking; failed =
 * red; idle = a dim steel glow; a free desk stays dark. A pane that asks or
 * failed also raises a beam of its colour from its desk into the sky, so the
 * person sees from anywhere on the deck who needs them.
 *
 * Every repeated part is one instanced mesh; the status colours are rewritten
 * a few times a second, not every frame.
 */
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import {
  AdditiveBlending, BufferGeometry, Color, CylinderGeometry, DoubleSide, Euler, InstancedMesh, Matrix4, MeshBasicMaterial,
  MeshStandardMaterial, PlaneGeometry, Quaternion, RepeatWrapping, RingGeometry, Vector3, type Material, type Mesh,
} from "three";
import { RoundedBoxGeometry } from "three-stdlib";
import type { AgentDotKind } from "@/components/agentic/sidePanel/agentStatus";
import { cachedCanvasTexture } from "./canvasMaterials";
import type { PaneOccupant } from "./codingFloor";
import { CHAIR_MAT, TASK_CHAIR_PARTS, type ChairFinish } from "./OfficeChairs";
import { GEO, screenMaterial } from "./OfficeFurniture";
import { benchPlanters, type Department, type DeskSlot } from "./officeLayout";
import { baySignal, FOUNDRY, glowColour } from "./foundryPalette";
import type { ScreenFace } from "./screenTextures";

const rounded = (w: number, h: number, d: number, r: number) => new RoundedBoxGeometry(w, h, d, 1, r);

/** Self-lit parts: white × instance colour × this, past the bloom threshold. */
const LIT = 1.8;

const CMAT = {
  top: new MeshStandardMaterial({ color: "#2b2f37", roughness: 0.35, metalness: 0.55 }),
  side: new MeshStandardMaterial({ color: FOUNDRY.steel, roughness: 0.4, metalness: 0.65 }),
  panel: new MeshStandardMaterial({ color: FOUNDRY.steelDark, roughness: 0.5, metalness: 0.5 }),
  gold: new MeshStandardMaterial({ color: FOUNDRY.gold, roughness: 0.28, metalness: 0.85 }),
  bezel: new MeshStandardMaterial({ color: "#0d0f13", roughness: 0.3, metalness: 0.3 }),
  arm: new MeshStandardMaterial({ color: "#3d424c", roughness: 0.3, metalness: 0.7 }),
  keys: new MeshStandardMaterial({ color: "#14161a", roughness: 0.5 }),
  /** White: each instance's colour is the light's colour. */
  lit: new MeshBasicMaterial({ color: new Color(LIT, LIT, LIT), toneMapped: false }),
  chairFrame: new MeshStandardMaterial({ color: "#1b1d22", roughness: 0.45, metalness: 0.3 }),
  /** White: the seat takes its bay's colour, darkened, per instance. */
  seat: new MeshStandardMaterial({ color: "#ffffff", roughness: 0.7 }),
  chairMesh: new MeshStandardMaterial({ color: "#16181c", roughness: 0.9, side: DoubleSide }),
};

type Tint = "edge" | "signal" | "seat";

interface Part {
  geometry: BufferGeometry;
  material: Material;
  position: [number, number, number];
  scale?: [number, number, number];
  tint?: Tint;
  cast: boolean;
}

const CHAIR_Z = 0.62;
const CHAIR_MATERIAL: Record<ChairFinish, Material> = { frame: CMAT.chairFrame, fabric: CMAT.seat, metal: CHAIR_MAT.aluminium, mesh: CMAT.chairMesh };

/** One workstation in its own space: the agent sits at +z, the monitor is at -z. Top surface at 0.77 m. */
const PARTS: Part[] = [
  { geometry: rounded(1.5, 0.04, 0.8, 0.012), material: CMAT.top, position: [0, 0.75, 0], cast: true },
  // The light edge along the front of the top.
  { geometry: GEO.box, material: CMAT.lit, position: [0, 0.735, 0.402], scale: [1.42, 0.012, 0.01], tint: "edge", cast: false },
  // Waterfall sides, a modesty panel and a gold kick line.
  ...[-0.71, 0.71].map((x): Part => ({ geometry: GEO.box, material: CMAT.side, position: [x, 0.365, 0], scale: [0.06, 0.73, 0.78], cast: true })),
  { geometry: GEO.box, material: CMAT.panel, position: [0, 0.45, -0.34], scale: [1.36, 0.5, 0.03], cast: false },
  { geometry: GEO.box, material: CMAT.gold, position: [0, 0.025, -0.33], scale: [1.36, 0.02, 0.025], cast: false },
  // The signal bar between back-to-back desks: a dark fin with the status light along its top.
  { geometry: rounded(1.46, 0.3, 0.035, 0.01), material: CMAT.panel, position: [0, 0.92, -0.41], cast: true },
  { geometry: GEO.box, material: CMAT.lit, position: [0, 1.075, -0.41], scale: [1.44, 0.02, 0.04], tint: "signal", cast: false },
  // Monitor on an arm, a thin backlight in the bay's colour behind it.
  { geometry: GEO.box, material: CMAT.arm, position: [0, 0.795, -0.33], scale: [0.08, 0.05, 0.06], cast: false },
  { geometry: GEO.cyl, material: CMAT.arm, position: [0, 0.95, -0.33], scale: [0.018, 0.32, 0.018], cast: true },
  { geometry: GEO.box, material: CMAT.arm, position: [0, 1.1, -0.28], scale: [0.04, 0.03, 0.1], cast: false },
  { geometry: rounded(0.72, 0.43, 0.022, 0.012), material: CMAT.bezel, position: [0, 1.18, -0.224], cast: true },
  { geometry: GEO.box, material: CMAT.lit, position: [0, 0.962, -0.236], scale: [0.6, 0.008, 0.008], tint: "edge", cast: false },
  // Keyboard and mouse.
  { geometry: GEO.box, material: CMAT.keys, position: [0, 0.777, 0.22], scale: [0.46, 0.014, 0.14], cast: true },
  { geometry: GEO.box, material: CMAT.keys, position: [0.34, 0.78, 0.22], scale: [0.05, 0.02, 0.08], cast: false },
  // Pilot's chair: the task chair in dark steel, its seat in the bay's colour.
  ...TASK_CHAIR_PARTS.map((part): Part => ({
    geometry: part.geometry, material: CHAIR_MATERIAL[part.finish], position: [0, 0, CHAIR_Z],
    tint: part.finish === "fabric" ? "seat" : undefined, cast: part.cast,
  })),
];

const SCREEN_GEOMETRY = new PlaneGeometry(0.66, 0.38);
const SCREEN_LOCAL: [number, number, number] = [0, 1.18, -0.212];
const FACES: ScreenFace[] = ["working", "idle", "waiting", "paused", "empty"];

const _q = new Quaternion(), _e = new Euler(), _p = new Vector3(), _s = new Vector3();
function deskMatrix(desk: DeskSlot, local: [number, number, number], scale: [number, number, number] = [1, 1, 1]): Matrix4 {
  const world = new Matrix4().compose(_p.set(desk.x, 0, desk.z), _q.setFromEuler(_e.set(0, desk.facing === "north" ? 0 : Math.PI, 0)), _s.set(1, 1, 1));
  return world.multiply(new Matrix4().compose(new Vector3(...local), new Quaternion(), new Vector3(...scale)));
}

/** A moment at which every blinking or breathing signal is lit: the still frame under reduced motion. */
const REST_T = 0.1;

/** The status a desk's light shows. */
export type DeskSignal = AgentDotKind | "free";

const STATUS_COLOUR = {
  waiting: glowColour(FOUNDRY.status.asking, 0.8),
  error: glowColour(FOUNDRY.status.failed, 0.8),
  idle: new Color("#4a5566").multiplyScalar(0.45),
  free: new Color("#0c0d10"),
};

/** The colour of a desk's signal light at time `t` (s). Pure. */
export function signalColour(signal: DeskSignal, bay: Color, t: number, out: Color): Color {
  switch (signal) {
    case "working": return out.copy(bay).multiplyScalar(0.55 + 0.45 * (0.5 + 0.5 * Math.sin(t * 2.4)));
    case "waiting": return out.copy(STATUS_COLOUR.waiting).multiplyScalar(Math.sin(t * 6) > 0 ? 1 : 0.25);
    case "error": return out.copy(STATUS_COLOUR.error).multiplyScalar(0.6 + 0.4 * (0.5 + 0.5 * Math.sin(t * 3)));
    case "idle": return out.copy(STATUS_COLOUR.idle);
    default: return out.copy(STATUS_COLOUR.free);
  }
}

interface DeskInfo { desk: DeskSlot; bay: Color; seat: Color; signal: DeskSignal }

function PartInstances({ part, infos, animate }: { part: Part; infos: readonly DeskInfo[]; animate: boolean }) {
  const ref = useRef<InstancedMesh>(null);
  const colour = useMemo(() => new Color(), []);
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    infos.forEach((info, i) => {
      mesh.setMatrixAt(i, deskMatrix(info.desk, part.position, part.scale));
      if (part.tint === "edge") mesh.setColorAt(i, colour.copy(info.bay).multiplyScalar(info.signal === "free" ? 0.25 : 0.8));
      if (part.tint === "seat") mesh.setColorAt(i, info.seat);
      // At rest (reduced motion) the light holds a lit phase: an asking desk must not sit at its dark blink.
      if (part.tint === "signal") mesh.setColorAt(i, signalColour(info.signal, info.bay, REST_T, colour));
    });
    mesh.count = infos.length;
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [infos, part, colour]);
  const next = useRef(0);
  useFrame(({ clock }) => {
    if (part.tint !== "signal" || !animate || clock.elapsedTime < next.current) return;
    next.current = clock.elapsedTime + 0.08;
    const mesh = ref.current;
    if (!mesh) return;
    infos.forEach((info, i) => mesh.setColorAt(i, signalColour(info.signal, info.bay, clock.elapsedTime + i * 0.37, colour)));
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  });
  return <instancedMesh ref={ref} args={[part.geometry, part.material, Math.max(1, infos.length)]} castShadow={part.cast} receiveShadow frustumCulled={false} />;
}

function ScreenInstances({ face, desks }: { face: ScreenFace; desks: DeskSlot[] }) {
  const ref = useRef<InstancedMesh>(null);
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    desks.forEach((desk, i) => mesh.setMatrixAt(i, deskMatrix(desk, SCREEN_LOCAL)));
    mesh.count = desks.length;
    mesh.instanceMatrix.needsUpdate = true;
  }, [desks]);
  return <instancedMesh key={Math.max(1, desks.length)} ref={ref} args={[SCREEN_GEOMETRY, screenMaterial(face), Math.max(1, desks.length)]} frustumCulled={false} />;
}

// ---------------------------------------------------------------------------
// Node towers at the bench ends
// ---------------------------------------------------------------------------

const TOWER_H = 1.05;

/** Running lights: rows of small LEDs, most dim, some lit (white; the emissive colour tints them). */
function drawLeds(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  ctx.fillStyle = "#15171c";
  ctx.fillRect(0, 0, w, h);
  let seed = 0x1ed5;
  const rand = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 0x1_0000_0000; };
  for (let y = 4; y < h; y += 8) {
    for (let x = 4; x < w; x += 8) {
      const on = rand();
      ctx.fillStyle = on > 0.72 ? "#ffffff" : on > 0.5 ? "#5a6470" : "#262a31";
      ctx.fillRect(x, y, 3, 3);
    }
  }
}

function NodeTowers({ departments, animate }: { departments: readonly Department[]; animate: boolean }) {
  const material = useMemo(() => {
    const base = cachedCanvasTexture("foundry:leds", 64, 128, drawLeds);
    const map = base?.clone() ?? null;
    if (map) { map.wrapS = map.wrapT = RepeatWrapping; map.needsUpdate = true; }
    return new MeshStandardMaterial({
      color: map ? "#ffffff" : FOUNDRY.steelDark, map, roughness: 0.45, metalness: 0.5,
      emissive: new Color(FOUNDRY.code), emissiveMap: map, emissiveIntensity: map ? 1.6 : 0,
    });
  }, []);
  useEffect(() => () => { material.map?.dispose(); material.dispose(); }, [material]);
  const rects = useMemo(() => departments.flatMap((d) => benchPlanters(d).map((p) => p.rect)), [departments]);
  const ref = useRef<InstancedMesh>(null);
  const caps = useRef<InstancedMesh>(null);
  useLayoutEffect(() => {
    const m = new Matrix4();
    rects.forEach((r, i) => {
      const x = (r.minX + r.maxX) / 2, z = (r.minZ + r.maxZ) / 2, w = r.maxX - r.minX, d = r.maxZ - r.minZ;
      ref.current?.setMatrixAt(i, m.compose(_p.set(x, TOWER_H / 2, z), _q.identity(), _s.set(w, TOWER_H, d)));
      caps.current?.setMatrixAt(i, m.compose(_p.set(x, TOWER_H + 0.012, z), _q.identity(), _s.set(w + 0.02, 0.024, d + 0.02)));
    });
    for (const mesh of [ref.current, caps.current]) {
      if (!mesh) continue;
      mesh.count = rects.length;
      mesh.instanceMatrix.needsUpdate = true;
      mesh.computeBoundingSphere();
    }
  }, [rects]);
  // The LEDs run: the texture scrolls slowly, so the lit ones move like traffic.
  useFrame((_, delta) => {
    if (animate && material.map) material.map.offset.y = (material.map.offset.y + Math.min(delta, 0.1) * 0.05) % 1;
  });
  if (rects.length === 0) return null;
  return (
    <group>
      {/* Remount when the count changes: an instanced mesh cannot grow in place. */}
      <instancedMesh key={rects.length} ref={ref} args={[GEO.box, material, rects.length]} castShadow receiveShadow frustumCulled={false} />
      <instancedMesh key={`cap${rects.length}`} ref={caps} args={[GEO.box, CMAT.gold, rects.length]} frustumCulled={false} />
    </group>
  );
}

// ---------------------------------------------------------------------------
// Beams for panes that need the person
// ---------------------------------------------------------------------------

const BEAM_H = 22;
const BEAM_GEOMETRY = new CylinderGeometry(0.11, 0.11, BEAM_H, 12, 1, true);
const BEAM_HALO = new CylinderGeometry(0.34, 0.34, BEAM_H, 16, 1, true);
const RING_GEOMETRY = new RingGeometry(0.42, 0.5, 40);

/** Fades out upwards (white; tinted). */
function drawFade(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const g = ctx.createLinearGradient(0, h, 0, 0);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.3, "rgba(255,255,255,0.5)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
}

const beamMaterials = new Map<string, { core: MeshBasicMaterial; halo: MeshBasicMaterial; ring: MeshBasicMaterial }>();
function beamMaterial(signal: "waiting" | "error") {
  let set = beamMaterials.get(signal);
  if (!set) {
    const map = cachedCanvasTexture("foundry:fade", 32, 256, drawFade);
    const colour = STATUS_COLOUR[signal];
    const make = (k: number) => new MeshBasicMaterial({
      map, color: colour.clone().multiplyScalar(k), transparent: true, depthWrite: false, blending: AdditiveBlending, toneMapped: false, side: DoubleSide,
    });
    set = {
      core: make(1.6), halo: make(0.35),
      ring: new MeshBasicMaterial({ color: colour.clone().multiplyScalar(1.6), transparent: true, depthWrite: false, blending: AdditiveBlending, toneMapped: false }),
    };
    beamMaterials.set(signal, set);
  }
  return set;
}

function SignalBeam({ desk, signal, animate }: { desk: DeskSlot; signal: "waiting" | "error"; animate: boolean }) {
  const m = beamMaterial(signal);
  // Each ripple fades on its own clock, so it needs its own copy of the ring material.
  const ripple = useMemo(() => m.ring.clone(), [m]);
  useEffect(() => () => ripple.dispose(), [ripple]);
  const ringMesh = useRef<Mesh>(null);
  const phase = useMemo(() => Math.abs(desk.x * 3.1 + desk.z * 1.7) % 1, [desk.x, desk.z]);
  useFrame(({ clock }) => {
    const mesh = ringMesh.current;
    if (!mesh) return;
    const p = animate ? (clock.elapsedTime * 0.8 + phase) % 1 : 0.4;
    mesh.scale.setScalar(1 + p * 2.4);
    ripple.opacity = 1 - p;
  });
  // The beam rises from the signal bar between the desks.
  const back = desk.facing === "north" ? -0.41 : 0.41;
  return (
    <group position={[desk.x, 0, desk.z + back]}>
      <mesh geometry={BEAM_GEOMETRY} material={m.core} position={[0, 1.1 + BEAM_H / 2, 0]} renderOrder={3} />
      <mesh geometry={BEAM_HALO} material={m.halo} position={[0, 1.1 + BEAM_H / 2, 0]} renderOrder={3} />
      <mesh ref={ringMesh} geometry={RING_GEOMETRY} material={ripple} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, -back * 0.8]} renderOrder={3} />
    </group>
  );
}

// ---------------------------------------------------------------------------

/** Every console of the coding floor, their status lights and beams, and the node towers. */
export function FoundryConsoles({ departments, occupants, animate }: {
  departments: readonly Department[]; occupants: ReadonlyMap<string, PaneOccupant>; animate: boolean;
}) {
  const infos = useMemo<DeskInfo[]>(() => departments.flatMap((dept) => {
    // The light parts take the bay's colour at a set luminance; the seat its plain colour, darkened.
    const bay = glowColour(baySignal(dept.tint), 0.8);
    const seat = new Color(baySignal(dept.tint)).lerp(new Color("#1b1d22"), 0.55);
    return dept.desks.map((desk) => {
      const occupant = desk.agentId ? occupants.get(desk.agentId) : undefined;
      return { desk, bay, seat, signal: occupant ? occupant.dot : "free" as DeskSignal };
    });
  }), [departments, occupants]);
  const byFace = useMemo(() => {
    const groups = new Map<ScreenFace, DeskSlot[]>(FACES.map((f) => [f, []]));
    for (const info of infos) {
      const occupant = info.desk.agentId ? occupants.get(info.desk.agentId) : undefined;
      groups.get(occupant ? occupant.agent.state : "empty")!.push(info.desk);
    }
    return groups;
  }, [infos, occupants]);
  const beams = infos.filter((i) => i.signal === "waiting" || i.signal === "error");
  return (
    <group>
      {PARTS.map((part, i) => <PartInstances key={`${i}:${infos.length}`} part={part} infos={infos} animate={animate} />)}
      {FACES.map((face) => (byFace.get(face)!.length > 0 ? <ScreenInstances key={face} face={face} desks={byFace.get(face)!} /> : null))}
      <NodeTowers departments={departments} animate={animate} />
      {beams.map((info) => <SignalBeam key={info.desk.id} desk={info.desk} signal={info.signal as "waiting" | "error"} animate={animate} />)}
    </group>
  );
}
