import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowDown, X } from "lucide-react";
import { fill, useT } from "@/i18n";
import type { TimelineItem } from "../reduce";
import { plural } from "../traceEntries";
import { localeForUiLanguage } from "@/components/runs/format";
import { announcementFor, openQuestionText, runSnapshot, type RunSnapshot } from "./runAnnouncer";
import { stampLabel } from "./transcriptTime";
import "./runView.css";

/**
 * The small aids a long transcript needs: time stamps that mark a pause, a
 * "N new" pill for a reader who scrolled up, rows that grow smoothly, and a
 * quiet live region that tells a screen reader when the agent starts,
 * replies, finishes, stops or asks.
 */

/** A pause in the conversation, as a hairline with the time in the middle. */
export function TranscriptStamp({ ms }: { ms: number }) {
  const t = useT();
  // The UI language, read through the dictionary like every trace line.
  const locale = localeForUiLanguage(t("trace_report.locale"));
  const label = stampLabel(ms, Date.now(), locale, t);
  return <p className="run-stamp" data-testid="transcript-stamp">
    <time dateTime={new Date(ms).toISOString()}>{label}</time>
  </p>;
}

/** Items that count as "new" for a reader who scrolled away. */
function countable(item: TimelineItem): boolean {
  return item.type === "turn" || item.type === "user" || item.type === "internal" || item.type === "notice";
}

/** How many countable items are not in `seen`. */
export function countUnseen(items: readonly TimelineItem[], seen: ReadonlySet<string>): number {
  let n = 0;
  for (const item of items) if (countable(item) && !seen.has(item.id)) n += 1;
  return n;
}

/**
 * Counts what arrived while the reader was away from the end. Everything on
 * screen while they sit at the end is seen; dismissing the pill marks the
 * rest seen too.
 */
export function useUnseen(items: readonly TimelineItem[], atEnd: boolean): { count: number; dismiss: () => void } {
  const seen = useRef<Set<string>>(new Set());
  const [, bump] = useState(0);
  if (atEnd) {
    for (const item of items) seen.current.add(item.id);
  }
  return {
    count: atEnd ? 0 : countUnseen(items, seen.current),
    dismiss: () => {
      for (const item of items) seen.current.add(item.id);
      bump((n) => n + 1);
    },
  };
}

/** True while the scroller sits more than `px` above its end. */
export function useFarFromEnd(el: HTMLElement | null, px = 80): boolean {
  const [far, setFar] = useState(false);
  useEffect(() => {
    if (!el) return;
    const read = () => setFar(el.scrollHeight - el.scrollTop - el.clientHeight > px);
    read();
    el.addEventListener("scroll", read, { passive: true });
    return () => el.removeEventListener("scroll", read);
  }, [el, px]);
  return far;
}

/** "3 new messages ↓" with a dismiss ×, floating over the conversation's end. */
export function CatchUpPill({ count, onJump, onDismiss }: { count: number; onJump: () => void; onDismiss: () => void }) {
  const t = useT();
  const lang = t("trace_report.locale");
  const label = fill(t(`run_view.pill.new_${plural(lang, count)}`), { count });
  return <div className="run-pill" data-testid="transcript-new-pill">
    <button type="button" className="run-pill-main" onClick={onJump}>
      <span>{label}</span>
      <ArrowDown aria-hidden className="h-3.5 w-3.5" />
    </button>
    <button type="button" className="run-pill-close" onClick={onDismiss} aria-label={t("run_view.pill.dismiss")} title={t("run_view.pill.dismiss")}>
      <X aria-hidden className="h-3 w-3" />
    </button>
  </div>;
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** How long a row takes to settle into its new height. */
export const SETTLE_MS = 200;

/**
 * A row that glides to its new height instead of jumping, while `active`
 * (the live turn). The inner box is measured; the outer box animates from
 * the old height to the new one and lets go when it arrives. Off with
 * reduced motion and where there is no ResizeObserver.
 */
export function SettleBox({ active, children, className }: { active: boolean; children: ReactNode; className?: string }) {
  const outer = useRef<HTMLDivElement | null>(null);
  const inner = useRef<HTMLDivElement | null>(null);
  const last = useRef(0);
  useLayoutEffect(() => {
    const box = outer.current;
    const content = inner.current;
    if (!active || !box || !content || typeof ResizeObserver === "undefined" || prefersReducedMotion()) return;
    last.current = content.offsetHeight;
    let timer = 0;
    const ro = new ResizeObserver(() => {
      const next = content.offsetHeight;
      const from = box.getBoundingClientRect().height || last.current;
      last.current = next;
      if (next <= from + 1) {
        box.style.height = "";
        box.style.overflow = "";
        return;
      }
      box.style.transition = "none";
      box.style.height = `${from}px`;
      box.style.overflow = "clip";
      void box.offsetHeight;
      box.style.transition = `height ${SETTLE_MS}ms cubic-bezier(0.2, 0, 0, 1)`;
      box.style.height = `${next}px`;
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        box.style.transition = "";
        box.style.height = "";
        box.style.overflow = "";
      }, SETTLE_MS + 20);
    });
    ro.observe(content);
    return () => {
      ro.disconnect();
      window.clearTimeout(timer);
      box.style.transition = "";
      box.style.height = "";
      box.style.overflow = "";
    };
  }, [active]);
  return <div ref={outer} className={className}><div ref={inner} className="flex flex-col gap-2">{children}</div></div>;
}

/**
 * The live region: one sentence per lifecycle change of the newest turn.
 * The first snapshot after mounting is only remembered, so opening a chat
 * never reads out old news.
 */
export function RunAnnouncer({ items, agentName }: { items: readonly TimelineItem[]; agentName: string }) {
  const t = useT();
  const snapshot = useMemo(() => runSnapshot(items), [items]);
  const question = useMemo(() => openQuestionText(items, snapshot), [items, snapshot]);
  const prev = useRef<RunSnapshot | null | undefined>(undefined);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (prev.current === undefined) {
      prev.current = snapshot;
      return;
    }
    const said = announcementFor(prev.current, snapshot, question);
    prev.current = snapshot;
    if (said) setMessage(fill(t(said.key), { agent: agentName, question: said.detail }));
  }, [snapshot, question, agentName, t]);
  return <p className="sr-only" role="status" aria-live="polite" data-testid="run-announcer">{message}</p>;
}
