/**
 * Which face an agent shows when nobody picked one for it. By default that is
 * a pixel creature grown from its shape and colour, so a roster of agents
 * that were created with shapes reads as creatures without anyone editing
 * them. An agent that explicitly wears its shape (`look: "shape"`), a
 * creature of its own or a pet is never touched.
 *
 * The switch is a presentation choice of this device, like the companion's
 * visibility: it lives in local storage and changes no agent.
 */
import { useMemo } from "react";
import { create } from "zustand";
import type { CompanionAppearance } from "./appearance";
import { creatureFromShape, type CreatureLook } from "./creature";

const STORAGE_KEY = "jarvis.companion.creatures-by-default.v1";

function readEnabled(): boolean {
  try { return localStorage.getItem(STORAGE_KEY) !== "false"; }
  catch { return true; } // Storage can be unavailable in private browser profiles.
}

export const useCreatureDefault = create<{ enabled: boolean; setEnabled: (enabled: boolean) => void }>((set) => ({
  enabled: readEnabled(),
  setEnabled: (enabled) => {
    try { localStorage.setItem(STORAGE_KEY, String(enabled)); }
    catch { /* The open windows keep the in-memory choice. */ }
    set({ enabled });
  },
}));

// Another window of the app flipped the switch: follow it.
if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY) useCreatureDefault.setState({ enabled: event.newValue !== "false" });
  });
}

/** Whether a look without a creature of its own is drawn as one grown from its shape. */
export function growsCreature(appearance: Pick<CompanionAppearance, "creature" | "look">, enabled: boolean): boolean {
  return !appearance.creature && enabled && appearance.look !== "shape";
}

/**
 * The creature a surface draws for this look, or undefined when it draws the
 * shape: the one the agent wears, or the one grown from its shape. A worn pet
 * always wins; the pet surfaces decide that themselves.
 */
export function useShownCreature(appearance: CompanionAppearance): CreatureLook | undefined {
  const enabled = useCreatureDefault((state) => state.enabled);
  const { creature, look, shape, color, eyes, accessories } = appearance;
  return useMemo(
    () => creature ?? (growsCreature({ creature, look }, enabled) ? creatureFromShape({ shape, color, eyes, accessories }) : undefined),
    [creature, look, enabled, shape, color, eyes, accessories],
  );
}
