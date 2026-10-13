/**
 * Draws 3D profile faces off the UI thread: reads the companion models once,
 * traces a figure per shape, outfit and size, and shades it in the asked
 * colours. Traces are kept, so another colour on the same figure is only
 * the cheap half of the work. Terminating the worker releases everything.
 */
import { meshesByName, readGlb, type FigureMesh } from "./figureGlb";
import { figureCover, shadeFigure, traceFigure, type FigureTrace } from "./figureRender";
import {
  bodyEffectMoves, figureFaceMatrix, figureParts, figureSmoke, figureTraceKey, wearsAccessories, type FigureLook, type FigureSmoke,
} from "./figureScene";

export interface FigureRequest {
  id: number;
  look: FigureLook;
  /** Width and height of the picture, device pixels. */
  pixels: number;
  /** Absolute URLs of companions.glb and accessories.glb. */
  bodies: string;
  worn: string;
}

export type FigureResponse =
  | {
    id: number; ok: true; pixels: number; data: ArrayBuffer; face: [number, number, number, number, number, number];
    /** How much of each pixel is body, one byte per pixel: only for a look whose effect moves across the body. */
    body?: ArrayBuffer;
    smoke: FigureSmoke[];
  }
  | { id: number; ok: false };

type Meshes = Map<string, FigureMesh[]>;

const files = new Map<string, Promise<Meshes>>();

function load(url: string): Promise<Meshes> {
  let file = files.get(url);
  if (!file) {
    file = fetch(url).then(async response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return meshesByName(readGlb(await response.arrayBuffer()));
    });
    files.set(url, file);
    // A failed download is tried again with the next picture.
    file.catch(() => files.delete(url));
  }
  return file;
}

/** The most trace memory kept, bytes: ten bytes per sample. */
const TRACE_BUDGET = 40 * 1024 * 1024;
const traces = new Map<string, FigureTrace>();
let traceBytes = 0;

function traceSize(trace: FigureTrace): number {
  return trace.depth.byteLength + trace.normal.byteLength + trace.owner.byteLength + trace.light.byteLength + trace.open.byteLength;
}

function remember(key: string, trace: FigureTrace): void {
  traces.set(key, trace);
  traceBytes += traceSize(trace);
  // Oldest first: a Map keeps insertion order, and a hit is moved to the end.
  for (const [old, value] of traces) {
    if (traceBytes <= TRACE_BUDGET || old === key) break;
    traces.delete(old);
    traceBytes -= traceSize(value);
  }
}

async function draw(request: FigureRequest): Promise<FigureResponse> {
  const { look, pixels } = request;
  const bodies = await load(request.bodies);
  const worn = wearsAccessories(look) ? await load(request.worn) : undefined;
  const parts = figureParts(look, bodies, worn);
  const key = figureTraceKey(look, pixels);
  let trace = traces.get(key);
  if (trace) { traces.delete(key); traces.set(key, trace); }
  else { trace = traceFigure(parts, pixels); remember(key, trace); }
  const image = shadeFigure(trace, parts);
  return {
    id: request.id, ok: true, pixels, data: image.data.buffer as ArrayBuffer, face: figureFaceMatrix(look, bodies, image.frame),
    body: bodyEffectMoves(look) ? figureCover(trace, parts.map(part => !!part.body)).buffer : undefined,
    smoke: figureSmoke(look, image.frame),
  };
}

// One picture at a time, in the order asked.
let chain: Promise<void> = Promise.resolve();

self.onmessage = (event: MessageEvent<FigureRequest>) => {
  const request = event.data;
  chain = chain.then(async () => {
    let answer: FigureResponse;
    try {
      answer = await draw(request);
    } catch (error) {
      // The face falls back to the flat symbol; the reason stays readable in the console.
      console.warn("Companion figure unavailable", error);
      answer = { id: request.id, ok: false };
    }
    if (answer.ok) (self as unknown as { postMessage: (message: FigureResponse, transfer: Transferable[]) => void }).postMessage(answer, answer.body ? [answer.data, answer.body] : [answer.data]);
    else self.postMessage(answer);
  });
};
