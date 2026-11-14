/**
 * The native node editors on the stage.
 *
 * Contracts worth pinning:
 * - "Edit" on a typed node with an editor swaps the page for that editor,
 *   loaded with the node's spec and version; the stage's own keys pause;
 * - the editor hears the node's revisions through the stage's watcher;
 * - Done brings the page back, drawn again (a fresh frame);
 * - a node started blank opens straight in its editor;
 * - Comment still works on the page.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { nodesResponse, typedNodeCard } from "@/components/nodes/testCards";
import type { NodeCard } from "@/components/nodes/nodeModel";
import type { NodeState } from "@/components/nodes/useNodes";
import type { NodeEditorProps } from "@/components/nodes/editors/types";
import { useRevisionSource } from "@/components/nodes/editors/editorContext";
import type { OutputSummary } from "@/hooks/useOutputs";
import { VisualizationView } from "@/views/VisualizationView";

vi.mock("@/hooks/useWebSocket", () => ({ getWSClient: () => null }));
vi.mock("@/components/nodes/askDodaios", () => ({
  requestNewNode: vi.fn(async () => undefined),
  askDodaiosToChange: vi.fn(async () => undefined),
}));

/* Every type's editor: a stand-in that shows what the stage hands it and
 * the revisions it hears. */
function StubEditor({ node, initial, onDone }: NodeEditorProps) {
  const source = useRevisionSource();
  const [heard, setHeard] = useState<number | null>(null);
  useEffect(() => source?.subscribe(setHeard), [source]);
  return (
    <div
      data-testid="editor-stub"
      data-node={node.id ?? ""}
      data-type={node.type}
      data-version={String(initial.version)}
      data-spec={JSON.stringify(initial.spec)}
      data-heard={String(heard)}
    >
      <button type="button" data-testid="editor-stub-done" onClick={onDone}>
        Done
      </button>
    </div>
  );
}
vi.mock("@/components/nodes/editors/registry", () => {
  const load = async () => ({ default: StubEditor });
  return {
    NODE_EDITORS: { docs: load, slides: load, sheets: load, design: load, data: load, motion: load },
  };
});

const DOC = typedNodeCard("d1", { type: "docs", title: "Brief", updated_at: 1_700_000_000 });
const DOC_RUN: OutputSummary = { slug: DOC.slug, utterance: "Brief", status: "success" };
const FILES = { [DOC.slug]: [{ path: "index.html", size: 10, mtime: 1, is_text: true, preview: null }] };

function state(id: string, slug: string, over: Partial<NodeState> = {}): NodeState {
  return {
    id,
    type: "docs",
    title: "Brief",
    slug,
    page_path: "index.html",
    version: 3,
    updated_at: 1_700_000_000,
    track: "",
    every_minutes: 0,
    refreshing: false,
    note: "",
    visual_id: `${slug}::index.html`,
    page_url: "",
    spec: { markdown: "# Brief" },
    ...over,
  };
}

function installFetch(options: { typed: NodeCard[]; runs: OutputSummary[]; created?: NodeCard; states: Record<string, NodeState> }) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/nodes") {
      const body = init?.method === "POST" ? options.created : nodesResponse(options.runs, FILES, options.typed);
      return { ok: true, status: 200, json: async () => body ?? {} };
    }
    const bySlug = /^\/api\/nodes\/by-slug\/([^/?]+)/.exec(url);
    if (bySlug) {
      const found = options.states[decodeURIComponent(bySlug[1])];
      return found ? { ok: true, status: 200, json: async () => found } : { ok: false, status: 404, json: async () => ({}) };
    }
    const byId = /^\/api\/nodes\/([0-9a-z]+)$/.exec(url);
    if (byId) {
      const found = Object.values(options.states).find((entry) => entry.id === byId[1]);
      return found ? { ok: true, status: 200, json: async () => found } : { ok: false, status: 404, json: async () => ({}) };
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

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("a node's native editor on the stage", () => {
  it("swaps the page for the editor on Edit and brings a fresh page back on Done", async () => {
    const states = { [DOC.slug]: state("d1", DOC.slug) };
    installFetch({ typed: [DOC], runs: [DOC_RUN], states });
    const { client } = renderView();
    await openCard(DOC.key);
    const firstFrame = await screen.findByTestId("visualization-frame");

    fireEvent.click(screen.getByTestId("visualization-edit"));
    const editor = await screen.findByTestId("editor-stub");
    expect(screen.queryByTestId("visualization-frame")).toBeNull();
    expect(editor.getAttribute("data-node")).toBe("d1");
    expect(editor.getAttribute("data-type")).toBe("docs");
    expect(editor.getAttribute("data-version")).toBe("3");
    expect(JSON.parse(editor.getAttribute("data-spec") ?? "null")).toEqual({ markdown: "# Brief" });
    // The page's toggles step aside while the editor is open.
    expect(screen.queryByTestId("visualization-edit")).toBeNull();
    expect(screen.queryByTestId("visualization-comment")).toBeNull();

    // The stage's own keys pause: Escape does not close the stage under the editor.
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByTestId("editor-stub")).toBeTruthy();

    // The editor hears the watcher …
    await waitFor(() => expect(screen.getByTestId("editor-stub").getAttribute("data-heard")).toBe("1700000000"));
    // … and the assistant's revision.
    states[DOC.slug] = state("d1", DOC.slug, { version: 4, updated_at: 1_700_000_500 });
    await client.invalidateQueries({ queryKey: ["node-upkeep", DOC.slug] });
    await waitFor(() => expect(screen.getByTestId("editor-stub").getAttribute("data-heard")).toBe("1700000500"));

    fireEvent.click(screen.getByTestId("editor-stub-done"));
    const frame = await screen.findByTestId("visualization-frame");
    expect(frame).not.toBe(firstFrame);
    expect(screen.queryByTestId("editor-stub")).toBeNull();
    expect(screen.getByTestId("visualization-edit").getAttribute("aria-pressed")).toBe("false");
    // Comment still works on the page.
    fireEvent.click(screen.getByTestId("visualization-comment"));
    expect(screen.getByTestId("visualization-comment").getAttribute("aria-pressed")).toBe("true");
  });

  it("opens a node started blank straight in its editor", async () => {
    const created = typedNodeCard("n9", { title: "Untitled document" });
    const states = { [created.slug]: state("n9", created.slug, { version: 1, spec: { markdown: "" } }) };
    installFetch({ typed: [DOC], runs: [DOC_RUN], created, states });
    renderView();
    await openCard(DOC.key);
    fireEvent.click(screen.getByTestId("visualization-back"));
    await waitFor(() => expect(screen.queryAllByTestId("node-card").length).toBeGreaterThan(0));

    fireEvent.click(screen.getByTestId("nodes-new"));
    fireEvent.click(screen.getByTestId("nodes-new-blank-docs"));
    const editor = await screen.findByTestId("editor-stub");
    expect(editor.getAttribute("data-node")).toBe("n9");
    expect(editor.getAttribute("data-version")).toBe("1");
    expect(screen.queryByTestId("visualization-frame")).toBeNull();
  });

  it("says so when the node cannot be read, and goes back to the page", async () => {
    installFetch({ typed: [DOC], runs: [DOC_RUN], states: {} });
    renderView();
    await openCard(DOC.key);
    await screen.findByTestId("visualization-frame");
    fireEvent.click(screen.getByTestId("visualization-edit"));
    await screen.findByTestId("node-editor-failed");
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await screen.findByTestId("visualization-frame");
  });
});
