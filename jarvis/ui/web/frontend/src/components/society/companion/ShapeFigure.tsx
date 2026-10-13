import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type ReactNode } from "react";
import { followPointer } from "./figureGaze";
import { figureKey, type FigureLook, type FigureSmoke } from "./figureScene";
import { WorkingBadge } from "./WorkingBadge";
import { FIGURE_BROKEN, figuresSupported, readFigure, watchFigure, watchFigureSupport, type Figure } from "./figureStore";

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
 * The body's outline as an image a CSS mask can use: white where the body
 * is, by how much of each pixel it covers. Encoded on the CPU, once per
 * picture, and only for a look whose effect moves across the body. With
 * `grown`, the outline reaches one pixel further, so a layer cut to it
 * fully covers the body's soft edge.
 */
function outlineUrl(figure: Figure, grown: boolean): string | undefined {
  const body = figure.body;
  if (!body || typeof document === "undefined") return undefined;
  const sheet = document.createElement("canvas");
  const side = figure.pixels;
  sheet.width = side; sheet.height = side;
  const context = sheet.getContext("2d", { willReadFrequently: true });
  if (!context) return undefined;
  const pixels = new Uint8ClampedArray(side * side * 4).fill(255);
  for (let y = 0; y < side; y++) for (let x = 0; x < side; x++) {
    let cover = body[y * side + x]!;
    if (grown && cover < 255) {
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        const nx = x + dx, ny = y + dy;
        if (nx >= 0 && ny >= 0 && nx < side && ny < side && body[ny * side + nx]! > cover) cover = body[ny * side + nx]!;
      }
    }
    pixels[(y * side + x) * 4 + 3] = cover;
  }
  context.putImageData(new ImageData(pixels, side, side), 0, 0);
  return sheet.toDataURL("image/png");
}

/** Where the eyes sit across the flat symbol, and half their width and height, in symbol units. */
const EYE_X = [15.4, 24.6] as const;
const EYE_HALF = { lines: [1.35, 3.15], dots: [2.15, 2.3] } as const;

/**
 * The eyes of a figure as two plain elements at the place the picture's own
 * projection gives them: a wrapper that glances (or follows the pointer
 * while it is near, see figureGaze.ts), and in it each eye, leaning with the
 * turned face, that blinks. Lengths are in `em` of one symbol unit, so the
 * motion scales with the face.
 */
function LivingEyes({ figure, size, eyes }: { figure: Figure; size: number; eyes: { kind: "dots" | "lines"; y: number; color: string } }) {
  const [a, b, c, d, e, f] = figure.face;
  const scale = size / figure.pixels;
  // One symbol unit across and down the turned face, CSS pixels.
  const across = Math.hypot(a, b) * scale, down = Math.hypot(c, d) * scale;
  const [halfX, halfY] = EYE_HALF[eyes.kind];
  const lean = Math.atan2(b, a) * 180 / Math.PI;
  const pair = useRef<HTMLSpanElement>(null);
  useEffect(() => pair.current ? followPointer(pair.current) : undefined, []);
  return <span ref={pair} aria-hidden className="agent-figure-eyes" data-figure-eyes={eyes.kind} style={{ fontSize: down }}>
    {EYE_X.map(x => <i key={x} style={{
      left: (a * x + c * eyes.y + e) * scale - halfX * across, top: (b * x + d * eyes.y + f) * scale - halfY * down,
      width: halfX * across * 2, height: halfY * down * 2, transform: `skewY(${lean.toFixed(2)}deg)`,
    }}><b style={{ background: eyes.color }} /></i>)}
  </span>;
}

/**
 * An agent's shape as a 3D figure, `size` pixels wide. The picture is drawn
 * once by the figure worker and painted into a plain 2D canvas; until it is
 * there the box is empty at its final size, and while a changed look is on
 * its way the previous picture stays. `children` is drawn over the eyes, in
 * the flat symbol's own units (a face with moving eyes). A look that cannot
 * be drawn shows `fallback` instead.
 *
 * What moves is laid over the still picture as compositor-only layers: the
 * colours of a flowing design (multiplied onto a white body), the shine of a
 * shimmering one, both cut to the body's outline, and the smoke of a cigar.
 *
 * The figure is alive at rest: it breathes, hops and wobbles over a shadow
 * that stays on the ground, and with `eyes` it blinks, glances about and
 * follows the pointer. Those eyes are plain elements moved by transforms only, so
 * a roster of faces costs the UI thread nothing while it idles; each figure
 * runs a little out of step with the others.
 */
export function ShapeFigure({ look, size, shape, behind, children, overlay, fallback, flow, shine, inside, smoke, eyes, working = false }: {
  look: FigureLook; size: number;
  /** Shown when this look could not be drawn and no earlier picture is there. */
  fallback: ReactNode;
  /** For `data-agent-figure`: what tests and styles tell figures apart by. */
  shape: string;
  /** Drawn behind the picture (a glow). */
  behind?: ReactNode;
  /** Drawn over the picture, unscaled (glints around the figure). */
  overlay?: ReactNode;
  /** The colours that flow across the body, and their direction as a CSS angle. */
  flow?: { colors: readonly string[]; angle: number };
  /** A shine sweeps across the body. */
  shine?: boolean;
  /** Drawn on the body in the flat symbol's units and cut to its outline (twinkling stars). */
  inside?: ReactNode;
  /** Living eyes over an eyeless picture: their kind, their height in symbol units and their ink. */
  eyes?: { kind: "dots" | "lines"; y: number; color: string };
  /** The agent is at work: the figure nods over what it does, under the working bubble. */
  working?: boolean;
  /** Draws one plume of smoke, in symbol units around its source. */
  smoke?: (plume: FigureSmoke, index: number) => ReactNode;
  children?: ReactNode;
}) {
  const pixels = figurePixels(size);
  const key = figureKey(look, pixels);
  const subscribe = useCallback((listener: () => void) => watchFigure(look, pixels, listener),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the key names the look and the size
    [key]);
  const answer = useSyncExternalStore(subscribe, () => readFigure(look, pixels), () => undefined);
  const figure = answer === FIGURE_BROKEN ? undefined : answer;
  // The last picture stays while the next one is drawn.
  const [last, setLast] = useState<Figure | undefined>(figure);
  if (figure && figure !== last) setLast(figure);
  const shown = figure ?? last;
  const canvas = useRef<HTMLCanvasElement>(null);
  // The outlines belong to one picture; they are set in the same pass that paints it, before the browser draws.
  const [outline, setOutline] = useState<{ of: Figure; body: string | undefined; whole: string | undefined }>();
  const flowing = !!flow;
  useLayoutEffect(() => {
    const node = canvas.current;
    if (!node || !shown) return;
    if (node.width !== shown.pixels) { node.width = shown.pixels; node.height = shown.pixels; }
    // Painted on the CPU like the pixel creatures: many small GPU canvases can hold the UI thread.
    const context = node.getContext("2d", { willReadFrequently: true });
    context?.putImageData(new ImageData(shown.data, shown.pixels, shown.pixels), 0, 0);
    // Flowing colours are multiplied over the whole body and its soft edge, then the pair is cut to the picture itself.
    setOutline(current => current?.of === shown ? current
      : { of: shown, body: outlineUrl(shown, flowing), whole: flowing && shown.body ? node.toDataURL("image/png") : undefined });
  }, [shown, flowing]);
  if (answer === FIGURE_BROKEN && !shown) return <>{fallback}</>;
  const masked = (url: string | undefined) => url ? { maskImage: `url(${url})`, WebkitMaskImage: `url(${url})` } : undefined;
  const current = shown && outline?.of === shown ? outline : undefined;
  const cut = masked(current?.body);
  // A flowing body is white until its colours lie over it: show nothing rather than a white figure.
  const ready = !!shown && (!shown.body || !!cut);
  // Every figure keeps its own beat, so a roster never breathes or blinks as one.
  let beat = 0;
  for (let i = 0; i < key.length; i++) beat = (beat * 31 + key.charCodeAt(i)) % 9973;
  const pace = { "--agent-figure-delay": `${-beat}ms` } as CSSProperties;
  return <span className="society-agent-figure" data-agent-figure={shape} data-ready={ready ? "true" : undefined} data-working={working ? "true" : undefined} style={{ width: size, height: size, ...pace }}>
    {behind}
    {shown?.ground && <i aria-hidden className="agent-figure-ground" style={{
      left: (shown.ground.x - shown.ground.rx) * size / shown.pixels, top: (shown.ground.y - shown.ground.ry) * size / shown.pixels,
      width: shown.ground.rx * 2 * size / shown.pixels, height: shown.ground.ry * 2 * size / shown.pixels,
    }} />}
    <span className="agent-figure-body">
    <span className="agent-figure-picture" style={flow ? masked(current?.whole) : undefined}>
      <canvas ref={canvas} aria-hidden />
      {cut && flow && <span aria-hidden className="agent-figure-flow" style={cut}>
        <i style={{ transform: `rotate(${flow.angle - 90}deg)` }}>
          <b style={{ backgroundImage: `linear-gradient(90deg, ${[...flow.colors, flow.colors[0]].join(", ")})` }} />
        </i>
      </span>}
    </span>
    {cut && shine && <span aria-hidden className="agent-figure-shine" style={cut}><i /></span>}
    {cut && shown && inside && <span aria-hidden className="agent-figure-inside" style={cut}>
      <svg focusable="false" viewBox={`0 0 ${shown.pixels} ${shown.pixels}`} className="society-agent-symbol">
        <g transform={`matrix(${shown.face.map(value => +value.toFixed(4)).join(" ")})`}>{inside}</g>
      </svg>
    </span>}
    {shown && eyes && <LivingEyes figure={shown} size={size} eyes={eyes} />}
    {shown && children && <svg aria-hidden focusable="false" viewBox={`0 0 ${shown.pixels} ${shown.pixels}`} className="society-agent-symbol" data-expressive="true">
      <g transform={`matrix(${shown.face.map(value => +value.toFixed(4)).join(" ")})`}>{children}</g>
    </svg>}
    {shown && smoke && shown.smoke.length > 0 && <svg aria-hidden focusable="false" viewBox={`0 0 ${shown.pixels} ${shown.pixels}`} className="society-agent-symbol" data-figure-smoke>
      {shown.smoke.map((plume, index) => <g key={index} transform={`translate(${+plume.x.toFixed(2)} ${+plume.y.toFixed(2)}) scale(${+plume.scale.toFixed(4)})`}>{smoke(plume, index)}</g>)}
    </svg>}
    </span>
    {shown && overlay}
    {working && <WorkingBadge size={size} />}
  </span>;
}
