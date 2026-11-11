/**
 * The Kenney cube cat (`assets/pets/cube-cat.glb`, CC0). Its clips move
 * separate pieces — body, tail, legs — so a mixer can play them. There is
 * no skeleton and no forward travel: the root only bobs.
 */

import type { PetState } from "@/lib/petStates";

/** Clips shipped in the cat GLB, run first because that is the one the preview plays. */
export const CUBE_CLIPS = [
  "run",
  "walk",
  "idle",
  "static",
  "eat",
  "dance",
  "gesture-positive",
  "gesture-negative",
] as const;

export type CubeClip = (typeof CUBE_CLIPS)[number];

/** The clip that matches a desktop pet state. The file has eight clips for ten states. */
const CLIP_FOR_STATE: Record<PetState, CubeClip> = {
  idle: "idle",
  listening: "idle",
  thinking: "eat",
  talking: "gesture-positive",
  success: "dance",
  error: "gesture-negative",
  sleeping: "static",
  working: "walk",
  searching: "run",
  held: "static",
};

export function cubeClipForState(state: PetState): CubeClip {
  return CLIP_FOR_STATE[state];
}

/** Ground speed, metres per second, at which the cat walks and then runs. */
export const CUBE_WALK_SPEED = 0.2;
export const CUBE_RUN_SPEED = 0.9;

export function isCubeClip(name: string): name is CubeClip {
  return (CUBE_CLIPS as readonly string[]).includes(name);
}

/**
 * Which clip plays for a follower. Reduced motion holds the bind pose.
 * Standing still idles; a stroll walks; a real pace runs.
 */
export function cubeClipFor(speed: number, reduced: boolean): CubeClip {
  if (reduced || !Number.isFinite(speed)) return "static";
  const pace = Math.max(0, speed);
  if (pace >= CUBE_RUN_SPEED) return "run";
  if (pace >= CUBE_WALK_SPEED) return "walk";
  return "idle";
}
