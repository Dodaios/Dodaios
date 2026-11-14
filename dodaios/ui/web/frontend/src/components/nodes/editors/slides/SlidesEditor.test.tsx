/**
 * The deck editor as a whole: the strip's actions (add with a layout,
 * duplicate, delete, move by keys and by dragging), a layout switch that
 * carries the content, the inspector and the canvas writing into one undo
 * history, a chart slide drawn by the server and edited in the chart editor,
 * saving, presenting, and undo following the slide it changes.
 *
 * The server is a stand-in `fetch`: the preview route answers with a tiny
 * stylesheet (and a figure for a chart), the spec route saves.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { NodeCard } from "../../nodeModel";
import { resetDeckPageCache } from "./deckPage";
import SlidesEditor from "./index";

// jsdom has no PointerEvent; a mouse event with a pointer id carries what the strip reads.
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
  id: "deck01",
  type: "slides",
  origin: "node",
  title: "Q3 deck",
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
  theme: "auto",
  slides: [
    { layout: "title", title: "Q3 review", subtitle: "Numbers" },
    { layout: "bullets", title: "Plan", bullets: ["One", "Two"] },
    { layout: "chart", title: "Revenue", chart: { type: "column", x: ["Jul", "Aug"], series: [{ name: "R", data: [1, 2] }] } },
    { layout: "closing", title: "Thanks" },
  ],
};

interface Call {
  url: string;
  method: string;
  body: { spec: { slides?: { layout: string; chart?: { type: string } }[]; theme?: string } };
}

let calls: Call[] = [];

beforeEach(() => {
  calls = [];
  resetDeckPageCache();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body = init?.body ? (JSON.parse(String(init.body)) as Call["body"]) : { spec: {} };
      calls.push({ url, method, body });
      if (url.endsWith("/preview")) {
        const first = body.spec.slides?.[0];
        const figure = first?.layout === "chart" ? `<svg data-figure="${first.chart?.type}"></svg>` : "";
        const html = `<!doctype html><html><head><style>:root{--bg:#fff}.sl{position:absolute}</style></head><body><div class="sl-plot">${figure}</div></body></html>`;
        return { ok: true, status: 200, text: async () => html, json: async () => ({}) };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ version: 4, updated_at: 300, spec: body.spec }),
        text: async () => "",
      };
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function open() {
  const view = render(<SlidesEditor node={NODE} initial={{ spec: SPEC, version: 3, updated_at: 2 }} onDone={() => {}} />);
  await screen.findByTestId("slides-canvas");
  return view;
}

function canvas(): ShadowRoot {
  return screen.getByTestId("slides-canvas").shadowRoot!;
}

function field(key: string): HTMLElement {
  const el = canvas().querySelector<HTMLElement>(`[data-field="${key}"]`);
  if (!el) throw new Error(`no field ${key}`);
  return el;
}

function thumbs(): HTMLElement[] {
  return within(screen.getByTestId("slides-strip")).getAllByRole("option");
}

function names(): string[] {
  return thumbs().map((thumb) => thumb.getAttribute("aria-label") ?? "");
}

function undoButton(): HTMLButtonElement {
  return screen.getByTestId("node-editor-undo") as HTMLButtonElement;
}

describe("SlidesEditor", () => {
  it("shows every slide in the strip and the selected one on the canvas", async () => {
    await open();
    expect(names()).toEqual(["Slide 1: Q3 review", "Slide 2: Plan", "Slide 3: Revenue", "Slide 4: Thanks"]);
    expect(field("title").textContent).toBe("Q3 review");
    fireEvent.click(thumbs()[1]);
    expect(thumbs()[1].getAttribute("aria-selected")).toBe("true");
    expect(field("title").textContent).toBe("Plan");
    expect(field("bullets/1").textContent).toBe("Two");
  });

  it("adds a slide of a picked layout after the selected one, ready to type, as one undo step", async () => {
    await open();
    fireEvent.click(screen.getByTestId("slides-add"));
    fireEvent.click(within(screen.getByTestId("slides-layout-picker")).getByRole("button", { name: "Steps" }));
    expect(thumbs()).toHaveLength(5);
    expect(thumbs()[1].getAttribute("aria-selected")).toBe("true");
    expect(canvas().querySelectorAll(".sl-steps li")).toHaveLength(3);
    await waitFor(() => expect(canvas().activeElement?.getAttribute("data-field")).toBe("title"));
    expect(undoButton().getAttribute("aria-label")).toContain("New slide");
    fireEvent.click(undoButton());
    expect(thumbs()).toHaveLength(4);
  });

  it("duplicates, deletes and moves the selected slide with the keyboard", async () => {
    await open();
    const strip = () => thumbs();
    fireEvent.keyDown(strip()[1], { key: "d", metaKey: true });
    expect(names()).toEqual(["Slide 1: Q3 review", "Slide 2: Plan", "Slide 3: Plan", "Slide 4: Revenue", "Slide 5: Thanks"]);
    fireEvent.keyDown(strip()[2], { key: "Delete" });
    expect(names()).toHaveLength(4);
    fireEvent.keyDown(strip()[1], { key: "ArrowDown", altKey: true });
    expect(names()).toEqual(["Slide 1: Q3 review", "Slide 2: Revenue", "Slide 3: Plan", "Slide 4: Thanks"]);
    expect(strip()[2].getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("Slide 2 moved to position 3.")).toBeTruthy();
    // Arrow keys move the selection; the last slide cannot be deleted below one.
    fireEvent.keyDown(strip()[2], { key: "End" });
    expect(strip()[3].getAttribute("aria-selected")).toBe("true");
  });

  it("reorders slides by dragging a thumbnail", async () => {
    await open();
    thumbs().forEach((thumb, index) => {
      thumb.getBoundingClientRect = () => ({ top: index * 100, height: 100, bottom: index * 100 + 100, left: 0, right: 200, width: 200, x: 0, y: index * 100, toJSON: () => ({}) });
    });
    const list = screen.getByRole("listbox");
    fireEvent.pointerDown(thumbs()[0], { button: 0, clientY: 50, pointerId: 1 });
    fireEvent.pointerMove(list, { clientY: 120, pointerId: 1 });
    fireEvent.pointerMove(list, { clientY: 260, pointerId: 1 });
    fireEvent.pointerUp(list, { clientY: 260, pointerId: 1 });
    expect(names()).toEqual(["Slide 1: Plan", "Slide 2: Revenue", "Slide 3: Q3 review", "Slide 4: Thanks"]);
    expect(thumbs()[2].getAttribute("aria-selected")).toBe("true");
    fireEvent.click(undoButton());
    expect(names()[0]).toBe("Slide 1: Q3 review");
  });

  it("switches a slide's layout from the inspector and carries its points over", async () => {
    await open();
    fireEvent.click(thumbs()[1]);
    fireEvent.click(screen.getByTestId("slides-layout-button"));
    fireEvent.click(within(screen.getByTestId("slides-layout-picker")).getByRole("button", { name: "Steps" }));
    const steps = Array.from(canvas().querySelectorAll(".sl-steps h3")).map((h) => h.textContent);
    expect(steps).toEqual(["One", "Two"]);
    expect(field("title").textContent).toBe("Plan");
    fireEvent.click(undoButton());
    expect(canvas().querySelector(".sl-list")).toBeTruthy();
  });

  it("writes the same text from the inspector and the canvas, one undo step per typing run", async () => {
    await open();
    const input = screen.getByTestId("slides-field-title") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "Q3 in" } });
    fireEvent.change(input, { target: { value: "Q3 in review" } });
    expect(field("title").textContent).toBe("Q3 in review");
    fireEvent.click(undoButton());
    expect(field("title").textContent).toBe("Q3 review");
    expect(input.value).toBe("Q3 review");

    const title = field("title");
    act(() => title.focus());
    title.textContent = "Typed here";
    fireEvent.input(title);
    expect(input.value).toBe("Typed here");
    // Undo from inside the slide's field is the deck's undo.
    fireEvent.keyDown(title, { key: "z", metaKey: true });
    expect(input.value).toBe("Q3 review");
    expect(title.textContent).toBe("Q3 review");
  });

  it("adds points with Enter on the canvas and with the inspector", async () => {
    await open();
    fireEvent.click(thumbs()[1]);
    fireEvent.keyDown(field("bullets/1"), { key: "Enter" });
    expect(canvas().querySelectorAll(".sl-list li")).toHaveLength(3);
    await waitFor(() => expect(canvas().activeElement?.getAttribute("data-field")).toBe("bullets/2"));
    fireEvent.click(screen.getByTestId("slides-add-bullet"));
    expect(canvas().querySelectorAll(".sl-list li")).toHaveLength(4);
    fireEvent.click(screen.getByRole("button", { name: "Remove Point 4" }));
    expect(canvas().querySelectorAll(".sl-list li")).toHaveLength(3);
  });

  it("draws a chart slide's figure from the server and edits the chart in the chart editor", async () => {
    await open();
    fireEvent.click(thumbs()[2]);
    await waitFor(() => expect(canvas().querySelector('.sl-plot svg[data-figure="column"]')).toBeTruthy());
    fireEvent.click(screen.getByTestId("slides-edit-chart"));
    const editor = await screen.findByTestId("chart-editor");
    fireEvent.click(within(editor).getByTestId("chart-kind-line"));
    fireEvent.click(screen.getByTestId("chart-save"));
    await waitFor(() => expect(canvas().querySelector('.sl-plot svg[data-figure="line"]')).toBeTruthy());
    expect(undoButton().getAttribute("aria-label")).toContain("Edit chart");
    const asked = calls.filter((call) => call.url.endsWith("/preview")).map((call) => call.body.spec.slides?.[0].chart?.type);
    expect(asked).toContain("line");
  });

  it("saves the deck shortly after a change", async () => {
    await open();
    fireEvent.click(screen.getByTestId("slides-theme"));
    fireEvent.click(screen.getByTestId("slides-theme-dark"));
    expect(screen.getByTestId("slides-canvas").getAttribute("data-theme")).toBe("dark");
    await waitFor(
      () => {
        const put = calls.find((call) => call.method === "PUT");
        expect(put?.body.spec.theme).toBe("dark");
      },
      { timeout: 3000 },
    );
  });

  it("presents from the selected slide and returns to the slide it ended on", async () => {
    await open();
    fireEvent.click(thumbs()[1]);
    fireEvent.click(screen.getByTestId("slides-present-button"));
    const stage = screen.getByTestId("slides-present");
    expect(within(stage).getByText("2 / 4")).toBeTruthy();
    fireEvent.keyDown(stage, { key: "ArrowRight" });
    expect(within(stage).getByText("3 / 4")).toBeTruthy();
    fireEvent.keyDown(stage, { key: "n" });
    expect(screen.getByTestId("slides-present-notes").textContent).toContain("No notes");
    fireEvent.keyDown(stage, { key: "Escape" });
    expect(screen.queryByTestId("slides-present")).toBeNull();
    expect(thumbs()[2].getAttribute("aria-selected")).toBe("true");
  });

  it("selects the slide an undo changes", async () => {
    await open();
    fireEvent.click(thumbs()[1]);
    fireEvent.change(screen.getByTestId("slides-field-title"), { target: { value: "Plan B" } });
    fireEvent.click(thumbs()[3]);
    fireEvent.click(undoButton());
    expect(thumbs()[1].getAttribute("aria-selected")).toBe("true");
    expect(field("title").textContent).toBe("Plan");
  });

  it("keeps speaker notes per slide", async () => {
    await open();
    const notes = screen.getByTestId("slides-notes") as HTMLTextAreaElement;
    fireEvent.change(notes, { target: { value: "Open with the headline." } });
    fireEvent.click(thumbs()[1]);
    expect((screen.getByTestId("slides-notes") as HTMLTextAreaElement).value).toBe("");
    fireEvent.click(thumbs()[0]);
    expect((screen.getByTestId("slides-notes") as HTMLTextAreaElement).value).toBe("Open with the headline.");
  });
});
