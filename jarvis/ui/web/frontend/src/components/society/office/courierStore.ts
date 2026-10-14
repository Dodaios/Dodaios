/**
 * The courier's session: whether the person is flying it, the pilot's choices
 * (camera, assist, pitch, sound, key bindings) and what the HUD shows. The
 * choices are per viewer and kept in this browser; the flight itself lives in
 * the scene (SkyCourier.tsx) and publishes a telemetry snapshot a few times a
 * second for the HUD.
 */
import { create } from "zustand";
import { loadBindings, saveBindings, type FlightBindings } from "./courierControls";
import type { AutopilotPhase, FlightAssist } from "./courierFlight";

export type CourierView = "chase" | "cockpit";

export interface CourierTelemetry {
  speed: number;
  throttle: number;
  charge: number;
  /** Metres over the pad's deck while above it, else over the street level. */
  altitude: number;
  overPad: boolean;
  landed: boolean;
  autopilot: AutopilotPhase | null;
  /** Near enough the pad for the landing assist. */
  canLand: boolean;
}

const PREFS_KEY = "dodaios.verse.courier.prefs";

interface CourierPrefs { view: CourierView; assist: FlightAssist; invertPitch: boolean; volume: number }

const DEFAULT_PREFS: CourierPrefs = { view: "chase", assist: "arcade", invertPitch: false, volume: 0.6 };

function loadPrefs(): CourierPrefs {
  try {
    const raw = typeof window !== "undefined" ? window.localStorage.getItem(PREFS_KEY) : null;
    if (!raw) return DEFAULT_PREFS;
    const saved = JSON.parse(raw) as Partial<CourierPrefs>;
    return {
      view: saved.view === "cockpit" ? "cockpit" : "chase",
      assist: saved.assist === "simulation" ? "simulation" : "arcade",
      invertPitch: saved.invertPitch === true,
      volume: typeof saved.volume === "number" ? Math.min(1, Math.max(0, saved.volume)) : DEFAULT_PREFS.volume,
    };
  } catch (error) {
    console.warn("courier preferences unreadable, using the defaults", error);
    return DEFAULT_PREFS;
  }
}

function savePrefs(prefs: CourierPrefs) {
  try {
    window.localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch (error) {
    // Blocked storage keeps the choice for this visit only.
    console.warn("courier preferences not saved", error);
  }
}

interface CourierState extends CourierPrefs {
  flying: boolean;
  /** The ship stands loaded on its pad; boarding waits for it. */
  ready: boolean;
  bindings: FlightBindings;
  helpOpen: boolean;
  settingsOpen: boolean;
  /** The mouse is captured for steering. */
  mouseLocked: boolean;
  telemetry: CourierTelemetry;
  /** Bumped when the pilot asks for the landing assist, or to step out, from the HUD (the keys act in the scene). */
  landRequest: number;
  exitRequest: number;
  board: () => void;
  disembark: () => void;
  setPrefs: (patch: Partial<CourierPrefs>) => void;
  setBindings: (bindings: FlightBindings) => void;
  set: (patch: Partial<Pick<CourierState, "helpOpen" | "settingsOpen" | "telemetry" | "mouseLocked">>) => void;
  requestLanding: () => void;
  requestExit: () => void;
  setReady: (ready: boolean) => void;
}

const IDLE: CourierTelemetry = { speed: 0, throttle: 0, charge: 1, altitude: 0, overPad: true, landed: true, autopilot: null, canLand: false };

export const useCourier = create<CourierState>((set, get) => ({
  ...loadPrefs(),
  flying: false,
  ready: false,
  bindings: loadBindings(),
  helpOpen: false,
  settingsOpen: false,
  mouseLocked: false,
  telemetry: IDLE,
  landRequest: 0,
  exitRequest: 0,
  board: () => {
    if (!get().ready) return;
    courierSession.flying = true;
    set({ flying: true, telemetry: IDLE });
  },
  disembark: () => { courierSession.flying = false; set({ flying: false, settingsOpen: false, helpOpen: false, telemetry: IDLE }); },
  setPrefs: (patch) => {
    set(patch);
    const { view, assist, invertPitch, volume } = get();
    savePrefs({ view, assist, invertPitch, volume });
  },
  setBindings: (bindings) => { saveBindings(bindings); set({ bindings }); },
  set: (patch) => set(patch),
  requestLanding: () => set((s) => ({ landRequest: s.landRequest + 1 })),
  requestExit: () => set((s) => ({ exitRequest: s.exitRequest + 1 })),
  setReady: (ready) => set({ ready }),
}));

/** Read every frame by the camera rig and the character: no subscription, no render. */
export const courierSession = { flying: false };
