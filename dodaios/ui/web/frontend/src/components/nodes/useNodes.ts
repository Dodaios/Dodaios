/**
 * The Nodes library's data: the list (`/api/nodes`) and what can be done to
 * a card.
 *
 * The list polls. A library with something in the making (a card that is
 * `building`, or a request the assistant has not answered with a node yet)
 * is read every few seconds so the new card appears by itself; a quiet one
 * twice a minute and when the window comes back to the front.
 *
 * The plain functions (`createNode`, `renameNode`, …) only talk to the
 * server. `useNodeActions()` hands out the same calls bound to the query
 * client: each of those re-reads the library and the run archive when it
 * settles, whether it worked or not.
 */
import { useMemo } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { DeleteOutputError, deleteOutput } from "@/hooks/useOutputs";
import { isTypedNode, type NodeCard, type NodeType, type NodesResponse } from "./nodeModel";

export const NODES_QUERY_KEY = ["nodes"] as const;
const OUTPUTS_QUERY_KEY = ["outputs"] as const;

export const NODES_FAST_POLL_MS = 4_000;
export const NODES_SLOW_POLL_MS = 30_000;

/** A request the nodes API refused; `detail` is the server's own sentence, or "". */
export class NodesApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail || `HTTP ${status}`);
    this.name = "NodesApiError";
  }
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // No JSON body: the status is all there is to report.
    }
    throw new NodesApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

function postJson(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

function nodeUrl(id: string, tail = ""): string {
  return `/api/nodes/${encodeURIComponent(id)}${tail}`;
}

/** A typed node as its own endpoints describe it (the upkeep strip reads this). */
export interface NodeState {
  id: string;
  type: NodeType;
  title: string;
  slug: string;
  page_path: string;
  version: number;
  /** Seconds since the epoch. */
  updated_at: number;
  /** What the node keeps current; "" for a node that is not kept current. */
  track: string;
  every_minutes: number;
  refreshing: boolean;
  note: string;
  visual_id: string;
  page_url: string;
  spec: unknown;
}

export async function fetchNodes(): Promise<NodesResponse> {
  const data = await readJson<Partial<NodesResponse>>(await fetch("/api/nodes"));
  return {
    nodes: Array.isArray(data.nodes) ? data.nodes : [],
    scanned_runs: data.scanned_runs ?? 0,
    skipped_runs: data.skipped_runs ?? 0,
  };
}

export async function fetchNodeBySlug(slug: string): Promise<NodeState> {
  // Without the spec: the caller watches the node's state, not its content.
  return readJson<NodeState>(await fetch(`/api/nodes/by-slug/${encodeURIComponent(slug)}?spec=0`));
}

export async function setNodeUpkeep(
  id: string,
  action: "stop" | "resume",
  everyMinutes?: number,
): Promise<NodeState> {
  const init: RequestInit =
    action === "resume" && everyMinutes ? postJson({ every_minutes: everyMinutes }) : { method: "POST" };
  return readJson<NodeState>(await fetch(nodeUrl(id, `/upkeep/${action}`), init));
}

/** Save one value the reader typed into a node's page. Rejects with the server's reason. */
export async function saveNodeField(
  id: string,
  edit: { path: string; value: string | boolean; as: "text" | "number" | "toggle" },
): Promise<NodeState> {
  return readJson<NodeState>(await fetch(nodeUrl(id, "/edit"), postJson(edit)));
}

export interface CreateNodeInput {
  type: NodeType;
  title?: string;
  language?: string;
}

/** A starter node of that type. */
export async function createNode(input: CreateNodeInput): Promise<NodeCard> {
  return readJson<NodeCard>(await fetch("/api/nodes", postJson(input)));
}

export async function renameNode(id: string, title: string): Promise<NodeCard> {
  return readJson<NodeCard>(
    await fetch(nodeUrl(id), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  );
}

export async function duplicateNode(id: string, title?: string): Promise<NodeCard> {
  return readJson<NodeCard>(await fetch(nodeUrl(id, "/duplicate"), postJson(title ? { title } : {})));
}

/** Back to the version before the last change (400 when there is none). */
export async function revertNode(id: string): Promise<NodeCard> {
  return readJson<NodeCard>(await fetch(nodeUrl(id, "/revert"), { method: "POST" }));
}

/**
 * Delete what a card stands for: a typed node through the nodes API, an
 * adopted file as that one file, a run as the whole run.
 */
export async function deleteNodeCard(card: NodeCard): Promise<void> {
  if (isTypedNode(card)) {
    await readJson<{ deleted: boolean }>(await fetch(nodeUrl(card.id), { method: "DELETE" }));
    return;
  }
  await deleteOutput(card.slug, card.origin === "run" ? null : card.path);
}

/** The server refused a delete because the run behind the card still works. */
export function isStillRunningError(error: unknown): boolean {
  return (error instanceof NodesApiError || error instanceof DeleteOutputError) && error.status === 409;
}

/** Re-read the library and the run archive (a node is also a run on disk). */
export function invalidateNodes(client: QueryClient): void {
  void client.invalidateQueries({ queryKey: NODES_QUERY_KEY });
  void client.invalidateQueries({ queryKey: OUTPUTS_QUERY_KEY });
}

export interface UseNodesOptions {
  /** A request for a new node is open: read as often as while one is building. */
  pending?: boolean;
}

export function useNodes(options: UseNodesOptions = {}) {
  const pending = options.pending === true;
  return useQuery<NodesResponse>({
    queryKey: NODES_QUERY_KEY,
    queryFn: fetchNodes,
    refetchInterval: (query) =>
      pending || query.state.data?.nodes.some((card) => card.status === "building")
        ? NODES_FAST_POLL_MS
        : NODES_SLOW_POLL_MS,
    refetchOnWindowFocus: true,
    staleTime: 2_000,
  });
}

export interface NodeActions {
  createNode: (input: CreateNodeInput) => Promise<NodeCard>;
  renameNode: (id: string, title: string) => Promise<NodeCard>;
  duplicateNode: (id: string, title?: string) => Promise<NodeCard>;
  revertNode: (id: string) => Promise<NodeCard>;
  deleteNodeCard: (card: NodeCard) => Promise<void>;
}

/** The mutations, each followed by a fresh read of `["nodes"]` and `["outputs"]`. */
export function useNodeActions(): NodeActions {
  const client = useQueryClient();
  return useMemo(() => {
    const settled = async <T,>(work: Promise<T>): Promise<T> => {
      try {
        return await work;
      } finally {
        invalidateNodes(client);
      }
    };
    return {
      createNode: (input) => settled(createNode(input)),
      renameNode: (id, title) => settled(renameNode(id, title)),
      duplicateNode: (id, title) => settled(duplicateNode(id, title)),
      revertNode: (id) => settled(revertNode(id)),
      deleteNodeCard: (card) => settled(deleteNodeCard(card)),
    };
  }, [client]);
}
