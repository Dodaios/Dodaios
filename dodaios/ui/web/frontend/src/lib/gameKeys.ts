/**
 * Key names for game keybinds, in the words games print in their menus
 * ("Left Shift", "Mouse 4", "Space") rather than browser codes.
 */

const CODE_NAMES: Record<string, string> = {
  Space: "Space",
  ShiftLeft: "Left Shift",
  ShiftRight: "Right Shift",
  ControlLeft: "Left Ctrl",
  ControlRight: "Right Ctrl",
  AltLeft: "Left Alt",
  AltRight: "Right Alt",
  MetaLeft: "Left Win",
  MetaRight: "Right Win",
  CapsLock: "Caps Lock",
  Tab: "Tab",
  Enter: "Enter",
  Backspace: "Backspace",
  Delete: "Delete",
  Insert: "Insert",
  Home: "Home",
  End: "End",
  PageUp: "Page Up",
  PageDown: "Page Down",
  ArrowUp: "Up Arrow",
  ArrowDown: "Down Arrow",
  ArrowLeft: "Left Arrow",
  ArrowRight: "Right Arrow",
  Backquote: "`",
  Minus: "-",
  Equal: "=",
  BracketLeft: "[",
  BracketRight: "]",
  Backslash: "\\",
  Semicolon: ";",
  Quote: "'",
  Comma: ",",
  Period: ".",
  Slash: "/",
  IntlBackslash: "<",
  NumpadAdd: "Numpad +",
  NumpadSubtract: "Numpad -",
  NumpadMultiply: "Numpad *",
  NumpadDivide: "Numpad /",
  NumpadDecimal: "Numpad .",
  NumpadEnter: "Numpad Enter",
};

/** The game-style name of a pressed key, or null for keys we cannot name. */
export function keyNameFromCode(code: string): string | null {
  if (CODE_NAMES[code]) return CODE_NAMES[code];
  let m = /^Key([A-Z])$/.exec(code);
  if (m) return m[1];
  m = /^Digit([0-9])$/.exec(code);
  if (m) return m[1];
  m = /^Numpad([0-9])$/.exec(code);
  if (m) return `Numpad ${m[1]}`;
  m = /^F([0-9]{1,2})$/.exec(code);
  if (m) return `F${m[1]}`;
  return null;
}

const MOUSE_NAMES = ["Left Mouse", "Middle Mouse", "Right Mouse", "Mouse 4", "Mouse 5"];

/** `MouseEvent.button` → game-style name. */
export function mouseButtonName(button: number): string | null {
  return MOUSE_NAMES[button] ?? null;
}

export function wheelName(deltaY: number): string {
  return deltaY < 0 ? "Mouse Wheel Up" : "Mouse Wheel Down";
}

/**
 * Which actions share a key with another action: action id → the other
 * actions' labels. Unbound actions never conflict.
 */
export function keyConflicts(
  binds: readonly { id: string; action: string; key: string }[],
): Map<string, string[]> {
  const byKey = new Map<string, { id: string; action: string }[]>();
  for (const bind of binds) {
    const key = bind.key.trim().toLowerCase();
    if (!key) continue;
    byKey.set(key, [...(byKey.get(key) ?? []), bind]);
  }
  const out = new Map<string, string[]>();
  for (const group of byKey.values()) {
    if (group.length < 2) continue;
    for (const bind of group) {
      out.set(bind.id, group.filter((other) => other.id !== bind.id).map((other) => other.action));
    }
  }
  return out;
}
