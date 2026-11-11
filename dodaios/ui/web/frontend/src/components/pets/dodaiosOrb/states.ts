// Vendored from cyber1443/jarvis-ai-orb-web-animation @ 8af5ad1d. MIT.
// The notice is dodaiosOrb/LICENSE and third_party/orb-web-animation/LICENSE.
export type JarvisStateName = "idle" | "thinking" | "success" | "alert";

export type JarvisSize = "hero" | "panel" | "avatar";

export type JarvisPaletteName = "cyan" | "aurora" | "ember";

export interface JarvisStateTarget {
  energy: number;
  rotationSpeed: number;
  particleSpeed: number;
  shellRadius: number;
  ringSpread: number;
  filamentOpacity: number;
  coreScale: number;
  bloom: number;
}

export interface JarvisSizePreset {
  px: number;
  particleCount: number;
  filamentCount: number;
  ringSegments: number;
  sceneScale: number;
  dpr: number;
  minDpr: number;
}

export interface JarvisPaletteValues {
  core: number;
  primary: number;
  secondary: number;
  tertiary: number;
  deep: number;
  fallback: string;
}

export type JarvisState = JarvisStateName | JarvisStateTarget;
export type JarvisPalette = JarvisPaletteName | JarvisPaletteValues;

export const STATE_TARGETS: Record<JarvisStateName, JarvisStateTarget> = {
  idle: {
    energy: 0.72,
    rotationSpeed: 0.48,
    particleSpeed: 0.55,
    shellRadius: 1.0,
    ringSpread: 0.88,
    filamentOpacity: 0.34,
    coreScale: 0.92,
    bloom: 0.55,
  },
  thinking: {
    energy: 1.08,
    rotationSpeed: 1.35,
    particleSpeed: 1.24,
    shellRadius: 1.06,
    ringSpread: 1.06,
    filamentOpacity: 0.5,
    coreScale: 1.05,
    bloom: 0.82,
  },
  success: {
    energy: 1.24,
    rotationSpeed: 0.82,
    particleSpeed: 1.08,
    shellRadius: 1.12,
    ringSpread: 1.16,
    filamentOpacity: 0.64,
    coreScale: 1.18,
    bloom: 1.0,
  },
  alert: {
    energy: 0.94,
    rotationSpeed: 0.92,
    particleSpeed: 0.92,
    shellRadius: 1.04,
    ringSpread: 0.98,
    filamentOpacity: 0.46,
    coreScale: 1.0,
    bloom: 0.74,
  },
};

export const SIZE_PRESETS: Record<JarvisSize, JarvisSizePreset> = {
  hero: {
    px: 640,
    particleCount: 660,
    filamentCount: 74,
    ringSegments: 168,
    sceneScale: 0.82,
    dpr: 2,
    minDpr: 1.25,
  },
  panel: {
    px: 320,
    particleCount: 460,
    filamentCount: 50,
    ringSegments: 144,
    sceneScale: 0.88,
    dpr: 2.25,
    minDpr: 1.75,
  },
  avatar: {
    px: 112,
    particleCount: 165,
    filamentCount: 18,
    ringSegments: 128,
    sceneScale: 0.82,
    dpr: 3.5,
    minDpr: 2.75,
  },
};

const cyanFallback =
  "radial-gradient(circle at 50% 50%, rgba(238,255,255,0.96) 0%, rgba(71,245,255,0.82) 16%, rgba(20,184,255,0.48) 42%, rgba(6,92,148,0.22) 70%, rgba(0,0,0,0) 82%)";

export const PALETTES: Record<JarvisPaletteName, JarvisPaletteValues> = {
  cyan: {
    core: 0xeaffff,
    primary: 0x38f4ff,
    secondary: 0x19a8ff,
    tertiary: 0x7fffee,
    deep: 0x063952,
    fallback: cyanFallback,
  },
  aurora: {
    core: 0xf2ffff,
    primary: 0x58f7ff,
    secondary: 0x2cc7ff,
    tertiary: 0x9afff4,
    deep: 0x073a66,
    fallback: cyanFallback,
  },
  ember: {
    core: 0xffffff,
    primary: 0x4df6ff,
    secondary: 0x0ea5e9,
    tertiary: 0x99fff0,
    deep: 0x052f4a,
    fallback: cyanFallback,
  },
};

export function resolvePalette(input: JarvisPalette | undefined): JarvisPaletteValues {
  if (!input) return PALETTES.cyan;
  if (typeof input === "string") return PALETTES[input] ?? PALETTES.cyan;
  return input;
}

export function resolveStateTarget(input: JarvisState | undefined): JarvisStateTarget {
  if (!input) return STATE_TARGETS.idle;
  if (typeof input === "string") return STATE_TARGETS[input] ?? STATE_TARGETS.idle;
  return input;
}

export function sameStateTarget(a: JarvisStateTarget, b: JarvisStateTarget): boolean {
  return (
    a.energy === b.energy &&
    a.rotationSpeed === b.rotationSpeed &&
    a.particleSpeed === b.particleSpeed &&
    a.shellRadius === b.shellRadius &&
    a.ringSpread === b.ringSpread &&
    a.filamentOpacity === b.filamentOpacity &&
    a.coreScale === b.coreScale &&
    a.bloom === b.bloom
  );
}

/**
 * How hard a mood change flares. Idle stays quiet. A target object is already
 * the mood, so it must not use the thinking kick (that made a resting orb look busy).
 */
export function stateChangeKick(state: JarvisState): number {
  if (typeof state !== "string" || state === "idle") return 0.2;
  if (state === "thinking") return 0.62;
  if (state === "alert") return 0.88;
  if (state === "success") return 1.25;
  return 0.62;
}
