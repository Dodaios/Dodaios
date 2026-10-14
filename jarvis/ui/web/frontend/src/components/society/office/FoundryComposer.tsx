/**
 * The Foundry deck's frame: bloom on everything that glows (rails, signs,
 * signal lights, the Core) and a soft studio environment so steel and gold
 * reflect something. Only the coding floor mounts it, and only in the full
 * stage; the compact side-panel stage renders plainly.
 *
 * Bloom runs at half the canvas resolution, with its threshold above any lit
 * surface: only the self-lit parts (colour above 1) bloom.
 * Mounted inside the Canvas; `useFrame` priority 1 takes rendering over from R3F.
 */
import { useEffect, useMemo } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { HalfFloatType, PMREMGenerator, Vector2, WebGLRenderTarget } from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

export const FOUNDRY_BLOOM = { strength: 0.6, radius: 0.45, threshold: 1.0 } as const;
/** How strongly the studio environment lights the deck's metals. */
const ENVIRONMENT = 0.32;

/** The studio environment for reflections, while mounted. */
export function FoundryEnvironment() {
  const gl = useThree((s) => s.gl);
  const scene = useThree((s) => s.scene);
  useEffect(() => {
    const pmrem = new PMREMGenerator(gl);
    const room = new RoomEnvironment();
    const target = pmrem.fromScene(room, 0.04);
    const before = { environment: scene.environment, intensity: scene.environmentIntensity };
    scene.environment = target.texture;
    scene.environmentIntensity = ENVIRONMENT;
    return () => {
      scene.environment = before.environment;
      scene.environmentIntensity = before.intensity;
      target.dispose();
      room.dispose();
      pmrem.dispose();
    };
  }, [gl, scene]);
  return null;
}

export function FoundryComposer() {
  const gl = useThree((s) => s.gl);
  const scene = useThree((s) => s.scene);
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  const dpr = useThree((s) => s.viewport.dpr);
  const composer = useMemo(() => {
    // A multisampled HDR target: the canvas's own antialiasing does not reach an offscreen render.
    const c = new EffectComposer(gl, new WebGLRenderTarget(1, 1, { type: HalfFloatType, samples: 4 }));
    c.addPass(new RenderPass(scene, camera));
    c.addPass(new UnrealBloomPass(new Vector2(256, 256), FOUNDRY_BLOOM.strength, FOUNDRY_BLOOM.radius, FOUNDRY_BLOOM.threshold));
    c.addPass(new OutputPass());
    return c;
  }, [gl, scene, camera]);
  useEffect(() => {
    composer.setPixelRatio(dpr);
    composer.setSize(size.width, size.height);
    // The bloom pass blurs at half of that: wide glows need no full-resolution targets.
    const bloom = composer.passes.find((p): p is UnrealBloomPass => p instanceof UnrealBloomPass);
    bloom?.setSize(Math.max(2, Math.round((size.width * dpr) / 2)), Math.max(2, Math.round((size.height * dpr) / 2)));
  }, [composer, size.width, size.height, dpr]);
  useEffect(() => () => composer.dispose(), [composer]);
  useFrame(() => composer.render(), 1);
  return null;
}
