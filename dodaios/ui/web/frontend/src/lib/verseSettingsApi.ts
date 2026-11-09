/**
 * Settings → Game settings: the Verse's in-game settings menu.
 *
 * `GET /api/verse/settings/catalogue` lists every option
 * (`dodaios/verse_host/game_settings.py`), `GET /api/verse/settings` holds the
 * values and `PATCH /api/verse/settings` writes them; a running Verse gets each
 * change as `settings.changed` (bridge-protocol 14).
 */

export type SettingKind = "choice" | "toggle" | "range" | "key";
export type SettingValue = string | number | boolean;
export type Impact = "low" | "medium" | "high";

export interface SettingDef {
  id: string;
  tab: string;
  section: string;
  kind: SettingKind;
  default: SettingValue;
  options?: string[];
  min?: number;
  max?: number;
  step?: number;
  unit?: "%" | "°" | "x";
  /** Where a setting older than the catalogue lives in `settings` ("view.sensitivity", "gore"). */
  path?: string;
  restart?: boolean;
  advanced?: boolean;
  impact?: Impact;
  tags?: string[];
}

export interface Catalogue {
  schema: string;
  tabs: string[];
  preset_groups: string[];
  settings: SettingDef[];
}

export type VerseSettings = Record<string, unknown> & {
  view?: Record<string, unknown>;
  game?: Record<string, SettingValue>;
};

export type SettingsPatch = Record<string, unknown>;

export class VerseSettingsError extends Error {}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const body = (await res.json().catch(() => null)) as unknown;
  if (!res.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : null;
    throw new VerseSettingsError(typeof detail === "string" && detail ? detail : `Request failed (${res.status}).`);
  }
  return body as T;
}

export function fetchCatalogue(): Promise<Catalogue> {
  return request<Catalogue>("/api/verse/settings/catalogue");
}

export async function fetchSettings(): Promise<VerseSettings> {
  return (await request<{ settings: VerseSettings }>("/api/verse/settings")).settings;
}

export async function patchSettings(patch: SettingsPatch): Promise<VerseSettings> {
  const body = await request<{ settings: VerseSettings }>("/api/verse/settings", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(patch),
  });
  return body.settings;
}

/** The current value of one setting, its default when unset. */
export function readValue(settings: VerseSettings | null, def: SettingDef): SettingValue {
  if (!settings) return def.default;
  let raw: unknown;
  if (def.path) {
    const [head, sub] = def.path.split(".", 2);
    raw = sub ? (settings[head] as Record<string, unknown> | undefined)?.[sub] : settings[head];
  } else {
    raw = settings.game?.[def.id];
  }
  return typeof raw === typeof def.default ? (raw as SettingValue) : def.default;
}

/** Adds one value to a patch in the shape `settings.set` takes. */
export function addToPatch(patch: SettingsPatch, def: SettingDef, value: SettingValue): SettingsPatch {
  if (def.path) {
    const [head, sub] = def.path.split(".", 2);
    if (sub) patch[head] = { ...((patch[head] as Record<string, unknown>) ?? {}), [sub]: value };
    else patch[head] = value;
  } else {
    patch.game = { ...((patch.game as Record<string, unknown>) ?? {}), [def.id]: value };
  }
  return patch;
}

/** Writes a patch into a local copy of the settings (optimistic update). */
export function applyPatch(settings: VerseSettings, patch: SettingsPatch): VerseSettings {
  const next: VerseSettings = { ...settings };
  for (const [key, value] of Object.entries(patch)) {
    if ((key === "view" || key === "game") && value && typeof value === "object") {
      next[key] = { ...((settings[key] as Record<string, unknown>) ?? {}), ...(value as Record<string, unknown>) } as never;
    } else {
      next[key] = value;
    }
  }
  return next;
}

// ------------------------------------------------------------------ keys

const CODE_TO_KEY: Record<string, string> = {
  Space: "SpaceBar",
  ShiftLeft: "LeftShift",
  ShiftRight: "RightShift",
  ControlLeft: "LeftControl",
  ControlRight: "RightControl",
  AltLeft: "LeftAlt",
  AltRight: "RightAlt",
  MetaLeft: "LeftCommand",
  MetaRight: "RightCommand",
  Tab: "Tab",
  Enter: "Enter",
  NumpadEnter: "Enter",
  Backspace: "BackSpace",
  CapsLock: "CapsLock",
  Backquote: "Tilde",
  Minus: "Hyphen",
  Equal: "Equals",
  BracketLeft: "LeftBracket",
  BracketRight: "RightBracket",
  Backslash: "Backslash",
  Semicolon: "Semicolon",
  Quote: "Apostrophe",
  Comma: "Comma",
  Period: "Period",
  Slash: "Slash",
  ArrowUp: "Up",
  ArrowDown: "Down",
  ArrowLeft: "Left",
  ArrowRight: "Right",
  Insert: "Insert",
  Delete: "Delete",
  Home: "Home",
  End: "End",
  PageUp: "PageUp",
  PageDown: "PageDown",
  Escape: "Escape",
};
const DIGITS = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"];
const MOUSE = ["LeftMouseButton", "MiddleMouseButton", "RightMouseButton", "ThumbMouseButton", "ThumbMouseButton2"];

/** A KeyboardEvent.code as an Unreal key name; null for keys Unreal has no name for here. */
export function keyFromCode(code: string): string | null {
  if (CODE_TO_KEY[code]) return CODE_TO_KEY[code];
  let m = /^Key([A-Z])$/.exec(code);
  if (m) return m[1];
  m = /^Digit([0-9])$/.exec(code);
  if (m) return DIGITS[Number(m[1])];
  m = /^Numpad([0-9])$/.exec(code);
  if (m) return `NumPad${DIGITS[Number(m[1])]}`;
  m = /^F([1-9]|1[0-2])$/.exec(code);
  if (m) return code;
  return null;
}

export function keyFromMouse(button: number): string | null {
  return MOUSE[button] ?? null;
}

export const RESERVED_KEYS = new Set(["Escape", "LeftCommand", "RightCommand", "LeftWindows", "RightWindows"]);

const KEY_LABELS: Record<string, string> = {
  SpaceBar: "Space",
  LeftShift: "L-Shift",
  RightShift: "R-Shift",
  LeftControl: "L-Ctrl",
  RightControl: "R-Ctrl",
  LeftAlt: "L-Alt",
  RightAlt: "R-Alt",
  BackSpace: "Backspace",
  Tilde: "`",
  Hyphen: "-",
  Equals: "=",
  LeftBracket: "[",
  RightBracket: "]",
  Backslash: "\\",
  Semicolon: ";",
  Apostrophe: "'",
  Comma: ",",
  Period: ".",
  Slash: "/",
  Up: "↑",
  Down: "↓",
  Left: "←",
  Right: "→",
  LeftMouseButton: "Mouse 1",
  RightMouseButton: "Mouse 2",
  MiddleMouseButton: "Mouse 3",
  ThumbMouseButton: "Mouse 4",
  ThumbMouseButton2: "Mouse 5",
};

/** How a key name reads on a keycap. */
export function keyLabel(key: string): string {
  if (KEY_LABELS[key]) return KEY_LABELS[key];
  const digit = DIGITS.indexOf(key);
  if (digit >= 0) return String(digit);
  const pad = /^NumPad(\w+)$/.exec(key);
  if (pad && DIGITS.includes(pad[1])) return `Num ${DIGITS.indexOf(pad[1])}`;
  return key;
}

/** A value as the menu shows it next to its control. */
export function formatValue(def: SettingDef, value: SettingValue): string {
  if (def.kind !== "range" || typeof value !== "number") return String(value);
  if (def.unit === "%") {
    // 0..1 ranges are shares; 0..100 ranges already are percent.
    const pct = (def.max ?? 1) <= 2 ? value * 100 : value;
    return `${Math.round(pct)}%`;
  }
  if (def.unit === "°") return `${Math.round(value)}°`;
  if (def.unit === "x") return value.toFixed(2);
  return Number.isInteger(def.step ?? 1) ? String(Math.round(value)) : value.toFixed(2);
}
