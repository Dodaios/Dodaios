/**
 * Renderer set-up shared by every deck: tone mapping, the environment map
 * for reflections, the key light with its shadow over the deck, and a
 * post-processing chain (multisampled HDR render, bloom, output) that makes
 * every light strip, screen and hologram glow. The low quality setting
 * drops bloom and shadows.
 */
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import {
  ACESFilmicToneMapping, DirectionalLight, HalfFloatType, Object3D, PMREMGenerator, Vector2, WebGLRenderTarget, type Texture,
} from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import type { DeckPlan } from "../plan/types";

export type Quality = "high" | "low";

export function RendererSetup({ quality }: { quality: Quality }) {
  const { gl, scene } = useThree();
  useEffect(() => {
    gl.toneMapping = ACESFilmicToneMapping;
    gl.toneMappingExposure = 1.05;
    gl.shadowMap.enabled = quality === "high";
  }, [gl, quality]);
  useEffect(() => {
    const pmrem = new PMREMGenerator(gl);
    const room = new RoomEnvironment();
    const env: Texture = pmrem.fromScene(room, 0.04).texture;
    room.dispose();
    scene.environment = env;
    scene.environmentIntensity = 0.55;
    return () => { scene.environment = null; env.dispose(); pmrem.dispose(); };
  }, [gl, scene]);
  return null;
}

/** Hemisphere fill, a cool ambient and one overhead key light whose shadow covers the deck. */
export function DeckLights({ plan, quality, sunDirection }: { plan: DeckPlan; quality: Quality; sunDirection: [number, number, number] }) {
  const key = useMemo(() => {
    const light = new DirectionalLight("#ffeedd", 1.55);
    light.castShadow = quality === "high";
    const w = plan.bounds.x1 - plan.bounds.x0, d = plan.bounds.z1 - plan.bounds.z0;
    const cx = (plan.bounds.x0 + plan.bounds.x1) / 2, cz = (plan.bounds.z0 + plan.bounds.z1) / 2;
    const half = Math.max(w, d) / 2 + 4;
    // Mostly from above, leaning towards the destination's sun, so shadows stay short and readable.
    const sx = sunDirection[0] * 0.35, sz = sunDirection[2] * 0.35;
    light.position.set(cx + sx * 60, 60, cz + sz * 60);
    light.target = new Object3D();
    light.target.position.set(cx, 0, cz);
    const cam = light.shadow.camera;
    cam.left = -half; cam.right = half; cam.top = half; cam.bottom = -half; cam.near = 10; cam.far = 120;
    light.shadow.mapSize.set(4096, 4096);
    light.shadow.bias = -0.0004;
    light.shadow.normalBias = 0.03;
    light.shadow.radius = 3;
    return light;
  }, [plan, quality, sunDirection]);
  useEffect(() => () => key.shadow.map?.dispose(), [key]);
  return (
    <>
      <hemisphereLight args={["#8ea6d6", "#1d1a1c", 0.42]} />
      <ambientLight intensity={0.06} color="#9fb4d6" />
      <primitive object={key} />
      <primitive object={key.target} />
    </>
  );
}

/** Renders the scene through the bloom chain; replaces R3F's own render (priority 1). */
export function PostFx({ quality }: { quality: Quality }) {
  const { gl, scene, camera, size } = useThree();
  const composer = useMemo(() => {
    const target = new WebGLRenderTarget(1, 1, { type: HalfFloatType, samples: quality === "high" ? 4 : 0 });
    const c = new EffectComposer(gl, target);
    c.addPass(new RenderPass(scene, camera));
    if (quality === "high") c.addPass(new UnrealBloomPass(new Vector2(256, 256), 0.5, 0.42, 1.0));
    c.addPass(new OutputPass());
    return c;
  }, [gl, scene, camera, quality]);
  useEffect(() => {
    const dpr = gl.getPixelRatio();
    composer.setPixelRatio(dpr);
    composer.setSize(size.width, size.height);
  }, [composer, size.width, size.height, gl]);
  useEffect(() => () => { composer.renderTarget1.dispose(); composer.renderTarget2.dispose(); for (const p of composer.passes) (p as { dispose?: () => void }).dispose?.(); }, [composer]);
  useFrame((_, dt) => {
    if (!import.meta.env.DEV) { composer.render(dt); return; }
    // Development: what one frame costs, for runtime checks (`window.__shipStats`).
    gl.info.autoReset = false;
    gl.info.reset();
    const t0 = performance.now();
    composer.render(dt);
    const ms = performance.now() - t0;
    const stats = ((window as unknown as { __shipStats?: { ms: number; calls: number; triangles: number } }).__shipStats ??= { ms: 0, calls: 0, triangles: 0 });
    stats.ms = stats.ms * 0.9 + ms * 0.1;
    stats.calls = gl.info.render.calls;
    stats.triangles = gl.info.render.triangles;
  }, 1);
  return null;
}
