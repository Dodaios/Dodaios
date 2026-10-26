import { describe, expect, it, vi } from "vitest";
import { Terminal } from "@xterm/xterm";
import { liveTerminal, liveTerminalsGeneration, registerLiveTerminal, subscribeLiveTerminals } from "./liveTerminals";

describe("live terminal registry", () => {
  it("finds a pane by any of its names and counts its writes", async () => {
    const term = new Terminal({ cols: 10, rows: 2 });
    const listener = vi.fn();
    const stop = subscribeLiveTerminals(listener);
    const before = liveTerminalsGeneration();
    const unregister = registerLiveTerminal("ws1", "T1", term);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(liveTerminalsGeneration()).toBe(before + 1);
    const entry = liveTerminal("ws1", ["Claude", "T1"]);
    expect(entry?.term).toBe(term);
    await new Promise<void>((resolve) => term.write("hi", resolve));
    expect(entry!.version).toBeGreaterThan(0);
    unregister();
    expect(liveTerminal("ws1", ["T1"])).toBeUndefined();
    stop();
    term.dispose();
  });

  it("leaves a newer viewer of the same pane registered", () => {
    const a = new Terminal(), b = new Terminal();
    const offA = registerLiveTerminal("ws2", "T1", a);
    const offB = registerLiveTerminal("ws2", "T1", b);
    offA();
    expect(liveTerminal("ws2", ["T1"])?.term).toBe(b);
    offB();
    expect(liveTerminal("ws2", ["T1"])).toBeUndefined();
    a.dispose(); b.dispose();
  });
});
