import { describe, expect, it } from "vitest";

import {
  bindUsesKey,
  comboName,
  comboParts,
  keyConflicts,
  keyNameFromCode,
  mouseButtonName,
  wheelName,
} from "@/lib/gameKeys";

describe("game key names", () => {
  it("names keys the way game menus print them", () => {
    expect(keyNameFromCode("KeyW")).toBe("W");
    expect(keyNameFromCode("Digit4")).toBe("4");
    expect(keyNameFromCode("ShiftLeft")).toBe("Left Shift");
    expect(keyNameFromCode("ControlLeft")).toBe("Left Ctrl");
    expect(keyNameFromCode("Space")).toBe("Space");
    expect(keyNameFromCode("F12")).toBe("F12");
    expect(keyNameFromCode("Numpad5")).toBe("Numpad 5");
    expect(keyNameFromCode("Unidentified")).toBeNull();
  });

  it("names mouse buttons and the wheel", () => {
    expect(mouseButtonName(0)).toBe("Left Mouse");
    expect(mouseButtonName(3)).toBe("Mouse 4");
    expect(mouseButtonName(9)).toBeNull();
    expect(wheelName(-1)).toBe("Mouse Wheel Up");
    expect(wheelName(1)).toBe("Mouse Wheel Down");
  });
});

describe("keyConflicts", () => {
  it("flags actions sharing a key, case-insensitively, and ignores unbound ones", () => {
    const conflicts = keyConflicts([
      { id: "jump", action: "Jump", key: "Space" },
      { id: "vault", action: "Vault", key: "space" },
      { id: "crouch", action: "Crouch", key: "C" },
      { id: "a", action: "A", key: "" },
      { id: "b", action: "B", key: "" },
    ]);
    expect(conflicts.get("jump")).toEqual(["Vault"]);
    expect(conflicts.get("vault")).toEqual(["Jump"]);
    expect(conflicts.has("crouch")).toBe(false);
    expect(conflicts.has("a")).toBe(false);
  });
});

describe("combinations", () => {
  it("orders modifiers and never repeats the main key as a modifier", () => {
    expect(comboName({ ctrl: true, shift: true, alt: false }, "Mouse 4")).toBe("Ctrl + Shift + Mouse 4");
    expect(comboName({ ctrl: false, shift: true, alt: false }, "Left Shift")).toBe("Left Shift");
    expect(comboName({ ctrl: true, shift: false, alt: false }, "Left Shift")).toBe("Ctrl + Left Shift");
    expect(comboParts("Alt + E")).toEqual(["Alt", "E"]);
  });

  it("matches a physical key inside a combo", () => {
    expect(bindUsesKey("Ctrl + F", "Left Ctrl")).toBe(true);
    expect(bindUsesKey("Ctrl + F", "F")).toBe(true);
    expect(bindUsesKey("Left Shift", "Right Shift")).toBe(false);
    expect(bindUsesKey("", "F")).toBe(false);
  });
});
