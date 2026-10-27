import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Bell } from "lucide-react";

import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { CAPTION_ICON_BUTTON, CAPTION_ICON_CLASS, CAPTION_ICON_STROKE } from "@/components/layout/captionSwitch";
import { useAgentNavigation } from "@/views/society/agentNavigation";

import { AttentionInbox } from "./AttentionInbox";
import { useAgentAttention } from "./useAgentAttention";

/** Width of the inbox panel and its distance from the window edges. */
const PANEL_W = 384;
const EDGE = 12;

/**
 * The caption button for "waiting for you": a bell with the count, and the
 * inbox under it. The count is the same one the window title carries.
 * Quiet by design: it never animates on its own, it only changes its number.
 */
export function AttentionBell({ className }: { className?: string }) {
  const t = useT();
  const { count } = useAgentAttention();
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [left, setLeft] = useState(EDGE);

  const close = useCallback((refocus = true) => {
    setOpen(false);
    if (refocus) button.current?.focus({ preventScroll: true });
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const rect = button.current?.getBoundingClientRect();
      const width = Math.min(PANEL_W, window.innerWidth - EDGE * 2);
      const center = rect ? rect.left + rect.width / 2 : window.innerWidth / 2;
      setLeft(Math.max(EDGE, Math.min(center - width / 2, window.innerWidth - width - EDGE)));
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
    // Open lands on the panel, so the keyboard can walk the list at once.
    panel.current?.focus({ preventScroll: true });
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onPointer, true);
    };
  }, [open, close]);

  // Jumping to a card closes the inbox: the card is where the answer goes.
  useEffect(() => useAgentNavigation.subscribe((state, previous) => {
    if (state.request && state.request !== previous.request) setOpen(false);
  }), []);

  const label = count > 0
    ? fill(t("agent_attention.bell_count"), { count })
    : t("agent_attention.bell");

  return (
    <>
      <button
        ref={button}
        type="button"
        onClick={() => (open ? close() : setOpen(true))}
        aria-label={label}
        title={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        data-testid="attention-bell"
        data-count={count}
        className={cn(CAPTION_ICON_BUTTON, "relative", (open || count > 0) && "text-foreground", className)}
      >
        <Bell aria-hidden className={CAPTION_ICON_CLASS} strokeWidth={CAPTION_ICON_STROKE} />
        {count > 0 && (
          <span
            aria-hidden
            data-testid="attention-bell-count"
            className="absolute -right-1.5 -top-1.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-warning px-1 text-[12px] font-semibold leading-none tabular-nums text-background ring-2 ring-background"
          >
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>
      {open && createPortal(
        <div
          ref={panel}
          role="dialog"
          aria-label={t("agent_attention.title")}
          tabIndex={-1}
          style={{ left, width: `min(${PANEL_W}px, calc(100vw - ${EDGE * 2}px))` }}
          className={cn(
            "fixed top-10 z-[150] overflow-hidden rounded-[24px] bg-popover text-popover-foreground shadow-float outline-none ring-1 ring-inset ring-border/50",
            "origin-top motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-95 motion-safe:duration-150",
          )}
        >
          <AttentionInbox onClose={() => close()} />
        </div>,
        document.body,
      )}
    </>
  );
}
