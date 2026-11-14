/**
 * The three calls an editor makes: read the node's spec, save the person's
 * spec, and draw an unsaved spec as the node's real page.
 *
 * A save names the version it was edited from (`base_version`). When the
 * node moved on meanwhile (the assistant revised it), the server refuses
 * with 409 and the current state, so the editor can let the person choose
 * instead of silently overwriting either side.
 */
import { NodesApiError } from "../useNodes";

export interface SavedSpec {
  version: number;
  /** Seconds since the epoch. */
  updated_at: number;
  /** The spec as the type's `normalize` kept it. */
  spec: unknown;
}

/** The node moved on since `base_version`: what it is now. */
export class SpecConflictError extends NodesApiError {
  constructor(
    detail: string,
    readonly current: SavedSpec,
  ) {
    super(409, detail);
    this.name = "SpecConflictError";
  }
}

function specUrl(nodeId: string, tail: string): string {
  return `/api/nodes/${encodeURIComponent(nodeId)}${tail}`;
}

async function failure(response: Response): Promise<never> {
  let body: Record<string, unknown> = {};
  try {
    body = (await response.json()) as Record<string, unknown>;
  } catch {
    // No JSON body: the status is all there is to report.
  }
  const detail = typeof body.detail === "string" ? body.detail : "";
  if (response.status === 409 && typeof body.version === "number") {
    throw new SpecConflictError(detail, {
      version: body.version,
      updated_at: typeof body.updated_at === "number" ? body.updated_at : 0,
      spec: body.spec,
    });
  }
  throw new NodesApiError(response.status, detail);
}

/** The node's spec and the revision it belongs to. */
export async function fetchNodeSpec(nodeId: string, signal?: AbortSignal): Promise<SavedSpec> {
  const response = await fetch(specUrl(nodeId, ""), { signal });
  if (!response.ok) return failure(response);
  const data = (await response.json()) as Partial<SavedSpec>;
  return { version: data.version ?? 0, updated_at: data.updated_at ?? 0, spec: data.spec };
}

/** Bodies up to this size may outlive the page (`keepalive`): the browser's own ceiling is 64 KiB. */
const KEEPALIVE_BYTES = 60 * 1024;

/**
 * Save the person's spec. Rejects with `SpecConflictError` (409) when the
 * node is no longer at `baseVersion`, and with `NodesApiError` carrying the
 * type's own sentence (422) when the spec is refused.
 */
export async function saveNodeSpec(
  nodeId: string,
  spec: unknown,
  baseVersion: number | null,
  options: { keepalive?: boolean } = {},
): Promise<SavedSpec> {
  const body = JSON.stringify({ spec, base_version: baseVersion });
  const response = await fetch(specUrl(nodeId, "/spec"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: options.keepalive === true && body.length < KEEPALIVE_BYTES,
  });
  if (!response.ok) return failure(response);
  return (await response.json()) as SavedSpec;
}

/**
 * The node's page drawn from `spec` without saving it: the full HTML
 * document, styles inline, exactly what the node page would be.
 */
export async function fetchNodePreview(nodeId: string, spec: unknown, signal?: AbortSignal): Promise<string> {
  const response = await fetch(specUrl(nodeId, "/preview"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ spec }),
    signal,
  });
  if (!response.ok) return failure(response);
  return response.text();
}
