/**
 * Client for notifications and reminders (`dodaios/ui/web/notify_routes.py`).
 *
 * Settings: the one switch, a choice per kind, quiet hours, Telegram
 * approvals. Reminders: what is coming up, done, snooze, a brain dump into
 * items. A captured item's undo forgets the memory (`personalMemoryApi`).
 */

const BASE = "/api/notify";

export const NOTIFY_KINDS = ["reminder", "needs_you", "approval", "finished"] as const;
export type NotifyKind = (typeof NOTIFY_KINDS)[number];

export const PHONE_KINDS = ["decisions", "results", "failures", "progress", "brief"] as const;
export type PhoneKind = (typeof PHONE_KINDS)[number];

export const URGENT_EVENTS = ["approval", "question", "watchdog"] as const;
export type UrgentEvent = (typeof URGENT_EVENTS)[number];

/** "Call me for urgent decisions": off until the owner turns it on. */
export interface UrgentCallSettings {
  enabled: boolean;
  events: Record<UrgentEvent, boolean>;
  keywords: string[];
  deadline_min: number;
  max_per_day: number;
  escalate_after_min: number;
  route: "desktop" | "phone";
  /** E.164, e.g. +4915112345678; empty = no phone call. */
  phone_number: string;
}

export interface QuietHours {
  enabled: boolean;
  /** Local wall-clock times, `HH:MM`. */
  start: string;
  end: string;
}

export interface NotifySettings {
  enabled: boolean;
  kinds: Record<NotifyKind, boolean>;
  quiet_hours: QuietHours;
  telegram_approvals: boolean;
  /** Which lead updates reach the phone chat (Telegram, Discord DM, WhatsApp). */
  phone: Record<PhoneKind, boolean>;
  urgent_call?: UrgentCallSettings;
}

export interface NotifySettingsPatch {
  enabled?: boolean;
  kinds?: Partial<Record<NotifyKind, boolean>>;
  quiet_hours?: Partial<QuietHours>;
  telegram_approvals?: boolean;
  phone?: Partial<Record<PhoneKind, boolean>>;
  urgent_call?: Partial<Omit<UrgentCallSettings, "events">> & {
    events?: Partial<Record<UrgentEvent, boolean>>;
  };
}

export interface NotifyVerdict {
  shown: boolean;
  /** Why it was held back (`off`, `kind_off`, `quiet_hours`, `looking`), else "". */
  held: string;
  /** How it was shown (`shown`, `shown_no_click`, `unsupported`, `failed`). */
  how: string;
}

export interface TelegramState {
  connected: boolean;
  owner_known: boolean;
}

export interface ReminderRow {
  id: string;
  text: string;
  due_at: string | null;
  kind: string;
  reminder: boolean;
  overdue: boolean;
  delivered: boolean;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // The status alone names the failure.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export const getNotifySettings = () => request<NotifySettings>(`${BASE}/settings`);

export const putNotifySettings = (patch: NotifySettingsPatch) =>
  request<NotifySettings>(`${BASE}/settings`, { method: "PUT", body: JSON.stringify(patch) });

export const sendTestNotification = () =>
  request<NotifyVerdict>(`${BASE}/test`, { method: "POST" });

export const getTelegramState = () => request<TelegramState>(`${BASE}/telegram`);

export const listReminders = (days = 14) =>
  request<{ items: ReminderRow[] }>(`${BASE}/reminders?days=${days}`);

export const markReminderDone = (id: string) =>
  request<{ ok: boolean }>(`${BASE}/reminders/${encodeURIComponent(id)}/done`, { method: "POST" });

/** Move a reminder by `minutes`, or to `until` (time words or ISO) when given. */
export const snoozeReminder = (id: string, body: { minutes?: number; until?: string }) =>
  request<ReminderRow>(`${BASE}/reminders/${encodeURIComponent(id)}/snooze`, {
    method: "POST",
    body: JSON.stringify({ ...body, timezone: localTimezone() }),
  });

export function localTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone ?? "";
  } catch {
    return "";
  }
}
