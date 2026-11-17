/**
 * Smooth movement on the board: the wheel, the trackpad and the zoom buttons.
 *
 * The editor moves its view in steps: a mouse wheel notch jumps 100 pixels or
 * 10 % of zoom at once, which reads as a stutter. This controller takes the
 * wheel before the editor does and moves the view towards a target over a few
 * frames instead, so every move glides:
 *
 * - Ctrl or Cmd with the wheel (and a trackpad pinch, which the browser sends
 *   the same way) zooms around the pointer. A pinch follows the fingers at
 *   once; a mouse notch eases in.
 * - The wheel alone pans; Shift turns it sideways. A trackpad's own smooth
 *   deltas are applied as they come; a mouse notch eases in.
 *
 * While the zoom changes, the editor draws its cached shapes scaled
 * (`shouldCacheIgnoreZoom`) and draws them sharp again once the zoom rests,
 * as its own wheel handler does: redrawing every shape at every frame of a
 * zoom is what would make it stutter.
 */
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";

export const MIN_ZOOM = 0.1;
export const MAX_ZOOM = 30;
/** How far towards its target the view moves each frame (0..1). */
const EASE = 0.28;
/** How long the zoom must rest before shapes are drawn sharp again. */
const SHARPEN_MS = 180;
/** A wheel delta at least this large, in whole steps, comes from a mouse notch. */
const NOTCH = 50;

interface View {
  scrollX: number;
  scrollY: number;
  zoom: number;
}

export function clampZoom(value: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

/**
 * The view after zooming to `nextZoom` while the scene point under
 * (`viewportX`, `viewportY`) stays where it is. The editor's own formula
 * (`getStateForZoom`); the point is relative to the canvas's top-left corner.
 */
export function zoomAround(view: View, nextZoom: number, pointX: number, pointY: number): View {
  const sceneX = pointX / view.zoom - view.scrollX;
  const sceneY = pointY / view.zoom - view.scrollY;
  return { zoom: nextZoom, scrollX: pointX / nextZoom - sceneX, scrollY: pointY / nextZoom - sceneY };
}

/** Is this wheel event a mouse notch rather than a trackpad's smooth stream? */
export function isNotch(event: Pick<WheelEvent, "deltaMode" | "deltaX" | "deltaY">): boolean {
  if (event.deltaMode !== 0) return true;
  const y = Math.abs(event.deltaY);
  return event.deltaX === 0 && y >= NOTCH && Number.isInteger(event.deltaY);
}

type Glide =
  | { kind: "zoom"; zoom: number; anchorX: number; anchorY: number }
  | { kind: "pan"; scrollX: number; scrollY: number };

export class SmoothViewport {
  private target: Glide | null = null;
  private frame = 0;
  private sharpenTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly api: () => ExcalidrawImperativeAPI | null,
    private readonly origin: () => { left: number; top: number },
  ) {}

  private current(): View | null {
    const editor = this.api();
    if (!editor) return null;
    const state = editor.getAppState();
    return { scrollX: state.scrollX, scrollY: state.scrollY, zoom: state.zoom.value };
  }

  /** Handle a wheel event over the canvas. Returns true when it was used. */
  wheel(event: WheelEvent): boolean {
    const now = this.current();
    if (!now) return false;
    const notch = isNotch(event);
    const scale = event.deltaMode === 1 ? 33 : event.deltaMode === 2 ? 400 : 1;
    const dx = event.deltaX * scale;
    const dy = event.deltaY * scale;
    if (event.ctrlKey || event.metaKey) {
      const { left, top } = this.origin();
      const x = event.clientX - left;
      const y = event.clientY - top;
      if (notch) {
        const from = this.target?.kind === "zoom" ? this.target.zoom : now.zoom;
        const strength = Math.sign(dy) * Math.min(Math.abs(dy), 120) * 0.0018;
        this.glideZoom(clampZoom(from * Math.exp(-strength)), x, y);
      } else {
        // A pinch sends small deltas many times a second: follow at once.
        this.stop();
        this.apply(zoomAround(now, clampZoom(now.zoom * Math.exp(-dy * 0.012)), x, y), true);
      }
      return true;
    }
    const panX = event.shiftKey && dx === 0 ? dy : dx;
    const panY = event.shiftKey && dx === 0 ? 0 : dy;
    if (notch) {
      const from = this.target?.kind === "pan" ? this.target : now;
      this.glide({ kind: "pan", scrollX: from.scrollX - panX / now.zoom, scrollY: from.scrollY - panY / now.zoom });
    } else {
      this.stop();
      this.apply({ ...now, scrollX: now.scrollX - panX / now.zoom, scrollY: now.scrollY - panY / now.zoom }, false);
    }
    return true;
  }

  /** Zoom by a factor around the middle of the canvas (the zoom buttons). */
  zoomBy(factor: number, size: { width: number; height: number }): void {
    const now = this.current();
    if (!now) return;
    const from = this.target?.kind === "zoom" ? this.target.zoom : now.zoom;
    this.glideZoom(clampZoom(from * factor), size.width / 2, size.height / 2);
  }

  /** Zoom to an exact value around the middle of the canvas. */
  zoomTo(value: number, size: { width: number; height: number }): void {
    this.glideZoom(clampZoom(value), size.width / 2, size.height / 2);
  }

  /** Stop gliding (a fit animation of the editor takes over). */
  stop(): void {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = 0;
    this.target = null;
  }

  dispose(): void {
    this.stop();
    if (this.sharpenTimer) clearTimeout(this.sharpenTimer);
  }

  private glideZoom(zoom: number, anchorX: number, anchorY: number): void {
    this.glide({ kind: "zoom", zoom, anchorX, anchorY });
  }

  private glide(target: Glide): void {
    this.target = target;
    if (!this.frame) this.frame = requestAnimationFrame(this.step);
  }

  private step = () => {
    this.frame = 0;
    const target = this.target;
    const now = this.current();
    if (!target || !now) return;
    if (target.kind === "zoom") {
      // Zoom eases in log space, so zooming in and out feel the same; the
      // point under the anchor stays where it is at every frame.
      const done = Math.abs(target.zoom - now.zoom) / target.zoom < 0.002;
      const zoom = done ? target.zoom : Math.exp(Math.log(now.zoom) + (Math.log(target.zoom) - Math.log(now.zoom)) * EASE);
      this.apply(zoomAround(now, zoom, target.anchorX, target.anchorY), true);
      if (done) {
        this.target = null;
        return;
      }
    } else {
      const done =
        Math.abs(target.scrollX - now.scrollX) * now.zoom < 0.5 && Math.abs(target.scrollY - now.scrollY) * now.zoom < 0.5;
      this.apply(
        done
          ? { ...now, scrollX: target.scrollX, scrollY: target.scrollY }
          : {
              ...now,
              scrollX: now.scrollX + (target.scrollX - now.scrollX) * EASE,
              scrollY: now.scrollY + (target.scrollY - now.scrollY) * EASE,
            },
        false,
      );
      if (done) {
        this.target = null;
        return;
      }
    }
    this.frame = requestAnimationFrame(this.step);
  };

  private apply(view: View, zoom: boolean): void {
    const editor = this.api();
    if (!editor) return;
    editor.updateScene({
      appState: {
        scrollX: view.scrollX,
        scrollY: view.scrollY,
        zoom: { value: view.zoom },
        ...(zoom ? { shouldCacheIgnoreZoom: true } : {}),
      } as never,
    });
    if (zoom) {
      if (this.sharpenTimer) clearTimeout(this.sharpenTimer);
      this.sharpenTimer = setTimeout(() => {
        this.sharpenTimer = null;
        if (this.target?.kind === "zoom") return;
        this.api()?.updateScene({ appState: { shouldCacheIgnoreZoom: false } });
      }, SHARPEN_MS);
    }
  }
}
