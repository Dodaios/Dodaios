import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { clsx } from "clsx";
import { X } from "lucide-react";

import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { useNavSidebarStore } from "@/store/navSidebar";

import {
  useStatusLightStore,
  watchStatusLight,
  type StatusFinding,
  type StatusRow,
  type StatusTrouble,
} from "./statusLightStore";
import { StatusGroup, StatusTroubleGroup, goToStatusRow } from "./statusRows";

/** Width of the popover and its distance from the window edges. */
const PANEL_W = 340;
const EDGE = 12;

/**
 * The glanceable status light in the window caption: "2 running · 1 needs you".
 *
 * It stands in for a pile of notifications: one calm chip to look at when the
 * person chooses to. It never pops up, animates, sounds or toasts on its own;
 * only its words change. A subtle amber dot says a login or usage limit is in
 * trouble. Clicking opens a compact list; each row goes to its place (a card in
 * the conversation, the Agentic IDE, the board).
 *
 * Beside the conversation the open sidebar lists the same rows itself
 * (`SidebarStatus`), so there the chip steps aside rather than say it twice.
 */
export function StatusLight({ className }: { className?: string }) {
  const t = useT();
  const light = useStatusLightStore((s) => s.light);
  const error = useStatusLightStore((s) => s.error);
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [left, setLeft] = useState(EDGE);
  const onConversation = useEventStore((s) => s.activeSection === "chats");
  const sidebarOpen = !useNavSidebarStore((s) => s.collapsed);
  const inSidebar = onConversation && sidebarOpen;

  useEffect(() => watchStatusLight(), []);

  const close = useCallback((refocus = true) => {
    setOpen(false);
    if (refocus) button.current?.focus({ preventScroll: true });
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const rect = button.current?.getBoundingClientRect();
      const width = Math.min(PANEL_W, window.innerWidth - EDGE * 2);
      const right = rect ? rect.right : window.innerWidth - EDGE;
      setLeft(Math.max(EDGE, Math.min(right - width, window.innerWidth - width - EDGE)));
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    };
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target && (panel.current?.contains(target) || button.current?.contains(target))) return;
      close(false);
    };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onPointer, true);
    panel.current?.focus({ preventScroll: true });
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onPointer, true);
    };
  }, [open, close]);

  const running = light?.counts.running ?? 0;
  const needs = light?.counts.needs_you ?? 0;
  const warn = light?.tone === "warn";
  const parts: string[] = [];
  if (running > 0) parts.push(fill(t("status_light.summary_running"), { count: running }));
  if (needs > 0) parts.push(fill(t("status_light.summary_needs"), { count: needs }));
  const summary = parts.length > 0 ? parts.join(" · ") : t("status_light.idle");

  const go = (row: StatusRow) => {
    goToStatusRow(row);
    setOpen(false);
  };

  if (inSidebar) return null;

  return (
    <>
      <button
        ref={button}
        type="button"
        onClick={() => (open ? close() : setOpen(true))}
        aria-label={`${t("status_light.label")}: ${summary}`}
        title={summary}
        aria-haspopup="dialog"
        aria-expanded={open}
        data-testid="status-light"
        data-running={running}
        data-needs-you={needs}
        data-tone={warn ? "warn" : "calm"}
        // `clsx`, not `cn`: tailwind-merge would read `text-body` as a colour.
        className={clsx(
          "pointer-events-auto mx-1 inline-flex h-6 shrink-0 items-center gap-1.5 self-center rounded-full px-2.5",
          "text-body transition-colors duration-150 hover:bg-secondary/70 hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          needs > 0 || open ? "text-foreground" : "text-muted-foreground",
          className,
        )}
      >
        <span
          aria-hidden
          data-testid="status-light-dot"
          className={cn(
            "h-2 w-2 shrink-0 rounded-full",
            warn ? "bg-warning" : running > 0 || needs > 0 ? "bg-primary" : "bg-muted-foreground/40",
          )}
        />
        <span className="hidden whitespace-nowrap tabular-nums md:inline" data-testid="status-light-text">
          {summary}
        </span>
      </button>
      {open && createPortal(
        <div
          ref={panel}
          role="dialog"
          aria-label={t("status_light.title")}
          tabIndex={-1}
          data-testid="status-light-panel"
          style={{ left, width: `min(${PANEL_W}px, calc(100vw - ${EDGE * 2}px))` }}
          className={cn(
            "fixed top-10 z-[150] overflow-hidden rounded-xl border border-border bg-popover text-popover-foreground shadow-float outline-none",
            "origin-top motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-95 motion-safe:duration-150",
          )}
        >
          <StatusPanel
            needs={light?.needs_you ?? []}
            running={light?.running ?? []}
            trouble={light?.trouble ?? []}
            findings={light?.findings ?? []}
            loaded={light !== null}
            error={error}
            onGo={go}
            onClose={() => close()}
          />
        </div>,
        document.body,
      )}
    </>
  );
}

function StatusPanel({
  needs,
  running,
  trouble,
  findings,
  loaded,
  error,
  onGo,
  onClose,
}: {
  needs: StatusRow[];
  running: StatusRow[];
  trouble: StatusTrouble[];
  findings: StatusFinding[];
  loaded: boolean;
  error: boolean;
  onGo: (row: StatusRow) => void;
  onClose: () => void;
}) {
  const t = useT();
  const empty = needs.length === 0 && running.length === 0 && trouble.length === 0 && findings.length === 0;
  return (
    <div className="flex max-h-[min(70vh,520px)] min-h-0 flex-col" data-testid="status-light-content">
      <header className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <h2 className="m-0 flex-1 text-base font-semibold text-foreground-strong">{t("status_light.title")}</h2>
        <button type="button" onClick={onClose} aria-label={t("status_light.close")} title={t("status_light.close")}
          className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <X aria-hidden className="h-4 w-4" />
        </button>
      </header>
      <div className="chat-scroller min-h-0 flex-1 overflow-y-auto px-2 py-3">
        {!loaded ? (
          <p role={error ? "alert" : "status"} className="px-3 py-6 text-center text-[13px] text-muted-foreground">
            {error ? t("status_light.unavailable") : "…"}
          </p>
        ) : empty ? (
          <p className="m-0 px-3 py-6 text-center text-[13px] text-muted-foreground" data-testid="status-light-empty">
            {t("status_light.empty")}
          </p>
        ) : (
          <>
            <StatusGroup title={t("status_light.needs_heading")} rows={needs} onGo={onGo} testId="status-light-needs" />
            <StatusGroup title={t("status_light.running_heading")} rows={running} running onGo={onGo} testId="status-light-running" />
            <StatusTroubleGroup trouble={trouble} findings={findings} testId="status-light-trouble" onNavigate={onClose} />
          </>
        )}
      </div>
    </div>
  );
}
