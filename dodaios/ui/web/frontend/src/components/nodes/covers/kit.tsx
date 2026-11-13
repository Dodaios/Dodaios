/**
 * The parts every cover miniature is built from: the paper lying on the
 * tinted desk, the framed artboard of a slide or a film, the quiet gray bars
 * that stand for text nobody has written yet, and the small pill in a corner.
 *
 * Everything here is static markup: no state, no effects, no measuring. A
 * library of a hundred cards draws a hundred of these.
 */
import type { CSSProperties, ReactNode, Ref } from "react";

import { cn } from "@/lib/utils";

/* --- reading a preview without trusting its shape ------------------------- */

/** A preview string, whatever the server actually sent. */
export function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** A preview list, whatever the server actually sent. */
export function arr<T>(value: readonly T[] | null | undefined): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

/** A finite preview number, or the fallback. */
export function num(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/* --- surfaces -------------------------------------------------------------- */

/**
 * The edge and the shadow of a sheet on the desk: a hairline in the type's
 * hue and a very soft cast, so the paper reads as lying on the color.
 */
const SHEET_EDGE =
  "border border-[hsl(var(--node-hue)/0.18)] shadow-[0_1px_2px_rgb(var(--scrim-rgb)/0.05),0_12px_28px_-16px_rgb(var(--scrim-rgb)/0.28)]";

export interface PaperProps {
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
  paperRef?: Ref<HTMLDivElement>;
}

/**
 * The paper: a sheet in the card surface color, inset from the cover's sides
 * and top, running out past the cover's bottom edge (the cover clips it).
 */
export function Paper({ children, className, style, paperRef }: PaperProps) {
  return (
    <div
      ref={paperRef}
      data-node-paper=""
      className={cn(
        "absolute bottom-0 left-[17%] right-[17%] top-[10%] overflow-hidden rounded-t-[10px] bg-card text-foreground",
        SHEET_EDGE,
        // After the edge: the sheet has no bottom rim, it runs off the cover.
        "border-b-0",
        className,
      )}
      style={style}
    >
      {children}
    </div>
  );
}

export interface ArtboardProps extends PaperProps {
  /** Width / height of the artboard. */
  ratio: number;
}

/**
 * An artboard shown whole: a slide, a film frame, a design canvas. It keeps
 * its own proportions and is as large as the cover allows with air around
 * it. Sized in container units of the cover (`container-type: size` there).
 */
export function Artboard({ ratio, children, className, style, paperRef }: ArtboardProps) {
  const safe = ratio > 0 && Number.isFinite(ratio) ? Math.min(4, Math.max(0.25, ratio)) : 16 / 9;
  return (
    <div
      ref={paperRef}
      data-node-paper=""
      className={cn(
        "absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-[8px] bg-card text-foreground",
        SHEET_EDGE,
        className,
      )}
      style={{
        width: `min(72cqw, calc(80cqh * ${safe.toFixed(4)}))`,
        aspectRatio: safe.toFixed(4),
        ...style,
      }}
    >
      {children}
    </div>
  );
}

/* --- small parts ----------------------------------------------------------- */

const BAR_WIDTHS = ["w-[46%]", "w-[92%]", "w-[84%]", "w-[88%]", "w-[58%]", "w-[80%]", "w-[66%]"];

/**
 * Quiet gray bars standing for lines of text: a shorter, stronger one for a
 * heading, then a paragraph. `shimmer` lets a highlight travel across them
 * (a node that is still being built).
 */
export function TextBars({
  count = 5,
  heading = true,
  shimmer = false,
  className,
}: {
  /** Bars in all, the heading bar included. */
  count?: number;
  /** Lead with the heading bar (off when a real heading stands above). */
  heading?: boolean;
  shimmer?: boolean;
  className?: string;
}) {
  const widths = BAR_WIDTHS.slice(heading ? 0 : 1, count);
  return (
    <div data-node-bars={shimmer ? "shimmer" : "still"} className={cn("flex flex-col gap-[7px]", className)}>
      {widths.map((width, index) => {
        const lead = heading && index === 0;
        return (
          <span
            key={width}
            className={cn(
              "block rounded-full",
              width,
              lead ? "mb-[3px] h-[7px]" : "h-[5px]",
              shimmer
                ? "animate-[node-shimmer_2.4s_linear_infinite] motion-reduce:animate-none"
                : lead
                  ? "bg-foreground/[0.14]"
                  : "bg-foreground/[0.08]",
            )}
            style={shimmer ? SHIMMER_STYLE : undefined}
          />
        );
      })}
    </div>
  );
}

/** A bar whose highlight travels: the ground is the still bar's gray. */
const SHIMMER_STYLE: CSSProperties = {
  backgroundImage:
    "linear-gradient(100deg, hsl(var(--foreground) / 0.08) 35%, hsl(var(--foreground) / 0.2) 50%, hsl(var(--foreground) / 0.08) 65%)",
  backgroundSize: "200% 100%",
};

/** A small pill in the cover's corner: a slide count, a duration. */
export function CoverPill({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <span
      data-testid={testId}
      className="absolute bottom-[7%] right-[4%] rounded-full border border-[hsl(var(--node-hue)/0.2)] bg-card px-[7px] text-[11px] font-medium leading-[18px] tabular-nums text-foreground-secondary"
    >
      {children}
    </span>
  );
}
