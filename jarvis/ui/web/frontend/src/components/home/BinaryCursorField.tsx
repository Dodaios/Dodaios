import { useEffect, useRef } from "react";

/**
 * A field of binary digits that lights up around the pointer, in the accent
 * blue, and trails behind it as it moves: the empty front page's one bit of
 * play while nothing is on it yet.
 *
 * The page is an invisible grid of 0s and 1s. Moving the pointer heats the
 * cells near it; heat shows a cell's digit and fades out over half a second,
 * so a quick sweep leaves a short glowing wake. A per-cell grain breaks the
 * round edge into a scatter, and hot cells flip their digit as they burn so
 * the field reads as live data rather than a stencil.
 *
 * It costs nothing at rest: the animation loop only runs while some cell is
 * still warm, and stops by itself once the wake has faded. It listens on its
 * parent element (pointer-events stay on the page's own controls), draws
 * behind everything, and stays off entirely for reduced motion and for touch.
 */
export function BinaryCursorField({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const host = canvas?.parentElement;
    if (!canvas || !host) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    // The canvas is set up when a mouse first arrives, so a page nobody
    // hovers never allocates the grid.
    let dispose: (() => void) | null = null;
    const start = (e: PointerEvent) => {
      if (dispose || e.pointerType === "touch") return;
      const ctx = canvas.getContext("2d");
      if (ctx) dispose = mountField(canvas, host, ctx);
    };
    host.addEventListener("pointermove", start);
    return () => {
      host.removeEventListener("pointermove", start);
      dispose?.();
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      data-testid="binary-cursor-field"
      className={
        className ?? "pointer-events-none absolute inset-0 h-full w-full"
      }
    />
  );
}

/** Draws the field on `canvas`, following the pointer over `host`; returns the teardown. */
function mountField(
  canvas: HTMLCanvasElement,
  host: HTMLElement,
  ctx: CanvasRenderingContext2D,
): () => void {
  let width = 0;
  let height = 0;
  let cols = 0;
  let rows = 0;
  let heat = new Float32Array(0);
  let grain = new Float32Array(0);
  let bits = new Uint8Array(0);
  let hue = "212 100% 62%";
  let frame = 0;
  let last = 0;
  let pointer: { x: number; y: number } | null = null;
  let glowLevel = 0;
  let lastMove = 0;

  const readHue = () => {
    const value = getComputedStyle(host).getPropertyValue("--accent").trim();
    if (value) hue = value;
  };

  const resize = () => {
    const rect = host.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = rect.width;
    height = rect.height;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cols = Math.ceil(width / CELL);
    rows = Math.ceil(height / CELL);
    heat = new Float32Array(cols * rows);
    grain = new Float32Array(cols * rows);
    bits = new Uint8Array(cols * rows);
    for (let i = 0; i < bits.length; i++) {
      grain[i] = Math.random();
      bits[i] = Math.random() < 0.5 ? 0 : 1;
    }
    readHue();
  };

  /** Warm every cell within RADIUS of (x, y) up to `strength`, keeping the hotter value. */
  const stamp = (x: number, y: number, strength = 1) => {
    const c0 = Math.max(0, Math.floor((x - RADIUS) / CELL));
    const c1 = Math.min(cols - 1, Math.floor((x + RADIUS) / CELL));
    const r0 = Math.max(0, Math.floor((y - RADIUS) / CELL));
    const r1 = Math.min(rows - 1, Math.floor((y + RADIUS) / CELL));
    for (let r = r0; r <= r1; r++) {
      for (let c = c0; c <= c1; c++) {
        const dx = (c + 0.5) * CELL - x;
        const dy = (r + 0.5) * CELL - y;
        const d = Math.sqrt(dx * dx + dy * dy) / RADIUS;
        if (d >= 1) continue;
        const i = r * cols + c;
        // Grain pushes some cells out of the disc: a dithered edge, not a circle.
        const v = strength * (1 - d) ** 1.6 * (0.45 + 0.55 * grain[i]);
        if (v > heat[i]) heat[i] = v;
      }
    }
  };

  const draw = (now: number) => {
    // A resting pointer keeps a quiet halo, redrawn at a lower rate.
    if (pointer && now - lastMove > IDLE_MS && now - last < IDLE_FRAME_MS) {
      frame = requestAnimationFrame(draw);
      return;
    }
    // Real elapsed time, so a throttled background window still fades on schedule.
    const dt = last ? Math.min(now - last, 1000) : 16;
    last = now;
    const fade = Math.exp(-dt / FADE_MS);
    ctx.clearRect(0, 0, width, height);
    ctx.font = `${FONT_PX}px ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    if (pointer) {
      stamp(pointer.x, pointer.y, REST);
      if (glowLevel < REST) glowLevel = REST;
    }

    if (pointer && glowLevel > 0.015) {
      // A soft blue glow under the pointer, so the digits sit in light.
      const glow = ctx.createRadialGradient(
        pointer.x,
        pointer.y,
        0,
        pointer.x,
        pointer.y,
        RADIUS * 1.4,
      );
      glow.addColorStop(0, `hsl(${hue} / ${0.14 * glowLevel})`);
      glow.addColorStop(1, `hsl(${hue} / 0)`);
      ctx.fillStyle = glow;
      ctx.fillRect(
        pointer.x - RADIUS * 1.4,
        pointer.y - RADIUS * 1.4,
        RADIUS * 2.8,
        RADIUS * 2.8,
      );
    }

    let warm = false;
    for (let i = 0; i < heat.length; i++) {
      let h = heat[i];
      if (h < 0.015) {
        heat[i] = 0;
        continue;
      }
      warm = true;
      // Hot cells churn: the hotter, the more often the digit flips.
      if (Math.random() < h * 0.12) bits[i] ^= 1;
      const x = ((i % cols) + 0.5) * CELL;
      const y = (Math.floor(i / cols) + 0.5) * CELL;
      // The core burns near-white, the wake cools to the accent blue.
      ctx.fillStyle =
        h > 0.6
          ? `hsl(212 100% 85% / ${Math.min(1, h * 1.2)})`
          : `hsl(${hue} / ${Math.min(1, h * 1.35)})`;
      ctx.fillText(bits[i] ? "1" : "0", x, y);
      h *= fade;
      heat[i] = h;
    }

    glowLevel *= fade;
    // Once the pointer has left and the wake has burnt out, the loop stops.
    frame = warm ? requestAnimationFrame(draw) : 0;
    if (!frame) last = 0;
  };

  const wake = () => {
    if (!frame) frame = requestAnimationFrame(draw);
  };

  const onMove = (e: PointerEvent) => {
    if (e.pointerType === "touch") return;
    // Over a marked control (the composer) the field steps aside, as if the
    // pointer had left the page: no new digits, the wake fades out.
    if (e.target instanceof Element && e.target.closest(`[${FIELD_OFF_ATTR}]`)) {
      pointer = null;
      return;
    }
    const rect = host.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    // Fill the gap between two events so a fast sweep leaves an unbroken wake.
    if (pointer) {
      const dist = Math.hypot(x - pointer.x, y - pointer.y);
      const steps = Math.min(24, Math.floor(dist / (CELL * 1.5)));
      for (let s = 1; s <= steps; s++) {
        const t = s / (steps + 1);
        stamp(pointer.x + (x - pointer.x) * t, pointer.y + (y - pointer.y) * t);
      }
    }
    stamp(x, y);
    pointer = { x, y };
    glowLevel = 1;
    lastMove = performance.now();
    wake();
  };

  const onLeave = () => {
    pointer = null;
  };

  resize();
  const ro = new ResizeObserver(resize);
  ro.observe(host);
  // The theme switch swaps --accent; pick it up on the next hover.
  host.addEventListener("pointerenter", readHue);
  host.addEventListener("pointermove", onMove);
  host.addEventListener("pointerleave", onLeave);
  return () => {
    ro.disconnect();
    host.removeEventListener("pointerenter", readHue);
    host.removeEventListener("pointermove", onMove);
    host.removeEventListener("pointerleave", onLeave);
    if (frame) cancelAnimationFrame(frame);
  };
}

/** Put this attribute on an element to keep the field off while the pointer is over it. */
const FIELD_OFF_ATTR = "data-binary-field-off";

/** Grid pitch in CSS pixels. */
const CELL = 14;
/** Digit size; a little under the pitch so neighbours never touch. */
const FONT_PX = 11;
/** How far from the pointer the digits light up. */
const RADIUS = 120;
/** Time constant of the wake's fade. */
const FADE_MS = 420;
/** Strength of the halo that stays around a resting pointer. */
const REST = 0.5;
/** After this long without movement the pointer counts as resting... */
const IDLE_MS = 400;
/** ...and the halo is redrawn about 16 times a second instead of every frame. */
const IDLE_FRAME_MS = 60;
