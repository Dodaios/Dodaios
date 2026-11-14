/**
 * The eleven slide layouts as a grid of small pictures, for adding a slide
 * and for switching one. Each picture sketches where the layout puts its
 * title, its text and its main element, so the choice reads at a glance;
 * the name sits under it and is the button's accessible name.
 */
import { useRef, type KeyboardEvent } from "react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

import { LAYOUTS, type Layout } from "./deckModel";

/** A 48 x 27 sketch of a layout; `currentColor` lines, the accent for the main element. */
export function LayoutGlyph({ layout, className }: { layout: Layout; className?: string }) {
  const line = (x: number, y: number, w: number, h = 2.2) => <rect x={x} y={y} width={w} height={h} rx={1.1} fill="currentColor" />;
  const accent = (x: number, y: number, w: number, h: number) => (
    <rect x={x} y={y} width={w} height={h} rx={1} className="fill-[hsl(var(--node-slides,var(--accent)))]" opacity={0.8} />
  );
  let body;
  switch (layout) {
    case "title":
      body = (
        <>
          {accent(5, 13, 6, 1.6)}
          {line(5, 16.5, 26, 3.4)}
          {line(5, 22, 18, 1.6)}
        </>
      );
      break;
    case "section":
      body = (
        <>
          <rect x={0} y={0} width={48} height={27} className="fill-[hsl(var(--node-slides,var(--accent)))]" opacity={0.12} />
          {line(5, 5, 4, 1.6)}
          {line(10, 5.6, 33, 0.5)}
          {line(5, 12, 24, 3.4)}
        </>
      );
      break;
    case "bullets":
      body = (
        <>
          {line(5, 5, 14, 2.6)}
          {line(5, 9.5, 10, 1.4)}
          {[6, 11, 16, 21].map((y) => (
            <g key={y}>{line(23, y, 20, 1.4)}</g>
          ))}
        </>
      );
      break;
    case "columns":
      body = (
        <>
          {line(5, 4.5, 20, 2.6)}
          {[5, 18.5, 32].map((x) => (
            <g key={x}>
              {line(x, 11, 11, 0.5)}
              {line(x, 13.5, 8, 1.6)}
              {line(x, 17, 11, 1.2)}
              {line(x, 19.5, 9, 1.2)}
            </g>
          ))}
        </>
      );
      break;
    case "quote":
      body = (
        <>
          <text x={5} y={14} fontSize={11} fontFamily="Georgia,serif" className="fill-[hsl(var(--node-slides,var(--accent)))]">
            {"“"}
          </text>
          {line(13, 8, 28, 2.4)}
          {line(13, 12, 22, 2.4)}
          {line(13, 18, 10, 1.2)}
        </>
      );
      break;
    case "stats":
      body = (
        <>
          {line(5, 4.5, 20, 2.6)}
          {[5, 20, 35].map((x) => (
            <g key={x}>
              {accent(x, 13, 9, 5)}
              {line(x, 20.5, 7, 1.2)}
            </g>
          ))}
        </>
      );
      break;
    case "chart":
      body = (
        <>
          {line(5, 4.5, 20, 2.6)}
          {[0, 1, 2, 3].map((i) => accent(7 + i * 6, 22 - (i + 2) * 2.4, 4, (i + 2) * 2.4))}
          {line(33, 17, 10, 1.2)}
          {line(33, 19.5, 8, 1.2)}
        </>
      );
      break;
    case "table":
      body = (
        <>
          {line(5, 4.5, 20, 2.6)}
          {[11, 15, 19, 23].map((y, i) => (
            <g key={y}>
              {line(5, y, 38, i === 0 ? 0.7 : 0.4)}
              {line(5, y - 2.2, 10, 1.2)}
              {line(30, y - 2.2, 7, 1.2)}
            </g>
          ))}
        </>
      );
      break;
    case "image":
      body = (
        <>
          {line(5, 5, 13, 2.6)}
          {line(5, 20, 12, 1.2)}
          <rect x={25} y={0} width={23} height={27} className="fill-current" opacity={0.28} />
          <path d="M28 22 34 15l4 4 3-3 5 6z" className="fill-current" opacity={0.5} />
        </>
      );
      break;
    case "steps":
      body = (
        <>
          {line(5, 4.5, 20, 2.6)}
          {[6, 19, 32].map((x) => (
            <g key={x}>
              <circle cx={x + 2} cy={14} r={2} fill="none" strokeWidth={0.8} className="stroke-[hsl(var(--node-slides,var(--accent)))]" />
              {line(x + 5, 13.8, 6, 0.4)}
              {line(x, 18.5, 8, 1.4)}
            </g>
          ))}
        </>
      );
      break;
    case "closing":
      body = (
        <>
          {accent(5, 4.5, 6, 1.6)}
          {line(5, 8, 22, 3.2)}
          {[5, 19, 33].map((x) => (
            <g key={x}>
              {line(x, 19, 10, 0.5)}
              {line(x, 21, 9, 1.2)}
            </g>
          ))}
        </>
      );
      break;
  }
  return (
    <svg viewBox="0 0 48 27" aria-hidden className={cn("overflow-hidden rounded-[3px] text-muted-foreground", className)}>
      <rect x={0} y={0} width={48} height={27} className="fill-background" />
      {body}
    </svg>
  );
}

export interface LayoutPickerProps {
  /** The layout now in use (switching), or none (adding). */
  current?: Layout;
  onPick: (layout: Layout) => void;
  className?: string;
}

/** The layouts as a 3-column grid of buttons; arrow keys move between them. */
export function LayoutPicker({ current, onPick, className }: LayoutPickerProps) {
  const t = useT();
  const grid = useRef<HTMLDivElement>(null);
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const buttons = Array.from(grid.current?.querySelectorAll<HTMLButtonElement>("button[data-layout]") ?? []);
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (at < 0) return;
    const step = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: 3, ArrowUp: -3 }[event.key];
    if (step === undefined) return;
    event.preventDefault();
    event.stopPropagation();
    buttons[Math.max(0, Math.min(buttons.length - 1, at + step))]?.focus();
  };
  return (
    <div ref={grid} className={cn("grid grid-cols-3 gap-1.5", className)} onKeyDown={onKeyDown} data-testid="slides-layout-picker">
      {LAYOUTS.map((layout) => {
        const label = t(`nodes.editor.slides.layout.${layout}`);
        const on = layout === current;
        return (
          <button
            key={layout}
            type="button"
            data-layout={layout}
            aria-pressed={current === undefined ? undefined : on}
            onClick={() => onPick(layout)}
            className={cn(
              "flex flex-col items-center gap-1 rounded-md p-1.5 text-xs text-muted-foreground",
              "hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              on && "bg-secondary text-foreground ring-1 ring-inset ring-border-strong",
            )}
          >
            <LayoutGlyph layout={layout} className="h-[27px] w-12 border border-border" />
            <span className="w-full truncate text-center">{label}</span>
          </button>
        );
      })}
    </div>
  );
}
