/**
 * The ship's interaction state, shared by the canvas and the HUD. What
 * changes every frame (the captain's position, the crew's bodies) lives in
 * plain mutable objects and never in React state; the store carries what the
 * HUD renders and what the world must react to.
 */
import { create } from "zustand";
import type { DeckId, Vec2 } from "./plan/types";
import { loadDestination, saveDestination, type DestinationId } from "./space/destinations";

export type Selection =
  | { kind: "agent"; id: string }
  | { kind: "station"; id: string };

export interface CaptainBody {
  x: number;
  z: number;
  yaw: number;
  /** Remaining route (world points). */
  path: Vec2[];
  moving: boolean;
  speed: number;
  /** Seated in a chair (the captain's chair), with its yaw and seat height. */
  seated: { x: number; z: number; yaw: number; seatY: number } | null;
}

/** The captain's body: mutable, read by the camera and the crew every frame. */
export const captain: CaptainBody = { x: 0, z: 0, yaw: Math.PI, path: [], moving: false, speed: 0, seated: null };

const DECK_KEY = "dodaios.ship.deck.v1";
const LOOK_KEY = "dodaios.ship.captain.v1";

/** The captain's suit, chosen at the quartermaster and kept per browser profile. */
export interface CaptainLook {
  suit: string;
  trim: string;
  visor: string;
}

export const DEFAULT_LOOK: CaptainLook = { suit: "#2c3340", trim: "#d9a441", visor: "#d6a440" };

function loadLook(): CaptainLook {
  try {
    const raw = localStorage.getItem(LOOK_KEY);
    if (raw) return { ...DEFAULT_LOOK, ...(JSON.parse(raw) as Partial<CaptainLook>) };
  } catch { /* storage unavailable or damaged */ }
  return DEFAULT_LOOK;
}

function loadDeck(): DeckId {
  try {
    const raw = localStorage.getItem(DECK_KEY);
    if (raw === "bridge" || raw === "ops" || raw === "engineering" || raw === "holodeck" || raw === "honors") return raw;
  } catch { /* storage unavailable */ }
  return "ops";
}

export interface Gathering {
  /** The division (room id) whose crew is called, or "mess" for a break. */
  place: string;
  agentIds: string[];
  untilMs: number;
}

interface ShipState {
  deck: DeckId;
  /** Increments on every deck change, so the captain is placed once per arrival. */
  arrivals: number;
  selection: Selection | null;
  /** The station the captain stands at (or the pointer rests on). */
  nearby: string | null;
  hovered: Selection | null;
  follow: boolean;
  /** Bumped to ask the camera for the overview. */
  overviewSeq: number;
  /** Bumped to glide the camera to `focus`. */
  focus: { at: Vec2; seq: number } | null;
  /** A walk the HUD asked for (walk there). */
  walkTo: { at: Vec2; seq: number } | null;
  /** Put the captain somewhere at once (development checks; a reduced-motion "walk there"). */
  placeAt: { at: Vec2; seq: number } | null;
  destination: DestinationId;
  /** 0..1 while the ship jumps to a new destination. */
  warpingTo: DestinationId | null;
  gathering: Gathering | null;
  captainLook: CaptainLook;
  setCaptainLook: (look: CaptainLook) => void;
  setDeck: (deck: DeckId) => void;
  select: (selection: Selection | null) => void;
  setNearby: (id: string | null) => void;
  hover: (selection: Selection | null) => void;
  setFollow: (follow: boolean) => void;
  overview: () => void;
  focusOn: (at: Vec2) => void;
  requestWalk: (at: Vec2) => void;
  place: (at: Vec2) => void;
  setDestination: (id: DestinationId) => void;
  setWarping: (id: DestinationId | null) => void;
  gather: (g: Gathering | null) => void;
}

export const useShip = create<ShipState>((set, get) => ({
  deck: loadDeck(),
  arrivals: 0,
  selection: null,
  nearby: null,
  hovered: null,
  follow: true,
  overviewSeq: 0,
  focus: null,
  walkTo: null,
  placeAt: null,
  destination: loadDestination(),
  warpingTo: null,
  gathering: null,
  captainLook: loadLook(),
  setCaptainLook: (captainLook) => {
    try { localStorage.setItem(LOOK_KEY, JSON.stringify(captainLook)); } catch { /* storage unavailable */ }
    set({ captainLook });
  },
  setDeck: (deck) => {
    try { localStorage.setItem(DECK_KEY, deck); } catch { /* storage unavailable */ }
    set({ deck, arrivals: get().arrivals + 1, selection: null, nearby: null, hovered: null, gathering: null, follow: true, walkTo: null, placeAt: null, focus: null });
  },
  select: (selection) => set({ selection }),
  setNearby: (nearby) => { if (get().nearby !== nearby) set({ nearby }); },
  hover: (hovered) => {
    const cur = get().hovered;
    if (cur?.kind === hovered?.kind && cur?.id === hovered?.id) return;
    set({ hovered });
  },
  setFollow: (follow) => { if (get().follow !== follow) set({ follow }); },
  overview: () => set({ overviewSeq: get().overviewSeq + 1, follow: false }),
  focusOn: (at) => set({ focus: { at, seq: (get().focus?.seq ?? 0) + 1 }, follow: false }),
  requestWalk: (at) => set({ walkTo: { at, seq: (get().walkTo?.seq ?? 0) + 1 }, follow: true }),
  place: (at) => set({ placeAt: { at, seq: (get().placeAt?.seq ?? 0) + 1 }, follow: true }),
  setDestination: (destination) => { saveDestination(destination); set({ destination }); },
  setWarping: (warpingTo) => set({ warpingTo }),
  gather: (gathering) => set({ gathering }),
}));
