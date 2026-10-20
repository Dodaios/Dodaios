/**
 * Loads a cooked deck (schema verse.deck/1, written by scripts/verse/package.py)
 * into the runtime `Deck`: the manifest is validated, URLs are resolved
 * against it, and the nav PNG is decoded into walkable bits and floor heights.
 *
 * A deck that is missing or broken is an error the stage shows, never a
 * half-built scene.
 */
import type { DeckId } from "../decks";
import { STATION_KINDS, type Deck, type NavGrid, type PlateImages, type PlateLevel, type Socket, type Station, type StationKind } from "./deck";
import { fetchImageBitmap } from "../engine/imageFetch";
import {
  fillTileUrl, manifestUrl as resolveUrl, parseDeckManifest,
  type DeckManifest, type ManifestCamera, type ManifestNav, type ManifestPlate, type ManifestSocket,
} from "./manifest";

export class DeckLoadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DeckLoadError";
  }
}

/**
 * A socket id's group and order: kit sockets join the placement and the local
 * id with "__" (`brief__01`), hand-placed ones end in `_<n>` (`pit_p_3`). Pure.
 */
export function socketGroup(id: string): { group: string; order: number } {
  const cut = id.lastIndexOf("__");
  if (cut > 0) {
    const tail = id.slice(cut + 2);
    return { group: id.slice(0, cut), order: /^\d+$/.test(tail) ? Number(tail) : 0 };
  }
  const m = /^(.*?)_?(\d+)$/.exec(id);
  return m ? { group: m[1], order: Number(m[2]) } : { group: id, order: 0 };
}

function socketOf(raw: ManifestSocket): Socket {
  const { group, order } = socketGroup(raw.id);
  const [x, y, z] = raw.position;
  return {
    id: raw.id,
    kind: raw.kind,
    x, y, z,
    yaw: (raw.yaw_deg * Math.PI) / 180,
    room: raw.room ?? null,
    group,
    order,
    station: raw.station ?? null,
    corners: raw.corners ?? null,
    size: raw.size ?? null,
    props: raw.props ?? {},
  };
}

/**
 * The plate's images: L0, the optional mips by growing divisor (only those
 * finer than the overview, which covers everything coarser), the overview.
 * Pure apart from URL resolution.
 */
export function plateImages(camera: ManifestCamera, plate: ManifestPlate, url: (relative: string) => string): PlateImages {
  const tileSize = plate.tile_px;
  const l0: PlateLevel = {
    divisor: 1, width: camera.plate_w_px, height: camera.plate_h_px, tileSize, cols: plate.cols, rows: plate.rows,
    tileUrl: (col, row) => url(fillTileUrl(plate.tile_url, col, row)),
  };
  const mips: PlateLevel[] = (plate.mips ?? [])
    .filter((mip) => mip.w_px > plate.l1_w_px)
    .map((mip) => ({
      divisor: mip.divisor, width: mip.w_px, height: mip.h_px, tileSize, cols: mip.cols, rows: mip.rows,
      tileUrl: (col: number, row: number) => url(fillTileUrl(mip.tile_url, col, row)),
    }))
    .sort((a, b) => a.divisor - b.divisor);
  return {
    width: l0.width,
    height: l0.height,
    overview: { url: url(plate.l1_url), width: plate.l1_w_px, height: plate.l1_h_px },
    tileSize,
    cols: l0.cols,
    rows: l0.rows,
    tileUrl: l0.tileUrl,
    levels: [l0, ...mips],
  };
}

/** Validate a manifest and turn it into a deck (nav still to decode). Pure apart from URL resolution. */
export function deckFromManifest(json: unknown, at: string, deckId: DeckId, contentId: string): Omit<Deck, "nav"> & { navUrl: string; navMeta: ManifestNav } {
  let m: DeckManifest;
  try {
    m = parseDeckManifest(json);
  } catch (error) {
    throw new DeckLoadError(`Deck ${contentId}: bad manifest (${error instanceof Error ? error.message : String(error)})`);
  }
  const url = (relative: string) => resolveUrl(at, relative);
  const stations: Station[] = m.stations
    .filter((s) => (STATION_KINDS as readonly string[]).includes(s.kind))
    .map((s) => ({
      id: s.id, kind: s.kind as StationKind, room: s.room ?? null,
      x: s.position[0], y: s.position[1], z: s.position[2],
      sockets: (s.sockets ?? {}) as Station["sockets"],
    }));
  return {
    id: deckId,
    contentId,
    name: m.name,
    camera: {
      center: m.camera.centre,
      pitchDeg: m.camera.pitch_deg,
      frameW: m.camera.frame_w_m,
      frameH: m.camera.frame_h_m,
      pxPerMetre: m.camera.px_per_m,
    },
    plate: plateImages(m.camera, m.plate, url),
    occludersUrl: url(m.occluders.url),
    envUrl: url(m.env.url),
    exposure: m.camera.exposure,
    sockets: m.sockets.map(socketOf),
    stations,
    rooms: m.rooms.map((r) => ({ id: r.id, name: r.name, floorY: r.floor_y, polygon: r.polygon, main: r.main })),
    probes: m.probes.map((p) => ({ room: p.room, x: p.position[0], y: p.position[1], z: p.position[2], sh: p.sh })),
    navUrl: url(m.nav.url),
    navMeta: m.nav,
  };
}

/** Walkable bits and floor heights from the nav PNG's grey values (0 = blocked). Pure. */
export function navFromCodes(codes: Uint8Array | Uint8ClampedArray, stride: number, meta: ManifestNav): NavGrid {
  const n = meta.w * meta.h;
  const walkable = new Uint8Array(n);
  const heights = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const code = codes[i * stride];
    if (code === 0) continue;
    walkable[i] = 1;
    heights[i] = (code - meta.height_zero) * meta.height_step;
  }
  return { cell: meta.cell, x0: meta.origin_x, z0: meta.origin_z, cols: meta.w, rows: meta.h, walkable, heights, maxStep: meta.max_step };
}

async function decodeNav(url: string, meta: ManifestNav, signal: AbortSignal): Promise<NavGrid> {
  const bitmap = await fetchImageBitmap(url, signal);
  try {
    if (bitmap.width !== meta.w || bitmap.height !== meta.h) {
      throw new DeckLoadError(`Nav grid is ${bitmap.width}×${bitmap.height}, the manifest says ${meta.w}×${meta.h}`);
    }
    const canvas = new OffscreenCanvas(meta.w, meta.h);
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) throw new DeckLoadError("No 2D context to decode the nav grid");
    ctx.drawImage(bitmap, 0, 0);
    return navFromCodes(ctx.getImageData(0, 0, meta.w, meta.h).data, 4, meta);
  } finally {
    bitmap.close();
  }
}

/** Where a deck's cooked content lives. */
export function deckManifestUrl(contentId: string): string {
  return `${import.meta.env.BASE_URL}verse/decks/${contentId}/manifest.json`;
}

export async function loadDeck(deckId: DeckId, contentId: string, signal: AbortSignal): Promise<Deck> {
  const at = deckManifestUrl(contentId);
  const res = await fetch(at, { signal });
  if (!res.ok) throw new DeckLoadError(`Deck ${contentId} is not cooked yet (HTTP ${res.status})`);
  let json: unknown;
  try {
    json = await res.json();
  } catch {
    // The app answers a missing file with its index.html.
    throw new DeckLoadError(`Deck ${contentId} is not cooked yet (no manifest)`);
  }
  const { navUrl, navMeta, ...deck } = deckFromManifest(json, at, deckId, contentId);
  const nav = await decodeNav(navUrl, navMeta, signal);
  return { ...deck, nav };
}
