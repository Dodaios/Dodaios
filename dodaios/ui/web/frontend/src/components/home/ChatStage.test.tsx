import { act, cleanup, fireEvent, render as rtlRender, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatStage } from "@/components/home/ChatStage";

import { EMPTY_TIMELINE, reduceEvents } from "@/components/agentchat/reduce";
import type { AgentChatCatalog, AgentChatEvent } from "@/lib/agentChatApi";
import { AgentChatStoreProvider } from "@/components/agentchat/AgentChatStoreContext";
import { useAgentChatStore, useAgentSessionStore } from "@/store/agentChat";
import { useEventStore } from "@/store/events";
import { useHomeStore } from "@/store/home";
import { composerDraftsFor } from "@/components/agentchat/composerDrafts";

const CATALOG: AgentChatCatalog = {
  default_cwd: "C:\\work",
  shell: "pwsh",
  providers: [
    {
      id: "claude-api",
      label: "Anthropic Claude",
      family: "claude",
      runner: "claude-cli",
      models_source: "curated",
      curated_models: [
        { id: "claude-opus-5", label: "Claude Opus 5" },
        { id: "claude-sonnet-5", label: "Claude Sonnet 5" },
      ],
      default_model: "",
      keyless: false,
      native_resume: true,
      effort_levels: ["low", "medium", "high", "xhigh", "max"],
      default_effort: "high",
      permission_modes: [
        { id: "default", label: "Ask before acting", description: "" },
        { id: "acceptEdits", label: "Auto-accept edits", description: "" },
        { id: "plan", label: "Plan", description: "" },
        { id: "bypassPermissions", label: "Bypass permissions", description: "" },
      ],
      default_permission_mode: "acceptEdits",
      cli_installed: true,
    },
    {
      id: "openai-codex",
      label: "OpenAI Codex",
      family: "openai",
      runner: "codex-cli",
      models_source: "curated",
      curated_models: [{ id: "gpt-5.4", label: "GPT-5.4" }],
      default_model: "",
      keyless: false,
      native_resume: true,
      effort_levels: ["minimal", "low", "medium", "high", "xhigh"],
      default_effort: "medium",
      permission_modes: [
        { id: "read-only", label: "Read only", description: "" },
        { id: "auto", label: "Auto", description: "" },
        { id: "full-access", label: "Full access", description: "" },
      ],
      default_permission_mode: "auto",
      cli_installed: false,
    },
  ],
};

// The greeting reads the profile name (a query), so the stage mounts under a
// query client like the app.
function render(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return rtlRender(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

/**
 * The state both stores are seeded with — the front page's and the IDE's.
 *
 * Fresh per call: the two stores must never share one draft object, which is
 * the whole point of the split (jarvis surface vs agent surface).
 */
function seedState() {
  return {
    catalog: CATALOG,
    connections: [
      { jarvis: "claude-api", key_set: true, is_active_brain: true },
      { jarvis: "openai-codex", key_set: true, is_active_brain: false },
    ],
    catalogError: null,
    backendOutdated: false,
    liveModels: {},
    sessions: [],
    activeSessionId: null,
    activeSession: null,
    timeline: EMPTY_TIMELINE,
    // The conversation has arrived, and nothing is in it yet.
    opening: false,
    draft: {
      provider: "claude-api",
      model: "",
      effort: "high",
      permissionMode: "acceptEdits",
      buildMode: "acceptEdits",
      cwd: "C:\\work",
    },
    busy: false,
    lastError: null,
    // The stage's mount effects fetch; keep them inert here.
    loadCatalog: async () => {},
    loadSessions: async () => {},
    loadModels: async () => {},
  };
}

let seq = 0;
function ev(kind: string, payload: Record<string, unknown>): AgentChatEvent {
  seq += 1;
  return { seq, ts_ms: 1_000 + seq, kind, payload };
}

/**
 * jsdom has no ResizeObserver, and the stage only follows a growing answer
 * where the platform has one. This one records every observer's callback
 * and is fired by hand — "the column just grew" — from the test.
 */
class FakeResizeObserver {
  static callbacks: ResizeObserverCallback[] = [];
  constructor(callback: ResizeObserverCallback) {
    FakeResizeObserver.callbacks.push(callback);
  }
  observe() {}
  unobserve() {}
  disconnect() {}
  static fire() {
    for (const callback of FakeResizeObserver.callbacks) {
      callback([], this as unknown as ResizeObserver);
    }
  }
}
function withResizeObserver() {
  FakeResizeObserver.callbacks = [];
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
}

/** jsdom lays nothing out, so the scroller is told how tall it "is". */
function measure(el: HTMLElement, scrollTop: number, scrollHeight: number, clientHeight: number) {
  Object.defineProperty(el, "scrollHeight", { value: scrollHeight, configurable: true });
  Object.defineProperty(el, "clientHeight", { value: clientHeight, configurable: true });
  el.scrollTop = scrollTop;
}

/** The Radix viewport the stage scrolls — the element the follow rule listens on. */
function stageViewport(): HTMLElement {
  const viewport = screen
    .getByTestId("chat-stage")
    .querySelector<HTMLElement>("[data-radix-scroll-area-viewport]");
  if (!viewport) throw new Error("the chat stage rendered no scroll viewport");
  return viewport;
}

/** A turn that is under way: the person asked, the agent is answering. */
function runningTurn() {
  return reduceEvents(EMPTY_TIMELINE, [
    ev("user_message", { text: "run the tests" }),
    ev("turn_started", { turn_id: "t1", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" }),
    ev("assistant_text", { turn_id: "t1", message_id: "m1", text: "Running them now." }),
  ]);
}

describe("ChatStage (agent chat)", () => {
  let scrollTo: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    scrollTo = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      writable: true,
      value: scrollTo,
    });
    // jsdom implements neither; the column scrolls with one or the other.
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
    window.localStorage.clear();
    useEventStore.setState({ connected: true, wsWarming: false, assistantName: "Jarvis" });
    useAgentChatStore.setState(seedState());
    composerDraftsFor(useAgentChatStore).setState({ drafts: new Map() });
    composerDraftsFor(useAgentSessionStore).setState({ drafts: new Map() });
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("opens on a short greeting over the quiet composer when there is nothing yet", () => {
    render(<ChatStage />);
    expect(screen.getByTestId("chat-stage").getAttribute("data-empty")).toBe("true");
    // One line, no explainer paragraph under it.
    expect(screen.getByTestId("home-greeting").querySelector("p")).toBeNull();
    const composer = screen.getByTestId("agent-composer");
    expect(within(composer).getByTestId("composer-row")).toBeTruthy();
    // Provider and model are ONE pick on the front page.
    expect(within(composer).queryByTestId("composer-provider")).toBeNull();
    expect(within(composer).getByTestId("composer-model").getAttribute("data-value")).toBe("claude-api\u0001");
    expect(within(composer).getByTestId("composer-effort").getAttribute("data-value")).toBe("high");
    expect(within(composer).getByTestId("composer-permission").getAttribute("data-value")).toBe("acceptEdits");
    // No Build | Plan switch on the front page, even for a ladder with a plan entry.
    expect(within(composer).queryByTestId("composer-plan")).toBeNull();
    // No surface chip, no paperclip: "+" carries attaching.
    expect(within(composer).queryByTestId("composer-surface")).toBeNull();
    expect(within(composer).queryByTestId("composer-attach")).toBeNull();
    expect(within(composer).getByTestId("composer-add")).toBeTruthy();
  });

  it("paints no selection on the ground around the composer", () => {
    // WebKit filled the composer's wrapper with the selection colour: a grey
    // band under the box once a selection reached it.
    const { unmount } = render(<ChatStage />);
    const wrapperOf = () => screen.getByTestId("agent-composer").parentElement!;
    expect(wrapperOf().className).toContain("selection-text-only");
    expect(wrapperOf().parentElement!.className).toContain("selection-text-only");
    unmount();
    const timeline = reduceEvents(EMPTY_TIMELINE, [ev("user_message", { text: "hello" })]);
    useAgentChatStore.setState({ activeSessionId: "lead-1", timeline });
    render(<ChatStage />);
    expect(screen.getByTestId("chat-stage").getAttribute("data-empty")).toBe("false");
    expect(wrapperOf().className).toContain("selection-text-only");
  });

  it("shows no greeting while the conversation is still on its way, only the composer", () => {
    useAgentChatStore.setState({ activeSessionId: "lead-1", opening: true });
    render(<ChatStage />);
    const stage = screen.getByTestId("chat-stage");
    expect(stage.getAttribute("data-opening")).toBe("true");
    expect(screen.queryByTestId("home-greeting")).toBeNull();
    expect(screen.getByTestId("agent-composer")).toBeTruthy();
    // The transcript lands empty: then it is a chat with nothing in it yet.
    act(() => useAgentChatStore.setState({ opening: false }));
    expect(screen.getByTestId("chat-stage").getAttribute("data-opening")).toBeNull();
    expect(screen.getByTestId("home-greeting")).toBeTruthy();
  });

  it("shows the call while the box is empty and turns it into Send once there is text", () => {
    useHomeStore.setState({ surface: "chat" });
    render(<ChatStage />);
    // Nothing to send yet: dictation and the call, no arrow.
    expect(screen.queryByTestId("composer-send")).toBeNull();
    expect(screen.getByTestId("dictation-button")).toBeTruthy();
    const voice = screen.getByTestId("composer-voice-mode");
    expect(voice.nextElementSibling).toBeNull();
    const box = screen.getByRole("textbox");
    box.textContent = "hello";
    fireEvent.input(box);
    // The call's place is Send's now, last in the row.
    expect(screen.queryByTestId("composer-voice-mode")).toBeNull();
    const send = screen.getByTestId("composer-send") as HTMLButtonElement;
    expect(send.disabled).toBe(false);
    expect(send.nextElementSibling).toBeNull();
    box.textContent = "";
    fireEvent.input(box);
    expect(screen.queryByTestId("composer-send")).toBeNull();
    fireEvent.click(screen.getByTestId("composer-voice-mode"));
    // A call stays in the conversation: the page does not switch away.
    expect(useHomeStore.getState().surface).toBe("chat");
    expect(screen.getByRole("textbox")).toBeTruthy();
  });

  it("sits on one line at rest, turns tall at a line break and returns once empty", () => {
    render(<ChatStage />);
    const composer = screen.getByTestId("agent-composer");
    expect(composer.getAttribute("data-shape")).toBe("line");
    const box = screen.getByRole("textbox");
    box.textContent = "first line";
    fireEvent.input(box);
    expect(composer.getAttribute("data-shape")).toBe("line");
    box.textContent = "first line\nsecond line";
    fireEvent.input(box);
    expect(composer.getAttribute("data-shape")).toBe("tall");
    // A shorter text keeps it tall: the controls do not jump while typing.
    box.textContent = "first";
    fireEvent.input(box);
    expect(composer.getAttribute("data-shape")).toBe("tall");
    box.textContent = "";
    fireEvent.input(box);
    expect(composer.getAttribute("data-shape")).toBe("line");
  });

  it("turns the round action into Hang up while a call runs", () => {
    useEventStore.setState({ voiceState: "listening" });
    try {
      render(<ChatStage />);
      expect(screen.queryByTestId("composer-voice-mode")).toBeNull();
      expect(screen.getByTestId("composer-hang-up").textContent).toContain("Hang up");
      // No Send while there are no words.
      expect(screen.queryByTestId("composer-send")).toBeNull();
      // The microphone button is the call's mute switch, not dictation.
      expect(screen.queryByTestId("dictation-button")).toBeNull();
      expect(screen.getByTestId("composer-call-mute").getAttribute("aria-pressed")).toBe("false");
      // Typed words during a call still go out as a message.
      const box = screen.getByRole("textbox");
      box.textContent = "a note";
      fireEvent.input(box);
      expect(screen.getByTestId("composer-send")).toBeTruthy();
      expect(screen.queryByTestId("composer-hang-up")).toBeNull();
    } finally {
      useEventStore.setState({ voiceState: "idle" });
    }
  });

  it("restores an unsent multiline draft after leaving the chat section", () => {
    const text = "  Draft to finish later\nKeep this second line too.  ";
    const first = render(<ChatStage />);
    const box = screen.getByRole("textbox");
    box.textContent = text;
    fireEvent.input(box);
    first.unmount();

    const second = render(<ChatStage />);
    expect(screen.getByRole("textbox").textContent).toBe(text);
    expect(screen.getByTestId("composer-send")).toBeTruthy();
    const restored = screen.getByRole("textbox");
    restored.textContent = `${text}\nAnd a third line.`;
    fireEvent.input(restored);
    second.unmount();

    render(<ChatStage />);
    expect(screen.getByRole("textbox").textContent).toBe(`${text}\nAnd a third line.`);
  });

  it("keeps drafts separate when switching conversations", () => {
    render(<ChatStage />);
    const box = screen.getByRole("textbox");
    box.textContent = "New conversation draft";
    fireEvent.input(box);
    act(() => useAgentChatStore.setState({ activeSessionId: "other-chat" }));
    expect(screen.getByRole("textbox").textContent).toBe("");
    const other = screen.getByRole("textbox");
    other.textContent = "Existing conversation draft";
    fireEvent.input(other);

    act(() => useAgentChatStore.setState({ activeSessionId: null }));
    expect(screen.getByRole("textbox").textContent).toBe("New conversation draft");
    act(() => useAgentChatStore.setState({ activeSessionId: "other-chat" }));
    expect(screen.getByRole("textbox").textContent).toBe("Existing conversation draft");
  });

  it("does not transfer the front page draft into the IDE chat", () => {
    const first = render(<ChatStage />);
    const box = screen.getByRole("textbox");
    box.textContent = "Front page draft";
    fireEvent.input(box);
    first.unmount();
    useAgentSessionStore.setState(seedState());
    const ide = render(<AgentChatStoreProvider store={useAgentSessionStore}><ChatStage /></AgentChatStoreProvider>);
    expect(screen.getByRole("textbox").textContent).toBe("");
    ide.unmount();
    render(<ChatStage />);
    expect(screen.getByRole("textbox").textContent).toBe("Front page draft");
  });

  it("keeps a manually cleared draft empty after remounting", () => {
    const first = render(<ChatStage />);
    const box = screen.getByRole("textbox");
    box.textContent = "Discard this draft";
    fireEvent.input(box);
    box.textContent = "";
    fireEvent.input(box);
    first.unmount();
    render(<ChatStage />);
    expect(screen.getByRole("textbox").textContent).toBe("");
  });

  it("does not restore a successfully sent draft after remounting", async () => {
    const originalSend = useAgentChatStore.getState().send;
    const sent: string[] = [];
    useAgentChatStore.setState({ send: async (text) => { sent.push(text); } });
    try {
      const first = render(<ChatStage />);
      const box = screen.getByRole("textbox");
      box.textContent = "Send this once";
      fireEvent.input(box);
      await act(async () => fireEvent.click(screen.getByTestId("composer-send")));
      expect(sent).toEqual(["Send this once"]);
      first.unmount();
      render(<ChatStage />);
      expect(screen.getByRole("textbox").textContent).toBe("");
    } finally {
      useAgentChatStore.setState({ send: originalSend });
    }
  });

  it("restores a failed send in the field and across remounts", async () => {
    const originalSend = useAgentChatStore.getState().send;
    useAgentChatStore.setState({ send: async () => { useAgentChatStore.setState({ lastError: "Offline" }); } });
    try {
      const first = render(<ChatStage />);
      const box = screen.getByRole("textbox");
      box.textContent = "Keep this if sending fails";
      fireEvent.input(box);
      await act(async () => fireEvent.click(screen.getByTestId("composer-send")));
      expect(screen.getByRole("textbox").textContent).toBe("Keep this if sending fails");
      first.unmount();
      render(<ChatStage />);
      expect(screen.getByRole("textbox").textContent).toBe("Keep this if sending fails");
    } finally {
      useAgentChatStore.setState({ send: originalSend });
    }
  });

  it("lists each connected provider with its models in the one brain pick", async () => {
    render(<ChatStage />);
    fireEvent.click(screen.getByTestId("composer-model"));
    const panel = await screen.findByTestId("composer-model-panel");
    const options = within(panel).getAllByRole("option").map((el) => el.getAttribute("data-value"));
    // Strongest first, and no "default" row: the person picks a model.
    expect(options).toEqual([
      "claude-api\u0001claude-opus-5",
      "claude-api\u0001claude-sonnet-5",
    ]);
    // Codex is not installed on this box, so it is not offered at all.
    expect(within(panel).queryByText("GPT-5.4")).toBeNull();
    fireEvent.click(within(panel).getByText("Claude Sonnet 5"));
    await act(async () => {});
    expect(useAgentChatStore.getState().draft.provider).toBe("claude-api");
    expect(useAgentChatStore.getState().draft.model).toBe("claude-sonnet-5");
  });

  it("says who is answering in the IDE; the front page needs no label for its own assistant", () => {
    const { unmount } = render(<ChatStage />);
    expect(screen.queryByTestId("composer-surface")).toBeNull();
    expect(screen.getByTestId("home-greeting")).toBeTruthy();
    unmount();

    useAgentSessionStore.setState(seedState());
    render(
      <AgentChatStoreProvider store={useAgentSessionStore}>
        <ChatStage />
      </AgentChatStoreProvider>,
    );
    const ide = screen.getByTestId("composer-surface");
    expect(ide.getAttribute("data-surface")).toBe("agent");
    expect(ide.textContent).toContain("Coding agent");
    expect(ide.textContent).not.toContain("Jarvis");
    // No "Good afternoon" from a coding agent — the folder it works in instead.
    expect(screen.queryByTestId("home-greeting")).toBeNull();
    expect(screen.getByTestId("chat-folder-headline").textContent).toContain("work");
  });

  it("keeps the folder chip out of the Jarvis chat and leaves it in the IDE's", () => {
    // The chip belongs to the IDE: a coding agent is pointed at a checkout and
    // has to be movable. On the front page it only showed the leaf of the
    // default path — on Windows the account name, which read like a setting
    // nobody chose (maintainer, 2026-08-25). The folder itself did not go
    // away; a CLI seat still starts in one. It is just no longer a control.
    const { unmount } = render(<ChatStage />);
    expect(screen.queryByTestId("composer-folder")).toBeNull();
    unmount();

    useAgentSessionStore.setState(seedState());
    render(
      <AgentChatStoreProvider store={useAgentSessionStore}>
        <ChatStage />
      </AgentChatStoreProvider>,
    );
    expect(screen.getByTestId("composer-surface").getAttribute("data-surface")).toBe("agent");
    expect(screen.getByTestId("composer-folder")).toBeTruthy();
  });

  it("answers as plain text on the front page and bylines the coding agent in the IDE", () => {
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "list the files" }),
      ev("turn_started", { turn_id: "t1", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "brain" }),
      ev("assistant_text", { turn_id: "t1", message_id: "m1", text: "Two files." }),
      ev("turn_finished", { turn_id: "t1", status: "done", duration_ms: 900, usage: {} }),
    ]);
    useAgentChatStore.setState({ activeSessionId: "s1", timeline });
    const { unmount } = render(<ChatStage />);
    const front = screen.getByTestId("agent-turn");
    expect(front.textContent).toContain("Two files.");
    expect(front.textContent).not.toContain("Anthropic Claude");
    unmount();

    useAgentSessionStore.setState({ ...seedState(), activeSessionId: "ide-1", timeline });
    render(
      <AgentChatStoreProvider store={useAgentSessionStore}>
        <ChatStage />
      </AgentChatStoreProvider>,
    );
    const turn = screen.getByTestId("agent-turn");
    expect(turn.textContent).toContain("Coding agent");
    expect(turn.textContent).not.toContain("Jarvis");
  });

  it("hides the Build | Plan switch for a provider whose ladder has no plan entry", () => {
    useAgentChatStore.setState((s) => ({ draft: { ...s.draft, provider: "openai-codex", permissionMode: "auto" } }));
    render(<ChatStage />);
    expect(screen.queryByTestId("composer-plan")).toBeNull();
  });

  it("groups the provider list by what stands behind a row: coding CLIs, API keys, local servers", async () => {
    const apiRow = {
      ...CATALOG.providers[0],
      id: "openai",
      label: "OpenAI",
      family: "openai",
      runner: "api",
      models_source: "live" as const,
      curated_models: [],
      cli_installed: null,
    };
    const localRow = { ...apiRow, id: "ollama", label: "Ollama", family: "ollama", keyless: true };
    useAgentSessionStore.setState({
      ...seedState(),
      catalog: { ...CATALOG, providers: [...CATALOG.providers, apiRow, localRow] },
      connections: [
        { jarvis: "claude-api", key_set: true, is_active_brain: false },
        { jarvis: "openai-codex", key_set: false, is_active_brain: false },
        { jarvis: "openai", key_set: true, is_active_brain: true },
      ],
    });
    render(
      <AgentChatStoreProvider store={useAgentSessionStore}>
        <ChatStage />
      </AgentChatStoreProvider>,
    );
    fireEvent.click(screen.getByTestId("composer-provider"));
    const panel = await screen.findByTestId("composer-provider-panel");
    // The headings, in catalog order — never "connected / not connected".
    const headings = ["Coding CLIs", "API keys", "On your own hardware"]
      .map((label) => within(panel).getByText(label).textContent);
    expect(headings).toEqual(["Coding CLIs", "API keys", "On your own hardware"]);
    expect(within(panel).queryByText("Connected")).toBeNull();
    // Only what the Agents tab has set up is listed: Codex (no login) is not
    // there at all, and the voice sub-agent's "active" word is not shown.
    const options = within(panel).getAllByRole("option").map((el) => el.textContent ?? "");
    expect(options.map((o) => o.replace(/\s+/g, " ").trim())).toEqual(["Anthropic Claude", "OpenAI", "Ollama"]);
    expect(within(panel).queryByText("active")).toBeNull();
  });

  it("with nothing connected yet, lists every provider greyed with its connect hint", async () => {
    useAgentSessionStore.setState({
      ...seedState(),
      connections: [
        { jarvis: "claude-api", key_set: false, is_active_brain: false },
        { jarvis: "openai-codex", key_set: false, is_active_brain: false },
      ],
    });
    render(
      <AgentChatStoreProvider store={useAgentSessionStore}>
        <ChatStage />
      </AgentChatStoreProvider>,
    );
    fireEvent.click(screen.getByTestId("composer-provider"));
    const panel = await screen.findByTestId("composer-provider-panel");
    const options = within(panel).getAllByRole("option");
    expect(options).toHaveLength(2);
    expect(options[0].textContent).toContain("connect");
    // Codex is not installed on this box: the hint says so instead of "connect".
    expect(options[1].textContent).toContain("not installed");
  });

  it("says when the backend is older than this window and offers the restart", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    try {
      useAgentChatStore.setState({ backendOutdated: true });
      render(<ChatStage />);
      const notice = screen.getByTestId("composer-backend-outdated");
      expect(notice.textContent).toContain("older version");
      fireEvent.click(within(notice).getByRole("button"));
      await act(async () => {});
      expect(fetchMock).toHaveBeenCalledWith("/api/settings/restart-app", { method: "POST" });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("draws a different glyph per permission mode in the pill and the list", async () => {
    render(<ChatStage />);
    // The labelled pick row draws no glyph on the pill; the list carries them.
    const pill = screen.getByTestId("composer-permission");
    fireEvent.click(pill);
    const panel = await screen.findByTestId("composer-permission-panel");
    const glyphs = within(panel)
      .getAllByRole("option")
      .map((el) => el.querySelector("svg")?.getAttribute("data-icon") ?? "");
    // default → hand, acceptEdits → pencil, bypass → warning shield; plan lives on the switch.
    expect(glyphs).toContain("StanceAskIcon");
    expect(glyphs).toContain("StanceEditsIcon");
    expect(glyphs).toContain("StanceBypassIcon");
    expect(new Set(glyphs).size).toBe(glyphs.length);
  });

  it("marks the provider's default effort and explains each stance in its menu", async () => {
    useAgentChatStore.setState({
      catalog: {
        ...CATALOG,
        providers: CATALOG.providers.map((p) => ({
          ...p,
          permission_modes: p.permission_modes.map((m) => ({ ...m, description: `What ${m.label} lets through.` })),
        })),
      },
    });
    render(<ChatStage />);
    fireEvent.click(screen.getByTestId("composer-effort"));
    const effort = await screen.findByTestId("composer-effort-panel");
    expect(effort.textContent).toContain("Reasoning");
    const high = within(effort).getAllByRole("option").find((el) => el.getAttribute("data-value") === "high");
    expect(high?.textContent).toContain("Default");
    fireEvent.keyDown(effort, { key: "Escape" });

    fireEvent.click(screen.getByTestId("composer-permission"));
    const stances = await screen.findByTestId("composer-permission-panel");
    expect(stances.textContent).toContain("What Auto-accept edits lets through.");
  });

  it("wears one glyph per stance on the unified ladder", async () => {
    // The front page's catalog hands every provider the same four-step ladder
    // (dodaios/agent_chat/permissions.py, surface=jarvis); the composer draws
    // what it is given and never a ladder typed here.
    const unified = [
      { id: "ask", label: "Ask before acting", description: "" },
      { id: "accept-edits", label: "Auto-accept edits", description: "" },
      { id: "plan", label: "Plan", description: "" },
      { id: "bypass", label: "Bypass permissions", description: "" },
    ];
    useAgentChatStore.setState((s) => ({
      catalog: {
        ...CATALOG,
        providers: CATALOG.providers.map((p) => ({
          ...p,
          permission_modes: unified,
          default_permission_mode: "ask",
        })),
      },
      draft: { ...s.draft, permissionMode: "ask", buildMode: "ask" },
    }));
    render(<ChatStage />);
    const pill = screen.getByTestId("composer-permission");
    expect(pill.getAttribute("data-value")).toBe("ask");
    fireEvent.click(pill);
    const panel = await screen.findByTestId("composer-permission-panel");
    const rows = within(panel).getAllByRole("option");
    // Plan is the switch next door, so the list holds the other three.
    expect(rows.map((el) => el.getAttribute("data-value"))).toEqual(["ask", "accept-edits", "bypass"]);
    const glyphs = rows.map((el) => el.querySelector("svg")?.getAttribute("data-icon") ?? "");
    expect(glyphs).toEqual(["StanceAskIcon", "StanceEditsIcon", "StanceBypassIcon"]);
  });

  it("draws Bypass in the row's plain grey, like every other stance", () => {
    useAgentChatStore.setState((s) => ({ draft: { ...s.draft, permissionMode: "bypassPermissions" } }));
    render(<ChatStage />);
    const pill = screen.getByTestId("composer-permission");
    expect(pill.getAttribute("data-value")).toBe("bypassPermissions");
    expect(pill.className).not.toContain("text-warning");
  });

  it("brings a chat left in Plan back to its build stance, since the front page has no switch", async () => {
    const setPlan = vi.fn(async () => {});
    useAgentChatStore.setState((s) => ({ setPlan, draft: { ...s.draft, permissionMode: "plan" } }) as never);
    render(<ChatStage />);
    await waitFor(() => expect(setPlan).toHaveBeenCalledWith(false));
  });

  it("accepts a prompt through the current rich text composer", () => {
    render(<ChatStage />);
    const box = screen.getByRole("textbox");
    box.textContent = "Check this trace";
    fireEvent.input(box);
    expect((screen.getByTestId("composer-send") as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows no restart notice when the catalog carries the permission ladders", () => {
    render(<ChatStage />);
    expect(screen.queryByTestId("composer-backend-outdated")).toBeNull();
  });

  it("greys out a provider that is not connected and says how to fix it", () => {
    useAgentChatStore.setState({
      connections: [{ jarvis: "claude-api", key_set: false, is_active_brain: true }],
    });
    render(<ChatStage />);
    const hint = screen.getByTestId("composer-connect-hint");
    expect(hint.textContent).toContain("Anthropic Claude");
    // Send stays off until the provider is usable.
    const box = screen.getByRole("textbox");
    box.textContent = "hello";
    fireEvent.input(box);
    expect((screen.getByTestId("composer-send") as HTMLButtonElement).disabled).toBe(true);
  });

  it("renders the folded timeline: user bubble, byline with provider + model, tool row, answer", () => {
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "list the files" }),
      ev("turn_started", { turn_id: "t1", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" }),
      ev("tool_call", { turn_id: "t1", call_id: "c1", name: "Bash", input: { command: "ls" } }),
      ev("tool_result", { turn_id: "t1", call_id: "c1", output: "a.py\nb.py", is_error: false, duration_ms: 40 }),
      ev("assistant_text", { turn_id: "t1", message_id: "m1", text: "Two files: **a.py** and b.py." }),
      ev("turn_finished", { turn_id: "t1", status: "done", duration_ms: 1200, usage: {} }),
    ]);
    useAgentSessionStore.setState({ ...seedState(), activeSessionId: "s1", timeline });
    render(
      <AgentChatStoreProvider store={useAgentSessionStore}>
        <ChatStage />
      </AgentChatStoreProvider>,
    );
    expect(screen.getByTestId("chat-stage").getAttribute("data-empty")).toBe("false");
    expect(screen.getByTestId("agent-message-user").textContent).toContain("list the files");
    const turn = screen.getByTestId("agent-turn");
    expect(turn.textContent).toContain("Anthropic Claude");
    expect(turn.textContent).toContain("claude-opus-5");
    const tool = turn.querySelector<HTMLElement>("[data-trace-tool]")!;
    expect(tool.textContent).toContain("Run command");
    expect(tool.getAttribute("data-state")).toBe("completed");
    // The row opens to show input and output.
    fireEvent.click(within(tool).getByRole("button"));
    expect(tool.textContent).toContain("a.py");
    expect(within(turn).getByTestId("agent-text").querySelector("strong")?.textContent).toBe("a.py");
  });

  it("draws no background record: a learned memory, a watchdog finding, a routine run that failed", () => {
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "good morning" }),
      ev("notice", { kind: "memory_learned", status: "done", text: "Wants results as files.",
        items: [{ op: "added", id: "m1", text: "Wants results as files." }] }),
      ev("notice", { kind: "watchdog", status: "done", text: "Something needs a look.\n- The app was not running for about 16 minutes" }),
      ev("notice", { kind: "society_result", source: "routine", status: "failed", agent_name: "Jarvis",
        text: 'The routine "Probe status file" failed: RuntimeError: no model seat' }),
      ev("notice", { kind: "society_result", source: "routine", status: "done", agent_name: "Jarvis", text: "Three new orders today." }),
    ]);
    useAgentChatStore.setState({ ...seedState(), activeSessionId: "s1", timeline });
    render(<ChatStage />);
    const stage = screen.getByTestId("chat-stage");
    expect(stage.textContent).toContain("good morning");
    // The routine's finished result is an answer and stays.
    expect(stage.textContent).toContain("Three new orders today.");
    expect(stage.textContent).not.toContain("Wants results as files.");
    expect(stage.textContent).not.toContain("Something needs a look.");
    expect(stage.textContent).not.toContain("Probe status file");
  });

  it("stays on the greeting when the log holds background records only", () => {
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("notice", { kind: "watchdog", status: "done", text: "Something needs a look." }),
      ev("notice", { kind: "memory_learned", status: "done", text: "Wants results as files." }),
    ]);
    useAgentChatStore.setState({ ...seedState(), activeSessionId: "s1", timeline });
    render(<ChatStage />);
    expect(screen.getByTestId("chat-stage").getAttribute("data-empty")).toBe("true");
  });

  it("goes on at the bottom when the person sends: the conversation above stays in view", () => {
    // The complaint this guards (maintainer, 2026-11-12): a sent message was
    // brought to the top of the scroll area over a spacer, so every send hid
    // the conversation and the person had to scroll up to see it.
    withResizeObserver();
    const before = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "run the tests" }),
      ev("turn_started", { turn_id: "t1", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" }),
      ev("assistant_text", { turn_id: "t1", message_id: "m1", text: "All green." }),
      ev("turn_finished", { turn_id: "t1", status: "done", duration_ms: 900, usage: {} }),
    ]);
    useAgentChatStore.setState({ activeSessionId: "s1", timeline: before });
    render(<ChatStage />);
    const viewport = stageViewport();
    measure(viewport, 900, 1000, 100);
    act(() => {
      fireEvent.scroll(viewport);
    });
    // Opening a conversation animates nothing and adds no room under it.
    expect(scrollTo).not.toHaveBeenCalled();
    expect(screen.queryByTestId("chat-bottom-spacer")).toBeNull();

    // Sent: the column is taller by the new message, and the view is at its
    // end at once. No glide: the turn's next update would cut one short, and
    // the desktop app's engine then leaves the view standing where it was
    // (maintainer, 2026-11-12: "the chat does not move down by itself").
    measure(viewport, 900, 1080, 100);
    act(() => useAgentChatStore.setState({ timeline: reduceEvents(before, [ev("user_message", { text: "and the linter?" })]) }));
    expect(viewport.scrollTop).toBe(1080);
    expect(scrollTo).not.toHaveBeenCalled();
    // Both messages of the person are in the column, the earlier one first.
    expect(screen.getAllByTestId("agent-message-user").map((node) => node.textContent)).toEqual(["run the tests", "and the linter?"]);
    expect(screen.queryByTestId("chat-bottom-spacer")).toBeNull();
    expect(screen.queryByTestId("chat-scroll-end")).toBeNull();
  });

  it("takes a reader who had scrolled up back to the end when they send", () => {
    withResizeObserver();
    const before = runningTurn();
    useAgentChatStore.setState({ activeSessionId: "s1", timeline: before });
    render(<ChatStage />);
    const viewport = stageViewport();
    measure(viewport, 100, 1000, 50);
    act(() => {
      fireEvent.scroll(viewport);
    });
    expect(screen.getByTestId("chat-scroll-end")).toBeTruthy();

    measure(viewport, 100, 1080, 50);
    act(() => useAgentChatStore.setState({ timeline: reduceEvents(before, [ev("user_message", { text: "stop after the first failure" })]) }));
    expect(viewport.scrollTop).toBe(1080);
    expect(scrollTo).not.toHaveBeenCalled();
    expect(screen.queryByTestId("chat-scroll-end")).toBeNull();

    // The answer's first words arrive: the view is still at the end and follows.
    measure(viewport, 1080, 1200, 50);
    act(() => useAgentChatStore.setState({
      timeline: reduceEvents(before, [
        ev("user_message", { text: "stop after the first failure" }),
        ev("turn_started", { turn_id: "t9", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" }),
      ]),
    }));
    expect(viewport.scrollTop).toBe(1200);
  });

  it("takes a reader who had scrolled up to the end when the message and its turn arrive in one render", () => {
    // The two events are a millisecond apart on the wire. When both reach
    // one render, the last item is the turn, not the message: the stage
    // still has to see that the person sent something.
    withResizeObserver();
    const before = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "run the tests" }),
      ev("turn_started", { turn_id: "t1", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" }),
      ev("assistant_text", { turn_id: "t1", message_id: "m1", text: "All green." }),
      ev("turn_finished", { turn_id: "t1", status: "done", duration_ms: 900, usage: {} }),
    ]);
    useAgentChatStore.setState({ activeSessionId: "s1", timeline: before });
    render(<ChatStage />);
    const viewport = stageViewport();
    measure(viewport, 100, 1000, 50);
    act(() => {
      fireEvent.scroll(viewport);
    });
    expect(screen.getByTestId("chat-scroll-end")).toBeTruthy();

    measure(viewport, 100, 1130, 50);
    act(() => useAgentChatStore.setState({
      timeline: reduceEvents(before, [
        ev("user_message", { text: "and the linter?" }),
        ev("turn_started", { turn_id: "t2", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" }),
      ]),
    }));
    expect(viewport.scrollTop).toBe(1130);
    expect(screen.queryByTestId("chat-scroll-end")).toBeNull();
  });

  it("takes a reader who had scrolled up to the end when they send into the running turn", () => {
    withResizeObserver();
    const before = runningTurn();
    useAgentChatStore.setState({ activeSessionId: "s1", timeline: before });
    render(<ChatStage />);
    const viewport = stageViewport();
    measure(viewport, 100, 1000, 50);
    act(() => {
      fireEvent.scroll(viewport);
    });
    expect(screen.getByTestId("chat-scroll-end")).toBeTruthy();

    measure(viewport, 100, 1070, 50);
    act(() => useAgentChatStore.setState({
      timeline: reduceEvents(before, [ev("user_message", { text: "only the unit tests", turn_id: "t1", steered: true })]),
    }));
    expect(viewport.scrollTop).toBe(1070);
    expect(screen.queryByTestId("chat-scroll-end")).toBeNull();
  });

  it("leaves a reader who scrolled up alone when an earlier request's result comes back by itself", () => {
    withResizeObserver();
    const before = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "run the tests" }),
      ev("turn_started", { turn_id: "t1", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" }),
      ev("assistant_text", { turn_id: "t1", message_id: "m1", text: "All green." }),
      ev("turn_finished", { turn_id: "t1", status: "done", duration_ms: 900, usage: {} }),
    ]);
    useAgentChatStore.setState({ activeSessionId: "s1", timeline: before });
    render(<ChatStage />);
    const viewport = stageViewport();
    measure(viewport, 100, 1000, 50);
    act(() => {
      fireEvent.scroll(viewport);
    });

    // Nobody sent this now: the view stays, and the way back is offered.
    measure(viewport, 100, 1040, 50);
    act(() => useAgentChatStore.setState({
      timeline: reduceEvents(before, [ev("user_message", { text: "the nightly report", origin: "background" })]),
    }));
    expect(viewport.scrollTop).toBe(100);
    expect(screen.getByTestId("chat-scroll-end")).toBeTruthy();
  });

  it("lands an opened conversation at its end without a glide, even when the person wrote last", () => {
    withResizeObserver();
    useAgentChatStore.setState({
      activeSessionId: "s1",
      timeline: reduceEvents(EMPTY_TIMELINE, [ev("user_message", { text: "run the tests" })]),
    });
    render(<ChatStage />);
    expect(scrollTo).not.toHaveBeenCalled();
    const viewport = stageViewport();
    measure(viewport, 0, 1000, 100);
    act(() => {
      FakeResizeObserver.fire();
    });
    expect(viewport.scrollTop).toBe(1000);
  });

  it("follows an answer that grows past the window while the view is at the end", () => {
    withResizeObserver();
    useAgentChatStore.setState({ activeSessionId: "s1", timeline: runningTurn() });
    render(<ChatStage />);
    const viewport = stageViewport();
    measure(viewport, 950, 1000, 50);
    act(() => {
      fireEvent.scroll(viewport);
    });

    // The reasoning trace grows without a new item — the column gets taller.
    measure(viewport, 950, 2000, 50);
    act(() => {
      FakeResizeObserver.fire();
    });
    expect(viewport.scrollTop).toBe(2000);
    expect(screen.queryByTestId("chat-scroll-end")).toBeNull();
  });

  it("leaves a reader who scrolled up where they are, and offers the way back over the composer", () => {
    withResizeObserver();
    useAgentChatStore.setState({ activeSessionId: "s1", timeline: runningTurn() });
    render(<ChatStage />);
    const viewport = stageViewport();
    measure(viewport, 100, 1000, 50);
    act(() => {
      fireEvent.scroll(viewport);
    });
    expect(screen.getByTestId("chat-scroll-end")).toBeTruthy();

    // The answer keeps growing below; the reader's place is not touched.
    measure(viewport, 100, 2000, 50);
    act(() => {
      FakeResizeObserver.fire();
    });
    expect(viewport.scrollTop).toBe(100);

    // Taking the way back goes to the end and retires the button.
    scrollTo.mockClear();
    act(() => {
      fireEvent.click(screen.getByTestId("chat-scroll-end"));
    });
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ top: 2000 }));
    expect(screen.queryByTestId("chat-scroll-end")).toBeNull();
  });

  it("shows the approval card while the runner waits and routes the click to the store", () => {
    const decide = vi.fn(async () => {});
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "delete it" }),
      ev("turn_started", { turn_id: "t2", provider: "openai", model: "", effort: "", runner: "api" }),
      ev("approval_required", { turn_id: "t2", approval_id: "a1", call_id: "c2", name: "RunCommand", input: { command: "rm x" }, summary: "rm x" }),
    ]);
    useAgentChatStore.setState({ activeSessionId: "s2", timeline, decide });
    render(<ChatStage />);
    const card = screen.getByTestId("thread-approval");
    expect(card.textContent).toContain("rm x");
    act(() => {
      fireEvent.click(within(card).getByRole("button", { name: "Allow once" }));
    });
    expect(decide).toHaveBeenCalledWith("a1", "allow");
    // No Stop button in the Dodaios chat: the box names the word instead.
    expect(screen.queryByTestId("composer-stop")).toBeNull();
    expect(screen.getByRole("textbox").getAttribute("data-placeholder")).toBe('Write “stop” to stop…');
  });

  it("opens the call window above the composer for a call, a call asked for and a call that failed", async () => {
    useAgentChatStore.setState({ activeSessionId: "s1", timeline: reduceEvents(EMPTY_TIMELINE, [ev("user_message", { text: "hello" })]) });
    useHomeStore.setState({ callPending: false, callProblem: null });
    useEventStore.setState({ voiceState: "idle" });
    render(<ChatStage />);
    expect(screen.queryByTestId("call-window")).toBeNull();
    // Asked for from this window: there before any state arrives.
    act(() => useHomeStore.setState({ callPending: true }));
    const call = await screen.findByTestId("call-window");
    // It stands on the composer: same wrapper, before it.
    expect(call.parentElement?.querySelector("[data-testid='agent-composer'], textarea, [contenteditable]")).toBeTruthy();
    // Running, however it was started.
    act(() => { useHomeStore.setState({ callPending: false }); useEventStore.setState({ voiceState: "listening" }); });
    expect(screen.getByTestId("call-window").getAttribute("data-state")).toBe("listening");
    // One set of call controls: the composer's, none in the window.
    expect(within(screen.getByTestId("call-window")).queryByTestId("call-hang-up")).toBeNull();
    expect(screen.getByTestId("composer-hang-up")).toBeTruthy();
    // Ended on a problem: the window stays with the reason.
    act(() => { useEventStore.setState({ voiceState: "idle" }); useHomeStore.setState({ callProblem: { message: "refused", at: Date.now() } }); });
    expect(screen.getByTestId("call-window").getAttribute("data-state")).toBe("failed");
    act(() => useHomeStore.setState({ callProblem: null }));
    expect(screen.queryByTestId("call-window")).toBeNull();
    // The conversation never left the page.
    expect(screen.getByTestId("agent-message-user").textContent).toContain("hello");
  });

  it("offers Send for the next message and shows no Stop button while a send is in flight", () => {
    // The maintainer's call (2026-11-12): the Dodaios chat has no Stop
    // button. A turn is stopped by writing "stop".
    useAgentChatStore.setState({ activeSessionId: "s1", busy: true, timeline: EMPTY_TIMELINE });
    render(<ChatStage />);
    expect(screen.queryByTestId("composer-stop")).toBeNull();
    // The next message can be written and sent while the assistant works.
    expect(screen.queryByTestId("composer-send")).toBeNull();
    const box = screen.getByRole("textbox");
    box.textContent = "and one more thing";
    fireEvent.input(box);
    expect((screen.getByTestId("composer-send") as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByTestId("composer-stop")).toBeNull();
  });

  it.each(["stop", "Stopp!", "please stop", "abbrechen"])("ends the running turn when %s is written, and sends nothing", async (word) => { // i18n-allow: input vocabulary
    const cancel = vi.fn(async () => {});
    const send = vi.fn(async () => "sent" as const);
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "write the report" }),
      ev("turn_started", { turn_id: "t7", provider: "openai", model: "", effort: "", runner: "api" }),
    ]);
    useAgentChatStore.setState({ activeSessionId: "s7", timeline, cancel, send });
    render(<ChatStage />);
    const box = screen.getByRole("textbox");
    box.textContent = word;
    fireEvent.input(box);
    fireEvent.click(screen.getByTestId("composer-send"));
    await waitFor(() => expect(cancel).toHaveBeenCalledWith("typed-stop"));
    expect(send).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox").textContent).toBe("");
  });

  it("lets the stop word out when nothing else can be sent", async () => {
    // The button it replaces worked with the connection down or the model
    // seat gone; the word must too, by the Send button as well as by Enter.
    const cancel = vi.fn(async () => {});
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "write the report" }),
      ev("turn_started", { turn_id: "t6", provider: "openai", model: "", effort: "", runner: "api" }),
    ]);
    useAgentChatStore.setState({ activeSessionId: "s6", timeline, cancel, connections: [] });
    useEventStore.setState({ connected: false });
    render(<ChatStage />);
    const box = screen.getByRole("textbox");
    box.textContent = "one more thing";
    fireEvent.input(box);
    expect((screen.getByTestId("composer-send") as HTMLButtonElement).disabled).toBe(true);
    box.textContent = "stop";
    fireEvent.input(box);
    const send = screen.getByTestId("composer-send") as HTMLButtonElement;
    expect(send.disabled).toBe(false);
    fireEvent.click(send);
    await waitFor(() => expect(cancel).toHaveBeenCalledWith("typed-stop"));
  });

  it("sends a sentence that only contains the word, and the bare word when nothing runs", async () => {
    const cancel = vi.fn(async () => {});
    const send = vi.fn(async (_text: string) => "sent" as const);
    const running = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "write the report" }),
      ev("turn_started", { turn_id: "t8", provider: "openai", model: "", effort: "", runner: "api" }),
    ]);
    useAgentChatStore.setState({ activeSessionId: "s8", timeline: running, cancel, send });
    render(<ChatStage />);
    const write = (text: string) => {
      const box = screen.getByRole("textbox");
      box.textContent = text;
      fireEvent.input(box);
      fireEvent.click(screen.getByTestId("composer-send"));
    };
    write("stop using tables in the report");
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    expect(send.mock.calls[0][0]).toBe("stop using tables in the report");
    // The turn is over: "stop" is a message like any other now.
    act(() => useAgentChatStore.setState({
      timeline: reduceEvents(running, [ev("turn_finished", { turn_id: "t8", status: "done" })]),
    }));
    expect(screen.getByRole("textbox").getAttribute("data-placeholder")).toBe("Ask anything…");
    write("stop");
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls[1][0]).toBe("stop");
    expect(cancel).not.toHaveBeenCalled();
  });

  it("keeps the Stop button in the Agentic IDE, where the word is a message", async () => {
    const cancel = vi.fn(async () => {});
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "fix the test" }),
      ev("turn_started", { turn_id: "t9", provider: "openai", model: "", effort: "", runner: "api" }),
    ]);
    useAgentSessionStore.setState({ ...seedState(), activeSessionId: "ide-9", timeline, cancel });
    render(<AgentChatStoreProvider store={useAgentSessionStore}><ChatStage /></AgentChatStoreProvider>);
    fireEvent.click(screen.getByTestId("composer-stop"));
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("textbox").getAttribute("data-placeholder")).toBe("Ask anything…");
  });

  it("ends an answer being written beside the main thread when stop is written", async () => {
    // The main turn is done; a message sent meanwhile is still being answered.
    // It has no control of its own: the word stops it, and the box says so.
    const cancel = vi.fn(async () => {});
    const send = vi.fn(async () => "sent" as const);
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      { seq: 1, ts_ms: 1, kind: "turn_started", payload: { turn_id: "t1" } },
      { seq: 2, ts_ms: 2, kind: "notice", payload: { kind: "side_thread_started", side_id: "s1", text: "and this?" } },
      { seq: 3, ts_ms: 3, kind: "turn_finished", payload: { turn_id: "t1", status: "done" } },
    ] as AgentChatEvent[]);
    useAgentChatStore.setState({ activeSessionId: "s1", busy: false, timeline, cancel, send });
    render(<ChatStage />);
    const box = screen.getByRole("textbox");
    expect(box.getAttribute("data-placeholder")).toBe('Write “stop” to stop…');
    box.textContent = "stop";
    fireEvent.input(box);
    fireEvent.click(screen.getByTestId("composer-send"));
    await waitFor(() => expect(cancel).toHaveBeenCalledWith("typed-stop"));
    expect(send).not.toHaveBeenCalled();
  });

  it("shows the assistant typing from the send until its answer is written", () => {
    // The look this guards (maintainer, 2026-11-12): the chat reads like a
    // messenger. While the assistant thinks or works, three dots stand in a
    // bubble where its next message will be.
    const sent = reduceEvents(EMPTY_TIMELINE, [ev("user_message", { text: "hello" })]);
    useAgentChatStore.setState({ activeSessionId: "s1", busy: true, timeline: sent });
    render(<ChatStage />);
    // The message is in and no turn has started: it types already.
    const waiting = screen.getByTestId("agent-turn-awaiting");
    expect(within(waiting).getByTestId("typing-indicator")).toBeTruthy();
    expect(within(waiting).getByRole("status").textContent).toContain("Working");
    expect(within(waiting).getByTestId("lead-face").getAttribute("data-pet")).toBe("working");

    // The turn takes over: still one set of dots, now the turn's own.
    const started = reduceEvents(sent, [
      ev("turn_started", { turn_id: "t1", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" }),
      ev("reasoning_started", { turn_id: "t1", message_id: "m1" }),
    ]);
    act(() => useAgentChatStore.setState({ busy: false, timeline: started }));
    expect(screen.queryByTestId("agent-turn-awaiting")).toBeNull();
    expect(screen.getAllByTestId("typing-indicator")).toHaveLength(1);
    expect(within(screen.getByTestId("work-trace")).getByTestId("typing-indicator")).toBeTruthy();
    expect(screen.getAllByTestId("lead-face")).toHaveLength(1);

    // The answer is there: nobody is typing.
    const done = reduceEvents(started, [
      ev("assistant_text", { turn_id: "t1", message_id: "m2", text: "Hello!" }),
      ev("turn_finished", { turn_id: "t1", status: "done", duration_ms: 3000, usage: {} }),
    ]);
    act(() => useAgentChatStore.setState({ timeline: done }));
    expect(screen.queryByTestId("typing-indicator")).toBeNull();
    expect(screen.getByTestId("work-trace").textContent).toContain("Hello!");
  });

  it("keeps the line the assistant sent before it looked, and then gives the answer", () => {
    // The look this guards (maintainer, 2026-11-12): the assistant says what
    // it is about to do, the way a person would, and comes back with the
    // answer. Its first message used to vanish into the fold once the turn
    // was done.
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "Hows the weather btw" }),
      ev("turn_started", { turn_id: "t8", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" }),
      ev("assistant_text", { turn_id: "t8", message_id: "m1", text: "I'll check the weather for this evening." }),
      ev("tool_call", { turn_id: "t8", call_id: "c1", name: "PowerShell", input: { command: "Get-Weather" } }),
      ev("tool_result", { turn_id: "t8", call_id: "c1", output: "32", is_error: false }),
      ev("assistant_text", { turn_id: "t8", message_id: "m2", text: "Hot and humid today, around 32°C." }),
      ev("turn_finished", { turn_id: "t8", status: "done", duration_ms: 8000, usage: {} }),
    ]);
    useAgentChatStore.setState({ activeSessionId: "s8", timeline });
    render(<ChatStage />);

    const trace = screen.getByTestId("work-trace");
    const bubbles = within(trace).getAllByTestId("lead-bubble");
    expect(bubbles.map((node) => node.textContent)).toEqual(["I'll check the weather for this evening.", "Hot and humid today, around 32°C."]);
    // The conversation is the two messages: no fold and no step between them.
    expect(within(trace).queryByTestId("conversation-work-fold")).toBeNull();
    expect(trace.textContent).not.toContain("Get-Weather");
    // Nothing under the turn opens the step either (maintainer, 2026-11-13).
    expect(within(trace).queryByRole("button")).toBeNull();
    expect(within(trace).getByRole("status").className).toBe("sr-only");
  });

  it("shows nobody typing under an old message that never got an answer", () => {
    const sent = reduceEvents(EMPTY_TIMELINE, [ev("user_message", { text: "hello" })]);
    useAgentChatStore.setState({ activeSessionId: "s1", busy: false, timeline: sent });
    render(<ChatStage />);
    expect(screen.getByTestId("agent-message-user").textContent).toContain("hello");
    expect(screen.queryByTestId("typing-indicator")).toBeNull();
  });

  it("shows that a running turn is alive with the dots alone: no clock and no tokens", () => {
    vi.useFakeTimers();
    try {
      const started = Date.now();
      const timeline = reduceEvents(EMPTY_TIMELINE, [
        ev("user_message", { text: "dig into it" }),
        { seq: 2, ts_ms: started, kind: "turn_started", payload: { turn_id: "t1", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" } },
        { seq: 0, ts_ms: started, kind: "reasoning_started", payload: { turn_id: "t1", message_id: "m1" } },
        { seq: 0, ts_ms: started, kind: "usage_delta", payload: { turn_id: "t1", usage: { input_tokens: 12, output_tokens: 4800 } } },
      ]);
      useAgentChatStore.setState({ activeSessionId: "s1", timeline });
      render(<ChatStage />);

      // A thought still running draws NO row of its own: the live line below
      // already says the turn is thinking, and two lines saying it at once is
      // the duplication the maintainer objected to (2026-08-25).
      expect(screen.queryByTestId("agent-reasoning")).toBeNull();

      const trace = screen.getByTestId("work-trace");
      expect(within(trace).getByTestId("typing-indicator")).toBeTruthy();
      // The word is only read out, and no figure runs beside the dots
      // (maintainer, 2026-11-13): neither the tokens nor a clock.
      const live = within(trace).getByRole("status");
      expect(live.className).toBe("sr-only");
      expect(live.textContent).toContain("Working");
      act(() => {
        vi.advanceTimersByTime(12_000);
      });
      expect(trace.textContent).not.toMatch(/4\.8k|tokens|\d+s/);
      // No hairline rail runs down the turn any more.
      expect(screen.queryByTestId("agent-turn-rail")).toBeNull();
      // A running turn shows no receipt yet.
      expect(screen.queryByTestId("agent-turn-footer")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("draws none of the model's reasoning and none of its steps: the chat is messages", () => {
    // The complaint this guards (maintainer, 2026-11-12): the model's
    // private thoughts and a line per tool call stood in the conversation
    // between its messages. The front-page chat shows what the assistant
    // says, never what it thought and, since 2026-11-13, never its steps
    // (the 2026-08-25 scratchpad lives on in the IDE and the agent chats,
    // agentchat/AgentTimeline.test.tsx).
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "look into it" }),
      ev("turn_started", { turn_id: "t4", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" }),
      ev("reasoning", { turn_id: "t4", text: "First the port.", duration_ms: 1000 }),
      ev("tool_call", { turn_id: "t4", call_id: "c1", name: "PowerShell", input: { command: "Get-NetTCPConnection" } }),
      ev("tool_result", { turn_id: "t4", call_id: "c1", output: "ok", is_error: false }),
      ev("reasoning", { turn_id: "t4", text: "It is listening.", duration_ms: 4000 }),
      ev("assistant_text", { turn_id: "t4", message_id: "m1", text: "Running." }),
      ev("turn_finished", { turn_id: "t4", status: "done", duration_ms: 6000, usage: {} }),
    ]);
    useAgentChatStore.setState({ activeSessionId: "s4", timeline });
    render(<ChatStage />);

    const trace = screen.getByTestId("work-trace");
    expect(within(trace).queryByTestId("conversation-work-fold")).toBeNull();
    expect(trace.querySelector("[data-trace-entry]")).toBeNull();
    expect(trace.textContent).not.toContain("Get-NetTCPConnection");
    expect(within(trace).getAllByTestId("lead-bubble").map((node) => node.textContent)).toEqual(["Running."]);
    // Under the turn stands nothing (maintainer, 2026-11-13): no time, no
    // number of steps, and nothing that opens them.
    const status = within(trace).getByRole("status");
    expect(status.className).toBe("sr-only");
    expect(status.textContent).toBe("Done");
    expect(within(trace).queryByRole("button")).toBeNull();
    expect(trace.textContent).not.toMatch(/6s|step|Thought/);
    expect(document.querySelectorAll("[data-trace-entry='reasoning']")).toHaveLength(0);
  });

  it("keeps thoughts and steps out of a running turn too: only the dots say it is working", () => {
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "look into it" }),
      ev("turn_started", { turn_id: "t6", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" }),
      ev("reasoning", { turn_id: "t6", text: "The user wants the port.", duration_ms: 1000 }),
      ev("assistant_text", { turn_id: "t6", message_id: "m1", text: "I'll look at the port." }),
      ev("tool_call", { turn_id: "t6", call_id: "c1", name: "PowerShell", input: { command: "Get-NetTCPConnection" } }),
      ev("tool_result", { turn_id: "t6", call_id: "c1", output: "ok", is_error: false }),
      ev("tool_call", { turn_id: "t6", call_id: "c2", name: "PowerShell", input: { command: "Get-NetFirewallRule" } }),
      ev("reasoning_started", { turn_id: "t6", message_id: "m2" }),
      ev("reasoning_delta", { turn_id: "t6", message_id: "m2", text: "Now the firewall." }),
    ]);
    useAgentChatStore.setState({ activeSessionId: "s6", timeline });
    render(<ChatStage />);

    const trace = screen.getByTestId("work-trace");
    expect(trace.textContent).not.toContain("The user wants the port.");
    expect(trace.textContent).not.toContain("Now the firewall.");
    expect(screen.queryByTestId("reasoning-body")).toBeNull();
    expect(trace.textContent).not.toMatch(/Thinking|Thought/);
    // Neither the finished step nor the running one draws a line.
    expect(trace.textContent).not.toContain("Get-NetTCPConnection");
    expect(trace.textContent).not.toContain("Get-NetFirewallRule");
    expect(trace.querySelector("[data-trace-entry]")).toBeNull();
    // What it said is there, the dots under it, and the state is read out.
    expect(within(trace).getAllByTestId("lead-bubble").map((node) => node.textContent)).toEqual(["I'll look at the port."]);
    expect(within(trace).getByTestId("typing-indicator")).toBeTruthy();
    expect(within(trace).getByRole("status").textContent).toContain("Working");
  });

  it("shows no fold for a turn that only thought before it answered", () => {
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "hello" }),
      ev("turn_started", { turn_id: "t7", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" }),
      ev("reasoning", { turn_id: "t7", text: "A greeting. Greet back.", duration_ms: 3000 }),
      ev("assistant_text", { turn_id: "t7", message_id: "m1", text: "Hello!" }),
      ev("turn_finished", { turn_id: "t7", status: "done", duration_ms: 4000, usage: {} }),
    ]);
    useAgentChatStore.setState({ activeSessionId: "s7", timeline });
    render(<ChatStage />);

    const trace = screen.getByTestId("work-trace");
    expect(within(trace).queryByTestId("conversation-work-fold")).toBeNull();
    expect(trace.textContent).toContain("Hello!");
    expect(trace.textContent).not.toContain("A greeting.");
  });

  it("says how a turn ended — including one that answered nothing at all", () => {
    // The complaint this guards (maintainer, 2026-08-25): a turn whose only
    // step was a denied command simply stopped drawing, and there was no way
    // to tell a finished turn from one still thinking.
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "what is on my list?" }),
      ev("turn_started", { turn_id: "t4", provider: "google", model: "gemini-3-flash", effort: "medium", runner: "agy" }),
      ev("tool_call", { turn_id: "t4", call_id: "c1", name: "run_command", input: { CommandLine: "gws tasks list" } }),
      ev("tool_result", { turn_id: "t4", call_id: "c1", output: "permission check failed for command\nuser denied permission", is_error: true }),
      ev("turn_finished", { turn_id: "t4", status: "done", duration_ms: 28_000, usage: { input_tokens: 35_400, output_tokens: 448 } }),
    ]);
    useAgentChatStore.setState({ activeSessionId: "s4", timeline });
    render(<ChatStage />);

    const outcome = within(screen.getByTestId("work-trace")).getByRole("status");
    expect(outcome.textContent).toContain("Finished without an answer");
    // The line says how it ended and counts nothing: no time, no tokens.
    expect(outcome.textContent).not.toMatch(/448|35\.4k|28s/);
    // With no answer the report IS the outcome: it stands open and the
    // failure reads without opening anything.
    expect(screen.getByText(/permission check failed for command/)).toBeTruthy();
    expect(document.querySelector("[data-trace-entry='call']")?.textContent).toContain("Failed");
    // Nothing claims to still be working.
    expect(screen.queryByTestId("agent-turn-live")).toBeNull();
  });

  it("keeps full tool input behind the detail disclosure", () => {
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("turn_started", { turn_id: "t5", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" }),
      ev("tool_call", { turn_id: "t5", call_id: "c1", name: "Bash", input: { command: "ls -la" } }),
      ev("tool_result", { turn_id: "t5", call_id: "c1", output: "a.py", is_error: false }),
      ev("tool_call", { turn_id: "t5", call_id: "c2", name: "Grep", input: { pattern: "TODO", path: "src", "-n": true } }),
      ev("tool_result", { turn_id: "t5", call_id: "c2", output: "src/a.py:3", is_error: false }),
      ev("turn_finished", { turn_id: "t5", status: "done", duration_ms: 900, usage: {} }),
    ]);
    useAgentChatStore.setState({ activeSessionId: "s5", timeline });
    render(<ChatStage />);
    // With no answer the timeline stands open: one quiet line for the stretch.
    const stretch = screen.getByRole("button", { name: /^Ran a command, searched the files/ });
    fireEvent.click(stretch);
    const [shell, grep] = Array.from(document.querySelectorAll<HTMLElement>("[data-trace-entry='call']"));
    expect(shell.textContent).toContain("ls -la");
    expect(grep.textContent).toContain("Searched for TODO in src");
    // The full receipt is available on demand: what ran, and what it printed.
    fireEvent.click(within(shell).getByRole("button", { name: /^ls -la/ }));
    expect(shell.querySelector("[data-trace-output]")?.textContent).toContain("a.py");
    // More than the line could say, so the whole input is worth printing.
    fireEvent.click(within(grep).getByRole("button", { name: /^Searched for TODO/ }));
    expect(within(grep).getByText("Input")).toBeTruthy();
  });

  it("uses readable tool names and preserves canonical detail where a turn's work stands open", () => {
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "check the repo" }),
      ev("turn_started", { turn_id: "t9", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" }),
      ev("tool_call", { turn_id: "t9", call_id: "c1", name: "PowerShell", input: { command: "Get-ChildItem -Path 'C:\\Users'" } }),
      ev("tool_result", { turn_id: "t9", call_id: "c1", output: "ok", is_error: false }),
      ev("tool_call", { turn_id: "t9", call_id: "c2", name: "mcp__github__create_issue", input: { title: "Bug" } }),
      ev("tool_result", { turn_id: "t9", call_id: "c2", output: "#12", is_error: false }),
      ev("reasoning", { turn_id: "t9", text: "", duration_ms: 8585 }),
      ev("turn_finished", { turn_id: "t9", status: "done", duration_ms: 12_000, usage: { input_tokens: 2, output_tokens: 219 }, cost_usd: 0.8483 }),
    ]);
    useAgentChatStore.setState({ activeSessionId: "s9", timeline });
    render(<ChatStage />);
    // The turn ended without a word, so its work is all it has to show.
    // The plugin the turn used shows on its line by its own logo.
    const stretch = screen.getByRole("button", { name: /^Ran a command, used GitHub/ });
    expect(stretch.querySelector("img, [data-logo]")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Ran a command, used GitHub/ }));
    const [shell, github] = Array.from(document.querySelectorAll<HTMLElement>("[data-trace-entry='call']"));
    expect(shell.textContent).toContain("Get-ChildItem -Path 'C:\\Users'");
    fireEvent.click(within(shell).getByRole("button"));
    expect(shell.querySelector("[data-trace-output]")?.textContent).toContain("ok");
    // An MCP call is named after its service, and wears its mark.
    expect(github.textContent).toContain("GitHub");
    expect(github.querySelector("img, [data-logo]")).toBeTruthy();

    // Thinking with no readable text draws no line of its own.
    expect(document.querySelectorAll("[data-trace-entry='reasoning']")).toHaveLength(0);

    // The line under it says how it ended, without the time or the usage.
    const footer = within(screen.getByTestId("work-trace")).getByRole("status");
    expect(footer.textContent).toContain("Finished without an answer");
    expect(footer.textContent).not.toMatch(/12s|219|\$/);
  });

  it("shows no time, usage or price under an answer, even for a turn billed to a per-token key", () => {
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "check the repo" }),
      ev("turn_started", { turn_id: "t10", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" }),
      ev("assistant_text", { turn_id: "t10", message_id: "m1", text: "Done." }),
      ev("turn_finished", { turn_id: "t10", status: "done", duration_ms: 12_000, usage: { input_tokens: 2, output_tokens: 219 }, cost_usd: 0.8483, billed_via_key: true }),
    ]);
    useAgentChatStore.setState({ activeSessionId: "s10", timeline });
    render(<ChatStage />);
    // The request this guards (maintainer, 2026-11-13): "12s · 219 tokens ·
    // 6 steps · 1 step did not work" stood under every answer of the
    // front-page chat. The answer is the last thing a turn shows.
    const trace = screen.getByTestId("work-trace");
    expect(within(trace).getByRole("status").className).toBe("sr-only");
    expect(trace.textContent).not.toMatch(/12s|219|tokens|\$0\.8483/);
  });

  it("reads an opened voice session in the chat column instead of the previous chat", () => {
    // The regression this guards: the sidebar's history lists voice sessions
    // next to agent chats, and clicking one used to load its words into the
    // event store while the stage kept rendering the agent timeline — the
    // screen did not change at all.
    const timeline = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { turn_id: "t1", text: "Earlier agent chat" }),
    ]);
    useAgentChatStore.setState({ activeSessionId: null, timeline });
    useEventStore.setState({
      activeKind: "voice",
      activeThreadId: "v1",
      conversations: [
        {
          kind: "voice",
          id: "v1",
          title: "Kitchen timer",
          preview: "set a timer",
          created_ms: 1,
          updated_ms: 2,
          message_count: 2,
        },
      ],
      messages: [
        { id: "m1", role: "user", content: "set a timer", ts: 1 },
        { id: "m2", role: "assistant", content: "Ten minutes, running.", ts: 2 },
      ],
      thinkingTraces: {},
    });
    render(<ChatStage />);

    const stage = screen.getByTestId("voice-thread-stage");
    expect(stage.getAttribute("data-thread")).toBe("v1");
    expect(stage.textContent).toContain("Kitchen timer");
    expect(stage.textContent).toContain("Ten minutes, running.");
    // A spoken thread has no composer: it is continued by talking.
    expect(screen.queryByTestId("agent-composer")).toBeNull();
    expect(screen.getByTestId("continue-by-voice")).toBeTruthy();
  });

  it("continues a spoken thread by starting a call seeded with it", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ armed: true, seeded_turns: 2 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    useAgentChatStore.setState({ activeSessionId: null, timeline: EMPTY_TIMELINE });
    useHomeStore.setState({ surface: "chat", jarvisCardMode: "chat", transcript: [] });
    useEventStore.setState({
      activeKind: "voice",
      activeThreadId: "v1",
      messages: [
        { id: "m1", role: "user", content: "set a timer", ts: 1 },
        { id: "m2", role: "assistant", content: "Ten minutes, running.", ts: 2 },
      ],
      thinkingTraces: {},
    });
    render(<ChatStage />);

    await act(async () => {
      fireEvent.click(screen.getByTestId("continue-by-voice"));
    });

    // The call itself starts — switching the screen alone left a silent orb.
    expect(fetchMock).toHaveBeenCalledWith("/api/chats/voice/v1/speak", { method: "POST" });
    expect(useHomeStore.getState().surface).toBe("voice");
    expect(useHomeStore.getState().jarvisCardMode).toBe("voice");
    expect(useHomeStore.getState().transcript.length).toBe(2);
    vi.unstubAllGlobals();
  });

  it("says so when the seeded call could not start", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ armed: false, seeded_turns: 0 }), { status: 200 })),
    );
    const pushToast = vi.fn();
    useAgentChatStore.setState({ activeSessionId: null, timeline: EMPTY_TIMELINE });
    useEventStore.setState({
      activeKind: "voice",
      activeThreadId: "v1",
      messages: [{ id: "m1", role: "user", content: "set a timer", ts: 1 }],
      thinkingTraces: {},
      pushToast,
    });
    render(<ChatStage />);

    await act(async () => {
      fireEvent.click(screen.getByTestId("continue-by-voice"));
    });

    expect(pushToast).toHaveBeenCalledWith("warning", expect.any(String));
    vi.unstubAllGlobals();
  });

  it("gives the stage back to the agent chat once a session is open", () => {
    useEventStore.setState({ activeKind: "voice", activeThreadId: "v1", messages: [] });
    useAgentChatStore.setState({ activeSessionId: "s1", timeline: EMPTY_TIMELINE });
    render(<ChatStage />);
    expect(screen.queryByTestId("voice-thread-stage")).toBeNull();
    expect(screen.getByTestId("chat-stage")).toBeTruthy();
  });
});
