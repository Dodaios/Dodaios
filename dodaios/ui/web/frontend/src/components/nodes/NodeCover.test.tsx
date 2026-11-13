/**
 * The cover of a library card.
 *
 * Contracts worth pinning:
 * - every type draws its own miniature from its preview, on its own hue,
 * - a preview with nothing in it (or with less than its shape promises)
 *   draws a quiet placeholder and never throws,
 * - preview text is text: markup in it shows up as characters, never as
 *   elements,
 * - a node being built shows the shimmering paper, whatever else is known,
 * - a run without a page shows the first lines of its answer on the neutral
 *   cover,
 * - an adopted file is shown as itself: a picture, a PDF sheet, a live page;
 *   the live page is a sandboxed frame that mounts only near the viewport.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { runningTime } from "./covers/typed";
import { NodeCover } from "./NodeCover";
import type { CardType, NodeCard, NodePreviewByType } from "./nodeModel";

vi.mock("@/i18n", () => ({
  useT: () => (key: string) => key,
  useUiLanguage: () => "en",
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function card(over: Partial<NodeCard> = {}): NodeCard {
  return {
    key: "run-1::index.html",
    id: "node-1",
    type: "docs",
    origin: "node",
    title: "A node",
    slug: "run-1",
    path: "index.html",
    visual_kind: "page",
    created_at: 1_794_000_000,
    updated_at: 1_794_000_600,
    size: 1024,
    version: 1,
    status: "ready",
    kept_current: false,
    refreshing: false,
    every_minutes: 0,
    request: "",
    preview: null,
    ...over,
  };
}

const SAMPLES: { [T in CardType]: NodePreviewByType[T] } = {
  docs: { heading: "Onboarding guide", lines: ["Welcome aboard", "Week one"], bullets: true },
  slides: { title: "Spring menu", subtitle: "Internal pitch", count: 12, dark: true, accent: "" },
  sheets: {
    columns: ["Item", "Price"],
    rows: [
      ["Beans", "18.40"],
      ["Milk", "1.95"],
    ],
    numeric: [false, true],
    count: 2,
  },
  design: { background: "", fit: "canvas", width: 1080, height: 1350 },
  data: {
    metrics: [
      { label: "Revenue", value: "48.2k" },
      { label: "Orders", value: "3,214" },
    ],
    bars: [0.2, 0.6, 1],
    chart: "bar",
  },
  whiteboard: {
    notes: [
      { text: "Tours on Saturdays", color: "yellow" },
      { text: "Seasonal blend", color: "pink" },
    ],
    count: 2,
  },
  motion: { title: "Spring is served", subtitle: "From March", seconds: 24, dark: true, accent: "", format: "wide" },
  output: { text: "Mostly cloudy tomorrow.\nTake a jacket." },
};

const EMPTY: { [T in CardType]: NodePreviewByType[T] } = {
  docs: { heading: "", lines: [], bullets: false },
  slides: { title: "", subtitle: "", count: 0, dark: false, accent: "" },
  sheets: { columns: [], rows: [], numeric: [], count: 0 },
  design: { background: "", fit: "page", width: 0, height: 0 },
  data: { metrics: [], bars: [], chart: "bar" },
  whiteboard: { notes: [], count: 0 },
  motion: { title: "", subtitle: "", seconds: 0, dark: true, accent: "", format: "wide" },
  output: { text: "" },
};

const TYPES = Object.keys(SAMPLES) as CardType[];

/** A text every sample shows on its cover (design shows its page, not text). */
const SHOWN: Partial<Record<CardType, string[]>> = {
  docs: ["Onboarding guide", "Welcome aboard", "Week one"],
  slides: ["Spring menu", "Internal pitch", "12"],
  sheets: ["Item", "Price", "Beans", "18.40", "1.95"],
  data: ["Revenue", "48.2k", "Orders", "3,214"],
  whiteboard: ["Tours on Saturdays", "Seasonal blend"],
  motion: ["Spring is served", "From March", "0:24"],
  output: ["Mostly cloudy tomorrow.\nTake a jacket."],
};

function renderCover(over: Partial<NodeCard>) {
  const view = render(<NodeCover card={card(over)} />);
  return { ...view, cover: screen.getByTestId("node-cover") };
}

/** Lets the live covers believe they are on screen and have a size. */
function onScreen(width = 240, height = 150) {
  class NearObserver {
    private readonly notify: (entries: { isIntersecting: boolean }[]) => void;
    constructor(notify: (entries: { isIntersecting: boolean }[]) => void) {
      this.notify = notify;
    }
    observe() {
      this.notify([{ isIntersecting: true }]);
    }
    disconnect() {}
  }
  vi.stubGlobal("IntersectionObserver", NearObserver);
  vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(width);
  vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(height);
}

describe("NodeCover: typed nodes", () => {
  it.each(TYPES)("draws the %s miniature from its preview, on its hue", (type) => {
    const { cover } = renderCover({ type, origin: type === "output" ? "run" : "node", preview: SAMPLES[type] });
    expect(cover.getAttribute("data-node-type")).toBe(type);
    expect(cover.style.getPropertyValue("--node-hue")).toBe(`var(--node-${type})`);
    expect(cover.querySelector("[data-node-paper]")).toBeTruthy();
    if (type !== "design") expect(cover.querySelector(`[data-node-mini="${type}"]`)).toBeTruthy();
    for (const text of SHOWN[type] ?? []) {
      expect(screen.getByText((_, element) => element?.textContent === text && element.children.length === 0)).toBeTruthy();
    }
  });

  it.each(TYPES)("draws a placeholder for an empty %s preview", (type) => {
    const { cover } = renderCover({ type, preview: EMPTY[type] });
    expect(cover.querySelector("[data-node-paper]")).toBeTruthy();
    expect(cover.querySelector("[data-node-bars='shimmer']")).toBeNull();
  });

  it.each(TYPES)("survives a %s preview that is missing its fields", (type) => {
    const broken = {} as NodePreviewByType[typeof type];
    const { cover } = renderCover({ type, preview: broken });
    expect(cover.querySelector("[data-node-paper]")).toBeTruthy();
  });

  it("renders preview text as text, never as markup", () => {
    const markup = "<script>alert(1)</script>";
    const image = '<img src=x onerror="alert(2)">';
    const { cover } = renderCover({
      type: "docs",
      preview: { heading: markup, lines: [image, "<b>bold</b>"], bullets: false },
    });
    expect(cover.querySelector("script")).toBeNull();
    expect(cover.querySelector("img")).toBeNull();
    expect(cover.querySelector("b")).toBeNull();
    expect(screen.getByText(markup)).toBeTruthy();
    expect(screen.getByText(image)).toBeTruthy();
  });

  it("renders markup in a note, a cell, a slide and an answer as text too", () => {
    const markup = "<script>alert(1)</script>";
    for (const [type, preview] of [
      ["whiteboard", { notes: [{ text: markup, color: "yellow" }], count: 1 }],
      ["sheets", { columns: [markup], rows: [], numeric: [], count: 0 }],
      ["slides", { title: markup, subtitle: "", count: 1, dark: false, accent: "" }],
      ["output", { text: markup }],
    ] as [CardType, NodePreviewByType[CardType]][]) {
      const { cover, unmount } = renderCover({ type, preview });
      expect(cover.querySelector("script")).toBeNull();
      expect(screen.getByText(markup)).toBeTruthy();
      unmount();
    }
  });

  it("right-aligns the numeric columns of a sheet and shows three rows at most", () => {
    const { cover } = renderCover({
      type: "sheets",
      preview: {
        columns: ["Item", "Price"],
        rows: [["a", "1"], ["b", "2"], ["c", "3"], ["d", "4"]],
        numeric: [false, true],
        count: 4,
      },
    });
    const columns = Array.from(cover.querySelectorAll("[data-node-mini='sheets'] > div"));
    expect(columns).toHaveLength(2);
    expect(columns[0].className).not.toContain("text-right");
    expect(columns[1].className).toContain("text-right");
    expect(columns[1].className).toContain("tabular-nums");
    expect(screen.queryByText("c")).toBeTruthy();
    expect(screen.queryByText("d")).toBeNull();
  });

  it("draws a line for a line chart and bars otherwise", () => {
    const line = renderCover({ type: "data", preview: { metrics: [], bars: [0.1, 0.5, 0.9], chart: "line" } });
    expect(line.cover.querySelector("[data-node-chart='line'] polyline")).toBeTruthy();
    line.unmount();
    const bars = renderCover({ type: "data", preview: { metrics: [], bars: [0.1, 0.5, 0.9], chart: "bar" } });
    expect(bars.cover.querySelectorAll("[data-node-chart='bar'] > span")).toHaveLength(3);
  });

  it("shows four notes at most, each on its own paper color", () => {
    const { cover } = renderCover({
      type: "whiteboard",
      preview: {
        notes: [
          { text: "one", color: "yellow" },
          { text: "two", color: "pink" },
          { text: "three", color: "blue" },
          { text: "four", color: "green" },
          { text: "five", color: "violet" },
        ],
        count: 5,
      },
    });
    const notes = Array.from(cover.querySelectorAll("[data-node-note]"));
    expect(notes.map((note) => note.getAttribute("data-node-note"))).toEqual(["yellow", "pink", "blue", "green"]);
    expect(screen.queryByText("five")).toBeNull();
  });

  it("leaves the count and the duration off when there is none", () => {
    const deck = renderCover({ type: "slides", preview: { ...SAMPLES.slides, count: 0 } });
    expect(deck.cover.querySelector("[data-testid='node-cover-count']")).toBeNull();
    deck.unmount();
    const film = renderCover({ type: "motion", preview: { ...SAMPLES.motion, seconds: 0 } });
    expect(film.cover.querySelector("[data-testid='node-cover-duration']")).toBeNull();
    expect(film.cover.querySelector("[data-node-play]")).toBeTruthy();
  });

  it("writes a running time as minutes and seconds", () => {
    expect(runningTime(24)).toBe("0:24");
    expect(runningTime(95)).toBe("1:35");
    expect(runningTime(600)).toBe("10:00");
    expect(runningTime(-3)).toBe("0:00");
  });
});

describe("NodeCover: building and output", () => {
  it("shows the shimmering paper for a page still being built", () => {
    const { cover } = renderCover({ origin: "build", status: "building", path: null, visual_kind: null, id: null });
    expect(cover.querySelector("[data-node-mini='building']")).toBeTruthy();
    expect(cover.querySelector("[data-node-bars='shimmer']")).toBeTruthy();
  });

  it("shows the shimmering paper for a typed node that is building, not its old preview", () => {
    const { cover } = renderCover({ type: "slides", status: "building", preview: SAMPLES.slides });
    expect(cover.querySelector("[data-node-bars='shimmer']")).toBeTruthy();
    expect(screen.queryByText("Spring menu")).toBeNull();
    expect(cover.style.getPropertyValue("--node-hue")).toBe("var(--node-slides)");
  });

  it("shows the first lines of a run's answer on the neutral cover", () => {
    const { cover } = renderCover({
      type: "output",
      origin: "run",
      id: null,
      path: null,
      visual_kind: null,
      preview: { text: "First line\nSecond line" },
    });
    expect(cover.getAttribute("data-node-type")).toBe("output");
    expect(cover.style.getPropertyValue("--node-hue")).toBe("var(--node-output)");
    expect(cover.querySelector("[data-node-mini='output']")?.textContent).toBe("First line\nSecond line");
  });

  it("draws quiet bars for a run without a preview", () => {
    const { cover } = renderCover({ type: "output", origin: "run", id: null, path: null, visual_kind: null, preview: null });
    expect(cover.querySelector("[data-node-mini='output'] [data-node-bars='still']")).toBeTruthy();
  });

  it("falls back to the neutral hue for a type it does not know", () => {
    const { cover } = renderCover({ type: "hologram" as CardType, preview: { text: "x" } });
    expect(cover.getAttribute("data-node-type")).toBe("hologram");
    expect(cover.style.getPropertyValue("--node-hue")).toBe("var(--node-output)");
    expect(cover.querySelector("[data-node-paper]")).toBeTruthy();
  });

  it("passes its className on to the cover", () => {
    const view = render(<NodeCover card={card()} className="rounded-t-xl" />);
    expect(view.getByTestId("node-cover").className).toContain("rounded-t-xl");
  });
});

describe("NodeCover: adopted files", () => {
  it("shows a picture as the picture itself, filling the cover", () => {
    const { cover } = renderCover({ origin: "file", id: null, visual_kind: "image", path: "shots/photo one.png" });
    const picture = cover.querySelector("img");
    expect(picture?.getAttribute("src")).toBe(
      "/api/outputs/run-1/files/shots/photo%20one.png/download?disposition=inline",
    );
    expect(picture?.className).toContain("object-cover");
    expect(cover.querySelector("[data-node-paper]")).toBeNull();
  });

  it("shows a vector whole", () => {
    const { cover } = renderCover({ origin: "file", id: null, visual_kind: "vector", path: "logo.svg" });
    expect(cover.querySelector("img")?.className).toContain("object-contain");
  });

  it("shows a PDF as a sheet with its tag", () => {
    const { cover } = renderCover({ origin: "file", id: null, visual_kind: "document", path: "contract.pdf" });
    expect(cover.querySelector("[data-node-mini='document'] [data-node-bars='still']")).toBeTruthy();
    expect(screen.getByText("PDF")).toBeTruthy();
    expect(cover.querySelector("iframe")).toBeNull();
  });

  it("keeps a page a quiet paper until its card is near the viewport", () => {
    const { cover } = renderCover({ origin: "page", id: null, visual_kind: "page", path: "site/index.html" });
    expect(cover.querySelector("iframe")).toBeNull();
    expect(cover.querySelector("[data-node-paper] [data-node-bars='still']")).toBeTruthy();
  });

  it("mounts a page near the viewport as an inert, sandboxed frame", () => {
    onScreen();
    renderCover({ origin: "page", id: null, visual_kind: "page", path: "site/index.html", title: "Menu" });
    const frame = screen.getByTestId("node-cover-frame");
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame.getAttribute("src")).toMatch(/^\/api\/outputs\/run-1\/files\/site\/index\.html\/page\?theme=(light|dark)$/);
    expect(frame.getAttribute("tabindex")).toBe("-1");
    expect(frame.className).toContain("pointer-events-none");
    expect(frame.getAttribute("title")).toBe("Menu");
  });

  it("lays a design canvas out at its own size, scaled into its frame", () => {
    onScreen(108, 135);
    renderCover({ type: "design", preview: SAMPLES.design });
    const frame = screen.getByTestId("node-cover-frame") as HTMLIFrameElement;
    expect(frame.style.width).toBe("1080px");
    expect(frame.style.height).toBe("1350px");
    expect(frame.style.transform).toBe("scale(0.1)");
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
  });

  it("draws a paper for a design node that has no file yet", () => {
    onScreen();
    const { cover } = renderCover({ type: "design", path: null, preview: SAMPLES.design });
    expect(cover.querySelector("iframe")).toBeNull();
    expect(cover.querySelector("[data-node-mini='placeholder']")).toBeTruthy();
  });
});
