/**
 * The Agents section's three-region frame as plain numbers: the roster on the
 * left, the chat in the middle, the details pane on the right.
 *
 * The person sets two widths and two switches (roster collapsed, pane open);
 * the window decides how much of that fits. `resolveShellLayout` is the one
 * place that decides it, so the order in which regions give way is testable
 * and identical everywhere:
 *
 *   1. the chat keeps at least `CHAT_MIN` pixels,
 *   2. the details pane shrinks to its minimum,
 *   3. then the pane closes,
 *   4. then the roster shrinks to its minimum,
 *   5. then the roster folds to the avatar rail.
 *
 * Only what the person chose is persisted. A pane the window closed comes
 * back by itself once the window is wide enough again.
 */

export const ROSTER_MIN = 240;
export const ROSTER_MAX = 400;
export const ROSTER_DEFAULT = 280;
/** The folded roster: avatars only. */
export const ROSTER_RAIL = 64;
export const PANE_MIN = 280;
export const PANE_MAX = 480;
export const PANE_DEFAULT = 320;
/** The chat never gets narrower than this while anything else can give way. */
export const CHAT_MIN = 424;

const STORAGE_KEY = "society.shell.layout.v1";

export interface ShellPrefs {
  rosterWidth: number;
  rosterCollapsed: boolean;
  paneOpen: boolean;
  paneWidth: number;
}

export const DEFAULT_SHELL_PREFS: ShellPrefs = {
  rosterWidth: ROSTER_DEFAULT,
  rosterCollapsed: false,
  paneOpen: true,
  paneWidth: PANE_DEFAULT,
};

export interface ShellLayout {
  /** Width of the roster column in pixels (the rail width when folded). */
  rosterWidth: number;
  /** "full" shows rows; "rail" shows avatars only. */
  roster: "full" | "rail";
  /** True when the roster is a rail because the window is too narrow, not by choice. */
  rosterForced: boolean;
  /** 0 when the pane is closed. */
  paneWidth: number;
  paneOpen: boolean;
  /** True when the pane is closed because the window is too narrow, not by choice. */
  paneForced: boolean;
  /** What is left for the chat. */
  chatWidth: number;
}

export const clampRoster = (width: number) => Math.round(Math.min(ROSTER_MAX, Math.max(ROSTER_MIN, width)));
export const clampPane = (width: number) => Math.round(Math.min(PANE_MAX, Math.max(PANE_MIN, width)));

/**
 * Fit the person's preferred layout into `available` pixels.
 * `hasPane` is false where no details pane exists (no agent open).
 */
export function resolveShellLayout(available: number, prefs: ShellPrefs, hasPane = true): ShellLayout {
  const total = Math.max(0, Math.floor(available));
  let roster = prefs.rosterCollapsed ? ROSTER_RAIL : clampRoster(prefs.rosterWidth);
  let rosterMode: "full" | "rail" = prefs.rosterCollapsed ? "rail" : "full";
  let pane = hasPane && prefs.paneOpen ? clampPane(prefs.paneWidth) : 0;
  let paneForced = false;
  let rosterForced = false;

  const overflow = () => roster + pane + CHAT_MIN - total;

  // 2. The pane shrinks first ...
  if (pane > 0 && overflow() > 0) pane = Math.max(PANE_MIN, pane - overflow());
  // 3. ... then closes.
  if (pane > 0 && overflow() > 0) {
    pane = 0;
    paneForced = true;
  }
  // 4. The roster shrinks ...
  if (rosterMode === "full" && overflow() > 0) roster = Math.max(ROSTER_MIN, roster - overflow());
  // 5. ... then folds to the rail.
  if (rosterMode === "full" && overflow() > 0) {
    roster = ROSTER_RAIL;
    rosterMode = "rail";
    rosterForced = true;
  }
  return {
    rosterWidth: roster,
    roster: rosterMode,
    rosterForced,
    paneWidth: pane,
    paneOpen: pane > 0,
    paneForced,
    chatWidth: Math.max(0, total - roster - pane),
  };
}

function sanitize(value: unknown): ShellPrefs {
  if (!value || typeof value !== "object") return { ...DEFAULT_SHELL_PREFS };
  const raw = value as Partial<Record<keyof ShellPrefs, unknown>>;
  const num = (input: unknown, fallback: number) => (typeof input === "number" && Number.isFinite(input) ? input : fallback);
  return {
    rosterWidth: clampRoster(num(raw.rosterWidth, ROSTER_DEFAULT)),
    rosterCollapsed: raw.rosterCollapsed === true,
    paneOpen: raw.paneOpen !== false,
    paneWidth: clampPane(num(raw.paneWidth, PANE_DEFAULT)),
  };
}

export function readShellPrefs(): ShellPrefs {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? sanitize(JSON.parse(stored)) : { ...DEFAULT_SHELL_PREFS };
  } catch {
    return { ...DEFAULT_SHELL_PREFS };
  }
}

export function writeShellPrefs(prefs: ShellPrefs): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sanitize(prefs)));
  } catch {
    // Private mode or a full disk: the layout holds for this window.
  }
}

export type ShellAction =
  | { type: "resize-roster"; width: number }
  | { type: "resize-pane"; width: number }
  | { type: "toggle-roster" }
  | { type: "set-roster-collapsed"; collapsed: boolean }
  | { type: "toggle-pane" }
  | { type: "set-pane-open"; open: boolean };

/** The person's choices, changed by one gesture. Pure; persistence is the caller's. */
export function shellPrefsReducer(prefs: ShellPrefs, action: ShellAction): ShellPrefs {
  switch (action.type) {
    case "resize-roster":
      return { ...prefs, rosterWidth: clampRoster(action.width), rosterCollapsed: false };
    case "resize-pane":
      return { ...prefs, paneWidth: clampPane(action.width), paneOpen: true };
    case "toggle-roster":
      return { ...prefs, rosterCollapsed: !prefs.rosterCollapsed };
    case "set-roster-collapsed":
      return prefs.rosterCollapsed === action.collapsed ? prefs : { ...prefs, rosterCollapsed: action.collapsed };
    case "toggle-pane":
      return { ...prefs, paneOpen: !prefs.paneOpen };
    case "set-pane-open":
      return prefs.paneOpen === action.open ? prefs : { ...prefs, paneOpen: action.open };
    default:
      return prefs;
  }
}
