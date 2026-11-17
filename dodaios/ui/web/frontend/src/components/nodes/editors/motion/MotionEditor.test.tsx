/**
 * The clip editor as a whole: the bin, the timeline's keys, the inspector,
 * one shared undo history, and the preview steered and answered.
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

function open(spec: Record<string, unknown> = SPEC) {
  const onDone = vi.fn();
  render(
    <MotionEditor
      node={NODE}
      initial={{ spec: structuredClone(spec), version: 3, updated_at: 2 }}
      onDone={onDone}
    />,
  );
  return { onDone };
}

/** A new clip as the server's starter makes it: one blank title card. */
const BLANK = {
  format: "wide",
  theme: "dark",
  accent: "",
  loop: false,
  scenes: [{ type: "title", seconds: 4, transition: "fade" }],
};


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

const SAVE_WAIT = { timeout: 4000 };
const lastSave = () => saves[saves.length - 1]?.spec as Record<string, any> | undefined; // eslint-disable-line @typescript-eslint/no-explicit-any
const editorKeys = (key: string, init: KeyboardEventInit = {}) => fireEvent.keyDown(screen.getByTestId("clip-editor"), { key, ...init });

describe("MotionEditor", () => {
  it("adds a card from the bin after the piece under the playhead, and undo takes it back", () => {
    open();
    expect(screen.getAllByTestId(/^clip-scene-/)).toHaveLength(3);
    fireEvent.click(screen.getByTestId("clip-tab-cards"));
    fireEvent.click(screen.getByTestId("motion-add-stat"));
    expect(screen.getAllByTestId(/^clip-scene-/)).toHaveLength(4);
    // After the first scene (the playhead stands at 0), and it is picked.
    expect(screen.getByTestId("clip-scene-1").getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByTestId("node-editor-undo"));
    expect(screen.getAllByTestId(/^clip-scene-/)).toHaveLength(3);
    fireEvent.click(screen.getByTestId("node-editor-redo"));
    expect(screen.getAllByTestId(/^clip-scene-/)).toHaveLength(4);
  });

  it("splits at the playhead with S, deletes the pick with Delete, and saves", async () => {
    open();
    editorKeys("ArrowRight", { shiftKey: true });
    editorKeys("ArrowRight", { shiftKey: true });
    expect(screen.getByTestId("clip-clock").textContent).toContain("0:02.00");
    editorKeys("s");
    expect(screen.getAllByTestId(/^clip-scene-/)).toHaveLength(4);
    // The right half is picked; Delete takes it away and the track closes up.
    editorKeys("Delete");
    expect(screen.getAllByTestId(/^clip-scene-/)).toHaveLength(3);
    await waitFor(() => expect(saves.length).toBeGreaterThan(0), SAVE_WAIT);
    await waitFor(() => expect((lastSave()?.scenes as { seconds: number }[])[0].seconds).toBe(2), SAVE_WAIT);
    expect(saves[0].base_version).toBe(3);
  });

  it("adds a text layer at the playhead and edits it in the inspector", async () => {
    open();
    fireEvent.click(screen.getByTestId("clip-tab-text"));
    fireEvent.click(screen.getByTestId("clip-add-text-title"));
    expect(screen.getByTestId("clip-inspector-text")).toBeTruthy();
    fireEvent.change(screen.getByTestId("clip-text"), { target: { value: "Watch this" } });
    await waitFor(() => expect(lastSave()?.tracks?.[0]?.items?.[0]?.text).toBe("Watch this"), SAVE_WAIT);
    expect(lastSave()?.tracks?.[0]).toMatchObject({ kind: "text" });
    expect(lastSave()?.tracks?.[0]?.items?.[0]).toMatchObject({ start: 0, style: "title", anim: "pop" });
  });

  it("shows the preview bare, plays from the playhead and follows the page's clock", async () => {
    open();
    const frame = await previewReady();
    const sent: Record<string, unknown>[] = [];
    vi.spyOn(frame.contentWindow as Window, "postMessage").mockImplementation((message: unknown) => {
      sent.push(message as Record<string, unknown>);
    });
    fireEvent.click(screen.getByTestId("motion-play"));
    expect(sent).toContainEqual({ type: "dodaios-film-view", bare: true, guides: false });
    expect(sent).toContainEqual({ type: "dodaios-film-seek", t: 0, play: true });
    const report = (data: Record<string, unknown>) =>
      act(async () => {
        window.dispatchEvent(new MessageEvent("message", { data: { type: "dodaios-film-time", ...data }, source: frame.contentWindow }));
      });
    // A report from before the page started playing does not end the play.
    await report({ t: 0, scene: 0, playing: false });
    expect(screen.getByTestId("motion-stop")).toBeTruthy();
    await report({ t: 2.5, scene: 0, playing: true });
    expect(screen.getByTestId("clip-clock").textContent).toContain("0:02.50");
    await report({ t: 11, scene: 2, playing: false });
    expect(screen.getByTestId("motion-play")).toBeTruthy();
    // The safe-zone guide is the page's own.
    fireEvent.click(screen.getByTestId("clip-guides"));
    expect(sent).toContainEqual({ type: "dodaios-film-view", bare: true, guides: true });
  });

  it("takes a text written in the preview (text mode) as one step, and answers the page", async () => {
    open();
    const frame = await previewReady();
    const answers: Record<string, unknown>[] = [];
    vi.spyOn(frame.contentWindow as Window, "postMessage").mockImplementation((message: unknown) => {
      answers.push(message as Record<string, unknown>);
    });
    fireEvent.click(screen.getByTestId("clip-edit-text"));
    expect(answers).toContainEqual({ type: "dodaios-node-mode", mode: "edit" });
    await act(async () => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: "dodaios-node-edit", id: 7, path: "/scenes/0/title", value: "Hi there" },
          source: frame.contentWindow,
        }),
      );
    });
    expect(answers).toContainEqual({ type: "dodaios-node-edit-state", id: 7, state: "saved" });
    await waitFor(() => expect(lastSave()?.scenes?.[0]?.title).toBe("Hi there"), SAVE_WAIT);
  });

  it("moves a layer dragged in the preview and picks what was clicked", async () => {
    open({
      ...SPEC,
      tracks: [{ id: "tr1", kind: "text", items: [{ id: "t1", start: 0, seconds: 3, text: "Hook", style: "title", x: 50, y: 50 }] }],
    });
    const frame = await previewReady();
    await act(async () => {
      window.dispatchEvent(new MessageEvent("message", { data: { type: "dodaios-film-pick", id: "t1" }, source: frame.contentWindow }));
    });
    expect(screen.getByTestId("clip-inspector-text")).toBeTruthy();
    await act(async () => {
      window.dispatchEvent(new MessageEvent("message", { data: { type: "dodaios-film-move", id: "t1", x: 30.5, y: 20 }, source: frame.contentWindow }));
    });
    await waitFor(() => expect(lastSave()?.tracks?.[0]?.items?.[0]).toMatchObject({ x: 30.5, y: 20 }), SAVE_WAIT);
  });

  it("sets the format from a platform preset in the clip's settings", async () => {
    open();
    fireEvent.click(screen.getByTestId("clip-preset-shorts"));
    await waitFor(() => expect(lastSave()?.format).toBe("tall"), SAVE_WAIT);
    fireEvent.click(screen.getByTestId("clip-preset-feed"));
    await waitFor(() => expect(lastSave()?.format).toBe("portrait"), SAVE_WAIT);
  });

  it("copies and pastes the pick at the playhead with Ctrl+C / Ctrl+V", () => {
    open();
    fireEvent.pointerDown(screen.getByTestId("clip-scene-2"), { button: 0, pointerId: 1, clientX: 0 });
    fireEvent.pointerUp(screen.getByTestId("clip-scene-2"), { button: 0, pointerId: 1, clientX: 0 });
    editorKeys("c", { ctrlKey: true });
    editorKeys("Home");
    editorKeys("v", { ctrlKey: true });
    const scenes = screen.getAllByTestId(/^clip-scene-/);
    expect(scenes).toHaveLength(4);
    expect(scenes[1].getAttribute("aria-selected")).toBe("true");
  });

  it("opens a new clip blank and saves the first card typed into it", async () => {
    open(BLANK);
    fireEvent.pointerDown(screen.getByTestId("clip-scene-0"), { button: 0, pointerId: 1, clientX: 0 });
    fireEvent.pointerUp(screen.getByTestId("clip-scene-0"), { button: 0, pointerId: 1, clientX: 0 });
    fireEvent.change(screen.getByTestId("motion-field-title"), { target: { value: "Launch" } });
    await waitFor(() => expect(lastSave()?.scenes?.[0]?.title).toBe("Launch"), SAVE_WAIT);
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
