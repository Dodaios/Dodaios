/**
 * A GLB pet on My Pets. The clip, height and camera come from its pet.json.
 */
import { Suspense, useLayoutEffect, useRef } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { CubeCatModel } from "@/components/society/companion/CubeCatModel";
import { useCanvasAwake } from "@/hooks/useCanvasAwake";
import { useWebglSurface } from "@/hooks/useWebglSurface";
import { useWebglSupported } from "@/lib/graphDimension";
import type { ModelOptions } from "@/lib/petsApi";

const DEFAULT_EYE: [number, number, number] = [1.05, 0.55, 1.9];

function AimAt({ height, aim }: { height: number; aim: number }) {
  const camera = useThree((state) => state.camera);
  useLayoutEffect(() => {
    camera.lookAt(0, height * aim, 0);
  }, [camera, height, aim]);
  return null;
}

/** Any uploaded or built-in model, playing one clip. */
export function ModelPetPreview({
  url,
  clip,
  options,
  reduced,
}: {
  url: string;
  clip: string;
  options?: ModelOptions;
  reduced: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const { generation } = useWebglSurface(host);
  const awake = useCanvasAwake(host);
  const supported = useWebglSupported();
  const height = options?.height ?? 0.7;
  const aim = options?.aim ?? 0.62;
  const eye = options?.eye ?? DEFAULT_EYE;
  return (
    <div
      ref={host}
      data-testid="model-pet-preview"
      data-clip={clip}
      className="h-full w-full overflow-hidden rounded-lg"
    >
      {supported && awake && url && (
        <Canvas
          key={generation}
          frameloop={reduced ? "demand" : "always"}
          dpr={[1, 2]}
          camera={{ position: eye, fov: 30, near: 0.05, far: 20 }}
          gl={{ alpha: true, antialias: true }}
        >
          <AimAt height={height} aim={aim} />
          <ambientLight intensity={0.75} />
          <directionalLight position={[2.2, 3.4, 2]} intensity={1.6} />
          <Suspense fallback={null}>
            <CubeCatModel url={url} clip={clip} reduced={reduced} paused={!awake} heightM={height} />
          </Suspense>
        </Canvas>
      )}
    </div>
  );
}
