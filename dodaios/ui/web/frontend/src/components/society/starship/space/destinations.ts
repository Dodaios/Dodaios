/**
 * Where the ship is. Every destination is a sky (stars and nebula), a body
 * below the ship and a sun; the bridge's helm sets course, and new
 * destinations open with the captain's rank (the level system's
 * `destination` rewards). Pure data, so tests and the helm share it.
 */

export type DestinationId =
  | "home" | "gas_giant" | "crimson_nebula" | "ice_moon" | "twin_suns" | "event_horizon" | "aurora_world" | "galactic_core";

export interface Destination {
  id: DestinationId;
  /** Captain's level that opens it (mirrors the rulebook's `destination` rewards). */
  level: number;
  /** The body below the ship. */
  planet: {
    kind: "terran" | "gas" | "ice" | "lava" | "none" | "aurora";
    /** Day-side colours, deep to bright. */
    colours: [string, string, string];
    atmosphere: string;
    radius: number;
    /** Where the body's centre lies relative to the deck (metres). */
    centre: [number, number, number];
    rings?: { inner: number; outer: number; colour: string; tilt: number };
    cityLights?: boolean;
  };
  sky: { nebula: [string, string]; nebulaStrength: number; stars: number; band: number };
  sun: { direction: [number, number, number]; colour: string; size: number; twin?: boolean };
  /** A black hole in the sky instead of a planet's company. */
  singularity?: boolean;
}

export const DESTINATIONS: readonly Destination[] = [
  {
    id: "home", level: 1,
    planet: { kind: "terran", colours: ["#0b2a55", "#1f6fb0", "#e8f2ff"], atmosphere: "#6fb8ff", radius: 1400, centre: [520, -1650, -260], cityLights: true },
    sky: { nebula: ["#1a2a6c", "#3b1f5e"], nebulaStrength: 0.35, stars: 1, band: 0.5 },
    sun: { direction: [-0.55, 0.42, -0.72], colour: "#fff1d6", size: 1 },
  },
  {
    id: "gas_giant", level: 5,
    planet: { kind: "gas", colours: ["#5a3418", "#c98a4b", "#f3dcb4"], atmosphere: "#ffcf8a", radius: 2200, centre: [-900, -2300, -900],
      rings: { inner: 2600, outer: 4100, colour: "#d9c3a0", tilt: 0.32 } },
    sky: { nebula: ["#2b1a0c", "#1a2440"], nebulaStrength: 0.25, stars: 0.9, band: 0.3 },
    sun: { direction: [0.6, 0.35, -0.7], colour: "#fff4e0", size: 0.9 },
  },
  {
    id: "crimson_nebula", level: 10,
    planet: { kind: "none", colours: ["#000000", "#000000", "#000000"], atmosphere: "#000000", radius: 1, centre: [0, -9000, 0] },
    sky: { nebula: ["#8c1c3a", "#ff7a4c"], nebulaStrength: 1.0, stars: 0.6, band: 0.1 },
    sun: { direction: [0.2, 0.5, -0.85], colour: "#ffd2c2", size: 0.7 },
  },
  {
    id: "ice_moon", level: 15,
    planet: { kind: "ice", colours: ["#5e7c9a", "#bcd6ea", "#ffffff"], atmosphere: "#cfeaff", radius: 1100, centre: [-380, -1350, -420] },
    sky: { nebula: ["#0f3a4a", "#1d2a5a"], nebulaStrength: 0.4, stars: 1.1, band: 0.6 },
    sun: { direction: [0.7, 0.3, -0.6], colour: "#e9f3ff", size: 1.1 },
  },
  {
    id: "twin_suns", level: 20,
    planet: { kind: "lava", colours: ["#2a0f08", "#a33a12", "#ffb347"], atmosphere: "#ff8a4c", radius: 1250, centre: [640, -1500, 120] },
    sky: { nebula: ["#40200a", "#2a0f30"], nebulaStrength: 0.45, stars: 0.8, band: 0.2 },
    sun: { direction: [-0.4, 0.5, -0.76], colour: "#ffe0a8", size: 1.2, twin: true },
  },
  {
    id: "event_horizon", level: 25,
    planet: { kind: "none", colours: ["#000000", "#000000", "#000000"], atmosphere: "#000000", radius: 1, centre: [0, -9000, 0] },
    sky: { nebula: ["#1b0f3a", "#0a2a4a"], nebulaStrength: 0.5, stars: 1.2, band: 0.4 },
    sun: { direction: [0.3, 0.4, -0.86], colour: "#ffdca8", size: 0.5 },
    singularity: true,
  },
  {
    id: "aurora_world", level: 30,
    planet: { kind: "aurora", colours: ["#0a2a2a", "#1f7a6a", "#cfffe9"], atmosphere: "#5bffb8", radius: 1500, centre: [-560, -1720, -320], cityLights: true },
    sky: { nebula: ["#0d3b2e", "#3a1f5e"], nebulaStrength: 0.55, stars: 1, band: 0.5 },
    sun: { direction: [0.5, 0.45, -0.74], colour: "#f2fff6", size: 0.9 },
  },
  {
    id: "galactic_core", level: 40,
    planet: { kind: "none", colours: ["#000000", "#000000", "#000000"], atmosphere: "#000000", radius: 1, centre: [0, -9000, 0] },
    sky: { nebula: ["#ffcf8a", "#7a3cff"], nebulaStrength: 0.85, stars: 2.2, band: 1.6 },
    sun: { direction: [-0.2, 0.3, -0.93], colour: "#fff3dd", size: 0.6 },
  },
];

export const DESTINATION_IDS = DESTINATIONS.map((d) => d.id);

export function destinationById(id: string | null | undefined): Destination {
  return DESTINATIONS.find((d) => d.id === id) ?? DESTINATIONS[0];
}

/** The destinations open at a captain's level, home first. */
export function openDestinations(level: number): Destination[] {
  return DESTINATIONS.filter((d) => d.level <= Math.max(1, level));
}

const KEY = "dodaios.ship.destination.v1";

export function loadDestination(): DestinationId {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw && (DESTINATION_IDS as string[]).includes(raw)) return raw as DestinationId;
  } catch { /* storage unavailable */ }
  return "home";
}

export function saveDestination(id: DestinationId): void {
  try { localStorage.setItem(KEY, id); } catch { /* storage unavailable */ }
}
