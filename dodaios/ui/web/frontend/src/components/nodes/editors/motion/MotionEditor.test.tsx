/**
 * The clip editor as a whole: scene actions through the toolbar and the
 * inspector, one shared undo history, texts written in the preview, and a
 * save that waits while a scene lacks what its type needs.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { NodeCard } from "../../nodeModel";
import MotionEditor, { accentToHex, hexToAccent } from "./index";

vi.mock("@/i18n", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/i18n")>();
  return { ...actual, useT: () => (key: string) => key, useUiLanguage: () => "en" };
});

// jsdom has no PointerEvent; a mouse event with a pointer id carries what the timeline reads.
if (typeof window.PointerEvent === "undefined") {
  class TestPointerEvent extends MouseEvent {
    readonly pointerId: number;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
    }
  }
  (window as unknown as { PointerEvent: typeof TestPointerEvent }).PointerEvent = TestPointerEvent;
}

const NODE = {
  key: "k",
  id: "abc123",
  type: "motion",
  origin: "node",
  title: "Quarter",
  slug: "s",
  path: "p.html",
  visual_kind: null,
  created_at: 1,
  updated_at: 2,
  size: 0,
  version: 3,
  status: "ready",
  kept_current: false,
  refreshing: false,
  every_minutes: 0,
  request: "",
  preview: null,
} as unknown as NodeCard;

const SPEC = {
  format: "wide",
  theme: "dark",
  accent: "green",
  loop: false,
  scenes: [
    { type: "title", title: "Hello", seconds: 4, transition: "fade" },
    {
      type: "bars",
      title: "Revenue",
      items: [
        { label: "North", value: 420 },
        { label: "South", value: 310 },
      ],
      seconds: 4, transition: "slide",
    },
    { type: "end", title: "Bye", seconds: 3, transition: "zoom" },
  ],
};

let saves: { spec: Record<string, unknown>; base_version: number }[] = [];
let previews = 0;

beforeEach(() => {
  saves = [];
  previews = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/preview")) {
        previews += 1;
        return new Response("<!doctype html><html lang=\"en\"><body>film</body></html>", { status: 200 });
      }
      if (url.endsWith("/spec") && init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as { spec: Record<string, unknown>; base_version: number };
        saves.push(body);
        return new Response(JSON.stringify({ version: 4 + saves.length, updated_at: 10 + saves.length, spec: body.spec }), {
          status: 200,
        });
      }
      return new Response("{}", { status: 404 });
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function open() {
  const onDone = vi.fn();
  render(
    <MotionEditor
      node={NODE}
      initial={{ spec: structuredClone(SPEC), version: 3, updated_at: 2 }}
      onDone={onDone}
    />,
  );
  return { onDone };
}

const blocks = () => screen.getAllByRole("option");

/** Wait for the preview page and let it say it is ready: it becomes the page on screen. */
async function previewReady(): Promise<HTMLIFrameElement> {
  await waitFor(() => expect(previews).toBeGreaterThan(0));
  const frame = await waitFor(() => {
    const loaded = screen
      .getAllByTestId(/motion-preview-frame-/)
      .find((node) => (node as HTMLIFrameElement).getAttribute("srcdoc"));
    expect(loaded).toBeTruthy();
    return loaded as HTMLIFrameElement;
  });
  await act(async () => {
    window.dispatchEvent(new MessageEvent("message", { data: { type: "dodaios-node-ready" }, source: frame.contentWindow }));
  });
  await waitFor(() => expect(frame.getAttribute("data-active")).toBe("true"));
  return frame;
}

describe("MotionEditor", () => {
  it("adds a scene after the picked one, and undo and redo take it back and forth", () => {
    open();
    expect(blocks()).toHaveLength(3);
    fireEvent.click(screen.getByTestId("motion-add"));
    fireEvent.click(screen.getByTestId("motion-add-stat"));
    expect(blocks()).toHaveLength(4);
    // After the picked first scene, and picked itself.
    expect(blocks()[1].getAttribute("aria-selected")).toBe("true");
    expect(blocks()[1].textContent).toContain("nodes.editor.motion.kinds.stat");
    expect(screen.getByTestId("motion-field-value")).toBeTruthy();

    fireEvent.click(screen.getByTestId("node-editor-undo"));
    expect(blocks()).toHaveLength(3);
    fireEvent.click(screen.getByTestId("node-editor-redo"));
    expect(blocks()).toHaveLength(4);
  });

  it("duplicates and deletes the picked scene from the inspector", () => {
    open();
    fireEvent.pointerDown(blocks()[1], { button: 0, pointerId: 1, clientX: 0 });
    fireEvent.click(screen.getByTestId("motion-duplicate"));
    expect(blocks().map((block) => block.textContent?.includes("Revenue"))).toEqual([false, true, true, false]);
    expect(blocks()[2].getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByTestId("motion-delete"));
    fireEvent.click(screen.getByTestId("motion-delete"));
    expect(blocks()).toHaveLength(2);
    // A clip keeps one scene: the last one cannot be deleted.
    fireEvent.click(screen.getByTestId("motion-delete"));
    expect(blocks()).toHaveLength(1);
    expect((screen.getByTestId("motion-delete") as HTMLButtonElement).disabled).toBe(true);
  });

  it("makes a typing run one undo step and saves it with the version it came from", async () => {
    open();
    const field = screen.getByTestId("motion-field-title") as HTMLInputElement;
    fireEvent.change(field, { target: { value: "Hello!" } });
    fireEvent.change(field, { target: { value: "Hello there" } });
    expect(blocks()[0].textContent).toContain("Hello there");
    await waitFor(() => expect(saves.length).toBe(1), { timeout: 3000 });
    expect(saves[0].base_version).toBe(3);
    expect((saves[0].spec.scenes as { title: string }[])[0].title).toBe("Hello there");

    fireEvent.click(screen.getByTestId("node-editor-undo"));
    expect((screen.getByTestId("motion-field-title") as HTMLInputElement).value).toBe("Hello");
  });

  it("holds the save while a scene lacks what its type needs, and says which", async () => {
    open();
    fireEvent.change(screen.getByTestId("motion-field-title"), { target: { value: "" } });
    await waitFor(() => expect(screen.getByTestId("node-editor-save-state").getAttribute("data-state")).toBe("held"), {
      timeout: 3000,
    });
    expect(screen.getByTestId("node-editor-save-state").textContent).toBe("nodes.editor.motion.needs");
    expect(saves).toEqual([]);
    expect(blocks()[0].getAttribute("aria-invalid")).toBe("true");
  });

  it("takes a text written in the preview as one step, and answers the page", async () => {
    open();
    const frame = await previewReady();
    const answers: unknown[] = [];
    const post = vi.spyOn(frame.contentWindow as Window, "postMessage").mockImplementation((message: unknown) => {
      answers.push(message);
    });

    await act(async () => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: "dodaios-node-edit", id: 7, path: "/scenes/1/items/0/value", value: "1.250,5", as: "number" },
          source: frame.contentWindow,
        }),
      );
    });
    expect(answers).toContainEqual({ type: "dodaios-node-edit-state", id: 7, state: "saved" });
    // The edited scene is picked, and its inspector shows the new number.
    expect(blocks()[1].getAttribute("aria-selected")).toBe("true");
    expect((screen.getByTestId("motion-bar-value-0") as HTMLInputElement).value).toBe("1250.5");

    await act(async () => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: "dodaios-node-edit", id: 8, path: "/scenes/1/items/1/value", value: "lots", as: "number" },
          source: frame.contentWindow,
        }),
      );
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: "dodaios-node-edit", id: 9, path: "/scenes/0/kicker", value: "Q3", as: "text" },
          source: frame.contentWindow,
        }),
      );
    });
    // Not a number, and a place the spec has no value at: both refused.
    expect(answers).toContainEqual({ type: "dodaios-node-edit-state", id: 8, state: "failed" });
    expect(answers).toContainEqual({ type: "dodaios-node-edit-state", id: 9, state: "failed" });

    fireEvent.click(screen.getByTestId("node-editor-undo"));
    expect((screen.getByTestId("motion-bar-value-0") as HTMLInputElement).value).toBe("420");
    post.mockRestore();
  });

  it("stands the preview on the picked scene and plays it from there", async () => {
    open();
    const frame = await previewReady();
    const sent: Record<string, unknown>[] = [];
    vi.spyOn(frame.contentWindow as Window, "postMessage").mockImplementation((message: unknown) => {
      sent.push(message as Record<string, unknown>);
    });
    // The page itself opened on the picked scene (no play from the start first).
    expect(frame.getAttribute("srcdoc")).toContain('data-film-scene="0"');

    fireEvent.pointerDown(blocks()[2], { button: 0, pointerId: 1, clientX: 0 });
    expect(sent).toContainEqual({ type: "dodaios-node-mode", mode: "edit" });
    expect(sent).toContainEqual({ type: "dodaios-film-seek", t: 8, play: false });

    fireEvent.click(screen.getByTestId("motion-play"));
    expect(sent).toContainEqual({ type: "dodaios-node-mode", mode: "view" });
    expect(sent).toContainEqual({ type: "dodaios-film-seek", t: 8, play: true });

    const report = (data: Record<string, unknown>) =>
      act(async () => {
        window.dispatchEvent(new MessageEvent("message", { data: { type: "dodaios-film-time", ...data }, source: frame.contentWindow }));
      });
    // A report from before the page started playing does not end the play.
    await report({ t: 9, scene: 2, playing: false });
    expect(screen.getByTestId("motion-stop")).toBeTruthy();
    await report({ t: 9.5, scene: 2, playing: true });
    expect(screen.getByTestId("motion-playhead")).toBeTruthy();
    // The film ended: the editor stands on the scene it reached.
    await report({ t: 11, scene: 2, playing: false });
    expect(screen.getByTestId("motion-play")).toBeTruthy();
    expect(screen.queryByTestId("motion-playhead")).toBeNull();
  });

  it("changes the whole clip's look from the toolbar, each an undo step", () => {
    open();
    fireEvent.click(screen.getByTestId("motion-loop"));
    expect(screen.getByTestId("motion-loop").getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByTestId("motion-theme"));
    expect(screen.getByTestId("motion-theme").getAttribute("aria-label")).toBe("nodes.editor.motion.toolbar.toDark");
    fireEvent.click(screen.getByTestId("node-editor-undo"));
    fireEvent.click(screen.getByTestId("node-editor-undo"));
    expect(screen.getByTestId("motion-loop").getAttribute("aria-pressed")).toBe("false");
  });

  it("changes a scene's length from the inspector and fits it back to its content", () => {
    open();
    const fit = screen.getByTestId("motion-fit") as HTMLButtonElement;
    // The opening title runs its default 4 s: nothing to fit.
    expect(fit.disabled).toBe(true);
    const handle = screen.getByTestId("motion-length-0");
    fireEvent.keyDown(handle, { key: "ArrowRight", shiftKey: true });
    expect(handle.getAttribute("aria-valuenow")).toBe("4.5");
    fireEvent.click(screen.getByTestId("motion-fit"));
    expect(screen.getByTestId("motion-length-0").getAttribute("aria-valuenow")).toBe("4");
  });

  it("edits a list: points of a bar scene are added, moved and removed", () => {
    open();
    fireEvent.pointerDown(blocks()[1], { button: 0, pointerId: 1, clientX: 0 });
    fireEvent.click(screen.getByText("nodes.editor.motion.inspector.addBar"));
    expect(screen.getByTestId("motion-bar-label-2")).toBeTruthy();
    fireEvent.change(screen.getByTestId("motion-bar-label-2"), { target: { value: "East" } });
    fireEvent.click(screen.getAllByLabelText("nodes.editor.motion.inspector.moveUp")[2]);
    expect((screen.getByTestId("motion-bar-label-1") as HTMLInputElement).value).toBe("East");
    fireEvent.click(screen.getAllByLabelText("nodes.editor.motion.inspector.remove")[0]);
    expect((screen.getByTestId("motion-bar-label-0") as HTMLInputElement).value).toBe("East");
  });
});

describe("accent", () => {
  it("keeps the kit's colours by name, so the film takes the theme's shade", () => {
    expect(hexToAccent(accentToHex("green"))).toBe("green");
    expect(accentToHex("purple")).toBe(accentToHex("violet"));
    expect(hexToAccent("#123456")).toBe("#123456");
    expect(accentToHex("#abcdef")).toBe("#ABCDEF");
    expect(accentToHex("")).toBe("");
    expect(hexToAccent("")).toBe("");
  });
});
