/**
 * The whiteboard's sync with the server, without the editor.
 *
 * Contracts worth pinning:
 * - a change is saved once the editor has been still for a moment, as one
 *   save, and not again while nothing changed (a selection or a scroll is no
 *   change); a flush saves at once,
 * - a new picture is uploaded before the save that names it, once,
 * - a merged answer (the server held something newer) is drawn into the
 *   editor, and what it brought is not saved back,
 * - a revision of the node is fetched and drawn in, unless this editor's own
 *   save made it; one reported during a save waits for the save,
 * - an element the editor dropped without deleting it goes out as deleted.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BoardElement, BoardScene, SceneRead, SceneWrite } from "./boardApi";
import { BoardSync, SAVE_DEBOUNCE_MS, type BoardTransport, type EditorSnapshot } from "./boardSync";

function el(id: string, version = 1, over: Partial<BoardElement> = {}): BoardElement {
  return { id, type: "rectangle", version, versionNonce: version * 10, isDeleted: false, ...over };
}

function scene(elements: BoardElement[], over: Partial<BoardScene> = {}): BoardScene {
  return { format: "scene", elements, appState: { viewBackgroundColor: "#ffffff", gridModeEnabled: false }, files: {}, ...over };
}

function read(elements: BoardElement[], updatedAt = 100): SceneRead {
  return { version: 1, updated_at: updatedAt, scene: scene(elements) };
}

function snap(elements: BoardElement[], files: EditorSnapshot["files"] = {}): EditorSnapshot {
  return { elements, appState: { viewBackgroundColor: "#ffffff", gridModeEnabled: false }, files };
}

function setup(initial: SceneRead, answers: Partial<{ put: (scene: BoardScene) => SceneWrite; fetch: () => SceneRead }> = {}) {
  let revision = initial.updated_at;
  const transport = {
    fetchScene: vi.fn(async () => answers.fetch?.() ?? initial),
    putScene: vi.fn(
      async (sent: BoardScene, _init?: { leaving?: boolean }) =>
        answers.put?.(sent) ?? { version: 2, updated_at: ++revision, merged: false },
    ),
    uploadFile: vi.fn(async (file: { id: string; dataURL: string }) => ({ id: file.id, mimeType: "image/png" })),
    fetchFile: vi.fn(async (_id: string) => ({ dataURL: "data:image/png;base64,AAAA", mimeType: "image/png" })),
  } satisfies BoardTransport;
  const editor = { applyRemote: vi.fn(), addFiles: vi.fn() };
  const states: string[] = [];
  const sync = new BoardSync({ transport, editor, initial, onState: (state) => states.push(state) });
  return { sync, transport, editor, states };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("BoardSync", () => {
  it("saves a change once the editor is still, and nothing for a mere selection", async () => {
    const { sync, transport, states } = setup(read([el("a")]));

    sync.onChange(snap([el("a")]));
    await vi.advanceTimersByTimeAsync(SAVE_DEBOUNCE_MS * 2);
    expect(transport.putScene).not.toHaveBeenCalled();

    sync.onChange(snap([el("a", 2)]));
    await vi.advanceTimersByTimeAsync(SAVE_DEBOUNCE_MS / 2);
    sync.onChange(snap([el("a", 3)]));
    await vi.advanceTimersByTimeAsync(SAVE_DEBOUNCE_MS / 2);
    expect(transport.putScene).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(SAVE_DEBOUNCE_MS);
    expect(transport.putScene).toHaveBeenCalledTimes(1);
    const sent = transport.putScene.mock.calls[0][0];
    expect(sent.format).toBe("scene");
    expect(sent.elements.map((e) => [e.id, e.version])).toEqual([["a", 3]]);
    expect(sent.appState).toEqual({ viewBackgroundColor: "#ffffff", gridModeEnabled: false });
    expect(states).toEqual(["saving", "saved"]);

    // The same state again is no change.
    sync.onChange(snap([el("a", 3)]));
    await vi.advanceTimersByTimeAsync(SAVE_DEBOUNCE_MS * 2);
    expect(transport.putScene).toHaveBeenCalledTimes(1);
  });

  it("saves at once on flush, and says so when leaving", async () => {
    const { sync, transport } = setup(read([]));
    sync.onChange(snap([el("n")]));
    await sync.flush({ leaving: true });
    expect(transport.putScene).toHaveBeenCalledTimes(1);
    expect(transport.putScene.mock.calls[0][1]).toEqual({ leaving: true });
    // Nothing left to save: the pending timer is gone too.
    await vi.advanceTimersByTimeAsync(SAVE_DEBOUNCE_MS * 2);
    expect(transport.putScene).toHaveBeenCalledTimes(1);
  });

  it("saves the background and the grid", async () => {
    const { sync, transport } = setup(read([el("a")]));
    sync.onChange({ elements: [el("a")], appState: { viewBackgroundColor: "#ffc9c9", gridModeEnabled: true }, files: {} });
    await vi.advanceTimersByTimeAsync(SAVE_DEBOUNCE_MS);
    expect(transport.putScene.mock.calls[0][0].appState).toEqual({ viewBackgroundColor: "#ffc9c9", gridModeEnabled: true });
  });

  it("uploads a new picture before the save that names it, and only once", async () => {
    const { sync, transport } = setup(read([]));
    const order: string[] = [];
    transport.uploadFile.mockImplementation(async (file) => {
      order.push(`upload:${file.id}`);
      return { id: file.id, mimeType: "image/png" };
    });
    transport.putScene.mockImplementation(async () => {
      order.push("save");
      return { version: 2, updated_at: 101, merged: false };
    });
    const picture = { id: "f1", dataURL: "data:image/png;base64,AAAA", mimeType: "image/png", created: 5 };
    sync.onChange(snap([el("img", 1, { type: "image", fileId: "f1" })], { f1: picture }));
    await sync.flush();
    expect(order).toEqual(["upload:f1", "save"]);
    expect(transport.uploadFile).toHaveBeenCalledWith({ id: "f1", dataURL: picture.dataURL });
    expect(transport.putScene.mock.calls[0][0].files).toEqual({ f1: { id: "f1", mimeType: "image/png", created: 5 } });

    // Moved: saved again, not uploaded again.
    sync.onChange(snap([el("img", 2, { type: "image", fileId: "f1" })], { f1: picture }));
    await sync.flush();
    expect(transport.uploadFile).toHaveBeenCalledTimes(1);
    expect(transport.putScene).toHaveBeenCalledTimes(2);
  });

  it("saves the board even when a picture is refused, and says it was not all saved", async () => {
    const { sync, transport, states } = setup(read([]));
    transport.uploadFile.mockRejectedValueOnce(new Error("too big"));
    const picture = { id: "big", dataURL: "data:image/png;base64,AAAA", mimeType: "image/png", created: 1 };
    sync.onChange(snap([el("img", 1, { type: "image", fileId: "big" }), el("b")], { big: picture }));
    await sync.flush();
    expect(transport.putScene).toHaveBeenCalledTimes(1);
    expect(transport.putScene.mock.calls[0][0].files).toEqual({});
    expect(states.at(-1)).toBe("failed");
  });

  it("draws a merged answer into the editor and does not save it back", async () => {
    const theirs = el("t", 1);
    const { sync, transport, editor } = setup(read([el("a")]), {
      put: (sent) => ({ version: 3, updated_at: 102, merged: true, scene: scene([...sent.elements, theirs]) }),
    });
    sync.onChange(snap([el("a", 2)]));
    await sync.flush();
    expect(editor.applyRemote).toHaveBeenCalledTimes(1);
    expect(editor.applyRemote.mock.calls[0][0].map((e: BoardElement) => e.id)).toEqual(["a", "t"]);
    // The view settings did not change: they are left alone.
    expect(editor.applyRemote.mock.calls[0][1]).toBeNull();

    // The editor now reports the merged scene: nothing new to save.
    sync.onChange(snap([el("a", 2), theirs]));
    await vi.advanceTimersByTimeAsync(SAVE_DEBOUNCE_MS * 2);
    expect(transport.putScene).toHaveBeenCalledTimes(1);
  });

  it("fetches someone else's revision and draws it in; ignores its own", async () => {
    const assistant = read([el("a"), el("drawn")], 200);
    const { sync, transport, editor } = setup(read([el("a")], 100), { fetch: () => assistant });
    sync.onChange(snap([el("a")]));

    // The revision the board was opened at, and an older one, are known.
    await sync.onRevision(100);
    await sync.onRevision(90);
    expect(transport.fetchScene).not.toHaveBeenCalled();

    // Its own save's revision is not drawn in again.
    sync.onChange(snap([el("a", 2)]));
    await sync.flush();
    const own = (await transport.putScene.mock.results[0].value) as SceneWrite;
    await sync.onRevision(own.updated_at);
    expect(transport.fetchScene).not.toHaveBeenCalled();

    await sync.onRevision(200);
    expect(transport.fetchScene).toHaveBeenCalledTimes(1);
    expect(editor.applyRemote).toHaveBeenCalledTimes(1);
    expect(editor.applyRemote.mock.calls[0][0].map((e: BoardElement) => e.id)).toEqual(["a", "drawn"]);
    // Taken in once: the same revision again is no news.
    await sync.onRevision(200);
    expect(transport.fetchScene).toHaveBeenCalledTimes(1);
  });

  it("holds a revision reported during a save until the save is done", async () => {
    let finish: (answer: SceneWrite) => void = () => undefined;
    const { sync, transport, editor } = setup(read([el("a")], 100), { fetch: () => read([el("a", 2), el("x")], 300) });
    transport.putScene.mockImplementationOnce(() => new Promise<SceneWrite>((resolve) => (finish = resolve)));
    sync.onChange(snap([el("a", 2)]));
    const saving = sync.flush();
    await sync.onRevision(300);
    expect(transport.fetchScene).not.toHaveBeenCalled();
    finish({ version: 2, updated_at: 150, merged: false });
    await saving;
    await vi.waitFor(() => expect(transport.fetchScene).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(editor.applyRemote).toHaveBeenCalledTimes(1));
  });

  it("hands new view settings from the server to the editor", async () => {
    const changed: SceneRead = { version: 2, updated_at: 200, scene: scene([el("a")], { appState: { viewBackgroundColor: "#000000", gridModeEnabled: true } }) };
    const { sync, editor } = setup(read([el("a")]), { fetch: () => changed });
    await sync.onRevision(200);
    expect(editor.applyRemote.mock.calls[0][1]).toEqual({ viewBackgroundColor: "#000000", gridModeEnabled: true });
  });

  it("sends an element the editor dropped without deleting it as deleted", async () => {
    const { sync, transport } = setup(read([el("old", 4)]));
    sync.onChange(snap([el("old", 4)]));
    // A scene opened from a file replaced the whole list.
    sync.onChange(snap([el("new")]));
    await sync.flush();
    const sent = transport.putScene.mock.calls[0][0].elements;
    const tombstone = sent.find((e) => e.id === "old");
    expect(tombstone).toMatchObject({ isDeleted: true, version: 5 });
    expect(sent.find((e) => e.id === "new")).toBeTruthy();
  });

  it("does not delete what the server has and the editor never held", async () => {
    const { sync, transport } = setup(read([el("server-only")]));
    sync.onChange(snap([el("mine")]));
    await sync.flush();
    expect(transport.putScene.mock.calls[0][0].elements.map((e) => e.id)).toEqual(["mine"]);
  });

  it("tries a failed save again by itself", async () => {
    const { sync, transport, states } = setup(read([]));
    transport.putScene.mockRejectedValueOnce(new Error("offline"));
    sync.onChange(snap([el("a")]));
    await sync.flush();
    expect(states.at(-1)).toBe("failed");
    await vi.advanceTimersByTimeAsync(6_000);
    expect(transport.putScene).toHaveBeenCalledTimes(2);
    expect(states.at(-1)).toBe("saved");
  });

  it("fetches the pictures the editor does not hold", async () => {
    const opened: SceneRead = {
      version: 1,
      updated_at: 100,
      scene: scene([el("img", 1, { type: "image", fileId: "f9" })], { files: { f9: { id: "f9", mimeType: "image/jpeg", created: 7 } } }),
    };
    const { sync, transport, editor } = setup(opened);
    await sync.loadMissingFiles(opened.scene.elements);
    expect(transport.fetchFile).toHaveBeenCalledWith("f9");
    expect(editor.addFiles).toHaveBeenCalledWith([
      { id: "f9", dataURL: "data:image/png;base64,AAAA", mimeType: "image/jpeg", created: 7 },
    ]);
  });
});
