import type { ChatAttachment } from "@/lib/agentChatApi";
import type { TimelineItem, UserItem } from "./reduce";

/**
 * A message the person sent that the conversation has not recorded yet.
 *
 * The backend writes the person's `user_message` only after it has prepared
 * the turn (the seat, the screen context, the history), and the socket then
 * carries it here. That took about a second, and for that second Enter seemed
 * to do nothing: the box was empty and the chat had not moved (maintainer,
 * 2026-11-16). The outbox draws the message, and the assistant typing under
 * it, the moment it is sent; its own event replaces it when it arrives.
 */
export interface OutboxEntry {
  /** Local id; also the id of the drawn message. */
  id: string;
  /** The chat it went to; null while a new chat's session is still being created. */
  sessionId: string | null;
  item: UserItem;
}

/**
 * How much earlier than the send the backend's stamp on the same message may
 * read. The two clocks are one machine's, but the browser stamps the send
 * before the request leaves; a little room keeps a rounding from hiding the
 * match, and an identical older message from counting as this one.
 */
const CLOCK_ROOM_MS = 2_000;

let counter = 0;

/** The drawn message for a send, built from what the composer held. */
export function outboxEntry(sessionId: string | null, text: string, attachments: readonly ChatAttachment[], nowMs: number): OutboxEntry {
  counter += 1;
  const id = `local-send-${nowMs}-${counter}`;
  return {
    id,
    sessionId,
    item: {
      type: "user",
      id,
      text,
      attachments: attachments.map((file) => ({ name: file.name, kind: file.kind, describedBy: file.described_by })),
      tsMs: nowMs,
    },
  };
}

/**
 * The entries whose own message is in `items` now. Each recorded message
 * answers one entry, oldest first, so two identical messages sent one after
 * the other each wait for their own.
 */
export function recordedEntries(entries: readonly OutboxEntry[], items: readonly TimelineItem[]): Set<string> {
  const done = new Set<string>();
  if (!entries.length) return done;
  const taken = new Set<string>();
  for (const entry of entries) {
    const match = items.find((item) => item.type === "user" && !item.origin && !taken.has(item.id)
      && item.text === entry.item.text && item.tsMs >= entry.item.tsMs - CLOCK_ROOM_MS);
    if (!match) continue;
    taken.add(match.id);
    done.add(entry.id);
  }
  return done;
}

/** The entries still waiting for their own message; `entries` itself when none arrived. */
export function pendingEntries(entries: readonly OutboxEntry[], items: readonly TimelineItem[]): readonly OutboxEntry[] {
  const done = recordedEntries(entries, items);
  return done.size ? entries.filter((entry) => !done.has(entry.id)) : entries;
}

/** The conversation as drawn: what was recorded, then this chat's messages still on their way. */
export function withOutbox(items: TimelineItem[], entries: readonly OutboxEntry[] | undefined, sessionId: string | null): TimelineItem[] {
  if (!entries?.length) return items;
  const mine = entries.filter((entry) => entry.sessionId === sessionId);
  if (!mine.length) return items;
  const waiting = pendingEntries(mine, items);
  return waiting.length ? [...items, ...waiting.map((entry) => entry.item)] : items;
}
