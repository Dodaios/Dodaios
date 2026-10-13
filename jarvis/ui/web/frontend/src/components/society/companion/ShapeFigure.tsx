import { useCallback, useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { figureKey, type FigureLook } from "./figureScene";
import { figuresSupported, readFigure, watchFigure, watchFigureSupport, type Figure } from "./figureStore";

/** True while agent shapes can be drawn as 3D figures here; re-renders when that changes. */
export function useFiguresSupported(): boolean {
  return useSyncExternalStore(watchFigureSupport, figuresSupported, () => false);
}

/** The widest picture a face asks for, device pixels. */
const MAX_PIXELS = 288;

/** Device pixels for a face `size` CSS pixels wide: twice at least, so an enlarged window stays crisp. */
function figurePixels(size: number): number {
  const ratio = typeof window === "undefined" ? 2 : Math.max(2, Math.min(window.devicePixelRatio || 1, 3));
  return Math.max(8, Math.min(MAX_PIXELS, Math.round(size * ratio)));
}

/**
 * An agent's shape as a 3D figure, `size` pixels wide. The picture is drawn
 * once by the figure worker and painted into a plain 2D canvas; until it is
 * there the box is empty at its final size, and while a changed look is on
 * its way the previous picture stays. `children` is drawn over the eyes, in
 * the flat symbol's own units (a face with moving eyes).
 */
export function ShapeFigure({ look, size, shape, behind, children, overlay }: {
  look: FigureLook; size: number;
  /** For `data-agent-figure`: what tests and styles tell figures apart by. */
  shape: string;
  /** Drawn behind the picture (a glow). */
  behind?: ReactNode;
  /** Drawn over the picture, unscaled (glints around the figure). */
  overlay?: ReactNode;
  children?: ReactNode;
}) {
  const pixels = figurePixels(size);
  const key = figureKey(look, pixels);
  const subscribe = useCallback((listener: () => void) => watchFigure(look, pixels, listener),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the key names the look and the size
    [key]);
  const figure = useSyncExternalStore(subscribe, () => readFigure(look, pixels), () => undefined);
  // The last picture stays while the next one is drawn.
  const [last, setLast] = useState<Figure | undefined>(figure);
  if (figure && figure !== last) setLast(figure);
  const shown = figure ?? last;
  const canvas = useRef<HTMLCanvasElement>(null);
  useLayoutEffect(() => {
    const node = canvas.current;
    if (!node || !shown) return;
    if (node.width !== shown.pixels) { node.width = shown.pixels; node.height = shown.pixels; }
    // Painted on the CPU like the pixel creatures: many small GPU canvases can hold the UI thread.
    const context = node.getContext("2d", { willReadFrequently: true });
    context?.putImageData(new ImageData(shown.data, shown.pixels, shown.pixels), 0, 0);
  }, [shown]);
  return <span className="society-agent-figure" data-agent-figure={shape} data-ready={shown ? "true" : undefined} style={{ width: size, height: size }}>
    {behind}
    <canvas ref={canvas} aria-hidden />
    {shown && children && <svg aria-hidden focusable="false" viewBox={`0 0 ${shown.pixels} ${shown.pixels}`} className="society-agent-symbol" data-expressive="true">
      <g transform={`matrix(${shown.face.map(value => +value.toFixed(4)).join(" ")})`}>{children}</g>
    </svg>}
    {shown && overlay}
  </span>;
}
