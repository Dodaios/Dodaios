/**
 * What the app knows about nodes being built right now.
 *
 * The backend announces every node write as a `NodeChanged` event on the
 * app's WebSocket (`dodaios/nodes/live.py`). This store keeps, per node, the
 * last few changes, who made them and whether an agent is still building, so
 * that:
 *
 * - the chat card can show "being built" until the agent's turn ends,
 * - the node window can open by itself on an agent's create (`autoOpen.ts`),
 * - an open editor can play an agent's edit back with the agent's presence
 *   (`LiveBuildLayer`), and never a person's own save.
 *
 * Contract: docs/node-live-build.md.
 */
import { create } from "zustand";

import { isNodeType, type NodeType } from "../nodeModel";

/** The WebSocket event name the backend publishes. */
export const NODE_CHANGED_EVENT = "NodeChanged";

/** Changes kept per node, newest last: enough to span the versions one fetch can jump. */
const KEPT_CHANGES = 24;
/** An agent that wrote nothing for this long is taken to be done, turn end or not. */
export const IDLE_SETTLE_MS = 90_000;
/** Presence stays this long after the agent's turn ended, then fades. */
export const PRESENCE_LINGER_MS = 1_500;

/** One JSON Pointer op as the backend applied it (`dodaios/nodes/patch.py`). */
export interface LiveOp {
  op: string;
  path: string;
  value?: unknown;
  /** The value was too large to send; read the node's spec for it. */
  value_omitted?: boolean;
  to?: number;
  find?: string;
}

export type LiveAction = "create" | "update" | "revert" | "save";

export interface LiveAuthor {
  kind: "assistant" | "person";
  /** The name on the agent's tag ("" for the person). */
  name: string;
  /** Tells authors apart: `lead`, `agent:<id>`, `thread:<session id>`, `person`. */
  id: string;
}

/** One `NodeChanged` event, as the app reads it. */
export interface NodeChange {
  nodeId: string;
  /** `slug::page_path`, the address the stage, the chat card and the node window use. */
  ref: string;
  slug: string;
  nodeType: NodeType;
  title: string;
  version: number;
  previousVersion: number;
  /** Seconds since the epoch, as `/api/nodes` reports it. */
  updatedAt: number;
  action: LiveAction;
  /** The spec was replaced whole: `ops` is empty and says nothing. */
  rewrite: boolean;
  ops: LiveOp[];
  author: LiveAuthor;
  /** The chat session the write came from; "" when none. */
  sessionId: string;
  /** The agent's current step, when known. */
  step: string;
  /** `Date.now()` when this window heard of it. */
  receivedAt: number;
}

export interface LiveNode {
  nodeId: string;
  ref: string;
  slug: string;
  nodeType: NodeType;
  title: string;
  version: number;
  updatedAt: number;
  /** The agent that wrote last (null while only the person has). */
  author: LiveAuthor | null;
  sessionId: string;
  /** The last changes, oldest first. */
  changes: NodeChange[];
  /** An agent is building it: from its first write until its turn ends (or it goes quiet). */
  building: boolean;
  /** `Date.now()` of the agent's last write; 0 when there was none. */
  lastEditAt: number;
  /** `Date.now()` when the build was over; 0 while it runs. */
  settledAt: number;
  /** The agent's current step, when known ("" otherwise). */
  step: string;
  /** The node was made in this window's lifetime by an agent. */
  created: boolean;
}

interface LiveState {
  nodes: Record<string, LiveNode>;
  /** `ref` to node id. */
  refs: Record<string, string>;
  /** Refs the node window already opened by itself (it never opens twice for one node). */
  autoOpened: Record<string, true>;
  /** Sessions whose auto-opened window the person closed: no more opening until the turn ends. */
  suppressed: Record<string, true>;
  receive: (change: NodeChange) => void;
  /** The agent's turn in `sessionId` ended: its builds settle and presence fades. */
  turnEnded: (sessionId: string) => void;
  /** End one node's build (the idle fallback, or a test). */
  settle: (nodeId: string) => void;
  /** Say what the agent is doing on a node ("" clears it). */
  setStep: (nodeId: string, step: string) => void;
  /** True the first time for `ref`; false when the window opened for it before. */
  claimAutoOpen: (ref: string) => boolean;
  suppress: (sessionId: string) => void;
}

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

/** Is `change` an agent's work, the only kind that plays back? */
export function isAgentChange(change: Pick<NodeChange, "author">): boolean {
  return change.author.kind === "assistant";
}

const idleTimers = new Map<string, number>();

export const useNodeLive = create<LiveState>((set, get) => ({
  nodes: {},
  refs: {},
  autoOpened: {},
  suppressed: {},
  receive: (change) => {
    const before = get().nodes[change.nodeId];
    if (before && before.changes.some((c) => c.version === change.version && c.action === change.action)) return;
    const agent = isAgentChange(change);
    const changes = [...(before?.changes ?? []), change].slice(-KEPT_CHANGES);
    const node: LiveNode = {
      nodeId: change.nodeId,
      ref: change.ref,
      slug: change.slug,
      nodeType: change.nodeType,
      title: change.title || before?.title || "",
      version: Math.max(change.version, before?.version ?? 0),
      updatedAt: Math.max(change.updatedAt, before?.updatedAt ?? 0),
      author: agent ? change.author : (before?.author ?? null),
      sessionId: agent ? change.sessionId : (before?.sessionId ?? ""),
      changes,
      building: agent ? true : (before?.building ?? false),
      lastEditAt: agent ? change.receivedAt : (before?.lastEditAt ?? 0),
      settledAt: agent ? 0 : (before?.settledAt ?? 0),
      step: agent ? change.step : (before?.step ?? ""),
      created: (before?.created ?? false) || (agent && change.action === "create"),
    };
    set((state) => ({
      nodes: { ...state.nodes, [change.nodeId]: node },
      refs: state.refs[change.ref] === change.nodeId ? state.refs : { ...state.refs, [change.ref]: change.nodeId },
    }));
    if (agent) {
      window.clearTimeout(idleTimers.get(change.nodeId));
      idleTimers.set(change.nodeId, window.setTimeout(() => get().settle(change.nodeId), IDLE_SETTLE_MS));
    }
  },
  turnEnded: (sessionId) => {
    const now = Date.now();
    const nodes = { ...get().nodes };
    let changed = false;
    for (const node of Object.values(nodes)) {
      if (!node.building || node.sessionId !== sessionId) continue;
      nodes[node.nodeId] = { ...node, building: false, settledAt: now, step: "" };
      changed = true;
    }
    const suppressed = { ...get().suppressed };
    const wasSuppressed = delete suppressed[sessionId] && sessionId in get().suppressed;
    if (changed || wasSuppressed) set({ nodes, suppressed });
  },
  settle: (nodeId) => {
    const node = get().nodes[nodeId];
    window.clearTimeout(idleTimers.get(nodeId));
    idleTimers.delete(nodeId);
    if (!node || !node.building) return;
    set((state) => ({ nodes: { ...state.nodes, [nodeId]: { ...node, building: false, settledAt: Date.now(), step: "" } } }));
  },
  setStep: (nodeId, step) => {
    const node = get().nodes[nodeId];
    if (!node || node.step === step) return;
    set((state) => ({ nodes: { ...state.nodes, [nodeId]: { ...node, step } } }));
  },
  claimAutoOpen: (ref) => {
    if (get().autoOpened[ref]) return false;
    set((state) => ({ autoOpened: { ...state.autoOpened, [ref]: true } }));
    return true;
  },
  suppress: (sessionId) => {
    if (!sessionId || get().suppressed[sessionId]) return;
    set((state) => ({ suppressed: { ...state.suppressed, [sessionId]: true } }));
  },
}));

/** The live record of the node at `ref`, or null. */
export function liveNodeOfRef(state: Pick<LiveState, "nodes" | "refs">, ref: string): LiveNode | null {
  const id = state.refs[ref];
  return id ? (state.nodes[id] ?? null) : null;
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
