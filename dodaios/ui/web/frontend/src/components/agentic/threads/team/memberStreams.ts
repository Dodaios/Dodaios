import { useCallback, useSyncExternalStore } from "react";
import { EMPTY_TIMELINE, reduceEvent, reduceEvents, type Timeline, type TurnItem } from "@/components/agentchat/reduce";
import { agentChatSocketUrl, type AgentChatEvent } from "@/lib/agentChatApi";
import { jitteredDelay, requestConnect } from "@/lib/connectBudget";

/**
 * Each team member's own conversation, read from its thread's event stream.
 *
 * A member is an ordinary thread session, so its turns, tool calls and text
 * arrive on that session's socket as they happen. The team room reads one
 * member from several places at once (its node on the canvas, its chat in the
 * side column), and they all share ONE socket per member: the stream opens
 * with its first reader and closes a moment after its last one leaves, so a
 * tab switch does not reconnect. Every (re)connect is jittered and paid for
 * out of the shared connect budget (AP-33).
 */

const RECONNECT_MS = 1500;
const RECONNECT_MAX_MS = 20_000;
/** Text streams in many small events; readers repaint at most this often. */
const PAINT_MS = 200;
/** How long a stream nobody reads stays open, so switching back does not reconnect. */
const LINGER_MS = 4000;

interface Stream {
  /** What the readers see; replaced at most every PAINT_MS. */
  shown: Timeline;
  readers: Set<() => void>;
  stop: () => void;
  linger: ReturnType<typeof setTimeout> | null;
}

const streams = new Map<string, Stream>();

function open(sessionId: string): Stream {
  let timeline: Timeline = EMPTY_TIMELINE;
  let socket: WebSocket | null = null;
  let cancelConnect: (() => void) | null = null;
  let paint: ReturnType<typeof setTimeout> | null = null;
  let attempt = 0;
  let closed = false;

  const stream: Stream = { shown: EMPTY_TIMELINE, readers: new Set(), stop: () => {}, linger: null };
  const publish = () => {
    paint = null;
    if (closed) return;
    stream.shown = timeline;
    for (const reader of [...stream.readers]) reader();
  };
  const schedule = () => {
    if (paint === null) paint = setTimeout(publish, PAINT_MS);
  };

  const connect = () => {
    cancelConnect = null;
    if (closed) return;
    const afterSeq = timeline.lastSeq;
    const ws = new WebSocket(agentChatSocketUrl(sessionId, afterSeq));
    socket = ws;
    ws.onopen = () => { attempt = 0; };
    ws.onmessage = (message) => {
      if (socket !== ws) return;
      let frame: { type?: string; events?: AgentChatEvent[]; event?: AgentChatEvent };
      try {
        frame = JSON.parse(String(message.data));
      } catch {
        return; // not a frame of this protocol
      }
      if (frame.type === "snapshot") {
        // After a reconnect the snapshot only carries what was missed.
        timeline = reduceEvents(afterSeq > 0 ? timeline : EMPTY_TIMELINE, frame.events ?? []);
        schedule();
      } else if (frame.type === "event" && frame.event) {
        timeline = reduceEvent(timeline, frame.event);
        schedule();
      }
    };
    ws.onclose = () => {
      if (socket !== ws || closed) return;
      socket = null;
      attempt += 1;
      cancelConnect = requestConnect(connect, jitteredDelay(attempt - 1, RECONNECT_MS, RECONNECT_MAX_MS));
    };
    ws.onerror = () => { /* onclose follows and schedules the reconnect */ };
  };

  cancelConnect = requestConnect(connect, 0);
  stream.stop = () => {
    closed = true;
    cancelConnect?.();
    if (paint !== null) clearTimeout(paint);
    const ws = socket;
    socket = null;
    ws?.close();
  };
  return stream;
}

function subscribe(sessionId: string, reader: () => void): () => void {
  let stream = streams.get(sessionId);
  if (!stream) {
    stream = open(sessionId);
    streams.set(sessionId, stream);
  }
  if (stream.linger !== null) {
    clearTimeout(stream.linger);
    stream.linger = null;
  }
  stream.readers.add(reader);
  const mine = stream;
  return () => {
    mine.readers.delete(reader);
    if (mine.readers.size > 0 || mine.linger !== null) return;
    mine.linger = setTimeout(() => {
      mine.linger = null;
      if (mine.readers.size > 0 || streams.get(sessionId) !== mine) return;
      streams.delete(sessionId);
      mine.stop();
    }, LINGER_MS);
  };
}

const noop = () => () => {};

/** A member's whole conversation as it streams in; empty while `enabled` is false. */
export function useMemberTimeline(sessionId: string, enabled: boolean): Timeline {
  const on = enabled && Boolean(sessionId) && typeof WebSocket !== "undefined";
  const listen = useCallback((reader: () => void) => (on ? subscribe(sessionId, reader) : noop()), [sessionId, on]);
  const read = useCallback(() => (on ? streams.get(sessionId)?.shown ?? EMPTY_TIMELINE : EMPTY_TIMELINE), [sessionId, on]);
  return useSyncExternalStore(listen, read, read);
}

/** The turn a member is in, or `null` while it has none running. */
export function runningTurnOf(timeline: Timeline): TurnItem | null {
  for (let index = timeline.items.length - 1; index >= 0; index -= 1) {
    const item = timeline.items[index];
    if (item.type === "turn") return item.status === "running" ? item : null;
  }
  return null;
}

/** For tests: drop every open stream at once. */
export function closeAllMemberStreams(): void {
  for (const stream of streams.values()) {
    if (stream.linger !== null) clearTimeout(stream.linger);
    stream.stop();
  }
  streams.clear();
}
