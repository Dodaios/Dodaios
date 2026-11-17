/**
 * The layer over the canvas while one of the board's own tools is active
 * (the lasso, the paint bucket). The editor does not know these tools, so
 * this layer takes the pointer instead of the canvas: the lasso draws its
 * loop here, the bucket reads the click here. The wheel still reaches the
 * board's smooth view (`data-board-overlay`).
 */
import { useRef, useState } from "react";

import type { Point } from "./boardTools";

export type OverlayTool = "lasso" | "bucket";

/** The bucket's pointer: a small paint bucket, its tip where the paint goes. */
const BUCKET_CURSOR =
  "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='%23171717' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'><path d='M19 11 11 3 2.5 11.5a2.1 2.1 0 0 0 0 3l7 7a2.1 2.1 0 0 0 3 0L19 11Z' fill='white'/><path d='m5 2 5 5'/><path d='M2 13h15'/><path d='M22 20a2 2 0 1 1-4 0c0-1.6 1.7-2.4 2-4 .3 1.6 2 2.4 2 4Z' fill='%23D4A72C'/></svg>\") 20 21, crosshair";

export function ToolOverlay({
  tool,
  onLasso,
  onBucket,
}: {
  tool: OverlayTool;
  /** The loop the person drew, in window coordinates; `add` with Shift. */
  onLasso: (loop: Point[], add: boolean) => void;
  /** Where the person clicked, in window coordinates. */
  onBucket: (at: Point) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [loop, setLoop] = useState<Point[] | null>(null);
  const drawing = useRef<Point[] | null>(null);

  const origin = () => {
    const rect = box.current?.getBoundingClientRect();
    return { left: rect?.left ?? 0, top: rect?.top ?? 0 };
  };

  return (
    <div
      ref={box}
      data-board-overlay
      data-testid={`board-overlay-${tool}`}
      className="absolute inset-0 z-[2] touch-none"
      style={{ cursor: tool === "bucket" ? BUCKET_CURSOR : "crosshair" }}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        if (tool === "bucket") {
          onBucket({ x: event.clientX, y: event.clientY });
          return;
        }
        event.currentTarget.setPointerCapture(event.pointerId);
        drawing.current = [{ x: event.clientX, y: event.clientY }];
        setLoop(drawing.current);
      }}
      onPointerMove={(event) => {
        if (tool !== "lasso" || !drawing.current) return;
        const last = drawing.current[drawing.current.length - 1];
        if (Math.hypot(event.clientX - last.x, event.clientY - last.y) < 3) return;
        drawing.current = [...drawing.current, { x: event.clientX, y: event.clientY }];
        setLoop(drawing.current);
      }}
      onPointerUp={(event) => {
        if (tool !== "lasso" || !drawing.current) return;
        const points = drawing.current;
        drawing.current = null;
        setLoop(null);
        onLasso(points, event.shiftKey);
      }}
    >
      {loop && loop.length > 1 ? (
        <svg className="pointer-events-none absolute inset-0 h-full w-full overflow-visible" aria-hidden>
          <path
            d={`M ${loop.map((p) => `${p.x - origin().left} ${p.y - origin().top}`).join(" L ")} Z`}
            className="board-lasso"
          />
        </svg>
      ) : null}
    </div>
  );
}
