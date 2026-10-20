/**
 * Live chat tails for the agents who sit at their desk right now.
 *
 * Polls the existing session endpoint only for seated agents, at most six per
 * tick, the longest unread first, so every monitor on a full floor gets its
 * turn. Jittered so windows and agents never fire in lockstep (AP-33). A
 * failed poll keeps the last good screen; it is logged, not shown. The ticks
 * do not wait for the reads: each read shows its answer when it comes, has a
 * timeout, and is aborted when the poller stops, so a request hanging on a
 * half-open socket costs one of the six places for a few seconds and nothing
 * else.
 */
import { useEffect, useRef, useState } from "react";
import { fetchAgentChatSession } from "@/lib/agentChatApi";
import { chatLines, chatVersion, type ChatLine } from "./deskChat";
import { withReadSignal } from "./pollSignal";
import { seatedAtDesk } from "./walkerRegistry";

/** Events fetched per poll: enough for a full screen after tool noise is filtered out. */
const TAIL_EVENTS = 60;

const POLL_MS = 2500;
const JITTER_MS = 1200;
/** Never more sessions in flight per tick than this, however many agents sit. */
export const MAX_PER_TICK = 6;

export interface DeskChat { lines: ChatLine[]; version: string }

/**
 * Which seated agents to read on this tick: those with a chat session and no
 * read still under way (`inFlight`), the one read longest ago first (never
 * read = first of all). Reads under way count against the `cap`, so there are
 * never more than that many at once. With more seated agents than the cap the
 * reads rotate, so nobody's monitor starves. Pure.
 */
export function dueDesks(
  seated: Iterable<string>, sessions: ReadonlyMap<string, string>, lastRead: ReadonlyMap<string, number>,
  inFlight: ReadonlySet<string> = new Set(), cap = MAX_PER_TICK,
): string[] {
  return [...seated].filter((id) => sessions.has(id) && !inFlight.has(id))
    .sort((a, b) => (lastRead.get(a) ?? 0) - (lastRead.get(b) ?? 0) || a.localeCompare(b))
    .slice(0, Math.max(0, cap - inFlight.size));
}

/** The chats of agents that are still on the floor; the same map when nobody left. */
export function keptChats(chats: ReadonlyMap<string, DeskChat>, sessions: ReadonlyMap<string, string>): ReadonlyMap<string, DeskChat> {
  let kept: Map<string, DeskChat> | null = null;
  for (const id of chats.keys()) {
    if (sessions.has(id)) continue;
    kept ??= new Map(chats);
    kept.delete(id);
  }
  return kept ?? chats;
}

export function useDeskChats(sessions: ReadonlyMap<string, string>, awake: boolean): ReadonlyMap<string, DeskChat> {
  const [chats, setChats] = useState<ReadonlyMap<string, DeskChat>>(new Map());
  const sessionsRef = useRef(sessions);
  sessionsRef.current = sessions;
  // An agent that left the floor takes its chat with it.
  useEffect(() => { setChats((prev) => keptChats(prev, sessions)); }, [sessions]);
  useEffect(() => {
    if (!awake) return;
    const stop = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const lastRead = new Map<string, number>();
    const inFlight = new Set<string>();
    const read = async (agentId: string) => {
      // Counted as read whatever comes of it, so a session that keeps failing cannot keep its place in every tick.
      lastRead.set(agentId, Date.now());
      inFlight.add(agentId);
      try {
        const sessionId = sessionsRef.current.get(agentId)!;
        const detail = await withReadSignal(stop.signal, (signal) => fetchAgentChatSession(sessionId, { tail: TAIL_EVENTS, signal }));
        if (stop.signal.aborted || !sessionsRef.current.has(agentId)) return;
        const chat: DeskChat = { lines: chatLines(detail.events), version: chatVersion(detail.events) };
        setChats((prev) => (prev.get(agentId)?.version === chat.version ? prev : new Map(prev).set(agentId, chat)));
      } catch (error) {
        // The monitor keeps its last good frame; the chat view itself reports real failures.
        if (!stop.signal.aborted) console.debug("Desk chat poll failed", agentId, error);
      } finally {
        inFlight.delete(agentId);
      }
    };
    const tick = () => {
      for (const id of [...lastRead.keys()]) if (!sessionsRef.current.has(id)) lastRead.delete(id);
      for (const agentId of dueDesks(seatedAtDesk, sessionsRef.current, lastRead, inFlight)) void read(agentId);
      // The next tick does not wait for these reads: one that hangs holds nothing back.
      timer = setTimeout(tick, POLL_MS + Math.random() * JITTER_MS);
    };
    timer = setTimeout(tick, Math.random() * JITTER_MS);
    return () => { stop.abort(); clearTimeout(timer); };
  }, [awake]);
  return chats;
}
