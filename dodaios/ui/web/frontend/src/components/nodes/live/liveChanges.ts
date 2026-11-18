/**
 * Reading `NodeChanged` events and the ranges an editor plays back: the half
 * of the live store that only the push receiver and the editors need, kept
 * out of the app's entry bundle (the chat card needs only the store).
 */
import { isNodeType } from "../nodeModel";
import {
  PRESENCE_LINGER_MS,
  isAgentChange,
  type LiveAction,
  type LiveAuthor,
  type LiveNode,
  type LiveOp,
  type NodeChange,
} from "./liveStore";

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

const ACTIONS: readonly LiveAction[] = ["create", "update", "revert", "save"];

/** A `NodeChanged` payload as a `NodeChange`, or null when it is not one. */
export function parseNodeChange(payload: unknown, now = Date.now()): NodeChange | null {
  if (payload === null || typeof payload !== "object") return null;
  const p = payload as Record<string, unknown>;
  const nodeId = text(p.node_id);
  const ref = text(p.ref);
  if (!nodeId || !ref.includes("::") || !isNodeType(p.node_type)) return null;
  const action = ACTIONS.includes(p.action as LiveAction) ? (p.action as LiveAction) : "update";
  const ops = Array.isArray(p.ops)
    ? (p.ops as unknown[]).filter(
        (op): op is LiveOp => op !== null && typeof op === "object" && typeof (op as LiveOp).path === "string",
      )
    : [];
  return {
    nodeId,
    ref,
    slug: text(p.slug) || ref.slice(0, ref.indexOf("::")),
    nodeType: p.node_type,
    title: text(p.title),
    version: num(p.version),
    previousVersion: num(p.previous_version),
    updatedAt: num(p.updated_at),
    action,
    rewrite: p.rewrite === true,
    ops,
    author: {
      kind: p.author_kind === "assistant" ? "assistant" : "person",
      name: text(p.author_name),
      id: text(p.author_id) || (p.author_kind === "assistant" ? "lead" : "person"),
    },
    sessionId: text(p.session_id),
    step: text(p.step),
    receivedAt: now,
  };
}

/**
 * What an editor that moved from version `from` to `to` should play: the
 * agent's ops in order, or null when a rewrite (or a version this window
 * never heard of) lies between, and whether an agent wrote that range at all.
 */
export function changesBetween(
  node: LiveNode | null | undefined,
  from: number,
  to: number,
): { agent: boolean; ops: LiveOp[] | null; author: LiveAuthor | null; created: boolean } {
  const none = { agent: false, ops: null, author: null, created: false };
  if (!node) return none;
  const range = node.changes.filter((c) => c.version > from && c.version <= to);
  const agentChanges = range.filter(isAgentChange);
  if (agentChanges.length === 0) return none;
  const known = new Set(range.map((c) => c.version));
  let complete = true;
  for (let v = from + 1; v <= to; v += 1) if (!known.has(v)) complete = false;
  const rewrite = range.some((c) => c.rewrite || c.action === "revert");
  return {
    agent: true,
    ops: complete && !rewrite ? range.flatMap((c) => c.ops) : null,
    author: agentChanges[agentChanges.length - 1].author,
    created: range.some((c) => c.action === "create"),
  };
}

/** Is the agent's presence still to be shown on `node` at `now`? */
export function presenceActive(node: LiveNode | null | undefined, now = Date.now()): boolean {
  if (!node || node.author === null || node.lastEditAt === 0) return false;
  if (node.building) return true;
  return node.settledAt > 0 && now - node.settledAt < PRESENCE_LINGER_MS;
}
