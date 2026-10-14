import { useEffect, useState } from "react";
import { EMPTY_TIMELINE, reduceEvent, reduceEvents, type Timeline, type TurnItem } from "@/components/agentchat/reduce";
import type { Translate } from "@/components/agentchat/traceEntries";
import { agentChatSocketUrl, type AgentChatEvent } from "@/lib/agentChatApi";
import { jitteredDelay, requestConnect } from "@/lib/connectBudget";
import { buildThreadRows, thoughtGist } from "../threadWork";

/**
 * What a member is doing right now, read from its own thread's event stream.
 *
 * A member of a team thread is an ordinary thread session, so its tool calls
 * and its text arrive on that session's socket as they happen. The board
 * listens only while the member's turn runs and shows the newest steps; the
 * whole conversation stays one click away in the member's thread.
 */

const RECONNECT_MS = 1500;
const RECONNECT_MAX_MS = 20_000;
/** Text streams in many small events; the board repaints at most this often. */
const PAINT_MS = 200;

/** The turn a member is in, or `null` while it has none running. */
export function useMemberTurn(sessionId: string, enabled: boolean): TurnItem | null {
  const [turn, setTurn] = useState<TurnItem | null>(null);

  useEffect(() => {
    if (!enabled || !sessionId || typeof WebSocket === "undefined") {
      setTurn(null);
      return;
    }
    let timeline: Timeline = EMPTY_TIMELINE;
    let socket: WebSocket | null = null;
    let cancelConnect: (() => void) | null = null;
    let paint: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let closed = false;

    const publish = () => {
      paint = null;
      if (closed) return;
      const last = [...timeline.items].reverse().find((item): item is TurnItem => item.type === "turn");
      setTurn(last && last.status === "running" ? last : null);
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
        // Jittered, escalating and paid for out of the shared connect budget (AP-33).
        attempt += 1;
        cancelConnect = requestConnect(connect, jitteredDelay(attempt - 1, RECONNECT_MS, RECONNECT_MAX_MS));
      };
      ws.onerror = () => { /* onclose follows and schedules the reconnect */ };
    };

    cancelConnect = requestConnect(connect, 0);
    return () => {
      closed = true;
      cancelConnect?.();
      if (paint !== null) clearTimeout(paint);
      const ws = socket;
      socket = null;
      ws?.close();
    };
  }, [sessionId, enabled]);

  return turn;
}

/** One line of a member's live feed. */
export interface LiveLine {
  id: string;
  /** A tool call, the member's own words, or a thought. */
  kind: "call" | "text" | "thought";
  text: string;
  /** A tool call's kind, for its glyph ("read", "command", "edit", …). */
  call?: string;
  running: boolean;
  failed: boolean;
}

/** The newest steps of a running turn, oldest first, at most `max`. */
export function liveLines(turn: TurnItem | null, options: { t: Translate; lang: string; max?: number }): LiveLine[] {
  if (!turn) return [];
  const lines: LiveLine[] = [];
  for (const row of buildThreadRows(turn.blocks, { t: options.t, lang: options.lang, status: turn.status })) {
    if (row.kind === "work") {
      for (const item of row.items) {
        if (item.kind === "call") {
          lines.push({
            id: item.id,
            kind: "call",
            text: [item.call.text, item.call.detail].filter(Boolean).join(" "),
            call: item.call.kind,
            running: item.call.status === "running",
            failed: item.call.status === "failed",
          });
        } else {
          lines.push({ id: item.id, kind: "thought", text: "", running: true, failed: false });
        }
      }
    } else if (row.kind === "text") {
      const text = thoughtGist(row.text);
      if (text) lines.push({ id: row.id, kind: "text", text, running: false, failed: false });
    } else if (row.kind === "thought") {
      const text = thoughtGist(row.text);
      if (text) lines.push({ id: row.id, kind: "thought", text, running: row.live, failed: false });
    }
  }
  return lines.slice(-(options.max ?? 6));
}

/** Tokens a running turn has produced so far, when its runner reports them. */
export function liveTokens(turn: TurnItem | null): number {
  const usage = turn?.liveUsage;
  if (!usage) return 0;
  return Number(usage.output_tokens ?? usage.output ?? 0) || 0;
}
