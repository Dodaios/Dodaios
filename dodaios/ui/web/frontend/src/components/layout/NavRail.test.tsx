import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { NavRail, tileInitials } from "@/components/layout/NavRail";
import { useStatusLightStore, type StatusLightData, type StatusRow } from "@/components/layout/statusLightStore";
import { useEventStore } from "@/store/events";

const FAVORITES_KEY = "jarvis.artifacts.favorites";

function running(id: string, title: string): StatusRow {
  return { kind: "pane", id, title, state: "busy", link: { section: "agentic-ide" } };
}

const BUSY: StatusLightData = {
  counts: { running: 4, needs_you: 2 },
  needs_you: [
    { kind: "credential", id: "c1", title: "Hacker News", state: "waiting", link: { section: "apikeys" } },
    { kind: "question", id: "q1", title: "Which database?", state: "waiting", link: { section: "board" } },
  ],
  running: [running("t1", "Agent 1"), running("t2", "Agent 2"), running("t3", "Agent 3"), running("t4", "Agent 4")],
  trouble: [{ provider: "openai", account: "", class: "quota", reason: "x", blocked: false }],
  findings: [{ id: "f1", kind: "silent_turn", title: "Turn is silent" }],
  tone: "warn",
};

/** Answers the rail's reads: the status light, the run list and one listing per run. */
function backend(runs: { slug: string; status?: string; files: { path: string; title?: string }[] }[], light: StatusLightData | null = null) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    if (url === "/api/status-light") return light ? json(light) : new Response("no", { status: 500 });
    if (url === "/api/outputs") return json(runs.map(({ slug, status }) => ({ slug, status: status ?? "success" })));
    const match = /^\/api\/outputs\/([^/]+)\/artifacts$/.exec(url);
    const run = match && runs.find((candidate) => candidate.slug === decodeURIComponent(match[1]));
    if (!run) return new Response("gone", { status: 404 });
    return json({ files: run.files.map((file, index) => ({ size: 1, mtime: index + 1, is_text: true, preview: null, ...file })) });
  });
}

function renderRail(pluginsWarn: string | null = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><NavRail searchOn pluginsWarn={pluginsWarn} /></QueryClientProvider>);
}

beforeEach(() => {
  window.localStorage.removeItem(FAVORITES_KEY);
  useStatusLightStore.setState({ light: null, error: false });
  useEventStore.setState({ activeSection: "chats", visualStage: null });
  vi.stubGlobal("fetch", backend([]));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.removeItem(FAVORITES_KEY);
});

describe("NavRail", () => {
  test("marks the page that is on screen, also behind one of its tabs", () => {
    act(() => useEventStore.setState({ activeSection: "mcps" }));
    renderRail();
    expect(screen.getByTestId("sidebar-shortcut-plugins").getAttribute("aria-current")).toBe("page");
    expect(screen.getByTestId("sidebar-shortcut-chats").getAttribute("aria-current")).toBeNull();
  });

  test("puts a dot on Plugins when a connection needs a reconnect", () => {
    renderRail("Reconnect a plugin: Cloudflare");
    expect(screen.getByTestId("sidebar-shortcut-warn").getAttribute("aria-label")).toBe("Reconnect a plugin: Cloudflare");
  });

  test("stays quiet while nothing is live", async () => {
    renderRail();
    await act(async () => {});
    expect(screen.queryByTestId("rail-events")).toBeNull();
    expect(screen.queryByTestId("rail-artifacts")).toBeNull();
  });

  test("draws what waits first, then trouble, then what runs", async () => {
    vi.stubGlobal("fetch", backend([], { ...BUSY, running: [BUSY.running[0]], findings: [] }));
    renderRail();
    await waitFor(() => expect(screen.getAllByTestId("rail-event")).toHaveLength(4));
    expect(screen.getAllByTestId("rail-event").map((tile) => tile.dataset.tone)).toEqual(["needs", "needs", "trouble", "running"]);
    expect(screen.queryByTestId("rail-events-more")).toBeNull();
  });

  test("keeps the rail short: the rest waits behind a count that opens the whole list", async () => {
    vi.stubGlobal("fetch", backend([], BUSY));
    renderRail();
    // Eight things are live; four tiles and the count take the five places.
    await waitFor(() => expect(screen.getAllByTestId("rail-event")).toHaveLength(4));
    const more = screen.getByTestId("rail-events-more");
    expect(more.textContent).toBe("+4");
    expect(screen.queryByTestId("rail-events-panel")).toBeNull();
    fireEvent.click(more);
    const panel = screen.getByTestId("rail-events-panel");
    expect(panel.textContent).toContain("Agent 4");
    expect(panel.textContent).toContain("Turn is silent");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("rail-events-panel")).toBeNull();
    // A row takes the person to its place and closes the list behind it.
    fireEvent.click(more);
    fireEvent.click(screen.getByText("Agent 4"));
    expect(useEventStore.getState().activeSection).toBe("agentic-ide");
    expect(screen.queryByTestId("rail-events-panel")).toBeNull();
  });

  test("a finding that leads nowhere is a mark, not a button", async () => {
    vi.stubGlobal("fetch", backend([], { ...BUSY, needs_you: [], running: [], trouble: [] }));
    renderRail();
    const tile = await screen.findByTestId("rail-event");
    expect(tile.tagName).toBe("SPAN");
    expect(tile.getAttribute("aria-label")).toContain("Turn is silent");
  });

  test("offers the newest artifacts, a page before a picture of the same run", async () => {
    vi.stubGlobal("fetch", backend([
      { slug: "run-new", files: [{ path: "shot.png" }, { path: "index.html", title: "Sales dashboard" }] },
      { slug: "run-busy", status: "running", files: [{ path: "draft.html", title: "Draft" }] },
      { slug: "run-notes", files: [{ path: "notes.txt" }] },
      { slug: "run-old", files: [{ path: "chart.png" }] },
    ]));
    renderRail();
    await waitFor(() => expect(screen.getAllByTestId("rail-artifact")).toHaveLength(2));
    const [page, picture] = screen.getAllByTestId("rail-artifact");
    expect(page.getAttribute("aria-label")).toBe("Sales dashboard");
    expect(page.textContent).toBe("SD");
    expect(picture.querySelector("img")?.getAttribute("src")).toContain("/api/outputs/run-old/files/chart.png/");
    fireEvent.click(page);
    expect(useEventStore.getState().activeSection).toBe("visualization");
    expect(useEventStore.getState().visualStage?.target).toBe("run-new::index.html");
  });

  test("a starred artifact leads, and a star on something deleted draws nothing", async () => {
    window.localStorage.setItem(FAVORITES_KEY, JSON.stringify(["run-old::chart.png", "run-gone::index.html", "run:run-new"]));
    vi.stubGlobal("fetch", backend([
      { slug: "run-new", files: [{ path: "index.html", title: "Sales dashboard" }] },
      { slug: "run-old", files: [{ path: "chart.png" }] },
    ]));
    renderRail();
    await waitFor(() => expect(screen.getAllByTestId("rail-artifact")).toHaveLength(2));
    expect(screen.getAllByTestId("rail-artifact").map((tile) => tile.getAttribute("aria-label"))).toEqual(["chart.png", "Sales dashboard"]);
  });

  test("two letters stand for a title", () => {
    expect(tileInitials("PR update 2026-10-05")).toBe("PU");
    expect(tileInitials("index.html")).toBe("IH");
    expect(tileInitials("École")).toBe("É");
    expect(tileInitials(" — ")).toBe("?");
  });
});
