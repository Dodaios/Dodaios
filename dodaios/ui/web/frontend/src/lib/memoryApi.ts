/**
 * Client for the path-addressed Memory API (`dodaios/ui/web/memory_vault_routes.py`).
 *
 * Every page is identified by its vault-relative path (`entities/ruben.md`,
 * `society/<agent>/MEMORY.md`), never by its file name: a hundred agent
 * notebooks share the name `MEMORY.md`.
 */
import { useQuery } from "@tanstack/react-query";

export type MemoryGroup = "knowledge" | "agents" | "journal" | "system";
export type MemoryKind =
  | "entity"
  | "person"
  | "project"
  | "concept"
  | "session"
  | "note"
  | "memory"
  | "profile"
  | "shared"
  | "system"
  | "template";
export type AgentState = "active" | "archived" | "orphan";

export interface MemoryPageSummary {
  path: string;
  slug: string;
  title: string;
  kind: MemoryKind;
  group: MemoryGroup;
  folder: string;
  agent_id: string | null;
  mtime: number;
  words: number;
  empty: boolean;
  summary: string;
  tags: string[];
  links_in: number;
  links_out: number;
}

export interface MemoryAgent {
  agent_id: string;
  name: string;
  state: AgentState;
  empty: boolean;
  updated: number;
  pages: string[];
}

export interface MemoryStats {
  pages: number;
  content_pages: number;
  empty_pages: number;
  links: number;
  mentions: number;
  broken_links: number;
}

export interface MemoryIndex {
  ok: true;
  vault_root: string;
  stats: MemoryStats;
  pages: MemoryPageSummary[];
  agents: MemoryAgent[];
  writable: boolean;
}

export interface PageRef {
  path: string;
  title: string;
  kind: MemoryKind | null;
  group: MemoryGroup | null;
  empty: boolean;
  agent_id?: string | null;
}

export interface LinkRef extends PageRef {
  context: string;
}

export interface OutgoingRef {
  path: string | null;
  title: string;
  kind: MemoryKind | null;
  broken: boolean;
  raw: string;
}

export interface RelatedRef extends PageRef {
  score: number;
  via: PageRef | null;
}

export interface NotebookEntry {
  id: string;
  text: string;
  importance: number;
  origin: string;
}

export interface MemoryPage extends Omit<MemoryPageSummary, "links_in" | "links_out"> {
  ok: true;
  properties: Record<string, unknown>;
  aliases: string[];
  body_md: string;
  size: number;
  editable: boolean;
  archivable: boolean;
  agent: { agent_id: string; name: string; state: AgentState } | null;
  entries: NotebookEntry[];
  outgoing: OutgoingRef[];
  backlinks: LinkRef[];
  mentions: LinkRef[];
  mentioned_in: LinkRef[];
  related: RelatedRef[];
}

export interface MapNode {
  id: string;
  title: string;
  kind: MemoryKind;
  group: MemoryGroup;
  agent_id: string | null;
  degree: number;
}

export interface MapEdge {
  source: string;
  target: string;
  kind: "link" | "mention";
}

export interface MemoryMap {
  ok: true;
  nodes: MapNode[];
  edges: MapEdge[];
}

export interface ActivityItem {
  ts: string;
  verb: string;
  source: string;
  summary: string;
  pages: { path: string; title: string; kind: MemoryKind }[];
}

export interface TidyResult {
  ok: true;
  dry_run: boolean;
  count: number;
  paths: string[];
}

export interface SearchHit {
  path: string;
  title: string;
  snippet: string;
  by_meaning: boolean;
}

/** An API refusal with the server's own sentence, ready to show. */
export class MemoryApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json", ...init.headers } : init?.headers,
  });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail = (payload as { detail?: unknown } | null)?.detail;
    const message = typeof detail === "string" ? detail : `HTTP ${response.status}`;
    throw new MemoryApiError(message, response.status);
  }
  return payload as T;
}

export const MEMORY_KEYS = {
  all: ["wiki", "memory"] as const,
  index: ["wiki", "memory", "index"] as const,
  page: (path: string) => ["wiki", "memory", "read", path] as const,
  map: (agents: boolean) => ["wiki", "memory", "map", agents] as const,
  activity: ["wiki", "memory", "activity"] as const,
  search: (query: string) => ["wiki", "memory", "search", query] as const,
};

export const fetchMemoryIndex = () => request<MemoryIndex>("/api/wiki/index");
export const fetchMemoryPage = (path: string) =>
  request<MemoryPage>(`/api/wiki/read?path=${encodeURIComponent(path)}`);
export const fetchMemoryMap = (agents: boolean) =>
  request<MemoryMap>(`/api/wiki/map?agents=${agents ? "true" : "false"}`);
export const fetchMemoryActivity = (limit = 30) =>
  request<{ ok: true; items: ActivityItem[] }>(`/api/wiki/activity?limit=${limit}`);

export async function searchMemory(query: string): Promise<SearchHit[]> {
  const result = await request<{
    ok: boolean;
    hits?: { path: string; title: string; snippet: string; by_meaning?: boolean }[];
  }>(`/api/wiki/search?q=${encodeURIComponent(query)}&k=12`);
  return (result.hits ?? []).map((hit) => ({
    path: hit.path,
    title: hit.title,
    snippet: hit.snippet,
    by_meaning: Boolean(hit.by_meaning),
  }));
}

export const createMemoryPage = (kind: "entity" | "project" | "concept", title: string, body_md = "") =>
  request<{ ok: true; path: string }>("/api/wiki/pages", {
    method: "POST",
    body: JSON.stringify({ kind, title, body_md }),
  });

export const saveMemoryPage = (path: string, body_md: string, base_mtime: number | null) =>
  request<{ ok: true; path: string; mtime: number }>("/api/wiki/pages", {
    method: "PUT",
    body: JSON.stringify({ path, body_md, base_mtime }),
  });

export const renameMemoryPage = (path: string, title: string) =>
  request<{ ok: true; path: string; links_rewritten: number; links_unrewritten: number }>("/api/wiki/pages/rename", {
    method: "POST",
    body: JSON.stringify({ path, title }),
  });

export const archiveMemoryPage = (path: string) =>
  request<{ ok: true; path: string }>("/api/wiki/pages/archive", {
    method: "POST",
    body: JSON.stringify({ path }),
  });

export const tidyMemory = (dry_run: boolean) =>
  request<TidyResult>("/api/wiki/tidy", { method: "POST", body: JSON.stringify({ dry_run }) });

export function useMemoryIndex() {
  return useQuery({ queryKey: MEMORY_KEYS.index, queryFn: fetchMemoryIndex, staleTime: 5_000 });
}

export function useMemoryPage(path: string | null) {
  return useQuery({
    queryKey: MEMORY_KEYS.page(path ?? ""),
    queryFn: () => fetchMemoryPage(path ?? ""),
    enabled: Boolean(path),
    staleTime: 5_000,
  });
}
