import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SETTLED_TTL_MS } from "@/lib/commandActivity";
import { useCommandActivityStore } from "./commandActivity";

const T0 = 1_700_000_000_000;

function proposed(command: string) {
  return { tool_name: "run_shell", args: { command } };
}

describe("useCommandActivityStore", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(T0);
    useCommandActivityStore.setState({ entries: [] });
  });

  afterEach(() => {
    // Let the store's tick see the empty list and stop itself.
    useCommandActivityStore.setState({ entries: [] });
    vi.advanceTimersByTime(1_000);
    vi.useRealTimers();
  });

  it("drops a finished command by itself, with no component mounted", () => {
    const { ingest } = useCommandActivityStore.getState();
    ingest("ActionProposed", "t1", proposed("ls"), T0);
    ingest(
      "ActionExecuted",
      "t1",
      { tool_name: "run_shell", success: true, duration_ms: 24 },
      T0,
    );
    expect(useCommandActivityStore.getState().entries).toHaveLength(1);

    vi.advanceTimersByTime(SETTLED_TTL_MS + 1_000);

    expect(useCommandActivityStore.getState().entries).toEqual([]);
  });

  it("keeps a command that still runs", () => {
    useCommandActivityStore
      .getState()
      .ingest("ActionProposed", "t1", proposed("npm test"), T0);

    vi.advanceTimersByTime(SETTLED_TTL_MS + 1_000);

    const entries = useCommandActivityStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0].status).toBe("running");
  });

  it("stops its tick once the list is empty and starts it again", () => {
    const { ingest } = useCommandActivityStore.getState();
    ingest("ActionProposed", "t1", proposed("ls"), T0);
    ingest("ActionExecuted", "t1", { tool_name: "run_shell" }, T0);
    vi.advanceTimersByTime(SETTLED_TTL_MS + 1_000);
    expect(vi.getTimerCount()).toBe(0);

    const later = Date.now();
    ingest("ActionProposed", "t2", proposed("pwd"), later);
    ingest("ActionExecuted", "t2", { tool_name: "run_shell" }, later);
    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(SETTLED_TTL_MS + 1_000);

    expect(useCommandActivityStore.getState().entries).toEqual([]);
    expect(vi.getTimerCount()).toBe(0);
  });
});
