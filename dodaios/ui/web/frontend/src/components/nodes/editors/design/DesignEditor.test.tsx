/**
 * The Visuals editor on its own, with the network stubbed. The preview
 * frame's script does not run here, so its messages are posted as the frame
 * would post them.
 *
 * Contracts worth pinning:
 * - the design opens with its blocks as a tree and the page's settings,
 * - selecting a block (in the tree, or in the preview) opens its inspector;
 *   its words typed there are one undo step and are saved as markup,
 * - blocks are added after the selection, duplicated, moved and deleted,
 *   from the toolbar and from the keyboard,
 * - words typed in place in the preview come back as markup; a shortcut
 *   pressed in the preview reaches the editor,
 * - colours are written as theme tokens; the page's accent goes into the spec,
 * - a design emptied of every block holds its save with the reason.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { NodeCard } from "../../nodeModel";
import DesignEditor from "./index";
import { PICKER_SOURCE } from "./picker";

const HTML =
  '<section class="cover"><h1>Open house</h1><p class="lead">Saturday, 10 am</p>' +
  '<svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"></circle></svg></section>';

function card(): NodeCard {
  return {
    key: "k",
    id: "d1",
    type: "design",
    origin: "node",
    title: "Open house",
    slug: "2026__node__d1",
    path: "index.html",
    visual_kind: "page",
    created_at: 1,
    updated_at: 100,
    size: 0,
    version: 1,
    status: "ready",
    kept_current: false,
    refreshing: false,
    every_minutes: 0,
    request: "",
    preview: null,
  };
}

let puts: Array<{ spec: Record<string, unknown> }> = [];
let previews = 0;

beforeEach(() => {
  puts = [];
  previews = 0;
  // jsdom lays nothing out; the tree keeps the selected row in view with this.
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/spec") && init?.method === "PUT") {
        const body = JSON.parse(String(init.body));
        puts.push(body);
        return new Response(JSON.stringify({ version: 2 + puts.length, updated_at: 200 + puts.length, spec: body.spec }), { status: 200 });
      }
      if (url.endsWith("/preview")) {
        previews += 1;
        return new Response('<!doctype html><html><head></head><body><main class="design">x</main></body></html>', { status: 200 });
      }
      return new Response("{}", { status: 404 });
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function open(spec: Record<string, unknown> = { html: HTML, css: "", fit: "page", background: "" }) {
  render(<DesignEditor node={card()} initial={{ spec, version: 1, updated_at: 100 }} onDone={vi.fn()} />);
}

const rows = () => screen.getAllByTestId("design-layer").map((row) => row.querySelector('[data-part="label"]')?.textContent ?? "");
const lastHtml = () => String(puts[puts.length - 1]!.spec.html);

/** A message as the preview frame's script posts it. */
function fromFrame(data: Record<string, unknown>) {
  const frame = screen.getByTestId("node-preview-frame") as HTMLIFrameElement;
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { data: { source: PICKER_SOURCE, ...data }, source: frame.contentWindow }));
  });
}

describe("DesignEditor", () => {
  it("opens with the blocks as a tree and the page's settings", async () => {
    open();
    expect(rows()).toEqual([".cover", "Open house", "Saturday, 10 am", "Drawing"]);
    expect(screen.getByRole("tree", { name: "Blocks of the design" })).toBeTruthy();
    expect(screen.getByTestId("design-page-inspector")).toBeTruthy();
    // The real page is asked for, drawn from the unsaved spec.
    await waitFor(() => expect(previews).toBeGreaterThan(0), { timeout: 3000 });
  });

  it("edits a block's words in the inspector as one undo step, saved as markup", async () => {
    open();
    fireEvent.click(screen.getAllByTestId("design-layer")[1]!);
    expect(screen.getByTestId("design-element-inspector")).toBeTruthy();
    const text = screen.getByTestId("design-text");
    fireEvent.change(text, { target: { value: "Open" } });
    fireEvent.change(text, { target: { value: "Open studio\n2026" } });
    expect(rows()[1]).toBe("Open studio2026");
    await waitFor(() => expect(puts.length).toBeGreaterThan(0), { timeout: 3000 });
    expect(lastHtml()).toContain("<h1>Open studio<br>2026</h1>");

    fireEvent.click(screen.getByTestId("node-editor-undo"));
    expect(rows()[1]).toBe("Open house");
    expect((screen.getByTestId("node-editor-undo") as HTMLButtonElement).disabled).toBe(true);
  });

  it("adds a block after the selection and selects it", () => {
    open();
    fireEvent.click(screen.getAllByTestId("design-layer")[1]!);
    fireEvent.click(screen.getByTestId("design-add"));
    fireEvent.click(screen.getByTestId("design-add-button"));
    expect(rows()).toEqual([".cover", "Open house", "Learn more", "Saturday, 10 am", "Drawing"]);
    expect(screen.getAllByTestId("design-layer")[2]!.getAttribute("aria-selected")).toBe("true");
  });

  it("duplicates, moves and deletes from the toolbar and the keyboard", () => {
    open();
    fireEvent.click(screen.getAllByTestId("design-layer")[2]!);
    fireEvent.click(screen.getByTestId("design-duplicate"));
    expect(rows()).toEqual([".cover", "Open house", "Saturday, 10 am", "Saturday, 10 am", "Drawing"]);
    fireEvent.click(screen.getByTestId("design-delete"));
    expect(rows()).toEqual([".cover", "Open house", "Saturday, 10 am", "Drawing"]);

    const row = screen.getAllByTestId("design-layer")[2]!;
    fireEvent.click(row);
    fireEvent.keyDown(row, { key: "ArrowUp", altKey: true });
    expect(rows()).toEqual([".cover", "Saturday, 10 am", "Open house", "Drawing"]);
    fireEvent.keyDown(screen.getAllByTestId("design-layer")[1]!, { key: "Delete" });
    expect(rows()).toEqual([".cover", "Open house", "Drawing"]);
  });

  it("travels the tree with the arrow keys", () => {
    open();
    const first = screen.getAllByTestId("design-layer")[0]!;
    fireEvent.click(first);
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(screen.getAllByTestId("design-layer")[1]!.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(screen.getAllByTestId("design-layer")[1]!, { key: "ArrowLeft" });
    expect(screen.getAllByTestId("design-layer")[0]!.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(screen.getAllByTestId("design-layer")[0]!, { key: "ArrowLeft" });
    expect(rows()).toEqual([".cover"]);
    expect(screen.getAllByTestId("design-layer")[0]!.getAttribute("aria-expanded")).toBe("false");
  });

  it("takes a selection, words typed in place and a shortcut from the preview", async () => {
    open();
    await waitFor(() => expect(previews).toBeGreaterThan(0), { timeout: 3000 });
    fromFrame({ type: "select", path: [0, 1] });
    expect(screen.getAllByTestId("design-layer")[2]!.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByTestId("design-element-inspector")).toBeTruthy();

    fromFrame({ type: "text", path: [0, 1], html: "Sunday, <b>11 am</b><div>sharp</div>" });
    expect(rows()[2]).toBe("Sunday, 11 amsharp");
    fromFrame({ type: "key", key: "z", meta: true, ctrl: false, shift: false, alt: false });
    expect(rows()[2]).toBe("Saturday, 10 am");
    fromFrame({ type: "key", key: "z", meta: true, ctrl: false, shift: true, alt: false });
    await waitFor(() => expect(puts.length).toBeGreaterThan(0), { timeout: 3000 });
    expect(lastHtml()).toContain('<p class="lead">Sunday, <b>11 am</b><br>sharp</p>');

    // A message from somewhere else than the frame is not taken.
    act(() => {
      window.dispatchEvent(new MessageEvent("message", { data: { source: PICKER_SOURCE, type: "select", path: [0, 0] }, source: window }));
    });
    expect(screen.getAllByTestId("design-layer")[2]!.getAttribute("aria-selected")).toBe("true");
  });

  it("writes a block's colour as a theme token", async () => {
    open();
    fireEvent.click(screen.getAllByTestId("design-layer")[1]!);
    fireEvent.click(screen.getByTestId("design-color"));
    fireEvent.click(screen.getByRole("button", { name: "accent" }));
    await waitFor(() => expect(puts.length).toBeGreaterThan(0), { timeout: 3000 });
    expect(lastHtml()).toContain('<h1 style="color: var(--accent);">Open house</h1>');
  });

  it("sets the page's accent in the spec", async () => {
    open();
    fireEvent.click(screen.getByTestId("design-accent"));
    fireEvent.click(screen.getByRole("button", { name: "green" }));
    await waitFor(() => expect(puts.length).toBeGreaterThan(0), { timeout: 3000 });
    expect(puts[puts.length - 1]!.spec.accent).toBe("green");
  });

  it("holds the save of a design emptied of every block", async () => {
    open({ html: "<h1>Only</h1>", css: "", fit: "page", background: "" });
    fireEvent.click(screen.getAllByTestId("design-layer")[0]!);
    fireEvent.click(screen.getByTestId("design-delete"));
    expect(screen.getByText("This design has no blocks yet. Add one from the toolbar.")).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId("node-editor-save-state").getAttribute("data-state")).toBe("held"), { timeout: 3000 });
    expect(puts).toHaveLength(0);
    fireEvent.click(screen.getByTestId("node-editor-undo"));
    expect(rows()).toEqual(["Only"]);
  });

  it("shows a picture's inspector with replace and description", () => {
    open({ html: '<img src="data:image/png;base64,AAAA" alt="Logo">', css: "", fit: "page", background: "" });
    fireEvent.click(screen.getAllByTestId("design-layer")[0]!);
    const inspector = screen.getByTestId("design-element-inspector");
    expect(within(inspector).getByRole("button", { name: "Replace picture…" })).toBeTruthy();
    const alt = within(inspector).getByLabelText("Description") as HTMLInputElement;
    expect(alt.value).toBe("Logo");
  });
});
