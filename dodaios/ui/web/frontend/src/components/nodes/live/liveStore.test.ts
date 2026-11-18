import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAgentChatStore } from "@/store/agentChat";
import { useNodePeek } from "@/store/nodePeek";
import { AUTO_OPEN_WITHIN_MS, shouldAutoOpen } from "./autoOpen";
import {
  IDLE_SETTLE_MS,
  PRESENCE_LINGER_MS,
  changesBetween,
  liveNodeOfRef,
  parseNodeChange,
  presenceActive,
  useNodeLive,
} from "./liveStore";
import { receiveNodeChange } from "./receive";

const REF = "20261118T100000__node__abc123def456::tasks/node/artifacts/files/budget.html";

function payload(over: Record<string, unknown> = {}) {
  return {
    node_id: "abc123def456",
    ref: REF,
    slug: "20261118T100000__node__abc123def456",
    node_type: "sheets",
    title: "Budget",
    version: 1,
    previous_version: 0,
    updated_at: 1_000,
    action: "create",
    rewrite: false,
    ops: [],
    author_kind: "assistant",
    author_name: "Dodaios",
    author_id: "lead",
    session_id: "chat-1",
    step: "",
    ...over,
  };
}

function receive(over: Record<string, unknown> = {}) {
  const change = parseNodeChange(payload(over));
  if (change === null) throw new Error("not a change");
  useNodeLive.getState().receive(change);
  return change;
}

afterEach(() => {
  useNodeLive.setState({ nodes: {}, refs: {}, autoOpened: {}, suppressed: {} });
  useNodePeek.setState({ peek: null });
  vi.useRealTimers();
});

describe("reading a NodeChanged event", () => {
  it("takes the node's address, its author and its ops", () => {
    const change = parseNodeChange(payload({ action: "update", ops: [{ op: "set", path: "/rows/0", value: [1] }, { nope: 1 }] }));
    expect(change).toMatchObject({
      nodeId: "abc123def456",
      ref: REF,
      nodeType: "sheets",
      action: "update",
      author: { kind: "assistant", name: "Dodaios", id: "lead" },
      sessionId: "chat-1",
    });
    expect(change?.ops).toEqual([{ op: "set", path: "/rows/0", value: [1] }]);
  });

  it("refuses what is not a node change", () => {
    expect(parseNodeChange(null)).toBeNull();
    expect(parseNodeChange(payload({ node_type: "hologram" }))).toBeNull();
    expect(parseNodeChange(payload({ ref: "no-address" }))).toBeNull();
  });
});

describe("the live store", () => {
  it("marks a node an agent made as being built until the turn ends", () => {
    receive();
    const node = liveNodeOfRef(useNodeLive.getState(), REF);
    expect(node).toMatchObject({ building: true, created: true, sessionId: "chat-1" });
    expect(presenceActive(node)).toBe(true);
    useNodeLive.getState().turnEnded("chat-1");
    const ended = useNodeLive.getState().nodes.abc123def456;
    expect(ended.building).toBe(false);
    // The presence lingers a moment, then it is gone.
    expect(presenceActive(ended, ended.settledAt + PRESENCE_LINGER_MS - 1)).toBe(true);
    expect(presenceActive(ended, ended.settledAt + PRESENCE_LINGER_MS + 1)).toBe(false);
  });

  it("never shows presence for the person's own saves", () => {
    receive({ action: "save", author_kind: "person", author_name: "", author_id: "person", rewrite: true });
    const node = useNodeLive.getState().nodes.abc123def456;
    expect(node.building).toBe(false);
    expect(presenceActive(node)).toBe(false);
  });

  it("settles a build whose agent went quiet", () => {
    vi.useFakeTimers();
    receive();
    vi.advanceTimersByTime(IDLE_SETTLE_MS + 1);
    expect(useNodeLive.getState().nodes.abc123def456.building).toBe(false);
  });

  it("hands an editor the agent's ops for the versions it jumped, or null across a rewrite", () => {
    receive();
    receive({ action: "update", version: 2, previous_version: 1, ops: [{ op: "append", path: "/rows", value: ["a"] }] });
    receive({ action: "update", version: 3, previous_version: 2, ops: [{ op: "append", path: "/rows", value: ["b"] }] });
    const node = useNodeLive.getState().nodes.abc123def456;
    expect(changesBetween(node, 1, 3).ops?.map((op) => op.value)).toEqual([["a"], ["b"]]);
    expect(changesBetween(node, 1, 3)).toMatchObject({ agent: true, created: false });
    receive({ action: "update", version: 4, previous_version: 3, rewrite: true });
    expect(changesBetween(useNodeLive.getState().nodes.abc123def456, 2, 4).ops).toBeNull();
    // A version this window never heard of: play, but without ops.
    expect(changesBetween(useNodeLive.getState().nodes.abc123def456, 0, 6)).toMatchObject({ agent: true, ops: null });
  });

  it("says no agent wrote a range the person alone wrote", () => {
    receive({ action: "save", version: 5, previous_version: 4, author_kind: "person", author_id: "person", rewrite: true });
    expect(changesBetween(useNodeLive.getState().nodes.abc123def456, 4, 5).agent).toBe(false);
  });
});

describe("opening the window by itself", () => {
  it("opens once for an agent's fresh create, not while the person reads another node", () => {
    receive();
    const node = useNodeLive.getState().nodes.abc123def456;
    expect(shouldAutoOpen(node, useAgentChatStore)).toBe(true);
    // The person opened a node themselves: it is left alone.
    useNodePeek.getState().open("run-2::page.html", { chat: useAgentChatStore });
    expect(shouldAutoOpen(node, useAgentChatStore)).toBe(false);
    // A window that opened by itself is swapped.
    useNodePeek.getState().open("run-2::page.html", { chat: useAgentChatStore, auto: true });
    expect(shouldAutoOpen(node, useAgentChatStore)).toBe(true);
    expect(useNodeLive.getState().claimAutoOpen(REF)).toBe(true);
    expect(shouldAutoOpen(node, useAgentChatStore)).toBe(false);
  });

  it("stays shut after the person closed it in this turn, and for an old create", () => {
    receive();
    const node = useNodeLive.getState().nodes.abc123def456;
    useNodeLive.getState().suppress("chat-1");
    expect(shouldAutoOpen(node, useAgentChatStore)).toBe(false);
    useNodeLive.getState().turnEnded("chat-1");
    receive({ action: "update", version: 2, previous_version: 1 });
    const later = useNodeLive.getState().nodes.abc123def456;
    expect(shouldAutoOpen(later, useAgentChatStore, Date.now() + AUTO_OPEN_WITHIN_MS + 1)).toBe(false);
  });

  it("respects the setting", () => {
    receive();
    window.localStorage.setItem("ui.nodeAutoOpen.v1", "off");
    try {
      expect(shouldAutoOpen(useNodeLive.getState().nodes.abc123def456, useAgentChatStore)).toBe(false);
    } finally {
      window.localStorage.removeItem("ui.nodeAutoOpen.v1");
    }
  });
});

describe("the push reaching open views", () => {
  it("hands the node's watcher the new update time, so an open page or editor follows now", () => {
    const client = new QueryClient();
    const key = ["node-upkeep", "20261118T100000__node__abc123def456"];
    client.setQueryData(key, { id: "abc123def456", updated_at: 900, version: 1, title: "Budget" });
    receiveNodeChange(payload({ action: "update", version: 2, previous_version: 1, updated_at: 1_200 }), client);
    expect(client.getQueryData(key)).toMatchObject({ updated_at: 1_200, version: 2 });
    expect(useNodeLive.getState().nodes.abc123def456.version).toBe(2);
  });
});
