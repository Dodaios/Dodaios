/**
 * Client for `/api/games` — Settings → Game settings (docs/game-settings.md).
 *
 * The catalog (which settings each game has) comes from the backend, so a
 * new game is one entry in `dodaios/games/catalog.json`, not a frontend change.
 */

export type GameSettingType = "slider" | "number" | "select" | "toggle" | "text";
export type GameSettingValue = number | string | boolean;
export type GameSectionId =
  | "perf_display"
  | "perf_rendering"
  | "perf_detail"
  | "perf_raytracing"
  | "perf_effects"
  | "mouse"
  | "audio"
  | "video"
  | "gameplay";

export type BindMode = "hold" | "toggle";

export interface CustomBind {
  id: string;
  action: string;
  key: string;
  alt: string;
}

export interface GamePreset {
  id: "competitive" | "balanced" | "quality" | "epic";
  /** "monitor" in perf_fps_cap means: the detected monitor's refresh rate. */
  values: Record<string, GameSettingValue>;
}

export interface MonitorInfo {
  name: string;
  primary: boolean;
  width: number;
  height: number;
  refresh_hz: number;
  max_width: number;
  max_height: number;
  max_refresh_hz: number;
}

export interface SystemInfo {
  os: string;
  cpu: string | null;
  ram_gb: number | null;
  gpus: { name: string; vram_gb: number | null }[];
  monitors: MonitorInfo[];
  gpu_tier: "entry" | "mid" | "high" | "enthusiast" | null;
  recommended_preset: GamePreset["id"] | null;
}

export interface GameSetting {
  key: string;
  label: string;
  type: GameSettingType;
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
  default: GameSettingValue | null;
  note?: string;
}

export interface GameKeybind {
  id: string;
  action: string;
  default: string;
  note?: string;
}

export interface GameDefinition {
  id: string;
  name: string;
  publisher: string;
  /** Degrees per mouse count at sensitivity 1; null when not linear. */
  yaw: number | null;
  yaw_note: string;
  /** The hip-fire setting the converter reads and writes. */
  sens_key: string | null;
  config_file: string;
  sources: string[];
  sections: { id: GameSectionId; settings: GameSetting[] }[];
  keybinds: GameKeybind[];
}

export interface GameProfile {
  values: Record<string, GameSettingValue>;
  keybinds: Record<string, string>;
  alt_keybinds: Record<string, string>;
  bind_modes: Record<string, BindMode>;
  custom_binds: CustomBind[];
  dpi: number | null;
  notes: string;
  updated_at: string | null;
}

export interface GameSummary {
  id: string;
  name: string;
  publisher: string;
  convertible: boolean;
  has_profile: boolean;
  updated_at: string | null;
}

export interface GamesIndex {
  dpi: number;
  games: GameSummary[];
  presets: GamePreset[];
}

export interface GameDetail {
  game: GameDefinition;
  profile: GameProfile;
  default_dpi: number;
}

export interface ProfilePatch {
  values?: Record<string, GameSettingValue | null>;
  keybinds?: Record<string, string | null>;
  alt_keybinds?: Record<string, string | null>;
  bind_modes?: Record<string, BindMode | null>;
  custom_binds?: CustomBind[];
  dpi?: number;
  reset_dpi?: boolean;
  notes?: string;
}

export interface ConvertResult {
  game_id: string;
  sens: number;
  dpi: number;
  to_dpi: number;
  cm_per_360: number;
  edpi: number;
  results: { id: string; name: string; sens_key: string; sens: number; edpi: number }[];
}

export class GamesRequestError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "GamesRequestError";
    this.status = status;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const body = (await response.json().catch(() => null)) as T | { detail?: unknown } | null;
  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body && typeof body.detail === "string"
        ? body.detail
        : "";
    throw new GamesRequestError(detail || `Request failed (${response.status}).`, response.status);
  }
  return body as T;
}

function sendJson<T>(url: string, method: string, payload: unknown): Promise<T> {
  return request<T>(url, {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function fetchGames(): Promise<GamesIndex> {
  return request<GamesIndex>("/api/games");
}

export function fetchGame(gameId: string): Promise<GameDetail> {
  return request<GameDetail>(`/api/games/${encodeURIComponent(gameId)}`);
}

export function saveGameProfile(gameId: string, patch: ProfilePatch): Promise<{ profile: GameProfile }> {
  return sendJson(`/api/games/${encodeURIComponent(gameId)}/profile`, "PUT", patch);
}

export function resetGameProfile(gameId: string): Promise<{ removed: boolean }> {
  return request(`/api/games/${encodeURIComponent(gameId)}/profile`, { method: "DELETE" });
}

export function fetchSystem(): Promise<SystemInfo> {
  return request<SystemInfo>("/api/games/system");
}

export function saveDefaultDpi(dpi: number): Promise<{ dpi: number }> {
  return sendJson("/api/games/dpi", "PUT", { dpi });
}

export function convertSensitivity(input: {
  game_id: string;
  sens: number;
  dpi?: number;
  to_dpi?: number;
}): Promise<ConvertResult> {
  return sendJson("/api/games/convert", "POST", input);
}

/** cm of mouse travel for a 360° turn (same formula as dodaios/games/sensitivity.py). */
export function cmPer360(yaw: number, sens: number, dpi: number): number | null {
  if (!(yaw > 0 && sens > 0 && dpi > 0)) return null;
  return (360 / (yaw * sens * dpi)) * 2.54;
}
