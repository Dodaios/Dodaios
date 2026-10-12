import { useEffect, useRef } from "react";
import { useReducedMotion } from "framer-motion";
import {
  creatureBody, creaturePose, CREATURE_STILL_FRAME, CREATURE_TICK_MS, GRID, STAGE_H, STAGE_W, STAGE_X, STAGE_Y,
  type CreatureLook, type CreatureState,
} from "./creature";
import { FACE_YAW, paintCreature } from "./creaturePaint";

/**
 * One clock for every creature on screen. It only runs while a visible
 * creature listens and the window is shown, and each face repaints only when
 * its pose actually changed: a resting roster costs a blink every six seconds.
 */
const listeners = new Set<(frame: number) => void>();
let timer: number | undefined;
let watching = false;

function tick(): void {
  const frame = Math.floor(performance.now() / CREATURE_TICK_MS);
  for (const listener of listeners) listener(frame);
}

/** Runs the timer exactly while someone listens and the window is visible. */
function syncClock(): void {
  const run = listeners.size > 0 && !document.hidden;
  if (run && timer === undefined) timer = window.setInterval(tick, CREATURE_TICK_MS);
  else if (!run && timer !== undefined) {
    window.clearInterval(timer);
    timer = undefined;
  }
}

function onFrame(listener: (frame: number) => void): () => void {
  listeners.add(listener);
  if (!watching) {
    watching = true;
    document.addEventListener("visibilitychange", syncClock);
  }
  syncClock();
  return () => {
    listeners.delete(listener);
    syncClock();
  };
}

/**
 * An agent's pixel creature at `size` pixels, acting out `state`. The figure
 * fills the square like every other agent face; the canvas reaches a little
 * past it on each side, so a question mark or a spark can play beside the
 * head without a wider layout. Reduced motion shows one still frame per state.
 */
export function PixelCreature({ creature, size, state = "idle" }: { creature: CreatureLook; size: number; state?: CreatureState }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const reduced = useReducedMotion() ?? false;
  const { seed, palette, eyes } = creature;
  useEffect(() => {
    const node = canvas.current;
    // No 2D canvas (a test DOM): the box keeps its size and stays empty.
    if (!node || typeof CanvasRenderingContext2D === "undefined") return;
    const context = node.getContext("2d");
    if (!context) return;
    const body = creatureBody({ seed, palette, eyes });
    // Twice the layout size at least: the turned cubes need the extra pixels to stay crisp.
    const scale = Math.max(2, Math.min(window.devicePixelRatio || 1, 3));
    const width = Math.round((size * STAGE_W / GRID) * scale);
    node.width = width;
    node.height = Math.round((width * STAGE_H) / STAGE_W);
    if (reduced) {
      paintCreature(context, width, body, creaturePose(state, CREATURE_STILL_FRAME[state]), FACE_YAW);
      return;
    }
    // Each creature runs a little out of step, so a roster never blinks as one.
    const offset = (seed * 13) % 60;
    let shown = "";
    const draw = (frame: number) => {
      const pose = creaturePose(state, frame + offset);
      const key = JSON.stringify(pose);
      if (key === shown) return;
      shown = key;
      paintCreature(context, width, body, pose, FACE_YAW);
    };
    draw(Math.floor(performance.now() / CREATURE_TICK_MS));
    let stop: (() => void) | undefined;
    const watch = (visible: boolean) => {
      if (visible && !stop) stop = onFrame(draw);
      else if (!visible && stop) { stop(); stop = undefined; }
    };
    if (typeof IntersectionObserver === "undefined") {
      watch(true);
      return () => watch(false);
    }
    const observer = new IntersectionObserver((entries) => watch(entries.some((entry) => entry.isIntersecting)));
    observer.observe(node);
    return () => { observer.disconnect(); watch(false); };
  }, [seed, palette, eyes, size, state, reduced]);
  const cell = size / GRID;
  return <span className="relative inline-block shrink-0" data-agent-creature={seed} data-creature-state={state} style={{ width: size, height: size }}>
    <canvas ref={canvas} aria-hidden className="pointer-events-none absolute max-w-none"
      style={{ left: -STAGE_X * cell, top: -STAGE_Y * cell, width: STAGE_W * cell, height: STAGE_H * cell }} />
  </span>;
}

/** How far the stage figure sways to each side of its resting turn, radians. */
const STAGE_SWAY = 0.5;
/** One sway takes this long, milliseconds. */
const STAGE_SWAY_MS = 7000;
/** The stage repaints at most this often, milliseconds: the sway is slow, and a preview must stay cheap. */
const STAGE_FRAME_MS = 33;
/** How far a drag across the whole stage turns the figure, radians. */
const STAGE_DRAG_TURN = Math.PI * 1.5;

/**
 * The large preview of a pixel creature in the look editor: the same cubes
 * as the profile face, big, swaying slowly so every side shows, and turned
 * by dragging. It is a 2D canvas on purpose: it needs no WebGL context, so it
 * shows on every machine and never competes with the map for one.
 */
export function CreatureStage({ creature, state = "idle" }: { creature: CreatureLook; state?: CreatureState }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const turn = useRef(0);
  const reduced = useReducedMotion() ?? false;
  const { seed, palette, eyes } = creature;
  useEffect(() => {
    const node = canvas.current;
    if (!node || typeof CanvasRenderingContext2D === "undefined") return;
    const context = node.getContext("2d");
    if (!context) return;
    const body = creatureBody({ seed, palette, eyes });
    let width = 0;
    let shown = "";
    let frameRequest = 0;
    let visible = true;
    let painted = -Infinity;
    const paint = (now: number, force = false) => {
      if (!force && now - painted < STAGE_FRAME_MS) return;
      painted = now;
      const scale = Math.min(window.devicePixelRatio || 1, 2);
      const next = Math.round(node.clientWidth * scale);
      if (next === 0) return;
      if (next !== width) {
        width = next;
        node.width = width;
        node.height = Math.round((width * STAGE_H) / STAGE_W);
        shown = "";
      }
      const frame = reduced ? CREATURE_STILL_FRAME[state] : Math.floor(now / CREATURE_TICK_MS);
      const sway = reduced ? 0 : Math.sin((now / STAGE_SWAY_MS) * Math.PI * 2) * STAGE_SWAY;
      const yaw = FACE_YAW + sway + turn.current;
      const key = `${frame}|${yaw.toFixed(3)}`;
      if (key === shown) return;
      shown = key;
      paintCreature(context, width, body, creaturePose(state, frame), yaw);
    };
    const loop = (now: number) => {
      paint(now);
      // Reduced motion paints once and again only after a drag.
      frameRequest = visible && !reduced ? requestAnimationFrame(loop) : 0;
    };
    const start = () => { if (!frameRequest) frameRequest = requestAnimationFrame(loop); };
    start();

    let dragFrom: number | null = null;
    const onDown = (event: PointerEvent) => { dragFrom = event.clientX; node.setPointerCapture(event.pointerId); };
    const onMove = (event: PointerEvent) => {
      if (dragFrom === null) return;
      turn.current += ((event.clientX - dragFrom) / Math.max(1, node.clientWidth)) * STAGE_DRAG_TURN;
      dragFrom = event.clientX;
      // A still figure (reduced motion) repaints on the drag itself.
      if (reduced) paint(performance.now(), true); else start();
    };
    const onUp = () => { dragFrom = null; };
    node.addEventListener("pointerdown", onDown);
    node.addEventListener("pointermove", onMove);
    node.addEventListener("pointerup", onUp);
    node.addEventListener("pointercancel", onUp);
    const observer = typeof IntersectionObserver === "undefined" ? null
      : new IntersectionObserver((entries) => { visible = entries.some((entry) => entry.isIntersecting); if (visible) start(); });
    observer?.observe(node);
    return () => {
      observer?.disconnect();
      if (frameRequest) cancelAnimationFrame(frameRequest);
      node.removeEventListener("pointerdown", onDown);
      node.removeEventListener("pointermove", onMove);
      node.removeEventListener("pointerup", onUp);
      node.removeEventListener("pointercancel", onUp);
    };
  }, [seed, palette, eyes, state, reduced]);
  return <div className="flex h-56 w-full items-center justify-center" data-testid="creature-stage" data-creature-state={state}>
    <canvas ref={canvas} aria-hidden className="h-full max-w-full cursor-grab touch-none active:cursor-grabbing" style={{ aspectRatio: `${STAGE_W} / ${STAGE_H}` }} />
  </div>;
}
