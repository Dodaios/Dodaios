/**
 * The deck's environment map (a small equirect Radiance HDR the cook renders
 * at the main room) as the scene environment, prefiltered with PMREM. Only
 * the live people's PBR materials read it, for their reflections; the plate
 * and the effects ignore it.
 */
import { useEffect } from "react";
import { useThree } from "@react-three/fiber";
import { DataTexture, EquirectangularReflectionMapping, LinearFilter, PMREMGenerator, type Texture } from "three";
import { HDRLoader } from "three/examples/jsm/loaders/HDRLoader.js";

export function DeckEnvironment({ url }: { url: string | null }) {
  const gl = useThree((s) => s.gl);
  const scene = useThree((s) => s.scene);

  useEffect(() => {
    if (!url) return;
    const abort = new AbortController();
    let env: Texture | null = null;
    (async () => {
      const res = await fetch(url, { signal: abort.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const buffer = await res.arrayBuffer();
      const head = new TextDecoder().decode(buffer.slice(0, 10));
      if (!head.startsWith("#?")) throw new Error("not a Radiance HDR");
      const parsed = new HDRLoader().parse(buffer);
      const source = new DataTexture(parsed.data, parsed.width, parsed.height, undefined, parsed.type);
      source.mapping = EquirectangularReflectionMapping;
      source.minFilter = LinearFilter;
      source.magFilter = LinearFilter;
      source.flipY = true;
      source.needsUpdate = true;
      const pmrem = new PMREMGenerator(gl);
      env = pmrem.fromEquirectangular(source).texture;
      pmrem.dispose();
      source.dispose();
      if (abort.signal.aborted) { env.dispose(); env = null; return; }
      scene.environment = env;
    })().catch((error: unknown) => {
      // The room probes still light the people; only their reflections go flat.
      if (!abort.signal.aborted) console.warn("Verse environment map unavailable", error);
    });
    return () => {
      abort.abort();
      if (env && scene.environment === env) scene.environment = null;
      env?.dispose();
    };
  }, [url, gl, scene]);

  return null;
}
