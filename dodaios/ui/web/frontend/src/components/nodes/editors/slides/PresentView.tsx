/**
 * Present: the deck full screen from the selected slide (or the first), with
 * the unsaved edits, so the person can rehearse without leaving the editor.
 *
 * Like the deck's own player: arrows, Space, Page Up/Down, Home/End; a
 * slide's elements that wait for a click come in one per step before the
 * next slide; hidden slides are skipped; each slide comes in with its
 * transition. N shows the speaker notes under the slide, P switches to the
 * presenter view (this slide, the next one, the notes, a timer and the
 * clock), B and W blank the screen black or white, Escape ends.
 *
 * It asks the window for full screen where the engine allows it and is a
 * full-window layer otherwise, so it works the same in the desktop app and in
 * a browser.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, MonitorPlay, RotateCcw, StickyNote, X } from "lucide-react";

import { fill, useT } from "@/i18n";
import { openExternalUrl } from "@/lib/openExternal";
import { cn } from "@/lib/utils";

import type { Slide } from "./deckModel";
import { BuiltContext } from "./elements";
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
  /** The deck's default transition (a slide's own wins). */
  transition?: string;
  /** Open in the presenter view. */
  presenter?: boolean;
  /** Ends the presentation on slide `at` (the editor selects it). */
  onClose: (at: number) => void;
}

const MOTION_CSS = `
@keyframes pv-fade{from{opacity:0}}
@keyframes pv-slide{from{transform:translateX(100%)}}
@keyframes pv-slide-back{from{transform:translateX(-100%)}}
@keyframes pv-rise{from{opacity:0;transform:translateY(48px)}}
@keyframes pv-zoom{from{opacity:0;transform:scale(.9)}}
@keyframes pv-default{from{opacity:0;transform:translateX(18px)}}
@keyframes pv-default-back{from{opacity:0;transform:translateX(-18px)}}
.pv-in{animation:.45s cubic-bezier(.2,.7,.2,1) both}
.pv-fade{animation-name:pv-fade}.pv-slide{animation-name:pv-slide;animation-duration:.55s}
.pv-slide-back{animation-name:pv-slide-back;animation-duration:.55s}.pv-rise{animation-name:pv-rise}
.pv-zoom{animation-name:pv-zoom}.pv-default{animation-name:pv-default;animation-duration:.32s}
.pv-default-back{animation-name:pv-default-back;animation-duration:.32s}
@media (prefers-reduced-motion:reduce){.pv-in{animation:none!important}}
`;

function clicksOf(slide: Slide | undefined): number {
  return (slide?.elements ?? []).filter((element) => element.anim && element.click).length;
}

function clock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const two = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${two(m)}:${two(s)}` : `${two(m)}:${two(s)}`;
}

export function PresentView({
  slides,
  start,
  css,
  theme,
  accent,
  deckTitle,
  sections,
  figureOf,
  transition = "",
  presenter: presenterAtStart = false,
  onClose,
}: PresentViewProps) {
  const t = useT();
  const root = useRef<HTMLDivElement>(null);
  const count = slides.length;
  const [at, setAt] = useState(() => Math.max(0, Math.min(count - 1, start)));
  const [built, setBuilt] = useState(0);
  const [dir, setDir] = useState<"fwd" | "back">("fwd");
  const [notes, setNotes] = useState(false);
  const [presenter, setPresenter] = useState(presenterAtStart);
  const [blank, setBlank] = useState<"" | "black" | "white">("");
  const [box, setBox] = useState({ width: 0, height: 0 });
  const [began, setBegan] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());

  const visible = useCallback(
    (from: number, step: number) => {
      let i = from;
      while (i >= 0 && i < count && slides[i]?.hidden) i += step;
      return i;
    },
    [count, slides],
  );

  const forward = useCallback(() => {
    if (blank) {
      setBlank("");
      return;
    }
    if (built < clicksOf(slides[at])) {
      setBuilt((n) => n + 1);
      return;
    }
    const to = visible(at + 1, 1);
    if (to < count) {
      setDir("fwd");
      setAt(to);
      setBuilt(0);
    }
  }, [at, blank, built, count, slides, visible]);

  const back = useCallback(() => {
    if (blank) {
      setBlank("");
      return;
    }
    const to = visible(at - 1, -1);
    if (to >= 0) {
      setDir("back");
      setAt(to);
      setBuilt(clicksOf(slides[to]));
    }
  }, [at, blank, slides, visible]);

  const go = useCallback(
    (to: number) => {
      const target = Math.max(0, Math.min(count - 1, to));
      setDir(target < at ? "back" : "fwd");
      setAt(target);
      setBuilt(0);
    },
    [at, count],
  );

  const close = useCallback(() => {
    if (document.fullscreenElement) void document.exitFullscreen?.().catch(() => undefined);
    onClose(at);
  }, [at, onClose]);

  useEffect(() => {
    const el = root.current;
    el?.focus();
    el?.requestFullscreen?.().catch(() => undefined);
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  // Leaving full screen with the system's own key or gesture ends the presentation too.
  const atRef = useRef(at);
  atRef.current = at;
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    let was = false;
    const onChange = () => {
      if (document.fullscreenElement) was = true;
      else if (was) closeRef.current(atRef.current);
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

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
    if (key === "Escape") {
      if (blank) setBlank("");
      else close();
    } else if (key === "ArrowRight" || key === "ArrowDown" || key === "PageDown" || key === "Enter" || (key === " " && !event.shiftKey)) forward();
    else if (key === "ArrowLeft" || key === "ArrowUp" || key === "PageUp" || key === "Backspace" || (key === " " && event.shiftKey)) back();
    else if (key === "Home") go(visible(0, 1) % Math.max(1, count));
    else if (key === "End") {
      const last = visible(count - 1, -1);
      go(last < 0 ? count - 1 : last);
    }
    else if (key === "n" || key === "N") setNotes((on) => !on);
    else if (key === "p" || key === "P") setPresenter((on) => !on);
    else if (key === "b" || key === "B" || key === ".") setBlank((b) => (b === "black" ? "" : "black"));
    else if (key === "w" || key === "W" || key === ",") setBlank((b) => (b === "white" ? "" : "white"));
    else return;
    event.preventDefault();
    event.stopPropagation();
  };

  const slide = slides[at];
  const next = visible(at + 1, 1);
  const motion = slide?.transition || transition;
  const motionClass = useMemo(() => {
    if (motion === "none") return "";
    if (motion === "fade") return "pv-fade";
    if (motion === "slide") return dir === "back" ? "pv-slide-back" : "pv-slide";
    if (motion === "rise") return "pv-rise";
    if (motion === "zoom") return "pv-zoom";
    return dir === "back" ? "pv-default-back" : "pv-default";
  }, [motion, dir]);

  const onStageClick = (event: React.MouseEvent<HTMLDivElement>) => {
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
    if (x < 1 / 3) back();
    else forward();
  };

  const drawn = (index: number, width: number, live: boolean) => {
    const target = slides[index];
    if (!target || width <= 0) return null;
    return (
      <BuiltContext.Provider value={live ? built : 1_000}>
        <SlideCanvas css={css} width={width} theme={theme} accent={accent} presenting={live} className="overflow-hidden rounded-md">
          <SlideView slide={target} index={index} deckTitle={deckTitle} section={sections[index] ?? 0} figure={figureOf(index)} />
        </SlideCanvas>
      </BuiltContext.Provider>
    );
  };

  const noteText = slide?.notes ?? "";
  const notesHeight = notes && !presenter ? Math.min(220, Math.round(box.height * 0.28)) : 0;
  const pad = 24;
  const bar = 48;
  let stage: ReactNode;
  if (presenter) {
    const mainWidth = Math.max(1, Math.min(box.width * 0.62 - 2 * pad, ((box.height - bar - 2 * pad) * 16) / 9));
    const sideWidth = Math.max(1, Math.min(box.width * 0.38 - 2 * pad, 440));
    stage = (
      <div className="flex min-h-0 flex-1 gap-6 px-6 py-4" data-testid="slides-presenter">
        <div className="flex min-w-0 flex-[62] items-center justify-center" onClick={onStageClick}>
          <div key={`${at}`} className={cn("pv-in", motionClass)}>
            {drawn(at, mainWidth, true)}
          </div>
        </div>
        <div className="flex min-w-0 flex-[38] flex-col gap-3 overflow-hidden">
          <div className="flex items-center justify-between gap-3 rounded-lg bg-white/5 px-4 py-3">
            <div>
              <p className="text-xs uppercase tracking-wide text-white/50">{t("nodes.editor.slides.present.elapsed")}</p>
              <p className="text-3xl font-semibold tabular-nums" data-testid="slides-presenter-timer">
                {clock(now - began)}
              </p>
            </div>
            <PresentButton label={t("nodes.editor.slides.present.reset_timer")} onClick={() => setBegan(Date.now())}>
              <RotateCcw className="h-4 w-4" aria-hidden />
            </PresentButton>
            <div className="text-right">
              <p className="text-xs uppercase tracking-wide text-white/50">{t("nodes.editor.slides.present.clock")}</p>
              <p className="text-xl tabular-nums text-white/80">{new Date(now).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</p>
            </div>
          </div>
          <div>
            <p className="mb-1.5 text-xs uppercase tracking-wide text-white/50">{t("nodes.editor.slides.present.up_next")}</p>
            {next < count ? (
              <div className="opacity-90">{drawn(next, sideWidth, false)}</div>
            ) : (
              <p className="text-sm text-white/50">{t("nodes.editor.slides.present.end_of_deck")}</p>
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto rounded-lg bg-white/5 px-4 py-3 text-lg leading-8 text-white/90" data-testid="slides-presenter-notes">
            {noteText ? <div dangerouslySetInnerHTML={{ __html: linesHtml(noteText) }} /> : <p className="text-white/50">{t("nodes.editor.slides.notes.none")}</p>}
          </div>
        </div>
      </div>
    );
  } else {
    const width = Math.max(1, Math.min(box.width - 2 * pad, ((box.height - notesHeight - 2 * pad - bar) * 16) / 9));
    stage = (
      <>
        <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden" onClick={onStageClick}>
          <div key={`${at}`} className={cn("pv-in", motionClass)}>
            {drawn(at, width, true)}
          </div>
        </div>
        {notes && (
          <div
            className="shrink-0 overflow-y-auto border-t border-white/15 bg-neutral-950 px-6 py-3 text-base leading-7 text-white/90"
            style={{ height: notesHeight }}
            data-testid="slides-present-notes"
          >
            {noteText ? <div dangerouslySetInnerHTML={{ __html: linesHtml(noteText) }} /> : <p className="text-white/50">{t("nodes.editor.slides.notes.none")}</p>}
          </div>
        )}
      </>
    );
  }

  return createPortal(
    <div
      ref={root}
      role="dialog"
      aria-modal="true"
      aria-label={t("nodes.editor.slides.present.label")}
      tabIndex={-1}
      onKeyDown={onKeyDown}
      className="fixed inset-0 z-[100] flex flex-col overflow-hidden bg-black text-white outline-none"
      data-testid="slides-present"
    >
      <style>{MOTION_CSS}</style>
      {stage}
      {blank && (
        <div
          className={cn("absolute inset-0 z-10", blank === "black" ? "bg-black" : "bg-white")}
          onClick={() => setBlank("")}
          data-testid="slides-present-blank"
        />
      )}
      <div className="flex h-12 shrink-0 items-center justify-between gap-2 px-3 text-sm text-white/70">
        <span className="min-w-0 truncate">{deckTitle}</span>
        <div className="flex items-center gap-1">
          <PresentButton label={t("nodes.editor.slides.present.previous")} onClick={back} disabled={visible(at - 1, -1) < 0}>
            <ChevronLeft className="h-4 w-4" aria-hidden />
          </PresentButton>
          <span className="min-w-[64px] text-center tabular-nums" aria-live="polite">
            {fill(t("nodes.editor.slides.present.position"), { n: at + 1, total: count })}
          </span>
          <PresentButton label={t("nodes.editor.slides.present.next")} onClick={forward} disabled={next >= count && built >= clicksOf(slide)}>
            <ChevronRight className="h-4 w-4" aria-hidden />
          </PresentButton>
        </div>
        <div className="flex items-center gap-1">
          <PresentButton label={t("nodes.editor.slides.present.notes")} onClick={() => setNotes((on) => !on)} pressed={notes} disabled={presenter}>
            <StickyNote className="h-4 w-4" aria-hidden />
          </PresentButton>
          <PresentButton label={t("nodes.editor.slides.present.presenter")} onClick={() => setPresenter((on) => !on)} pressed={presenter} testId="slides-present-presenter">
            <MonitorPlay className="h-4 w-4" aria-hidden />
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
