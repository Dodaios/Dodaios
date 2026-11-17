/**
 * The deck editor as a presentation program: inserting text boxes, shapes,
 * lines and tables; selecting, moving, nudging, duplicating, deleting and
 * ordering them; formatting from the format bar and the inspector; slide
 * backgrounds and hidden slides; the deck's ready-made looks; and the
 * presenter view.
 *
 * The server is a stand-in `fetch`, as in `SlidesEditor.test.tsx`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { NodeCard } from "../../nodeModel";
import { resetDeckPageCache } from "./deckPage";
import SlidesEditor from "./index";

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
  id: "deck02",
  type: "slides",
  origin: "node",
  title: "Elements deck",
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

type Spec = { theme?: string; font?: string; background?: unknown; slides: Record<string, unknown>[] };

const SPEC: Spec = {
  theme: "auto",
  slides: [
    {
      layout: "blank",
      elements: [
        { id: "a", type: "shape", shape: "rect", x: 100, y: 100, w: 200, h: 100, text: "Box" },
        { id: "b", type: "text", x: 500, y: 400, w: 300, h: 80, text: "Hello" },
      ],
    },
    { layout: "title", title: "Second" },
  ],
};

let calls: { url: string; method: string; body: { spec: Spec } }[] = [];

beforeEach(() => {
  calls = [];
  resetDeckPageCache();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : { spec: { slides: [] } };
      calls.push({ url, method, body });
      if (url.endsWith("/preview")) {
        const html = `<!doctype html><html><head><style>:root{--bg:#fff}.sl{position:absolute}</style></head><body><div class="el-chart"><svg data-figure="1"></svg></div></body></html>`;
        return { ok: true, status: 200, text: async () => html, json: async () => ({}) };
      }
      return { ok: true, status: 200, json: async () => ({ version: 4, updated_at: 300, spec: body.spec }), text: async () => "" };
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function open(spec: Spec = SPEC) {
  const view = render(<SlidesEditor node={NODE} initial={{ spec, version: 3, updated_at: 2 }} onDone={() => {}} />);
  await screen.findByTestId("slides-canvas");
  return view;
}

function shadow(): ShadowRoot {
  return screen.getByTestId("slides-canvas").shadowRoot!;
}

function el(index: number): HTMLElement {
  const found = shadow().querySelector<HTMLElement>(`[data-el="${index}"]`);
  if (!found) throw new Error(`no element ${index}`);
  return found;
}

function surface(): HTMLElement {
  return screen.getByTestId("slides-canvas-editor");
}

/** Press on an element of the slide (and let go, unless `hold`). */
function press(index: number, init: PointerEventInit = {}) {
  fireEvent.pointerDown(el(index), { button: 0, pointerId: 1, clientX: 10, clientY: 10, ...init });
  fireEvent.pointerUp(surface(), { pointerId: 1 });
}

async function saved(): Promise<Spec> {
  let spec: Spec | undefined;
  await waitFor(
    () => {
      const put = [...calls].reverse().find((call) => call.method === "PUT");
      expect(put).toBeTruthy();
      spec = put!.body.spec;
    },
    { timeout: 3000 },
  );
  return spec!;
}

describe("inserting elements", () => {
  it("inserts a text box ready to type and saves its words", async () => {
    await open();
    fireEvent.click(screen.getByTestId("slides-insert-text"));
    const box = el(2);
    expect(box.className).toContain("el-text");
    const writing = box.querySelector<HTMLElement>("[data-el-text]")!;
    expect(writing.getAttribute("contenteditable")).toBe("plaintext-only");
    writing.textContent = "Typed words";
    fireEvent.input(writing);
    expect(screen.getByTestId("slides-element-kind").textContent).toBe("Text box");
    await waitFor(async () => {
      const spec = await saved();
      expect((spec.slides[0].elements as { text?: string }[])[2].text).toBe("Typed words");
    });
  });

  it("drops a text box that was left empty", async () => {
    await open();
    fireEvent.click(screen.getByTestId("slides-insert-text"));
    const writing = el(2).querySelector<HTMLElement>("[data-el-text]")!;
    act(() => writing.blur());
    await waitFor(() => expect(shadow().querySelector('[data-el="2"]')).toBeNull());
  });

  it("inserts a shape of a picked kind, a line and a table", async () => {
    await open();
    fireEvent.click(screen.getByTestId("slides-insert-shape"));
    fireEvent.click(screen.getByTestId("slides-insert-shape-star"));
    expect(el(2).className).toContain("is-star");
    fireEvent.click(screen.getByTestId("slides-insert-line"));
    fireEvent.click(screen.getByTestId("slides-insert-line-arrow"));
    expect(el(3).className).toContain("el-line");
    expect(el(3).querySelector("polygon")).not.toBeNull();
    fireEvent.click(screen.getByTestId("slides-insert-table"));
    expect(el(4).querySelector("table.el-table")).not.toBeNull();
    const spec = await saved();
    const kinds = (spec.slides[0].elements as { type: string }[]).map((e) => e.type);
    expect(kinds).toEqual(["shape", "text", "shape", "line", "table"]);
  });
});

describe("selecting and changing elements", () => {
  it("selects an element with a click and shows its format", async () => {
    await open();
    press(0);
    expect(screen.getByTestId("slides-selection")).toBeTruthy();
    expect(screen.getByTestId("slides-element-kind").textContent).toBe("Shape");
    expect(screen.getByTestId("slides-format-bar")).toBeTruthy();
  });

  it("moves an element by dragging it, as one undo step", async () => {
    await open();
    fireEvent.pointerDown(el(0), { button: 0, pointerId: 1, clientX: 100, clientY: 100 });
    // The canvas is 960 px wide here: 75 screen px are 100 slide px.
    fireEvent.pointerMove(surface(), { pointerId: 1, clientX: 140, clientY: 100 });
    fireEvent.pointerMove(surface(), { pointerId: 1, clientX: 175, clientY: 137.5 });
    fireEvent.pointerUp(surface(), { pointerId: 1 });
    expect(el(0).style.left).toBe("200px");
    expect(el(0).style.top).toBe("150px");
    fireEvent.click(screen.getByRole("button", { name: /undo/i }));
    expect(el(0).style.left).toBe("100px");
  });

  it("nudges, duplicates and deletes the selection with the keys", async () => {
    await open();
    press(1);
    fireEvent.keyDown(surface(), { key: "ArrowRight", shiftKey: true });
    expect(el(1).style.left).toBe("510px");
    fireEvent.keyDown(surface(), { key: "d", ctrlKey: true });
    expect(el(2).style.left).toBe("534px");
    fireEvent.keyDown(surface(), { key: "Delete" });
    expect(shadow().querySelector('[data-el="2"]')).toBeNull();
    const spec = await saved();
    expect((spec.slides[0].elements as unknown[]).length).toBe(2);
  });

  it("formats a text from the format bar", async () => {
    await open();
    press(1);
    fireEvent.click(screen.getByTestId("slides-bar-bold"));
    fireEvent.click(screen.getByTestId("slides-bar-bigger"));
    fireEvent.click(screen.getByTestId("slides-bar-bullets"));
    const text = el(1).querySelector(".el-t")!;
    expect(text.className).toContain("is-b");
    expect((text as HTMLElement).style.fontSize).toBe("30px");
    expect(text.querySelector("ul")).not.toBeNull();
  });

  it("orders and aligns from the inspector", async () => {
    await open();
    press(0);
    fireEvent.click(screen.getByTestId("slides-order-front"));
    // The shape is drawn last now, on top.
    expect(el(1).className).toContain("el-shape");
    fireEvent.click(screen.getByTestId("slides-align-center"));
    expect(el(1).style.left).toBe("540px");
  });

  it("selects several with a frame drawn on the empty slide", async () => {
    await open();
    const stage = shadow().querySelector<HTMLElement>(".sl")!;
    fireEvent.pointerDown(stage, { button: 0, pointerId: 1, clientX: 0, clientY: 0 });
    fireEvent.pointerMove(surface(), { pointerId: 1, clientX: 900, clientY: 500 });
    fireEvent.pointerUp(surface(), { pointerId: 1 });
    expect(screen.getByTestId("slides-element-kind").textContent).toBe("2 elements");
  });

  it("copies and pastes through the right-click menu", async () => {
    await open();
    fireEvent.contextMenu(el(0), { clientX: 50, clientY: 50 });
    const menu = screen.getByTestId("slides-context-menu");
    fireEvent.click(within(menu).getByTestId("slides-menu-duplicate"));
    expect(el(2).className).toContain("el-shape");
    expect(el(2).style.left).toBe("124px");
  });
});

describe("review fixes", () => {
  it("takes a link typed letter by letter once the field is left", async () => {
    await open();
    press(0);
    const link = screen.getByTestId("slides-el-link") as HTMLInputElement;
    for (const part of ["h", "ht", "https://example.org"]) fireEvent.change(link, { target: { value: part } });
    expect(link.value).toBe("https://example.org");
    fireEvent.blur(link);
    const spec = await saved();
    expect((spec.slides[0].elements as { link?: string }[])[0].link).toBe("https://example.org");
  });

  it("leaves the slide alone while a menu of the format bar takes the arrow keys", async () => {
    await open();
    press(1);
    const before = el(1).style.left;
    fireEvent.keyDown(screen.getByTestId("slides-format-bar"), { key: "ArrowRight" });
    expect(el(1).style.left).toBe(before);
  });
});

describe("the slide and the deck", () => {
  it("hides a slide from the format bar and marks it in the strip", async () => {
    await open();
    fireEvent.click(screen.getByTestId("slides-bar-hide"));
    expect(screen.getByTestId("slides-thumb-hidden-0")).toBeTruthy();
    const spec = await saved();
    expect(spec.slides[0].hidden).toBe(true);
  });

  it("gives a slide a background colour from the inspector", async () => {
    await open();
    fireEvent.click(within(screen.getByTestId("slides-bg")).getByTestId("slides-bg-color"));
    const bg = shadow().querySelector<HTMLElement>(".sl-bg")!;
    expect(bg.style.background).toBeTruthy();
    expect(shadow().querySelector(".sl")!.getAttribute("data-tone")).toBe("dark");
  });

  it("applies a ready-made look to the whole deck", async () => {
    await open();
    fireEvent.click(screen.getByTestId("slides-design-button"));
    fireEvent.click(screen.getByTestId("slides-preset-ocean"));
    expect(shadow().querySelector(".sl")!.className).toContain("f-geometric");
    const spec = await saved();
    expect(spec.theme).toBe("dark");
    expect(spec.font).toBe("geometric");
    expect(spec.background).toEqual({ gradient: { from: "#0B1E3A", to: "#0E4C6E", angle: 160 } });
  });

  it("presents in the presenter view with the next slide and a timer", async () => {
    await open();
    fireEvent.click(screen.getByTestId("slides-present-more"));
    fireEvent.click(screen.getByTestId("slides-present-presenter-view"));
    expect(await screen.findByTestId("slides-presenter")).toBeTruthy();
    expect(screen.getByTestId("slides-presenter-timer").textContent).toMatch(/^\d\d:\d\d$/);
    fireEvent.keyDown(screen.getByTestId("slides-present"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("slides-present")).toBeNull());
  });
});
