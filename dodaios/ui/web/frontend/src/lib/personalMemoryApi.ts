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

export function useVaultItems(q: string, history: boolean) {
  return useQuery({
    queryKey: VAULT_KEYS.items(q, history),
    queryFn: () => {
      const params = new URLSearchParams();
      if (q.trim()) params.set("q", q.trim());
      if (history) params.set("history", "true");
      return request<{ items: VaultMemory[]; count: number }>(`${BASE}/items?${params}`);
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

export const forgetMemory = (id: string) =>
  request<{ forgotten: number }>(`${BASE}/items/${encodeURIComponent(id)}`, { method: "DELETE" });

export const importBundle = (file: Blob) =>
  request<ImportReport>(`${BASE}/import`, {
    method: "POST",
    body: file,
    headers: { "Content-Type": "application/zip" },
  });

export const exportUrl = (format: "bundle" | "markdown") => `${BASE}/export?format=${format}`;
