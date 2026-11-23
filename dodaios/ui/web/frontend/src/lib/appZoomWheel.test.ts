/**
 * Ctrl + wheel steps the whole-app zoom, leaves plain scrolling alone, and
 * yields to surfaces that zoom their own content.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  appZoomWheelIntent,
  installAppZoomWheel,
  OWN_WHEEL_ZOOM_ATTRIBUTE,
  type AppZoomWheelOptions,
} from "./appZoomWheel";

function turn(init: WheelEventInit): WheelEvent {
  return new WheelEvent("wheel", { bubbles: true, cancelable: true, ...init });
}

describe("appZoomWheelIntent", () => {
  const base = { ctrlKey: false, metaKey: false, altKey: false, buttons: 0 };

  it("zooms in when the wheel turns away and out when it turns back", () => {
    expect(appZoomWheelIntent({ ...base, ctrlKey: true, deltaY: -100 })).toBe("in");
    expect(appZoomWheelIntent({ ...base, ctrlKey: true, deltaY: 100 })).toBe("out");
  });

  it("counts the wheel held down like Ctrl", () => {
    expect(appZoomWheelIntent({ ...base, buttons: 4, deltaY: -100 })).toBe("in");
    expect(appZoomWheelIntent({ ...base, buttons: 4, deltaY: 100 })).toBe("out");
  });

  it("leaves plain scrolling, sideways turns, Cmd and AltGr alone", () => {
    expect(appZoomWheelIntent({ ...base, deltaY: 100 })).toBeNull();
    expect(appZoomWheelIntent({ ...base, buttons: 1, deltaY: 100 })).toBeNull();
    expect(appZoomWheelIntent({ ...base, ctrlKey: true, deltaY: 0 })).toBeNull();
    expect(appZoomWheelIntent({ ...base, ctrlKey: true, metaKey: true, deltaY: 100 })).toBeNull();
    expect(appZoomWheelIntent({ ...base, ctrlKey: true, altKey: true, deltaY: 100 })).toBeNull();
  });
});

describe("installAppZoomWheel", () => {
  let steps: string[];
  let options: AppZoomWheelOptions & { on: boolean; zoom: number; claim: boolean };
  let dispose: () => void;
  let page: HTMLDivElement;

  beforeEach(() => {
    steps = [];
    options = {
      on: true,
      zoom: 1,
      claim: true,
      claims: () => options.claim,
      enabled: () => options.on,
      level: () => options.zoom,
      apply: (intent) => steps.push(intent),
    };
    dispose = installAppZoomWheel(window, options);
    page = document.createElement("div");
    document.body.append(page);
  });

  afterEach(() => {
    dispose();
    page.remove();
  });

  it("steps once per mouse notch and cancels the engine's own zoom", () => {
    const notch = turn({ deltaY: -100, ctrlKey: true });
    expect(page.dispatchEvent(notch)).toBe(false);
    page.dispatchEvent(turn({ deltaY: 100, ctrlKey: true }));
    page.dispatchEvent(turn({ deltaY: 100, ctrlKey: true }));
    expect(steps).toEqual(["in", "out", "out"]);
  });

  it("keeps the gesture from reaching the element under the pointer", () => {
    let reached = false;
    page.addEventListener("wheel", () => (reached = true));
    page.dispatchEvent(turn({ deltaY: -100, ctrlKey: true }));
    expect(reached).toBe(false);
  });

  it("leaves plain scrolling untouched", () => {
    let reached = false;
    page.addEventListener("wheel", () => (reached = true));
    const scroll = turn({ deltaY: 100 });
    expect(page.dispatchEvent(scroll)).toBe(true);
    expect(reached).toBe(true);
    expect(steps).toEqual([]);
  });

  it("adds up the small deltas of a pinch before stepping", () => {
    for (let i = 0; i < 3; i += 1) page.dispatchEvent(turn({ deltaY: -10, ctrlKey: true }));
    expect(steps).toEqual([]);
    page.dispatchEvent(turn({ deltaY: -10, ctrlKey: true }));
    expect(steps).toEqual(["in"]);
  });

  it("drops banked travel when the gesture turns around", () => {
    page.dispatchEvent(turn({ deltaY: -30, ctrlKey: true }));
    page.dispatchEvent(turn({ deltaY: 30, ctrlKey: true }));
    expect(steps).toEqual([]);
    page.dispatchEvent(turn({ deltaY: 10, ctrlKey: true }));
    expect(steps).toEqual(["out"]);
  });

  it("measures travel on screen, so a notch still steps when zoomed in far", () => {
    // At 300 % the engine reports a notch as a third of its CSS pixels.
    options.zoom = 3;
    page.dispatchEvent(turn({ deltaY: 100 / 3, ctrlKey: true }));
    expect(steps).toEqual(["out"]);
  });

  it("steps at once for devices that report lines", () => {
    page.dispatchEvent(turn({ deltaY: -1, deltaMode: 1, ctrlKey: true }));
    expect(steps).toEqual(["in"]);
  });

  it("leaves the gesture to a surface that zooms itself, still without the engine's zoom", () => {
    const board = document.createElement("div");
    board.setAttribute(OWN_WHEEL_ZOOM_ATTRIBUTE, "");
    const canvas = document.createElement("canvas");
    board.append(canvas);
    page.append(board);
    let boardSaw = false;
    board.addEventListener("wheel", () => (boardSaw = true));

    const pinch = turn({ deltaY: -100, ctrlKey: true });
    canvas.dispatchEvent(pinch);
    expect(boardSaw).toBe(true);
    expect(pinch.defaultPrevented).toBe(true);
    expect(steps).toEqual([]);
  });

  it("does nothing, and lets nothing else zoom, when zoom is switched off", () => {
    options.on = false;
    const notch = turn({ deltaY: -100, ctrlKey: true });
    page.dispatchEvent(notch);
    expect(notch.defaultPrevented).toBe(true);
    expect(steps).toEqual([]);
  });

  it("leaves the gesture to the engine where the app cannot zoom", () => {
    options.claim = false;
    const notch = turn({ deltaY: -100, ctrlKey: true });
    page.dispatchEvent(notch);
    expect(notch.defaultPrevented).toBe(false);
    expect(steps).toEqual([]);
  });

  it("stops listening once disposed", () => {
    dispose();
    page.dispatchEvent(turn({ deltaY: -100, ctrlKey: true }));
    expect(steps).toEqual([]);
  });
});
