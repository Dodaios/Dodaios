/**
 * The courier's controls: the actions a pilot has, their default keys, the
 * pilot's own rebinding (kept in this browser), and how held keys and a
 * gamepad become one FlightInput. Pure and tested.
 */
import { Quaternion, Vector3 } from "three";
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
  pitchUp: ["ArrowUp"], pitchDown: ["ArrowDown"],
  yawLeft: ["KeyA"], yawRight: ["KeyD"],
  rollLeft: ["KeyQ", "ArrowLeft"], rollRight: ["KeyE", "ArrowRight"],
  liftUp: ["Space"], liftDown: ["KeyC", "ControlLeft"],
  boost: ["ShiftLeft", "ShiftRight"], brake: ["KeyX"],
  assist: ["KeyT"], camera: ["KeyV"], land: ["KeyL"], exit: ["KeyF"], help: ["KeyH"],
};

/** Versioned: the first defaults had the arrows the other way round, and a saved copy of them must not survive. */
const STORAGE_KEY = "dodaios.verse.courier.bindings.v2";

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
  // A stick pushed forward (negative y) dives, as in every flight game.
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

/**
 * Mouse aim. With the mouse captured, moving it moves where the pilot aims (a direction in the world, shown as a
 * reticle), and the ship keeps turning towards that aim by itself until its nose is on it, whether or not the
 * mouse is still moving. Yaw 0 looks along -z and grows towards -x; pitch is up from the horizon.
 */
export interface MouseAim { yaw: number; pitch: number }

/** Radians of aim per pixel of mouse movement, and the steepest aim up or down. */
export const AIM_PER_PIXEL = 0.0024;
const AIM_PITCH_LIMIT = 1.4;
/** How hard the ship steers towards the aim: stick per radian of error. */
const AIM_GAIN = 2.6;

export function aimFromForward(forward: Vector3): MouseAim {
  return { yaw: Math.atan2(-forward.x, -forward.z), pitch: Math.asin(Math.max(-1, Math.min(1, forward.y))) };
}

export function aimDirection(aim: MouseAim, out = new Vector3()): Vector3 {
  const c = Math.cos(aim.pitch);
  return out.set(-Math.sin(aim.yaw) * c, Math.sin(aim.pitch), -Math.cos(aim.yaw) * c);
}

/** Move the aim by a mouse movement (pixels, browser axes: +y is down): up aims higher, right aims right. */
export function moveAim(aim: MouseAim, dx: number, dy: number, invertPitch: boolean): MouseAim {
  aim.yaw -= dx * AIM_PER_PIXEL;
  aim.pitch = Math.max(-AIM_PITCH_LIMIT, Math.min(AIM_PITCH_LIMIT, aim.pitch + (invertPitch ? dy : -dy) * AIM_PER_PIXEL));
  return aim;
}

/** Turn rate of the aim with the cursor at the edge of the view, and the still zone around its middle. */
const CURSOR_TURN_RATE = 1.8;
const CURSOR_DEAD_ZONE = 0.08;

/**
 * Cursor steering, for when the view cannot capture the mouse: the cursor's place in the view (-1..1 from the middle,
 * +y up) turns the aim at a rate that grows towards the edge, and keeps turning while the cursor rests there.
 */
export function cursorTurn(aim: MouseAim, x: number, y: number, dt: number): MouseAim {
  const shape = (v: number) => {
    const m = Math.max(0, Math.min(1, (Math.abs(v) - CURSOR_DEAD_ZONE) / (1 - CURSOR_DEAD_ZONE)));
    return Math.sign(v) * m * m;
  };
  aim.yaw -= shape(x) * CURSOR_TURN_RATE * dt;
  aim.pitch = Math.max(-AIM_PITCH_LIMIT, Math.min(AIM_PITCH_LIMIT, aim.pitch + shape(y) * CURSOR_TURN_RATE * dt));
  return aim;
}

const _local = new Vector3();
const _inverse = new Quaternion();

/** The pitch and yaw that turn a ship of orientation q towards direction dir, added to the input. */
export function steerTowards(input: FlightInput, q: Quaternion, dir: Vector3): FlightInput {
  const local = _local.copy(dir).applyQuaternion(_inverse.copy(q).invert());
  const clamp = (v: number) => Math.max(-1, Math.min(1, v));
  input.yaw = clamp(input.yaw + Math.atan2(local.x, -local.z) * AIM_GAIN);
  input.pitch = clamp(input.pitch + Math.atan2(local.y, Math.hypot(local.x, local.z)) * AIM_GAIN);
  return input;
}
