/**
 * Streams L0 plate tiles in and out of GPU memory.
 *
 * Each frame the plate layer says which tiles the view wants (visible ones
 * first, then a prefetch ring). The streamer fetches at most a few at once,
 * aborts what is no longer wanted, hands decoded tiles over for upload one per
 * frame (a 2048² upload with mipmaps is a few milliseconds; several in one
 * frame would hitch a pan), and keeps GPU memory bounded: at most
 * `maxResident` tiles, the least recently seen of the unwanted ones go first,
 * and an unwanted tile is let go after `idleMs` even under budget.
 */
import { LinearFilter, LinearMipmapLinearFilter, SRGBColorSpace, Texture, ClampToEdgeWrapping } from "three";
import type { PlateImages } from "../content/deck";
import type { PlateCamera } from "./plateMath";
import { tileKey, tileRect, type TileKey, type TileRect } from "./tiles";

export interface StreamedTile {
  key: string;
  rect: TileRect;
  texture: Texture;
  /** False until the texture has been uploaded (the layer draws only uploaded tiles). */
  uploaded: boolean;
  lastWanted: number;
}

export type BitmapLoader = (url: string, signal: AbortSignal) => Promise<ImageBitmap>;

export interface StreamerOptions {
  load: BitmapLoader;
  maxResident?: number;
  maxInFlight?: number;
  idleMs?: number;
  /** A failed tile is retried after this long. */
  retryMs?: number;
}

const byLastWanted = (a: StreamedTile, b: StreamedTile) => a.lastWanted - b.lastWanted;

export class TileStreamer {
  private readonly tiles = new Map<string, StreamedTile>();
  private readonly loading = new Map<string, AbortController>();
  private readonly failedUntil = new Map<string, number>();
  private readonly maxResident: number;
  private readonly maxInFlight: number;
  private readonly idleMs: number;
  private readonly retryMs: number;
  private disposed = false;
  // Scratch state reused by every update: the per-frame path allocates nothing while the view is still.
  private readonly wantedKeys = new Set<string>();
  private readonly idle: StreamedTile[] = [];
  private readonly keys = new Map<number, string>();

  constructor(private readonly plate: PlateImages, private readonly cam: PlateCamera, private readonly opts: StreamerOptions) {
    this.maxResident = opts.maxResident ?? 12;
    this.maxInFlight = opts.maxInFlight ?? 3;
    this.idleMs = opts.idleMs ?? 20_000;
    this.retryMs = opts.retryMs ?? 8_000;
  }

  /** Tell the streamer what the view wants; `wanted` is ordered by priority. */
  update(wanted: readonly TileKey[], now: number): void {
    if (this.disposed) return;
    const wantedKeys = this.wantedKeys;
    wantedKeys.clear();
    for (const k of wanted) {
      const key = this.keyOf(k);
      if (wantedKeys.has(key)) continue;
      wantedKeys.add(key);
      const tile = this.tiles.get(key);
      if (tile) tile.lastWanted = now;
    }
    for (const [key, ctrl] of this.loading) {
      if (!wantedKeys.has(key)) { ctrl.abort(); this.loading.delete(key); }
    }
    this.evict(wantedKeys, now);
    for (const k of wanted) {
      if (this.loading.size >= this.maxInFlight) break;
      const key = this.keyOf(k);
      if (this.tiles.has(key) || this.loading.has(key) || (this.failedUntil.get(key) ?? 0) > now) continue;
      if (this.tiles.size + this.loading.size >= this.maxResident) break;
      this.start(k, key);
    }
  }

  /** A decoded tile still waiting for its upload, the most wanted first; null when none. */
  nextUpload(): StreamedTile | null {
    let best: StreamedTile | null = null;
    for (const tile of this.tiles.values()) {
      if (!tile.uploaded && (!best || tile.lastWanted > best.lastWanted)) best = tile;
    }
    return best;
  }

  /** Uploaded tiles among `keys`. */
  drawable(keys: readonly TileKey[]): StreamedTile[] {
    const out: StreamedTile[] = [];
    for (const k of keys) {
      const tile = this.tiles.get(tileKey(k.col, k.row));
      if (tile?.uploaded) out.push(tile);
    }
    return out;
  }

  /** True while the tile with this key is resident and uploaded. */
  isDrawable(key: string): boolean {
    return this.tiles.get(key)?.uploaded === true;
  }

  get residentCount(): number {
    return this.tiles.size;
  }

  get inFlightCount(): number {
    return this.loading.size;
  }

  dispose(): void {
    this.disposed = true;
    for (const ctrl of this.loading.values()) ctrl.abort();
    this.loading.clear();
    for (const tile of this.tiles.values()) release(tile);
    this.tiles.clear();
  }

  private start(k: TileKey, key: string): void {
    const ctrl = new AbortController();
    this.loading.set(key, ctrl);
    const url = this.plate.tileUrl(k.col, k.row);
    this.opts.load(url, ctrl.signal).then((bitmap) => {
      if (this.loading.get(key) !== ctrl || this.disposed) { bitmap.close(); return; }
      this.loading.delete(key);
      this.tiles.set(key, { key, rect: tileRect(this.plate, this.cam, k.col, k.row), texture: plateTexture(bitmap), uploaded: false, lastWanted: performance.now() });
    }, (error: unknown) => {
      if (this.loading.get(key) !== ctrl) return;
      this.loading.delete(key);
      if (ctrl.signal.aborted) return;
      this.failedUntil.set(key, performance.now() + this.retryMs);
      console.warn("Verse plate tile failed", url, error);
    });
  }

  /** The tile's map key, built once per tile instead of once per frame. */
  private keyOf(k: TileKey): string {
    const id = k.col * 65_536 + k.row;
    let key = this.keys.get(id);
    if (key === undefined) { key = tileKey(k.col, k.row); this.keys.set(id, key); }
    return key;
  }

  private evict(wanted: ReadonlySet<string>, now: number): void {
    const idle = this.idle;
    for (const tile of this.tiles.values()) if (!wanted.has(tile.key)) idle.push(tile);
    if (idle.length === 0) return;
    if (idle.length > 1) idle.sort(byLastWanted);
    let over = this.tiles.size + this.loading.size - this.maxResident;
    for (const tile of idle) {
      if (over <= 0 && now - tile.lastWanted < this.idleMs) continue;
      release(tile);
      this.tiles.delete(tile.key);
      over -= 1;
    }
    idle.length = 0;
  }
}

/** A plate image as a texture that round-trips its sRGB values exactly (drawn with toneMapped off). */
export function plateTexture(bitmap: ImageBitmap): Texture {
  const texture = new Texture(bitmap);
  texture.colorSpace = SRGBColorSpace;
  // An ImageBitmap cannot be flipped on upload; the quad's UVs put row 0 at the top instead.
  texture.flipY = false;
  texture.generateMipmaps = true;
  texture.minFilter = LinearMipmapLinearFilter;
  texture.magFilter = LinearFilter;
  texture.wrapS = ClampToEdgeWrapping;
  texture.wrapT = ClampToEdgeWrapping;
  texture.needsUpdate = true;
  return texture;
}

function release(tile: StreamedTile): void {
  const image = tile.texture.image as ImageBitmap | undefined;
  tile.texture.dispose();
  image?.close?.();
}


