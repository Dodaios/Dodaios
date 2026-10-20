/**
 * The plate in the scene: camera-aligned quads far behind everything, drawn
 * first, with no depth and no tone mapping, so the photograph reaches the
 * screen with exactly the sRGB values the cook wrote.
 *
 * The overview covers the whole plate from the start. Over it the layer draws
 * the tiles of the level the view's density asks for (tiles.ts,
 * plateLevelFor): the coarsest that is still sharp, so a close follow camera
 * streams L0 and a pulled-back view a mip or nothing at all. While that level
 * is still loading, whatever other level already sits in GPU memory for the
 * view stays drawn beneath (finer levels on top), so crossing a level never
 * shows a hole or a flash; once the wanted level covers the view it is drawn
 * alone. Each tile quad covers exactly its pixel rectangle of the plate, so
 * the overview, the mips and L0 line up to the pixel.
 *
 * The per-frame path allocates nothing while the view stays on the same tiles.
 */
import { BufferAttribute, BufferGeometry, Group, Mesh, MeshBasicMaterial, type Texture, type WebGLRenderer } from "three";
import type { Deck } from "../content/deck";
import { cameraBasis, type PlateCamera } from "./plateMath";
import { PLATE_DEPTH } from "./plateCamera";
import { density, type View, type Viewport } from "./view";
import { fetchImageBitmap } from "./imageFetch";
import { inRange, OVERVIEW_LEVEL, plateLevelFor, sameRange, tileRange, tilesInRect, type PlateRect, type TileKey, type TileRange } from "./tiles";
import { plateTexture, TileStreamer, type StreamedTile } from "./tileStreamer";
import { BACKDROP_LAYER, RENDER_ORDER } from "./renderOrder";

/** A quad over the plate rectangle [u0, u1] × [v0, v1], row 0 of its texture at the top. */
export function plateQuad(cam: PlateCamera, u0: number, u1: number, v0: number, v1: number): BufferGeometry {
  const { right, up, dir } = cameraBasis(cam.pitchDeg);
  const [cx, cy, cz] = cam.center;
  const at = (u: number, v: number) => [0, 1, 2].map((k) => [cx, cy, cz][k] + right[k] * u + up[k] * v + dir[k] * PLATE_DEPTH);
  const g = new BufferGeometry();
  g.setAttribute("position", new BufferAttribute(new Float32Array([...at(u0, v1), ...at(u1, v1), ...at(u1, v0), ...at(u0, v0)]), 3));
  g.setAttribute("uv", new BufferAttribute(new Float32Array([0, 0, 1, 0, 1, 1, 0, 1]), 2));
  g.setIndex([0, 3, 2, 0, 2, 1]);
  return g;
}

function plateMaterial(map: Texture | null): MeshBasicMaterial {
  return new MeshBasicMaterial({ map, toneMapped: false, depthTest: false, depthWrite: false, fog: false });
}

interface TileMesh {
  mesh: Mesh<BufferGeometry, MeshBasicMaterial>;
  tile: StreamedTile;
  /** The redraw that last showed it. */
  stamp: number;
}

const emptyRange = (level: number): TileRange => ({ level, c0: 0, c1: -2, r0: 0, r1: -2 });

export class PlateLayer {
  readonly group = new Group();
  private readonly overview: Mesh<BufferGeometry, MeshBasicMaterial>;
  private readonly streamer: TileStreamer;
  private readonly meshes = new Map<string, TileMesh>();
  private readonly abort = new AbortController();
  private disposed = false;
  private overviewUploaded = false;
  private revision = -1;
  /** The level the view streams: OVERVIEW_LEVEL or an index into the plate's levels. */
  private target = OVERVIEW_LEVEL;
  /** Per level, the tiles the view touches; and the target level's prefetch ring. */
  private readonly ranges: TileRange[];
  private readonly levelNames: readonly string[];
  private readonly ring = emptyRange(0);
  private readonly scratch = emptyRange(0);
  private readonly rect: PlateRect = { u0: 0, u1: 0, v0: 0, v1: 0 };
  /** The target level's tiles: on screen first (`needCount`), then the ring. */
  private wanted: TileKey[] = [];
  private needCount = 0;
  /** Tiles of other levels drawn while the target level loads. */
  private readonly keep = new Set<string>();
  private dirty = true;
  private drawnVersion = -1;
  private stamp = 0;
  /** Nothing to do until the view reaches other tiles. */
  private settled = false;
  /** True once the overview is on screen. */
  ready = false;
  /** Called when something new can be drawn (a tile arrived). */
  onChange: () => void = () => undefined;

  constructor(private readonly deck: Deck) {
    const cam = deck.camera;
    this.group.name = "plate";
    this.overview = new Mesh(plateQuad(cam, -cam.frameW / 2, cam.frameW / 2, -cam.frameH / 2, cam.frameH / 2), plateMaterial(null));
    this.overview.renderOrder = RENDER_ORDER.plate;
    this.overview.frustumCulled = false;
    this.overview.visible = false;
    this.overview.layers.set(BACKDROP_LAYER);
    this.group.add(this.overview);
    this.ranges = deck.plate.levels.map((_, i) => emptyRange(i));
    this.levelNames = deck.plate.levels.map((l) => (l.divisor === 1 ? "L0" : `M${l.divisor}`));
    this.streamer = new TileStreamer(deck.plate, cam, { load: fetchImageBitmap });
  }

  /** Fetch and show the overview; rejects when the plate cannot be loaded. */
  async load(): Promise<void> {
    const bitmap = await fetchImageBitmap(this.deck.plate.overview.url, this.abort.signal);
    if (this.disposed) { bitmap.close(); return; }
    this.overview.material.map = plateTexture(bitmap);
    this.overview.material.needsUpdate = true;
    this.overview.visible = true;
    this.ready = true;
    this.onChange();
  }

  /**
   * Per frame: stream the tiles the view needs, upload at most one, show the
   * uploaded ones. While the view stays on the same tiles and every wanted
   * tile is on screen this does nothing at all. `revision` changes whenever
   * the view does.
   */
  update(view: View, vp: Viewport, revision: number, gl: WebGLRenderer, now: number): void {
    if (this.disposed || !this.ready) return;
    const map = this.overview.material.map;
    if (map && !this.overviewUploaded) {
      gl.initTexture(map);
      // The GPU has its copy; the decoded pixels on the CPU side can go.
      (map.image as ImageBitmap | undefined)?.close?.();
      this.overviewUploaded = true;
    }
    if (revision !== this.revision) {
      this.revision = revision;
      if (this.measure(view, vp)) {
        this.dirty = true;
        this.settled = false;
      }
    }
    if (this.settled) return;
    if (this.dirty || this.streamer.version !== this.drawnVersion) this.redraw();
    this.streamer.update(this.wanted, now, this.needCount, this.keep);
    const pending = this.streamer.nextUpload();
    if (pending) {
      gl.initTexture(pending.texture);
      (pending.texture.image as ImageBitmap | undefined)?.close?.();
      pending.uploaded = true;
      this.onChange();
    }
    if (pending || this.streamer.version !== this.drawnVersion) this.redraw();
    // Nothing uploaded and nothing loading right after asking for the wanted tiles: everything that can be shown is.
    this.settled = !pending && this.streamer.inFlightCount === 0;
  }

  /** Let every tile go (the stage went off screen); the overview stays. */
  trim(): void {
    this.streamer.update([], Number.POSITIVE_INFINITY);
    this.wanted = [];
    this.needCount = 0;
    this.keep.clear();
    this.target = OVERVIEW_LEVEL;
    for (let i = 0; i < this.ranges.length; i++) this.ranges[i] = emptyRange(i);
    Object.assign(this.ring, emptyRange(0));
    this.redraw();
    // The next frame on screen asks for its tiles again.
    this.revision = -1;
    this.settled = false;
  }

  /**
   * Which level and which tiles the view needs now. True when that changed
   * (the wanted list is rebuilt then); allocation-free otherwise.
   */
  private measure(view: View, vp: Viewport): boolean {
    const plate = this.deck.plate;
    const cam = this.deck.camera;
    const target = plateLevelFor(plate, density(cam, vp, view));
    const rect = this.rect;
    const halfW = vp.width / (2 * view.scale);
    const halfH = vp.height / (2 * view.scale);
    rect.u0 = view.cu - halfW;
    rect.u1 = view.cu + halfW;
    rect.v0 = view.cv - halfH;
    rect.v1 = view.cv + halfH;
    let changed = target !== this.target;
    this.target = target;
    for (let i = 0; i < this.ranges.length; i++) {
      tileRange(plate, cam, rect, 0, i, this.scratch);
      if (!sameRange(this.scratch, this.ranges[i])) { Object.assign(this.ranges[i], this.scratch); changed = true; }
    }
    if (target !== OVERVIEW_LEVEL) {
      tileRange(plate, cam, rect, 1, target, this.scratch);
      if (!sameRange(this.scratch, this.ring)) { Object.assign(this.ring, this.scratch); changed = true; }
    }
    if (!changed) return false;
    if (target === OVERVIEW_LEVEL) {
      this.wanted = [];
      this.needCount = 0;
    } else {
      const shown = this.ranges[target];
      const need = tilesInRect(plate, cam, rect, 0, target);
      const ring = tilesInRect(plate, cam, rect, 1, target).filter((k) => !inRange(shown, k.col, k.row));
      this.wanted = need.concat(ring);
      this.needCount = need.length;
    }
    return true;
  }

  /**
   * Show the target level's uploaded tiles in view; while it does not cover
   * the view yet, also every other level's uploaded tiles in view (kept, so
   * the streamer does not let them go). Hide the rest, drop meshes whose tile
   * the streamer let go.
   */
  private redraw(): void {
    this.dirty = false;
    this.drawnVersion = this.streamer.version;
    const stamp = ++this.stamp;
    this.keep.clear();
    if (this.target !== OVERVIEW_LEVEL && !this.showLevel(this.target, stamp, false)) {
      for (let i = 0; i < this.ranges.length; i++) if (i !== this.target) this.showLevel(i, stamp, true);
    }
    for (const [key, entry] of this.meshes) {
      const tile = entry.tile;
      if (this.streamer.tileAt(tile.level, tile.col, tile.row) !== tile) {
        this.group.remove(entry.mesh);
        entry.mesh.geometry.dispose();
        entry.mesh.material.dispose();
        this.meshes.delete(key);
        continue;
      }
      entry.mesh.visible = entry.stamp === stamp;
    }
  }

  /** Show one level's uploaded tiles in view; true when they cover the whole view. */
  private showLevel(level: number, stamp: number, keep: boolean): boolean {
    const r = this.ranges[level];
    let complete = true;
    for (let row = r.r0; row <= r.r1; row++) {
      for (let col = r.c0; col <= r.c1; col++) {
        const tile = this.streamer.tileAt(level, col, row);
        if (!tile?.uploaded) { complete = false; continue; }
        this.show(tile, stamp);
        if (keep) this.keep.add(tile.key);
      }
    }
    return complete;
  }

  private show(tile: StreamedTile, stamp: number): void {
    let entry = this.meshes.get(tile.key);
    if (entry && entry.tile !== tile) {
      this.group.remove(entry.mesh);
      entry.mesh.geometry.dispose();
      entry.mesh.material.dispose();
      entry = undefined;
    }
    if (!entry) {
      const cam = this.deck.camera;
      const mesh = new Mesh(plateQuad(cam, tile.rect.u0, tile.rect.u1, tile.rect.v0, tile.rect.v1), plateMaterial(tile.texture));
      // Finer levels draw over coarser ones; L0 (level 0) last.
      mesh.renderOrder = RENDER_ORDER.plateTile + (this.ranges.length - 1 - tile.level);
      mesh.frustumCulled = false;
      mesh.layers.set(BACKDROP_LAYER);
      entry = { mesh, tile, stamp };
      this.meshes.set(tile.key, entry);
      this.group.add(mesh);
    }
    entry.stamp = stamp;
  }

  /** Tiles (all levels) in GPU memory, and loads under way. */
  get resident(): number {
    return this.streamer.residentCount;
  }

  get inFlight(): number {
    return this.streamer.inFlightCount;
  }

  /** The level the view streams: OVERVIEW_LEVEL (−1) or an index into the plate's levels (0 = L0). */
  get level(): number {
    return this.target;
  }

  /** The same as a name for the stats readout: "overview", "M4", "M2" or "L0". */
  get levelName(): string {
    return this.target === OVERVIEW_LEVEL ? "overview" : this.levelNames[this.target];
  }

  dispose(): void {
    this.disposed = true;
    this.abort.abort();
    this.streamer.dispose();
    for (const entry of this.meshes.values()) { entry.mesh.geometry.dispose(); entry.mesh.material.dispose(); }
    this.meshes.clear();
    const map = this.overview.material.map;
    if (map) { (map.image as ImageBitmap | undefined)?.close?.(); map.dispose(); }
    this.overview.geometry.dispose();
    this.overview.material.dispose();
  }
}
