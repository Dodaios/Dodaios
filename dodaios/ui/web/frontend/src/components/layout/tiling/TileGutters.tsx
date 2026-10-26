import { useRef } from "react";
import { clsx } from "clsx";

import { layoutSplits, type TileNode } from "@/lib/tilingLayout";
import { useTilingStore } from "@/store/tiling";

/**
 * The draggable seams between tiles. One per split, laid over the gap it
 * sits in; dragging moves that split's ratio, double-click evens it out.
 */
export function TileGutters({ tree, gap }: { tree: TileNode; gap: number }) {
  const resize = useTilingStore((s) => s.resize);
  const host = useRef<HTMLDivElement>(null);

  return (
    <div ref={host} className="pointer-events-none absolute inset-0">
      {layoutSplits(tree).map(({ split, rect }) => {
        const row = split.dir === "row";
        const at = row ? rect.x + rect.w * split.ratio : rect.y + rect.h * split.ratio;
        const style: React.CSSProperties = row
          ? { left: `calc(${at * 100}% - ${gap / 2}px)`, top: `${rect.y * 100}%`, width: gap, height: `${rect.h * 100}%` }
          : { top: `calc(${at * 100}% - ${gap / 2}px)`, left: `${rect.x * 100}%`, height: gap, width: `${rect.w * 100}%` };
        return (
          <div
            key={split.id}
            role="separator"
            aria-orientation={row ? "vertical" : "horizontal"}
            aria-valuenow={Math.round(split.ratio * 100)}
            data-testid="tile-gutter"
            className={clsx(
              "group pointer-events-auto absolute z-20 flex items-center justify-center",
              row ? "cursor-col-resize" : "cursor-row-resize",
            )}
            style={style}
            onDoubleClick={() => resize(split.id, 0.5)}
            onPointerDown={(event) => {
              const box = host.current?.getBoundingClientRect();
              if (!box || event.button !== 0) return;
              event.preventDefault();
              const target = event.currentTarget;
              target.setPointerCapture(event.pointerId);
              const move = (ev: PointerEvent) => {
                const ratio = row
                  ? ((ev.clientX - box.left) / box.width - rect.x) / rect.w
                  : ((ev.clientY - box.top) / box.height - rect.y) / rect.h;
                resize(split.id, ratio);
              };
              const up = () => {
                target.removeEventListener("pointermove", move);
                target.removeEventListener("pointerup", up);
                target.removeEventListener("pointercancel", up);
                document.body.style.cursor = "";
              };
              document.body.style.cursor = row ? "col-resize" : "row-resize";
              target.addEventListener("pointermove", move);
              target.addEventListener("pointerup", up);
              target.addEventListener("pointercancel", up);
            }}
          >
            <span
              className={clsx(
                "rounded-full bg-white/0 transition-colors group-hover:bg-white/50",
                row ? "h-10 w-1" : "h-1 w-10",
              )}
            />
          </div>
        );
      })}
    </div>
  );
}
