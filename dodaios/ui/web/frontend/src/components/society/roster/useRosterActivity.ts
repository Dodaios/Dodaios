/**
 * The chat facts a roster row shows besides the agent's state: the last
 * message, when it was sent, and any unsent draft.
 *
 * Nothing new is fetched per agent. Every specialist's chat is one session in
 * the society chat store, whose session list already carries a preview and
 * an update time; drafts live in the composer's draft store. The lead's chat
 * is the front page's chat, so its row reads that store instead.
 */
import { useEffect, useMemo, useRef } from "react";
import { useStore } from "zustand";

import { composerDraftsFor } from "@/components/agentchat/composerDrafts";
import { useAgentChatStore, type AgentChatStoreHook } from "@/store/agentChat";

import type { SocietyAgent } from "../data";

export interface RosterActivity {
  lastMessage?: string;
  lastMs?: number | null;
  draft?: string;
}

export type RosterActivityMap = ReadonlyMap<string, RosterActivity>;

/** Re-read the session list at most this often while agents finish work. */
const REFRESH_GAP_MS = 2_500;

export function useRosterActivity(agents: SocietyAgent[], societyStore: AgentChatStoreHook, enabled = true): RosterActivityMap {
  const sessions = societyStore((state) => state.sessions);
  const leadSessions = useAgentChatStore((state) => state.sessions);
  const leadActive = useAgentChatStore((state) => state.activeSessionId);
  const drafts = useStore(composerDraftsFor(societyStore), (state) => state.drafts);
  const leadDrafts = useStore(composerDraftsFor(useAgentChatStore), (state) => state.drafts);

  // A finished turn changes the last message: reload the list when an agent
  // stops working, throttled so a busy team does not hammer the endpoint.
  const working = agents.filter((agent) => agent.state === "working").map((agent) => agent.agentId).join(",");
  const lastRefresh = useRef(0);
  const previousWorking = useRef<string | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const first = previousWorking.current === null;
    const someoneFinished = !first && previousWorking.current!.split(",").some((id) => id && !working.split(",").includes(id));
    previousWorking.current = working;
    if (!first && !someoneFinished) return;
    const now = Date.now();
    if (now - lastRefresh.current < REFRESH_GAP_MS) return;
    lastRefresh.current = now;
    void societyStore.getState().loadSessions();
  }, [enabled, working, societyStore]);

  return useMemo(() => {
    const bySession = new Map(sessions.map((row) => [row.session_id, row]));
    const out = new Map<string, RosterActivity>();
    for (const agent of agents) {
      if (agent.tier === "lead") {
        const latest = leadSessions.reduce<(typeof leadSessions)[number] | null>(
          (best, row) => (!best || row.updated_ms > best.updated_ms ? row : best), null);
        out.set(agent.agentId, {
          lastMessage: latest?.preview,
          lastMs: latest?.updated_ms ?? agent.stats?.lastActiveMs,
          draft: leadDrafts.get(leadActive)?.text,
        });
        continue;
      }
      const session = agent.chatSessionId ? bySession.get(agent.chatSessionId) : undefined;
      out.set(agent.agentId, {
        lastMessage: session?.preview,
        lastMs: session?.updated_ms ?? agent.stats?.lastActiveMs,
        draft: agent.chatSessionId ? drafts.get(agent.chatSessionId)?.text : undefined,
      });
    }
    return out;
  }, [agents, sessions, leadSessions, leadActive, drafts, leadDrafts]);
}
