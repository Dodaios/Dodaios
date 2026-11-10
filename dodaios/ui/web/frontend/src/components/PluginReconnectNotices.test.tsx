import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/bootStagger", () => ({ bootSettled: () => Promise.resolve() }));
vi.mock("@/lib/openExternal", () => ({ openExternalUrl: vi.fn(async () => true) }));

import { PluginReconnectHost } from "./PluginReconnectHost";
import { PluginReconnectNotices } from "./PluginReconnectNotices";

type Row = { id: string; display_name: string; status: string; reauth_at?: string | null };

let plugins: Row[] = [];

function serve() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/connect/start")) {
      // The sign-in finishes at once: the next plugin list reports connected.
      plugins = plugins.map((p) => (url.includes(`/${p.id}/`) ? { ...p, status: "connected", reauth_at: null } : p));
      return new Response(JSON.stringify({ flow_id: "f1", kind: "local", open_url: null }), { status: 200 });
    }
    return new Response(JSON.stringify({ plugins }), { status: 200 });
  });
}

beforeEach(() => {
  window.localStorage.clear();
  plugins = [
    { id: "notion", display_name: "Notion", status: "needs_reauth", reauth_at: "2026-10-05T15:16:52+00:00" },
    { id: "gmail", display_name: "Gmail", status: "connected" },
  ];
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("plugin reconnect notices", () => {
  it("shows one card per ended connection, none for a healthy plugin", async () => {
    serve();
    render(<PluginReconnectNotices />);
    const card = await screen.findByTestId("plugin-reconnect-notice");
    expect(card.textContent).toContain("Notion");
    expect(card.textContent).not.toContain("Gmail");
    expect(screen.getAllByTestId("plugin-reconnect-notice")).toHaveLength(1);
  });

  it("stays closed for that disconnect and returns for a later one", async () => {
    serve();
    const first = render(<PluginReconnectNotices />);
    fireEvent.click(await screen.findByTestId("plugin-reconnect-dismiss"));
    expect(screen.queryByTestId("plugin-reconnect-notice")).toBeNull();
    first.unmount();

    // The same disconnect after a restart: still closed.
    const second = render(<PluginReconnectNotices />);
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(screen.queryByTestId("plugin-reconnect-notice")).toBeNull();
    second.unmount();

    // Reconnected, then cut off again later: a new notice.
    plugins = [{ id: "notion", display_name: "Notion", status: "needs_reauth", reauth_at: "2026-11-10T08:00:00+00:00" }];
    render(<PluginReconnectNotices />);
    expect((await screen.findByTestId("plugin-reconnect-notice")).textContent).toContain("Notion");
  });

  it("runs the plugin's sign-in and reports the connection", async () => {
    const fetchMock = serve();
    render(<PluginReconnectNotices />);
    fireEvent.click(await screen.findByTestId("plugin-reconnect-connect"));
    await waitFor(
      () => expect(screen.getByTestId("plugin-reconnect-notice").getAttribute("data-state")).toBe("success"),
      { timeout: 6000 },
    );
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/plugins/notion/connect/start"))).toBe(true);
  });

  it("loads the cards only once a connection has ended", async () => {
    plugins = [{ id: "gmail", display_name: "Gmail", status: "connected" }];
    serve();
    const calm = render(<PluginReconnectHost />);
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(screen.queryByTestId("plugin-reconnect-notice")).toBeNull();
    calm.unmount();

    plugins = [{ id: "notion", display_name: "Notion", status: "needs_reauth", reauth_at: null }];
    render(<PluginReconnectHost />);
    expect((await screen.findByTestId("plugin-reconnect-notice")).textContent).toContain("Notion");
  });

  it("shows at most three cards", async () => {
    plugins = ["a", "b", "c", "d", "e"].map((id) => ({
      id,
      display_name: id.toUpperCase(),
      status: "needs_reauth",
      reauth_at: `2026-11-0${id.charCodeAt(0) - 96}T00:00:00+00:00`,
    }));
    serve();
    render(<PluginReconnectNotices />);
    await screen.findAllByTestId("plugin-reconnect-notice");
    const cards = screen.getAllByTestId("plugin-reconnect-notice");
    expect(cards).toHaveLength(3);
    // Newest disconnect first.
    expect(cards[0].textContent).toContain("E");
  });
});
