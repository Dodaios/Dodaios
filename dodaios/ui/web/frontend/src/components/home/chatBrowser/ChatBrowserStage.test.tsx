import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { ChatWithBrowser } from "./ChatBrowserStage";
import { requestAgentBrowserStage } from "./openEvent";
import { setAgentBrowserSlot, useAgentBrowserStaged } from "./slot";

vi.mock("@/i18n", () => ({
  fill: (template: string, vars: Record<string, string>) =>
    template.replace(/\{(\w+)\}/g, (_, key: string) => vars[key] ?? ""),
  useT: () => (key: string) => ({
    "sidebar.conversation": "Dodaios",
    "agent_browser.driving": "{assistant} has control",
    "agent_browser.you_drive": "You have control",
    "agent_browser.take_over": "Take over",
    "agent_browser.hand_back": "Hand back",
    "agent_browser.needs_you": "{assistant} needs you here",
    "agent_browser.ready": "Ready",
    "agent_browser.connecting": "Connecting…",
    "agent_browser.private_hint": "Not recorded, not shown to {assistant}.",
  } as Record<string, string>)[key] ?? key,
}));
const { control, view, browser, state } = vi.hoisted(() => ({
  control: vi.fn(),
  view: vi.fn(),
  browser: { open: true, running: true, mode: "own" },
  state: {
    connected: true, ready: true, fullWindow: false, extendedInput: false, previewPaused: false,
    loginAvailable: false, loginMode: false, loginReady: false, manual: false, running: true,
    controlPending: false, url: "https://www.example.com/flights", tabs: [], target: "", error: "",
    takeoverRequest: undefined as undefined | { id: string; reason: string },
    pointer: undefined as undefined | Record<string, number>,
  },
}));
vi.mock("@/components/society/cardData", () => ({
  useAgentBrowserOpen: () => ({ data: browser }),
}));
vi.mock("@/components/society/card/useBrowserView", () => ({
  useBrowserView: (agentId: string, enabled: boolean) => {
    view(agentId, enabled);
    return { canvas: { current: null }, state, control, approve: vi.fn() };
  },
}));

function mount() {
  return render(<ChatWithBrowser><div data-testid="the-chat">chat</div></ChatWithBrowser>);
}

afterEach(() => {
  cleanup();
  act(() => setAgentBrowserSlot(null));
  control.mockClear();
  view.mockClear();
  browser.open = true; browser.running = true; browser.mode = "own";
  state.manual = false; state.running = true; state.ready = true; state.takeoverRequest = undefined;
});

describe("the chat's browser stage", () => {
  test("shows a live tile over the chat while the assistant browses", () => {
    mount();
    expect(screen.getByTestId("the-chat")).toBeTruthy();
    const surface = screen.getByTestId("chat-browser");
    expect(surface.dataset.layout).toBe("tile");
    expect(surface.dataset.driver).toBe("agent");
    expect(screen.getByTestId("chat-browser-status").textContent).toBe("Dodaios has control · example.com");
    expect(view).toHaveBeenLastCalledWith("jarvis", true);
  });

  test("never attaches to a browser that is not open, so watching launches nothing", () => {
    browser.open = false; browser.running = false;
    mount();
    expect(screen.queryByTestId("chat-browser")).toBeNull();
    expect(view).toHaveBeenLastCalledWith("jarvis", false);
  });

  test("an open browser with no task stays out of the way", () => {
    browser.running = false;
    mount();
    expect(screen.queryByTestId("chat-browser")).toBeNull();
  });

  test("a click on the tile opens the stage and never takes control", () => {
    mount();
    fireEvent.click(screen.getByTestId("chat-browser-open-stage"));
    expect(screen.getByTestId("chat-browser").dataset.layout).toBe("stage");
    expect(control).not.toHaveBeenCalled();
    expect(screen.getByTestId("chat-browser-control").textContent).toContain("Dodaios has control");
  });

  test("take over and hand back go through the browser's control lease", () => {
    mount();
    fireEvent.click(screen.getByTestId("chat-browser-open-stage"));
    fireEvent.click(screen.getByTestId("chat-browser-take-over"));
    expect(control).toHaveBeenLastCalledWith("takeover", { enabled: true });
    state.manual = true;
    cleanup();
    mount();
    fireEvent.click(screen.getByTestId("chat-browser-open-stage"));
    expect(screen.getByTestId("chat-browser").dataset.driver).toBe("person");
    fireEvent.click(screen.getByTestId("chat-browser-hand-back"));
    expect(control).toHaveBeenLastCalledWith("takeover", { enabled: false });
  });

  test("a request for a hand brings the stage up by itself", () => {
    state.takeoverRequest = { id: "r1", reason: "Please solve the CAPTCHA." };
    mount();
    expect(screen.getByTestId("chat-browser").dataset.layout).toBe("stage");
    expect(screen.getByRole("alert").textContent).toBe("Please solve the CAPTCHA.");
  });

  test("hiding the tile keeps it away while the same task runs", () => {
    mount();
    fireEvent.click(screen.getByTestId("chat-browser-hide"));
    expect(screen.queryByTestId("chat-browser")).toBeNull();
  });

  test("the takeover card in this chat opens the stage here", () => {
    browser.running = false;
    mount();
    expect(screen.queryByTestId("chat-browser")).toBeNull();
    let taken = false;
    act(() => { taken = requestAgentBrowserStage("jarvis"); });
    expect(taken).toBe(true);
    expect(screen.getByTestId("chat-browser").dataset.layout).toBe("stage");
    expect(requestAgentBrowserStage("scout")).toBe(false);
  });

  test("with the assistant's panel open the tile stands among its computers, not over the chat", () => {
    const slot = document.createElement("div");
    document.body.appendChild(slot);
    act(() => setAgentBrowserSlot(slot));
    const { container } = mount();
    const tile = screen.getByTestId("chat-browser");
    expect(tile.dataset.docked).toBe("true");
    expect(slot.contains(tile)).toBe(true);
    expect(container.contains(tile)).toBe(false);
    // Opened large, the stage comes back beside the chat and takes the panel's place.
    let staged = false;
    function Probe() { staged = useAgentBrowserStaged(); return null; }
    render(<Probe />);
    expect(staged).toBe(false);
    fireEvent.click(screen.getByTestId("chat-browser-open-stage"));
    const stage = screen.getByTestId("chat-browser");
    expect(stage.dataset.layout).toBe("stage");
    expect(container.contains(stage)).toBe(true);
    expect(staged).toBe(true);
    fireEvent.click(screen.getByTestId("chat-browser-resize"));
    expect(staged).toBe(false);
    slot.remove();
  });
});
