/**
 * Keeping a whiteboard in the editor and on the server the same.
 *
 * Two hands draw on one board: the person in the editor, and the assistant
 * through its `whiteboard` tool, which writes the scene on the server. Every
 * element carries a version (and a random nonce that settles a tie), so the
 * two never need a lock: per element, the newer one wins.
 *
 * What this class does:
 * - It remembers which version of each element the server last confirmed.
 *   An editor change that makes any element differ from that is unsaved; it
 *   is saved after a short pause (and at once when the window or the board
 *   goes away), so a stroke is not sent point by point.
 * - It uploads a new picture before the save that first names it.
 * - When the server answers a save with a merged scene (it held something
 *   newer, the assistant's work), or when the node changed and it was not this
 *   editor's save, it hands the server's elements to the editor, which keeps
 *   its own where they are newer or still being drawn (`applyRemote`).
 *
 * The editor package itself stays outside: the component wires `applyRemote`
 * and `addFiles` to it, and feeds every change in through `onChange`. That
 * keeps this logic testable without a canvas.
 */
import type { BoardAppState, BoardElement, BoardFileMeta, BoardScene, SceneRead, SceneWrite } from "./boardApi";

/** How long the editor has to be still before a change is saved. */
export const SAVE_DEBOUNCE_MS = 800;
/** After a failed save, when to try again (unless another change comes first). */
export const SAVE_RETRY_MS = 5_000;

export type SaveState = "idle" | "saving" | "saved" | "failed";

/** A picture as the editor holds it. */
export interface EditorFile {
  id: string;
  dataURL: string;
  mimeType: string;
  created: number;
}

/** What the editor reports with each change. */
export interface EditorSnapshot {
  elements: readonly BoardElement[];
  appState: { viewBackgroundColor?: string; gridModeEnabled?: boolean };
  files: Readonly<Record<string, EditorFile | undefined>>;
}

/** The server side: the board's routes, bound to one node. */
export interface BoardTransport {
  fetchScene: () => Promise<SceneRead>;
  putScene: (scene: BoardScene, init?: { leaving?: boolean }) => Promise<SceneWrite>;
  uploadFile: (file: { id: string; dataURL: string }) => Promise<{ id: string; mimeType: string }>;
  fetchFile: (fileId: string) => Promise<{ dataURL: string; mimeType: string }>;
}

/** The editor side. */
export interface BoardEditorPort {
  /**
   * Bring the server's elements into the editor without touching its undo
   * history, keeping the editor's own element wherever it is newer or being
   * drawn. `appState` is set only when the server's view settings changed.
   */
  applyRemote: (elements: readonly BoardElement[], appState: BoardAppState | null) => void;
  addFiles: (files: EditorFile[]) => void;
}

export interface BoardSyncOptions {
  transport: BoardTransport;
  editor: BoardEditorPort;
  /** The scene the editor was opened with. */
  initial: SceneRead;
  onState?: (state: SaveState, detail: string) => void;
  /** A server refusal turned into a sentence; "" when there is none. */
  describeError?: (error: unknown) => string;
}

interface Confirmed {
  version: number;
  versionNonce: number;
  element: BoardElement;
}

function randomNonce(): number {
  return Math.floor(Math.random() * 2 ** 31);
}

function isLiveImage(element: BoardElement): boolean {
  return element.type === "image" && !element.isDeleted && typeof element.fileId === "string" && element.fileId !== "";
}

export class BoardSync {
  private readonly transport: BoardTransport;
  private readonly editor: BoardEditorPort;
  private readonly onState: (state: SaveState, detail: string) => void;
  private readonly describeError: (error: unknown) => string;

  /** Per element id: what the server last confirmed. */
  private confirmed = new Map<string, Confirmed>();
  private confirmedAppState: BoardAppState;
  /** File ids the server has the bytes of, with their metadata. */
  private serverFiles = new Map<string, BoardFileMeta>();
  /** Pictures the server refused; not sent again while the board is open. */
  private refusedFiles = new Set<string>();
  /** Pictures being fetched for the editor, so one is not fetched twice. */
  private loadingFiles = new Set<string>();
  /** Every element id the editor has held: one that vanishes is sent as deleted. */
  private seenInEditor = new Set<string>();

  private latest: EditorSnapshot | null = null;
  private checked: { elements: readonly BoardElement[]; background?: string; grid?: boolean } | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private saving: Promise<void> | null = null;
  private again = false;

  /** The node's update times this editor's own saves produced. */
  private ownRevisions = new Set<number>();
  /** The newest revision of the node this editor has taken in. */
  private seenRevision: number;
  /** A revision reported while a save was under way: looked at once it is done. */
  private heldRevision: number | null = null;
  private disposed = false;

  constructor(options: BoardSyncOptions) {
    this.transport = options.transport;
    this.editor = options.editor;
    this.onState = options.onState ?? (() => undefined);
    this.describeError = options.describeError ?? (() => "");
    this.seenRevision = options.initial.updated_at;
    this.confirmedAppState = { ...options.initial.scene.appState };
    this.takeServerScene(options.initial.scene);
  }

  /** The editor changed (anything: a stroke, a selection, a scroll). */
  onChange(snapshot: EditorSnapshot): void {
    if (this.disposed) return;
    this.latest = snapshot;
    for (const element of snapshot.elements) this.seenInEditor.add(element.id);
    if (!this.changedSinceLastLook(snapshot)) return;
    if (this.isDirty(snapshot)) this.schedule(SAVE_DEBOUNCE_MS);
  }

  /** Save now what is unsaved: the window hides, the board closes. */
  flush(init?: { leaving?: boolean }): Promise<void> {
    this.clearTimer();
    if (this.saving) {
      this.again = true;
      return this.saving;
    }
    if (!this.latest || !this.isDirty(this.latest)) return Promise.resolve();
    this.saving = this.save(this.latest, init).finally(() => {
      this.saving = null;
      if (this.disposed) return;
      if (this.again) {
        this.again = false;
        if (this.latest && this.isDirty(this.latest)) this.schedule(0);
      }
      const held = this.heldRevision;
      this.heldRevision = null;
      if (held !== null) void this.onRevision(held);
    });
    return this.saving;
  }

  /**
   * The node changed on the server (the stage watches its update time). A
   * revision this editor wrote itself, or one already taken in, is ignored;
   * anyone else's is fetched and drawn in.
   */
  async onRevision(updatedAt: number): Promise<void> {
    if (this.disposed || this.isKnownRevision(updatedAt)) return;
    if (this.saving) {
      this.heldRevision = Math.max(this.heldRevision ?? 0, updatedAt);
      return;
    }
    let read: SceneRead;
    try {
      read = await this.transport.fetchScene();
    } catch {
      // The next report of the node tries again.
      return;
    }
    if (this.disposed || this.isKnownRevision(read.updated_at) || this.saving) return;
    this.seenRevision = Math.max(this.seenRevision, read.updated_at);
    this.applyServerScene(read.scene);
  }

  /** Stop: nothing is saved or drawn in after this (call `flush` first). */
  dispose(): void {
    this.disposed = true;
    this.clearTimer();
  }

  /* ---------------------------------------------------------------------- */

  private isKnownRevision(updatedAt: number): boolean {
    return this.ownRevisions.has(updatedAt) || updatedAt <= this.seenRevision;
  }

  private schedule(delay: number): void {
    this.clearTimer();
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.flush();
    }, delay);
  }

  private clearTimer(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  /** A cheap first test: the editor reports every pointer move. */
  private changedSinceLastLook(snapshot: EditorSnapshot): boolean {
    const previous = this.checked;
    const look = {
      elements: snapshot.elements,
      background: snapshot.appState.viewBackgroundColor,
      grid: snapshot.appState.gridModeEnabled,
    };
    this.checked = look;
    return (
      previous === null ||
      previous.elements !== look.elements ||
      previous.background !== look.background ||
      previous.grid !== look.grid
    );
  }

  private isDirty(snapshot: EditorSnapshot): boolean {
    if (this.vanished(snapshot).length > 0) return true;
    for (const element of snapshot.elements) {
      const known = this.confirmed.get(element.id);
      if (!known) {
        // A deleted element the server never had needs no save of its own.
        if (!element.isDeleted) return true;
        continue;
      }
      if (known.version !== element.version || known.versionNonce !== element.versionNonce) return true;
    }
    return (
      (snapshot.appState.viewBackgroundColor ?? undefined) !== (this.confirmedAppState.viewBackgroundColor ?? undefined) ||
      Boolean(snapshot.appState.gridModeEnabled) !== Boolean(this.confirmedAppState.gridModeEnabled)
    );
  }

  /**
   * Elements the server has and the editor held, but no longer lists (a scene
   * opened from a file replaces the whole list). Without a deletion of their
   * own the server would keep them and hand them back.
   */
  private vanished(snapshot: EditorSnapshot): Confirmed[] {
    const present = new Set(snapshot.elements.map((element) => element.id));
    const gone: Confirmed[] = [];
    for (const [id, known] of this.confirmed) {
      if (!present.has(id) && this.seenInEditor.has(id) && !known.element.isDeleted) gone.push(known);
    }
    return gone;
  }

  private async save(snapshot: EditorSnapshot, init?: { leaving?: boolean }): Promise<void> {
    this.onState("saving", "");
    // A picture the server refused: the board is saved without it, and the
    // state says not everything was.
    let refused: { detail: string } | null = null;
    try {
      // Pictures first: the scene that names a picture must find it there.
      for (const element of snapshot.elements) {
        if (!isLiveImage(element)) continue;
        const fileId = element.fileId as string;
        if (this.serverFiles.has(fileId) || this.refusedFiles.has(fileId)) continue;
        const file = snapshot.files[fileId];
        if (!file) continue; // still being read by the editor; the next save takes it
        try {
          const kept = await this.transport.uploadFile({ id: fileId, dataURL: file.dataURL });
          this.serverFiles.set(fileId, { id: fileId, mimeType: kept.mimeType || file.mimeType, created: file.created });
        } catch (error) {
          this.refusedFiles.add(fileId);
          refused = { detail: this.describeError(error) };
        }
      }

      const now = Date.now();
      const tombstones = this.vanished(snapshot).map(({ element }) => ({
        ...element,
        isDeleted: true,
        version: element.version + 1,
        versionNonce: randomNonce(),
        updated: now,
      }));
      const elements = [...snapshot.elements, ...tombstones];
      const files: Record<string, BoardFileMeta> = {};
      for (const element of elements) {
        if (!isLiveImage(element)) continue;
        const meta = this.serverFiles.get(element.fileId as string);
        if (meta) files[meta.id] = meta;
      }
      const appState: BoardAppState = {
        viewBackgroundColor: snapshot.appState.viewBackgroundColor,
        gridModeEnabled: Boolean(snapshot.appState.gridModeEnabled),
      };
      const answer = await this.transport.putScene({ format: "scene", elements, appState, files }, init);

      for (const element of elements) this.confirm(element);
      this.confirmedAppState = appState;
      this.ownRevisions.add(answer.updated_at);
      this.seenRevision = Math.max(this.seenRevision, answer.updated_at);
      if (answer.merged && answer.scene && !this.disposed) this.applyServerScene(answer.scene);
      if (refused) this.onState("failed", refused.detail);
      else this.onState("saved", "");
    } catch (error) {
      this.onState("failed", this.describeError(error));
      // Try again later; a new change reschedules it sooner.
      if (!this.disposed) this.schedule(SAVE_RETRY_MS);
    }
  }

  private confirm(element: BoardElement): void {
    this.confirmed.set(element.id, { version: element.version, versionNonce: element.versionNonce, element });
  }

  /** Remember what the server holds, before or without drawing it in. */
  private takeServerScene(scene: BoardScene): void {
    this.confirmed = new Map();
    for (const element of scene.elements) this.confirm(element);
    for (const [id, meta] of Object.entries(scene.files)) this.serverFiles.set(id, { ...meta, id });
  }

  /** Draw the server's scene into the editor and remember it as confirmed. */
  private applyServerScene(scene: BoardScene): void {
    const viewChanged =
      (scene.appState.viewBackgroundColor ?? undefined) !== (this.confirmedAppState.viewBackgroundColor ?? undefined) ||
      Boolean(scene.appState.gridModeEnabled) !== Boolean(this.confirmedAppState.gridModeEnabled);
    this.takeServerScene(scene);
    this.confirmedAppState = { ...scene.appState };
    this.editor.applyRemote(scene.elements, viewChanged ? scene.appState : null);
    void this.loadMissingFiles(scene.elements);
  }

  /** Fetch the pictures the editor does not hold yet. */
  async loadMissingFiles(elements: readonly BoardElement[]): Promise<void> {
    const held = this.latest?.files ?? {};
    const wanted = new Set<string>();
    for (const element of elements) {
      if (!isLiveImage(element)) continue;
      const fileId = element.fileId as string;
      if (held[fileId] || this.loadingFiles.has(fileId)) continue;
      wanted.add(fileId);
    }
    if (wanted.size === 0) return;
    const loaded: EditorFile[] = [];
    await Promise.all(
      [...wanted].map(async (fileId) => {
        this.loadingFiles.add(fileId);
        try {
          const file = await this.transport.fetchFile(fileId);
          const meta = this.serverFiles.get(fileId);
          loaded.push({ id: fileId, dataURL: file.dataURL, mimeType: meta?.mimeType ?? file.mimeType, created: meta?.created ?? Date.now() });
          if (!meta) this.serverFiles.set(fileId, { id: fileId, mimeType: file.mimeType, created: Date.now() });
        } catch {
          // The editor shows the picture as missing; the next revision tries again.
        } finally {
          this.loadingFiles.delete(fileId);
        }
      }),
    );
    if (loaded.length > 0 && !this.disposed) this.editor.addFiles(loaded);
  }
}
