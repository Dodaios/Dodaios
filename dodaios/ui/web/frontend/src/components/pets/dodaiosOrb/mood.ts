/**
 * Dodaios pet states, as targets the vendored orb eases toward.
 * Objects, not the built-in names: those names snap success and alert back to idle.
 */
import type { PetState } from "@/lib/petStates";
import { STATE_TARGETS, type JarvisStateTarget } from "./states";

export const JARVIS_ORB_MOODS: Record<PetState, JarvisStateTarget> = {
  idle: STATE_TARGETS.idle,
  listening: {
    energy: 1.35, rotationSpeed: 0.6, particleSpeed: 1.55, shellRadius: 1.08,
    ringSpread: 1, filamentOpacity: 0.7, coreScale: 1.1, bloom: 0.9,
  },
  thinking: STATE_TARGETS.thinking,
  talking: {
    ...STATE_TARGETS.thinking,
    energy: 1.2, rotationSpeed: 0.9, particleSpeed: 1.45, filamentOpacity: 0.62,
  },
  success: STATE_TARGETS.success,
  error: STATE_TARGETS.alert,
  sleeping: {
    energy: 0.35, rotationSpeed: 0.16, particleSpeed: 0.22, shellRadius: 0.92,
    ringSpread: 0.72, filamentOpacity: 0.12, coreScale: 0.78, bloom: 0.28,
  },
  working: {
    energy: 0.9, rotationSpeed: 0.72, particleSpeed: 0.85, shellRadius: 1.02,
    ringSpread: 0.96, filamentOpacity: 0.42, coreScale: 1, bloom: 0.66,
  },
  searching: {
    energy: 1.12, rotationSpeed: 1.55, particleSpeed: 1.4, shellRadius: 1.1,
    ringSpread: 1.18, filamentOpacity: 0.55, coreScale: 1.02, bloom: 0.8,
  },
  held: {
    energy: 0.6, rotationSpeed: 0.22, particleSpeed: 0.4, shellRadius: 1.14,
    ringSpread: 0.8, filamentOpacity: 0.3, coreScale: 1.18, bloom: 0.5,
  },
};

export function jarvisOrbMood(state: PetState): JarvisStateTarget {
  return JARVIS_ORB_MOODS[state];
}
