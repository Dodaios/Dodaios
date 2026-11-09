/**
 * Input the side panel may send to the Verse over the Pixel Streaming data channel (WP20.4).
 *
 * The panel is overview and walking only: W A S D, the arrow keys, Q and E to turn, V for the
 * view, and the mouse (move while a button is held, the three main buttons, the wheel). The duel
 * never runs in the panel, so nothing that fires, reloads, jumps, sprints, interacts or opens a
 * menu is ever encoded. `VerseStreamInputPolicy` in the Unreal module applies the same table.
 *
 * Layouts follow the plugin's default ToStreamer protocol (PixelStreaming2Input,
 * DefaultDataProtocol): one id byte, then little-endian fields.
 */

export const MESSAGE = {
  IFrameRequest: 0,
  KeyDown: 60,
  KeyUp: 61,
  MouseEnter: 70,
  MouseLeave: 71,
  MouseDown: 72,
  MouseUp: 73,
  MouseMove: 74,
  MouseWheel: 75,
} as const;

/** `KeyboardEvent.code` to the browser key code the plugin expects, for the allowed keys only. */
const KEY_CODES: Readonly<Record<string, number>> = {
  KeyW: 87,
  KeyA: 65,
  KeyS: 83,
  KeyD: 68,
  ArrowLeft: 37,
  ArrowUp: 38,
  ArrowRight: 39,
  ArrowDown: 40,
  KeyQ: 81,
  KeyE: 69,
  KeyV: 86,
};

export const ALLOWED_KEY_CODES: ReadonlySet<number> = new Set(Object.values(KEY_CODES));

export function keyCodeFor(code: string): number | null {
  return Object.prototype.hasOwnProperty.call(KEY_CODES, code) ? KEY_CODES[code] : null;
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

/** 0..1 to the plugin's unsigned 16-bit coordinate. */
export function quantizeUnsigned(fraction: number): number {
  return clamp(Math.round(fraction * 65535), 0, 65535);
}

/** -1..1 to the plugin's signed 16-bit delta. */
export function quantizeSigned(fraction: number): number {
  return clamp(Math.round(fraction * 32767), -32767, 32767);
}

export function encodeKey(down: boolean, code: string, repeat = false): Uint8Array | null {
  const keyCode = keyCodeFor(code);
  if (keyCode === null) return null;
  return down ? new Uint8Array([MESSAGE.KeyDown, keyCode, repeat ? 1 : 0]) : new Uint8Array([MESSAGE.KeyUp, keyCode]);
}

export interface PanelRect {
  width: number;
  height: number;
}

/** Pointer position inside the panel, both 0..1. */
export interface PanelPoint {
  x: number;
  y: number;
}

export function encodeMouseMove(point: PanelPoint, deltaPx: { dx: number; dy: number }, rect: PanelRect): Uint8Array {
  const out = new DataView(new ArrayBuffer(9));
  out.setUint8(0, MESSAGE.MouseMove);
  out.setUint16(1, quantizeUnsigned(point.x), true);
  out.setUint16(3, quantizeUnsigned(point.y), true);
  out.setInt16(5, quantizeSigned(rect.width > 0 ? deltaPx.dx / rect.width : 0), true);
  out.setInt16(7, quantizeSigned(rect.height > 0 ? deltaPx.dy / rect.height : 0), true);
  return new Uint8Array(out.buffer);
}

/** Main (0), middle (1) and secondary (2) buttons only. */
export function encodeMouseButton(down: boolean, button: number, point: PanelPoint): Uint8Array | null {
  if (!Number.isInteger(button) || button < 0 || button > 2) return null;
  const out = new DataView(new ArrayBuffer(6));
  out.setUint8(0, down ? MESSAGE.MouseDown : MESSAGE.MouseUp);
  out.setUint8(1, button);
  out.setUint16(2, quantizeUnsigned(point.x), true);
  out.setUint16(4, quantizeUnsigned(point.y), true);
  return new Uint8Array(out.buffer);
}

export function encodeWheel(deltaY: number, point: PanelPoint): Uint8Array {
  const out = new DataView(new ArrayBuffer(7));
  out.setUint8(0, MESSAGE.MouseWheel);
  out.setInt16(1, clamp(Math.round(-deltaY), -32767, 32767), true);
  out.setUint16(3, quantizeUnsigned(point.x), true);
  out.setUint16(5, quantizeUnsigned(point.y), true);
  return new Uint8Array(out.buffer);
}

export function encodeSimple(id: typeof MESSAGE.IFrameRequest | typeof MESSAGE.MouseEnter | typeof MESSAGE.MouseLeave): Uint8Array {
  return new Uint8Array([id]);
}

const PAYLOAD: Readonly<Record<number, number>> = {
  [MESSAGE.IFrameRequest]: 0,
  [MESSAGE.MouseEnter]: 0,
  [MESSAGE.MouseLeave]: 0,
  [MESSAGE.KeyDown]: 2,
  [MESSAGE.KeyUp]: 1,
  [MESSAGE.MouseDown]: 5,
  [MESSAGE.MouseUp]: 5,
  [MESSAGE.MouseMove]: 8,
  [MESSAGE.MouseWheel]: 6,
};

/** The last check before a message leaves: same rules as the Unreal side. */
export function isAllowedMessage(message: Uint8Array): boolean {
  if (message.length === 0) return false;
  const id = message[0];
  const size = PAYLOAD[id];
  if (size === undefined || message.length !== 1 + size) return false;
  if (id === MESSAGE.KeyDown || id === MESSAGE.KeyUp) return ALLOWED_KEY_CODES.has(message[1]);
  if (id === MESSAGE.MouseDown || id === MESSAGE.MouseUp) return message[1] <= 2;
  return true;
}
