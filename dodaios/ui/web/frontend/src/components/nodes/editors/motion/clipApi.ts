/**
 * The clip editor's calls to the app (`dodaios/ui/web/clip_routes.py`):
 * upload a file into the clip's library, ask for captions or silences, and
 * run an export. None of them changes the spec on the server: what comes back
 * is put into the editor's spec as an undoable step, so the person keeps the
 * last word and the autosave writes it.
 */
import { NodesApiError } from "../../useNodes";
import type { CaptionLine, MediaEntry, MotionSpec } from "./motionModel";

function clipUrl(nodeId: string, tail: string): string {
  return `/api/nodes/${encodeURIComponent(nodeId)}/clip${tail}`;
}

/** Where a library file (or its poster, filmstrip, waveform) is served. */
export function mediaUrl(nodeId: string, file: string): string {
  return `/clip-media/${encodeURIComponent(nodeId)}/${encodeURIComponent(file)}`;
}

/** The side files the import writes next to a library file. */
export function sideFile(file: string, kind: "poster.jpg" | "strip.jpg" | "wave.json"): string {
  return `${file.replace(/\.[^.]+$/, "")}.${kind}`;
}

async function failure(response: Response): Promise<never> {
  let detail = "";
  try {
    const body = (await response.json()) as Record<string, unknown>;
    detail = typeof body.detail === "string" ? body.detail : "";
  } catch {
    // No JSON body: the status is all there is to report.
  }
  throw new NodesApiError(response.status, detail);
}

async function postJson<T>(url: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) return failure(response);
  return (await response.json()) as T;
}

export interface UploadedMedia {
  id: string;
  entry: MediaEntry;
}

/** Send one file into the clip's library; `onProgress` gets 0…1 while it uploads. */
export function uploadMedia(nodeId: string, file: File, onProgress?: (share: number) => void): Promise<UploadedMedia> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", clipUrl(nodeId, "/media"));
    request.setRequestHeader("X-File-Name", encodeURIComponent(file.name));
    request.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    request.onload = () => {
      let body: Record<string, unknown> = {};
      try {
        body = JSON.parse(request.responseText) as Record<string, unknown>;
      } catch {
        // Not JSON: reported by status below.
      }
      if (request.status >= 200 && request.status < 300 && typeof body.id === "string") {
        resolve({ id: body.id, entry: body.entry as MediaEntry });
      } else {
        reject(new NodesApiError(request.status, typeof body.detail === "string" ? body.detail : ""));
      }
    };
    request.onerror = () => reject(new NodesApiError(0, ""));
    request.send(file);
  });
}

/** Captions for the speech of the clip as it is edited now. */
export async function fetchCaptions(nodeId: string, spec: MotionSpec, language?: string): Promise<CaptionLine[]> {
  const body = await postJson<{ items: CaptionLine[] }>(clipUrl(nodeId, "/captions"), { spec, language });
  return body.items ?? [];
}

/** The silent stretches of a library file between `from` and `to` (source seconds). */
export async function fetchSilences(
  nodeId: string,
  media: string,
  from: number,
  to: number,
  minSilence = 0.5,
): Promise<[number, number][]> {
  const body = await postJson<{ silences: [number, number][] }>(clipUrl(nodeId, "/silences"), {
    media,
    in: from,
    out: to,
    min_silence: minSilence,
  });
  return body.silences ?? [];
}

export interface WavePeaks {
  rate: number;
  peaks: number[];
}

const waves = new Map<string, Promise<WavePeaks | null>>();

/** A file's waveform peaks (cached: a file never changes under its name). */
export function fetchWave(nodeId: string, file: string): Promise<WavePeaks | null> {
  const url = mediaUrl(nodeId, sideFile(file, "wave.json"));
  let found = waves.get(url);
  if (!found) {
    found = fetch(url)
      .then((response) => (response.ok ? (response.json() as Promise<WavePeaks>) : null))
      .catch(() => null);
    waves.set(url, found);
  }
  return found;
}

export type ExportPreset = "720p" | "1080p" | "2160p";

export interface ExportStatus {
  state: "running" | "done" | "failed" | "cancelled";
  progress: number;
  frame?: number;
  frames?: number;
  file?: string;
  error?: string;
}

export async function startExport(nodeId: string, spec: MotionSpec, preset: ExportPreset, fps: number): Promise<string> {
  const body = await postJson<{ job: string }>(clipUrl(nodeId, "/export"), { spec, preset, fps });
  return body.job;
}

export async function exportStatus(nodeId: string, job: string): Promise<ExportStatus> {
  const response = await fetch(clipUrl(nodeId, `/export/${encodeURIComponent(job)}`));
  if (!response.ok) return failure(response);
  return (await response.json()) as ExportStatus;
}

export async function cancelExport(nodeId: string, job: string): Promise<void> {
  await fetch(clipUrl(nodeId, `/export/${encodeURIComponent(job)}`), { method: "DELETE" });
}

export function exportFileUrl(nodeId: string, job: string): string {
  return clipUrl(nodeId, `/export/${encodeURIComponent(job)}/file`);
}
