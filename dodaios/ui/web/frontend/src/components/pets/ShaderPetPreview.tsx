/**
 * The live shader pet in My Pets. The caller names the state.
 */

// The sphere fills ~85% of the view (camera z 2.2, fov 30). The disc used to
// be the whole box, about 14px past the sphere on the 180px hero. 60% of that
// overflow is scale 0.939, about 8px.
const SHADER_DISC_SCALE = 0.939;

function BackdropDisc({ opacity }: { opacity: number }) {
  if (opacity <= 0) return null;
  return (
    <div
      aria-hidden
      data-testid="shader-backdrop-disc"
      className="pointer-events-none absolute left-1/2 top-1/2 aspect-square h-full max-h-full max-w-full rounded-full bg-black"
      style={{ opacity, transform: `translate(-50%, -50%) scale(${SHADER_DISC_SCALE})` }}
    />
  );
}
import { useEffect, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { ShaderPetModel } from "@/components/society/companion/ShaderPetModel";
import { useCanvasAwake } from "@/hooks/useCanvasAwake";
import { useWebglSurface } from "@/hooks/useWebglSurface";
import type { PetState } from "@/lib/petStates";
import { useWebglSupported } from "@/lib/graphDimension";

export function ShaderPetPreview({ url, state, reduced, backdrop = 0 }: {
  url: string;
  state: PetState;
  reduced: boolean;
  /** Black disc behind the pet. 0 is clear. Grid tiles leave this at 0. */
  backdrop?: number;
}) {
  const host = useRef<HTMLDivElement>(null);
  const { generation } = useWebglSurface(host);
  const awake = useCanvasAwake(host);
  const supported = useWebglSupported();
  const [source, setSource] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    setSource(null);
    setFailed(false);
    void fetch(url)
      .then((response) => (response.ok ? response.text() : Promise.reject(new Error("missing"))))
      .then((text) => { if (live) setSource(text); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [url]);

  return (
    <div
      ref={host}
      data-testid="shader-pet-preview"
      data-state={state}
      data-backdrop={backdrop}
      className="relative h-full w-full overflow-hidden rounded-lg"
    >
      <BackdropDisc opacity={backdrop} />
      {/* Fiber's root is position:relative inline, so it cannot be the
          absolute box. The canvas element is forced to fill this one. */}
      {failed ? null : supported && awake && source && (
        <div className="absolute inset-0 z-10 [&_canvas]:!h-full [&_canvas]:!w-full">
          <Canvas
            key={generation}
            frameloop={reduced ? "demand" : "always"}
            dpr={[1, 1.5]}
            camera={{ position: [0, 0, 2.2], fov: 30, near: 0.05, far: 10 }}
            gl={{ alpha: true, antialias: true, premultipliedAlpha: false }}
          >
            <ShaderPetModel source={source} state={state} reduced={reduced} paused={!awake} heightM={1} opaque />
          </Canvas>
        </div>
      )}
    </div>
  );
}
