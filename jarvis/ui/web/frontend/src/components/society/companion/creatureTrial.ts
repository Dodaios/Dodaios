/**
 * The trial switch for pixel creatures: while it is on, every agent that has
 * no creature of its own is shown as one, grown from its shape look. It is a
 * presentation choice of this device, like the companion's visibility, so it
 * lives in local storage and changes no agent.
 */
import { useMemo } from "react";
import { create } from "zustand";
import type { CompanionAppearance } from "./appearance";
import { creatureFromShape, type CreatureLook } from "./creature";

const STORAGE_KEY = "jarvis.companion.creatures-everywhere.v1";

function readEverywhere(): boolean {
  try { return localStorage.getItem(STORAGE_KEY) === "true"; }
  catch { return false; } // Storage can be unavailable in private browser profiles.
}

export const useCreatureTrial = create<{ everywhere: boolean; setEverywhere: (everywhere: boolean) => void }>((set) => ({
  everywhere: readEverywhere(),
  setEverywhere: (everywhere) => {
    try { localStorage.setItem(STORAGE_KEY, String(everywhere)); }
    catch { /* The open windows keep the in-memory choice. */ }
    set({ everywhere });
  },
}));

// Another window of the app flipped the switch: follow it.
if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY) useCreatureTrial.setState({ everywhere: event.newValue === "true" });
  });
}

/**
 * The creature a surface draws for this look, or undefined when it draws the
 * shape: the one the agent wears, or (trial switch on) the one grown from its
 * shape. A worn pet always wins; the pet surfaces decide that themselves.
 */
export function useShownCreature(appearance: CompanionAppearance): CreatureLook | undefined {
  const everywhere = useCreatureTrial((state) => state.everywhere);
  const { creature, shape, color, eyes, accessories } = appearance;
  return useMemo(
    () => creature ?? (everywhere ? creatureFromShape({ shape, color, eyes, accessories }) : undefined),
    [creature, everywhere, shape, color, eyes, accessories],
  );
}
