/**
 * From a control state (what the keys, mouse or a bot want right now) to the
 * quantised InputCommand the simulation and the wire both use.
 */
import { clamp, q, wrapAngle } from "./math";
import { BTN, type InputCommand } from "./types";

/** Aim is sent to 1/10000 rad, movement to 1/127. */
export const AIM_SCALE = 10000;
export const MOVE_SCALE = 127;
export const PITCH_LIMIT = 1.2;

/** What a player wants this tick, in plain terms. */
export interface ControlState {
  /** Strafe right and forward, -1..1, in the aim frame (WASD). */
  moveX: number;
  moveY: number;
  /** Absolute aim, radians (0 faces +Z, positive pitch looks up). */
  yaw: number;
  pitch: number;
  fire: boolean;
  ads: boolean;
  shield: boolean;
  sprint: boolean;
  /** Presses: true for one command (the client latches them between ticks). */
  dodge: boolean;
  vent: boolean;
  forfeit: boolean;
}

export function idleControl(yaw = 0, pitch = 0): ControlState {
  return { moveX: 0, moveY: 0, yaw, pitch, fire: false, ads: false, shield: false, sprint: false, dodge: false, vent: false, forfeit: false };
}

export function buttonsOf(c: ControlState): number {
  return (c.fire ? BTN.FIRE : 0) | (c.ads ? BTN.ADS : 0) | (c.shield ? BTN.SHIELD : 0) | (c.dodge ? BTN.DODGE : 0)
    | (c.vent ? BTN.VENT : 0) | (c.sprint ? BTN.SPRINT : 0) | (c.forfeit ? BTN.FORFEIT : 0);
}

/** Every button bit an input may carry. */
const ALL_BUTTONS = BTN.FIRE | BTN.ADS | BTN.SHIELD | BTN.DODGE | BTN.VENT | BTN.SPRINT | BTN.FORFEIT;

const finite = (v: unknown, fallback: number): number => (typeof v === "number" && Number.isFinite(v) ? v : fallback);

/**
 * The move stick on the wire grid, never longer than 1 (a diagonal is not
 * faster): components are rounded, and if that pushed the length past 1 they
 * are rounded toward zero instead.
 */
function quantMove(mx: number, my: number): [number, number] {
  mx = clamp(mx, -1, 1);
  my = clamp(my, -1, 1);
  const len = Math.hypot(mx, my);
  if (len > 1) { mx /= len; my /= len; }
  let qx = Math.round(mx * MOVE_SCALE);
  let qy = Math.round(my * MOVE_SCALE);
  if (qx * qx + qy * qy > MOVE_SCALE * MOVE_SCALE) { qx = Math.trunc(mx * MOVE_SCALE); qy = Math.trunc(my * MOVE_SCALE); }
  return [qx / MOVE_SCALE + 0, qy / MOVE_SCALE + 0];
}

export function makeInput(seq: number, c: ControlState, viewTick = -1): InputCommand {
  const [mx, my] = quantMove(c.moveX, c.moveY);
  return {
    seq,
    mx,
    my,
    yaw: q(wrapAngle(c.yaw), AIM_SCALE),
    pitch: q(clamp(c.pitch, -PITCH_LIMIT, PITCH_LIMIT), AIM_SCALE),
    buttons: buttonsOf(c),
    viewTick,
  };
}

/**
 * An input as the server may trust it: whatever arrived over the wire (a
 * modified client, a broken encoder) becomes a legal command on the same grid
 * `makeInput` produces. Legal commands come out unchanged, so client
 * prediction and the server still agree. Non-numbers become 0 (aim: the
 * previous aim), the move stick is clamped to length 1, unknown button bits
 * are dropped.
 */
export function sanitizeInput(c: InputCommand, prevYaw = 0, prevPitch = 0): InputCommand {
  const [mx, my] = quantMove(finite(c.mx, 0), finite(c.my, 0));
  const yaw = finite(c.yaw, prevYaw);
  return {
    seq: Math.trunc(finite(c.seq, -1)),
    mx,
    my,
    // +-3.1416 (the grid's ends, just past +-PI) are legal as they are.
    yaw: q(Math.abs(yaw) <= Math.PI + 1e-3 ? yaw : wrapAngle(yaw), AIM_SCALE),
    pitch: q(clamp(finite(c.pitch, prevPitch), -PITCH_LIMIT, PITCH_LIMIT), AIM_SCALE),
    buttons: Math.trunc(finite(c.buttons, 0)) & ALL_BUTTONS,
    viewTick: Math.max(-1, Math.trunc(finite(c.viewTick, -1))),
  };
}
