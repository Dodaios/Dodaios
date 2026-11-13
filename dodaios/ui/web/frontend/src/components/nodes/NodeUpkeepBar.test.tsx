/**
 * The strip above a kept-current node on the stage.
 *
 * Contracts worth pinning:
 * - a typed node is recognised by its run slug (`__node__`),
 * - the strip reads the node by that slug and says when it was updated and
 *   how often the assistant looks again; it reports the update time upward
 *   so the stage can reload the page,
 * - it renders nothing for a node that is not kept current, and nothing for
 *   a slug the server does not know,
 * - one button pauses and resumes the upkeep through the nodes API, and the
 *   strip follows the answer,
 * - a scheduler that is down (503) is said as that, not as a generic failure.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import NodeUpkeepBar, { isNodeSlug } from "./NodeUpkeepBar";
import type { NodeState } from "./useNodes";

const SLUG = "2026-11-13__node__n1";

function state(over: Partial<NodeState> = {}): NodeState {
  return {
    id: "n1",
    type: "data",
    title: "Revenue dashboard",
    slug: SLUG,
    page_path: "index.html",
    version: 3,
    updated_at: Math.floor(Date.now() / 1000) - 600,
    track: "Revenue per month, from the shop's export",
    every_minutes: 60,
    refreshing: true,
    note: "",
    visual_id: `${SLUG}::index.html`,
    page_url: `/api/outputs/${SLUG}/files/index.html/page`,
    spec: {},
    ...over,
  };
}

interface Call {
  url: string;
  method: string;
}

interface Api {
  node: NodeState | null;
  /** The status the upkeep endpoints answer with (200: the node, toggled). */
  upkeepStatus?: number;
}

function installFetch(api: Api): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ url, method });
      if (url.startsWith("/api/nodes/by-slug/")) {
        if (api.node === null) return { ok: false, status: 404, json: async () => ({ detail: "unknown" }) };
        return { ok: true, status: 200, json: async () => api.node };
      }
      const upkeep = /\/api\/nodes\/[^/]+\/upkeep\/(stop|resume)$/.exec(url);
      if (upkeep && api.node) {
        const status = api.upkeepStatus ?? 200;
        if (status !== 200) return { ok: false, status, json: async () => ({ detail: "refused" }) };
        api.node = { ...api.node, refreshing: upkeep[1] === "resume" };
        return { ok: true, status: 200, json: async () => api.node };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    }),
  );
  return calls;
}

function renderBar(onUpdated?: (updatedAt: number) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <NodeUpkeepBar slug={SLUG} onUpdated={onUpdated} />
    </QueryClientProvider>,
  );
  return { invalidate };
}

const toggle = () => screen.getByTestId("node-upkeep-toggle") as HTMLButtonElement;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("isNodeSlug", () => {
  it("recognises the run directory of a typed node", () => {
    expect(isNodeSlug(SLUG)).toBe(true);
    expect(isNodeSlug("2026-11-05__living-page__open-invoices")).toBe(false);
    expect(isNodeSlug("mission_dash")).toBe(false);
    expect(isNodeSlug("")).toBe(false);
    expect(isNodeSlug(null)).toBe(false);
    expect(isNodeSlug(undefined)).toBe(false);
  });
});

describe("NodeUpkeepBar", () => {
  it("says when the node was updated and how often it is looked at", async () => {
    const node = state();
    const calls = installFetch({ node });
    const onUpdated = vi.fn();
    renderBar(onUpdated);

    const bar = await screen.findByTestId("node-upkeep-bar");
    expect(calls[0]).toEqual({ url: `/api/nodes/by-slug/${SLUG}?spec=0`, method: "GET" });
    expect(bar.textContent).toContain("10 minutes ago");
    expect(bar.textContent).toContain("1 hour");
    expect(onUpdated).toHaveBeenCalledWith(node.updated_at);
  });

  it("renders nothing for a node that is not kept current", async () => {
    const node = state({ track: "", refreshing: false, every_minutes: 0 });
    installFetch({ node });
    const onUpdated = vi.fn();
    renderBar(onUpdated);

    // The answer arrived (the update time was reported), and still no strip.
    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(node.updated_at));
    expect(screen.queryByTestId("node-upkeep-bar")).toBeNull();
  });

  it("renders nothing for a slug the server does not know", async () => {
    const calls = installFetch({ node: null });
    renderBar();
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    await Promise.resolve();
    expect(screen.queryByTestId("node-upkeep-bar")).toBeNull();
  });

  it("pauses and resumes the upkeep with one button", async () => {
    const calls = installFetch({ node: state() });
    const { invalidate } = renderBar();
    await screen.findByTestId("node-upkeep-bar");

    const pause = toggle().textContent;
    fireEvent.click(toggle());
    await waitFor(() => expect(toggle().textContent).not.toBe(pause));
    expect(calls.at(-1)).toEqual({ url: "/api/nodes/n1/upkeep/stop", method: "POST" });
    // A paused node no longer says how often it is looked at.
    expect(screen.getByTestId("node-upkeep-bar").textContent).not.toContain("1 hour");
    // The library's card says "paused" too: it is read again.
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["nodes"] });

    fireEvent.click(toggle());
    await waitFor(() => expect(toggle().textContent).toBe(pause));
    expect(calls.at(-1)).toEqual({ url: "/api/nodes/n1/upkeep/resume", method: "POST" });
    expect(screen.getByTestId("node-upkeep-bar").textContent).toContain("1 hour");
  });

  it("says that updates are unavailable when the scheduler is down", async () => {
    const api: Api = { node: state(), upkeepStatus: 503 };
    installFetch(api);
    renderBar();
    await screen.findByTestId("node-upkeep-bar");

    fireEvent.click(toggle());
    const unavailable = (await screen.findByRole("alert")).textContent;
    expect(unavailable).toBeTruthy();

    // Any other refusal reads differently.
    api.upkeepStatus = 500;
    fireEvent.click(toggle());
    await waitFor(() => expect(screen.getByRole("alert").textContent).not.toBe(unavailable));
    // And the strip still shows the node as it is.
    expect(screen.getByTestId("node-upkeep-bar").textContent).toContain("1 hour");
  });
});
