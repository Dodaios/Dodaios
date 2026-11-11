import { lazy, Suspense, useContext, type ReactNode } from "react";
import { QueryClientContext } from "@tanstack/react-query";
import { useReducedMotion } from "framer-motion";

import { PetSprite } from "@/components/pets/PetSprite";
import { ShaderPetMark } from "@/components/pets/ShaderPetMark";
import { useActivePet, usePets } from "@/hooks/usePets";
import type { Pet } from "@/lib/petsApi";
import type { PetState } from "@/lib/petStates";
import { cn } from "@/lib/utils";
import { useEventStore, type VoiceState } from "@/store/events";

// The chat mascot, the sidebar and the composer all draw this. A pixel pet is
// a sprite. The other three pull in three.js, so they stay out of the shell
// until one of them is actually chosen.
const ShaderPetPreview = lazy(() =>
  import("@/components/pets/ShaderPetPreview").then((m) => ({ default: m.ShaderPetPreview })),
);
const ModelPetPreview = lazy(() =>
  import("@/components/pets/CubeCatStage").then((m) => ({ default: m.ModelPetPreview })),
);
const JarvisOrbView = lazy(() =>
  import("@/components/pets/DodaiosOrbView").then((m) => ({ default: m.JarvisOrbView })),
);

/**
 * Jarvis as the app draws it: the user's chosen pet (Settings -> My Pets),
 * at any size. A pixel pet plays its sprite sheet. A shader, a model and the
 * Jarvis orb play the same preview My Pets uses. With no pet chosen it is
 * Gigi, the built-in default. Every in-app spot that used to show the static
 * Gigi image (sidebar, greeting, composer chip, deck header, the live line of
 * a reasoning trace) draws this instead, so picking a pet changes them all
 * at once — `PetChanged` refetches the shared query.
 *
 * `state` fixes the animation row; `reactive` follows the voice instead
 * (listening while you talk, working while it thinks, talking while it
 * answers). Until the pets answer arrives the box stays empty at its final
 * size, so nothing jumps and no stand-in image flashes.
 */
export function PetMark({
  size,
  state,
  reactive = false,
  label,
  className,
}: {
  size: number;
  state?: PetState;
  reactive?: boolean;
  /** Accessible name; decorative without one. */
  label?: string;
  className?: string;
}) {
  // Outside a query client (an isolated test render, a bare preview) there
  // is no pets answer to read; the empty box keeps the layout.
  const client = useContext(QueryClientContext);
  const box = (
    <span
      aria-hidden
      data-testid="pet-mark"
      className={cn("inline-block shrink-0", className)}
      style={{ width: size, height: size }}
    />
  );
  if (!client) return box;
  return <ActivePetMark size={size} state={state} reactive={reactive} label={label} className={className} fallback={box} />;
}

function ActivePetMark({
  size,
  state,
  reactive,
  label,
  className,
  fallback,
}: {
  size: number;
  state?: PetState;
  reactive: boolean;
  label?: string;
  className?: string;
  fallback: ReactNode;
}) {
  const pet = useActivePet();
  const backdrop = usePets().data?.shader_backdrop ?? 0;
  const voiceState = useEventStore((s) => s.voiceState);
  const reduced = useReducedMotion() ?? false;
  if (!pet) return <>{fallback}</>;
  const shown = state ?? (reactive ? petStateForVoice(voiceState) : "idle");
  return (
    <span
      data-testid="pet-mark"
      data-pet={pet.id}
      className={cn("inline-flex shrink-0 select-none", className)}
      style={{ width: size, height: size }}
    >
      <Suspense fallback={null}>
        <PetFace pet={pet} state={shown} size={size} label={label} reduced={reduced} backdrop={backdrop} />
      </Suspense>
    </span>
  );
}

function PetFace({
  pet,
  state,
  size,
  label,
  reduced,
  backdrop,
}: {
  pet: Pet;
  state: PetState;
  size: number;
  label?: string;
  reduced: boolean;
  backdrop: number;
}) {
  if (pet.kind === "model" && pet.model_url) {
    return (
      <ModelPetPreview
        url={pet.model_url}
        clip={pet.clips?.[state] ?? pet.clips?.idle ?? "idle"}
        options={pet.options}
        reduced={reduced}
      />
    );
  }
  if (pet.kind === "scene") return <JarvisOrbView state={state} reduced={reduced} backdrop={backdrop} />;
  if (pet.kind === "shader" && pet.shader_url) {
    return <ShaderPetPreview url={pet.shader_url} state={state} reduced={reduced} backdrop={backdrop} />;
  }
  if (pet.kind === "shader") return <ShaderPetMark className="h-full w-full" />;
  return <PetSprite pet={pet} state={state} px={size} label={label} />;
}

/** The pet row that mirrors what the voice is doing right now. */
export function petStateForVoice(voice: VoiceState): PetState {
  switch (voice) {
    case "listening":
      return "listening";
    case "connecting":
    case "thinking":
      // Thinking plays the working row, the same as a trace's live line.
      return "working";
    case "speaking":
      return "talking";
    case "error":
      return "error";
    case "paused":
      return "sleeping";
    default:
      return "idle";
  }
}
