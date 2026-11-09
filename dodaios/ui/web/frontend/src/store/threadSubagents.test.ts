import { beforeEach, describe, expect, it } from "vitest";
import { useThreadSubagentsStore } from "./threadSubagents";

describe("the open sub-agent", () => {
  beforeEach(() => useThreadSubagentsStore.setState({ sessionId: null, rows: [], open: null }));

  it("closes only for its own thread", () => {
    const store = useThreadSubagentsStore.getState();
    store.openAgent("main", "agent-1");

    // A side column on another thread sends a message: the main column's sub-agent stays open.
    store.openAgent("side", null);
    expect(useThreadSubagentsStore.getState().open).toEqual({ sessionId: "main", id: "agent-1" });

    store.openAgent("main", null);
    expect(useThreadSubagentsStore.getState().open).toBeNull();
  });
});
