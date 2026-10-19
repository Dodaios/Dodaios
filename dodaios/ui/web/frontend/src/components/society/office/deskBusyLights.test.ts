import { describe, expect, it } from "vitest";
import { Color } from "three";

import { busyColour } from "./DeskBusyLights";
import { CODING_SCENE } from "./officePalette";

describe("desk busy lights", () => {
  it("shows the pane's state: green at work, grey idle, red failed", () => {
    const out = new Color();
    expect(busyColour("working", 0, out).getHexString()).toBe(new Color(CODING_SCENE.busy.working).getHexString());
    expect(busyColour("idle", 3, out).getHexString()).toBe(new Color(CODING_SCENE.busy.idle).getHexString());
    const failed = busyColour("error", 0, out);
    expect(failed.r).toBeGreaterThan(failed.g * 2);
  });

  it("blinks while the pane waits for the person, lit at the still frame", () => {
    const on = busyColour("waiting", 0.1, new Color());
    const off = busyColour("waiting", 0.7, new Color());
    expect(on.r).toBeGreaterThan(off.r * 3);
  });
});
