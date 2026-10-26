import { create } from "zustand";

/**
 * How loudly waiting agents may reach the person, kept per window.
 *
 * * `muted`: agents that never notify (they still show in the list and badge).
 * * `desktop`: desktop notifications while the app is in the background. Off
 *   until the person turns it on, because turning it on asks the system for
 *   permission and nothing here may ask uninvited.
 * * `finished`: also tell when an agent finishes a job the person gave it.
 */

const STORAGE_KEY = "dodaios.attention.prefs";

export interface NotificationPrefs {
  muted: string[];
  desktop: boolean;
  finished: boolean;
}

const DEFAULTS: NotificationPrefs = { muted: [], desktop: false, finished: true };

function load(): NotificationPrefs {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw) as Partial<NotificationPrefs>;
    return {
      muted: Array.isArray(parsed.muted) ? parsed.muted.filter((id) => typeof id === "string") : [],
      desktop: parsed.desktop === true,
      finished: parsed.finished !== false,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

function save(prefs: NotificationPrefs): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    // Private mode or a full disk: the choice holds for this window only.
  }
}

export const useNotificationPrefs = create<NotificationPrefs>(() => load());

function update(patch: Partial<NotificationPrefs>): void {
  useNotificationPrefs.setState(patch);
  save(useNotificationPrefs.getState());
}

export function isAgentMuted(agentId: string): boolean {
  return useNotificationPrefs.getState().muted.includes(agentId);
}

export function toggleAgentMuted(agentId: string): void {
  const { muted } = useNotificationPrefs.getState();
  update({ muted: muted.includes(agentId) ? muted.filter((id) => id !== agentId) : [...muted, agentId] });
}

export function setFinishedNotices(on: boolean): void {
  update({ finished: on });
}

/** Whether this window can show desktop notifications at all. */
export function desktopNotificationsSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

/** The system's answer for desktop notifications ("default" until asked). */
export function desktopPermission(): NotificationPermission | "unsupported" {
  return desktopNotificationsSupported() ? Notification.permission : "unsupported";
}

/**
 * Turn desktop notifications on or off. Turning them on asks the system once
 * (from the person's own click); a refusal leaves them off.
 */
export async function setDesktopNotices(on: boolean): Promise<boolean> {
  if (!on) {
    update({ desktop: false });
    return false;
  }
  if (!desktopNotificationsSupported()) return false;
  let permission = Notification.permission;
  if (permission === "default") {
    try {
      permission = await Notification.requestPermission();
    } catch {
      permission = "denied";
    }
  }
  const granted = permission === "granted";
  update({ desktop: granted });
  return granted;
}

/** For tests: forget the stored choice. */
export function resetNotificationPrefs(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // nothing stored
  }
  useNotificationPrefs.setState({ ...DEFAULTS, muted: [] });
}
