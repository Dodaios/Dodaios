import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { RevisionContext, createRevisionSource } from "./editorContext";
import { hasOwnUndo, shortcutOf, useNodeSpecEditor, type NodeSpecEditorOptions } from "./useNodeSpecEditor";

interface Sheet {
  title: string;
  rows: string[];
}

/** A stand-in server: one node, a version, and a normalize that drops empty rows. */
function server(spec: Sheet) {
  const state = { version: 1, updated_at: 100, spec: spec as Sheet };
  const puts: { spec: Sheet; base_version: number | null; keepalive?: boolean }[] = [];
  let fail: { status: number; detail: string } | null = null;
  let hold: Promise<void> | null = null;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/spec") && init?.method === "PUT") {
      if (hold) await hold;
      const body = JSON.parse(String(init.body)) as { spec: Sheet; base_version: number | null };
      puts.push({ ...body, keepalive: init.keepalive });
      if (fail) return { ok: false, status: fail.status, json: async () => ({ detail: fail?.detail }) };
      if (body.base_version !== null && body.base_version !== state.version) {
        return { ok: false, status: 409, json: async () => ({ detail: "changed", ...state }) };
      }
      state.version += 1;
      state.updated_at += 10;
      state.spec = { ...body.spec, rows: body.spec.rows.filter(Boolean) };
      return { ok: true, status: 200, json: async () => ({ ...state }) };
    }
    if (/\/api\/nodes\/[^/]+$/.test(url)) return { ok: true, status: 200, json: async () => ({ ...state }) };
    return { ok: false, status: 404, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    state,
    puts,
    fetchMock,
    failWith(next: { status: number; detail: string } | null) {
      fail = next;
    },
    holdSaves() {
      let release = () => {};
      hold = new Promise<void>((resolve) => {
        release = () => {
          hold = null;
          resolve();
        };
      });
      return release;
    },
    /** The assistant revises the node. */
    revise(next: Sheet) {
      state.version += 1;
      state.updated_at += 100;
      state.spec = next;
    },
  };
}

const START: Sheet = { title: "Orders", rows: ["a"] };

function setup(options: NodeSpecEditorOptions<Sheet> = {}, withSource = false) {
  const remote = server(START);
  const source = createRevisionSource();
  const wrapper = withSource
    ? ({ children }: { children: ReactNode }) => <RevisionContext.Provider value={source}>{children}</RevisionContext.Provider>
    : undefined;
  const hook = renderHook(
    () => useNodeSpecEditor<Sheet>("n1", { spec: START, version: 1, updated_at: 100 }, { saveDelayMs: 20, ...options }),
    { wrapper },
  );
  return { remote, source, hook };
}

beforeEach(() => {
  vi.useRealTimers();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("useNodeSpecEditor", () => {
  it("applies changes immutably and undoes and redoes them", () => {
    const { hook } = setup();
    const first = hook.result.current.spec;
    act(() => hook.result.current.apply((draft) => void draft.rows.push("b"), { label: "Add row" }));
    expect(hook.result.current.spec.rows).toEqual(["a", "b"]);
    expect(first.rows).toEqual(["a"]);
    expect(hook.result.current.canUndo).toBe(true);
    expect(hook.result.current.undoLabel).toBe("Add row");
    act(() => hook.result.current.undo());
    expect(hook.result.current.spec).toBe(first);
    expect(hook.result.current.canRedo).toBe(true);
    act(() => hook.result.current.redo());
    expect(hook.result.current.spec.rows).toEqual(["a", "b"]);
    expect(hook.result.current.history.undo).toEqual(["Add row"]);
  });

  it("chains several changes made in one event", () => {
    const { hook } = setup();
    act(() => {
      hook.result.current.apply((draft) => void draft.rows.push("b"));
      hook.result.current.apply((draft) => void draft.rows.push("c"));
    });
    expect(hook.result.current.spec.rows).toEqual(["a", "b", "c"]);
    expect(hook.result.current.history.undo).toHaveLength(2);
  });

  it("coalesces a typing run into one step until the run is broken", () => {
    const { hook } = setup();
    for (const text of ["O", "Or", "Ord"]) {
      act(() => hook.result.current.apply((draft) => void (draft.title = text), { coalesce: "title" }));
    }
    expect(hook.result.current.history.undo).toHaveLength(1);
    act(() => hook.result.current.breakCoalesce());
    act(() => hook.result.current.apply((draft) => void (draft.title = "Ordx"), { coalesce: "title" }));
    expect(hook.result.current.history.undo).toHaveLength(2);
    act(() => hook.result.current.undo());
    act(() => hook.result.current.undo());
    expect(hook.result.current.spec.title).toBe("Orders");
  });

  it("saves after a quiet moment from the base version, and does not swap the normalized spec in", async () => {
    const { hook, remote } = setup();
    act(() => hook.result.current.apply((draft) => void draft.rows.push("")));
    expect(hook.result.current.dirty).toBe(true);
    await waitFor(() => expect(hook.result.current.saveState).toBe("saved"));
    expect(remote.puts).toHaveLength(1);
    expect(remote.puts[0].base_version).toBe(1);
    // The server dropped the empty row; the person's new row stays on screen.
    expect(hook.result.current.spec.rows).toEqual(["a", ""]);
    expect(hook.result.current.saved.rows).toEqual(["a"]);
    expect(hook.result.current.version).toBe(2);
    expect(hook.result.current.dirty).toBe(false);
  });

  it("debounces a burst of changes into one save", async () => {
    const { hook, remote } = setup();
    for (const text of ["A", "AB", "ABC"]) {
      act(() => hook.result.current.apply((draft) => void (draft.title = text), { coalesce: "t" }));
    }
    await waitFor(() => expect(hook.result.current.saveState).toBe("saved"));
    expect(remote.puts.map((put) => put.spec.title)).toEqual(["ABC"]);
  });

  it("is clean again after undoing back to the saved version, without a save", async () => {
    const { hook, remote } = setup({ saveDelayMs: 10_000 });
    act(() => hook.result.current.apply((draft) => void (draft.title = "X")));
    expect(hook.result.current.dirty).toBe(true);
    act(() => hook.result.current.undo());
    expect(hook.result.current.dirty).toBe(false);
    expect(await hook.result.current.flush()).toBe(true);
    expect(remote.puts).toHaveLength(0);
  });

  it("saves changes made while a save is on its way right after it", async () => {
    const { hook, remote } = setup();
    const release = remote.holdSaves();
    act(() => hook.result.current.apply((draft) => void (draft.title = "One")));
    await waitFor(() => expect(hook.result.current.saveState).toBe("saving"));
    act(() => hook.result.current.apply((draft) => void (draft.title = "Two")));
    release();
    await waitFor(() => expect(remote.puts.map((put) => put.spec.title)).toEqual(["One", "Two"]));
    await waitFor(() => expect(hook.result.current.saveState).toBe("saved"));
    expect(remote.puts[1].base_version).toBe(2);
  });

  it("flushes at once on blur", async () => {
    const { hook, remote } = setup({ saveDelayMs: 10_000 });
    act(() => hook.result.current.apply((draft) => void (draft.title = "X")));
    act(() => hook.result.current.onBlur());
    await waitFor(() => expect(remote.puts).toHaveLength(1));
  });

  it("turns a refused save into a conflict and lets the person take theirs, undoably", async () => {
    const { hook, remote } = setup();
    remote.revise({ title: "Theirs", rows: [] });
    act(() => hook.result.current.apply((draft) => void (draft.title = "Mine")));
    await waitFor(() => expect(hook.result.current.saveState).toBe("conflict"));
    expect(hook.result.current.conflict?.version).toBe(2);
    // No more saves while the conflict is open.
    act(() => hook.result.current.apply((draft) => void (draft.title = "Mine 2")));
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(remote.puts).toHaveLength(1);

    act(() => hook.result.current.takeTheirs());
    expect(hook.result.current.spec.title).toBe("Theirs");
    expect(hook.result.current.conflict).toBeNull();
    expect(hook.result.current.dirty).toBe(false);
    expect(hook.result.current.version).toBe(2);
    // The person's own version is one undo away, and saving it then goes through.
    act(() => hook.result.current.undo());
    expect(hook.result.current.spec.title).toBe("Mine 2");
    await waitFor(() => expect(hook.result.current.saveState).toBe("saved"));
    expect(remote.state.spec.title).toBe("Mine 2");
  });

  it("keeps mine by saving over the other version", async () => {
    const { hook, remote } = setup();
    remote.revise({ title: "Theirs", rows: [] });
    act(() => hook.result.current.apply((draft) => void (draft.title = "Mine")));
    await waitFor(() => expect(hook.result.current.saveState).toBe("conflict"));
    act(() => hook.result.current.keepMine());
    await waitFor(() => expect(hook.result.current.saveState).toBe("saved"));
    expect(remote.puts.at(-1)?.base_version).toBe(2);
    expect(remote.state.spec.title).toBe("Mine");
    expect(hook.result.current.spec.title).toBe("Mine");
  });

  it("takes a remote revision when nothing is unsaved, as an undoable step", async () => {
    const { hook, remote, source } = setup({}, true);
    remote.revise({ title: "Revised", rows: ["z"] });
    act(() => source.emit(remote.state.updated_at));
    await waitFor(() => expect(hook.result.current.spec.title).toBe("Revised"));
    expect(hook.result.current.version).toBe(2);
    expect(hook.result.current.dirty).toBe(false);
    expect(hook.result.current.undoLabel).toContain("Revised by");
    act(() => hook.result.current.undo());
    expect(hook.result.current.spec.title).toBe("Orders");
  });

  it("ignores the watcher's report of its own save and of the version it opened", async () => {
    const { hook, remote, source } = setup({}, true);
    act(() => source.emit(100));
    act(() => hook.result.current.apply((draft) => void (draft.title = "Mine")));
    await waitFor(() => expect(hook.result.current.saveState).toBe("saved"));
    const reads = () => remote.fetchMock.mock.calls.filter(([, init]) => !init?.method).length;
    act(() => source.emit(remote.state.updated_at));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(reads()).toBe(0);
    expect(hook.result.current.history.undo).toHaveLength(1);
  });

  it("turns a remote revision under unsaved work into a conflict", async () => {
    const { hook, remote } = setup({ saveDelayMs: 10_000 });
    act(() => hook.result.current.apply((draft) => void (draft.title = "Mine")));
    remote.revise({ title: "Theirs", rows: [] });
    act(() => hook.result.current.receiveRevision(remote.state.updated_at));
    await waitFor(() => expect(hook.result.current.saveState).toBe("conflict"));
    expect(hook.result.current.spec.title).toBe("Mine");
    expect(hook.result.current.conflict?.spec).toEqual({ title: "Theirs", rows: [] });
  });

  it("says why a refused save failed and waits for the next change", async () => {
    const { hook, remote } = setup();
    remote.failWith({ status: 422, detail: "A row needs a name." });
    act(() => hook.result.current.apply((draft) => void (draft.title = "X")));
    await waitFor(() => expect(hook.result.current.saveState).toBe("failed"));
    expect(hook.result.current.error).toBe("A row needs a name.");
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(remote.puts).toHaveLength(1);
    remote.failWith(null);
    act(() => hook.result.current.retry());
    await waitFor(() => expect(hook.result.current.saveState).toBe("saved"));
  });

  it("holds a save that prepare refuses, and sends what prepare made", async () => {
    const prepare = (spec: Sheet) => (spec.title ? { ...spec, rows: spec.rows.filter(Boolean) } : { error: "Name it first." });
    const { hook, remote } = setup({ prepare });
    act(() => hook.result.current.apply((draft) => void (draft.title = "")));
    await waitFor(() => expect(hook.result.current.saveState).toBe("held"));
    expect(hook.result.current.error).toBe("Name it first.");
    expect(remote.puts).toHaveLength(0);
    act(() =>
      hook.result.current.apply((draft) => {
        draft.title = "Named";
        draft.rows.push("");
      }),
    );
    await waitFor(() => expect(hook.result.current.saveState).toBe("saved"));
    expect(remote.puts[0].spec).toEqual({ title: "Named", rows: ["a"] });
    expect(hook.result.current.spec.rows).toEqual(["a", ""]);
  });

  it("saves what is unsaved when it unmounts", async () => {
    const { hook, remote } = setup({ saveDelayMs: 10_000 });
    act(() => hook.result.current.apply((draft) => void (draft.title = "Last words")));
    hook.unmount();
    await waitFor(() => expect(remote.puts).toHaveLength(1));
    expect(remote.puts[0].spec.title).toBe("Last words");
    expect(remote.puts[0].keepalive).toBe(true);
  });

  it("saves when the window is hidden", async () => {
    const { hook, remote } = setup({ saveDelayMs: 10_000 });
    act(() => hook.result.current.apply((draft) => void (draft.title = "Hidden")));
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    act(() => void document.dispatchEvent(new Event("visibilitychange")));
    await waitFor(() => expect(remote.puts).toHaveLength(1));
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
  });

  it("maps the shortcuts and leaves text fields their own undo", () => {
    const { hook } = setup();
    act(() => hook.result.current.apply((draft) => void (draft.title = "X")));
    const button = document.createElement("button");
    const event = new KeyboardEvent("keydown", { key: "z", metaKey: true, cancelable: true });
    Object.defineProperty(event, "target", { value: button });
    act(() => hook.result.current.onKeyDown(event));
    expect(event.defaultPrevented).toBe(true);
    expect(hook.result.current.spec.title).toBe("Orders");

    const field = document.createElement("input");
    const inField = new KeyboardEvent("keydown", { key: "z", ctrlKey: true, shiftKey: true, cancelable: true });
    Object.defineProperty(inField, "target", { value: field });
    act(() => hook.result.current.onKeyDown(inField));
    expect(inField.defaultPrevented).toBe(false);
    expect(hook.result.current.spec.title).toBe("Orders");

    expect(shortcutOf({ key: "z", metaKey: true, ctrlKey: false, shiftKey: false, altKey: false })).toBe("undo");
    expect(shortcutOf({ key: "Z", metaKey: true, ctrlKey: false, shiftKey: true, altKey: false })).toBe("redo");
    expect(shortcutOf({ key: "y", metaKey: false, ctrlKey: true, shiftKey: false, altKey: false })).toBe("redo");
    expect(shortcutOf({ key: "z", metaKey: false, ctrlKey: false, shiftKey: false, altKey: false })).toBeNull();
    expect(shortcutOf({ key: "z", metaKey: true, ctrlKey: false, shiftKey: false, altKey: true })).toBeNull();
  });

  it("knows which targets keep their own undo", () => {
    const wrap = document.createElement("div");
    wrap.setAttribute("data-spec-undo", "");
    const inWrap = document.createElement("textarea");
    wrap.appendChild(inWrap);
    const own = document.createElement("div");
    own.setAttribute("data-own-undo", "");
    const button = document.createElement("button");
    own.appendChild(button);
    const editable = document.createElement("div");
    editable.setAttribute("contenteditable", "true");
    document.body.append(wrap, own, editable);
    expect(hasOwnUndo(document.createElement("input"))).toBe(true);
    expect(hasOwnUndo(Object.assign(document.createElement("input"), { type: "checkbox" }))).toBe(false);
    expect(hasOwnUndo(inWrap)).toBe(false);
    expect(hasOwnUndo(button)).toBe(true);
    expect(hasOwnUndo(document.createElement("button"))).toBe(false);
    expect(hasOwnUndo(null)).toBe(false);
    expect(hasOwnUndo(editable)).toBe(true);
    wrap.remove();
    own.remove();
    editable.remove();
  });
});
