import { useEffect, useMemo, useState } from "react";
import type { TurnItem } from "@/components/agentchat/reduce";
import { fill, useT } from "@/i18n";
import type { TeamMember } from "@/lib/teamThreadsApi";
import type { Translate } from "@/components/agentchat/traceEntries";
import { buildThreadRows, thoughtGist } from "../threadWork";
import { runningTurnOf, useMemberTimeline } from "./memberStreams";

/**
 * What a member is doing right now, in a few lines: its newest tool calls and
 * words, read from its own thread's stream (`memberStreams`).
 */

/** The turn a member is in, or `null` while it has none running. */
export function useMemberTurn(sessionId: string, enabled: boolean): TurnItem | null {
  return runningTurnOf(useMemberTimeline(sessionId, enabled));
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

function useSeconds(sinceMs: number, on: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!on) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [on]);
  return sinceMs > 0 ? Math.max(0, Math.floor((now - sinceMs) / 1000)) : 0;
}

export const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

/** A member's state in one line: what it does right now, or why it does nothing. */
export function useMemberStatus(member: TeamMember, over: boolean) {
  const t = useT();
  const lang = t("trace_report.locale");
  const left = member.state === "left";
  const working = member.working && !left;
  const turn = useMemberTurn(member.session_id, working);
  const seconds = useSeconds(member.since_ms, working);
  const action = useMemo(() => liveLines(turn, { t, lang, max: 1 })[0] ?? null, [turn, t, lang]);
  const doing = action?.kind === "call" ? plainCommand(action.text) : action?.text ?? "";
  const text = left ? (member.left_reason ? fill(t("team_threads.room.left_because"), { reason: member.left_reason }) : t("team_threads.room.left"))
    : member.waiting ? t("team_threads.room.waits")
      : working ? (doing || t(action ? "team_threads.live_thinking" : "team_threads.live_starting"))
        : over ? t("team_threads.room.finished") : t("team_threads.room.idle");
  const tone: "working" | "waiting" | "idle" | "left" = left ? "left" : member.waiting ? "waiting" : working ? "working" : "idle";
  return { text, tone, seconds, call: action?.kind === "call" };
}

/**
 * A shell call without its shell: `"C:\…\powershell.exe" -Command "pytest -q"`
 * reads as `pytest -q`. Anything else comes back as it was.
 */
export function plainCommand(text: string): string {
  const match = /^(?:"[^"]*?|[^"\s]*?)(?:powershell|pwsh|bash|sh|cmd)(?:\.exe)?"?\s+(?:-NoProfile\s+)?(?:-Command|-lc|-c|\/c)\s+([\s\S]+)$/i.exec(text.trim());
  if (!match) return text;
  const inner = match[1].trim();
  const quote = /^["']/.exec(inner)?.[0];
  if (!quote) return inner;
  // A long call is cut short with an ellipsis, so its closing quote may be gone.
  return inner.slice(1).replace(new RegExp(`${quote}(…?)$`), "$1");
}
