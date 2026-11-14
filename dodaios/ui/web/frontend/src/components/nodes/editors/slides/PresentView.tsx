/**
 * Present: the deck full screen from the selected slide, with the unsaved
 * edits, so the person can rehearse without leaving the editor.
 *
 * Keys as in the deck's own player: arrows, Space, Page Up/Down, Home/End;
 * N shows the speaker notes under the slide, Escape ends. A click on the
 * right two thirds goes forward, on the left third back. It asks the window
 * for full screen where the engine allows it and is a full-window layer
 * otherwise, so it works the same in the desktop app and in a browser.
 */
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, StickyNote, X } from "lucide-react";

import { fill, useT } from "@/i18n";
import { openExternalUrl } from "@/lib/openExternal";
import { cn } from "@/lib/utils";

import type { Slide } from "./deckModel";
import { linesHtml } from "./inline";
import { SlideCanvas } from "./SlideCanvas";
import { SlideView } from "./SlideView";

export interface PresentViewProps {
  slides: readonly Slide[];
  start: number;
  css: string;
  theme: "light" | "dark";
  accent: string;
  deckTitle: string;
  sections: readonly number[];
  figureOf: (index: number) => string | null;
  /** Ends the presentation on slide `at` (the editor selects it). */
  onClose: (at: number) => void;
}

export function PresentView({ slides, start, css, theme, accent, deckTitle, sections, figureOf, onClose }: PresentViewProps) {
  const t = useT();
  const root = useRef<HTMLDivElement>(null);
  const [at, setAt] = useState(() => Math.max(0, Math.min(slides.length - 1, start)));
  const [notes, setNotes] = useState(false);
  const [box, setBox] = useState({ width: 0, height: 0 });
  const count = slides.length;

  const go = useCallback((to: number) => setAt(Math.max(0, Math.min(count - 1, to))), [count]);
  const close = useCallback(() => {
    if (document.fullscreenElement) void document.exitFullscreen?.().catch(() => undefined);
    onClose(at);
  }, [at, onClose]);

  useEffect(() => {
    const el = root.current;
    el?.focus();
    // Full screen where the engine allows it; the layer already covers the window otherwise.
    el?.requestFullscreen?.().catch(() => undefined);
  }, []);

  // Leaving full screen with the system's own key or gesture ends the presentation too.
  useEffect(() => {
    let was = false;
    const onChange = () => {
      if (document.fullscreenElement) was = true;
      else if (was) onClose(at);
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, [at, onClose]);

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const read = () => setBox({ width: el.clientWidth, height: el.clientHeight });
    read();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(read);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const onKeyDown = (event: KeyboardEvent) => {
    const key = event.key;
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (key === "Escape") close();
    else if (key === "ArrowRight" || key === "ArrowDown" || key === "PageDown" || (key === " " && !event.shiftKey)) go(at + 1);
    else if (key === "ArrowLeft" || key === "ArrowUp" || key === "PageUp" || (key === " " && event.shiftKey)) go(at - 1);
    else if (key === "Home") go(0);
    else if (key === "End") go(count - 1);
    else if (key === "n" || key === "N") setNotes((on) => !on);
    else return;
    event.preventDefault();
    event.stopPropagation();
  };

  const slide = slides[at];
  const noteText = slide?.notes ?? "";
  const notesHeight = notes ? Math.min(220, Math.round(box.height * 0.28)) : 0;
  const pad = 24;
  const width = Math.max(1, Math.min(box.width - 2 * pad, ((box.height - notesHeight - 2 * pad - 48) * 16) / 9));

  return createPortal(
    <div
      ref={root}
      role="dialog"
      aria-modal="true"
      aria-label={t("nodes.editor.slides.present.label")}
      tabIndex={-1}
      onKeyDown={onKeyDown}
      className="fixed inset-0 z-[100] flex flex-col bg-black text-white outline-none"
      data-testid="slides-present"
    >
      <div
        className="flex min-h-0 flex-1 items-center justify-center"
        onClick={(event) => {
          // A link on a slide opens outside the app; elsewhere the click moves on.
          const path = event.nativeEvent.composedPath();
          const link = path.find((el): el is HTMLAnchorElement => el instanceof HTMLAnchorElement && !!el.href);
          if (link) {
            event.preventDefault();
            void openExternalUrl(link.href);
            return;
          }
          const rect = event.currentTarget.getBoundingClientRect();
          const x = (event.clientX - rect.left) / Math.max(1, rect.width);
          go(x < 1 / 3 ? at - 1 : at + 1);
        }}
      >
        {slide && box.width > 0 && (
          <SlideCanvas css={css} width={width} theme={theme} accent={accent} presenting className="overflow-hidden rounded-md">
            <SlideView slide={slide} index={at} deckTitle={deckTitle} section={sections[at] ?? 0} figure={figureOf(at)} />
          </SlideCanvas>
        )}
      </div>
      {notes && (
        <div
          className="shrink-0 overflow-y-auto border-t border-white/15 bg-neutral-950 px-6 py-3 text-base leading-7 text-white/90"
          style={{ height: notesHeight }}
          data-testid="slides-present-notes"
        >
          {noteText ? (
            // The notes as the page draws them (escaped, the same few inline marks).
            <div dangerouslySetInnerHTML={{ __html: linesHtml(noteText) }} />
          ) : (
            <p className="text-white/50">{t("nodes.editor.slides.notes.none")}</p>
          )}
        </div>
      )}
      <div className="flex h-12 shrink-0 items-center justify-between gap-2 px-3 text-sm text-white/70">
        <span className="min-w-0 truncate">{deckTitle}</span>
        <div className="flex items-center gap-1">
          <PresentButton label={t("nodes.editor.slides.present.previous")} onClick={() => go(at - 1)} disabled={at === 0}>
            <ChevronLeft className="h-4 w-4" aria-hidden />
          </PresentButton>
          <span className="min-w-[64px] text-center tabular-nums" aria-live="polite">
            {fill(t("nodes.editor.slides.present.position"), { n: at + 1, total: count })}
          </span>
          <PresentButton label={t("nodes.editor.slides.present.next")} onClick={() => go(at + 1)} disabled={at === count - 1}>
            <ChevronRight className="h-4 w-4" aria-hidden />
          </PresentButton>
        </div>
        <div className="flex items-center gap-1">
          <PresentButton label={t("nodes.editor.slides.present.notes")} onClick={() => setNotes((on) => !on)} pressed={notes}>
            <StickyNote className="h-4 w-4" aria-hidden />
          </PresentButton>
          <PresentButton label={t("nodes.editor.slides.present.end")} onClick={close} testId="slides-present-end">
            <X className="h-4 w-4" aria-hidden />
          </PresentButton>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function PresentButton({
  label,
  onClick,
  disabled,
  pressed,
  testId,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  pressed?: boolean;
  testId?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      disabled={disabled}
      data-testid={testId}
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      className={cn(
        "grid h-8 w-8 place-items-center rounded-md text-white/80 hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 disabled:opacity-30",
        pressed && "bg-white/15 text-white",
      )}
    >
      {children}
    </button>
  );
}
