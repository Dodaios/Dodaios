import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeAll, beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("@/lib/bootStagger", () => ({ bootSettled: () => Promise.resolve() }));
vi.mock("@/lib/openExternal", () => ({ openExternalUrl: vi.fn(async () => true) }));

import { NavRail } from "@/components/layout/NavRail";
import { railNotices } from "@/components/layout/railNotices";
import { useStatusLightStore, type StatusLightData, type StatusRow } from "@/components/layout/statusLightStore";
import { translate } from "@/i18n";
import { useEventStore } from "@/store/events";
import { useIdeChatStore } from "@/store/ideChat";

type Plugin = { id: string; display_name: string; status: string; reauth_at?: string | null };

const QUIET: StatusLightData = { counts: { running: 0, needs_you: 0 }, running: [], needs_you: [], trouble: [], findings: [], tone: "calm" };

function card(kind: string, id: string, title: string, agent = "", name = ""): StatusRow {
  return {
    kind, id, title, state: "waiting", agent_name: name,
    link: agent ? { agent_id: agent, session_id: `society:${agent}`, ref_id: id } : { section: "board" },
  };
}

const PANE: StatusRow = {
  kind: "pane", id: "pane:1", title: "T2 (Library)", state: "needs_input",
  agent: "claude", agent_label: "Claude Code", name: "T2", workspace: "Library",
  link: { section: "agentic-ide", workspace_id: "w1", pane: "T2" },
};

let plugins: Plugin[] = [];
let calls: string[] = [];

/** Answers the rail's reads: the status light and the plugin list; a sign-in finishes at once. */
function backend(light: StatusLightData | null = null) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    if (url === "/api/status-light") return light ? json(light) : new Response("no", { status: 500 });
    if (url.endsWith("/connect/start")) {
      plugins = plugins.map((p) => (url.includes(`/${p.id}/`) ? { ...p, status: "connected", reauth_at: null } : p));
      return json({ flow_id: "", kind: "local", open_url: null });
    }
    if (url === "/api/marketplace/plugins") return json({ plugins });
    return new Response("gone", { status: 404 });
  });
}

function renderRail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><NavRail searchOn /></QueryClientProvider>);
}

// The tiles are a lazy chunk; fetching it once here keeps its first load out of a test's own time limit.
beforeAll(async () => { await import("@/components/layout/RailNoticeTiles"); });

beforeEach(() => {
  plugins = [];
  calls = [];
  useStatusLightStore.setState({ light: null, error: false });
  useEventStore.setState({ activeSection: "chats", toasts: [] });
  vi.stubGlobal("fetch", backend());
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("NavRail", () => {
  test("marks the page that is on screen, also behind one of its tabs", () => {
    act(() => useEventStore.setState({ activeSection: "mcps" }));
    renderRail();
    expect(screen.getByTestId("sidebar-shortcut-plugins").getAttribute("aria-current")).toBe("page");
    expect(screen.getByTestId("sidebar-shortcut-chats").getAttribute("aria-current")).toBeNull();
  });

  test("stays quiet while nothing needs the person: no running work, no artifacts", async () => {
    vi.stubGlobal("fetch", backend({
      ...QUIET,
      counts: { running: 2, needs_you: 0 },
      running: [
        { kind: "pane", id: "t1", title: "Agent 1", state: "busy", link: { section: "agentic-ide" } },
        { kind: "task", id: "k1", title: "Nightly sync", state: "running", link: { section: "agents" } },
      ],
      // A provider that is only slowed down, and a health finding nobody can act on.
      trouble: [{ provider: "openai", account: "", class: "rate_limit", reason: "x", blocked: false }],
      findings: [{ id: "f1", kind: "silent_turn", title: "Turn is silent" }],
      tone: "warn",
    }));
    renderRail();
    await waitFor(() => expect(useStatusLightStore.getState().light).not.toBeNull());
    await act(async () => {});
    expect(screen.queryByTestId("rail-notices")).toBeNull();
    expect(screen.queryByTestId("rail-notice")).toBeNull();
    // The rail no longer reads what the assistant made.
    expect(calls.some((url) => url.startsWith("/api/outputs"))).toBe(false);
  });

  test("a connection that ended shows the service with a reconnect badge, and a click signs in again", async () => {
    plugins = [
      { id: "gmail", display_name: "Gmail", status: "needs_reauth", reauth_at: "2026-11-13T09:00:00+00:00" },
      { id: "notion", display_name: "Notion", status: "connected" },
    ];
    renderRail();
    const tile = await screen.findByTestId("rail-notice");
    expect(screen.getAllByTestId("rail-notice")).toHaveLength(1);
    expect(tile.dataset.ask).toBe("reconnect");
    expect(tile.dataset.tone).toBe("trouble");
    expect(tile.getAttribute("aria-label")).toContain("Gmail is disconnected");
    expect(tile.getAttribute("aria-label")).toContain("Reconnect");
    expect(tile.querySelector('[data-testid="rail-notice-badge"]')?.getAttribute("data-ask")).toBe("reconnect");

    fireEvent.click(tile);
    await waitFor(() => expect(calls).toContain("/api/marketplace/plugins/gmail/connect/start"));
    // The click runs the sign-in where the person is; it does not send them to another page.
    expect(useEventStore.getState().activeSection).toBe("chats");
    expect(tile.getAttribute("aria-busy")).toBe("true");
    expect(tile.getAttribute("aria-label")).toContain("Finish signing in");
  });

  test("the bubble beside a tile says what happened and what a click does", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      plugins = [{ id: "gmail", display_name: "Gmail", status: "needs_reauth" }];
      renderRail();
      const tile = await screen.findByTestId("rail-notice");
      fireEvent.mouseEnter(tile.parentElement as HTMLElement);
      await act(async () => { vi.advanceTimersByTime(400); });
      const words = screen.getByTestId("rail-notice-words");
      expect(words.textContent).toContain("Gmail is disconnected");
      expect(words.textContent).toContain("The sign-in expired. Reconnect to use Gmail again.");
      expect(words.textContent).toContain("Reconnect");
    } finally {
      vi.useRealTimers();
    }
  });

  test("an agent with several open cards is one tile that names the agent", async () => {
    vi.stubGlobal("fetch", backend({
      ...QUIET,
      needs_you: [
        card("question", "q1", "Which database?", "a1", "Researcher"),
        card("approval", "p1", "Run the migration", "a1", "Researcher"),
        card("approval", "p2", "Send the mail", "a2", "Writer"),
      ],
    }));
    renderRail();
    await waitFor(() => expect(screen.getAllByTestId("rail-notice")).toHaveLength(2));
    const [first, second] = screen.getAllByTestId("rail-notice");
    expect(first.dataset.ask).toBe("question");
    expect(first.getAttribute("aria-label")).toContain("Researcher has a question");
    expect(first.getAttribute("aria-label")).toContain("Which database? · and 1 more");
    expect(second.dataset.ask).toBe("approval");
    expect(second.getAttribute("aria-label")).toContain("Writer needs your approval");
  });

  test("an agent that needs a service connected shows that service, not a key", async () => {
    // The plugin list reports the same plugin too; the person sees it once, as the card's notice.
    plugins = [{ id: "gmail", display_name: "Gmail", status: "needs_reauth" }];
    vi.stubGlobal("fetch", backend({
      ...QUIET,
      needs_you: [
        { ...card("credential", "c1", "Gmail", "a1", "Nova"), connect: { kind: "plugin", id: "gmail", label: "Gmail", why: "Then I read your unread mail." } },
        card("credential", "c2", "GitHub token", "a1", "Nova"),
      ],
    }));
    renderRail();
    await waitFor(() => expect(screen.getAllByTestId("rail-notice")).toHaveLength(2));
    const [connect, secret] = screen.getAllByTestId("rail-notice");
    expect(connect.dataset.ask).toBe("connect");
    expect(connect.dataset.key).toBe("connect:plugin:gmail");
    expect(connect.getAttribute("aria-label")).toBe("Nova needs Gmail · Then I read your unread mail. · Connect");
    // A secret the same agent asks for stays that agent's own notice.
    expect(secret.dataset.ask).toBe("credential");
    expect(secret.getAttribute("aria-label")).toContain("Nova needs a login or a key");
  });

  test("a waiting coding agent says which CLI waits and where, and opens its pane", async () => {
    vi.stubGlobal("fetch", backend({ ...QUIET, needs_you: [PANE] }));
    renderRail();
    const tile = await screen.findByTestId("rail-notice");
    expect(tile.dataset.ask).toBe("waiting");
    expect(tile.getAttribute("aria-label")).toContain("Claude Code is waiting for you");
    expect(tile.getAttribute("aria-label")).toContain("T2 · Library");
    expect(tile.getAttribute("aria-label")).not.toContain("T2 (Library)");
    expect(tile.querySelector('[data-testid="agent-mark-claude"]')).not.toBeNull();
    fireEvent.click(tile);
    expect(useEventStore.getState().activeSection).toBe("agentic-ide");
    expect(useIdeChatStore.getState().paneRequest).toMatchObject({ workspaceId: "w1", pane: "T2" });
  });

  test("a failing provider is one tile with its logo, what is wrong, and the way to the API keys", async () => {
    vi.stubGlobal("fetch", backend({
      ...QUIET,
      tone: "warn",
      trouble: [{ provider: "openai-live-subscription", label: "OpenAI GPT-Live (ChatGPT subscription)", account: "", class: "model_unavailable", reason: "x", blocked: true }],
      findings: [{
        id: "seat_failure:openai-live-subscription:realtime:model_unavailable", kind: "seat_failure",
        title: "openai-live-subscription (realtime) is failing: model_unavailable",
        provider: "OpenAI GPT-Live (ChatGPT subscription)", provider_id: "openai-live-subscription",
        modality: "realtime", status: "model_unavailable",
      }],
    }));
    renderRail();
    const tile = await screen.findByTestId("rail-notice");
    // The seat record and the watchdog both report it; the person sees it once.
    expect(screen.getAllByTestId("rail-notice")).toHaveLength(1);
    expect(tile.dataset.tone).toBe("trouble");
    const name = tile.getAttribute("aria-label") ?? "";
    expect(name).toContain("OpenAI GPT-Live: model not available");
    expect(name).toContain("ChatGPT subscription");
    expect(name).not.toContain("model_unavailable");
    expect(tile.querySelector('[data-family="openai"]')).not.toBeNull();
    fireEvent.click(tile);
    expect(useEventStore.getState().activeSection).toBe("apikeys");
  });

  test("keeps the rail short: the rest waits behind a count that opens the whole list", async () => {
    plugins = [
      { id: "gmail", display_name: "Gmail", status: "needs_reauth" },
      { id: "slack", display_name: "Slack", status: "error" },
    ];
    vi.stubGlobal("fetch", backend({
      ...QUIET,
      needs_you: [card("question", "q1", "Which database?", "a1", "Researcher"), PANE, card("approval", "p1", "Send the mail")],
      trouble: [{ provider: "openai", account: "work", class: "quota", reason: "x", blocked: true }],
    }));
    renderRail();
    // Six things need the person; three tiles and the count take the four places.
    await waitFor(() => expect(screen.getAllByTestId("rail-notice")).toHaveLength(3));
    const more = screen.getByTestId("rail-notices-more");
    expect(more.textContent).toBe("+3");
    expect(screen.queryByTestId("rail-notices-panel")).toBeNull();
    fireEvent.click(more);
    const panel = screen.getByTestId("rail-notices-panel");
    expect(screen.getAllByTestId("rail-notice-row")).toHaveLength(6);
    expect(panel.textContent).toContain("Gmail is disconnected");
    expect(panel.textContent).toContain("Slack reports a problem");
    expect(panel.textContent).toContain("OpenAI: usage limit reached");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("rail-notices-panel")).toBeNull();
    // A row takes the person to its place and closes the list behind it.
    fireEvent.click(more);
    fireEvent.click(screen.getByText("OpenAI: usage limit reached"));
    expect(useEventStore.getState().activeSection).toBe("apikeys");
    expect(screen.queryByTestId("rail-notices-panel")).toBeNull();
  });
});

describe("railNotices", () => {
  const t = (key: string) => translate(key);

  test("orders by urgency: who waits for an answer, then ended connections, then providers", () => {
    const notices = railNotices(
      {
        ...QUIET,
        needs_you: [PANE, card("credential", "c1", "Hacker News", "a1", "Scout")],
        trouble: [{ provider: "openai", account: "", class: "auth", reason: "x", blocked: true }],
      },
      [{ id: "gmail", name: "Gmail", status: "needs_reauth", reauthAt: null }],
      t,
    );
    expect(notices.map((notice) => notice.key)).toEqual(["pane:pane:1", "agent:a1", "plugin:gmail", "provider:openai"]);
    expect(notices.map((notice) => notice.tone)).toEqual(["needs", "needs", "trouble", "trouble"]);
    expect(notices[1].title).toBe("Scout needs a login or a key");
    expect(notices[3].title).toBe("OpenAI: login or key rejected");
  });

  test("a card without a named agent still reads as a sentence", () => {
    const [notice] = railNotices({ ...QUIET, needs_you: [card("browser_takeover", "r1", "Log in to the shop")] }, [], t);
    expect(notice.title).toBe("An agent needs you in the browser");
    expect(notice.detail).toBe("Log in to the shop");
    expect(notice.mark).toEqual({ type: "glyph", glyph: "agent" });
  });

  test("an older backend's pane row keeps its title as the second line", () => {
    const [notice] = railNotices({
      ...QUIET, needs_you: [{ kind: "pane", id: "t9", title: "T9 (api)", state: "needs_input", link: { section: "agentic-ide" } }],
    }, [], t);
    expect(notice.title).toBe("A coding agent is waiting for you");
    expect(notice.detail).toBe("T9 (api)");
    expect(notice.mark).toEqual({ type: "glyph", glyph: "terminal" });
  });
});
