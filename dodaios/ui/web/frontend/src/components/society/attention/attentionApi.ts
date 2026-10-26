import {
  answerAgentChatQuestion,
  resolveAgentChatApproval,
} from "@/lib/agentChatApi";

/**
 * The "needs you" list (`GET /api/agent-chat/attention`,
 * dodaios/agent_chat/attention.py) and the decisions the inbox can take on an
 * item without opening its chat.
 */

export type AttentionKind = "question" | "approval" | "credential" | "proposal";

export interface AttentionDetail {
  /** question: the current step's text and options. */
  question?: string;
  options?: string[];
  step?: number;
  count?: number;
  /** question: one tap answers it (a single pick). */
  single?: boolean;
  asker?: string;
  /** approval: the tool asking. */
  tool?: string;
  /** credential: the field's label. */
  label?: string;
  /** queue items: the capability and whether it was parked. */
  capability?: string;
  parked?: boolean;
  proposal_kind?: string;
}

export interface AttentionItem {
  kind: AttentionKind;
  agentId: string;
  sessionId: string;
  refId: string;
  summary: string;
  sinceMs: number;
  expiresMs: number | null;
  /** An end-of-turn card: the answer goes out as the next message. */
  deferred: boolean;
  /** `chat` for a card in a chat, `queue` for a society item. */
  source: "chat" | "queue";
  detail: AttentionDetail;
}

export interface AttentionList {
  items: AttentionItem[];
  count: number;
}

interface ItemRow {
  kind: AttentionKind;
  agent_id: string;
  session_id: string;
  ref_id: string;
  summary: string;
  since_ms: number;
  expires_ms: number | null;
  deferred?: boolean;
  source?: string;
  detail?: AttentionDetail;
}

function rowToItem(row: ItemRow): AttentionItem {
  return {
    kind: row.kind,
    agentId: row.agent_id,
    sessionId: row.session_id,
    refId: row.ref_id,
    summary: row.summary ?? "",
    sinceMs: Number(row.since_ms) || 0,
    expiresMs: row.expires_ms ? Number(row.expires_ms) : null,
    deferred: Boolean(row.deferred),
    source: row.source === "queue" ? "queue" : "chat",
    detail: row.detail ?? {},
  };
}

export async function fetchAttention(): Promise<AttentionList> {
  const res = await fetch("/api/agent-chat/attention");
  if (!res.ok) throw new Error(`attention ${res.status}`);
  const body = (await res.json()) as { items?: ItemRow[]; count?: number };
  const items = (body.items ?? []).map(rowToItem);
  return { items, count: typeof body.count === "number" ? body.count : items.length };
}

export interface FocusReport {
  agentId: string;
  sessionId: string;
  appFocused: boolean;
  muted: string[];
}

export async function reportAttentionFocus(report: FocusReport): Promise<void> {
  await fetch("/api/agent-chat/attention/focus", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      agent_id: report.agentId,
      session_id: report.sessionId,
      app_focused: report.appFocused,
      muted: report.muted,
    }),
  });
}

/** What the inbox can do with an item in place. */
export type QuickAction =
  | { type: "option"; index: number }
  | { type: "allow" }
  | { type: "deny" };

/** The quick actions an item offers; empty means "open it in its chat". */
export function quickActionsFor(item: AttentionItem): QuickAction[] {
  if (item.kind === "question") {
    const options = item.detail.options ?? [];
    return item.detail.single && options.length > 0
      ? options.slice(0, 4).map((_, index) => ({ type: "option", index }))
      : [];
  }
  if (item.kind === "approval") return [{ type: "deny" }, { type: "allow" }];
  if (item.kind === "proposal") {
    // A team offer is a pick list; it is answered on its card.
    return item.detail.proposal_kind === "team" ? [] : [{ type: "deny" }, { type: "allow" }];
  }
  return [];
}

async function resolveSociety(path: string, approve: boolean): Promise<void> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approve, note: "" }),
  });
  if (!res.ok) throw new Error(`resolve ${res.status}`);
}

/** Carry out a quick action on `item`. Never widens a permission: allow means once. */
export async function runQuickAction(item: AttentionItem, action: QuickAction): Promise<void> {
  if (item.kind === "question" && action.type === "option") {
    await answerAgentChatQuestion(item.sessionId, item.refId, item.detail.step ?? 0, { optionIndex: action.index });
    return;
  }
  const approve = action.type === "allow";
  if (item.kind === "approval" && item.source === "chat") {
    await resolveAgentChatApproval(item.sessionId, item.refId, approve ? "allow" : "deny");
    return;
  }
  if (item.kind === "approval") {
    await resolveSociety(`/api/society/approvals/${encodeURIComponent(item.refId)}/resolve`, approve);
    return;
  }
  if (item.kind === "proposal") {
    await resolveSociety(`/api/society/proposals/${encodeURIComponent(item.refId)}/resolve`, approve);
    return;
  }
  throw new Error(`no quick action for ${item.kind}`);
}
