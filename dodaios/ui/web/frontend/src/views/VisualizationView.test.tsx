/**
 * The Nodes section — the library of everything the assistant made and
 * keeps, and the stage a card opens on, full-size.
 *
 * Contracts worth pinning:
 * - the section opens on the library (`/api/nodes`): a card per node, a page
 *   named by its own <title>; a click opens it on the stage, back returns,
 *   previous / next walk the library in the order it shows,
 * - a card can be starred in the library and on the stage, and the starred
 *   ones are what Favorites shows; the same cards are a list one toggle away,
 * - a PAGE is framed from `/page` with `sandbox="allow-scripts"` and no
 *   same-origin (its scripts run, the app stays out of reach); an image goes
 *   through <img>; a PDF through a frame without a sandbox, because the
 *   browser's PDF viewer is a plugin and never loads inside one,
 * - "Code" shows the page's source, "Run" the node graph of the run that made
 *   it — the graph is one tab away, never in front of the page,
 * - a `create_artifact` mission still running shows as a "building" card and
 *   stage, recognised by the brief's "Artifact:" lead line,
 * - a typed node is watched while it is open: when the assistant revised it,
 *   its frame loads again; only a typed node offers "ask for a change",
 * - a node started empty from the new-row opens before the library lists it,
 * - `?run=<slug>` opens that run's artifact straight away,
 * - only files the WebView can draw are offered (`classifyVisual`).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { SectionStage } from "@/App";
import { nodesResponse, typedNodeCard } from "@/components/nodes/testCards";
import type { NodeCard } from "@/components/nodes/nodeModel";
import type { NodeState } from "@/components/nodes/useNodes";
import { parseArtifactUtterance } from "@/components/visualization/galleryModel";
import { VisualizationView } from "@/views/VisualizationView";
import {
  classifyVisual,
  pageTitleFromPreview,
  visualUrl,
} from "@/hooks/useVisualArtifacts";
import type {
  ArtifactSummary,
  OutputSummary,
  PlanResponse,
} from "@/hooks/useOutputs";

// ViewHeader lives in ChatsView, which subscribes to a WS client on mount —
// null keeps that a deterministic no-op in jsdom.
vi.mock("@/hooks/useWebSocket", () => ({
  getWSClient: () => null,
}));

// "Ask for a change" opens the lead conversation with a draft; the section
// only has to hand it the node.
const chat = vi.hoisted(() => ({
  requestNewNode: vi.fn(async () => undefined),
  askDodaiosToChange: vi.fn(async (_card: unknown) => undefined),
  sendNodeComments: vi.fn(async (_card: unknown, _comments: unknown) => undefined),
}));
vi.mock("@/components/nodes/askDodaios", () => chat);

beforeEach(() => {
  // The library remembers its tab, order and view, and the stars.
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

interface ServerOptions {
  plansBySlug?: Record<string, PlanResponse>;
  rawBySlug?: Record<string, string>;
  capabilities?: Record<string, unknown>;
  /** Typed nodes the library lists besides what it adopts from the runs. */
  typed?: NodeCard[];
  /** What `/api/nodes/by-slug/{slug}` answers; read on every request. */
  nodeStates?: Record<string, NodeState>;
  /** The starter node `POST /api/nodes` creates. */
  created?: NodeCard;
}

function installFetchMock(
  runs: OutputSummary[],
  artifactsBySlug: Record<string, ArtifactSummary[]>,
  options: ServerOptions = {},
) {
  const {
    plansBySlug = {},
    rawBySlug = {},
    capabilities = { native_file_actions: false, platform: "linux" },
  } = options;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/nodes") {
      // The library: the typed nodes, and what the server adopts from the runs.
      const body =
        init?.method === "POST" ? options.created : nodesResponse(runs, artifactsBySlug, options.typed);
      return { ok: true, status: 200, json: async () => body ?? {} };
    }
    const bySlug = /^\/api\/nodes\/by-slug\/([^/?]+)/.exec(url);
    if (bySlug) {
      const state = options.nodeStates?.[decodeURIComponent(bySlug[1])];
      return state
        ? { ok: true, status: 200, json: async () => state }
        : { ok: false, status: 404, json: async () => ({ detail: "unknown" }) };
    }
    if (url.includes("/capabilities")) {
      return { ok: true, status: 200, json: async () => capabilities };
    }
    if (url.endsWith("/share") && init?.method === "POST") {
      const body = JSON.parse(String(init.body)) as { format: string; title: string };
      const name = `${body.title}.${body.format === "file" ? "html" : body.format}`;
      return {
        ok: true,
        status: 200,
        json: async () => ({
          name,
          url: `/api/outputs/shared/abc/${encodeURIComponent(name)}`,
          path: `/tmp/dodaios-share/abc/${name}`,
        }),
      };
    }
    const plan = /\/api\/outputs\/([^/]+)\/plan/.exec(url);
    if (plan) {
      const slug = decodeURIComponent(plan[1]);
      return {
        ok: true,
        status: 200,
        json: async () => plansBySlug[slug] ?? { plan: null, steps: [] },
      };
    }
    const raw = /\/api\/outputs\/([^/]+)\/files\/.+\/raw/.exec(url);
    if (raw) {
      const slug = decodeURIComponent(raw[1]);
      return {
        ok: true,
        status: 200,
        json: async () => ({
          path: "x",
          size: 1,
          text: rawBySlug[slug] ?? "",
          truncated: false,
        }),
      };
    }
    const artifacts = /\/api\/outputs\/([^/]+)\/artifacts/.exec(url);
    if (artifacts) {
      const slug = decodeURIComponent(artifacts[1]);
      return {
        ok: true,
        status: 200,
        json: async () => ({ files: artifactsBySlug[slug] ?? [] }),
      };
    }
    if (url.includes("/api/outputs")) {
      return { ok: true, status: 200, json: async () => ({ sessions: runs }) };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Previous / next, the views and the file actions live behind "More". */
function openMore() {
  fireEvent.click(screen.getByTestId("visualization-more"));
}

function renderView() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <VisualizationView />
    </QueryClientProvider>,
  );
  return { ...view, client };
}

/** The library's cards as shown, by key. */
function cardKeys(): Array<string | null> {
  return screen.queryAllByTestId("node-card").map((card) => card.getAttribute("data-node-key"));
}

/** One card of the library, once the library shows it. */
function findCard(key: string): Promise<HTMLElement> {
  return waitFor(() => {
    const card = screen.queryAllByTestId("node-card").find((el) => el.getAttribute("data-node-key") === key);
    if (!card) throw new Error(`no card ${key} among ${cardKeys().join(", ")}`);
    return card;
  });
}

/** Open the card that leads the library. */
async function openFirstCard() {
  fireEvent.click((await screen.findAllByTestId("node-card"))[0]);
}

function stageTitle(): string | null {
  return screen.getByTestId("visualization-title").textContent;
}

function file(path: string, over: Partial<ArtifactSummary> = {}): ArtifactSummary {
  return {
    path,
    size: 2048,
    mtime: 1_700_000_000,
    is_text: false,
    preview: null,
    ...over,
  };
}

const DASH_HTML =
  "<!doctype html><html><head><title>Umsatz-Dashboard</title></head>" +
  "<body><script>document.title='x'</script></body></html>";

const ARTIFACT_UTTERANCE =
  "Artifact: Umsatz-Dashboard\nUmsatz pro Monat 2026 als Balken.\n\n## What to build\n…";

const DASH_RUN: OutputSummary = {
  slug: "mission_dash",
  utterance: ARTIFACT_UTTERANCE,
  status: "success",
};

const DASH_FILE = file("tasks/t1/artifacts/files/umsatz-dashboard.html", {
  is_text: true,
  preview: DASH_HTML,
  mtime: 1_700_000_900,
});

describe("classifyVisual", () => {
  it("accepts what the WebView can draw", () => {
    expect(classifyVisual("a/b/chart.PNG")).toBe("image");
    expect(classifyVisual("x.svg")).toBe("vector");
    expect(classifyVisual("report.html")).toBe("page");
    expect(classifyVisual("deck.pdf")).toBe("document");
  });

  it("rejects everything else, however data-shaped", () => {
    expect(classifyVisual("data.json")).toBeNull();
    expect(classifyVisual("notes.md")).toBeNull();
    expect(classifyVisual("archive.zip")).toBeNull();
    expect(classifyVisual("noext")).toBeNull();
  });

  it("encodes each path segment, so '#' in a filename survives", () => {
    expect(visualUrl("run-1", "tasks/t/artifacts/files/chart#2.png")).toContain(
      "chart%232.png",
    );
  });
});

describe("pageTitleFromPreview", () => {
  it("reads a page's own title and decodes the common entities", () => {
    expect(pageTitleFromPreview(DASH_HTML)).toBe("Umsatz-Dashboard");
    expect(pageTitleFromPreview("<title>  A &amp; B\n  </title>")).toBe("A & B");
    expect(pageTitleFromPreview("<title>&amp;lt;tag&amp;gt;</title>")).toBe("&lt;tag&gt;");
    expect(pageTitleFromPreview("<html><body>no title</body></html>")).toBeNull();
    expect(pageTitleFromPreview(null)).toBeNull();
  });
});

describe("parseArtifactUtterance", () => {
  it("recognises the brief's lead line and returns title + request", () => {
    expect(parseArtifactUtterance(ARTIFACT_UTTERANCE)).toEqual({
      title: "Umsatz-Dashboard",
      request: "Umsatz pro Monat 2026 als Balken.",
    });
    expect(parseArtifactUtterance("Build a flask app")).toBeNull();
    expect(parseArtifactUtterance(undefined)).toBeNull();
  });
});

const DASH_KEY = `mission_dash::${DASH_FILE.path}`;

/** A typed node: a run of its own on disk, and a card with an id in the library. */
const NODE = typedNodeCard("n1", {
  title: "Website brief",
  created_at: 1_700_000_000,
  updated_at: 1_700_000_000,
});
const NODE_RUN: OutputSummary = { slug: NODE.slug, utterance: "Website brief", status: "success" };
const NODE_FILES = { [NODE.slug]: [file("index.html", { is_text: true })] };

function nodeState(over: Partial<NodeState> = {}): NodeState {
  return {
    id: "n1",
    type: "docs",
    title: NODE.title,
    slug: NODE.slug,
    page_path: "index.html",
    version: 1,
    updated_at: NODE.updated_at,
    track: "",
    every_minutes: 0,
    refreshing: false,
    note: "",
    visual_id: NODE.key,
    page_url: `/api/outputs/${NODE.slug}/files/index.html/page`,
    spec: null,
    ...over,
  };
}

function frameSrc(): string {
  return screen.getByTestId("visualization-frame").getAttribute("src") ?? "";
}

describe("VisualizationView", () => {
  it("opens a card full-size on the stage, labelled by its page title", async () => {
    installFetchMock([DASH_RUN], { mission_dash: [DASH_FILE] });

    renderView();

    // The library card carries the page's title, not the filename, and a page
    // a worker built sits among the designs.
    const rows = await screen.findAllByTestId("node-card");
    expect(rows).toHaveLength(1);
    expect(rows[0].getAttribute("data-node-key")).toBe(DASH_KEY);
    expect(rows[0].textContent).toContain("Umsatz-Dashboard");
    expect(rows[0].textContent).not.toContain("umsatz-dashboard.html");
    expect(rows[0].getAttribute("data-node-type")).toBe("design");
    expect(screen.queryByTestId("visualization-frame")).toBeNull();
    fireEvent.click(rows[0]);

    const frame = await screen.findByTestId("visualization-frame");
    // The artifact-page route: scripts allowed server-side …
    expect(frame.getAttribute("src")).toContain("/files/tasks/t1/artifacts/files/umsatz-dashboard.html/page");
    // … and client-side the page runs in an opaque origin — scripts yes,
    // same-origin never.
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    // An adopted page is never rewritten: its frame carries no revision.
    expect(frame.getAttribute("src")).not.toContain("&v=");
    expect(stageTitle()).toBe("Umsatz-Dashboard");
    // The run graph is a tab away, not on stage.
    expect(screen.queryByTestId("graph-node-start")).toBeNull();
    // Back returns to the library.
    fireEvent.click(screen.getByTestId("visualization-back"));
    await screen.findAllByTestId("node-card");
    expect(screen.queryByTestId("visualization-frame")).toBeNull();
  });

  it("lists every artifact newest-first and walks them with next / previous", async () => {
    installFetchMock(
      [
        { slug: "run-a", utterance: "Draw the architecture", status: "success" },
        { slug: "run-b", utterance: "Summarise", status: "success" },
      ],
      {
        "run-a": [file("tasks/t1/artifacts/files/diagram.svg", { mtime: 1_700_000_500 })],
        "run-b": [file("tasks/t1/artifacts/files/old-chart.png", { mtime: 1_700_000_100 })],
      },
    );

    renderView();

    const rows = await screen.findAllByTestId("node-card");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("diagram.svg"),
      expect.stringContaining("old-chart.png"),
    ]);
    fireEvent.click(rows[0]);
    expect((await screen.findByTestId("visualization-image")).getAttribute("src")).toContain(
      "diagram.svg",
    );
    openMore();
    expect(screen.getByTestId("visualization-previous")).toHaveProperty("disabled", true);
    // Next moves to the older one …
    fireEvent.click(screen.getByTestId("visualization-next"));
    await waitFor(() =>
      expect(screen.getByTestId("visualization-image").getAttribute("src")).toContain(
        "old-chart.png",
      ),
    );
    // … and the arrow key walks back.
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    await waitFor(() =>
      expect(screen.getByTestId("visualization-image").getAttribute("src")).toContain(
        "diagram.svg",
      ),
    );
    // Escape returns to the library.
    fireEvent.keyDown(window, { key: "Escape" });
    await screen.findAllByTestId("node-card");
  });

  it("walks previous / next through the library in the order it shows, not the order it was listed in", async () => {
    installFetchMock(
      [
        { slug: "run-pics", utterance: "Three pictures", status: "success" },
        { slug: "run-notes", utterance: "Write notes", status: "success" },
      ],
      {
        "run-pics": [
          file("files/bravo.png", { mtime: 1_700_000_300 }),
          file("files/charlie.png", { mtime: 1_700_000_200 }),
          file("files/alpha.png", { mtime: 1_700_000_100 }),
        ],
        "run-notes": [file("files/notes.md", { is_text: true })],
      },
    );

    renderView();

    // Last changed first, as the server lists them …
    await waitFor(() =>
      expect(cardKeys()).toEqual([
        "run-pics::files/bravo.png",
        "run-pics::files/charlie.png",
        "run-pics::files/alpha.png",
      ]),
    );
    // … until the reader orders the library by name.
    fireEvent.click(screen.getByTestId("nodes-filter"));
    fireEvent.click(screen.getByTestId("nodes-sort-name"));
    expect(cardKeys()).toEqual([
      "run-pics::files/alpha.png",
      "run-pics::files/bravo.png",
      "run-pics::files/charlie.png",
    ]);

    fireEvent.click(await findCard("run-pics::files/bravo.png"));
    await waitFor(() => expect(stageTitle()).toBe("bravo.png"));
    openMore();
    // The run without a page is not on this tab, so it is not in the walk.
    expect(screen.getByRole("menu").textContent).toContain("2 of 3");
    fireEvent.click(screen.getByTestId("visualization-next"));
    await waitFor(() => expect(stageTitle()).toBe("charlie.png"));
    expect(screen.getByTestId("visualization-next")).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByTestId("visualization-previous"));
    fireEvent.click(screen.getByTestId("visualization-previous"));
    await waitFor(() => expect(stageTitle()).toBe("alpha.png"));
    expect(screen.getByTestId("visualization-previous")).toHaveProperty("disabled", true);
  });

  it("shows the source under Code and the run graph under Run", async () => {
    installFetchMock(
      [DASH_RUN],
      { mission_dash: [DASH_FILE] },
      {
        plansBySlug: {
          mission_dash: {
            plan: { plan_id: "mission_dash", vision: "Build it", status: "complete" },
            steps: [
              { step_id: "t1:0", name: "umsatz-dashboard.html", tool_name: "Write", status: "done" },
            ],
            final_answer: "Done.",
          },
        },
        rawBySlug: { mission_dash: DASH_HTML },
      },
    );

    renderView();
    await openFirstCard();
    await screen.findByTestId("visualization-frame");

    openMore();
    fireEvent.click(screen.getByTestId("visualization-tab-code"));
    const source = await screen.findByTestId("visualization-source");
    expect(source.textContent).toContain("<title>Umsatz-Dashboard</title>");
    expect(screen.queryByTestId("visualization-frame")).toBeNull();

    openMore();
    fireEvent.click(screen.getByTestId("visualization-tab-run"));
    await screen.findByTestId("graph-node-start");
    await screen.findByTestId("graph-node-step");
    // The no-JS mission map stays one click away from the graph.
    openMore();
    expect(screen.getByTestId("visualization-open-map")).toBeTruthy();

    fireEvent.click(screen.getByTestId("visualization-tab-preview"));
    await screen.findByTestId("visualization-frame");
  });

  it("frames a PDF without a sandbox and draws an image through <img>", async () => {
    installFetchMock(
      [{ slug: "run-1", utterance: "Export", status: "success" }],
      {
        "run-1": [
          file("tasks/t1/artifacts/files/deck.pdf", { mtime: 1_700_000_200 }),
          file("tasks/t1/artifacts/files/cover.png", { mtime: 1_700_000_100 }),
        ],
      },
    );

    renderView();

    const cards = await screen.findAllByTestId("node-card");
    expect(cards).toHaveLength(2);
    // A PDF is a document, a picture a design.
    expect(cards.map((card) => card.getAttribute("data-node-type"))).toEqual(["docs", "design"]);
    fireEvent.click(cards[0]);
    const frame = await screen.findByTestId("visualization-frame");
    // The browser's PDF viewer is a plugin; a sandboxed frame would stay blank.
    expect(frame.hasAttribute("sandbox")).toBe(false);
    expect(frame.getAttribute("src")).toContain("deck.pdf");
    // No Code view for a PDF — there is no source to show.
    openMore();
    expect(screen.queryByTestId("visualization-tab-code")).toBeNull();

    fireEvent.click(screen.getByTestId("visualization-next"));
    const image = await screen.findByTestId("visualization-image");
    expect(image.getAttribute("src")).toContain("cover.png");
  });

  it("shows a running artifact build as a card and a stage until the page lands", async () => {
    installFetchMock(
      [
        { slug: "mission_building", utterance: ARTIFACT_UTTERANCE, status: "running" },
        { slug: "mission_other", utterance: "Refactor the parser", status: "running" },
        DASH_RUN,
      ],
      { mission_building: [], mission_other: [], mission_dash: [DASH_FILE] },
    );

    renderView();

    // Only the artifact build shows as a page in the making — an unrelated
    // running mission is a run, under "Runs".
    const building = await findCard("build:mission_building");
    expect(cardKeys()).toEqual(["build:mission_building", DASH_KEY]);
    expect(building.getAttribute("data-status")).toBe("building");
    expect(building.textContent).toContain("Umsatz-Dashboard");
    expect(screen.getByTestId("nodes-tab-runs").getAttribute("data-count")).toBe("1");
    // Opening the build shows its stage …
    fireEvent.click(building);
    await screen.findByTestId("visualization-building");
    // … and the finished artifact is back in the library, one click away.
    fireEvent.click(screen.getByTestId("visualization-back"));
    fireEvent.click(await findCard(DASH_KEY));
    await screen.findByTestId("visualization-frame");
  });

  it("keeps the bar quiet: a title pill, Share, More and Close — no success badge", async () => {
    installFetchMock([DASH_RUN], { mission_dash: [DASH_FILE] });

    renderView();
    await openFirstCard();
    await screen.findByTestId("visualization-frame");

    const bar = screen.getByTestId("visualization-stage-bar");
    expect(bar.textContent).not.toMatch(/success/i);
    // The request is the title here; it is not printed a second time.
    expect(bar.textContent?.match(/Umsatz-Dashboard/g)).toHaveLength(1);
    expect(screen.getByTestId("visualization-share").textContent).toBe("Share");
    expect(screen.getByTestId("visualization-back").getAttribute("aria-label")).toBe("Close");
    // The rarely used actions are behind More, not in the bar.
    expect(screen.queryByTestId("visualization-favorite")).toBeNull();
    expect(screen.queryByTestId("visualization-tab-code")).toBeNull();
    openMore();
    expect(screen.getByTestId("visualization-favorite")).toBeTruthy();
    expect(screen.getByTestId("visualization-download").getAttribute("href")).toContain(
      "umsatz-dashboard.html/download",
    );
    expect(screen.getByTestId("visualization-tab-preview").getAttribute("aria-checked")).toBe("true");
  });

  it("still names a run's state when it did not simply succeed", async () => {
    installFetchMock([{ ...DASH_RUN, status: "error" }], { mission_dash: [DASH_FILE] });

    renderView();
    await openFirstCard();
    await screen.findByTestId("visualization-frame");

    expect(screen.getByTestId("visualization-stage-bar").textContent).toMatch(/error|failed/i);
  });

  it("copies a link that opens exactly this artifact in the person's Dodaios", async () => {
    installFetchMock([DASH_RUN], { mission_dash: [DASH_FILE] });
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    document.execCommand = vi.fn(() => false) as typeof document.execCommand;

    renderView();
    await openFirstCard();
    await screen.findByTestId("visualization-frame");
    fireEvent.click(screen.getByTestId("visualization-share"));
    fireEvent.click(screen.getByTestId("visualization-share-link"));

    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const link = new URL(String((writeText.mock.calls[0] as unknown[])[0]));
    expect(link.origin).toBe(window.location.origin);
    expect(link.searchParams.get("view")).toBe("visualization");
    expect(link.searchParams.get("run")).toBe("mission_dash");
    expect(link.searchParams.get("artifact")).toBe("tasks/t1/artifacts/files/umsatz-dashboard.html");
  });

  it("hands a page to the macOS share sheet as PDF, named after its title", async () => {
    const fetchMock = installFetchMock(
      [DASH_RUN],
      { mission_dash: [DASH_FILE] },
      { capabilities: { native_file_actions: true, platform: "darwin", page_export: true } },
    );
    const postMessage = vi.fn();
    (window as unknown as { webkit?: unknown }).webkit = {
      messageHandlers: { jarvisShare: { postMessage } },
    };

    try {
      renderView();
      await openFirstCard();
      await screen.findByTestId("visualization-frame");
      fireEvent.click(screen.getByTestId("visualization-share"));
      const pdf = await screen.findByTestId("visualization-share-pdf");
      expect(pdf.textContent).toBe("Share as PDF…");
      expect(screen.getByTestId("visualization-share-png")).toBeTruthy();
      fireEvent.click(pdf);

      await waitFor(() => expect(postMessage).toHaveBeenCalled());
      const [tag, body] = postMessage.mock.calls[0][0] as [string, { files: string[] }];
      expect(tag).toBe("jarvis-share");
      expect(body.files).toEqual(["/tmp/dodaios-share/abc/Umsatz-Dashboard.pdf"]);
      const shareCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/share"));
      expect(JSON.parse(String(shareCall?.[1]?.body))).toMatchObject({
        format: "pdf",
        title: "Umsatz-Dashboard",
      });
    } finally {
      delete (window as unknown as { webkit?: unknown }).webkit;
    }
  });

  it("offers only the file itself when no page can be drawn, as a download in a browser", async () => {
    installFetchMock([DASH_RUN], { mission_dash: [DASH_FILE] });

    renderView();
    await openFirstCard();
    await screen.findByTestId("visualization-frame");
    fireEvent.click(screen.getByTestId("visualization-share"));

    expect(screen.getByTestId("visualization-share-file").textContent).toBe("Download file");
    expect(screen.queryByTestId("visualization-share-pdf")).toBeNull();
    expect(screen.getByRole("menu", { name: "Share" }).textContent).toContain("Nothing is uploaded");
  });

  it("opens the artifact a copied link names with &artifact=", async () => {
    installFetchMock(
      [{ slug: "run-1", utterance: "Export", status: "success" }],
      {
        "run-1": [
          file("tasks/t1/artifacts/files/new.png", { mtime: 1_700_000_900 }),
          file("tasks/t1/artifacts/files/old.png", { mtime: 1_700_000_100 }),
        ],
      },
    );
    window.history.replaceState(
      null,
      "",
      "/?view=visualization&run=run-1&artifact=tasks%2Ft1%2Fartifacts%2Ffiles%2Fold.png",
    );

    try {
      renderView();
      await waitFor(() =>
        expect(screen.getByTestId("visualization-image").getAttribute("src")).toContain("old.png"),
      );
    } finally {
      window.history.replaceState(null, "", "/");
    }
  });

  it("pre-selects the run named by ?run= in the URL", async () => {
    installFetchMock(
      [
        { slug: "run-new", utterance: "Draw the architecture", status: "success" },
        { slug: "run-old", utterance: "Summarise the logs", status: "success" },
      ],
      {
        "run-new": [file("tasks/t1/artifacts/files/new.svg", { mtime: 1_700_000_900 })],
        "run-old": [file("tasks/t1/artifacts/files/old.png", { mtime: 1_700_000_100 })],
      },
    );
    window.history.replaceState(null, "", "/?view=visualization&run=run-old");

    try {
      renderView();
      // The deep-linked run wins over the newest-first default.
      const image = await screen.findByTestId("visualization-image");
      expect(image.getAttribute("src")).toContain("old.png");
    } finally {
      window.history.replaceState(null, "", "/");
    }
  });

  it("keeps a run without a page under Runs, never among the nodes", async () => {
    // Every run has a card: one that produced only a text file is a run card
    // under "Runs" (its file is behind the stage's Files tab), not a node and
    // not an empty stage.
    installFetchMock(
      [{ slug: "run-text", utterance: "Write notes", status: "success" }],
      { "run-text": [file("tasks/t1/artifacts/files/notes.md", { is_text: true })] },
    );

    renderView();

    fireEvent.click(await screen.findByTestId("nodes-tab-runs"));
    const rows = await screen.findAllByTestId("node-card");
    expect(rows).toHaveLength(1);
    expect(rows[0].getAttribute("data-node-key")).toBe("run:run-text");
    expect(rows[0].textContent).toContain("Write notes");
    expect(screen.queryByTestId("visualization-frame")).toBeNull();
    expect(screen.queryByTestId("visualization-empty")).toBeNull();

    fireEvent.click(screen.getByTestId("nodes-tab-all"));
    expect(screen.queryAllByTestId("node-card")).toHaveLength(0);
  });

  it("stars a card, shows the starred ones under Favorites, and the stage knows the same star", async () => {
    const DECK = "run-1::tasks/t1/artifacts/files/deck.pdf";
    const COVER = "run-1::tasks/t1/artifacts/files/cover.png";
    installFetchMock(
      [{ slug: "run-1", utterance: "Export", status: "success" }],
      {
        "run-1": [
          file("tasks/t1/artifacts/files/deck.pdf", { mtime: 1_700_000_200 }),
          file("tasks/t1/artifacts/files/cover.png", { mtime: 1_700_000_100 }),
        ],
      },
    );

    renderView();

    await waitFor(() => expect(cardKeys()).toEqual([DECK, COVER]));
    const favorites = () => screen.getByTestId("nodes-tab-favorites");
    expect(favorites().getAttribute("data-count")).toBe("0");
    const stars = screen.getAllByTestId("node-card-star");
    expect(stars[1].getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(stars[1]);
    expect(screen.getAllByTestId("node-card-star")[1].getAttribute("aria-pressed")).toBe("true");
    expect(favorites().getAttribute("data-count")).toBe("1");

    fireEvent.click(favorites());
    expect(cardKeys()).toEqual([COVER]);

    // The stage reads the same star; taking it away there empties the tab,
    // and the tab says what it is for.
    fireEvent.click(await findCard(COVER));
    await screen.findByTestId("visualization-image");
    openMore();
    expect(screen.getByTestId("visualization-favorite").textContent).toContain("Remove from favorites");
    fireEvent.click(screen.getByTestId("visualization-favorite"));
    fireEvent.click(screen.getByTestId("visualization-back"));
    await screen.findByTestId("nodes-no-matches");
    expect(screen.queryAllByTestId("node-card")).toHaveLength(0);
    expect(favorites().getAttribute("aria-pressed")).toBe("true");
  });

  it("draws the same cards as a list, and a row opens the stage like a card does", async () => {
    installFetchMock([DASH_RUN], { mission_dash: [DASH_FILE] });

    renderView();

    await screen.findAllByTestId("node-card");
    expect(screen.getByTestId("nodes-grid")).toBeTruthy();
    fireEvent.click(screen.getByTestId("nodes-view-toggle"));
    expect(screen.getByTestId("nodes-list")).toBeTruthy();
    const rows = screen.getAllByTestId("node-card");
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain("Umsatz-Dashboard");
    expect(window.localStorage.getItem("jarvis.nodes.view")).toBe("list");
    fireEvent.click(rows[0]);
    await screen.findByTestId("visualization-stage");
    // Back finds the library as it was left: still a list.
    fireEvent.click(screen.getByTestId("visualization-back"));
    expect(await screen.findByTestId("nodes-list")).toBeTruthy();
  });

  it("invites to make something when there are no runs at all", async () => {
    installFetchMock([], {});

    renderView();

    await screen.findByTestId("nodes-empty");
    expect(screen.getByTestId("nodes-type-row")).toBeTruthy();
    expect(screen.queryByTestId("visualization-frame")).toBeNull();
  });

  it("opens a typed node on the stage and loads its frame again when the assistant revised it", async () => {
    const nodeStates = { [NODE.slug]: nodeState() };
    const fetchMock = installFetchMock([NODE_RUN], NODE_FILES, { typed: [NODE], nodeStates });

    const { client } = renderView();

    // The node is one card: its run is not adopted a second time.
    const card = await findCard(NODE.key);
    expect(cardKeys()).toEqual([NODE.key]);
    expect(card.getAttribute("data-origin")).toBe("node");
    fireEvent.click(card);

    await screen.findByTestId("visualization-frame");
    expect(frameSrc()).toContain(`/api/outputs/${NODE.slug}/files/index.html/page?theme=`);
    expect(screen.getByTestId("visualization-frame").getAttribute("sandbox")).toBe("allow-scripts");
    expect(stageTitle()).toBe("Website brief");

    // The watcher asks for the node's state, without its content …
    const watched = `/api/nodes/by-slug/${NODE.slug}?spec=0`;
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === watched)).toBe(true));
    // … and the frame is addressed by the revision it shows.
    await waitFor(() => expect(frameSrc()).toMatch(/&v=1700000000$/));

    // The assistant revises the node while it is open: the next look at its
    // state draws the page again.
    nodeStates[NODE.slug] = nodeState({ version: 2, updated_at: 1_700_000_600 });
    await client.invalidateQueries({ queryKey: ["node-upkeep", NODE.slug] });
    await waitFor(() => expect(frameSrc()).toMatch(/&v=1700000600$/));
    // Not kept current: the strip itself stays away.
    expect(screen.queryByTestId("node-upkeep-bar")).toBeNull();
  });

  it("offers to ask for a change on a typed node, and not on an adopted page", async () => {
    installFetchMock(
      [NODE_RUN, DASH_RUN],
      { ...NODE_FILES, mission_dash: [DASH_FILE] },
      { typed: [NODE], nodeStates: { [NODE.slug]: nodeState() } },
    );

    renderView();

    fireEvent.click(await findCard(NODE.key));
    await screen.findByTestId("visualization-frame");
    openMore();
    fireEvent.click(screen.getByTestId("visualization-ask-change"));
    expect(chat.askDodaiosToChange).toHaveBeenCalledTimes(1);
    expect(chat.askDodaiosToChange).toHaveBeenCalledWith(NODE);

    fireEvent.click(screen.getByTestId("visualization-back"));
    fireEvent.click(await findCard(DASH_KEY));
    await waitFor(() => expect(stageTitle()).toBe("Umsatz-Dashboard"));
    openMore();
    expect(screen.getByTestId("visualization-favorite")).toBeTruthy();
    expect(screen.queryByTestId("visualization-ask-change")).toBeNull();
  });

  it("collects the comments left on a typed node's page and sends them all with one click", async () => {
    const nodeStates = { [NODE.slug]: nodeState() };
    installFetchMock(
      [NODE_RUN, DASH_RUN],
      { ...NODE_FILES, mission_dash: [DASH_FILE] },
      { typed: [NODE], nodeStates },
    );
    chat.sendNodeComments.mockClear();
    const { client } = renderView();

    fireEvent.click(await findCard(NODE.key));
    await waitFor(() => expect(frameSrc()).toMatch(/&v=1700000000$/));
    const frame = screen.getByTestId("visualization-frame") as HTMLIFrameElement;
    const posted = vi.spyOn(frame.contentWindow as Window, "postMessage");
    const toggle = screen.getByTestId("visualization-comment");
    const note = () => screen.getByTestId("visualization-page-note").getAttribute("data-state");
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(note()).toBe("idle");

    // The mode goes to the page, with the words it shows.
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    expect(note()).toBe("commenting");
    expect(posted).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: "dodaios-node-mode", mode: "comment" }),
      "*",
    );

    // The page reports what was written, on what, and where; nothing goes out yet.
    const fromPage = (data: Record<string, unknown>) =>
      act(() => {
        window.dispatchEvent(new MessageEvent("message", { data, source: frame.contentWindow }));
      });
    const first = { n: 1, text: "Make the intro shorter", quote: "Welcome", where: "§ Intro" };
    const second = { n: 2, text: "Add a price table", quote: "Costs", where: "§ Costs" };
    const third = { n: 3, text: "never mind", quote: "", where: "" };
    expect(screen.queryByTestId("visualization-comments-send")).toBeNull();
    fromPage({ type: "dodaios-node-comment", ...first });
    await waitFor(() =>
      expect(posted).toHaveBeenLastCalledWith({ type: "dodaios-node-comment-state", n: 1, state: "pending" }, "*"),
    );
    fromPage({ type: "dodaios-node-comment", ...second });
    fromPage({ type: "dodaios-node-comment", ...third });
    await waitFor(() => expect(screen.getByTestId("visualization-comments-send").textContent).toBe("Send 3 comments"));
    // A comment taken back on the page does not go out.
    fromPage({ type: "dodaios-node-comment-remove", n: 3 });
    await waitFor(() => expect(screen.getByTestId("visualization-comments-send").textContent).toBe("Send 2 comments"));
    expect(chat.sendNodeComments).not.toHaveBeenCalled();
    expect(note()).toBe("commenting");

    // One click sends them all together, and the page hears it.
    fireEvent.click(screen.getByTestId("visualization-comments-send"));
    await waitFor(() => expect(chat.sendNodeComments).toHaveBeenCalledWith(NODE, [first, second]));
    await waitFor(() =>
      expect(posted).toHaveBeenLastCalledWith({ type: "dodaios-node-comment-state", n: 2, state: "sent" }, "*"),
    );
    expect(posted).toHaveBeenCalledWith({ type: "dodaios-node-comment-state", n: 1, state: "sent" }, "*");
    expect(screen.queryByTestId("visualization-comments-send")).toBeNull();
    expect(note()).toBe("working");

    // Escape leaves the comment mode first; the node stays open.
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByTestId("visualization-comment").getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByTestId("visualization-frame")).toBeTruthy();

    // The assistant's revision answers the comment: the line goes quiet.
    nodeStates[NODE.slug] = nodeState({ version: 2, updated_at: 1_700_000_600 });
    await client.invalidateQueries({ queryKey: ["node-upkeep", NODE.slug] });
    await waitFor(() => expect(frameSrc()).toMatch(/&v=1700000600$/));
    expect(note()).toBe("idle");
  });

  it("offers no comments on a page the assistant cannot revise", async () => {
    installFetchMock([DASH_RUN], { mission_dash: [DASH_FILE] });
    renderView();

    fireEvent.click(await findCard(DASH_KEY));
    await screen.findByTestId("visualization-frame");
    expect(screen.queryByTestId("visualization-comment")).toBeNull();
  });

  it("opens a node started empty on the stage before the library lists it", async () => {
    const created = typedNodeCard("n9", { title: "Untitled document" });
    const fetchMock = installFetchMock([DASH_RUN], { mission_dash: [DASH_FILE] }, { created });

    renderView();

    await findCard(DASH_KEY);
    fireEvent.click(screen.getByTestId("nodes-new"));
    fireEvent.click(await screen.findByTestId("new-node-empty"));

    await screen.findByTestId("visualization-frame");
    expect(frameSrc()).toContain(`/api/outputs/${created.slug}/files/index.html/page?theme=`);
    expect(stageTitle()).toBe("Untitled document");
    const post = fetchMock.mock.calls.find(([url, init]) => String(url) === "/api/nodes" && init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({ type: "docs" });

    // The library was read again after the create and still does not list it.
    const reads = () =>
      fetchMock.mock.calls.filter(([url, init]) => String(url) === "/api/nodes" && init?.method !== "POST");
    await waitFor(() => expect(reads().length).toBeGreaterThan(1));
    fireEvent.click(screen.getByTestId("visualization-back"));
    await findCard(DASH_KEY);
    expect(cardKeys()).toEqual([DASH_KEY]);
  });
});

describe("SectionStage", () => {
  it("gives the visualization section its own opaque stage", () => {
    const { container, rerender } = render(
      <SectionStage visualization={false}>
        <span>section</span>
      </SectionStage>,
    );
    expect(container.firstElementChild?.className).toContain("jarvis-section-stage");

    rerender(
      <SectionStage visualization>
        <span>section</span>
      </SectionStage>,
    );
    const stage = container.firstElementChild;
    expect(stage?.className).toContain("jarvis-visualization-stage");
    // Never both: a rendered page is judged against one flat ground only.
    expect(stage?.className).not.toContain("jarvis-section-stage");
  });
});
