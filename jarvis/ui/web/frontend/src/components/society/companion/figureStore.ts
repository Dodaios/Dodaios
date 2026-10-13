/**
 * The pictures of 3D profile faces, shared by every face on screen. A face
 * asks for its look at its size; the worker (figure.worker.ts) draws each
 * picture once and it is kept here, so a roster, a chat and a dialog showing
 * the same agent share one drawing. Without a worker (an old webview, a test
 * DOM) or after a failure, faces fall back to the flat symbol.
 */
import accessoryModels from "@/assets/society/companions/accessories.glb";
import companionModels from "@/assets/society/companions/companions.glb";
import type { FigureRequest, FigureResponse } from "./figure.worker";
import { figureKey, type FigureLook } from "./figureScene";

export interface Figure {
  /** Width and height, device pixels. */
  pixels: number;
  /** Straight-alpha RGBA. */
  data: Uint8ClampedArray<ArrayBuffer>;
  /** SVG matrix from flat symbol units to picture pixels, at the eyes (figureFaceMatrix). */
  face: [number, number, number, number, number, number];
}

/** The most picture memory kept, bytes. */
const PICTURE_BUDGET = 24 * 1024 * 1024;
/** A worker with nothing to draw is released after this long, milliseconds. */
const IDLE_MS = 45_000;
/** A picture that takes longer than this is given up, milliseconds. */
const ANSWER_MS = 30_000;
/** A picture that failed, or a worker that broke, is tried again after this long, milliseconds. */
const RETRY_MS = 60_000;
/** A worker that keeps breaking is left alone after this many tries. */
const WORKER_TRIES = 3;

/** What `readFigure` answers for a look that could not be drawn: the face shows its flat symbol. */
export const FIGURE_BROKEN = "broken";

const pictures = new Map<string, Figure>();
let pictureBytes = 0;
/** Looks that could not be drawn, with the time they failed. */
const broken = new Map<string, number>();
const wanted = new Map<string, { look: FigureLook; pixels: number; listeners: Set<() => void> }>();
const supportListeners = new Set<() => void>();
let worker: Worker | undefined;
let current: { id: number; key: string } | undefined;
let nextId = 1;
let failed = false;
let workerFailures = 0;
let idleTimer: ReturnType<typeof setTimeout> | undefined;
let answerTimer: ReturnType<typeof setTimeout> | undefined;

/** True while faces can be drawn in 3D here. */
export function figuresSupported(): boolean {
  return !failed && typeof Worker !== "undefined" && typeof ImageData !== "undefined";
}

export function watchFigureSupport(listener: () => void): () => void {
  supportListeners.add(listener);
  return () => { supportListeners.delete(listener); };
}

/** The finished picture of a look at a size, `FIGURE_BROKEN` if it could not be drawn, or nothing yet. */
export function readFigure(look: FigureLook, pixels: number): Figure | typeof FIGURE_BROKEN | undefined {
  const key = figureKey(look, pixels);
  return pictures.get(key) ?? (broken.has(key) ? FIGURE_BROKEN : undefined);
}

function release(): void {
  clearTimeout(idleTimer);
  clearTimeout(answerTimer);
  worker?.terminate();
  worker = undefined;
  current = undefined;
}

/**
 * The worker itself is unusable: every face falls back to the flat symbol.
 * A worker that broke while running (its script could not be fetched during
 * a restart, say) gets a few more tries later; one that cannot be built at
 * all (no module workers, a strict content policy) does not.
 */
function fail(retry: boolean): void {
  failed = true;
  release();
  const listeners = [...wanted.values()].flatMap(entry => [...entry.listeners]);
  wanted.clear();
  for (const listener of [...supportListeners, ...listeners]) listener();
  if (!retry || ++workerFailures >= WORKER_TRIES) return;
  setTimeout(() => {
    failed = false;
    supportListeners.forEach(listener => listener());
  }, RETRY_MS);
}

/** One look could not be drawn: its faces show the flat symbol, the others carry on. */
function giveUp(key: string): void {
  broken.set(key, Date.now());
  if (current?.key === key) current = undefined;
  const entry = wanted.get(key);
  wanted.delete(key);
  entry?.listeners.forEach(listener => listener());
  pump();
}

function keep(key: string, figure: Figure): void {
  pictures.set(key, figure);
  pictureBytes += figure.data.byteLength;
  // Oldest first; a Map keeps insertion order. A face that still shows an evicted picture keeps its own copy.
  for (const [old, value] of pictures) {
    if (pictureBytes <= PICTURE_BUDGET || old === key) break;
    pictures.delete(old);
    pictureBytes -= value.data.byteLength;
  }
}

function answer(message: FigureResponse): void {
  if (!current || message.id !== current.id) return;
  clearTimeout(answerTimer);
  const { key } = current;
  // The worker logged why; a failed download is tried again with the next look.
  if (!message.ok) { giveUp(key); return; }
  current = undefined;
  workerFailures = 0;
  keep(key, { pixels: message.pixels, data: new Uint8ClampedArray(message.data), face: message.face });
  const entry = wanted.get(key);
  wanted.delete(key);
  entry?.listeners.forEach(listener => listener());
  pump();
}

function pump(): void {
  if (current || failed) return;
  // The newest request first: what was asked last is what the person looks at now.
  let key: string | undefined;
  for (const candidate of wanted.keys()) key = candidate;
  if (key === undefined) {
    clearTimeout(idleTimer);
    idleTimer = setTimeout(release, IDLE_MS);
    return;
  }
  const asking = key;
  const entry = wanted.get(asking)!;
  clearTimeout(idleTimer);
  try {
    if (!worker) {
      worker = new Worker(new URL("./figure.worker.ts", import.meta.url), { type: "module" });
      worker.onmessage = (event: MessageEvent<FigureResponse>) => answer(event.data);
      worker.onerror = event => {
        console.warn("Companion figure worker failed", event.message);
        fail(true);
      };
    }
    const asked = current = { id: nextId++, key: asking };
    const request: FigureRequest = {
      id: asked.id, look: entry.look, pixels: entry.pixels,
      bodies: new URL(companionModels, location.href).href, worn: new URL(accessoryModels, location.href).href,
    };
    worker.postMessage(request);
    answerTimer = setTimeout(() => {
      if (current !== asked) return;
      // A stuck worker is replaced; only this look is given up.
      console.warn("Companion figure took too long", asking);
      release();
      giveUp(asking);
    }, ANSWER_MS);
  } catch (error) {
    // No worker here (a strict content policy, an old webview): the flat symbol stays.
    console.warn("Companion figures unavailable", error);
    fail(false);
  }
}

/**
 * Asks for a picture and calls `listener` once it is there (or once it turned
 * out that it cannot be drawn). A picture nobody waits for any more is not
 * drawn. Returns the function that stops waiting.
 */
export function watchFigure(look: FigureLook, pixels: number, listener: () => void): () => void {
  if (!figuresSupported()) return () => {};
  const key = figureKey(look, pixels);
  if (pictures.has(key)) return () => {};
  const since = broken.get(key);
  if (since !== undefined) {
    if (Date.now() - since < RETRY_MS) return () => {};
    broken.delete(key);
  }
  let entry = wanted.get(key);
  if (!entry) wanted.set(key, entry = { look, pixels, listeners: new Set() });
  entry.listeners.add(listener);
  pump();
  return () => {
    entry.listeners.delete(listener);
    if (!entry.listeners.size && current?.key !== key && wanted.get(key) === entry) wanted.delete(key);
  };
}
