/**
 * The node window: a node opened over the conversation it was made in.
 *
 * Contracts worth pinning:
 * - a page card's click opens the node HERE, on the stage the Nodes section
 *   has, and never switches the section; the conversation the click came from
 *   stands beside it, on its own store,
 * - a typed node can be edited and commented in the window, and "ask for a
 *   change" drafts into the conversation beside it instead of leaving,
 * - the conversation can be put away (remembered), and the window always has
 *   exactly one close button,
 * - Escape, the scrim and a change of section close it; comments that were
 *   left and not sent are asked about first,
 * - previous / next walk the pages this conversation made,
 * - "Open in Nodes" hands the node to the section.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { readComposerDraft } from "@/components/agentchat/composerDrafts";
import { EMPTY_TIMELINE, type TimelineItem } from "@/components/agentchat/reduce";
import { useNodeCommentDraft } from "@/components/nodes/nodeCommentDraft";
import type { NodeCard } from "@/components/nodes/nodeModel";
import { nodesResponse, typedNodeCard } from "@/components/nodes/testCards";
import type { ArtifactSummary, OutputSummary } from "@/hooks/useOutputs";
import { useAgentChatStore } from "@/store/agentChat";
import { useEventStore } from "@/store/events";
import { openNodePeek, useNodePeek } from "@/store/nodePeek";
import { NodePeekHost } from "./NodePeekHost";

vi.mock("@/hooks/useWebSocket", () => ({ getWSClient: () => null }));

// The conversation is the front page's own stage; here it only has to show
// which chat store it was handed.
vi.mock("@/components/home/ChatStage", async () => {
  const { useAgentChat } = await import("@/components/agentchat/AgentChatStoreContext");
  return {
    ChatStage: () => {
      const surface = useAgentChat((s) => s.surface);
      return (
        <div data-testid="chat-stage-stub" data-surface={surface}>
          {/* A textarea: jsdom does not know `isContentEditable`, the composer's own kind of field. */}
          <textarea data-jarvis-chat-input="" />
        </div>
      );
    },
  };
});

const PLAN_RUN: OutputSummary = { slug: "run-1", status: "success", utterance: "Write the business plan" } as OutputSummary;
const PLAN_FILE: ArtifactSummary = {
  path: "tasks/report/artifacts/files/plan.html", size: 2048, mtime: 1_760_000_000, is_text: true,
  preview: "<title>Business plan v1</title>", title: "Business plan v1",
} as ArtifactSummary;
const PLAN = `run-1::${PLAN_FILE.path}`;
const DOC = typedNodeCard("doc-1", { title: "Launch notes", type: "docs" });
const DOC_REF = `${DOC.slug}::${DOC.path}`;

function installFetchMock(typed: NodeCard[] = []) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/nodes" && init?.method !== "POST") {
      return { ok: true, status: 200, json: async () => nodesResponse([PLAN_RUN], { "run-1": [PLAN_FILE] }, typed) };
    }
    if (/^\/api\/nodes\/by-slug\//.test(url)) return { ok: false, status: 404, json: async () => ({ detail: "unknown" }) };
    if (/\/api\/outputs\/[^/]+\/artifacts/.test(url)) {
      return { ok: true, status: 200, json: async () => ({ files: url.includes("run-1") ? [PLAN_FILE] : [] }) };
    }
    if (url.includes("/capabilities")) return { ok: true, status: 200, json: async () => ({ native_file_actions: false }) };
    if (url.includes("/api/outputs")) return { ok: true, status: 200, json: async () => ({ sessions: [PLAN_RUN] }) };
    return { ok: true, status: 200, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <button type="button" data-testid="behind">behind</button>
      <NodePeekHost />
    </QueryClientProvider>,
  );
}

const pageNotice = (id: string, artifact: string, text: string): TimelineItem =>
  ({
    type: "notice", id, kind: "report", text, agentName: "", agentId: "",
    status: "", tsMs: 1, data: { kind: "report", artifact }, resolved: "",
  }) as TimelineItem;

async function openWindow(ref: string, title = "") {
  act(() => openNodePeek(ref, { chat: useAgentChatStore, title }));
  // The window is its own chunk (the stage and the editors come with it).
  return screen.findByTestId("node-peek-window", {}, { timeout: 20_000 });
}

// The window is its own chunk, and the stage and the editors come with it:
// loaded once here, so no test pays for it inside its own time.
beforeAll(async () => {
  await import("./NodePeekWindow");
}, 120_000);

beforeEach(() => {
  window.localStorage.clear();
  useNodePeek.setState({ peek: null, touched: {}, chatOpen: true, lender: null });
  useNodeCommentDraft.setState({ nodeKey: null, pending: [], sending: false, working: 0, outcome: null });
  useAgentChatStore.setState({ timeline: EMPTY_TIMELINE });
  useEventStore.setState({ activeSection: "chats", solo: false });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  useNodePeek.setState({ peek: null, touched: {} });
});

describe("the node window", () => {
  it("draws nothing until a node is asked for", () => {
    installFetchMock();
    mount();
    expect(screen.queryByTestId("node-peek")).toBeNull();
  });

  it("opens the page over the conversation it came from, without leaving the page", async () => {
    installFetchMock();
    mount();
    const windowEl = await openWindow(PLAN, "Business plan v1");
    expect(windowEl.getAttribute("role")).toBe("dialog");
    // The page itself, framed the way the Nodes section frames it.
    const frame = await screen.findByTestId("visualization-frame");
    expect(frame.getAttribute("src")).toContain(`/api/outputs/run-1/files/${PLAN_FILE.path}/page`);
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(screen.getByTestId("visualization-title").textContent).toBe("Business plan v1");
    // The conversation beside it, on the store the click came from. Its
    // column is there with the window; the conversation itself is drawn
    // right after the window's first frame, so it never holds the node back.
    expect(screen.getByTestId("node-peek-chat")).toBeTruthy();
    expect((await screen.findByTestId("chat-stage-stub")).getAttribute("data-surface")).toBe("jarvis");
    expect(screen.getByTestId("node-peek-conversation").getAttribute("data-ready")).toBe("true");
    // On screen at once: nothing fades or zooms in, nothing is blurred.
    expect(windowEl.className).not.toContain("animate-");
    expect(screen.getByTestId("node-peek-scrim").className).not.toContain("blur");
    // The section did not change.
    expect(useEventStore.getState().activeSection).toBe("chats");
    expect(useEventStore.getState().visualStage).toBeNull();
  });

  it("moves the conversation that is on the page behind it instead of drawing it again", async () => {
    installFetchMock();
    // The front page offers its conversation: the element it is drawn in, and its column.
    const home = document.body.appendChild(document.createElement("div"));
    const element = home.appendChild(document.createElement("div"));
    useNodePeek.setState({ lender: { chat: useAgentChatStore, element, home } });
    mount();
    await openWindow(PLAN);
    const place = screen.getByTestId("node-peek-conversation");
    expect(place.getAttribute("data-borrowed")).toBe("true");
    // Right after the window's first frame the conversation stands beside the node.
    await waitFor(() => expect(place.contains(element)).toBe(true));
    // No second conversation is drawn.
    expect(screen.queryByTestId("chat-stage-stub")).toBeNull();

    // Put away, it is back in its own column; shown again, beside the node at once.
    fireEvent.click(screen.getByTestId("node-peek-chat-toggle"));
    expect(home.contains(element)).toBe(true);
    fireEvent.click(screen.getByTestId("node-peek-chat-toggle"));
    expect(screen.getByTestId("node-peek-conversation").contains(element)).toBe(true);

    // Closed: home again, and never off the page on the way.
    fireEvent.keyDown(screen.getByTestId("node-peek-window"), { key: "Escape" });
    expect(screen.queryByTestId("node-peek")).toBeNull();
    expect(home.contains(element)).toBe(true);
    home.remove();
  });

  it("does not wait for a frame that never comes: a covered window still gets its conversation", async () => {
    installFetchMock();
    const home = document.body.appendChild(document.createElement("div"));
    const element = home.appendChild(document.createElement("div"));
    useNodePeek.setState({ lender: { chat: useAgentChatStore, element, home } });
    // A window that is covered or minimised is given no frames.
    const frames = vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => 1);
    mount();
    await openWindow(PLAN);
    const place = screen.getByTestId("node-peek-conversation");
    await waitFor(() => expect(place.contains(element)).toBe(true));
    frames.mockRestore();
    fireEvent.keyDown(screen.getByTestId("node-peek-window"), { key: "Escape" });
    home.remove();
  });

  it("draws a conversation the page behind it does not have, after the node", async () => {
    installFetchMock();
    // The page behind offers another chat than the one the node was opened from.
    const home = document.body.appendChild(document.createElement("div"));
    const element = home.appendChild(document.createElement("div"));
    useNodePeek.setState({ lender: { chat: (() => undefined) as never, element, home } });
    mount();
    await openWindow(PLAN);
    expect(screen.getByTestId("node-peek-conversation").getAttribute("data-borrowed")).toBeNull();
    expect(await screen.findByTestId("chat-stage-stub")).toBeTruthy();
    // The other conversation stays where it is.
    expect(home.contains(element)).toBe(true);
    home.remove();
  });

  it("has one close button: on the conversation's header beside the node, on the node's bar without it", async () => {
    installFetchMock();
    mount();
    await openWindow(PLAN);
    expect(screen.getByTestId("node-peek-close")).toBeTruthy();
    expect(screen.queryByTestId("visualization-back")).toBeNull();

    fireEvent.click(screen.getByTestId("node-peek-chat-toggle"));
    expect(screen.queryByTestId("node-peek-chat")).toBeNull();
    expect(screen.queryByTestId("node-peek-close")).toBeNull();
    expect(screen.getByTestId("visualization-back")).toBeTruthy();
    // Put away once, away the next time too.
    expect(useNodePeek.getState().chatOpen).toBe(false);
    expect(window.localStorage.getItem("jarvis.nodes.peek.chat")).toBe("0");

    fireEvent.click(screen.getByTestId("visualization-back"));
    expect(screen.queryByTestId("node-peek")).toBeNull();
  });

  it("lets a typed node be edited and commented, and drafts a change into the conversation beside it", async () => {
    installFetchMock([DOC]);
    mount();
    await openWindow(DOC_REF, "Launch notes");
    expect(await screen.findByTestId("visualization-edit")).toBeTruthy();
    expect(screen.getByTestId("visualization-comment")).toBeTruthy();

    fireEvent.click(screen.getByTestId("visualization-more"));
    fireEvent.click(screen.getByTestId("visualization-ask-change"));
    // Nothing was left and nothing was sent: the sentence waits in the composer here.
    const draft = readComposerDraft(useAgentChatStore, useAgentChatStore.getState().activeSessionId);
    expect(draft.text).toContain("Launch notes");
    expect(draft.text).toContain("doc-1");
    expect(useEventStore.getState().activeSection).toBe("chats");
    expect(screen.getByTestId("node-peek-window")).toBeTruthy();
  });

  it("renames a typed node and takes its last change back from the window's menu", async () => {
    const fetchMock = installFetchMock([DOC]);
    mount();
    await openWindow(DOC_REF, "Launch notes");
    await screen.findByTestId("visualization-edit");

    fireEvent.click(screen.getByTestId("visualization-more"));
    fireEvent.click(screen.getByTestId("visualization-rename"));
    // The dialog is drawn over the window, with the node's name in its field.
    const dialog = await screen.findByTestId("node-rename-dialog");
    expect(dialog.querySelector("input")?.value).toBe("Launch notes");
    fireEvent.keyDown(dialog, { key: "Escape" });
    // Its Escape was its own: the window is still there.
    expect(screen.getByTestId("node-peek-window")).toBeTruthy();

    fireEvent.click(screen.getByTestId("visualization-more"));
    fireEvent.click(screen.getByTestId("visualization-revert"));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url, init]) => String(url) === "/api/nodes/doc-1/revert" && init?.method === "POST")).toBe(true),
    );
  });

  it("offers neither for a page that is no node", async () => {
    installFetchMock();
    mount();
    await openWindow(PLAN);
    await screen.findByTestId("visualization-frame");
    fireEvent.click(screen.getByTestId("visualization-more"));
    expect(screen.queryByTestId("visualization-rename")).toBeNull();
    expect(screen.queryByTestId("visualization-revert")).toBeNull();
    expect(screen.queryByTestId("visualization-ask-change")).toBeNull();
  });

  it("closes on Escape and on a click beside it, but not while a text is typed", async () => {
    installFetchMock();
    mount();
    const windowEl = await openWindow(PLAN);
    const field = (await screen.findByTestId("chat-stage-stub")).querySelector<HTMLElement>("[data-jarvis-chat-input]")!;
    fireEvent.keyDown(field, { key: "Escape" });
    expect(screen.getByTestId("node-peek-window")).toBeTruthy();

    fireEvent.keyDown(windowEl, { key: "Escape" });
    expect(screen.queryByTestId("node-peek")).toBeNull();
    expect(useNodePeek.getState().touched[PLAN]).toBeGreaterThan(0);

    await openWindow(PLAN);
    fireEvent.click(screen.getByTestId("node-peek-scrim"));
    expect(screen.queryByTestId("node-peek")).toBeNull();
  });

  it("leaves the keys of whatever is drawn over it alone", async () => {
    installFetchMock();
    mount();
    await openWindow(PLAN);
    // A dialog portaled to <body> is not in the window: its Escape is its own.
    fireEvent.keyDown(screen.getByTestId("behind"), { key: "Escape" });
    expect(screen.getByTestId("node-peek-window")).toBeTruthy();
    // The node's own content keeps its keys too (a whiteboard's arrows and Escape).
    const content = await screen.findByTestId("visualization-stage");
    fireEvent.keyDown(content, { key: "Escape" });
    fireEvent.keyDown(content, { key: "ArrowRight" });
    expect(screen.getByTestId("node-peek-window")).toBeTruthy();
    expect(useNodePeek.getState().peek?.ref).toBe(PLAN);
  });

  it("asks before it drops comments that were left and not sent", async () => {
    installFetchMock([DOC]);
    mount();
    const windowEl = await openWindow(DOC_REF);
    await screen.findByTestId("visualization-edit");
    act(() => useNodeCommentDraft.getState().add({ n: 1, text: "Shorter, please", quote: "Intro", where: "p" } as never));

    fireEvent.keyDown(windowEl, { key: "Escape" });
    expect(screen.getByTestId("node-peek-unsent").textContent).toContain("1 comment is not sent yet");
    // Escape again takes the question back, the window stays.
    fireEvent.keyDown(windowEl, { key: "Escape" });
    expect(screen.queryByTestId("node-peek-unsent")).toBeNull();
    expect(screen.getByTestId("node-peek-window")).toBeTruthy();

    fireEvent.click(screen.getByTestId("node-peek-scrim"));
    fireEvent.click(screen.getByTestId("node-peek-unsent-discard"));
    expect(screen.queryByTestId("node-peek")).toBeNull();
    expect(useNodeCommentDraft.getState().pending).toEqual([]);
  });

  it("walks the pages its conversation made with the arrow keys", async () => {
    installFetchMock([DOC]);
    useAgentChatStore.setState({
      timeline: {
        ...EMPTY_TIMELINE,
        items: [pageNotice("n-1", PLAN, "Business plan v1"), pageNotice("n-2", DOC_REF, "Launch notes")],
      },
    });
    mount();
    const windowEl = await openWindow(PLAN);
    fireEvent.keyDown(windowEl, { key: "ArrowRight" });
    await waitFor(() => expect(useNodePeek.getState().peek?.ref).toBe(DOC_REF));
    // The same conversation stays beside the next node.
    expect(useNodePeek.getState().peek?.chat).toBe(useAgentChatStore);
    // At the end of the list there is nowhere further to go.
    fireEvent.keyDown(screen.getByTestId("node-peek-window"), { key: "ArrowRight" });
    expect(useNodePeek.getState().peek?.ref).toBe(DOC_REF);
    fireEvent.keyDown(screen.getByTestId("node-peek-window"), { key: "ArrowLeft" });
    await waitFor(() => expect(useNodePeek.getState().peek?.ref).toBe(PLAN));
  });

  it("hands the node to the Nodes section on 'Open in Nodes'", async () => {
    installFetchMock();
    mount();
    await openWindow(PLAN);
    fireEvent.click(screen.getByTestId("node-peek-expand"));
    expect(screen.queryByTestId("node-peek")).toBeNull();
    expect(useEventStore.getState().visualStage?.target).toBe(PLAN);
    expect(useEventStore.getState().activeSection).toBe("visualization");
  });

  it("does not stay over a page it was not opened on", async () => {
    installFetchMock();
    mount();
    await openWindow(PLAN);
    act(() => useEventStore.getState().setActiveSection("settings"));
    expect(screen.queryByTestId("node-peek")).toBeNull();
  });

  it("brings focus back into the window when it lands in the app behind it", async () => {
    installFetchMock();
    mount();
    const windowEl = await openWindow(PLAN);
    const behind = screen.getByTestId("behind");
    act(() => behind.focus());
    expect(document.activeElement).toBe(windowEl);
  });
});
