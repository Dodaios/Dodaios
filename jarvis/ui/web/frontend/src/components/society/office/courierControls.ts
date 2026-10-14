/**
 * The courier's controls: the actions a pilot has, their default keys, the
 * pilot's own rebinding (kept in this browser), and how held keys and a
 * gamepad become one FlightInput. Pure and tested.
 */
import type { FlightInput } from "./courierFlight";

export const FLIGHT_ACTIONS = [
  "throttleUp", "throttleDown", "pitchUp", "pitchDown", "yawLeft", "yawRight", "rollLeft", "rollRight",
  "liftUp", "liftDown", "boost", "brake", "assist", "camera", "land", "exit", "help",
] as const;
export type FlightAction = (typeof FLIGHT_ACTIONS)[number];

/** Continuous actions are read while held; the rest fire once per press. */
export const PRESS_ACTIONS: ReadonlySet<FlightAction> = new Set(["assist", "camera", "land", "exit", "help"]);

export type FlightBindings = Record<FlightAction, string[]>;

export const DEFAULT_BINDINGS: FlightBindings = {
  throttleUp: ["KeyW"], throttleDown: ["KeyS"],
  pitchUp: ["ArrowDown"], pitchDown: ["ArrowUp"],
  yawLeft: ["KeyA"], yawRight: ["KeyD"],
  rollLeft: ["KeyQ", "ArrowLeft"], rollRight: ["KeyE", "ArrowRight"],
  liftUp: ["Space"], liftDown: ["KeyC", "ControlLeft"],
  boost: ["ShiftLeft", "ShiftRight"], brake: ["KeyX"],
  assist: ["KeyT"], camera: ["KeyV"], land: ["KeyL"], exit: ["KeyF"], help: ["KeyH"],
};

const STORAGE_KEY = "dodaios.verse.courier.bindings";

/** The pilot's bindings: the defaults with whatever this browser remembers laid over them. */
export function loadBindings(storage: Pick<Storage, "getItem"> | null = safeStorage()): FlightBindings {
  const out: FlightBindings = { ...DEFAULT_BINDINGS };
  try {
    const raw = storage?.getItem(STORAGE_KEY);
    if (!raw) return out;
    const saved = JSON.parse(raw) as Partial<Record<string, unknown>>;
    for (const action of FLIGHT_ACTIONS) {
      const keys = saved[action];
      if (Array.isArray(keys) && keys.every((k) => typeof k === "string")) out[action] = keys as string[];
    }
  } catch (error) {
    // A corrupt entry falls back to the defaults; the pilot can rebind again.
    console.warn("courier bindings unreadable, using the defaults", error);
  }
  return out;
}

export function saveBindings(bindings: FlightBindings, storage: Pick<Storage, "setItem"> | null = safeStorage()): void {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify(bindings));
  } catch (error) {
    // Private windows and blocked storage keep the binding for this visit only.
    console.warn("courier bindings not saved", error);
  }
}

function safeStorage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null; // Storage access itself can throw where site data is blocked; then nothing is remembered.
  }
}

/** Bind `code` to `action` alone: it leaves every other action it was on, and replaces the action's keys. */
export function rebind(bindings: FlightBindings, action: FlightAction, code: string): FlightBindings {
  const out = {} as FlightBindings;
  for (const a of FLIGHT_ACTIONS) out[a] = bindings[a].filter((k) => k !== code);
  out[action] = [code];
  return out;
}

/** A key code as a pilot reads it ("KeyW" → "W", "ArrowUp" → "↑", "ShiftLeft" → "Shift"). */
export function keyLabel(code: string): string {
  if (code.startsWith("Key")) return code.slice(3);
  if (code.startsWith("Digit")) return code.slice(5);
  const named: Record<string, string> = {
    ArrowUp: "↑", ArrowDown: "↓", ArrowLeft: "←", ArrowRight: "→", Space: "Space",
    ShiftLeft: "Shift", ShiftRight: "Shift", ControlLeft: "Ctrl", ControlRight: "Ctrl", AltLeft: "Alt", AltRight: "Alt",
  };
  return named[code] ?? code;
}

/** The subset of a Gamepad this module reads (standard mapping). */
export interface PadState { axes: readonly number[]; buttons: readonly { value: number; pressed: boolean }[] }

const DEAD_ZONE = 0.15;
function stick(v: number | undefined): number {
  const x = v ?? 0;
  return Math.abs(x) < DEAD_ZONE ? 0 : (x - Math.sign(x) * DEAD_ZONE) / (1 - DEAD_ZONE);
}

/**
 * One FlightInput from the held keys and an optional gamepad: left stick pitch and yaw, right stick roll and
 * lift, the triggers the throttle, A boost, B brake. Keys and pad add up and are clamped.
 */
export function flightInput(held: ReadonlySet<string>, bindings: FlightBindings, pad: PadState | null, invertPitch: boolean): FlightInput {
  const on = (action: FlightAction) => (bindings[action].some((k) => held.has(k)) ? 1 : 0);
  const axis = (plus: FlightAction, minus: FlightAction) => on(plus) - on(minus);
  const b = (i: number) => pad?.buttons[i]?.value ?? 0;
  const clamp = (v: number) => Math.max(-1, Math.min(1, v));
  const pitch = clamp(axis("pitchUp", "pitchDown") + stick(pad?.axes[1]));
  return {
    throttle: clamp(axis("throttleUp", "throttleDown") + b(7) - b(6)),
    pitch: invertPitch ? -pitch : pitch,
    yaw: clamp(axis("yawRight", "yawLeft") + stick(pad?.axes[0])),
    roll: clamp(axis("rollRight", "rollLeft") + stick(pad?.axes[2])),
    lift: clamp(axis("liftUp", "liftDown") - stick(pad?.axes[3])),
    boost: on("boost") === 1 || (pad?.buttons[0]?.pressed ?? false),
    brake: on("brake") === 1 || (pad?.buttons[1]?.pressed ?? false),
  };
}

/** Gamepad buttons that fire a press action: X lands, Y switches the camera, Back the assist, Start leaves the ship. */
export const PAD_PRESSES: readonly [number, FlightAction][] = [[2, "land"], [3, "camera"], [8, "assist"], [9, "exit"]];
