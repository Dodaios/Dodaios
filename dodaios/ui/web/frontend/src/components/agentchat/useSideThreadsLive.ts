import { useEffect, useMemo, useRef, useState } from "react";

import { createAgentChatStore, type AgentChatStoreHook } from "@/store/agentChat";
import { withoutAnsweredResults } from "./agentResults";
import { sideThreadOf, type TimelineItem } from "./reduce";

/** A side thread's own session, read live: the store its cards answer to, and what answered so far. */
export interface SideLive {
  store: AgentChatStoreHook;
  /** What answered the person: the session's items without their message. */
  items: TimelineItem[];
}

/**
 * The side threads of a conversation that run while it is open, each read
 * from its own session, by side id.
 *
 * The conversation look places every message of a side thread's answer by
 * the time it was written (`chronology.ts`), so it needs those messages and
 * their times while they arrive, not only once the side thread has ended.
 * One seen running keeps its items after it ends: its messages do not jump
 * from a live answer to a plain reply. Its socket closes then; the items
 * stay. `enabled` false reads nothing.
 */
export function useSideThreadsLive(items: readonly TimelineItem[], enabled: boolean): ReadonlyMap<string, SideLive> {
  const stores = useRef(new Map<string, { store: AgentChatStoreHook; stop: () => void; open: boolean }>());
  const [version, setVersion] = useState(0);
  const runningKey = useMemo(() => {
    if (!enabled) return "";
    const ids: string[] = [];
    for (const item of items) {
      const side = sideThreadOf(item);
      if (side?.running && side.id) ids.push(side.id);
    }
    return ids.join(" ");
  }, [items, enabled]);

  useEffect(() => {
    const running = new Set(runningKey.split(" ").filter(Boolean));
    let changed = false;
    for (const id of running) {
      if (stores.current.has(id)) continue;
      // Never the chat on stage: a voice call must not continue in a side thread.
      const store = createAgentChatStore("jarvis", `side:${id}`, { voice: false });
      const stop = store.subscribe((state, prev) => {
        if (state.timeline.items !== prev.timeline.items) setVersion((v) => v + 1);
      });
      stores.current.set(id, { store, stop, open: true });
      store.getState().openSession(id);
      changed = true;
    }
    for (const [id, entry] of stores.current) {
      // Its answer is complete and stays in the store; the socket is not needed any more.
      if (!running.has(id) && entry.open) {
        entry.open = false;
        entry.store.getState().disconnect();
      }
    }
    if (changed) setVersion((v) => v + 1);
  }, [runningKey]);

  useEffect(() => {
    const current = stores.current;
    return () => {
      for (const entry of current.values()) {
        entry.stop();
        if (entry.open) entry.store.getState().disconnect();
      }
      current.clear();
    };
  }, []);

  return useMemo(() => {
    void version;
    const out = new Map<string, SideLive>();
    for (const [id, { store }] of stores.current) {
      // An agent's result this answer takes up itself is not drawn, as in
      // the conversation the side thread stands in.
      const answering = withoutAnsweredResults(store.getState().timeline.items).filter((entry) => entry.type !== "user");
      out.set(id, { store, items: answering });
    }
    return out;
  }, [version]);
}
