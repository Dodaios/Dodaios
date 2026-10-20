/**
 * Owns the frame: steps the camera, frames the orthographic camera on the
 * view, streams the plate, then renders the three passes renderOrder.ts
 * describes: backdrop (plate, untouched by tone mapping, and occluder depth),
 * x-ray silhouettes of bodies behind occluders, then everything live (actors
 * and screens AgX tone mapped at the plate's exposure, effects).
 */
import { useEffect, useMemo } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { AgXToneMapping, GreaterDepth, MeshBasicMaterial, type OrthographicCamera } from "three";
import type { Deck } from "../content/deck";
import type { StageRuntime } from "../runtime";
import { applyPlateCamera } from "./plateCamera";
import type { PlateLayer } from "./plateLayer";
import { BACKDROP_LAYER, DEBUG_LAYER, XRAY_LAYER } from "./renderOrder";

export function xrayMaterial(): MeshBasicMaterial {
  return new MeshBasicMaterial({
    color: 0x9fb4c8, transparent: true, opacity: 0.22, depthFunc: GreaterDepth, depthWrite: false, toneMapped: false,
  });
}

interface Props {
  runtime: StageRuntime;
  deck: Deck;
  plate: PlateLayer;
  debug: boolean;
}

export function StageRenderer({ runtime, deck, plate, debug }: Props) {
  const gl = useThree((s) => s.gl);
  const scene = useThree((s) => s.scene);
  const camera = useThree((s) => s.camera) as OrthographicCamera;
  const size = useThree((s) => s.size);
  const dpr = useThree((s) => s.viewport.dpr);
  const xray = useMemo(xrayMaterial, []);
  useEffect(() => () => xray.dispose(), [xray]);

  useEffect(() => {
    runtime.view.resize({ width: Math.max(1, size.width), height: Math.max(1, size.height), dpr });
  }, [runtime, size.width, size.height, dpr]);

  useEffect(() => {
    gl.info.autoReset = false;
    return () => { gl.info.autoReset = true; };
  }, [gl]);

  // The camera moves before anything that reads the view this frame.
  useFrame((_, dt) => {
    runtime.view.step(Math.min(dt, 0.1));
    applyPlateCamera(camera, deck.camera, runtime.view.current, runtime.view.vp);
  }, -2);

  useFrame((_, dt) => {
    const started = performance.now();
    plate.update(runtime.view.current, runtime.view.vp, runtime.view.revision, gl, started);
    gl.info.reset();
    gl.toneMapping = AgXToneMapping;
    gl.toneMappingExposure = Math.pow(2, deck.exposure);
    gl.autoClear = true;
    camera.layers.set(BACKDROP_LAYER);
    gl.render(scene, camera);
    gl.autoClear = false;
    camera.layers.set(XRAY_LAYER);
    scene.overrideMaterial = xray;
    gl.render(scene, camera);
    scene.overrideMaterial = null;
    camera.layers.set(0);
    if (debug) camera.layers.enable(DEBUG_LAYER);
    gl.render(scene, camera);
    camera.layers.set(0);
    const s = runtime.stats;
    s.drawCalls = gl.info.render.calls;
    s.triangles = gl.info.render.triangles;
    s.cpuMs = s.cpuMs * 0.9 + (performance.now() - started) * 0.1;
    s.frameMs = s.frameMs * 0.9 + dt * 1000 * 0.1;
    s.tiles = plate.resident;
    s.tilesLoading = plate.inFlight;
    s.plateLevel = plate.levelName;
    for (const fn of runtime.afterFrame) fn();
  }, 1);

  return null;
}
