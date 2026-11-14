/**
 * The whiteboard's own routes: its scene and its pictures.
 *
 * A whiteboard node keeps the editor's scene as its spec. The editor reads it
 * whole (`GET /scene`) and writes it whole (`PUT /scene`); the server merges
 * what it gets with what it holds, element by element, so a save never
 * overwrites what the assistant drew meanwhile. When the server had something
 * newer, its answer carries the merged scene back. Pictures travel apart from
 * the scene (`/files`): the scene only names them.
 */
import { NodesApiError } from "../useNodes";

/** One element of the editor's scene, as the server stores it. */
export interface BoardElement {
  id: string;
  type: string;
  version: number;
  versionNonce: number;
  isDeleted: boolean;
  /** Image elements only. */
  fileId?: string | null;
  [field: string]: unknown;
}

/** What the server keeps of a picture: the bytes live behind `/files/{id}`. */
export interface BoardFileMeta {
  id: string;
  mimeType: string;
  /** Milliseconds since the epoch. */
  created: number;
}

export interface BoardAppState {
  viewBackgroundColor?: string;
  gridModeEnabled?: boolean;
}

/** A whiteboard node's spec. */
export interface BoardScene {
  format: "scene";
  elements: BoardElement[];
  appState: BoardAppState;
  files: Record<string, BoardFileMeta>;
}

export interface SceneRead {
  version: number;
  /** Seconds since the epoch: the same clock the node's state reports. */
  updated_at: number;
  scene: BoardScene;
}

export interface SceneWrite {
  version: number;
  updated_at: number;
  /** The server held something newer than what was sent; `scene` is the merge. */
  merged: boolean;
  scene?: BoardScene;
}

function boardUrl(nodeId: string, tail: string): string {
  return `/api/nodes/${encodeURIComponent(nodeId)}${tail}`;
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // No JSON body: the status is all there is to report.
    }
    throw new NodesApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

/** A scene as the server may hand it out, with every list and map present. */
export function normalizeScene(raw: unknown): BoardScene {
  const scene = (raw && typeof raw === "object" ? raw : {}) as Partial<BoardScene>;
  return {
    format: "scene",
    elements: Array.isArray(scene.elements) ? scene.elements : [],
    appState: scene.appState && typeof scene.appState === "object" ? scene.appState : {},
    files: scene.files && typeof scene.files === "object" ? scene.files : {},
  };
}

export async function fetchScene(nodeId: string, signal?: AbortSignal): Promise<SceneRead> {
  const data = await readJson<SceneRead>(await fetch(boardUrl(nodeId, "/scene"), { signal }));
  return { ...data, scene: normalizeScene(data.scene) };
}

/** The browser drops a `keepalive` request whose body is larger than this. */
const KEEPALIVE_MAX_BYTES = 60_000;

/**
 * Save the scene. `leaving` marks the save made while the window goes away:
 * a small one is sent so that it outlives the page.
 */
export async function putScene(nodeId: string, scene: BoardScene, init?: { leaving?: boolean }): Promise<SceneWrite> {
  const body = JSON.stringify({ scene });
  const data = await readJson<SceneWrite>(
    await fetch(boardUrl(nodeId, "/scene"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: init?.leaving === true && body.length < KEEPALIVE_MAX_BYTES,
    }),
  );
  return data.merged && data.scene ? { ...data, scene: normalizeScene(data.scene) } : data;
}

/** Keep one picture of the board. The server reads the type from the bytes. */
export async function uploadBoardFile(
  nodeId: string,
  file: { id: string; dataURL: string },
): Promise<{ id: string; mimeType: string }> {
  return readJson(
    await fetch(boardUrl(nodeId, "/files"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dataURL: file.dataURL, id: file.id }),
    }),
  );
}

export function boardFileUrl(nodeId: string, fileId: string): string {
  return boardUrl(nodeId, `/files/${encodeURIComponent(fileId)}`);
}

/** One picture of the board as a data URL, the form the editor takes. */
export async function fetchBoardFile(nodeId: string, fileId: string): Promise<{ dataURL: string; mimeType: string }> {
  const response = await fetch(boardFileUrl(nodeId, fileId));
  if (!response.ok) throw new NodesApiError(response.status, "");
  // The server names the type the bytes really have. The data URL is built
  // from the bytes themselves rather than through a FileReader: that works the
  // same in every engine, and a FileReader refuses a Blob from another realm.
  const mimeType = (response.headers.get("Content-Type") || "application/octet-stream").split(";")[0]!.trim();
  const bytes = new Uint8Array(await response.arrayBuffer());
  let binary = "";
  for (let start = 0; start < bytes.length; start += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(start, start + 0x8000));
  }
  return { dataURL: `data:${mimeType};base64,${btoa(binary)}`, mimeType };
}
