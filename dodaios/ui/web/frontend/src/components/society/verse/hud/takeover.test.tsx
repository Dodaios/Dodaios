import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Terminal } from "@xterm/xterm";
import { PANE_INPUT_EVENT, type PaneInputDetail } from "@/components/agentic/ideHotkeys";
import { registerLiveTerminal } from "@/lib/liveTerminals";
import { keyToTerminalData, leavesTakeover } from "../effects/terminalKeys";
import { TakeoverPanel } from "./TakeoverPanel";

const key = (k: string, mods: Partial<{ ctrlKey: boolean; altKey: boolean; metaKey: boolean; shiftKey: boolean }> = {}) =>
  ({ key: k, ctrlKey: false, altKey: false, metaKey: false, shiftKey: false, ...mods });

describe("keys to a taken-over terminal", () => {
  it("sends what a terminal sends", () => {
    expect(keyToTerminalData(key("a"))).toBe("a");
    expect(keyToTerminalData(key("A", { shiftKey: true }))).toBe("A");
    expect(keyToTerminalData(key("Enter"))).toBe("\r");
    expect(keyToTerminalData(key("Backspace"))).toBe("\x7f");
    expect(keyToTerminalData(key("Escape"))).toBe("\x1b");
    expect(keyToTerminalData(key("ArrowUp"))).toBe("\x1b[A");
    expect(keyToTerminalData(key("Tab", { shiftKey: true }))).toBe("\x1b[Z");
    expect(keyToTerminalData(key("c", { ctrlKey: true }))).toBe("\x03");
    expect(keyToTerminalData(key("b", { altKey: true }))).toBe("\x1bb");
    expect(keyToTerminalData(key("Shift", { shiftKey: true }))).toBeNull();
    expect(keyToTerminalData(key("F5"))).toBeNull();
  });

  it("leaves on Ctrl+Q only", () => {
    expect(leavesTakeover(key("q", { ctrlKey: true }))).toBe(true);
    expect(leavesTakeover(key("Escape"))).toBe(false);
    expect(leavesTakeover(key("q"))).toBe(false);
  });
});

describe("TakeoverPanel", () => {
  const t = (k: string) => k;
  const tile = { header: { title: "Mika", status: "Working", tone: "live" as const }, workspaceId: "ws1", names: ["mika", "mika"] };
  let unregister: (() => void) | null = null;
  afterEach(() => { unregister?.(); unregister = null; });

  it("types every key into the live pane without taking its focus, once per pane, and Ctrl+Q leaves", () => {
    const term = { cols: 80, rows: 24, buffer: { active: { length: 0, viewportY: 0, getLine: () => undefined, cursorX: 0, cursorY: 0 } }, options: { theme: {} } } as unknown as Terminal;
    unregister = registerLiveTerminal("ws1", "mika", term);
    const seen: PaneInputDetail[] = [];
    const listen = (e: Event) => seen.push((e as CustomEvent<PaneInputDetail>).detail);
    window.addEventListener(PANE_INPUT_EVENT, listen);
    const onClose = vi.fn();
    render(<TakeoverPanel tile={tile} t={t} onClose={onClose} />);
    const keys = screen.getByLabelText("verse.takeover.keys");
    fireEvent.keyDown(keys, { key: "h" });
    fireEvent.keyDown(keys, { key: "Enter" });
    fireEvent.keyDown(keys, { key: "Escape" });
    expect(seen.map((d) => d.data)).toEqual(["h", "\r", "\x1b"]);
    expect(seen.every((d) => d.focus === false && d.workspaceId === "ws1" && d.pane === "mika")).toBe(true);
    // Escape went to the agent; the terminal stays open.
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(keys, { key: "q", ctrlKey: true });
    expect(onClose).toHaveBeenCalledTimes(1);
    window.removeEventListener(PANE_INPUT_EVENT, listen);
  });

  it("offers a prompt line for a pane the IDE has not mounted", () => {
    render(<TakeoverPanel tile={{ ...tile, workspaceId: "elsewhere" }} t={t} onClose={() => undefined} />);
    expect(screen.queryByLabelText("verse.takeover.keys")).toBeNull();
    expect(screen.getByPlaceholderText("verse.takeover.placeholder")).toBeTruthy();
  });
});
