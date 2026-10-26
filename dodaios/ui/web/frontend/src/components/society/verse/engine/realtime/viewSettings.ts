/**
 * The person's own settings for the eye-level views: mouse sensitivity, an
 * inverted vertical axis, the field of view in third and in first person,
 * the render quality, and the view they last chose (bird's-eye, third or
 * first person). Cosmetic and local to this browser (localStorage, every
 * access guarded); never synced. Without storage the defaults apply and
 * changes last for the session.
 */
import { create } from "zustand";
import { LOOK_SENSITIVITY } from "./mouseLook";
import { SHOULDER, clampHfov } from "./shoulderRig";
import { normalizeView, type VerseView } from "./viewMode";

/** "auto" starts at high and drops to low on a GPU that cannot hold ~45 fps. */
export type QualityChoice = "auto" | "high" | "low";

export interface ViewPrefs {
  /** Turn-rate multiplier, LOOK_SENSITIVITY.min–max, 1 by default. */
  sensitivity: number;
  /** Moving the mouse up looks down. */
  invertY: boolean;
  quality: QualityChoice;
  /** Horizontal field of view in third and in first person, degrees (SHOULDER.minHfovDeg–maxHfovDeg). */
  fovThird: number;
  fovFirst: number;
  /** The view the person last chose. */
  view: VerseView;
}

export interface ViewSettings extends ViewPrefs {
  set: (patch: Partial<ViewPrefs>) => void;
  reset: () => void;
}

export const VIEW_SETTINGS_KEY = "dodaios.verse.view.v1";
export const VIEW_DEFAULTS: Readonly<ViewPrefs> = {
  sensitivity: 1, invertY: false, quality: "auto", fovThird: SHOULDER.hfovDeg, fovFirst: SHOULDER.firstHfovDeg, view: "third",
};

/** Whatever was stored (or nothing), as valid settings. Pure. */
export function normalizeViewPrefs(raw: unknown): ViewPrefs {
  const o = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>) : {};
  const s = o.sensitivity;
  return {
    sensitivity: typeof s === "number" && Number.isFinite(s)
      ? Math.min(LOOK_SENSITIVITY.max, Math.max(LOOK_SENSITIVITY.min, s))
      : VIEW_DEFAULTS.sensitivity,
    invertY: o.invertY === true,
    quality: o.quality === "high" || o.quality === "low" ? o.quality : "auto",
    fovThird: typeof o.fovThird === "number" ? clampHfov(o.fovThird, VIEW_DEFAULTS.fovThird) : VIEW_DEFAULTS.fovThird,
    fovFirst: typeof o.fovFirst === "number" ? clampHfov(o.fovFirst, VIEW_DEFAULTS.fovFirst) : VIEW_DEFAULTS.fovFirst,
    view: normalizeView(o.view),
  };
}

function read(): ViewPrefs {
  try {
    const raw = window.localStorage.getItem(VIEW_SETTINGS_KEY);
    return normalizeViewPrefs(raw ? JSON.parse(raw) : null);
  } catch {
    return { ...VIEW_DEFAULTS };
  }
}

function write(prefs: ViewPrefs): void {
  try {
    window.localStorage.setItem(VIEW_SETTINGS_KEY, JSON.stringify(prefs));
  } catch {
    /* not kept, still applied */
  }
}

const prefsOf = (s: ViewPrefs): ViewPrefs => ({
  sensitivity: s.sensitivity, invertY: s.invertY, quality: s.quality, fovThird: s.fovThird, fovFirst: s.fovFirst, view: s.view,
});

export const useViewSettings = create<ViewSettings>((set, get) => ({
  ...read(),
  set: (patch) => {
    const next = normalizeViewPrefs({ ...prefsOf(get()), ...patch });
    write(next);
    set(next);
  },
  // Reset puts the settings back; the view on screen stays what it is.
  reset: () => {
    const next = { ...VIEW_DEFAULTS, view: get().view };
    write(next);
    set(next);
  },
}));
