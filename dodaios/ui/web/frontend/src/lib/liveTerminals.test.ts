import { describe, expect, it, vi } from "vitest";
import { Terminal } from "@xterm/xterm";
import { liveTerminal, liveTerminalsGeneration, presentTerminal, registerLiveTerminal, registerTerminalPresenter, subscribeLiveTerminals } from "./liveTerminals";

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

describe("terminal presenter", () => {
  it("places a pane by any of its names and releases only that presenter", () => {
    const host = { nodeType: 1 } as HTMLElement;
    const release = vi.fn();
    const present = vi.fn(() => release);
    const listener = vi.fn();
    const stop = subscribeLiveTerminals(listener);
    const before = liveTerminalsGeneration();
    const unregister = registerTerminalPresenter("ws1", "T1", present);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(liveTerminalsGeneration()).toBe(before + 1);
    expect(presentTerminal("ws1", ["Claude", "T1"], host)).toBe(release);
    expect(present).toHaveBeenCalledWith(host);
    expect(presentTerminal("ws9", ["T1"], host)).toBeNull();
    unregister();
    expect(presentTerminal("ws1", ["T1"], host)).toBeNull();
    stop();
  });

  it("leaves a newer presenter of the same pane registered", () => {
    const first = vi.fn(() => () => undefined);
    const second = vi.fn(() => () => undefined);
    const offFirst = registerTerminalPresenter("ws2", "T1", first);
    const offSecond = registerTerminalPresenter("ws2", "T1", second);
    offFirst();
    const host = { nodeType: 1 } as HTMLElement;
    presentTerminal("ws2", ["T1"], host);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledWith(host);
    offSecond();
    expect(presentTerminal("ws2", ["T1"], host)).toBeNull();
  });
});
