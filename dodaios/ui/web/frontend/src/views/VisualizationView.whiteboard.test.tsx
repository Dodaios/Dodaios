/**
 * A whiteboard in the Nodes section.
 *
 * Contracts worth pinning:
 * - a typed whiteboard node opens on its editor, not on its page frame, and
 *   the editor hears when the node changed on the server,
 * - its stage bar has no Edit / Comment toggles (the editor is always
 *   editable) and offers "New whiteboard", which makes a blank board and
 *   opens it,
 * - on the library's whiteboard shelf, "New whiteboard" makes a blank board
 *   at once and opens it; the other types still open the dialog.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { nodesResponse, typedNodeCard } from "@/components/nodes/testCards";
import type { NodeCard } from "@/components/nodes/nodeModel";
import type { NodeState } from "@/components/nodes/useNodes";
import type { OutputSummary } from "@/hooks/useOutputs";
import { VisualizationView } from "@/views/VisualizationView";

vi.mock("@/hooks/useWebSocket", () => ({ getWSClient: () => null }));
vi.mock("@/components/nodes/askDodaios", () => ({
  requestNewNode: vi.fn(async () => undefined),
  askDodaiosToChange: vi.fn(async () => undefined),
}));

// The editor needs a canvas: a stand-in that shows what the stage hands it.
vi.mock("@/components/nodes/whiteboard/WhiteboardEditor", () => ({
  default: ({ nodeId, title, revision }: { nodeId: string; title: string; revision: number | null }) => (
    <div data-testid="whiteboard-editor-stub" data-node={nodeId} data-title={title} data-revision={String(revision)} />
  ),
}));

const BOARD = typedNodeCard("w1", { type: "whiteboard", title: "Launch plan", updated_at: 1_700_000_000 });
const BOARD_RUN: OutputSummary = { slug: BOARD.slug, utterance: "Launch plan", status: "success" };
const FILES = { [BOARD.slug]: [{ path: "index.html", size: 10, mtime: 1, is_text: true, preview: null }] };

function boardState(over: Partial<NodeState> = {}): NodeState {
  return {
    id: "w1",
    type: "whiteboard",
    title: BOARD.title,
    slug: BOARD.slug,
    page_path: "index.html",
    version: 1,
    updated_at: 1_700_000_000,
    track: "",
    every_minutes: 0,
    refreshing: false,
    note: "",
    visual_id: BOARD.key,
    page_url: "",
    spec: null,
    ...over,
  };
}

function installFetch(options: { typed: NodeCard[]; runs: OutputSummary[]; created?: NodeCard; states?: Record<string, NodeState> }) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/nodes") {
      const body = init?.method === "POST" ? options.created : nodesResponse(options.runs, FILES, options.typed);
      return { ok: true, status: 200, json: async () => body ?? {} };
    }
    const bySlug = /^\/api\/nodes\/by-slug\/([^/?]+)/.exec(url);
    if (bySlug) {
      const state = options.states?.[decodeURIComponent(bySlug[1])];
      return state ? { ok: true, status: 200, json: async () => state } : { ok: false, status: 404, json: async () => ({}) };
    }
    if (url.includes("/capabilities")) return { ok: true, status: 200, json: async () => ({}) };
    if (/\/api\/outputs\/[^/]+\/artifacts/.test(url)) return { ok: true, status: 200, json: async () => ({ files: [] }) };
    if (url.includes("/api/outputs")) return { ok: true, status: 200, json: async () => ({ sessions: options.runs }) };
    return { ok: true, status: 200, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } } });
  const view = render(
    <QueryClientProvider client={client}>
      <VisualizationView />
    </QueryClientProvider>,
  );
  return { ...view, client };
}

async function openCard(key: string) {
  const card = await waitFor(() => {
    const found = screen.queryAllByTestId("node-card").find((el) => el.getAttribute("data-node-key") === key);
    if (!found) throw new Error(`no card ${key}`);
    return found;
  });
  fireEvent.click(card);
}

function posts(fetchMock: ReturnType<typeof installFetch>) {
  return fetchMock.mock.calls.filter(([url, init]) => String(url) === "/api/nodes" && init?.method === "POST");
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("a whiteboard on the stage", () => {
  it("opens on its editor instead of the page frame, without Edit and Comment", async () => {
    const states = { [BOARD.slug]: boardState() };
    installFetch({ typed: [BOARD], runs: [BOARD_RUN], states });
    const { client } = renderView();
    await openCard(BOARD.key);

    const editor = await screen.findByTestId("whiteboard-editor-stub");
    expect(editor.getAttribute("data-node")).toBe("w1");
    expect(editor.getAttribute("data-title")).toBe("Launch plan");
    expect(screen.queryByTestId("visualization-frame")).toBeNull();
    expect(screen.queryByTestId("visualization-edit")).toBeNull();
    expect(screen.queryByTestId("visualization-comment")).toBeNull();

    // The node's watcher tells the editor what revision the server holds …
    await waitFor(() => expect(editor.getAttribute("data-revision")).toBe("1700000000"));
    // … and when the assistant drew something.
    states[BOARD.slug] = boardState({ version: 2, updated_at: 1_700_000_300 });
    await client.invalidateQueries({ queryKey: ["node-upkeep", BOARD.slug] });
    await waitFor(() =>
      expect(screen.getByTestId("whiteboard-editor-stub").getAttribute("data-revision")).toBe("1700000300"),
    );
  });

  it("makes a blank board from the stage bar and opens it", async () => {
    const created = typedNodeCard("w2", { type: "whiteboard", title: "Whiteboard 2" });
    const fetchMock = installFetch({ typed: [BOARD], runs: [BOARD_RUN], created, states: { [BOARD.slug]: boardState() } });
    renderView();
    await openCard(BOARD.key);
    await screen.findByTestId("whiteboard-editor-stub");

    fireEvent.click(screen.getByTestId("visualization-new-whiteboard"));
    await waitFor(() => expect(screen.getByTestId("whiteboard-editor-stub").getAttribute("data-node")).toBe("w2"));
    expect(posts(fetchMock)).toHaveLength(1);
    expect(JSON.parse(String(posts(fetchMock)[0][1]?.body))).toMatchObject({ type: "whiteboard" });
    expect(screen.getByTestId("visualization-title").textContent).toBe("Whiteboard 2");
  });

  it("offers no New whiteboard on another type's stage", async () => {
    const doc = typedNodeCard("d1", { title: "Brief" });
    installFetch({ typed: [doc], runs: [{ slug: doc.slug, utterance: "Brief", status: "success" }] });
    renderView();
    await openCard(doc.key);
    await screen.findByTestId("visualization-frame");
    expect(screen.queryByTestId("visualization-new-whiteboard")).toBeNull();
    expect(screen.queryByTestId("whiteboard-editor-stub")).toBeNull();
  });
});
