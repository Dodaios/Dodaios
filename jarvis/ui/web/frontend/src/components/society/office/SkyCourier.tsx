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
import { Suspense, useEffect, useMemo, useRef } from "react";
import { useGLTF } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import {
  AdditiveBlending, BackSide, BufferAttribute, BufferGeometry, Color, ConeGeometry, DoubleSide, Float32BufferAttribute, Group, LOD, Mesh,
  MeshBasicMaterial, MeshStandardMaterial, Object3D, PerspectiveCamera, PMREMGenerator, Points, RepeatWrapping, Scene, ShaderMaterial,
  SphereGeometry, Vector3, type Material, type Texture, type WebGLRenderer,
} from "three";
import courierNear from "@/assets/society/courier/courier-lod0.glb";
import courierMid from "@/assets/society/courier/courier-lod1.glb";
import courierFar from "@/assets/society/courier/courier-lod2.glb";
import { planCity } from "./cityPlan";
import { cachedCanvasTexture } from "./canvasMaterials";
import { CourierEngineSound } from "./courierAudio";
import { flightInput, PAD_PRESSES, PRESS_ACTIONS, type FlightAction, type PadState } from "./courierControls";
import { engageAutopilot, FLIGHT, forwardOf, heightOverDeck, parkedState, stepFlight, type FlightState } from "./courierFlight";
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
  exhausts: [[-6.6, -0.25, 12.6], [6.6, -0.25, 12.6]] as const,
  tails: [[-6.6, -0.25, 17.2], [6.6, -0.25, 17.2]] as const,
  shield: [8.6, 4.2, 19] as const,
} as const;

/** Chase camera: behind and above the ship (world metres), and where it looks. Cockpit: the pilot's eyes. */
const CHASE = { back: 22, up: 6, lookAhead: 24, stiffness: 5 } as const;
const COCKPIT = { up: 1.55, forward: -4.2 } as const;
const FLIGHT_FOV = { cruise: 60, boost: 72 } as const;

// ---------------------------------------------------------------------------
// Materials
// ---------------------------------------------------------------------------

/** The city's night as a small environment for the chrome: violet sky, a gold glow on one side, dark streets with lights. */
function cityEnvironment(gl: WebGLRenderer): Texture {
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
  return target.texture;
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
  if (tex) { tex.wrapS = tex.wrapT = RepeatWrapping; tex.repeat.set(2.5, 2.5); }
  return tex;
}

interface CourierMaterials {
  byName: Record<string, Material>;
  glow: MeshBasicMaterial;
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
  return {
    byName: { Chrome: chrome, Gold: gold, Graphite: graphite, CanopyGlass: glass, EngineGlow: glow, LightStrip: strip },
    glow,
    all: [chrome, gold, graphite, glass, glow, strip],
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
  private points: Vector3[] = [];
  private ages: number[] = [];
  private readonly pos = new Float32Array(TRAIL_POINTS * 2 * 3);
  private readonly fade = new Float32Array(TRAIL_POINTS * 2);
  constructor() {
    this.geometry.setAttribute("position", new BufferAttribute(this.pos, 3));
    this.geometry.setAttribute("aFade", new BufferAttribute(this.fade, 1));
    const index: number[] = [];
    for (let i = 0; i < TRAIL_POINTS - 1; i += 1) { const a = i * 2; index.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
    this.geometry.setIndex(index);
  }
  update(tip: Vector3, strength: number, dt: number, camera: Vector3) {
    for (let i = 0; i < this.ages.length; i += 1) this.ages[i] += dt;
    const last = this.points[0];
    if (!last || last.distanceTo(tip) > 1.4) { this.points.unshift(tip.clone()); this.ages.unshift(0); }
    else last.copy(tip);
    while (this.points.length > TRAIL_POINTS) { this.points.pop(); this.ages.pop(); }
    const side = new Vector3(), dir = new Vector3(), toCam = new Vector3();
    for (let i = 0; i < TRAIL_POINTS; i += 1) {
      const p = this.points[Math.min(i, this.points.length - 1)] ?? tip;
      const q = this.points[Math.min(i + 1, this.points.length - 1)] ?? p;
      dir.subVectors(p, q);
      if (dir.lengthSq() < 1e-6) dir.set(0, 0, 1);
      toCam.subVectors(camera, p).normalize();
      side.crossVectors(dir.normalize(), toCam).normalize().multiplyScalar(0.12 + i * 0.006);
      this.pos.set([p.x + side.x, p.y + side.y, p.z + side.z, p.x - side.x, p.y - side.y, p.z - side.z], i * 6);
      const age = this.ages[Math.min(i, this.ages.length - 1)] ?? 9;
      // Fading with age and along the trail, and gone where it would pass right by the camera.
      const near = Math.min(1, Math.max(0, (camera.distanceTo(p) - 8) / 20));
      const alpha = i < this.points.length ? strength * Math.max(0, 1 - age / 1.2) * (1 - i / TRAIL_POINTS) * near : 0;
      this.fade[i * 2] = alpha; this.fade[i * 2 + 1] = alpha;
    }
    (this.geometry.getAttribute("position") as BufferAttribute).needsUpdate = true;
    (this.geometry.getAttribute("aFade") as BufferAttribute).needsUpdate = true;
    this.geometry.computeBoundingSphere();
  }
  clear() { this.points = []; this.ages = []; this.fade.fill(0); (this.geometry.getAttribute("aFade") as BufferAttribute).needsUpdate = true; }
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
  return (
    <Suspense fallback={null}>
      {layout.skyPad && <Courier layout={layout} pad={layout.skyPad} reduced={reduced} awake={awake} />}
    </Suspense>
  );
}

function Courier({ layout, pad, reduced, awake }: { layout: OfficeLayout; pad: SkyPad; reduced: boolean; awake: boolean }) {
  const gl = useThree((s) => s.gl);
  const camera = useThree((s) => s.camera) as PerspectiveCamera;
  const gltfs = useGLTF([courierNear, courierMid, courierFar]);
  const env = useMemo(() => cityEnvironment(gl), [gl]);
  useEffect(() => () => env.dispose(), [env]);
  const materials = useMemo(() => courierMaterials(env), [env]);
  useEffect(() => () => { for (const m of materials.all) m.dispose(); }, [materials]);
  const { lod, gear } = useMemo(() => {
    const levels = gltfs.map((g) => dress(g.scene, materials));
    const l = new LOD();
    l.addLevel(levels[0].root, 0);
    l.addLevel(levels[1].root, 70);
    l.addLevel(levels[2].root, 170);
    return { lod: l, gear: levels.flatMap((lvl) => lvl.gear) };
  }, [gltfs, materials]);

  const { minX, maxX, minZ, maxZ } = layout.bounds;
  const world = useMemo(() => {
    const bounds = { minX, maxX, minZ, maxZ };
    return buildCourierWorld(planCity(bounds), bounds, pad);
  }, [minX, maxX, minZ, maxZ, pad]);
  const home = pad.ship;
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
    return { geometry, material, velocity: new Float32Array(DUST_COUNT * 3), life: new Float32Array(DUST_COUNT), next: 0 };
  }, []);
  useEffect(() => () => {
    flameGeometry.dispose(); flameMaterial.dispose(); shieldGeometry.dispose(); shieldMaterial.dispose(); trailMaterial.dispose();
    for (const t of trails) t.geometry.dispose();
    dust.geometry.dispose(); dust.material.dispose();
  }, [flameGeometry, flameMaterial, shieldGeometry, shieldMaterial, trails, trailMaterial, dust]);
  const flames = useRef<(Mesh | null)[]>([]);
  const shield = useRef<Mesh>(null);
  const light = useRef<import("three").PointLight>(null);
  const dustPoints = useRef<Points>(null);

  // Flight session: held keys, gamepad presses, the sound, the camera's own smoothing.
  const flying = useCourier((s) => s.flying);
  const held = useRef(new Set<string>());
  const padPressed = useRef(new Set<number>());
  const sound = useRef<CourierEngineSound | null>(null);
  const camPos = useRef(new Vector3());
  const camVel = useRef(new Vector3());
  const lastCam = useRef(new Vector3());
  const telemetryClock = useRef(0);
  const lastImpact = useRef(0);
  const landRequest = useCourier((s) => s.landRequest);

  const exitRequest = useCourier((s) => s.exitRequest);
  useEffect(() => {
    if (landRequest > 0) engageAutopilot(state.current);
  }, [landRequest]);
  useEffect(() => {
    if (exitRequest > 0 && state.current.landed && courierSession.flying) leaveShip();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exitRequest]);

  useEffect(() => {
    if (!flying) return;
    camPos.current.copy(camera.position);
    lastCam.current.copy(camera.position);
    try {
      sound.current = new CourierEngineSound();
      sound.current.resume();
    } catch (error) {
      // No Web Audio (an old engine, a locked-down WebView): the flight goes on in silence.
      console.warn("courier sound unavailable", error);
      sound.current = null;
    }
    const press = (action: FlightAction) => {
      const store = useCourier.getState();
      const s = state.current;
      if (action === "assist") store.setPrefs({ assist: store.assist === "arcade" ? "simulation" : "arcade" });
      else if (action === "camera") store.setPrefs({ view: store.view === "chase" ? "cockpit" : "chase" });
      else if (action === "land") engageAutopilot(s);
      else if (action === "help") store.set({ helpOpen: !store.helpOpen });
      else if (action === "exit" && s.landed) leaveShip();
    };
    const down = (event: KeyboardEvent) => {
      if (ownsKeyboard(event.target) || event.ctrlKey || event.metaKey || event.altKey) return;
      const store = useCourier.getState();
      if (event.key === "Escape") { store.set({ settingsOpen: !store.settingsOpen }); event.preventDefault(); return; }
      if (store.settingsOpen) return;
      const action = (Object.keys(store.bindings) as FlightAction[]).find((a) => store.bindings[a].includes(event.code));
      // E stands for "use" everywhere in the office: on the pad it leaves the ship too.
      if (event.code === "KeyE" && state.current.landed && !event.repeat) { leaveShip(); event.preventDefault(); event.stopPropagation(); return; }
      if (!action) return;
      event.preventDefault();
      event.stopPropagation();
      if (PRESS_ACTIONS.has(action)) { if (!event.repeat) press(action); return; }
      held.current.add(event.code);
    };
    const up = (event: KeyboardEvent) => { held.current.delete(event.code); };
    const blur = () => held.current.clear();
    window.addEventListener("keydown", down, true);
    window.addEventListener("keyup", up, true);
    window.addEventListener("blur", blur);
    pressHandler.current = press;
    return () => {
      window.removeEventListener("keydown", down, true);
      window.removeEventListener("keyup", up, true);
      window.removeEventListener("blur", blur);
      held.current.clear();
      sound.current?.close();
      sound.current = null;
      pressHandler.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flying]);
  const pressHandler = useRef<((action: FlightAction) => void) | null>(null);

  function leaveShip() {
    // Step out beside the hatch, facing the ship; the office camera takes over again.
    playerBody.x = pad.board.x; playerBody.z = pad.board.z; playerBody.heading = pad.board.facing;
    playerBody.path = []; playerBody.moving = false;
    camera.fov = CAMERA_FOV; camera.near = 0.2; camera.updateProjectionMatrix();
    for (const t of trails) t.clear();
    useCourier.getState().disembark();
    useOfficeStore.getState().setFollow(true);
  }

  // Leaving the floor or the map mid-flight: the ship is parked again and the person stands beside it.
  useEffect(() => () => {
    if (courierSession.flying) {
      state.current = parkedState(home);
      useCourier.getState().disembark();
    }
  }, [home]);

  useEffect(() => {
    if (!import.meta.env.DEV || typeof window === "undefined") return;
    // Dev-only: the live flight state, for runtime checks of the effects and the camera.
    Object.assign(window, { __courier: { state: () => state.current } });
  }, []);

  const _v = useMemo(() => ({ a: new Vector3(), b: new Vector3(), c: new Vector3(), f: new Vector3(), u: new Vector3() }), []);

  useFrame(({ clock }, rawDt) => {
    const g = ship.current;
    if (!g || !awake) return;
    const dt = Math.min(rawDt, 0.1);
    const s = state.current;
    const store = useCourier.getState();
    if (flying) {
      // Gamepad: the first connected pad, its press buttons on their rising edge.
      let pad: PadState | null = null;
      const pads = typeof navigator !== "undefined" && navigator.getGamepads ? navigator.getGamepads() : [];
      for (const p of pads) if (p && p.connected) { pad = p; break; }
      if (pad) {
        for (const [button, action] of PAD_PRESSES) {
          const isDown = pad.buttons[button]?.pressed ?? false;
          if (isDown && !padPressed.current.has(button)) pressHandler.current?.(action);
          if (isDown) padPressed.current.add(button); else padPressed.current.delete(button);
        }
      }
      const input = store.settingsOpen ? flightInput(new Set(), store.bindings, null, false)
        : flightInput(held.current, store.bindings, pad, store.invertPitch);
      stepFlight(s, input, dt, store.assist, world, home);
      if (s.impact > lastImpact.current + 6 && sound.current) sound.current.impact(s.impact, store.volume);
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
      // Not flown (left mid-air by a floor change): back on the pad.
      state.current = parkedState(home);
    }

    // Place the ship and dress it for its state.
    g.position.copy(state.current.p);
    g.quaternion.copy(state.current.q);
    const st = state.current;
    for (const { node, y } of gear) node.position.y = y + (1 - st.gear) * MODEL.gearTravel;
    const power = st.landed ? 0.12 : 0.25 + st.throttle * 0.75;
    materials.glow.color.setRGB(0.25 + power * 0.6, 0.55 + power * 0.45, 1).multiplyScalar(0.6 + power * 1.8);
    flameMaterial.uniforms.uTime.value = reduced ? 0 : clock.elapsedTime;
    flameMaterial.uniforms.uPower.value = st.landed ? 0 : 0.35 + st.throttle * 0.9;
    for (const f of flames.current) if (f) f.scale.set(1, 1, st.landed ? 0.01 : 2 + st.throttle * 7);
    if (light.current) light.current.intensity = st.landed ? 0 : 10 + st.throttle * 50;
    shieldMaterial.uniforms.uTime.value = clock.elapsedTime;
    shieldMaterial.uniforms.uStrength.value = st.shield;
    if (shield.current) shield.current.visible = st.shield > 0.01;
    updateTrails(dt);
    updateDust(dt);
  });

  function flyCamera(dt: number, boosting: boolean) {
    const s = state.current, store = useCourier.getState();
    const f = forwardOf(s.q, _v.f), u = _v.u.set(0, 1, 0).applyQuaternion(s.q);
    const before = _v.c.copy(camera.position);
    if (store.view === "cockpit") {
      camera.position.copy(s.p).addScaledVector(u, COCKPIT.up).addScaledVector(f, -COCKPIT.forward);
      camera.quaternion.copy(s.q);
    } else {
      // Behind the tail and above it, looking past the nose.
      const want = _v.a.copy(s.p).addScaledVector(f, -CHASE.back).add(_v.b.set(0, CHASE.up, 0));
      // Never through a tower: pull in to just short of whatever stands between the ship and the camera.
      const from = _v.b.copy(s.p).add(_v.c.set(0, 2, 0));
      const dir = _v.c.copy(want).sub(from);
      const reach = dir.length();
      dir.normalize();
      const free = rayDistance(world, from, dir, reach);
      if (free < reach) want.copy(from).addScaledVector(dir, Math.max(2, free - 1.5));
      camPos.current.lerp(want, 1 - Math.exp(-CHASE.stiffness * dt));
      camera.position.copy(camPos.current);
      if (!reduced && s.impact > 4) camera.position.add(_v.b.set(Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5).multiplyScalar(s.impact * 0.02));
      camera.up.set(0, 1, 0);
      camera.lookAt(_v.b.copy(s.p).addScaledVector(f, CHASE.lookAhead).addScaledVector(u, 1.5));
    }
    camVel.current.copy(camera.position).sub(before).divideScalar(Math.max(dt, 1e-3));
    const fov = boosting ? FLIGHT_FOV.boost : FLIGHT_FOV.cruise;
    camera.fov += (fov - camera.fov) * Math.min(1, dt * 3);
    camera.near = 0.3;
    camera.far = 1400;
    camera.updateProjectionMatrix();
  }

  function updateTrails(dt: number) {
    const s = state.current;
    const strength = flying ? Math.max(0, Math.min(1, (s.v.length() - FLIGHT.cruise * 0.6) / (FLIGHT.cruise * 0.6))) : 0;
    MODEL.tails.forEach((tail, i) => {
      const tip = _v.a.set(tail[0], tail[1], tail[2]).multiplyScalar(COURIER.scale).applyQuaternion(s.q).add(s.p);
      trails[i].update(tip, strength, dt, camera.position);
    });
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
      dust.velocity.set([Math.cos(a) * speed, 0.6 + Math.random() * 1.4, Math.sin(a) * speed], i * 3);
      dust.life[i] = 1;
    }
    for (let i = 0; i < DUST_COUNT; i += 1) {
      if (dust.life[i] <= 0) { life.setX(i, 0); continue; }
      dust.life[i] = Math.max(0, dust.life[i] - dt * 0.8);
      pos.setXYZ(i, pos.getX(i) + dust.velocity[i * 3] * dt, pos.getY(i) + dust.velocity[i * 3 + 1] * dt, pos.getZ(i) + dust.velocity[i * 3 + 2] * dt);
      dust.velocity[i * 3] *= 1 - dt * 0.9; dust.velocity[i * 3 + 2] *= 1 - dt * 0.9;
      life.setX(i, dust.life[i]);
    }
    pos.needsUpdate = true;
    life.needsUpdate = true;
  }

  return (
    <>
      <group ref={ship} name={COURIER_GROUP} visible>
        <group scale={COURIER.scale}>
          <primitive object={lod} />
          {MODEL.exhausts.map((p, i) => (
            <mesh key={i} ref={(m) => { flames.current[i] = m; }} geometry={flameGeometry} material={flameMaterial} position={p} renderOrder={6} frustumCulled={false} />
          ))}
          <pointLight ref={light} position={[0, 0, 14]} color="#7fd8ff" distance={40} decay={2} intensity={0} />
          <mesh ref={shield} geometry={shieldGeometry} material={shieldMaterial} scale={MODEL.shield as unknown as [number, number, number]} visible={false} renderOrder={7} />
        </group>
      </group>
      {trails.map((t, i) => <mesh key={i} geometry={t.geometry} material={trailMaterial} frustumCulled={false} renderOrder={5} />)}
      <points ref={dustPoints} geometry={dust.geometry} material={dust.material} frustumCulled={false} renderOrder={5} />
    </>
  );
}

