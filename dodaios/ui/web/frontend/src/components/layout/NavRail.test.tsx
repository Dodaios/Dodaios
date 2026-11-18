import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeAll, beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("@/lib/bootStagger", () => ({ bootSettled: () => Promise.resolve() }));

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

type Reminder = {
  id: string; text: string; due_at: string; kind: string; reminder: boolean; overdue: boolean; delivered: boolean;
  source?: string; title?: string; busy_only?: boolean; start?: string; end?: string; all_day?: boolean;
  calendar?: string; location?: string; url?: string;
};

function reminder(id: string, text: string, extra: Partial<Reminder> = {}): Reminder {
  return { id, text, due_at: "2026-11-14T07:45:00Z", kind: "ephemeral", reminder: true, overdue: true, delivered: true, ...extra };
}

/** A calendar appointment as the backend sends it: its source, own title, start and end, and its link. */
function appointment(id: string, title: string, extra: Partial<Reminder> = {}): Reminder {
  return reminder(id, `Appointment: ${title || "busy, no details shared"} on 2026-11-14 10:15–15:00.`, {
    reminder: false, source: "google_calendar", title, busy_only: false, due_at: "2026-11-14T09:15:00Z",
    start: "2026-11-14T09:15:00Z", end: "2026-11-14T14:00:00Z", all_day: false, calendar: "", location: "",
    url: `https://www.google.com/calendar/event?eid=${id}`, ...extra,
  });
}

let plugins: Plugin[] = [];
let reminders: Reminder[] = [];
let calls: string[] = [];
/** What a notice told an agent's chat: the credential request and the value sent. */
let reported: string[] = [];

/** Answers the rail's reads: the status light and the plugin list; a sign-in finishes at once. */
function backend(light: StatusLightData | null = null) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(url);
    if (url.includes("/credentials/")) {
      reported.push(`${url} ${String(init?.body ?? "")}`);
      return new Response(JSON.stringify({ status: "saved" }), { status: 200 });
    }
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    if (url === "/api/status-light") return light ? json(light) : new Response("no", { status: 500 });
    if (url.endsWith("/connect/start")) {
      plugins = plugins.map((p) => (url.includes(`/${p.id}/`) ? { ...p, status: "connected", reauth_at: null } : p));
      return json({ flow_id: "", kind: "local", open_url: null });
    }
    if (url === "/api/marketplace/plugins") return json({ plugins });
    if (url.startsWith("/api/notify/reminders?")) return json({ items: reminders });
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
  reminders = [];
  calls = [];
  reported = [];
  useStatusLightStore.setState({ light: null, error: false });
  useEventStore.setState({ activeSection: "chats", toasts: [] });
  vi.stubGlobal("fetch", backend());
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
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

  describe("the card beside a tile", () => {
    const APPROVAL = { ...QUIET, needs_you: [{ kind: "approval", id: "a1", title: "Browser: click on https://example.com", state: "waiting", agent_name: "Nova", link: { section: "board" } }] };

    async function hoverTile() {
      vi.stubGlobal("fetch", backend(APPROVAL));
      renderRail();
      const tile = await screen.findByTestId("rail-notice");
      fireEvent.mouseEnter(tile.parentElement as HTMLElement);
      await act(async () => { vi.advanceTimersByTime(400); });
      return tile;
    }

    beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }); });
    afterEach(() => { vi.useRealTimers(); });

    test("stays open while the pointer goes from the tile into it, and its button opens the approval", async () => {
      const tile = await hoverTile();
      // The pointer leaves the tile and is in the card a moment later.
      fireEvent.mouseLeave(tile.parentElement as HTMLElement);
      await act(async () => { vi.advanceTimersByTime(100); });
      fireEvent.mouseEnter(screen.getByTestId("hover-card-layer"));
      await act(async () => { vi.advanceTimersByTime(2000); });
      const action = screen.getByTestId("rail-notice-action");
      expect(action.tagName).toBe("BUTTON");
      expect(action.textContent).toBe("Review");
      fireEvent.click(action);
      expect(useEventStore.getState().activeSection).toBe("board");
      expect(screen.queryByTestId("hover-card")).toBeNull();
    });

    test("takes the pointer: no strip between tile and card that belongs to neither", async () => {
      await hoverTile();
      const layer = screen.getByTestId("hover-card-layer");
      expect(layer.className).not.toContain("pointer-events-none");
      // The layer starts at the tile's edge; the gap that shows is its own padding.
      expect(layer.style.paddingLeft).toBe("8px");
    });

    test("closes shortly after the pointer left both", async () => {
      const tile = await hoverTile();
      fireEvent.mouseLeave(tile.parentElement as HTMLElement);
      await act(async () => { vi.advanceTimersByTime(100); });
      expect(screen.queryByTestId("hover-card")).not.toBeNull();
      await act(async () => { vi.advanceTimersByTime(400); });
      expect(screen.queryByTestId("hover-card")).toBeNull();
    });

    test("opens on keyboard focus, Tab goes to its button, Escape closes it", async () => {
      vi.stubGlobal("fetch", backend(APPROVAL));
      renderRail();
      const tile = await screen.findByTestId("rail-notice");
      act(() => tile.focus());
      const action = screen.getByTestId("rail-notice-action");
      fireEvent.keyDown(tile, { key: "Tab" });
      expect(document.activeElement).toBe(action);
      fireEvent.keyDown(action, { key: "Escape" });
      expect(screen.queryByTestId("hover-card")).toBeNull();
      expect(document.activeElement).toBe(tile);
      // Back on the tile after Escape, the card stays closed until asked for again.
      act(() => tile.blur());
      act(() => tile.focus());
      fireEvent.keyDown(tile, { key: "Tab" });
      fireEvent.keyDown(screen.getByTestId("rail-notice-action"), { key: "Enter" });
      fireEvent.click(screen.getByTestId("rail-notice-action"));
      expect(useEventStore.getState().activeSection).toBe("board");
    });
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
    // A secret the same agent asks for is its own notice, with the logo of the service it is for.
    expect(secret.dataset.ask).toBe("credential");
    expect(secret.dataset.key).toBe("credential:github token");
    expect(secret.getAttribute("aria-label")).toContain("Nova needs a login or a key · GitHub token");
    expect(secret.querySelector("img, [data-logo]")).not.toBeNull();
  });

  test("a login an agent needs shows the service's own logo, or its initial; never a robot", async () => {
    vi.stubGlobal("fetch", backend({
      ...QUIET,
      needs_you: [
        card("credential", "c1", "Hacker News", "agent-gone"),
        card("credential", "c2", "X", "viral-marketing"),
        card("credential", "c3", "Claude Code", "a2", "Scout"),
        card("credential", "c4", "Acme portal", "a3", "Scout"),
      ],
    }));
    renderRail();
    await waitFor(() => expect(screen.getAllByTestId("rail-notice")).toHaveLength(4));
    const [hn, x, claude, acme] = screen.getAllByTestId("rail-notice");
    // Hacker News's own orange mark.
    expect(hn.querySelector("img")?.getAttribute("src")).toContain("FB651E");
    for (const tile of [x, claude]) {
      expect(tile.querySelector("img, [data-logo]")).not.toBeNull();
      expect(tile.querySelector('[data-testid="rail-notice-monogram"]')).toBeNull();
    }
    expect(acme.querySelector('[data-testid="rail-notice-monogram"]')?.textContent).toBe("A");
    expect(hn.getAttribute("aria-label")).toContain("An agent needs a login or a key · Hacker News");
  });

  test("a click on a service an agent asks for connects it and tells that agent's chat", async () => {
    plugins = [{ id: "gmail", display_name: "Gmail", status: "not_connected" }];
    vi.stubGlobal("fetch", backend({
      ...QUIET,
      needs_you: [{ ...card("credential", "c1", "Gmail", "a1", "Nova"), connect: { kind: "plugin", id: "gmail", label: "Gmail" } }],
    }));
    renderRail();
    const tile = await screen.findByTestId("rail-notice");
    fireEvent.click(tile);
    // The click starts the sign-in where the person is; nothing sends them looking for a card.
    await waitFor(() => expect(calls).toContain("/api/marketplace/plugins/gmail/connect/start"));
    expect(useEventStore.getState().activeSection).toBe("chats");
    expect(tile.getAttribute("aria-busy")).toBe("true");
    // Connected: the Connect card's chat hears it, so the agent goes on by itself.
    await waitFor(() => expect(reported).toEqual([
      '/api/agent-chat/sessions/society%3Aa1/credentials/c1 {"value":"connected"}',
    ]), { timeout: 6000 });
    await waitFor(() => expect(useEventStore.getState().toasts.some((toast) => toast.message === "Gmail connected")).toBe(true));
  }, 10_000);

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

  /** Gives the rail's tile box `height` pixels, as a window of that size would. */
  function railHeight(height: number) {
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      disconnect() {}
    });
    const real = HTMLElement.prototype.getBoundingClientRect;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      if (this.dataset.testid === "rail-notices-tiles") return { ...real.call(this), height } as DOMRect;
      return real.call(this);
    });
  }

  const SIX: Partial<StatusLightData> = {
    needs_you: [card("question", "q1", "Which database?", "a1", "Researcher"), PANE, card("approval", "p1", "Send the mail")],
    trouble: [{ provider: "openai", account: "work", class: "quota", reason: "x", blocked: true }],
  };

  test("a tall rail shows every notice as its own tile and no count", async () => {
    railHeight(600);
    plugins = [
      { id: "gmail", display_name: "Gmail", status: "needs_reauth" },
      { id: "slack", display_name: "Slack", status: "error" },
    ];
    vi.stubGlobal("fetch", backend({ ...QUIET, ...SIX }));
    renderRail();
    await waitFor(() => expect(screen.getAllByTestId("rail-notice")).toHaveLength(6));
    expect(screen.queryByTestId("rail-notices-more")).toBeNull();
  });

  test("a short rail shows fewer tiles: the last place that fits becomes the count", async () => {
    // 150 px hold three 44 px tiles with their 6 px gaps.
    railHeight(150);
    plugins = [
      { id: "gmail", display_name: "Gmail", status: "needs_reauth" },
      { id: "slack", display_name: "Slack", status: "error" },
    ];
    vi.stubGlobal("fetch", backend({ ...QUIET, ...SIX }));
    renderRail();
    await waitFor(() => expect(screen.getAllByTestId("rail-notice")).toHaveLength(2));
    expect(screen.getByTestId("rail-notices-more").textContent).toBe("+4");
  });
});

describe("NavRail and the assistant's own messages", () => {
  test("a reminder or appointment that came due never stands on the rail: the assistant says it in the chat", async () => {
    reminders = [reminder("mem_1", "Call the dentist"), appointment("ev_1", "Dentist")];
    renderRail();
    await waitFor(() => expect(calls).toContain("/api/status-light"));
    expect(calls.some((url) => url.startsWith("/api/notify/reminders"))).toBe(false);
    expect(screen.queryByTestId("rail-notice")).toBeNull();
  });

  test("the assistant's own approval stays in its chat; a service it asks to connect stays on the rail", async () => {
    const connect: StatusRow = {
      ...card("credential", "c1", "X (Twitter)", "jarvis", "Nova"),
      connect: { kind: "plugin", id: "x", label: "X (Twitter)" },
    };
    vi.stubGlobal("fetch", backend({
      ...QUIET,
      counts: { running: 0, needs_you: 3 },
      needs_you: [card("approval", "a1", "Browser: click", "jarvis", "Nova"), connect, PANE],
    }));
    renderRail();
    await waitFor(() => expect(screen.getAllByTestId("rail-notice")).toHaveLength(2));
    expect(screen.getAllByTestId("rail-notice").map((tile) => tile.dataset.key)).toEqual(["connect:plugin:x", "pane:pane:1"]);
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
    expect(notices.map((notice) => notice.key)).toEqual(["pane:pane:1", "credential:hacker news", "plugin:gmail", "provider:openai"]);
    expect(notices.map((notice) => notice.tone)).toEqual(["needs", "needs", "trouble", "trouble"]);
    expect(notices[1].title).toBe("Scout needs a login or a key");
    expect(notices[3].title).toBe("OpenAI: login or key rejected");
  });

  test("the assistant's own question, approval and proposal are answered in its chat, not on the rail", () => {
    const notices = railNotices(
      {
        ...QUIET,
        needs_you: [
          card("question", "q1", "Which hotel?", "jarvis", "Nova"),
          card("approval", "a1", "Browser: click", "jarvis", "Nova"),
          card("proposal", "p1", "A routine", "jarvis", "Nova"),
          card("credential", "k1", "Shop login", "jarvis", "Nova"),
          card("question", "q2", "Which repo?", "a1", "Scout"),
        ],
      },
      [],
      t,
    );
    // A login the assistant needs is done outside the chat; another agent's question is in a chat the person may not see.
    expect(notices.map((notice) => notice.key)).toEqual(["credential:shop login", "agent:a1"]);
    expect(notices.map((notice) => notice.ask)).toEqual(["credential", "question"]);
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
