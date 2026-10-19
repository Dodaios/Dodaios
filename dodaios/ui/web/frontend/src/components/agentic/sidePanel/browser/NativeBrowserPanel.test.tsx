import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { BrowserTab } from "./BrowserTab";
import { initialChoice, type NativeBrowser } from "./nativeBrowserApi";
import { boxesOverlap, measurePanel, overlayCovers } from "./useNativePlacement";

const BROWSERS: NativeBrowser[] = [{
  id: "chrome",
  label: "Google Chrome",
  profiles: [
    { directory: "Profile 7", name: "kontakt", email: "kontakt@example.com" },
    { directory: "Profile 3", name: "Profil 1", email: "me@example.com" },
  ],
  last_used: "Profile 3",
}];

function rect(x: number, y: number, width: number, height: number): DOMRect {
  return { x, y, width, height, left: x, top: y, right: x + width, bottom: y + height, toJSON: () => ({}) } as DOMRect;
}

describe("placement helpers", () => {
  afterEach(() => cleanup());

  it("detects overlapping boxes, not touching ones", () => {
    expect(boxesOverlap(rect(0, 0, 10, 10), rect(5, 5, 10, 10))).toBe(true);
    expect(boxesOverlap(rect(0, 0, 10, 10), rect(10, 0, 10, 10))).toBe(false);
  });

  it("reports a hidden panel as hidden", () => {
    const panel = document.createElement("div");
    document.body.appendChild(panel);
    panel.getBoundingClientRect = () => rect(0, 0, 0, 0);
    expect(measurePanel(panel, "p").visible).toBe(false);
    expect(measurePanel(null, "p").visible).toBe(false);
    panel.remove();
  });

  it("hides the browser while an app menu covers the panel", () => {
    const panel = document.createElement("div");
    panel.getBoundingClientRect = () => rect(100, 100, 400, 400);
    const menu = document.createElement("div");
    menu.setAttribute("role", "menu");
    menu.getBoundingClientRect = () => rect(300, 80, 200, 100);
    document.body.append(panel, menu);
    expect(overlayCovers(panel)).toBe(true);
    expect(measurePanel(panel, "p").visible).toBe(false);
    menu.getBoundingClientRect = () => rect(0, 0, 50, 50);
    expect(measurePanel(panel, "p")).toMatchObject({ visible: true, rect: { x: 100, y: 100, width: 400, height: 400 } });
    panel.remove();
    menu.remove();
  });
});

describe("initialChoice", () => {
  beforeEach(() => localStorage.clear());

  it("uses the browser's own last profile first", () => {
    expect(initialChoice(BROWSERS)).toEqual({ browser: "chrome", profile: "Profile 3" });
  });

  it("keeps a remembered profile that still exists", () => {
    localStorage.setItem("jarvis.agenticIde.browserProfile.v1", JSON.stringify({ browser: "chrome", profile: "Profile 7" }));
    expect(initialChoice(BROWSERS)).toEqual({ browser: "chrome", profile: "Profile 7" });
    localStorage.setItem("jarvis.agenticIde.browserProfile.v1", JSON.stringify({ browser: "chrome", profile: "Gone" }));
    expect(initialChoice(BROWSERS)).toEqual({ browser: "chrome", profile: "Profile 3" });
  });

  it("has nothing to offer without a browser", () => {
    expect(initialChoice([])).toBeNull();
  });
});

describe("BrowserTab on the desktop app", () => {
  const host = window as unknown as { __JARVIS_EMBEDDED_DESKTOP?: boolean };

  beforeEach(() => {
    localStorage.clear();
    host.__JARVIS_EMBEDDED_DESKTOP = true;
  });

  afterEach(() => {
    cleanup();
    delete host.__JARVIS_EMBEDDED_DESKTOP;
    vi.unstubAllGlobals();
  });

  function renderTab(status: Record<string, unknown>) {
    const fetchMock = vi.fn(async (url: string) => ({
      ok: true,
      json: async () => (url.endsWith("/status") ? status : { ...status, ok: true }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><BrowserTab /></QueryClientProvider>);
    return fetchMock;
  }

  it("shows the user's own browser with a profile picker", async () => {
    renderTab({ available: true, reason: "", state: "idle", browsers: BROWSERS });
    await waitFor(() => expect(screen.getByTestId("ide-browser-tab").dataset.mode).toBe("native"));
    expect(screen.getByTestId("ide-browser-profile")).toBeTruthy();
    expect(screen.queryByTestId("ide-browser-frame")).toBeNull();
  });

  it("offers reopening after the window was closed", async () => {
    renderTab({ available: true, reason: "", state: "closed", browser: "chrome", profile: "Profile 3", browsers: BROWSERS });
    await waitFor(() => expect(screen.getByTestId("ide-browser-reopen")).toBeTruthy());
  });

  it("falls back to the built-in view where the browser cannot be shown", async () => {
    renderTab({ available: false, reason: "no_browser", state: "idle", browsers: [] });
    await waitFor(() => expect(screen.getByTestId("ide-browser-address")).toBeTruthy());
    expect(screen.queryByTestId("ide-browser-use-native")).toBeNull();
  });
});
