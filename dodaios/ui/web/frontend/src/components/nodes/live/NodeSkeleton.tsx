/**
 * The quiet outline of a node type, shown while its editor loads and on the
 * chat card while an agent builds it: a faint grid for a sheet, lines of text
 * for a document, a slide frame for a deck, card blocks for Analytics, an
 * empty canvas for a whiteboard, empty tracks for a clip. One slow shimmer
 * runs over it; with reduced motion it stands still.
 *
 * Kept small and free of the editors' code: the node window draws it from
 * the app's entry bundle before any editor chunk has arrived.
 */
import type { CSSProperties, ReactNode } from "react";

import { cn } from "@/lib/utils";
import type { CardType } from "../nodeModel";
import "./live.css";

const BLOCK = "live-skeleton-block";

function Bar({ w, h = 10, className, style }: { w: string; h?: number; className?: string; style?: CSSProperties }) {
  return <div className={cn(BLOCK, className)} style={{ width: w, height: h, ...style }} />;
}

function DocsSkeleton() {
  const paragraphs = [["92%", "88%", "95%", "60%"], ["90%", "94%", "72%"], ["86%", "91%", "89%", "45%"]];
  return (
    <div className="mx-auto flex w-full max-w-[680px] flex-col gap-7 px-10 py-12">
      <Bar w="55%" h={22} />
      {paragraphs.map((lines, i) => (
        <div key={i} className="flex flex-col gap-2.5">
          {i === 1 && <Bar w="34%" h={14} className="mb-1.5" />}
          {lines.map((w, j) => <Bar key={j} w={w} />)}
        </div>
      ))}
    </div>
  );
}

function SheetsSkeleton() {
  const cols = 6;
  const rows = 12;
  return (
    <div className="flex h-full w-full flex-col">
      <div className="h-11 shrink-0" />
      <div
        className="grid flex-1 border-l border-t live-skeleton-line"
        style={{ gridTemplateColumns: `44px repeat(${cols}, minmax(0, 1fr))`, gridTemplateRows: `repeat(${rows}, 30px)` }}
      >
        {Array.from({ length: rows * (cols + 1) }, (_, i) => (
          <div key={i} className="flex items-center border-b border-r px-2 live-skeleton-line">
            {i < cols + 1 && i > 0 && <Bar w="60%" h={8} />}
          </div>
        ))}
      </div>
    </div>
  );
}

function SlidesSkeleton() {
  return (
    <div className="flex h-full w-full gap-5 p-5">
      <div className="flex w-28 shrink-0 flex-col gap-3">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className={cn(BLOCK, "aspect-video w-full")} style={{ opacity: i === 0 ? 1 : 0.6 }} />
        ))}
      </div>
      <div className="flex min-w-0 flex-1 items-center justify-center">
        <div className="flex aspect-video w-full max-w-[860px] flex-col justify-center gap-4 rounded-md border px-[8%] live-skeleton-line">
          <Bar w="58%" h={26} />
          <Bar w="36%" h={12} />
        </div>
      </div>
    </div>
  );
}

function DataSkeleton() {
  return (
    <div className="mx-auto flex w-full max-w-[980px] flex-col gap-4 p-8">
      <Bar w="40%" h={20} />
      <div className="grid grid-cols-3 gap-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex flex-col gap-3 rounded-lg border p-4 live-skeleton-line">
            <Bar w="45%" h={8} />
            <Bar w="62%" h={20} />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-4">
        {[0, 1].map((i) => (
          <div key={i} className="flex h-48 flex-col gap-3 rounded-lg border p-4 live-skeleton-line">
            <Bar w="35%" h={8} />
            <div className={cn(BLOCK, "flex-1")} />
          </div>
        ))}
      </div>
    </div>
  );
}

function WhiteboardSkeleton() {
  return (
    <div
      className="h-full w-full"
      style={{
        backgroundImage: "radial-gradient(hsl(var(--presence-skeleton)) 1.2px, transparent 1.2px)",
        backgroundSize: "22px 22px",
      }}
    />
  );
}

function MotionSkeleton() {
  return (
    <div className="flex h-full w-full flex-col gap-4 p-5">
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <div className="aspect-video h-full max-h-full max-w-full rounded-md border live-skeleton-line" />
      </div>
      <div className="flex shrink-0 flex-col gap-2">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex h-9 items-center gap-3 rounded border px-3 live-skeleton-line">
            <Bar w="56px" h={8} />
          </div>
        ))}
      </div>
    </div>
  );
}

const SKELETONS: Record<CardType, () => ReactNode> = {
  docs: DocsSkeleton,
  sheets: SheetsSkeleton,
  slides: SlidesSkeleton,
  data: DataSkeleton,
  whiteboard: WhiteboardSkeleton,
  motion: MotionSkeleton,
  output: DocsSkeleton,
};

export function NodeSkeleton({ type, className }: { type: CardType; className?: string }) {
  const Shape = SKELETONS[type] ?? DocsSkeleton;
  return (
    <div
      role="status"
      aria-busy="true"
      data-testid="node-skeleton"
      data-type={type}
      className={cn("live-skeleton h-full w-full overflow-hidden", className)}
    >
      <Shape />
    </div>
  );
}
