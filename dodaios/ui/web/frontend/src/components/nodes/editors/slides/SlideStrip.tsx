/**
 * The slide strip: every slide as a live thumbnail, in order.
 *
 * It is a listbox: one slide is selected (it is the one on the canvas), the
 * arrow keys move the selection, and the structural keys act on the
 * selected slide: Alt+Arrow moves it, Cmd/Ctrl+D duplicates it, Delete or
 * Backspace removes it, Enter goes to its title on the canvas. A slide is
 * dragged to a new place with the pointer; a line shows where it lands.
 * Drag and drop is done with pointer events rather than the HTML drag API,
 * which draws its own ghost image and behaves differently in each engine.
 *
 * Every change is announced in a live region, so a screen reader hears
 * "Slide 3 moved to position 1" instead of nothing.
 */
import { memo, useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { Copy, MoreHorizontal, Plus, Trash2, ArrowUp, ArrowDown } from "lucide-react";

import { useT, fill } from "@/i18n";
import { cn } from "@/lib/utils";

import { MenuItem, Popover } from "../controls";
import { LIMITS, slideName, type Slide } from "./deckModel";
import { LayoutPicker } from "./LayoutPicker";
import { SlideCanvas } from "./SlideCanvas";
import { SlideView } from "./SlideView";
import { ALT, MOD } from "./keys";
import type { Layout } from "./deckModel";

export const THUMB_WIDTH = 168;
/** Pointer travel before a press becomes a drag (a click stays a click). */
const DRAG_THRESHOLD = 5;

export interface SlideStripProps {
  slides: readonly Slide[];
  selected: number;
  css: string;
  theme: "light" | "dark";
  accent: string;
  deckTitle: string;
  sections: readonly number[];
  figureOf: (index: number) => string | null;
  onSelect: (index: number) => void;
  onMove: (from: number, to: number) => void;
  onDuplicate: (index: number) => void;
  onDelete: (index: number) => void;
  onAdd: (layout: Layout) => void;
  /** Enter on a slide: go to its first field on the canvas. */
  onOpen: (index: number) => void;
}

interface Drag {
  from: number;
  startY: number;
  pointerId: number;
  active: boolean;
  /** Insertion point: the slide lands before this index (0..n). */
  before: number;
}

const Thumb = memo(function Thumb({
  slide,
  index,
  css,
  theme,
  accent,
  deckTitle,
  section,
  figure,
}: {
  slide: Slide;
  index: number;
  css: string;
  theme: "light" | "dark";
  accent: string;
  deckTitle: string;
  section: number;
  figure: string | null;
}) {
  return (
    <SlideCanvas css={css} width={THUMB_WIDTH} theme={theme} accent={accent} className="overflow-hidden rounded-[5px]">
      <SlideView slide={slide} index={index} deckTitle={deckTitle} section={section} figure={figure} />
    </SlideCanvas>
  );
});

export function SlideStrip({
  slides,
  selected,
  css,
  theme,
  accent,
  deckTitle,
  sections,
  figureOf,
  onSelect,
  onMove,
  onDuplicate,
  onDelete,
  onAdd,
  onOpen,
}: SlideStripProps) {
  const t = useT();
  const list = useRef<HTMLDivElement>(null);
  const items = useRef<(HTMLDivElement | null)[]>([]);
  const [drag, setDrag] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const suppressClick = useRef(false);
  const [announcement, setAnnouncement] = useState("");
  const count = slides.length;
  const canAdd = count < LIMITS.slides;

  // The selected slide stays in view (after a move, an add, an undo).
  useEffect(() => {
    items.current[selected]?.scrollIntoView?.({ block: "nearest" });
  }, [selected, count]);

  const focusSlide = useCallback((index: number) => {
    requestAnimationFrame(() => items.current[index]?.focus({ preventScroll: false }));
  }, []);

  const move = useCallback(
    (from: number, to: number) => {
      if (to < 0 || to >= count || to === from) return;
      onMove(from, to);
      setAnnouncement(fill(t("nodes.editor.slides.strip.moved"), { from: from + 1, to: to + 1 }));
      focusSlide(to);
    },
    [count, onMove, t, focusSlide],
  );

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>, index: number) => {
    const mod = event.metaKey || event.ctrlKey;
    const key = event.key;
    if (event.altKey && (key === "ArrowUp" || key === "ArrowDown")) {
      event.preventDefault();
      move(index, index + (key === "ArrowUp" ? -1 : 1));
      return;
    }
    if (mod && key.toLowerCase() === "d") {
      event.preventDefault();
      if (canAdd) {
        onDuplicate(index);
        setAnnouncement(fill(t("nodes.editor.slides.strip.duplicated"), { n: index + 1 }));
        focusSlide(index + 1);
      }
      return;
    }
    if ((key === "Delete" || key === "Backspace") && !mod) {
      event.preventDefault();
      if (count > 1) {
        onDelete(index);
        setAnnouncement(fill(t("nodes.editor.slides.strip.deleted"), { n: index + 1 }));
        focusSlide(Math.min(index, count - 2));
      }
      return;
    }
    if (key === "Enter") {
      event.preventDefault();
      onOpen(index);
      return;
    }
    let to: number | null = null;
    if (key === "ArrowUp" || key === "ArrowLeft") to = index - 1;
    else if (key === "ArrowDown" || key === "ArrowRight") to = index + 1;
    else if (key === "Home") to = 0;
    else if (key === "End") to = count - 1;
    if (to === null || event.altKey || mod) return;
    event.preventDefault();
    const target = Math.max(0, Math.min(count - 1, to));
    onSelect(target);
    focusSlide(target);
  };

  // --- pointer drag ---------------------------------------------------------------

  const insertionAt = (clientY: number): number => {
    for (let i = 0; i < count; i++) {
      const rect = items.current[i]?.getBoundingClientRect();
      if (rect && clientY < rect.top + rect.height / 2) return i;
    }
    return count;
  };

  const onPointerDown = (event: PointerEvent<HTMLDivElement>, index: number) => {
    if (event.button !== 0 || (event.target as Element).closest("[data-thumb-menu]")) return;
    const next: Drag = { from: index, startY: event.clientY, pointerId: event.pointerId, active: false, before: index };
    dragRef.current = next;
    suppressClick.current = false;
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const current = dragRef.current;
    if (!current || current.pointerId !== event.pointerId) return;
    if (!current.active) {
      if (Math.abs(event.clientY - current.startY) < DRAG_THRESHOLD) return;
      current.active = true;
      (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    }
    current.before = insertionAt(event.clientY);
    setDrag({ ...current });
  };

  const endDrag = (event: PointerEvent<HTMLDivElement>, commit: boolean) => {
    const current = dragRef.current;
    dragRef.current = null;
    setDrag(null);
    if (!current || !current.active) return;
    suppressClick.current = true;
    (event.currentTarget as HTMLElement).releasePointerCapture?.(event.pointerId);
    if (!commit) return;
    const to = current.before > current.from ? current.before - 1 : current.before;
    move(current.from, to);
  };

  const dropLine = drag?.active && drag.before !== drag.from && drag.before !== drag.from + 1 ? drag.before : null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        ref={list}
        role="listbox"
        aria-label={t("nodes.editor.slides.strip.label")}
        aria-orientation="vertical"
        className="min-h-0 flex-1 overflow-y-auto px-3 py-3"
        onPointerMove={onPointerMove}
        onPointerUp={(event) => endDrag(event, true)}
        onPointerCancel={(event) => endDrag(event, false)}
        onKeyDown={(event) => {
          if (event.key === "Escape" && dragRef.current?.active) {
            dragRef.current = null;
            setDrag(null);
          }
        }}
        data-testid="slides-strip"
      >
        {slides.map((slide, index) => {
          const on = index === selected;
          const name = slideName(slide);
          const label = name
            ? fill(t("nodes.editor.slides.strip.slide_named"), { n: index + 1, title: name })
            : fill(t("nodes.editor.slides.strip.slide"), { n: index + 1 });
          return (
            <div key={index} className="relative">
              {dropLine === index && <DropLine />}
              <div
                ref={(el) => {
                  items.current[index] = el;
                }}
                role="option"
                aria-selected={on}
                aria-label={label}
                aria-posinset={index + 1}
                aria-setsize={count}
                tabIndex={on ? 0 : -1}
                data-testid={`slides-thumb-${index}`}
                onClick={() => {
                  if (suppressClick.current) {
                    suppressClick.current = false;
                    return;
                  }
                  onSelect(index);
                }}
                onKeyDown={(event) => onKeyDown(event, index)}
                onPointerDown={(event) => onPointerDown(event, index)}
                className={cn(
                  "group mb-2 flex cursor-default select-none items-start gap-2 rounded-lg p-1.5 outline-none",
                  "focus-visible:ring-2 focus-visible:ring-ring",
                  drag?.active && drag.from === index && "opacity-40",
                )}
              >
                <span
                  aria-hidden
                  className={cn("w-5 shrink-0 pt-0.5 text-right text-xs tabular-nums", on ? "font-medium text-foreground" : "text-muted-foreground")}
                >
                  {index + 1}
                </span>
                <div className="relative">
                  {/* The option's label names the slide; the drawing itself is not read out. */}
                  <div
                    aria-hidden
                    className={cn(
                      "rounded-[7px] p-[2px] transition-shadow",
                      on ? "ring-2 ring-[hsl(var(--accent))]" : "ring-1 ring-border group-hover:ring-border-strong",
                    )}
                  >
                    <Thumb
                      slide={slide}
                      index={index}
                      css={css}
                      theme={theme}
                      accent={accent}
                      deckTitle={deckTitle}
                      section={sections[index] ?? 0}
                      figure={figureOf(index)}
                    />
                  </div>
                  {slide.notes && (
                    <span className="sr-only">{t("nodes.editor.slides.strip.has_notes")}</span>
                  )}
                  <ThumbMenu
                    index={index}
                    count={count}
                    canAdd={canAdd}
                    onDuplicate={() => {
                      onDuplicate(index);
                      focusSlide(index + 1);
                    }}
                    onDelete={() => onDelete(index)}
                    onMove={(to) => move(index, to)}
                  />
                </div>
              </div>
            </div>
          );
        })}
        {dropLine === count && <DropLine />}
      </div>
      <div className="shrink-0 border-t border-border p-2">
        <Popover
          label={t("nodes.editor.slides.add.label")}
          trigger={
            <button
              type="button"
              disabled={!canAdd}
              className="flex h-8 w-full items-center justify-center gap-1.5 rounded-md text-sm text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40"
              data-testid="slides-strip-add"
            >
              <Plus className="h-4 w-4" aria-hidden />
              {t("nodes.editor.slides.add.button")}
            </button>
          }
        >
          {(close) => (
            <div className="w-72 p-1">
              <p className="px-1 pb-2 text-xs text-muted-foreground">{t("nodes.editor.slides.add.pick")}</p>
              <LayoutPicker
                onPick={(layout) => {
                  close();
                  onAdd(layout);
                }}
              />
            </div>
          )}
        </Popover>
      </div>
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
    </div>
  );
}

function DropLine() {
  return <div aria-hidden className="pointer-events-none absolute -top-[5px] left-8 right-1 h-[3px] rounded-full bg-[hsl(var(--accent))]" />;
}

function ThumbMenu({
  index,
  count,
  canAdd,
  onDuplicate,
  onDelete,
  onMove,
}: {
  index: number;
  count: number;
  canAdd: boolean;
  onDuplicate: () => void;
  onDelete: () => void;
  onMove: (to: number) => void;
}) {
  const t = useT();
  return (
    <div data-thumb-menu className="absolute right-1 top-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
      <Popover
        role="menu"
        label={fill(t("nodes.editor.slides.strip.menu"), { n: index + 1 })}
        align="end"
        trigger={
          <button
            type="button"
            tabIndex={-1}
            aria-label={fill(t("nodes.editor.slides.strip.menu"), { n: index + 1 })}
            className="grid h-6 w-6 place-items-center rounded-md bg-background/90 text-foreground shadow-sm ring-1 ring-border hover:bg-secondary"
            onClick={(event) => event.stopPropagation()}
            data-testid={`slides-thumb-menu-${index}`}
          >
            <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
          </button>
        }
      >
        {(close) => (
          <div className="w-52 p-1">
            <MenuItem
              label={t("nodes.editor.slides.action.duplicate")}
              icon={<Copy aria-hidden />}
              shortcut={`${MOD}D`}
              disabled={!canAdd}
              onClick={() => {
                close();
                onDuplicate();
              }}
            />
            <MenuItem
              label={t("nodes.editor.slides.action.move_up")}
              icon={<ArrowUp aria-hidden />}
              shortcut={`${ALT}↑`}
              disabled={index === 0}
              onClick={() => {
                close();
                onMove(index - 1);
              }}
            />
            <MenuItem
              label={t("nodes.editor.slides.action.move_down")}
              icon={<ArrowDown aria-hidden />}
              shortcut={`${ALT}↓`}
              disabled={index === count - 1}
              onClick={() => {
                close();
                onMove(index + 1);
              }}
            />
            <MenuItem
              label={t("nodes.editor.slides.action.delete")}
              icon={<Trash2 aria-hidden />}
              shortcut="⌫"
              destructive
              disabled={count <= 1}
              onClick={() => {
                close();
                onDelete();
              }}
            />
          </div>
        )}
      </Popover>
    </div>
  );
}
