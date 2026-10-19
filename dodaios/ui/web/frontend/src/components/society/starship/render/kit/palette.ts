/**
 * The ship's colours (sRGB hex). Charcoal and warm white carry the
 * architecture, gold marks command and everything the captain uses, cyan is
 * information. State colours appear only on real state.
 */
export const SHIP = {
  charcoal: "#24282f",
  graphite: "#30353d",
  steel: "#5d6672",
  steelLight: "#9aa3ae",
  hullOuter: "#aeb4bc",
  hullDark: "#3b4149",
  panel: "#e4e0d8",
  panelCool: "#d4d8dd",
  panelDark: "#2b3038",
  trim: "#c9ccd1",
  gold: "#d9a441",
  goldDeep: "#a8782a",
  cyan: "#5fd4ff",
  cyanDeep: "#1b7fb0",
  white: "#f4f6f8",
  lightWarm: "#ffe2b8",
  lightCool: "#cfe8ff",
  leather: "#3a2d29",
  fabric: "#3c4250",
  plant: "#3f7d4a",
  plantDark: "#2b5a36",
  soil: "#2d2421",
} as const;

export const STATE = {
  working: "#3fd27f",
  waiting: "#ffb020",
  idle: "#8a96a8",
  paused: "#6b6f8a",
  error: "#ff4d5e",
} as const;
