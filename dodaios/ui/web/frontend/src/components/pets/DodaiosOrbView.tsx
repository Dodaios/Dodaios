/**
 * The vendored Jarvis orb on its own canvas. A My Pets card and a worn
 * companion each keep one. The caller names the state.
 */

// The halo reaches ~70% of the frame. The disc used to fill the box; 60% of
// that gap leaves scale 0.88.
const JARVIS_DISC_SCALE = 0.88;

function BackdropDisc({ opacity }: { opacity: number }) {
  if (opacity <= 0) return null;
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 flex items-center justify-center">
      <div
        className="aspect-square h-full max-w-full rounded-full bg-black"
        style={{ opacity, transform: `scale(${JARVIS_DISC_SCALE})` }}
      />
    </div>
  );
}
import { useEffect, useRef } from "react";
import { Html } from "@react-three/drei";
import { useCanvasAwake } from "@/hooks/useCanvasAwake";
import { useWebglSurface } from "@/hooks/useWebglSurface";
import { useWebglSupported } from "@/lib/graphDimension";
import type { PetState } from "@/lib/petStates";
import { shaderVoiceLevel } from "@/components/society/companion/shaderPet";
import type { PetMood } from "@/components/society/companion/petRig";
import { createRenderer, type Renderer } from "./dodaiosOrb/renderer";
import { jarvisOrbMood } from "./dodaiosOrb/mood";
import { SIZE_PRESETS } from "./dodaiosOrb/states";

const MOOD_STATE: Record<PetMood, PetState> = {
  idle: "idle", work: "working", talk: "talking", sleep: "sleeping",
};

export function JarvisOrbView({ state, reduced, testId = "jarvis-orb-preview", backdrop = 0 }: {
  state: PetState;
  reduced: boolean;
  testId?: string;
  /** Black disc behind the orb. 0 is clear. Grid tiles leave this at 0. */
  backdrop?: number;
}) {
  const host = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const orbRef = useRef<Renderer | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;
  const { generation } = useWebglSurface(host);
  const awake = useCanvasAwake(host);
  const supported = useWebglSupported();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !supported || !awake) return;
    const orb = createRenderer({
      canvas,
      preset: SIZE_PRESETS.avatar,
      dpr: Math.min(window.devicePixelRatio || 1, 2),
      initialState: jarvisOrbMood(stateRef.current),
      initialPalette: "cyan",
    });
    orbRef.current = orb;
    const fit = () => orb.resize();
    const frame = requestAnimationFrame(fit);
    const observer = new ResizeObserver(fit);
    observer.observe(canvas.parentElement ?? canvas);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      orbRef.current = null;
      orb.dispose();
    };
  }, [generation, supported, awake]);

  useEffect(() => {
    const orb = orbRef.current;
    if (!orb) return;
    const mood = jarvisOrbMood(state);
    orb.setState(mood);
    orb.setPaused(reduced);
    if (reduced || (state !== "talking" && state !== "listening")) {
      orb.setIntensityOverride(null);
      return;
    }
    const follow = () => {
      const level = shaderVoiceLevel(state);
      orb.setIntensityOverride(level > 0.01 ? mood.energy * (0.65 + 0.7 * level) : null);
    };
    follow();
    const timer = window.setInterval(follow, 100);
    return () => window.clearInterval(timer);
  }, [state, reduced, generation, awake]);

  return (
    <div ref={host} data-testid={testId} data-state={state} data-backdrop={backdrop} className="relative isolate h-full w-full">
      <BackdropDisc opacity={backdrop} />
      {supported && awake && (
        <canvas ref={canvasRef} className="relative z-10 block h-full w-full" />
      )}
    </div>
  );
}

/** A worn orb beside an agent. Its canvas is its own, so the Verse keeps one context. */
export function JarvisOrbCompanion({ drive, reduced, paused }: {
  drive?: { current: { mood: PetMood } };
  reduced: boolean;
  paused: boolean;
}) {
  const state = MOOD_STATE[drive?.current.mood ?? "idle"];
  return (
    <Html center distanceFactor={4.5} style={{ pointerEvents: "none" }}>
      <div className="h-28 w-28">
        <JarvisOrbView state={state} reduced={reduced || paused} testId="jarvis-orb-companion" />
      </div>
    </Html>
  );
}
