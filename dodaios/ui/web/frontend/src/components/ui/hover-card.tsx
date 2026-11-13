/**
 * A card beside its anchor that the pointer and the keyboard can go into.
 *
 * `QuickTooltip` only repeats text and lets the pointer pass through it. This
 * one is for a bubble that holds something to click: it opens on hover or
 * keyboard focus, and stays open while the pointer travels from the anchor
 * into the card and while it rests there.
 *
 * Three things keep it reachable:
 * - no dead strip: the card's layer starts at the anchor's edge, and the gap
 *   that shows between the two is padding of that layer;
 * - a short wait before closing, so a diagonal move that leaves both for a
 *   moment does not close it;
 * - Tab goes from the anchor into the card and back out, although the card is
 *   drawn in a portal (so a clipping rail cannot cut it off).
 */
import {
  forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState,
  type KeyboardEvent, type FocusEvent, type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/utils";

/** The same wait as a tooltip: sweeping across a rail does not flash a card per icon. */
const SHOW_DELAY_MS = 180;
/** Long enough to cross a corner between anchor and card, short enough to feel closed when the pointer left. */
const CLOSE_DELAY_MS = 250;
/** The strip between anchor and card. It belongs to the card's layer, so the pointer never leaves both. */
const GAP = 8;
const VIEWPORT_MARGIN = 8;
const FOCUSABLE = 'button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface HoverCardHandle {
  close: () => void;
}

interface Place {
  left: number;
  top: number;
  /** The card stands under the anchor (no room to its right), so the strip is on top. */
  below: boolean;
}

function place(anchor: DOMRect, layer: DOMRect): Place {
  const clampTop = (top: number) =>
    Math.min(Math.max(top, VIEWPORT_MARGIN), Math.max(VIEWPORT_MARGIN, window.innerHeight - layer.height - VIEWPORT_MARGIN));
  if (anchor.right + layer.width <= window.innerWidth - VIEWPORT_MARGIN) {
    return { left: anchor.right, top: clampTop(anchor.top + anchor.height / 2 - layer.height / 2), below: false };
  }
  const left = Math.min(Math.max(anchor.left, VIEWPORT_MARGIN), Math.max(VIEWPORT_MARGIN, window.innerWidth - layer.width - VIEWPORT_MARGIN));
  return { left, top: anchor.bottom, below: true };
}

export const HoverCard = forwardRef<HoverCardHandle, {
  /** What the card holds; its buttons and links are reachable by pointer and by Tab. */
  content: ReactNode;
  /** The card's name for a screen reader. */
  label: string;
  /** Classes for the anchor span, so this can slot into an existing layout. */
  className?: string;
  children: ReactNode;
}>(function HoverCard({ content, label, className, children }, ref) {
  const anchorRef = useRef<HTMLSpanElement | null>(null);
  const layerRef = useRef<HTMLDivElement | null>(null);
  const timerRef = useRef<number | null>(null);
  /** Focus that only comes back from the card must not open it again. */
  const quietFocusRef = useRef(false);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<Place | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const close = useCallback(() => {
    clearTimer();
    setOpen(false);
    setPosition(null);
  }, [clearTimer]);

  const show = useCallback((delay: number) => {
    clearTimer();
    if (delay <= 0) {
      setOpen(true);
      return;
    }
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      setOpen(true);
    }, delay);
  }, [clearTimer]);

  const closeSoon = useCallback(() => {
    clearTimer();
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      setOpen(false);
      setPosition(null);
    }, CLOSE_DELAY_MS);
  }, [clearTimer]);

  useImperativeHandle(ref, () => ({ close }), [close]);
  useEffect(() => clearTimer, [clearTimer]);

  // The layer has to exist to be measured: it mounts hidden and is placed before the first paint.
  useLayoutEffect(() => {
    if (!open) return;
    const anchor = anchorRef.current?.getBoundingClientRect();
    const layer = layerRef.current?.getBoundingClientRect();
    if (anchor && layer) setPosition(place(anchor, layer));
  }, [open, content]);

  const anchorTarget = () => anchorRef.current?.querySelector<HTMLElement>(FOCUSABLE) ?? null;

  useEffect(() => {
    if (!open) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (layerRef.current?.contains(document.activeElement)) {
        quietFocusRef.current = true;
        anchorTarget()?.focus();
      }
      close();
    };
    // The card stands at fixed coordinates: once the page under it moves, it points at nothing.
    const onScroll = (event: Event) => {
      if (!layerRef.current?.contains(event.target as Node)) close();
    };
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", close);
    window.addEventListener("blur", close);
    return () => {
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", close);
      window.removeEventListener("blur", close);
    };
  }, [open, close]);

  const inside = (node: EventTarget | null) =>
    node instanceof Node && (!!anchorRef.current?.contains(node) || !!layerRef.current?.contains(node));

  const onAnchorFocus = () => {
    if (quietFocusRef.current) {
      quietFocusRef.current = false;
      return;
    }
    show(0);
  };
  const onBlur = (event: FocusEvent) => {
    if (!inside(event.relatedTarget)) close();
  };

  /** Tab on the anchor goes into the card first. */
  const onAnchorKeyDown = (event: KeyboardEvent) => {
    if (event.key !== "Tab" || event.shiftKey || !open) return;
    const first = layerRef.current?.querySelector<HTMLElement>(FOCUSABLE);
    if (!first) return;
    event.preventDefault();
    first.focus();
  };

  /** Tab at the card's edge goes back to where the anchor stands in the page's order. */
  const onLayerKeyDown = (event: KeyboardEvent) => {
    if (event.key !== "Tab") return;
    const stops = Array.from(layerRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    const edge = event.shiftKey ? stops[0] : stops[stops.length - 1];
    if (document.activeElement !== edge) return;
    const target = anchorTarget();
    if (!target) return;
    quietFocusRef.current = true;
    target.focus();
    // Backwards the anchor is the stop itself. Forwards the browser goes on from it to the next stop.
    if (event.shiftKey) event.preventDefault();
    else close();
  };

  return (
    <>
      <span ref={anchorRef} className={className}
        onMouseEnter={() => show(open ? 0 : SHOW_DELAY_MS)} onMouseLeave={closeSoon}
        onFocus={onAnchorFocus} onBlur={onBlur} onKeyDown={onAnchorKeyDown}>
        {children}
      </span>
      {open && createPortal(
        <div ref={layerRef} data-testid="hover-card-layer"
          onMouseEnter={clearTimer} onMouseLeave={closeSoon} onBlur={onBlur} onKeyDown={onLayerKeyDown}
          style={{
            position: "fixed",
            left: position?.left ?? 0,
            top: position?.top ?? 0,
            paddingLeft: position?.below ? 0 : GAP,
            paddingTop: position?.below ? GAP : 0,
            visibility: position ? "visible" : "hidden",
          }}
          className="z-[70]">
          <div role="group" aria-label={label} data-testid="hover-card"
            className={cn(
              "max-w-[320px] rounded-lg border border-border-strong bg-popover px-2.5 py-1.5 text-sm text-popover-foreground shadow-float",
              position && "animate-in fade-in-0 zoom-in-95 duration-100",
            )}>
            {content}
          </div>
        </div>,
        document.body,
      )}
    </>
  );
});
