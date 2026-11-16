import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useAgentChatStore } from "@/store/agentChat";
import { useEventStore } from "@/store/events";
import { openNodePeek, splitNodeRef, useNodePeek } from "@/store/nodePeek";

const PAGE = "run-1::tasks/report/artifacts/files/plan.html";
const SHEET = "run-2__node__abc::index.html";

beforeEach(() => {
  window.localStorage.clear();
  useNodePeek.setState({ peek: null, touched: {}, chatOpen: true });
});

afterEach(() => {
  useNodePeek.setState({ peek: null, touched: {} });
});

describe("the node window's store", () => {
  it("opens a page by its address, with the chat it was opened from", () => {
    openNodePeek(PAGE, { chat: useAgentChatStore, title: " Business plan " });
    expect(useNodePeek.getState().peek).toEqual({
      ref: PAGE,
      slug: "run-1",
      path: "tasks/report/artifacts/files/plan.html",
      title: "Business plan",
      chat: useAgentChatStore,
      seq: 1,
    });
  });

  it("keeps the conversation beside the node when another node is opened from inside the window", () => {
    openNodePeek(PAGE, { chat: useAgentChatStore });
    // Previous / next name no chat: the one that is there stays.
    openNodePeek(SHEET, { title: "Costs" });
    expect(useNodePeek.getState().peek).toMatchObject({ ref: SHEET, chat: useAgentChatStore, seq: 2 });
    // The lead conversation, asked for by name, replaces it.
    openNodePeek(PAGE, { chat: null });
    expect(useNodePeek.getState().peek?.chat).toBeNull();
  });

  it("hands anything that is not one file's address to the Nodes section", () => {
    const before = useEventStore.getState().visualStage?.seq ?? 0;
    openNodePeek("latest");
    expect(useNodePeek.getState().peek).toBeNull();
    expect(useEventStore.getState().visualStage).toEqual({ target: "latest", seq: before + 1 });
    expect(splitNodeRef("::path")).toBeNull();
    expect(splitNodeRef("slug::")).toBeNull();
    expect(splitNodeRef("a::b::c")).toEqual({ slug: "a", path: "b::c" });
  });

  it("remembers when a node's window was closed, and only then", () => {
    useNodePeek.getState().close();
    expect(useNodePeek.getState().touched).toEqual({});
    openNodePeek(PAGE);
    useNodePeek.getState().close();
    expect(useNodePeek.getState().peek).toBeNull();
    expect(useNodePeek.getState().touched[PAGE]).toBeGreaterThan(0);
  });

  it("keeps the choice to put the conversation away", () => {
    useNodePeek.getState().setChatOpen(false);
    expect(useNodePeek.getState().chatOpen).toBe(false);
    expect(window.localStorage.getItem("jarvis.nodes.peek.chat")).toBe("0");
    useNodePeek.getState().setChatOpen(true);
    expect(window.localStorage.getItem("jarvis.nodes.peek.chat")).toBe("1");
  });
});
