import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeAll, beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("@/lib/bootStagger", () => ({ bootSettled: () => Promise.resolve() }));

import { NavRail } from "@/components/layout/NavRail";
import { isDismissed, resetNoticeDismissals, SNOOZE_MS, UNSTAMPED_CLOSE_MS } from "@/components/layout/railNoticeDismiss";
import type { RailNotice } from "@/components/layout/railNotices";
import { useStatusLightStore } from "@/components/layout/statusLightStore";
import { useEventStore } from "@/store/events";

type Plugin = { id: string; display_name: string; status: string; reauth_at?: string | null };

let plugins: Plugin[] = [];
let calls: string[] = [];

function backend() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    if (url === "/api/marketplace/plugins") return json({ plugins });
    if (url.endsWith("/connect/start")) return json({ flow_id: "", kind: "local", open_url: null });
    return new Response("gone", { status: 404 });
  });
}

function renderRail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><NavRail searchOn /></QueryClientProvider>);
}

const GMAIL: Plugin = { id: "gmail", display_name: "Gmail", status: "needs_reauth", reauth_at: "2026-11-13T09:00:00+00:00" };
const NOTION: Plugin = { id: "notion", display_name: "Notion", status: "needs_reauth", reauth_at: "2026-11-13T10:00:00+00:00" };

beforeAll(async () => { await import("@/components/layout/RailNoticeTiles"); });

beforeEach(() => {
  plugins = [];
  calls = [];
  resetNoticeDismissals();
  useStatusLightStore.setState({ light: null, error: false });
  useEventStore.setState({ activeSection: "chats", toasts: [] });
  vi.stubGlobal("fetch", backend());
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("a notice's right-click menu", () => {
  test("opens instead of the app's edit menu and offers the action, an hour off, close and close all", async () => {
    plugins = [GMAIL, NOTION];
    renderRail();
    await waitFor(() => expect(screen.getAllByTestId("rail-notice")).toHaveLength(2));
    const [gmail] = screen.getAllByTestId("rail-notice");
    const event = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 40, clientY: 60 });
    act(() => { gmail.dispatchEvent(event); });
    expect(event.defaultPrevented).toBe(true);
    const menu = screen.getByTestId("rail-notice-menu");
    expect(menu.getAttribute("role")).toBe("menu");
    expect(screen.getByTestId("rail-notice-menu-go").textContent).toBe("Reconnect");
    expect(screen.getByTestId("rail-notice-menu-snooze")).toBeTruthy();
    expect(screen.getByTestId("rail-notice-menu-close")).toBeTruthy();
    expect(screen.getByTestId("rail-notice-menu-close-all").textContent).toContain("2");
  });

  test("Close takes the one tile away and keeps it away across a restart of the rail", async () => {
    plugins = [GMAIL, NOTION];
    const first = renderRail();
    await waitFor(() => expect(screen.getAllByTestId("rail-notice")).toHaveLength(2));
    fireEvent.contextMenu(screen.getAllByTestId("rail-notice")[0]);
    fireEvent.click(screen.getByTestId("rail-notice-menu-close"));
    await waitFor(() => expect(screen.getAllByTestId("rail-notice")).toHaveLength(1));
    expect(screen.getByTestId("rail-notice").dataset.key).toBe("plugin:notion");
    expect(screen.queryByTestId("rail-notice-menu")).toBeNull();
    first.unmount();

    renderRail();
    await waitFor(() => expect(screen.getAllByTestId("rail-notice")).toHaveLength(1));
    expect(screen.getByTestId("rail-notice").dataset.key).toBe("plugin:notion");
  });

  test("Close all empties the rail, and nothing is signed in on the way", async () => {
    plugins = [GMAIL, NOTION];
    renderRail();
    await waitFor(() => expect(screen.getAllByTestId("rail-notice")).toHaveLength(2));
    fireEvent.contextMenu(screen.getAllByTestId("rail-notice")[1]);
    fireEvent.click(screen.getByTestId("rail-notice-menu-close-all"));
    await waitFor(() => expect(screen.queryByTestId("rail-notices")).toBeNull());
    expect(calls.some((url) => url.endsWith("/connect/start"))).toBe(false);
  });

  test("the menu's action does what a click on the tile does", async () => {
    plugins = [GMAIL];
    renderRail();
    fireEvent.contextMenu(await screen.findByTestId("rail-notice"));
    expect(screen.queryByTestId("rail-notice-menu-close-all")).toBeNull();
    fireEvent.click(screen.getByTestId("rail-notice-menu-go"));
    await waitFor(() => expect(calls).toContain("/api/marketplace/plugins/gmail/connect/start"));
  });

  test("Escape leaves the menu without closing the notice", async () => {
    plugins = [GMAIL];
    renderRail();
    fireEvent.contextMenu(await screen.findByTestId("rail-notice"));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("rail-notice-menu")).toBeNull();
    expect(screen.getByTestId("rail-notice")).toBeTruthy();
  });
});

describe("closed and put-off notices", () => {
  const notice = (stamp: string | undefined, title = "Gmail is disconnected"): RailNotice => ({
    key: "plugin:gmail", ask: "reconnect", tone: "trouble", mark: { type: "plugin", id: "gmail" }, subject: "Gmail",
    title, detail: "", action: "Reconnect", count: 1, target: { type: "reconnect", pluginId: "gmail" }, stamp,
  });

  test("a closed notice comes back once it is a new one (new stamp or new words)", () => {
    const now = Date.now();
    const closed = { "plugin:gmail": { sign: `a\u0000Gmail is disconnected`, until: now + 1000 } };
    expect(isDismissed(notice("a"), closed, now)).toBe(true);
    expect(isDismissed(notice("b"), closed, now)).toBe(false);
    expect(isDismissed(notice("a", "Gmail reports a problem"), closed, now)).toBe(false);
  });

  test("a snooze hides whatever the notice says, until it runs out", () => {
    const now = Date.now();
    const snoozed = { "plugin:gmail": { sign: "", until: now + SNOOZE_MS } };
    expect(isDismissed(notice("anything"), snoozed, now)).toBe(true);
    expect(isDismissed(notice("anything"), snoozed, now + SNOOZE_MS)).toBe(false);
  });

  test("a notice without a stamp stays closed for a day only", () => {
    const now = Date.now();
    const closed = { "plugin:gmail": { sign: `\u0000Gmail is disconnected`, until: now + UNSTAMPED_CLOSE_MS } };
    expect(isDismissed(notice(undefined), closed, now + UNSTAMPED_CLOSE_MS - 1)).toBe(true);
    expect(isDismissed(notice(undefined), closed, now + UNSTAMPED_CLOSE_MS)).toBe(false);
  });
});
