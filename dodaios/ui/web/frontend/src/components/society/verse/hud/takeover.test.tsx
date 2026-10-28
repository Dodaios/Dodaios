import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEventStore } from "@/store/events";
import { useIdeChatStore } from "@/store/ideChat";
import { useIdeSidePanelStore } from "@/store/ideSidePanel";
import { keyToTerminalData, leavesTakeover } from "../effects/terminalKeys";

const termApi = vi.hoisted(() => {
  const focus = vi.fn();
  const release = vi.fn();
  const api = {
    focus,
    release,
    last: null as { workspaceId: string; names: readonly string[]; host: HTMLElement } | null,
    presentTerminal: vi.fn((workspaceId: string, names: readonly string[], host: HTMLElement): (() => void) | null => {
      api.last = { workspaceId, names, host };
      return release;
    }),
    liveTerminal: vi.fn(() => ({ term: { focus } })),
    subscribeLiveTerminals: vi.fn(() => () => undefined),
    liveTerminalsGeneration: vi.fn(() => 0),
  };
  return api;
});

vi.mock("@/lib/liveTerminals", () => ({
  presentTerminal: termApi.presentTerminal,
  liveTerminal: termApi.liveTerminal,
  subscribeLiveTerminals: termApi.subscribeLiveTerminals,
  liveTerminalsGeneration: termApi.liveTerminalsGeneration,
}));

vi.mock("@/components/agentic/AgenticTerminal", () => ({
  AgenticTerminal: ({ name, workspaceId }: { name: string; workspaceId?: string }) => (
    <div data-testid="verse-takeover-spare" data-name={name} data-workspace={workspaceId ?? ""} />
  ),
}));

import { TakeoverPanel } from "./TakeoverPanel";

const key = (k: string, mods: Partial<{ ctrlKey: boolean; altKey: boolean; metaKey: boolean; shiftKey: boolean }> = {}) =>
  ({ key: k, ctrlKey: false, altKey: false, metaKey: false, shiftKey: false, ...mods });

const restore: Array<() => void> = [];

function spyGetState(store: { getState: () => unknown }, value: unknown): void {
  const spy = vi.spyOn(store, "getState").mockReturnValue(value);
  restore.push(() => spy.mockRestore());
}

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

  beforeEach(() => {
    termApi.last = null;
    termApi.focus.mockClear();
    termApi.release.mockClear();
    termApi.liveTerminal.mockClear();
    termApi.presentTerminal.mockClear();
    termApi.presentTerminal.mockImplementation((workspaceId: string, names: readonly string[], host: HTMLElement) => {
      termApi.last = { workspaceId, names, host };
      return termApi.release;
    });
  });

  afterEach(() => {
    cleanup();
    while (restore.length) restore.pop()?.();
  });

  it("presents the live pane in the window and leaves only on Ctrl+Q", () => {
    const onClose = vi.fn();
    const view = render(<TakeoverPanel tile={tile} t={t} onClose={onClose} />);
    expect(document.querySelector("canvas")).toBeNull();
    expect(screen.queryByLabelText("verse.takeover.keys")).toBeNull();
    expect(termApi.presentTerminal).toHaveBeenCalledWith("ws1", tile.names, expect.any(HTMLElement));
    expect(termApi.last?.host).toBeInstanceOf(HTMLElement);
    expect(screen.queryByTestId("verse-takeover-spare")).toBeNull();
    expect(termApi.focus).toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "q", ctrlKey: true });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(termApi.release).not.toHaveBeenCalled();
    view.unmount();
    expect(termApi.release).toHaveBeenCalledTimes(1);
  });

  it("leaves for the Agentic IDE and opens the pane's changes", () => {
    const onClose = vi.fn();
    const setActiveSection = vi.fn();
    const requestPane = vi.fn();
    const setMaximized = vi.fn();
    spyGetState(useEventStore, { activeSection: "chats", setActiveSection });
    spyGetState(useIdeChatStore, { requestPane });
    spyGetState(useIdeSidePanelStore, { setMaximized });
    render(<TakeoverPanel tile={tile} t={t} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "verse.takeover.changes" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(setActiveSection).toHaveBeenCalledWith("agentic-ide");
    expect(requestPane).toHaveBeenCalledWith("ws1", "mika", { open: "changes" });
    expect(setMaximized).toHaveBeenCalledWith(false);
  });

  it("does not switch section when the Agentic IDE is already open", () => {
    const setActiveSection = vi.fn();
    const requestPane = vi.fn();
    const setMaximized = vi.fn();
    spyGetState(useEventStore, { activeSection: "agentic-ide", setActiveSection });
    spyGetState(useIdeChatStore, { requestPane });
    spyGetState(useIdeSidePanelStore, { setMaximized });
    render(<TakeoverPanel tile={tile} t={t} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "verse.takeover.changes" }));
    expect(setActiveSection).not.toHaveBeenCalled();
    expect(requestPane).toHaveBeenCalledWith("ws1", "mika", { open: "changes" });
    expect(setMaximized).toHaveBeenCalledWith(false);
  });

  it("shows the screen and opens the pane when the IDE grid has not mounted it", () => {
    termApi.presentTerminal.mockReturnValue(null);
    const onClose = vi.fn();
    render(<TakeoverPanel tile={{ ...tile, workspaceId: "elsewhere", fallback: { cols: 80, lines: ["Still waiting."], cursor: null, at: 1 } }} t={t} onClose={onClose} />);
    expect(screen.getByText("Still waiting.")).toBeTruthy();
    expect(screen.getByTestId("verse-takeover-spare").getAttribute("data-name")).toBe("mika");
    expect(screen.getByTestId("verse-takeover-spare").getAttribute("data-workspace")).toBe("elsewhere");
    expect(screen.queryByPlaceholderText("verse.takeover.placeholder")).toBeNull();
    expect(termApi.focus).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "q", ctrlKey: true });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not open a second pane when the IDE grid already has this one", () => {
    termApi.presentTerminal.mockReturnValue(null);
    const view = document.createElement("div");
    view.setAttribute("data-workspace-terminal-view", "ws1");
    const host = document.createElement("div");
    host.setAttribute("data-testid", "agentic-terminal-host-mika");
    view.appendChild(host);
    document.body.appendChild(view);
    render(<TakeoverPanel tile={{ ...tile, fallback: { cols: 40, lines: ["still working"], cursor: null, at: 2 } }} t={t} onClose={vi.fn()} />);
    expect(screen.queryByTestId("verse-takeover-spare")).toBeNull();
    expect(screen.getByText("still working")).toBeTruthy();
    view.remove();
  });
});
