/**
 * Streams plate tiles (L0 and the mips) in and out of GPU memory.
 *
 * Each frame the plate layer says which tiles the view wants, by priority:
 * first what it shows now (`need`), then a prefetch ring; it also names the
 * resident tiles it keeps on screen as a fallback while a finer or coarser
 * level loads (`keep`). The streamer fetches at most a few at once, aborts
 * what is no longer wanted, hands decoded tiles over for upload one per frame
 * (a 2048² upload with mipmaps is a few milliseconds; several in one frame
 * would hitch a pan), and keeps GPU memory bounded by one budget shared by
 * every level: at most `maxResident` tiles resident or loading. To make room
 * a needed tile pushes out unwanted tiles (the least recently seen first) and
 * then prefetched ones; a prefetched tile only takes free room or an unwanted
 * tile's place. What the view shows now and its fallback always fit, even
 * past the budget on a huge viewport. An unwanted tile is let go after
 * `idleMs` even under budget.
 */
import { LinearFilter, LinearMipmapLinearFilter, SRGBColorSpace, Texture, ClampToEdgeWrapping } from "three";
import type { PlateImages } from "../content/deck";
import type { PlateCamera } from "./plateMath";
import { tileKey, tileRect, type TileKey, type TileRect } from "./tiles";

export interface StreamedTile {
  key: string;
  /** Index into PlateImages.levels. */
  level: number;
  col: number;
  row: number;
  rect: TileRect;
  texture: Texture;
  /** False until the texture has been uploaded (the layer draws only uploaded tiles). */
  uploaded: boolean;
  lastWanted: number;
  /** Its place in the last update's wanted list (0 = most wanted); Infinity when nothing asked for it. */
  rank: number;
}

export type BitmapLoader = (url: string, signal: AbortSignal) => Promise<ImageBitmap>;

export interface StreamerOptions {
  load: BitmapLoader;
  /** Tiles resident or loading, all levels together. */
  maxResident?: number;
  maxInFlight?: number;
  idleMs?: number;
  /** A failed tile is retried after this long. */
  retryMs?: number;
}

/** 14 tiles of 2048² with mipmaps: about 300 MB of GPU memory at most. */
export const DEFAULT_MAX_RESIDENT = 14;

const NO_KEEP: ReadonlySet<string> = new Set();

export class TileStreamer {
  private readonly tiles = new Map<string, StreamedTile>();
  private readonly loading = new Map<string, AbortController>();
  private readonly failedUntil = new Map<string, number>();
  private readonly maxResident: number;
  private readonly maxInFlight: number;
  private readonly idleMs: number;
  private readonly retryMs: number;
  private disposed = false;
  // Scratch state reused by every update: the per-frame path allocates nothing while the wanted tiles stay the same.
  private readonly ranks = new Map<string, number>();
  private readonly keys = new Map<number, string>();
  /** Bumped whenever a tile arrives or goes, so the layer redraws only then. */
  version = 0;

  constructor(private readonly plate: PlateImages, private readonly cam: PlateCamera, private readonly opts: StreamerOptions) {
    this.maxResident = opts.maxResident ?? DEFAULT_MAX_RESIDENT;
    this.maxInFlight = opts.maxInFlight ?? 3;
    this.idleMs = opts.idleMs ?? 20_000;
    this.retryMs = opts.retryMs ?? 8_000;
  }

  /**
   * Tell the streamer what the view wants. `wanted` is ordered by priority;
   * its first `need` entries are on screen now (by default all of them), the
   * rest is prefetch. `keep` names resident tiles that must stay (never loaded).
   */
  update(wanted: readonly TileKey[], now: number, need = wanted.length, keep: ReadonlySet<string> = NO_KEEP): void {
    if (this.disposed) return;
    const ranks = this.ranks;
    ranks.clear();
    for (const tile of this.tiles.values()) tile.rank = Number.POSITIVE_INFINITY;
    for (let i = 0; i < wanted.length; i++) {
      const key = this.keyOf(wanted[i]);
      if (ranks.has(key)) continue;
      ranks.set(key, i);
      const tile = this.tiles.get(key);
      if (tile) { tile.lastWanted = now; tile.rank = i; }
    }
    let kept = 0;
    for (const key of keep) {
      const tile = this.tiles.get(key);
      if (tile) { tile.lastWanted = now; kept += 1; }
    }
    for (const [key, ctrl] of this.loading) {
      if (!ranks.has(key)) { ctrl.abort(); this.loading.delete(key); }
    }
    for (const tile of this.tiles.values()) {
      if (tile.rank === Number.POSITIVE_INFINITY && !keep.has(tile.key) && now - tile.lastWanted >= this.idleMs) this.release(tile);
    }
    // What is on screen now and its fallback always fit; the budget bounds everything else.
    const budget = Math.max(this.maxResident, Math.min(need, wanted.length) + kept);
    while (this.tiles.size + this.loading.size > budget) {
      const victim = this.victim(Number.POSITIVE_INFINITY, keep);
      if (!victim) break;
      this.release(victim);
    }
    for (let i = 0; i < wanted.length; i++) {
      const k = wanted[i];
      const key = this.keyOf(k);
      if (ranks.get(key) !== i || this.tiles.has(key) || this.loading.has(key) || (this.failedUntil.get(key) ?? 0) > now) continue;
      const needed = i < need;
      // A needed tile takes the slot of a prefetch still on its way.
      if (this.loading.size >= this.maxInFlight && !(needed && this.abortPrefetch(need))) break;
      if (this.tiles.size + this.loading.size >= budget) {
        const victim = this.victim(needed ? need : Number.POSITIVE_INFINITY, keep);
        if (!victim) {
          if (needed && this.abortPrefetch(need)) { this.start(k, key); continue; }
          break;
        }
        this.release(victim);
      }
      this.start(k, key);
    }
  }

  /** A decoded tile still waiting for its upload, the most wanted first; null when none. */
  nextUpload(): StreamedTile | null {
    let best: StreamedTile | null = null;
    for (const tile of this.tiles.values()) {
      if (tile.uploaded) continue;
      if (!best || tile.rank < best.rank || (tile.rank === best.rank && tile.lastWanted > best.lastWanted)) best = tile;
    }
    return best;
  }

  /** The resident tile at (level, col, row), uploaded or not. */
  tileAt(level: number, col: number, row: number): StreamedTile | undefined {
    return this.tiles.get(this.keyAt(level, col, row));
  }

  /** The map key of a tile, as `keep` expects it. */
  keyFor(level: number, col: number, row: number): string {
    return this.keyAt(level, col, row);
  }

  /** Uploaded tiles among `keys`. */
  drawable(keys: readonly TileKey[]): StreamedTile[] {
    const out: StreamedTile[] = [];
    for (const k of keys) {
      const tile = this.tiles.get(this.keyOf(k));
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
    const level = k.level ?? 0;
    const url = this.plate.levels[level].tileUrl(k.col, k.row);
    this.opts.load(url, ctrl.signal).then((bitmap) => {
      if (this.loading.get(key) !== ctrl || this.disposed) { bitmap.close(); return; }
      this.loading.delete(key);
      this.tiles.set(key, {
        key, level, col: k.col, row: k.row, rect: tileRect(this.plate, this.cam, k.col, k.row, level),
        texture: plateTexture(bitmap), uploaded: false, lastWanted: performance.now(), rank: this.ranks.get(key) ?? Number.POSITIVE_INFINITY,
      });
      this.version += 1;
    }, (error: unknown) => {
      if (this.loading.get(key) !== ctrl) return;
      this.loading.delete(key);
      if (ctrl.signal.aborted) return;
      this.failedUntil.set(key, performance.now() + this.retryMs);
      console.warn("Verse plate tile failed", url, error);
    });
  }

  /**
   * The tile to let go for room: the unwanted one seen longest ago, else
   * (only for a tile ranked below `prefetchFrom`, i.e. a needed one) the
   * least wanted prefetched tile. Kept tiles never go. Null when none may.
   */
  private victim(prefetchFrom: number, keep: ReadonlySet<string>): StreamedTile | null {
    let unwanted: StreamedTile | null = null;
    let prefetched: StreamedTile | null = null;
    for (const tile of this.tiles.values()) {
      if (keep.has(tile.key)) continue;
      if (tile.rank === Number.POSITIVE_INFINITY) {
        if (!unwanted || tile.lastWanted < unwanted.lastWanted) unwanted = tile;
      } else if (tile.rank >= prefetchFrom && (!prefetched || tile.rank > prefetched.rank)) {
        prefetched = tile;
      }
    }
    return unwanted ?? prefetched;
  }

  /** Abort the least wanted prefetch load (ranked at or after `need`); false when there is none. */
  private abortPrefetch(need: number): boolean {
    let worstKey: string | null = null;
    let worstRank = need - 1;
    for (const key of this.loading.keys()) {
      const rank = this.ranks.get(key) ?? Number.POSITIVE_INFINITY;
      if (rank > worstRank) { worstRank = rank; worstKey = key; }
    }
    if (worstKey === null) return false;
    this.loading.get(worstKey)?.abort();
    this.loading.delete(worstKey);
    return true;
  }

  private release(tile: StreamedTile): void {
    release(tile);
    this.tiles.delete(tile.key);
    this.version += 1;
  }

  /** The tile's map key, built once per tile instead of once per frame. */
  private keyOf(k: TileKey): string {
    return this.keyAt(k.level ?? 0, k.col, k.row);
  }

  private keyAt(level: number, col: number, row: number): string {
    const id = (level * 4096 + col) * 4096 + row;
    let key = this.keys.get(id);
    if (key === undefined) { key = tileKey(col, row, level); this.keys.set(id, key); }
    return key;
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
