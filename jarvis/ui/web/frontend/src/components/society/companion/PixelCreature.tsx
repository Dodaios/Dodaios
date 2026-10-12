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
