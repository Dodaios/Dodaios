/**
 * The Unreal Verse host's REST surface (`dodaios/ui/web/verse_routes.py`).
 * `GET /api/verse/status` answers `{status, state, pid, vram_mb, fps, crash_report}`
 * (architecture 1.1); the launcher card reads nothing else.
 */

export type VerseHostStatus = "not_installed" | "unsupported" | "stopped" | "running" | "crashed";
export type VerseLifecycle = "booting" | "visible" | "panel" | "dormant" | "exiting";

export interface VerseStatus {
  status: VerseHostStatus;
  state: VerseLifecycle | null;
  pid: number | null;
  vram_mb: number | null;
  fps: number | null;
  crash_report: string | null;
}

export type ShowReason = "verse_view" | "quick_start_duel" | "station";

const STATUSES: readonly VerseHostStatus[] = ["not_installed", "unsupported", "stopped", "running", "crashed"];

/** A status body as the backend sends it; an unknown value reads as `stopped`. */
export function parseStatus(body: unknown): VerseStatus {
  const raw = (body ?? {}) as Record<string, unknown>;
  const status = STATUSES.includes(raw.status as VerseHostStatus) ? (raw.status as VerseHostStatus) : "stopped";
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  return {
    status,
    state: typeof raw.state === "string" ? (raw.state as VerseLifecycle) : null,
    pid: num(raw.pid),
    vram_mb: num(raw.vram_mb),
    fps: num(raw.fps),
    crash_report: typeof raw.crash_report === "string" ? raw.crash_report : null,
  };
}

async function call(path: string, init?: RequestInit): Promise<unknown> {
  const res = await fetch(path, init);
  if (!res.ok) throw new Error(`${path} answered ${res.status}`);
  return res.json();
}

function post(path: string, body?: unknown): Promise<unknown> {
  return call(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
}

export async function fetchVerseStatus(): Promise<VerseStatus> {
  return parseStatus(await call("/api/verse/status"));
}

/** The monitor the app window is on, as `lifecycle.show` wants it. */
export function currentMonitor(): { x: number; y: number; w: number; h: number; dpi: number } {
  const s = window.screen as Screen & { availLeft?: number; availTop?: number };
  return {
    x: Math.round(s.availLeft ?? 0),
    y: Math.round(s.availTop ?? 0),
    w: Math.max(1, Math.round(s.width || 1920)),
    h: Math.max(1, Math.round(s.height || 1080)),
    dpi: Math.round(96 * (window.devicePixelRatio || 1)),
  };
}

export async function showVerse(reason: ShowReason = "verse_view"): Promise<VerseStatus> {
  return parseStatus(await post("/api/verse/show", { reason, monitor: currentMonitor() }));
}

export async function stopVerse(): Promise<VerseStatus> {
  return parseStatus(await post("/api/verse/stop"));
}

export async function launchVerse(): Promise<VerseStatus> {
  return parseStatus(await post("/api/verse/launch"));
}

export async function fetchVerseFlags(): Promise<{ unreal_preview: boolean }> {
  const body = (await call("/api/verse/flags")) as { unreal_preview?: unknown };
  return { unreal_preview: body.unreal_preview === true };
}

/** Browser-stored values of the web Verse, posted once (bridge contract 14). */
export const IMPORT_KEYS = [
  "dodaios.verse.view.v1",
  "dodaios.verse.uniform.v1",
  "jarvis.verse.level.sound.v1",
  "jarvis.verse.levels.seen.v1",
  "jarvis.office.arcade.asteroids.best",
] as const;

export async function importBrowserSettings(storage: Pick<Storage, "getItem"> = window.localStorage): Promise<string[]> {
  const values: Record<string, string> = {};
  for (const key of IMPORT_KEYS) {
    try {
      const value = storage.getItem(key);
      if (value !== null) values[key] = value;
    } catch {
      // Storage blocked: nothing to import.
    }
  }
  const body = (await post("/api/verse/settings/import", { values })) as { imported?: unknown };
  return Array.isArray(body.imported) ? body.imported.filter((k): k is string => typeof k === "string") : [];
}
