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

/**
 * The optional Verse download (README Delivery): the app install never carries
 * the Verse. `GET /api/verse/install/progress`, `POST /api/verse/install`,
 * `DELETE /api/verse/install` (cancels a running download, else removes it).
 */
export type InstallState =
  | "idle"
  | "downloading"
  | "verifying"
  | "installing"
  | "installed"
  | "cancelled"
  | "failed"
  | "removing"
  | "unavailable";

export interface InstallProgress {
  state: InstallState;
  done_bytes: number;
  total_bytes: number;
  version: string | null;
  installed_version: string | null;
  download_bytes: number | null;
  install_bytes: number | null;
  error: string | null;
  bytes_per_s: number | null;
}

const INSTALL_STATES: readonly InstallState[] = [
  "idle", "downloading", "verifying", "installing", "installed", "cancelled", "failed", "removing", "unavailable",
];

export function parseInstall(body: unknown): InstallProgress {
  const raw = (body ?? {}) as Record<string, unknown>;
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const str = (v: unknown) => (typeof v === "string" && v ? v : null);
  return {
    state: INSTALL_STATES.includes(raw.state as InstallState) ? (raw.state as InstallState) : "unavailable",
    done_bytes: num(raw.done_bytes) ?? 0,
    total_bytes: num(raw.total_bytes) ?? 0,
    version: str(raw.version),
    installed_version: str(raw.installed_version),
    download_bytes: num(raw.download_bytes),
    install_bytes: num(raw.install_bytes),
    error: str(raw.error),
    bytes_per_s: num(raw.bytes_per_s),
  };
}

export function isInstalling(p: InstallProgress | null): boolean {
  return !!p && (p.state === "downloading" || p.state === "verifying" || p.state === "installing");
}

export async function fetchInstallProgress(): Promise<InstallProgress> {
  return parseInstall(await call("/api/verse/install/progress"));
}

export async function startInstall(): Promise<InstallProgress> {
  return parseInstall(await post("/api/verse/install"));
}

/** Cancel the running download, or remove the installed Verse when none runs. */
export async function cancelOrRemoveInstall(): Promise<InstallProgress> {
  return parseInstall(await call("/api/verse/install", { method: "DELETE" }));
}

/** `7.4 GB`, `820 MB`: decimal units, one decimal from GB up. */
export function formatBytes(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`;
  return `${Math.max(0, Math.round(bytes / 1e3))} KB`;
}
