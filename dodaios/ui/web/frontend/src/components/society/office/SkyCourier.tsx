/**
 * The courier: the chrome starship on the sky pad, and the person's flight in
 * it. Parked, it stands on its gear beside the bridge; the ship station
 * (stations.ts) boards it. Flying, this component owns the camera (chase or
 * cockpit), reads the keys and a gamepad, steps the flight (courierFlight.ts)
 * against the city (courierWorld.ts), and drives the ship's looks: gear,
 * engine glow and flames, the engine light, contrails at speed, the shield's
 * flash on impact, dust on the deck when it lands or lifts, and the engine
 * sound (courierAudio.ts). With reduced motion the flames and dust stay calm
 * and the camera does not shake.
 *
 * The model comes in three levels of detail from the art study
 * (art/studies/sky-pad-courier-study); its chrome and gold reflect a small
 * environment of the city's night built once per renderer.
 */
import { Component, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useGLTF } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import {
  AdditiveBlending, BackSide, BufferAttribute, BufferGeometry, Color, ConeGeometry, DoubleSide, Float32BufferAttribute, Group, LOD, Mesh,
  MeshBasicMaterial, MeshStandardMaterial, Object3D, PerspectiveCamera, PMREMGenerator, PointLight, RepeatWrapping, Scene, ShaderMaterial,
  SphereGeometry, Vector3, type Material, type Texture, type WebGLRenderer, type WebGLRenderTarget,
} from "three";
import courierNear from "@/assets/society/courier/courier-lod0.glb";
import courierMid from "@/assets/society/courier/courier-lod1.glb";
import courierFar from "@/assets/society/courier/courier-lod2.glb";
import { planCity } from "./cityPlan";
import { cachedCanvasTexture } from "./canvasMaterials";
import { CourierEngineSound } from "./courierAudio";
import { aimDirection, aimFromForward, cursorTurn, FLIGHT_ACTIONS, flightInput, moveAim, PAD_PRESSES, steerTowards, type MouseAim, PRESS_ACTIONS, type FlightAction, type PadState } from "./courierControls";
import { engageAutopilot, FLIGHT, forwardOf, heightOverDeck, NO_INPUT, parkedState, stepFlight, type FlightState } from "./courierFlight";
import { courierSession, useCourier } from "./courierStore";
import { buildCourierWorld, rayDistance } from "./courierWorld";
import { CAMERA_FOV } from "./officeCamera";
import type { OfficeLayout } from "./officeLayout";
import { ownsKeyboard } from "./OfficePlayer";
import { player as playerBody, useOfficeStore } from "./officeStore";
import { COURIER, type SkyPad } from "./skyPad";
import { COURIER_GROUP } from "./stations";

/** Authored geometry the runtime drives (model units = authored metres): where the gear retracts to, the exhausts, the pod tails. */
const MODEL = {
  gearTravel: 1.9,
  exhausts: [[-5.9, -0.15, 13.8], [5.9, -0.15, 13.8]] as const,
  tails: [[-5.9, -0.15, 20.8], [5.9, -0.15, 20.8]] as const,
  shield: [9.2, 4, 21] as const,
} as const;

/** Chase camera: behind and above the ship (world metres), and where it looks. Cockpit: the pilot's eyes. */
const CHASE = { back: 22, up: 6, lookAhead: 24, stiffness: 5 } as const;
const COCKPIT = { up: 1.25, forward: -3.6 } as const;
const FLIGHT_FOV = { cruise: 60, boost: 72 } as const;

// ---------------------------------------------------------------------------
// Materials
// ---------------------------------------------------------------------------

/** The city's night as a small environment for the chrome: violet sky, a gold glow on one side, dark streets with lights. */
function cityEnvironment(gl: WebGLRenderer): WebGLRenderTarget {
  const scene = new Scene();
  const geometry = new SphereGeometry(50, 48, 24);
  const colours: number[] = [];
  const pos = geometry.getAttribute("position");
  // Brighter than the real night, so the chrome reads as silver at every angle: a steel-blue dome, a pale horizon.
  const top = new Color("#4f5d7c"), horizon = new Color("#c3c8d6"), below = new Color("#2b2840"), glow = new Color("#ffc27a"), c = new Color();
  for (let i = 0; i < pos.count; i += 1) {
    const y = pos.getY(i) / 50, x = pos.getX(i) / 50, z = pos.getZ(i) / 50;
    if (y > 0) c.copy(horizon).lerp(top, Math.min(1, y * 1.3)); else c.copy(horizon).lerp(below, Math.min(1, -y * 2.5));
    // The singularity's glow, low in the north.
    const toGlow = Math.max(0, -z * 0.95 - x * 0.3) * Math.exp(-Math.abs(y) * 4);
    c.lerp(glow, Math.min(0.8, toGlow ** 3));
    colours.push(c.r, c.g, c.b);
  }
  geometry.setAttribute("color", new Float32BufferAttribute(colours, 3));
  scene.add(new Mesh(geometry, new MeshBasicMaterial({ vertexColors: true, side: BackSide })));
  // A few bright panels for the city's lights to glint in the hull.
  const lamp = new MeshBasicMaterial({ color: "#ffe6c4" });
  for (let i = 0; i < 14; i += 1) {
    const a = (i / 14) * Math.PI * 2, panel = new Mesh(new SphereGeometry(1.6, 8, 6), lamp);
    panel.position.set(Math.cos(a) * 40, -6 - (i % 3) * 5, Math.sin(a) * 40);
    scene.add(panel);
  }
  const pmrem = new PMREMGenerator(gl);
  const target = pmrem.fromScene(scene, 0.02);
  pmrem.dispose();
  scene.traverse((o) => { if (o instanceof Mesh) { o.geometry.dispose(); (o.material as Material).dispose(); } });
  return target;
}

/** Hull panels: thin seams the chrome's bump map carries, so the surface reads as built and not cast. */
function panelTexture(): Texture | null {
  const tex = cachedCanvasTexture("courier:panels", 512, 512, (ctx, w, h) => {
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = "#9a9a9a";
    ctx.lineWidth = 2;
    let seed = 0x5eed;
    const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    for (let y = 0; y < h; y += 64) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
      for (let x = rand() * 90; x < w; x += 70 + rand() * 90) { ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x, y + 64); ctx.stroke(); }
    }
    // Rivet rows and a few hatches.
    ctx.fillStyle = "#8a8a8a";
    for (let y = 8; y < h; y += 64) for (let x = 6; x < w; x += 12) ctx.fillRect(x, y, 2, 2);
  });
  // The hull's UVs run across (u) and along (v) it: plates about a metre wide and a metre and a quarter long.
  if (tex) { tex.wrapS = tex.wrapT = RepeatWrapping; tex.repeat.set(1.5, 3); }
  return tex;
}

interface CourierMaterials {
  byName: Record<string, Material>;
  glow: MeshBasicMaterial;
  /** The white tail and mast lights: a short flash every second and a half. */
  strobe: MeshBasicMaterial;
  all: Material[];
}

function courierMaterials(env: Texture): CourierMaterials {
  const panels = panelTexture();
  const chrome = new MeshStandardMaterial({ color: "#dfe3ea", metalness: 1, roughness: 0.16, envMap: env, envMapIntensity: 1.1, bumpMap: panels, bumpScale: 0.12 });
  const gold = new MeshStandardMaterial({ color: "#d6a64e", metalness: 1, roughness: 0.24, envMap: env, envMapIntensity: 1.2 });
  const graphite = new MeshStandardMaterial({ color: "#16181e", metalness: 0.6, roughness: 0.42, envMap: env });
  const glass = new MeshStandardMaterial({ color: "#0b1526", metalness: 0.9, roughness: 0.04, envMap: env, envMapIntensity: 1.6 });
  const glow = new MeshBasicMaterial({ color: "#6fd8ff", toneMapped: false });
  const strip = new MeshBasicMaterial({ color: "#8be9ff", toneMapped: false });
  const belly = new MeshStandardMaterial({ color: "#2b2e35", metalness: 0.85, roughness: 0.3, envMap: env, envMapIntensity: 0.9, bumpMap: panels, bumpScale: 0.1 });
  const vent = new MeshStandardMaterial({ color: "#0b0c10", metalness: 0.5, roughness: 0.6 });
  const navRed = new MeshBasicMaterial({ color: "#ff2a2a", toneMapped: false });
  const navGreen = new MeshBasicMaterial({ color: "#2aff6a", toneMapped: false });
  const navWhite = new MeshBasicMaterial({ color: "#ffffff", toneMapped: false });
  return {
    byName: {
      Chrome: chrome, Gold: gold, Graphite: graphite, CanopyGlass: glass, EngineGlow: glow, LightStrip: strip,
      Belly: belly, Vent: vent, NavRed: navRed, NavGreen: navGreen, NavWhite: navWhite,
    },
    glow,
    strobe: navWhite,
    all: [chrome, gold, graphite, glass, glow, strip, belly, vent, navRed, navGreen, navWhite],
  };
}

const GEAR_NAME = /^Gear_(Nose|Left|Right)\.?\d*$/;

/** A level of detail, cloned, re-dressed in the shared materials; returns its gear nodes with their rest heights. */
function dress(source: Object3D, materials: CourierMaterials): { root: Object3D; gear: { node: Object3D; y: number }[] } {
  const root = source.clone(true);
  const gear: { node: Object3D; y: number }[] = [];
  root.traverse((o) => {
    if (GEAR_NAME.test(o.name)) gear.push({ node: o, y: o.position.y });
    if (o instanceof Mesh) {
      const name = (o.material as Material).name.replace(/\.\d+$/, "");
      o.material = materials.byName[name] ?? materials.byName.Chrome;
      o.castShadow = true;
      o.receiveShadow = true;
    }
  });
  return { root, gear };
}

// ---------------------------------------------------------------------------
// Effects
// ---------------------------------------------------------------------------

const FLAME_VERTEX = /* glsl */ `
  varying vec2 vUv;
  void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
`;
const FLAME_FRAGMENT = /* glsl */ `
  uniform float uTime, uPower;
  varying vec2 vUv;
  void main() {
    // The cone's base sits at the nozzle, its point trails behind; uv.y is 0 at the base and 1 at the point.
    float along = 1.0 - vUv.y;
    float flicker = 0.85 + 0.15 * sin(uTime * 43.0 + vUv.x * 30.0) * sin(uTime * 17.0);
    vec3 hot = vec3(0.85, 0.97, 1.0) * 3.0, cool = vec3(0.25, 0.55, 1.0) * 1.4;
    vec3 col = mix(cool, hot, pow(along, 2.0)) * pow(along, 1.4) * uPower * flicker;
    gl_FragColor = vec4(col, 1.0);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`;

const SHIELD_VERTEX = /* glsl */ `
  varying vec3 vNormalW; varying vec3 vWorld; varying vec3 vLocal;
  void main() {
    vLocal = position;
    vec4 w = modelMatrix * vec4(position, 1.0); vWorld = w.xyz;
    vNormalW = normalize(mat3(modelMatrix) * normal);
    gl_Position = projectionMatrix * viewMatrix * w;
  }
`;
const SHIELD_FRAGMENT = /* glsl */ `
  uniform float uTime, uStrength;
  varying vec3 vNormalW; varying vec3 vWorld; varying vec3 vLocal;
  void main() {
    vec3 V = normalize(cameraPosition - vWorld);
    float fres = pow(1.0 - abs(dot(normalize(vNormalW), V)), 2.6);
    float bands = 0.6 + 0.4 * sin(vLocal.z * 2.4 - uTime * 6.0);
    vec3 col = vec3(0.35, 0.85, 1.0) * fres * bands * uStrength * 2.2;
    gl_FragColor = vec4(col, 1.0);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`;

const TRAIL_POINTS = 26;

/** A contrail behind one pod tail: a camera-facing ribbon through the tail's recent positions. */
class Trail {
  readonly geometry = new BufferGeometry();
  /** A ring of pooled points, newest at `head`; `count` of them are in use. */
  private readonly points = Array.from({ length: TRAIL_POINTS }, () => new Vector3());
  private readonly ages = new Float32Array(TRAIL_POINTS);
  private head = 0;
  private count = 0;
  private readonly pos = new Float32Array(TRAIL_POINTS * 2 * 3);
  private readonly fade = new Float32Array(TRAIL_POINTS * 2);
  constructor() {
    this.geometry.setAttribute("position", new BufferAttribute(this.pos, 3));
    this.geometry.setAttribute("aFade", new BufferAttribute(this.fade, 1));
    const index: number[] = [];
    for (let i = 0; i < TRAIL_POINTS - 1; i += 1) { const a = i * 2; index.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
    this.geometry.setIndex(index);
  }
  private at(i: number): Vector3 { return this.points[(this.head - i + TRAIL_POINTS) % TRAIL_POINTS]; }
  update(tip: Vector3, strength: number, dt: number, camera: Vector3, v: { side: Vector3; dir: Vector3; cam: Vector3 }) {
    for (let i = 0; i < TRAIL_POINTS; i += 1) this.ages[i] += dt;
    if (this.count === 0 || this.at(0).distanceTo(tip) > 1.4) {
      this.head = (this.head + 1) % TRAIL_POINTS;
      this.points[this.head].copy(tip);
      this.ages[this.head] = 0;
      this.count = Math.min(TRAIL_POINTS, this.count + 1);
    } else {
      this.at(0).copy(tip);
    }
    for (let i = 0; i < TRAIL_POINTS; i += 1) {
      const used = i < this.count;
      const p = used ? this.at(i) : this.at(0);
      const q = i + 1 < this.count ? this.at(i + 1) : p;
      v.dir.subVectors(p, q);
      if (v.dir.lengthSq() < 1e-6) v.dir.set(0, 0, 1);
      v.cam.subVectors(camera, p).normalize();
      v.side.crossVectors(v.dir.normalize(), v.cam).normalize().multiplyScalar(0.12 + i * 0.006);
      const o = i * 6;
      this.pos[o] = p.x + v.side.x; this.pos[o + 1] = p.y + v.side.y; this.pos[o + 2] = p.z + v.side.z;
      this.pos[o + 3] = p.x - v.side.x; this.pos[o + 4] = p.y - v.side.y; this.pos[o + 5] = p.z - v.side.z;
      // Fading with age and along the trail, and gone where it would pass right by the camera.
      const near = Math.min(1, Math.max(0, (camera.distanceTo(p) - 8) / 20));
      const age = this.ages[(this.head - i + TRAIL_POINTS) % TRAIL_POINTS];
      const alpha = used ? strength * Math.max(0, 1 - age / 1.2) * (1 - i / TRAIL_POINTS) * near : 0;
      this.fade[i * 2] = alpha; this.fade[i * 2 + 1] = alpha;
    }
    (this.geometry.getAttribute("position") as BufferAttribute).needsUpdate = true;
    (this.geometry.getAttribute("aFade") as BufferAttribute).needsUpdate = true;
  }
  clear() { this.count = 0; this.fade.fill(0); (this.geometry.getAttribute("aFade") as BufferAttribute).needsUpdate = true; }
}

const TRAIL_MATERIAL_SOURCE = {
  vertexShader: /* glsl */ `attribute float aFade; varying float vFade; void main() { vFade = aFade; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: /* glsl */ `varying float vFade; void main() { gl_FragColor = vec4(vec3(0.75, 0.85, 1.0) * vFade * 0.4, 1.0); }`,
};

const DUST_COUNT = 220;

// ---------------------------------------------------------------------------
// The component
// ---------------------------------------------------------------------------

export function SkyCourier({ layout, reduced, awake }: { layout: OfficeLayout; reduced: boolean; awake: boolean }) {
  // A model that fails to load leaves the pad empty instead of taking the floor down with it.
  return (
    <CourierBoundary>
      <Suspense fallback={null}>
        {layout.skyPad && <Courier layout={layout} pad={layout.skyPad} reduced={reduced} awake={awake} />}
      </Suspense>
    </CourierBoundary>
  );
}

class CourierBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: unknown) { console.warn("the courier could not be shown", error); }
  render() { return this.state.failed ? null : this.props.children; }
}

function Courier({ layout, pad, reduced, awake }: { layout: OfficeLayout; pad: SkyPad; reduced: boolean; awake: boolean }) {
  const gl = useThree((s) => s.gl);
  const camera = useThree((s) => s.camera) as PerspectiveCamera;
  const gltfs = useGLTF([courierNear, courierMid, courierFar]);
  // The environment is a render target of its own: built in an effect, so its disposal pairs with its creation.
  const [env, setEnv] = useState<WebGLRenderTarget | null>(null);
  useEffect(() => {
    const target = cityEnvironment(gl);
    setEnv(target);
    return () => target.dispose();
  }, [gl]);
  const materials = useMemo(() => (env ? courierMaterials(env.texture) : null), [env]);
  useEffect(() => () => { for (const m of materials?.all ?? []) m.dispose(); }, [materials]);
  const levels = useMemo(() => {
    if (!materials) return null;
    const dressed = gltfs.map((g) => dress(g.scene, materials));
    const l = new LOD();
    l.addLevel(dressed[0].root, 0);
    l.addLevel(dressed[1].root, 70);
    l.addLevel(dressed[2].root, 170);
    return { lod: l, gear: dressed.flatMap((lvl) => lvl.gear) };
  }, [gltfs, materials]);

  // Keyed on the pad's numbers, not its object: every rebuilt floor plan (a new agent, a team change) passes a new
  // one, and that must neither rebuild the city's colliders nor end a flight.
  const padRef = useRef(pad);
  padRef.current = pad;
  const { minX, maxX, minZ, maxZ } = layout.bounds;
  const hx = pad.ship.x, hz = pad.ship.z, hh = pad.ship.heading, padR = pad.pad.r;
  const home = useMemo(() => ({ x: hx, z: hz, heading: hh }), [hx, hz, hh]);
  const world = useMemo(() => {
    const bounds = { minX, maxX, minZ, maxZ };
    return buildCourierWorld(planCity(bounds), bounds, padRef.current);
  }, [minX, maxX, minZ, maxZ, hx, hz, padR]);
  const state = useRef<FlightState>(parkedState(home));
  const ship = useRef<Group>(null);

  // Effects.
  const flameGeometry = useMemo(() => new ConeGeometry(0.75, 1, 18, 1, true).rotateX(Math.PI / 2).translate(0, 0, 0.5), []);
  const flameMaterial = useMemo(() => new ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uPower: { value: 0 } }, vertexShader: FLAME_VERTEX, fragmentShader: FLAME_FRAGMENT,
    transparent: true, depthWrite: false, blending: AdditiveBlending, side: DoubleSide,
  }), []);
  const shieldGeometry = useMemo(() => new SphereGeometry(1, 40, 20), []);
  const shieldMaterial = useMemo(() => new ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uStrength: { value: 0 } }, vertexShader: SHIELD_VERTEX, fragmentShader: SHIELD_FRAGMENT,
    transparent: true, depthWrite: false, blending: AdditiveBlending,
  }), []);
  const trails = useMemo(() => [new Trail(), new Trail()], []);
  const trailMaterial = useMemo(() => new ShaderMaterial({ ...TRAIL_MATERIAL_SOURCE, transparent: true, depthWrite: false, blending: AdditiveBlending, side: DoubleSide }), []);
  const dust = useMemo(() => {
    const geometry = new BufferGeometry();
    geometry.setAttribute("position", new BufferAttribute(new Float32Array(DUST_COUNT * 3), 3));
    const material = new ShaderMaterial({
      uniforms: { uSize: { value: 220 } },
      vertexShader: /* glsl */ `attribute float aLife; uniform float uSize; varying float vLife; void main() { vLife = aLife; vec4 mv = modelViewMatrix * vec4(position, 1.0); gl_PointSize = uSize * (0.4 + aLife) / -mv.z; gl_Position = projectionMatrix * mv; }`,
      fragmentShader: /* glsl */ `varying float vLife; void main() { vec2 q = gl_PointCoord * 2.0 - 1.0; float a = exp(-dot(q, q) * 3.0) * vLife * 0.35; gl_FragColor = vec4(vec3(0.62, 0.6, 0.66) * a, 1.0); }`,
      transparent: true, depthWrite: false, blending: AdditiveBlending,
    });
    geometry.setAttribute("aLife", new BufferAttribute(new Float32Array(DUST_COUNT), 1));
    return { geometry, material, velocity: new Float32Array(DUST_COUNT * 3), life: new Float32Array(DUST_COUNT), next: 0, alive: 0 };
  }, []);
  useEffect(() => () => {
    flameGeometry.dispose(); flameMaterial.dispose(); shieldGeometry.dispose(); shieldMaterial.dispose(); trailMaterial.dispose();
    for (const t of trails) t.geometry.dispose();
    dust.geometry.dispose(); dust.material.dispose();
  }, [flameGeometry, flameMaterial, shieldGeometry, shieldMaterial, trails, trailMaterial, dust]);
  const flames = useRef<(Mesh | null)[]>([]);
  const shield = useRef<Mesh>(null);
  const light = useRef<PointLight>(null);

  // Flight session: held keys, gamepad presses, the sound, the camera's own smoothing.
  const flying = useCourier((s) => s.flying);
  // The keys and the sound belong to a flight on screen: another section or a hidden window gets its keys back.
  const live = flying && awake;
  const held = useRef(new Set<string>());
  /** Where the pilot aims while the mouse is captured; the ship turns towards it by itself. */
  const aim = useRef<MouseAim>({ yaw: 0, pitch: 0 });
  const aimDir = useMemo(() => new Vector3(), []);
  /** The cursor's place in the view (-1..1, +y up) while cursor steering is on and it is over the view. */
  const cursor = useRef<{ x: number; y: number } | null>(null);
  const padPressed = useRef(new Set<number>());
  const sound = useRef<CourierEngineSound | null>(null);
  const camPos = useRef(new Vector3());
  const camVel = useRef(new Vector3());
  const camPrev = useRef(new Vector3());
  const telemetryClock = useRef(0);
  const lastImpact = useRef(0);
  const landRequest = useCourier((s) => s.landRequest);
  const exitRequest = useCourier((s) => s.exitRequest);

  // The model is on the pad: from now on the person can board.
  useEffect(() => {
    if (!levels) return;
    useCourier.getState().setReady(true);
    return () => useCourier.getState().setReady(false);
  }, [levels]);

  /** The office camera's lens again, after the flight's wider one. */
  const restoreCamera = () => {
    camera.fov = CAMERA_FOV; camera.near = 0.2; camera.updateProjectionMatrix();
    for (const t of trails) t.clear();
  };
  const leaveShip = () => {
    // Step out beside the hatch, facing the ship; the office camera takes over again.
    const { board } = padRef.current;
    playerBody.x = board.x; playerBody.z = board.z; playerBody.heading = board.facing;
    playerBody.path = []; playerBody.moving = false;
    restoreCamera();
    useCourier.getState().disembark();
    useOfficeStore.getState().setFollow(true);
  };
  const leaveRef = useRef(leaveShip);
  leaveRef.current = leaveShip;

  useEffect(() => {
    if (landRequest > 0) engageAutopilot(state.current);
  }, [landRequest]);
  useEffect(() => {
    if (exitRequest > 0 && state.current.landed && courierSession.flying) leaveRef.current();
  }, [exitRequest]);

  useEffect(() => {
    if (!live) return;
    camPos.current.copy(camera.position);
    camPrev.current.copy(camera.position);
    let engine: CourierEngineSound | null = null;
    try {
      engine = new CourierEngineSound();
      engine.resume();
    } catch (error) {
      // No Web Audio (an old engine, a locked-down WebView): the flight goes on in silence.
      console.warn("courier sound unavailable", error);
    }
    sound.current = engine;
    const press = (action: FlightAction) => {
      const store = useCourier.getState();
      const s = state.current;
      if (action === "assist") store.setPrefs({ assist: store.assist === "arcade" ? "simulation" : "arcade" });
      else if (action === "camera") store.setPrefs({ view: store.view === "chase" ? "cockpit" : "chase" });
      else if (action === "land") engageAutopilot(s);
      else if (action === "help") store.set({ helpOpen: !store.helpOpen });
      else if (action === "exit" && s.landed) leaveRef.current();
    };
    const down = (event: KeyboardEvent) => {
      const store = useCourier.getState();
      // Escape opens and closes the flight settings, wherever focus sits in them.
      if (event.key === "Escape") {
        store.set({ settingsOpen: !store.settingsOpen });
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      if (ownsKeyboard(event.target) || store.settingsOpen) return;
      // A modifier is a binding of its own (Ctrl sinks by default); held with another key it is a shortcut.
      const isModifier = /^(Control|Alt|Meta|OS)/.test(event.code);
      if (!isModifier && (event.ctrlKey || event.metaKey || event.altKey)) return;
      const action = FLIGHT_ACTIONS.find((a) => store.bindings[a].includes(event.code));
      // E is "use" everywhere in the office: standing on the pad, it also steps out.
      if (event.code === "KeyE" && state.current.landed && !event.repeat) { leaveRef.current(); event.preventDefault(); event.stopPropagation(); return; }
      if (!action) return;
      event.preventDefault();
      event.stopPropagation();
      if (PRESS_ACTIONS.has(action)) { if (!event.repeat) press(action); return; }
      held.current.add(event.code);
    };
    const up = (event: KeyboardEvent) => { held.current.delete(event.code); };
    const blur = () => held.current.clear();
    // A click into the view captures the mouse for steering; Escape (the browser's own) lets it go again.
    const canvas = gl.domElement;
    // Some hosts refuse to capture the mouse (an unfocused window, an embedded view): then the cursor steers.
    const refused = (error: unknown) => {
      console.warn("mouse capture refused, steering with the cursor", error);
      if (!useCourier.getState().cursorAim) Object.assign(aim.current, aimFromForward(forwardOf(state.current.q)));
      useCourier.getState().set({ cursorAim: true });
    };
    const capture = () => {
      if (document.pointerLockElement === canvas || useCourier.getState().settingsOpen) return;
      if (!canvas.requestPointerLock) { refused(new Error("pointer lock unsupported")); return; }
      try {
        const pending = canvas.requestPointerLock() as unknown as Promise<void> | undefined;
        pending?.catch?.(refused);
      } catch (error) {
        refused(error);
      }
    };
    const point = (event: PointerEvent) => {
      const r = canvas.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return;
      cursor.current = { x: ((event.clientX - r.left) / r.width) * 2 - 1, y: 1 - ((event.clientY - r.top) / r.height) * 2 };
    };
    const leave = () => { cursor.current = null; };
    const move = (event: MouseEvent) => {
      if (document.pointerLockElement !== canvas) return;
      const s = state.current;
      // Moving the mouse during the landing assist takes the ship back, aiming from where it points now.
      if (s.autopilot) { s.autopilot = null; Object.assign(aim.current, aimFromForward(forwardOf(s.q))); }
      moveAim(aim.current, event.movementX, event.movementY, useCourier.getState().invertPitch);
    };
    const lockChange = () => {
      const locked = document.pointerLockElement === canvas;
      // The aim starts where the nose points.
      if (locked) Object.assign(aim.current, aimFromForward(forwardOf(state.current.q)));
      useCourier.getState().set(locked ? { mouseLocked: true, cursorAim: false } : { mouseLocked: false });
    };
    canvas.addEventListener("click", capture);
    canvas.addEventListener("pointermove", point);
    canvas.addEventListener("pointerleave", leave);
    window.addEventListener("mousemove", move);
    document.addEventListener("pointerlockchange", lockChange);
    window.addEventListener("keydown", down, true);
    window.addEventListener("keyup", up, true);
    window.addEventListener("blur", blur);
    pressHandler.current = press;
    return () => {
      canvas.removeEventListener("click", capture);
      canvas.removeEventListener("pointermove", point);
      canvas.removeEventListener("pointerleave", leave);
      window.removeEventListener("mousemove", move);
      document.removeEventListener("pointerlockchange", lockChange);
      if (document.pointerLockElement === canvas) document.exitPointerLock();
      cursor.current = null;
      useCourier.getState().set({ mouseLocked: false, cursorAim: false });
      window.removeEventListener("keydown", down, true);
      window.removeEventListener("keyup", up, true);
      window.removeEventListener("blur", blur);
      held.current.clear();
      engine?.close();
      sound.current = null;
      pressHandler.current = null;
    };
  }, [live, camera, gl]);
  const pressHandler = useRef<((action: FlightAction) => void) | null>(null);

  // Leaving the floor or the map mid-flight: the ship is parked again, the person stands beside it, the lens is
  // the office's again.
  useEffect(() => () => {
    if (courierSession.flying) leaveRef.current();
  }, []);

  useEffect(() => {
    if (!import.meta.env.DEV || typeof window === "undefined") return;
    // Dev-only: the live flight state, for runtime checks of the effects and the camera.
    Object.assign(window, { __courier: { state: () => state.current, store: useCourier } });
  }, []);

  const _v = useMemo(() => ({ a: new Vector3(), b: new Vector3(), c: new Vector3(), f: new Vector3(), u: new Vector3(), side: new Vector3(), dir: new Vector3(), cam: new Vector3() }), []);

  useFrame(({ clock }, rawDt) => {
    const g = ship.current;
    if (!g || !awake) return;
    const dt = Math.min(rawDt, 0.1);
    const s = state.current;
    const store = useCourier.getState();
    if (flying) {
      // Gamepad: the first connected pad, its press buttons on their rising edge.
      let gamepad: PadState | null = null;
      try {
        const pads = typeof navigator !== "undefined" && navigator.getGamepads ? navigator.getGamepads() : [];
        for (const p of pads) if (p && p.connected) { gamepad = p; break; }
      } catch (error) {
        // A permissions policy may forbid gamepads; the keyboard still flies. Said once, not every frame.
        if (!gamepadWarned.current) { console.warn("gamepads unavailable", error); gamepadWarned.current = true; }
      }
      if (gamepad) {
        for (const [button, action] of PAD_PRESSES) {
          const isDown = gamepad.buttons[button]?.pressed ?? false;
          if (isDown && !padPressed.current.has(button)) pressHandler.current?.(action);
          if (isDown) padPressed.current.add(button); else padPressed.current.delete(button);
        }
      }
      const input = store.settingsOpen ? { ...NO_INPUT } : flightInput(held.current, store.bindings, gamepad, store.invertPitch);
      if (store.mouseLocked || store.cursorAim) {
        // Mouse aim: the turn and pitch keys move the aim too, and the ship flies to wherever it points.
        const a = aim.current;
        if (s.landed || s.autopilot) Object.assign(a, aimFromForward(forwardOf(s.q)));
        else {
          if (!store.mouseLocked && cursor.current && !store.settingsOpen) cursorTurn(a, cursor.current.x, cursor.current.y, dt);
          moveAim(a, input.yaw * 600 * dt, -input.pitch * 450 * dt, false);
          input.yaw = 0; input.pitch = 0;
          steerTowards(input, s.q, aimDirection(a, aimDir));
        }
      }
      stepFlight(s, input, dt, store.assist, world, home);
      if (s.impact > lastImpact.current + 6 && sound.current) sound.current.impact(s.impact);
      lastImpact.current = s.impact;
      flyCamera(dt, input.boost && s.charge > 0.02);
      sound.current?.update({
        throttle: s.throttle, boost: input.boost && s.charge > 0.02,
        ship: s.p, shipVelocity: s.v, listener: camera.position, listenerVelocity: camVel.current,
        forward: _v.f.set(0, 0, -1).applyQuaternion(camera.quaternion), up: _v.u.set(0, 1, 0).applyQuaternion(camera.quaternion),
        inside: store.view === "cockpit", volume: store.volume,
      });
      telemetryClock.current += dt;
      if (telemetryClock.current > 0.12) {
        telemetryClock.current = 0;
        const overDeck = heightOverDeck(s, home);
        store.set({
          telemetry: {
            speed: s.v.length(), throttle: s.throttle, charge: s.charge,
            altitude: Number.isFinite(overDeck) ? Math.max(0, overDeck) : s.p.y - world.ground,
            overPad: Number.isFinite(overDeck), landed: s.landed, autopilot: s.autopilot,
            canLand: !s.landed && !s.autopilot,
          },
        });
      }
    } else if (!s.landed || s.p.distanceToSquared(_v.a.set(home.x, COURIER.standHeight, home.z)) > 1e-4) {
      // Not flown (stepped out, or left mid-air by a floor change): back on the pad.
      state.current = parkedState(home);
    }

    // Place the ship and dress it for its state.
    const st = state.current;
    g.position.copy(st.p);
    g.quaternion.copy(st.q);
    if (levels) for (const { node, y } of levels.gear) node.position.y = y + (1 - st.gear) * MODEL.gearTravel;
    const power = st.landed ? 0.12 : 0.25 + st.throttle * 0.75;
    materials?.glow.color.setRGB(0.25 + power * 0.6, 0.55 + power * 0.45, 1).multiplyScalar(0.6 + power * 1.8);
    materials?.strobe.color.setScalar(reduced || (clock.elapsedTime % 1.5) < 0.09 ? 1.6 : 0.12);
    flameMaterial.uniforms.uTime.value = reduced ? 0 : clock.elapsedTime;
    flameMaterial.uniforms.uPower.value = st.landed ? 0 : 0.35 + st.throttle * 0.9;
    for (const f of flames.current) if (f) f.scale.set(1, 1, st.landed ? 0.01 : 2 + st.throttle * 7);
    if (light.current) light.current.intensity = st.landed ? 0 : 10 + st.throttle * 50;
    shieldMaterial.uniforms.uTime.value = clock.elapsedTime;
    shieldMaterial.uniforms.uStrength.value = st.shield;
    if (shield.current) shield.current.visible = st.shield > 0.01;
    if (flying) updateTrails(dt);
    if (flying || dust.alive > 0) updateDust(dt);
  });
  const gamepadWarned = useRef(false);

  function flyCamera(dt: number, boosting: boolean) {
    const s = state.current, store = useCourier.getState();
    const f = forwardOf(s.q, _v.f), u = _v.u.set(0, 1, 0).applyQuaternion(s.q);
    if (store.view === "cockpit") {
      camera.position.copy(s.p).addScaledVector(u, COCKPIT.up).addScaledVector(f, -COCKPIT.forward);
      camera.quaternion.copy(s.q);
      // The chase camera starts from here when the pilot switches back.
      camPos.current.copy(camera.position);
    } else {
      // Behind the tail and above it, looking past the nose; with mouse aim, looking where the pilot aims.
      const look = (store.mouseLocked || store.cursorAim) && !s.landed && !s.autopilot ? aimDirection(aim.current, aimDir) : f;
      const want = _v.a.copy(s.p).addScaledVector(look, -CHASE.back).add(_v.b.set(0, CHASE.up, 0));
      // Never through a tower: pull in to just short of whatever stands between the ship and the camera.
      const from = _v.b.copy(s.p).add(_v.c.set(0, 2, 0));
      const dir = _v.c.copy(want).sub(from);
      const reach = dir.length();
      dir.normalize();
      const free = rayDistance(world, from, dir, reach);
      if (free < reach) want.copy(from).addScaledVector(dir, Math.max(2, free - 1.5));
      camPos.current.lerp(want, 1 - Math.exp(-CHASE.stiffness * dt));
      camera.position.copy(camPos.current);
      camera.up.set(0, 1, 0);
      camera.lookAt(_v.b.copy(s.p).addScaledVector(look, CHASE.lookAhead).addScaledVector(u, 1.5));
    }
    placeMarkers();
    // The listener's own speed, for the Doppler shift: measured before any shake.
    camVel.current.copy(camera.position).sub(camPrev.current).divideScalar(Math.max(dt, 1e-3));
    camPrev.current.copy(camera.position);
    if (store.view === "chase" && !reduced && s.impact > 4) {
      camera.position.add(_v.b.set(Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5).multiplyScalar(s.impact * 0.02));
    }
    const fov = boosting ? FLIGHT_FOV.boost : FLIGHT_FOV.cruise;
    camera.fov += (fov - camera.fov) * Math.min(1, dt * 3);
    camera.near = 0.3;
    camera.far = 1400;
    camera.updateProjectionMatrix();
  }

  /** The aim reticle and the nose marker on the HUD: where the pilot aims, and where the nose points now. */
  function placeMarkers() {
    const s = state.current, store = useCourier.getState();
    const show = (store.mouseLocked || store.cursorAim) && !s.landed && !s.autopilot;
    camera.updateMatrixWorld();
    for (const [id, dir] of [["courier-aim", show ? aimDirection(aim.current, aimDir) : null], ["courier-nose", show ? forwardOf(s.q, _v.c) : null]] as const) {
      const el = document.getElementById(id);
      if (!el) continue;
      if (!dir) { el.style.opacity = "0"; continue; }
      const ndc = _v.a.copy(s.p).addScaledVector(dir, 220).project(camera);
      el.style.opacity = ndc.z < 1 ? "1" : "0";
      el.style.left = `${((ndc.x + 1) / 2) * 100}%`;
      el.style.top = `${((1 - ndc.y) / 2) * 100}%`;
    }
  }

  function updateTrails(dt: number) {
    const s = state.current;
    const strength = Math.max(0, Math.min(1, (s.v.length() - FLIGHT.cruise * 0.6) / (FLIGHT.cruise * 0.6)));
    for (let i = 0; i < MODEL.tails.length; i += 1) {
      const tail = MODEL.tails[i];
      const tip = _v.a.set(tail[0], tail[1], tail[2]).multiplyScalar(COURIER.scale).applyQuaternion(s.q).add(s.p);
      trails[i].update(tip, strength, dt, camera.position, _v);
    }
  }

  function updateDust(dt: number) {
    const s = state.current;
    const pos = dust.geometry.getAttribute("position") as BufferAttribute;
    const life = dust.geometry.getAttribute("aLife") as BufferAttribute;
    const above = heightOverDeck(s, home);
    // Thrust washing over the deck while the ship is low and not standing still on it.
    const wash = flying && !s.landed && above < 16 ? (1 - above / 16) : 0;
    const spawn = reduced ? 0 : Math.floor(wash * 90 * dt * 10);
    for (let k = 0; k < spawn; k += 1) {
      const i = dust.next; dust.next = (dust.next + 1) % DUST_COUNT;
      const a = Math.random() * Math.PI * 2, r = 2 + Math.random() * 3;
      pos.setXYZ(i, s.p.x + Math.cos(a) * r, 0.2, s.p.z + Math.sin(a) * r);
      const speed = 6 + Math.random() * 8;
      dust.velocity[i * 3] = Math.cos(a) * speed; dust.velocity[i * 3 + 1] = 0.6 + Math.random() * 1.4; dust.velocity[i * 3 + 2] = Math.sin(a) * speed;
      dust.life[i] = 1;
    }
    let alive = 0;
    for (let i = 0; i < DUST_COUNT; i += 1) {
      if (dust.life[i] <= 0) { life.setX(i, 0); continue; }
      alive += 1;
      dust.life[i] = Math.max(0, dust.life[i] - dt * 0.8);
      pos.setXYZ(i, pos.getX(i) + dust.velocity[i * 3] * dt, pos.getY(i) + dust.velocity[i * 3 + 1] * dt, pos.getZ(i) + dust.velocity[i * 3 + 2] * dt);
      dust.velocity[i * 3] *= 1 - dt * 0.9; dust.velocity[i * 3 + 2] *= 1 - dt * 0.9;
      life.setX(i, dust.life[i]);
    }
    dust.alive = alive;
    pos.needsUpdate = true;
    life.needsUpdate = true;
  }

  if (!levels) return null;
  return (
    <>
      <group ref={ship} name={COURIER_GROUP} visible>
        <group scale={COURIER.scale}>
          <primitive object={levels.lod} />
          {MODEL.exhausts.map((p, i) => (
            <mesh key={i} ref={(m) => { flames.current[i] = m; }} geometry={flameGeometry} material={flameMaterial} position={p} renderOrder={6} frustumCulled={false} />
          ))}
          <pointLight ref={light} position={[0, 0, 14]} color="#7fd8ff" distance={40} decay={2} intensity={0} />
          <mesh ref={shield} geometry={shieldGeometry} material={shieldMaterial} scale={MODEL.shield as unknown as [number, number, number]} visible={false} renderOrder={7} />
        </group>
      </group>
      {trails.map((t, i) => <mesh key={i} geometry={t.geometry} material={trailMaterial} frustumCulled={false} renderOrder={5} />)}
      <points geometry={dust.geometry} material={dust.material} frustumCulled={false} renderOrder={5} />
    </>
  );
}
