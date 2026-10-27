import { describe, expect, it } from "vitest";

import { keyConflicts, keyNameFromCode, mouseButtonName, wheelName } from "@/lib/gameKeys";

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
