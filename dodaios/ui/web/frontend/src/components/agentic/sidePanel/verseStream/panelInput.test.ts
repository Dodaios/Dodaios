import { describe, expect, it } from "vitest";
import {
  ALLOWED_KEY_CODES,
  encodeKey,
  encodeMouseButton,
  encodeMouseMove,
  encodeWheel,
  isAllowedMessage,
  keyCodeFor,
  MESSAGE,
  quantizeSigned,
  quantizeUnsigned,
} from "./panelInput";

describe("panel input (WP20.4)", () => {
  it("encodes only walking and view keys", () => {
    expect(Array.from(encodeKey(true, "KeyW") ?? [])).toEqual([MESSAGE.KeyDown, 87, 0]);
    expect(Array.from(encodeKey(true, "ArrowUp", true) ?? [])).toEqual([MESSAGE.KeyDown, 38, 1]);
    expect(Array.from(encodeKey(false, "KeyD") ?? [])).toEqual([MESSAGE.KeyUp, 68]);
    for (const duelKey of ["Space", "KeyR", "KeyF", "ShiftLeft", "ControlLeft", "KeyC", "KeyZ", "Escape", "F10", "Digit1", "KeyG", "Tab"]) {
      expect(encodeKey(true, duelKey)).toBeNull();
    }
    expect([...ALLOWED_KEY_CODES].sort((a, b) => a - b)).toEqual([37, 38, 39, 40, 65, 68, 69, 81, 83, 86, 87]);
    expect(keyCodeFor("toString")).toBeNull();
  });

  it("quantizes like the plugin's frontend", () => {
    expect(quantizeUnsigned(0)).toBe(0);
    expect(quantizeUnsigned(1)).toBe(65535);
    expect(quantizeUnsigned(2)).toBe(65535);
    expect(quantizeUnsigned(-1)).toBe(0);
    expect(quantizeSigned(-1)).toBe(-32767);
    expect(quantizeSigned(0.5)).toBe(16384);
  });

  it("lays out mouse messages little-endian", () => {
    const move = encodeMouseMove({ x: 0.5, y: 0.25 }, { dx: 48, dy: -32 }, { width: 480, height: 320 });
    const view = new DataView(move.buffer);
    expect(move.length).toBe(9);
    expect(view.getUint8(0)).toBe(MESSAGE.MouseMove);
    expect(view.getUint16(1, true)).toBe(32768);
    expect(view.getUint16(3, true)).toBe(16384);
    expect(view.getInt16(5, true)).toBe(3277);
    expect(view.getInt16(7, true)).toBe(-3277);

    const down = encodeMouseButton(true, 2, { x: 1, y: 0 });
    expect(Array.from(down ?? [])).toEqual([MESSAGE.MouseDown, 2, 255, 255, 0, 0]);
    expect(encodeMouseButton(true, 3, { x: 0, y: 0 })).toBeNull();
    expect(encodeMouseButton(true, 4, { x: 0, y: 0 })).toBeNull();

    const wheel = encodeWheel(-120, { x: 0, y: 0 });
    expect(new DataView(wheel.buffer).getInt16(1, true)).toBe(120);
    expect(wheel.length).toBe(7);
  });

  it("checks every message before it leaves", () => {
    expect(isAllowedMessage(new Uint8Array([MESSAGE.KeyDown, 87, 0]))).toBe(true);
    expect(isAllowedMessage(new Uint8Array([MESSAGE.KeyDown, 32, 0]))).toBe(false);
    expect(isAllowedMessage(new Uint8Array([MESSAGE.KeyDown, 87]))).toBe(false);
    expect(isAllowedMessage(new Uint8Array([51, 1, 0]))).toBe(false); // console command
    expect(isAllowedMessage(new Uint8Array([50, 1, 0]))).toBe(false); // UI interaction
    expect(isAllowedMessage(new Uint8Array([5]))).toBe(false); // stop streaming
    expect(isAllowedMessage(new Uint8Array([90, 0, 0, 0]))).toBe(false); // gamepad
    expect(isAllowedMessage(new Uint8Array([MESSAGE.MouseDown, 3, 0, 0, 0, 0]))).toBe(false);
    expect(isAllowedMessage(new Uint8Array([MESSAGE.IFrameRequest]))).toBe(true);
    expect(isAllowedMessage(new Uint8Array([]))).toBe(false);
  });
});
