/**
 * Client for the personal memory vault (`dodaios/ui/web/personal_memory_routes.py`,
 * ADR-0044): atomic memories with their versions, export and import.
 */
import { useQuery } from "@tanstack/react-query";

export const MEMORY_KINDS = [
  "profile",
  "preference",
  "relationship",
  "project",
  "procedural",
  "episode",
  "reference",
  "ephemeral",
] as const;
export type MemoryKind = (typeof MEMORY_KINDS)[number];
export type MemoryOrigin = "user" | "inferred" | "imported";

export interface VaultMemory {
  id: string;
  kind: MemoryKind;
  text: string;
  entities: string[];
  scope: string;
  origin: MemoryOrigin;
  recorded_at: string;
  valid_from: string | null;
  valid_to: string | null;
  expired_at: string | null;
  supersedes_id: string | null;
  source: Record<string, unknown>;
  confidence: number;
  sensitivity: "normal" | "sensitive";
  pinned: boolean;
  use_count: number;
  last_used_at: string | null;
  current: boolean;
  score?: number;
}

export interface VaultOverview {
  path: string;
  stats: {
    current: number;
    by_kind: Partial<Record<MemoryKind, number>>;
    all_versions: number;
    forgotten: number;
    entities: number;
  };
  kinds: MemoryKind[];
  prompt_block: string;
  /** Ids of the memories the always-on block holds right now. */
  in_mind_ids: string[];
  budget_chars: number;
  used_chars: number;
  imported: boolean;
  /** Learning from corrections: lessons kept, how-to notes, repeated corrections. */
  learning?: {
    lessons: number;
    how_to: number;
    repeat_errors: number;
    needs_stronger: number;
    last_tidy: { at?: string; merged?: number; resolved?: number; retired?: number; reworded?: number };
  };
}

export interface VaultFile {
  name: string;
  kind: MemoryKind | "index";
  bytes: number;
  lines: number;
  content: string;
}

export interface VaultActivity {
  seq: number;
  at: string;
  action: string;
  memory_id: string | null;
  text: string;
}

export interface ImportReport {
  added: number;
  skipped: number;
  forgotten: number;
  errors: string[];
}

export class VaultApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

const BASE = "/api/memory/vault";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const json = typeof init?.body === "string";
  const response = await fetch(url, {
    ...init,
    headers: json ? { "Content-Type": "application/json", ...init?.headers } : init?.headers,
  });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail = (payload as { detail?: unknown } | null)?.detail;
    throw new VaultApiError(typeof detail === "string" ? detail : `HTTP ${response.status}`, response.status);
  }
  return payload as T;
}

export const VAULT_KEYS = {
  all: ["memory-vault"] as const,
  overview: ["memory-vault", "overview"] as const,
  items: (q: string, history: boolean) => ["memory-vault", "items", q, history] as const,
  history: (id: string) => ["memory-vault", "history", id] as const,
  activity: ["memory-vault", "activity"] as const,
  files: ["memory-vault", "files"] as const,
};

export function useVaultFiles(enabled = true) {
  return useQuery({
    queryKey: VAULT_KEYS.files,
    enabled,
    queryFn: () => request<{ files: VaultFile[] }>(`${BASE}/files`),
  });
}

export function useVaultOverview() {
  return useQuery({ queryKey: VAULT_KEYS.overview, queryFn: () => request<VaultOverview>(BASE) });
}

export interface VaultItemFilters {
  origin?: MemoryOrigin | "";
  /** ISO date (`2026-11-01`): memories recorded on or after it. */
  since?: string;
  sort?: "newest" | "";
  limit?: number;
}

export function useVaultItems(q: string, history: boolean, filters: VaultItemFilters = {}) {
  const { origin = "", since = "", sort = "", limit = 0 } = filters;
  return useQuery({
    queryKey: [...VAULT_KEYS.items(q, history), origin, since, sort, limit],
    queryFn: () => {
      const params = new URLSearchParams();
      if (q.trim()) params.set("q", q.trim());
      if (history) params.set("history", "true");
      if (origin) params.set("origin", origin);
      if (since) params.set("since", since);
      if (sort) params.set("sort", sort);
      if (limit) params.set("limit", String(limit));
      return request<{ items: VaultMemory[]; count: number; total?: number; has_more?: boolean }>(
        `${BASE}/items?${params}`,
      );
    },
    placeholderData: (previous) => previous,
  });
}

export function useVaultHistory(id: string | null) {
  return useQuery({
    queryKey: VAULT_KEYS.history(id ?? ""),
    enabled: Boolean(id),
    queryFn: () => request<{ versions: VaultMemory[] }>(`${BASE}/items/${encodeURIComponent(id ?? "")}/history`),
  });
}

export function useVaultActivity() {
  return useQuery({
    queryKey: VAULT_KEYS.activity,
    queryFn: () => request<{ entries: VaultActivity[] }>(`${BASE}/activity?limit=12`),
  });
}

export const addMemory = (text: string, kind: MemoryKind | "", pinned = false) =>
  request<{ action: string; item: VaultMemory | null }>(`${BASE}/items`, {
    method: "POST",
    body: JSON.stringify({ text, kind, pinned }),
  });

export const editMemory = (id: string, text: string, kind: MemoryKind | "" = "") =>
  request<{ action: string; item: VaultMemory | null }>(`${BASE}/items/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify({ text, kind }),
  });

export const pinMemory = (id: string, pinned: boolean) =>
  request<{ ok: boolean }>(`${BASE}/items/${encodeURIComponent(id)}/pin`, {
    method: "POST",
    body: JSON.stringify({ pinned }),
  });

export const endMemory = (id: string) =>
  request<{ ok: boolean }>(`${BASE}/items/${encodeURIComponent(id)}/end`, { method: "POST" });

/** What a forget answers: how many versions went, and how to take it back for a short time. */
export interface ForgetResult {
  forgotten: number;
  undo_token?: string | null;
  undo_seconds?: number;
}

export const forgetMemory = (id: string) =>
  request<ForgetResult>(`${BASE}/items/${encodeURIComponent(id)}`, { method: "DELETE" });

export const forgetMany = (ids: string[]) =>
  request<ForgetResult>(`${BASE}/forget`, { method: "POST", body: JSON.stringify({ ids }) });

export const undoForget = (token: string) =>
  request<{ restored: number }>(`${BASE}/undo/${encodeURIComponent(token)}`, { method: "POST" });

export const importBundle = (file: Blob) =>
  request<ImportReport>(`${BASE}/import`, {
    method: "POST",
    body: file,
    headers: { "Content-Type": "application/zip" },
  });

export const exportUrl = (format: "all" | "bundle" | "markdown") => `${BASE}/export?format=${format}`;

/** Which part of life a memory belongs to; `global` is unmarked. */
export const MEMORY_SCOPES = ["global", "work", "private"] as const;
export type MemoryScope = (typeof MEMORY_SCOPES)[number];

export const setMemoryScope = (id: string, scope: MemoryScope) =>
  request<{ ok: boolean; scope: MemoryScope }>(`${BASE}/items/${encodeURIComponent(id)}/scope`, {
    method: "PUT",
    body: JSON.stringify({ scope }),
  });

/** One row of the review list an export of another assistant turns into. */
export interface ImportCandidate {
  text: string;
  kind: MemoryKind;
  /** Already in memory: shown, but not kept by default. */
  exists: boolean;
  /** Distilled from conversations by the model, rather than listed in the file. */
  extracted: boolean;
}

export interface ImportReading {
  candidates: ImportCandidate[];
  shape: "list" | "conversations" | "mixed";
  messages: number;
  /** The file held conversations but no assistant model could read them. */
  model_missing: boolean;
}

export const readForeignExport = (name: string, text: string) =>
  request<ImportReading>(`${BASE}/import/read`, {
    method: "POST",
    body: JSON.stringify({ name, text }),
  });

export const saveForeignImport = (name: string, items: ImportCandidate[]) =>
  request<{ added: number; existing: number; refused: number; failed: number }>(`${BASE}/import/save`, {
    method: "POST",
    body: JSON.stringify({
      name,
      items: items.map((item) => ({ text: item.text, kind: item.kind, extracted: item.extracted })),
    }),
  });

export interface PauseState {
  paused: boolean;
  until: string | null;
}

export function useLearningPause() {
  return useQuery({
    queryKey: ["memory-vault", "pause"],
    queryFn: () => request<PauseState>(`${BASE}/pause`),
  });
}

/** Pause learning for `minutes`, for good (`"forever"`), or resume (`null`). */
export const setLearningPause = (span: number | "forever" | null) =>
  request<PauseState>(`${BASE}/pause`, {
    method: "PUT",
    body: JSON.stringify(span === "forever" ? { forever: true } : span === null ? {} : { minutes: span }),
  });
