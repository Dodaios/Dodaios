/**
 * The eye-level view of a deck exported for it (docs/verse/realtime.md):
 * loads the realtime scene into the stage's scene (on its own layer) and,
 * while `active`, owns the frame: steps the eye-level camera (over the
 * shoulder or through the eyes) on the commander, renders deck, people and effects through the post chain (HDR
 * target with MSAA, bloom, AgX at the plate's exposure) and publishes the
 * camera for the HUD and the pointer (`runtime.eye`). In first person the
 * commander's own arms (`runtime.viewmodel`) are drawn last, into the same
 * target with depth cleared.
 *
 * Quality tiers: "high" (bloom, 4x MSAA, full resolution) by default; when
 * frames stay slower than ~45 fps the view drops to "low" (no post chain,
 * pixel ratio at most 1) for weak GPUs. The person can pin either tier in
 * the view settings (`quality`).
 *
 * The frame path allocates nothing of its own per frame (three.js and the
 * BVH query aside).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import {
  AgXToneMapping, Color, DoubleSide, HalfFloatType, PerspectiveCamera, Ray, Vector2, Vector3, WebGLRenderTarget, type Texture,
} from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import type { Deck } from "../../content/deck";
import type { StageRuntime } from "../../runtime";
import { liveLoad } from "../liveLoad";
import { REALTIME_LAYER } from "../renderOrder";
import { loadRealtimeScene, type RealtimeScene } from "./realtimeScene";
import { DECK_SHARED } from "./deckMaterial";
import { verticalFov, type SegmentTest } from "./shoulderRig";
import type { QualityChoice } from "./viewSettings";
import { viewmodelVisibility } from "../../viewmodel/motion";
import { drawViewmodel, ViewmodelPass } from "../../viewmodel/viewmodelPass";

interface Props {
  runtime: StageRuntime;
  deck: Deck;
  /** The eye-level view is the one on screen (third person on a full-size stage). */
  active: boolean;
  commanderId: string;
  /** The person's quality setting: "auto" picks the tier from the frame rate. */
  quality?: QualityChoice;
  onReady: (deck: Deck) => void;
  onError: (error: Error) => void;
}

export type QualityTier = "high" | "low";

/**
 * Bloom of the emissive fixtures, tuned against Cycles renders from the same
 * camera: UnrealBloom sums five blur levels, so a small strength already
 * matches the plate's glow (threshold 1.0, strength 0.12); more veils the
 * dark deck in grey.
 */
const BLOOM = { strength: 0.035, radius: 0.3, threshold: 1.5 };
/** Slower than this (smoothed frame time, ms) for the window below drops to the low tier. */
const SLOW_FRAME_MS = 22;
const SLOW_WINDOW_MS = 2500;
/** Frames ignored after the view opens (shader compiles, uploads). */
const WARMUP_FRAMES = 90;

/**
 * QA hook: `window.__verseTune = { bloomStrength, bloomRadius, bloomThreshold, envGain,
 * bakedGain, coatBias, exposureBias }` overrides the look while a run measures it.
 * Unset (always, outside QA runs) the view uses its built-in values.
 */
interface Tuning {
  bloomStrength?: number;
  bloomRadius?: number;
  bloomThreshold?: number;
  envGain?: number;
  bakedGain?: number;
  coatBias?: number;
  exposureBias?: number;
  /** Material property overrides by material-name prefix, e.g. { M_Floor: { specularIntensity: 0.05 } }; `visible: 0` hides. */
  materials?: Record<string, Record<string, number>>;
}

function tuning(): Tuning | undefined {
  return (window as unknown as { __verseTune?: Tuning }).__verseTune;
}

function applyTuning(loaded: RealtimeScene, bloom: UnrealBloomPass, t: Tuning | undefined): void {
  bloom.strength = t?.bloomStrength ?? BLOOM.strength;
  bloom.radius = t?.bloomRadius ?? BLOOM.radius;
  bloom.threshold = t?.bloomThreshold ?? BLOOM.threshold;
  DECK_SHARED.verseBakedGain.value = t?.bakedGain ?? 1;
  DECK_SHARED.verseCoatBias.value = t?.coatBias ?? 0;
  if (t) (window as unknown as { __verseMaterials?: string[] }).__verseMaterials = loaded.materials.map((m) => m.name);
  const env = t?.envGain ?? 1;
  for (const m of loaded.materials) {
    const props = m as unknown as Record<string, unknown> & { userData: { verseBase?: Record<string, number> } };
    const base = (props.userData.verseBase ??= { envMapIntensity: (props.envMapIntensity as number | undefined) ?? 1 });
    const override = Object.entries(t?.materials ?? {}).find(([prefix]) => m.name.startsWith(prefix))?.[1] ?? {};
    m.visible = override.visible === undefined ? true : override.visible !== 0;
    for (const [key, value] of Object.entries(override)) {
      if (key === "visible") continue;
      if (!(key in base) && typeof props[key] === "number") base[key] = props[key] as number;
      props[key] = value;
    }
    for (const [key, value] of Object.entries(base)) if (!(key in override)) props[key] = value;
    props.envMapIntensity = ((override.envMapIntensity ?? base.envMapIntensity) as number) * env;
  }
}

export function RealtimeBackdrop({ runtime, deck, active, commanderId, quality = "auto", onReady, onError }: Props) {
  const gl = useThree((s) => s.gl);
  const scene = useThree((s) => s.scene);
  const size = useThree((s) => s.size);
  const dpr = useThree((s) => s.viewport.dpr);
  const setDpr = useThree((s) => s.setDpr);
  const [loaded, setLoaded] = useState<RealtimeScene | null>(null);
  /** The tier "auto" settled on; a pinned quality overrides it. */
  const [autoTier, setAutoTier] = useState<QualityTier>("high");
  const tier: QualityTier = quality === "auto" ? autoTier : quality;
  // Back to "auto": measure again from the high tier.
  useEffect(() => { if (quality === "auto") setAutoTier("high"); }, [quality]);

  useEffect(() => {
    const content = deck.realtime;
    if (!content) return;
    const abort = new AbortController();
    let own: RealtimeScene | null = null;
    const stop = liveLoad(loadRealtimeScene(gl, content, abort.signal), (s) => {
      own = s;
      scene.add(s.group);
      setLoaded(s);
      onReady(deck);
    }, onError);
    return () => {
      stop();
      abort.abort();
      if (own) { scene.remove(own.group); own.dispose(); }
      setLoaded(null);
    };
    // The callbacks are the stage's and stable enough; a new deck is what reloads.
  }, [deck, gl, scene]);

  const camera = useMemo(() => {
    const c = new PerspectiveCamera(50, 1, 0.05, 500);
    c.layers.enable(0);
    c.layers.enable(REALTIME_LAYER);
    return c;
  }, []);

  const { composer, bloom, viewmodelPass } = useMemo(() => {
    const target = new WebGLRenderTarget(1, 1, { type: HalfFloatType, samples: 4 });
    const c = new EffectComposer(gl, target);
    c.addPass(new RenderPass(scene, camera));
    // First person: the commander's arms over the deck, before bloom and tone mapping like everything else.
    const vm = new ViewmodelPass();
    c.addPass(vm);
    const pass = new UnrealBloomPass(new Vector2(1, 1), BLOOM.strength, BLOOM.radius, BLOOM.threshold);
    c.addPass(pass);
    c.addPass(new OutputPass());
    return { composer: c, bloom: pass, viewmodelPass: vm };
  }, [gl, scene, camera]);
  useEffect(() => () => composer.dispose(), [composer]);

  useEffect(() => {
    const w = Math.max(1, size.width);
    const h = Math.max(1, size.height);
    composer.setPixelRatio(dpr);
    composer.setSize(w, h);
    camera.aspect = w / h;
    camera.fov = verticalFov(camera.aspect, runtime.shoulder.hfov());
    camera.updateProjectionMatrix();
  }, [composer, camera, size.width, size.height, dpr, runtime]);

  // The low tier renders at a pixel ratio of at most 1.
  useEffect(() => {
    if (tier !== "low" || !active) return;
    const previous = gl.getPixelRatio();
    if (previous > 1) setDpr(1);
    return () => { if (previous > 1) setDpr(previous); };
  }, [tier, active, gl, setDpr]);

  const clearColour = useMemo(() => new Color(), []);
  const direction = useMemo(() => new Vector3(), []);
  const ray = useMemo(() => new Ray(), []);
  const test = useMemo<SegmentTest>(() => (from, to) => {
    const bvh = loaded?.collider;
    if (!bvh) return null;
    direction.set(to.x - from.x, to.y - from.y, to.z - from.z);
    const length = direction.length();
    if (length < 1e-6) return null;
    ray.origin.set(from.x, from.y, from.z);
    ray.direction.copy(direction).multiplyScalar(1 / length);
    const hit = bvh.raycastFirst(ray, DoubleSide, 0, length);
    return hit ? hit.distance / length : null;
  }, [loaded, ray, direction]);

  // Publish the eye-level camera while it is the view on screen.
  useEffect(() => {
    if (!active || !loaded) return;
    const eye = { camera, collider: loaded.collider, test };
    runtime.eye = eye;
    runtime.control.reframe = true;
    return () => { if (runtime.eye === eye) runtime.eye = null; };
  }, [active, loaded, runtime, camera, test]);

  const frames = useRef({ count: 0, slowSince: 0 });
  useEffect(() => { frames.current = { count: 0, slowSince: 0 }; }, [active, loaded, quality]);
  // The QA look hook was applied last frame: unset again, the built-in look is put back once.
  const tuned = useRef(false);
  // The commander's pose as the rig reads it, refilled every frame.
  const body = useMemo(() => ({ x: 0, y: 0, z: 0, heading: 0, moving: false }), []);

  useFrame((_, dt) => {
    if (!active || !loaded) return;
    const started = performance.now();
    const rig = runtime.shoulder;
    const control = runtime.control;
    const pose = runtime.poses.get(commanderId);
    const override = runtime.cameraOverride;
    if (override) {
      // Another mode drives the camera (the duel's shoulder camera); the rig waits where it was.
      camera.position.set(override.position.x, override.position.y, override.position.z);
      camera.lookAt(override.target.x, override.target.y, override.target.z);
      if (Math.abs(camera.fov - override.fovDeg) > 1e-3) { camera.fov = override.fovDeg; camera.updateProjectionMatrix(); }
      runtime.commanderHidden = false;
    } else if (pose) {
      if (control.reframe) {
        rig.snapBehind(pose.yaw);
        control.reframe = false;
      }
      body.x = pose.x;
      body.y = pose.y;
      body.z = pose.z;
      body.heading = pose.yaw;
      body.moving = pose.moving;
      rig.update(dt, body, test);
    }
    if (!override) {
      // Close behind the head or inside it (first person) the commander's own body is not drawn.
      runtime.commanderHidden = viewmodelVisibility({ eyeOn: true, firstShare: rig.firstShare, thirdDistance: rig.actual, duelFirstShare: null }).hideOwnBody;
      camera.position.set(rig.position.x, rig.position.y, rig.position.z);
      camera.lookAt(rig.target.x, rig.target.y, rig.target.z);
      const fov = verticalFov(camera.aspect, rig.hfov());
      if (Math.abs(camera.fov - fov) > 1e-3) { camera.fov = fov; camera.updateProjectionMatrix(); }
    }
    camera.updateMatrixWorld();
    const vm = runtime.viewmodel;
    vm?.prepare(camera, dt, scene.environment as Texture | null);
    viewmodelPass.draw = vm;
    gl.info.reset();
    const tune = tuning();
    if (tune || tuned.current) applyTuning(loaded, bloom, tune);
    tuned.current = !!tune;
    gl.toneMapping = AgXToneMapping;
    gl.toneMappingExposure = Math.pow(2, deck.exposure + (tune?.exposureBias ?? 0));
    gl.autoClear = true;
    // True black behind everything: AgX lifts the plate view's near-black clear colour to a visible grey.
    gl.getClearColor(clearColour);
    const clearAlpha = gl.getClearAlpha();
    gl.setClearColor(0x000000, 1);
    if (tier === "high") {
      composer.render(dt);
    } else {
      gl.setRenderTarget(null);
      gl.render(scene, camera);
      if (vm?.visible) drawViewmodel(gl, vm, null);
    }
    gl.setClearColor(clearColour, clearAlpha);
    const s = runtime.stats;
    s.drawCalls = gl.info.render.calls;
    s.triangles = gl.info.render.triangles;
    s.cpuMs = s.cpuMs * 0.9 + (performance.now() - started) * 0.1;
    s.frameMs = s.frameMs * 0.9 + dt * 1000 * 0.1;
    s.plateLevel = "3D";
    s.tiles = 0;
    s.tilesLoading = 0;
    s.tier = tier;
    // A GPU that cannot hold ~45 fps at the high tier gets the low one.
    const f = frames.current;
    f.count++;
    if (quality === "auto" && tier === "high" && f.count > WARMUP_FRAMES && document.visibilityState === "visible") {
      if (s.frameMs > SLOW_FRAME_MS) {
        if (!f.slowSince) f.slowSince = started;
        else if (started - f.slowSince > SLOW_WINDOW_MS) setAutoTier("low");
      } else {
        f.slowSince = 0;
      }
    }
    for (const fn of runtime.afterFrame) fn();
  }, 1);

  return null;
}
