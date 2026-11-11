import { describe, expect, it } from "vitest";
import { PET_STATES } from "@/lib/petStates";
import { jarvisOrbMood } from "./mood";
import { STATE_TARGETS, sameStateTarget, stateChangeKick } from "./states";

describe("jarvisOrbMood", () => {
  it("gives every pet state its own target", () => {
    for (const state of PET_STATES) {
      const mood = jarvisOrbMood(state);
      expect(mood.energy).toBeGreaterThan(0);
      expect(mood).not.toBe(jarvisOrbMood(state === "idle" ? "sleeping" : "idle"));
    }
  });

  it("keeps idle at the resting target, and a repeat of it does not kick like thinking", () => {
    const idle = jarvisOrbMood("idle");
    expect(idle).toBe(STATE_TARGETS.idle);
    expect(idle.energy).toBeLessThan(jarvisOrbMood("listening").energy);
    expect(idle.energy).toBeLessThan(jarvisOrbMood("working").energy);
    expect(idle.rotationSpeed).toBeLessThan(jarvisOrbMood("thinking").rotationSpeed);
    expect(sameStateTarget(idle, STATE_TARGETS.idle)).toBe(true);
    expect(sameStateTarget(idle, jarvisOrbMood("working"))).toBe(false);
    expect(stateChangeKick(idle)).toBe(0.2);
    expect(stateChangeKick("idle")).toBe(0.2);
    expect(stateChangeKick("thinking")).toBeGreaterThan(stateChangeKick("idle"));
  });
});
