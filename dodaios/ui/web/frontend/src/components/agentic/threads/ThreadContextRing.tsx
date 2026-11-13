import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import type { ContextReading } from "@/components/agentchat/reduce";
import { fill, useI18nStore, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { ThreadMenuHeading, ThreadPopover } from "./ThreadPopover";

/** One line of Claude Code's `/context` report. */
export interface ContextCategory {
  key: string;
  label: string;
  tokens: number;
}

export interface ContextBreakdown {
  model: string;
  used: number | null;
  window: number | null;
  categories: ContextCategory[];
}

export interface ContextAnswer {
  supported: boolean;
  reading: ContextReading | null;
  breakdown: ContextBreakdown | null;
}

/** `GET /api/agent-chat/sessions/{id}/context`; null when the backend cannot say. */
export async function fetchContextWindow(sessionId: string, detail: boolean, signal?: AbortSignal): Promise<ContextAnswer | null> {
  const res = await fetch(`/api/agent-chat/sessions/${encodeURIComponent(sessionId)}/context${detail ? "?detail=true" : ""}`, { signal });
  if (!res.ok) return null;
  return (await res.json()) as ContextAnswer;
}

/** Tools Claude Code lists but does not load: they are not in the window. */
const NOT_LOADED = new Set(["deferred_tools", "deferred_mcp_tools"]);
/** The bar's order: what is fixed first, the conversation, then the room left. */
const ORDER = ["system_prompt", "system_tools", "mcp_tools", "agents", "memory", "skills", "other", "messages", "autocompact", "free"];
/** How strongly each part takes the signal blue; the conversation is the full hue. */
const SHADE: Record<string, number> = {
  system_prompt: 70, system_tools: 55, mcp_tools: 45, agents: 40, memory: 62, skills: 35, other: 30, messages: 100,
};
const KNOWN = new Set([...ORDER]);

function partColor(key: string): string {
  if (key === "free") return "hsl(var(--muted-foreground) / 0.16)";
  if (key === "autocompact") return "hsl(var(--muted-foreground) / 0.35)";
  return `rgb(var(--accent-rgb) / ${(SHADE[key] ?? 30) / 100})`;
}

/** The ring's colour: a quiet grey-blue when empty, the full signal blue when full. */
function ringColor(fraction: number): string {
  const blue = Math.round(30 + 70 * fraction);
  return `color-mix(in srgb, rgb(var(--accent-rgb)) ${blue}%, hsl(var(--muted-foreground)))`;
}

function formatTokens(value: number, locale: string): string {
  const number = (n: number, digits: number) => new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(n);
  if (value >= 1_000_000) return `${number(value / 1_000_000, 2)}M`;
  if (value >= 1_000) return `${number(value / 1_000, value < 10_000 ? 1 : 0)}k`;
  return number(value, 0);
}

function formatPercent(fraction: number): string {
  const percent = fraction * 100;
  if (percent > 0 && percent < 1) return "<1";
  return String(Math.round(percent));
}

/** The ring itself: a track, and an arc that fills clockwise from twelve o'clock. */
export function ContextRingIcon({ fraction, size = 16 }: { fraction: number; size?: number }) {
  const stroke = size / 7;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  // A thread that has used anything shows at least a sliver.
  const shown = fraction > 0 ? Math.max(fraction, 0.03) : 0;
  return <svg aria-hidden width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0" data-testid="context-ring-icon">
    <circle cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth={stroke} style={{ stroke: "hsl(var(--muted-foreground) / 0.25)" }} />
    <circle cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth={stroke} strokeLinecap="round"
      strokeDasharray={`${circumference * shown} ${circumference}`} transform={`rotate(-90 ${size / 2} ${size / 2})`}
      style={{ stroke: ringColor(fraction), transition: "stroke-dasharray 400ms ease, stroke 400ms ease" }} />
  </svg>;
}

/**
 * How full the thread's context window is, at the right end of the strip
 * under the composer. The ring fills clockwise from the top and turns bluer
 * as the window fills. Pointing at it (or a click, which keeps it open) shows
 * the numbers and what fills the window, as Claude Code itself counts it
 * (`/context`, run on an unsaved fork of the session — no model call).
 *
 * The live number comes with the thread's events; a thread that has none yet
 * reads its last answer from the CLI's own session file. Nothing is drawn
 * while the window size is unknown.
 */
export function ThreadContextRing({ sessionId, live, running, className }: {
  /** The thread; "" for a draft, which has no context yet. */
  sessionId: string;
  /** The newest reading the thread's events carried. */
  live: ContextReading | undefined;
  /** The agent is working: the breakdown is read again once it stops. */
  running: boolean;
  className: string;
}) {
  const t = useT();
  const locale = useI18nStore((state) => state.ui);
  const [recorded, setRecorded] = useState<ContextReading | null>(null);
  const [breakdown, setBreakdown] = useState<ContextBreakdown | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [hover, setHover] = useState(false);
  const [pinned, setPinned] = useState(false);
  const anchor = useRef<HTMLButtonElement | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const open = hover || pinned;

  // A thread without a live reading: its last answer, from the CLI's record.
  const needsRecord = Boolean(sessionId) && !live?.window;
  useEffect(() => {
    setRecorded(null);
    setBreakdown(null);
    if (!needsRecord) return;
    const controller = new AbortController();
    fetchContextWindow(sessionId, false, controller.signal)
      .then((answer) => { if (!controller.signal.aborted) setRecorded(answer?.reading ?? null); })
      .catch((error) => { if (!controller.signal.aborted) console.debug("context reading unavailable", error); });
    return () => controller.abort();
  }, [sessionId, needsRecord]);

  // What fills the window: asked each time the panel opens, and again when a turn ends.
  useEffect(() => {
    if (!open || !sessionId || running) return;
    const controller = new AbortController();
    setLoading(true);
    setFailed(false);
    fetchContextWindow(sessionId, true, controller.signal)
      .then((answer) => {
        if (controller.signal.aborted) return;
        setBreakdown(answer?.breakdown ?? null);
        setFailed(!answer?.breakdown);
        if (answer?.reading && !live) setRecorded(answer.reading);
      })
      .catch((error) => { if (!controller.signal.aborted) { setFailed(true); console.debug("context breakdown unavailable", error); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
    // Not on `live`: it changes with every message, the panel reads once per opening.
  }, [open, sessionId, running]);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const windowSize = live?.window || recorded?.window || breakdown?.window || 0;
  const used = live?.used ?? recorded?.used ?? breakdown?.used ?? 0;
  if (!sessionId || !windowSize || used <= 0) return null;

  const fraction = Math.min(1, Math.max(0, used / windowSize));
  const percent = formatPercent(fraction);
  const usedText = formatTokens(used, locale);
  const windowText = formatTokens(windowSize, locale);
  const label = fill(t("ide_threads.context.aria"), { percent, used: usedText, window: windowText });

  const enter = () => { window.clearTimeout(timer.current); timer.current = window.setTimeout(() => setHover(true), 120); };
  const leave = () => { window.clearTimeout(timer.current); timer.current = window.setTimeout(() => setHover(false), 220); };

  const parts = (breakdown?.categories ?? [])
    .filter((part) => !NOT_LOADED.has(part.key) && part.tokens > 0)
    .map((part) => ({ ...part, key: KNOWN.has(part.key) ? part.key : "other" }))
    .sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key));
  const total = parts.reduce((sum, part) => sum + part.tokens, 0) || windowSize;
  const reserve = parts.find((part) => part.key === "autocompact")?.tokens ?? 0;
  const compactAt = reserve > 0 && reserve < windowSize ? formatPercent((windowSize - reserve) / windowSize) : "";
  const partLabel = (part: ContextCategory) => {
    const key = `ide_threads.context.part.${part.key}`;
    const known = t(key);
    return part.key === "other" || known === key ? part.label : known;
  };

  return <>
    <button ref={anchor} type="button" className={cn(className, "shrink-0")} aria-haspopup="dialog" aria-expanded={open}
      aria-label={label} data-testid="thread-context-ring" data-percent={percent}
      onPointerEnter={enter} onPointerLeave={leave}
      onClick={() => { const next = !pinned; setPinned(next); if (!next) setHover(false); }}>
      <ContextRingIcon fraction={fraction} />
    </button>
    <ThreadPopover anchor={anchor} open={open} onClose={() => { setPinned(false); setHover(false); }}
      label={t("ide_threads.context.heading")} side="top" align="end" width={300}>
      <div onPointerEnter={enter} onPointerLeave={leave} data-testid="thread-context-details">
        <ThreadMenuHeading>{t("ide_threads.context.heading")}</ThreadMenuHeading>
        <div className="flex items-center gap-3 px-2 pb-2">
          <ContextRingIcon fraction={fraction} size={34} />
          <div className="min-w-0">
            <p className="text-sm font-medium tabular-nums text-foreground">{fill(t("ide_threads.context.used"), { percent })}</p>
            <p className="text-xs tabular-nums text-muted-foreground">{fill(t("ide_threads.context.of_tokens"), { used: usedText, window: windowText })}</p>
          </div>
        </div>

        <div className="px-2 pb-2">
          <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted" data-testid="thread-context-bar">
            {parts.length > 0
              ? parts.map((part) => <span key={part.key} className="h-full" title={partLabel(part)}
                style={{ width: `${(part.tokens / total) * 100}%`, background: partColor(part.key) }} />)
              : <span className="h-full rounded-full" style={{ width: `${fraction * 100}%`, background: ringColor(fraction) }} />}
          </div>
        </div>

        {parts.length > 0 && <ul className="px-2 pb-1" data-testid="thread-context-parts">
          {parts.map((part) => <li key={part.key} className="flex items-center gap-2 py-[3px] text-xs">
            <span aria-hidden className="h-2 w-2 shrink-0 rounded-full" style={{ background: partColor(part.key) }} />
            <span className={cn("min-w-0 flex-1 truncate", part.key === "free" ? "text-muted-foreground" : "text-foreground")}>{partLabel(part)}</span>
            <span className="shrink-0 tabular-nums text-muted-foreground">{formatTokens(part.tokens, locale)}</span>
            <span className="w-9 shrink-0 text-right tabular-nums text-muted-foreground">{formatPercent(part.tokens / total)} %</span>
          </li>)}
        </ul>}

        {loading && parts.length === 0 && <p className="flex items-center gap-1.5 px-2 pb-2 text-xs text-muted-foreground">
          <Loader2 aria-hidden className="h-3 w-3 animate-spin" />{t("ide_threads.context.loading")}
        </p>}
        {!loading && failed && parts.length === 0 && <p className="px-2 pb-2 text-xs text-muted-foreground">
          {running ? t("ide_threads.context.after_turn") : t("ide_threads.context.unavailable")}
        </p>}
        {running && parts.length === 0 && !failed && !loading && <p className="px-2 pb-2 text-xs text-muted-foreground">{t("ide_threads.context.after_turn")}</p>}
        {compactAt && <p className="border-t border-border px-2 pb-1 pt-2 text-[11px] leading-snug text-muted-foreground">
          {fill(t("ide_threads.context.compact_at"), { percent: compactAt })}
        </p>}
      </div>
    </ThreadPopover>
  </>;
}
