/**
 * The plate in the scene: camera-aligned quads far behind everything, drawn
 * first, with no depth and no tone mapping, so the photograph reaches the
 * screen with exactly the sRGB values the cook wrote.
 *
 * The overview covers the whole plate from the start; full-resolution tiles
 * are drawn over it where the view needs them (tileStreamer.ts). Each tile
 * quad covers exactly its pixel rectangle of the plate, so the overview and
 * the tiles line up to the pixel.
 */
import { BufferAttribute, BufferGeometry, Group, Mesh, MeshBasicMaterial, type Texture, type WebGLRenderer } from "three";
import type { Deck } from "../content/deck";
import { cameraBasis, type PlateCamera } from "./plateMath";
import { PLATE_DEPTH } from "./plateCamera";
import { density, viewRect, type View, type Viewport } from "./view";
import { fetchImageBitmap } from "./imageFetch";
import { needsFullResolution, tileKey, tilesInRect, type TileKey } from "./tiles";
import { plateTexture, TileStreamer } from "./tileStreamer";
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

export class PlateLayer {
  readonly group = new Group();
  private readonly overview: Mesh<BufferGeometry, MeshBasicMaterial>;
  private readonly streamer: TileStreamer;
  private readonly tiles = new Map<string, Mesh<BufferGeometry, MeshBasicMaterial>>();
  private readonly abort = new AbortController();
  private disposed = false;
  private overviewUploaded = false;
  private revision = -1;
  private visible: TileKey[] = [];
  private wanted: TileKey[] = [];
  /** Nothing to do until the view moves. */
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
   * uploaded ones. While the view stands still and every wanted tile is on
   * screen this does nothing at all. `revision` changes whenever the view does.
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
      const cam = this.deck.camera;
      const full = needsFullResolution(this.deck.plate, density(cam, vp, view));
      const rect = viewRect(view, vp);
      this.visible = full ? tilesInRect(this.deck.plate, cam, rect) : [];
      const shown = new Set(this.visible.map((k) => tileKey(k.col, k.row)));
      const ring = full ? tilesInRect(this.deck.plate, cam, rect, 1).filter((k) => !shown.has(tileKey(k.col, k.row))) : [];
      this.wanted = [...this.visible, ...ring];
      this.settled = false;
    }
    if (this.settled) return;
    this.streamer.update(this.wanted, now);
    const pending = this.streamer.nextUpload();
    if (pending) {
      gl.initTexture(pending.texture);
      (pending.texture.image as ImageBitmap | undefined)?.close?.();
      pending.uploaded = true;
      this.onChange();
    }
    this.syncMeshes();
    // Nothing uploaded and nothing loading right after asking for the wanted tiles: everything that can be shown is.
    this.settled = !pending && this.streamer.inFlightCount === 0;
  }

  /** Let every full-resolution tile go (the stage went off screen); the overview stays. */
  trim(): void {
    this.streamer.update([], Number.POSITIVE_INFINITY);
    this.visible = [];
    this.wanted = [];
    this.syncMeshes();
    // The next frame on screen asks for its tiles again.
    this.revision = -1;
    this.settled = false;
  }

  private syncMeshes(): void {
    const cam = this.deck.camera;
    const show = new Set<string>();
    for (const tile of this.streamer.drawable(this.visible)) {
      show.add(tile.key);
      if (this.tiles.has(tile.key)) continue;
      const mesh = new Mesh(plateQuad(cam, tile.rect.u0, tile.rect.u1, tile.rect.v0, tile.rect.v1), plateMaterial(tile.texture));
      mesh.renderOrder = RENDER_ORDER.plateTile;
      mesh.frustumCulled = false;
      mesh.layers.set(BACKDROP_LAYER);
      this.tiles.set(tile.key, mesh);
      this.group.add(mesh);
    }
    for (const [key, mesh] of this.tiles) {
      // A mesh whose texture the streamer released goes too.
      if (!show.has(key) && !this.streamer.isDrawable(key)) {
        this.group.remove(mesh);
        mesh.geometry.dispose();
        mesh.material.dispose();
        this.tiles.delete(key);
        continue;
      }
      mesh.visible = show.has(key);
    }
  }

  /** L0 tiles in GPU memory, and loads under way. */
  get resident(): number {
    return this.streamer.residentCount;
  }

  get inFlight(): number {
    return this.streamer.inFlightCount;
  }

  dispose(): void {
    this.disposed = true;
    this.abort.abort();
    this.streamer.dispose();
    for (const mesh of this.tiles.values()) { mesh.geometry.dispose(); mesh.material.dispose(); }
    this.tiles.clear();
    const map = this.overview.material.map;
    if (map) { (map.image as ImageBitmap | undefined)?.close?.(); map.dispose(); }
    this.overview.geometry.dispose();
    this.overview.material.dispose();
  }
}



