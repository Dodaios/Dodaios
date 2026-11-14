import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BrowserViewState } from "@/components/society/card/useBrowserView";
import { IDLE_HANDBACK_MS, LiveBrowserPage, type LiveRequest } from "./LiveBrowserPage";

const view = vi.hoisted(() => ({
  control: vi.fn(),
  state: {} as BrowserViewState,
  enabled: [] as boolean[],
}));

vi.mock("@/components/society/card/useBrowserView", () => ({
  useBrowserView: (_agent: string, enabled: boolean) => {
    view.enabled.push(enabled);
    return { canvas: { current: null }, state: view.state, control: view.control, approve: vi.fn(), repaint: vi.fn() };
  },
}));

function viewState(patch: Partial<BrowserViewState> = {}): BrowserViewState {
  return {
    connected: true, ready: true, fullWindow: false, extendedInput: false, previewPaused: false,
    loginAvailable: false, loginMode: false, loginReady: false, manual: false, running: false,
    controlPending: false, url: "about:blank", tabs: [], target: "", error: "", ...patch,
  };
}

function page(request: LiveRequest | null, onPageUrl = vi.fn()) {
  return <LiveBrowserPage request={request} onPageUrl={onPageUrl} />;
}

beforeEach(() => {
  view.control.mockReset();
  view.enabled = [];
  view.state = viewState();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("LiveBrowserPage", () => {
  it("takes control and then opens the address the person typed", () => {
    const request = { id: 1, url: "https://github.com/" };
    const { rerender } = render(page(request));
    expect(view.control).toHaveBeenCalledWith("takeover", { enabled: true });
    expect(view.control).not.toHaveBeenCalledWith("navigate", expect.anything());
    view.state = viewState({ manual: true });
    rerender(page(request));
    expect(view.control).toHaveBeenCalledWith("navigate", { url: "https://github.com/" });
    view.control.mockClear();
    rerender(page(request));
    expect(view.control).not.toHaveBeenCalledWith("navigate", expect.anything());
  });

  it("waits for the browser's first picture before acting", () => {
    view.state = viewState({ ready: false });
    render(page({ id: 1, url: "https://github.com/" }));
    expect(view.control).not.toHaveBeenCalled();
    expect(screen.getByTestId("ide-browser-live-waiting").textContent).toContain("Connecting");
  });

  it("never takes the page from the assistant for an address restored from the last session", () => {
    view.state = viewState({ url: "https://www.google.com/travel/flights", running: true });
    render(page({ id: 0, url: "https://github.com/", onlyIfBlank: true }));
    expect(view.control).not.toHaveBeenCalled();
    expect(screen.getByTestId("ide-browser-live-status").textContent).toContain("has control");
  });

  it("opens the restored address on a blank browser", () => {
    view.state = viewState({ manual: true, url: "about:blank" });
    render(page({ id: 0, url: "https://github.com/", onlyIfBlank: true }));
    expect(view.control).toHaveBeenCalledWith("navigate", { url: "https://github.com/" });
  });

  it("gives up on an address when control cannot be taken", () => {
    const request = { id: 1, url: "https://github.com/" };
    const { rerender } = render(page(request));
    for (const pending of [true, false, true, false, true, false]) {
      view.state = viewState({ controlPending: pending });
      rerender(page(request));
    }
    expect(view.control.mock.calls.filter(([op]) => op === "takeover")).toHaveLength(2);
  });

  it("hands control back to the assistant after a pause without input", () => {
    vi.useFakeTimers();
    view.state = viewState({ manual: true, url: "https://github.com/" });
    render(page(null));
    act(() => { vi.advanceTimersByTime(IDLE_HANDBACK_MS + 2_000); });
    expect(view.control).toHaveBeenCalledWith("takeover", { enabled: false });
  });

  it("keeps control while the assistant waits for the person", () => {
    vi.useFakeTimers();
    view.state = viewState({ manual: true, takeoverRequest: { id: "r1", reason: "Sign in" } });
    render(page(null));
    act(() => { vi.advanceTimersByTime(IDLE_HANDBACK_MS * 3); });
    expect(view.control).not.toHaveBeenCalledWith("takeover", { enabled: false });
  });

  it("reports the page the browser shows for the address bar", () => {
    const onPageUrl = vi.fn();
    view.state = viewState({ url: "https://github.com/Dodaios" });
    render(page(null, onPageUrl));
    expect(onPageUrl).toHaveBeenCalledWith("https://github.com/Dodaios");
  });

  it("says when the assistant needs the person here", () => {
    view.state = viewState({ takeoverRequest: { id: "r1", reason: "Solve the CAPTCHA" } });
    render(page(null));
    const status = screen.getByTestId("ide-browser-live-status");
    expect(status.textContent).toContain("needs you here");
    expect(status.textContent).toContain("Solve the CAPTCHA");
  });
});
