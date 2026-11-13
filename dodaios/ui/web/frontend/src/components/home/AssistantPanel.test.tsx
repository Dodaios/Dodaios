import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EMPTY_TIMELINE, type TimelineItem } from "@/components/agentchat/reduce";
import { takePluginFocus } from "@/lib/customConnector";
import { useAgentChatStore } from "@/store/agentChat";
import { useEventStore } from "@/store/events";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { useSettingsJump } from "@/store/settingsJump";

const chats = vi.hoisted(() => ({
  rows: [] as { kind: "voice" | "agent"; id: string; title: string; preview: string; updatedMs: number; messageCount: number; provider: string; raw: null }[],
  active: "",
  open: vi.fn(),
}));
vi.mock("@/components/home/chatRows", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/home/chatRows")>()),
  useChatRows: () => ({ rows: chats.rows, isActive: (row: { id: string }) => row.id === chats.active, open: chats.open, remove: vi.fn() }),
}));
vi.mock("@/components/home/AssistantRoutineDialog", () => ({
  default: ({ routineId, onClose }: { routineId: string; onClose: () => void }) => (
    <div data-testid="routine-dialog">{routineId}<button onClick={onClose}>Close routine</button></div>
  ),
}));
vi.mock("@/components/home/AssistantFileDialog", () => ({
  default: ({ fileId }: { fileId: string }) => <div data-testid="file-dialog">{fileId}</div>,
}));
vi.mock("@/components/pets/PetMark", () => ({ PetMark: () => <span data-testid="pet" /> }));
vi.mock("@/hooks/useVoiceEngineDisplay", () => ({
  useVoiceEngineDisplay: () => ({ tier: "realtime", providerId: "test", providerLabel: "Test Voice", model: "m1" }),
}));
vi.mock("@/views/assistant/api", () => ({
  useSoulProfile: () => ({ isLoading: false, data: { name: "Nova", wake_phrase: "Hey Nova", learning: true, files: [
    { id: "soul", filename: "SOUL.md" }, { id: "instructions", filename: "Nova.md" },
    { id: "memory", filename: "MEMORY.md" }, { id: "user", filename: "USER.md" },
  ] } }),
}));
const skills = vi.hoisted(() => ({ list: [] as { name: string; state: string }[], set: vi.fn() }));
vi.mock("@/hooks/useSkills", () => ({
  useSkillsList: () => ({ isLoading: false, data: { skills: skills.list } }),
  useSetSkillEnabled: () => ({ isPending: false, mutate: skills.set }),
}));
const tasks = vi.hoisted(() => ({ setTaskEnabled: vi.fn(async () => undefined) }));
vi.mock("@/lib/tasksApi", () => ({ setTaskEnabled: tasks.setTaskEnabled }));
const call = vi.hoisted(() => ({ live: false, busy: false, toggle: vi.fn() }));
vi.mock("@/components/home/assistantStatus", () => ({
  useVoiceModeSwitch: () => ({ on: call.live, live: call.live, busy: call.busy, enter: call.toggle, exit: call.toggle, toggle: call.toggle }),
}));
vi.mock("@/lib/voiceApi", () => ({ warmVoiceCall: vi.fn() }));
const external = vi.hoisted(() => ({ open: vi.fn(async () => true) }));
vi.mock("@/lib/openExternal", () => ({ openExternalUrl: external.open }));
const local = vi.hoisted(() => ({ open: vi.fn(async () => true) }));
vi.mock("@/lib/openLocalPath", () => ({ openLocalPath: local.open }));

import AssistantPanel from "./AssistantPanel";

function chat(id: string, title: string, updatedMs: number) {
  return { kind: "agent" as const, id, title, preview: "", updatedMs, messageCount: 2, provider: "", raw: null };
}

/** What the backend answers, by path; a test overrides the paths it is about. */
type Backend = Record<string, unknown>;

function mount(routines: unknown[], backend: Backend = {}) {
  const answers: Backend = {
    "/api/agent-chat/lead": { session_id: "lead", computer_id: "" },
    "/api/society/agents/jarvis/routines": { routines },
    "/api/computers": { computers: [] },
    "/api/computers/this": { name: "Adas-MacBook-Pro.local", os_id: "macos" },
    "/api/agent-chat/lead/threads": { threads: [] },
    "/api/agent-chat/lead/channels": { channels: [] },
    "/api/agent-chat/lead/files": { files: [] },
    "/api/outputs": [],
    ...backend,
  };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const path = String(url).split("?")[0];
    return path in answers
      ? new Response(JSON.stringify(answers[path]), { status: 200 })
      : new Response("{}", { status: 404 });
  }));
  const onConversation = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><AssistantPanel onConversation={onConversation} /></QueryClientProvider>);
  return onConversation;
}

function library() {
  fireEvent.click(screen.getByTestId("assistant-panel-tab-library"));
}

function computer(id: string, name: string, status = "online") {
  return { id, name, kind: "server", provider: "generic", host: `${id}.example`, port: 22, username: "root", auth: "key",
    provider_ref: null, region: null, plan: null, host_key: null, host_fingerprint: null, created_at: 1, facts: null,
    health: { status, checked_at: 1, latency_ms: 20, message: null, load_1m: null, mem_used_pct: null, disk_used_pct: null, uptime_s: null },
    enabled: true, busy: false };
}

function thread(id: string, title: string, more: Record<string, unknown> = {}) {
  return { session_id: id, title, cli_title: "", provider: "claude", cwd: "/work", briefed_ms: 100, updated_ms: 100, running: false, waiting: false, ...more };
}

function turn(status: "running" | "done", blocks: unknown[] = [], more: Record<string, unknown> = {}): TimelineItem {
  return { type: "turn", id: `t-${status}`, provider: "", model: "", effort: "", runner: "", status, blocks, startedMs: 1,
    durationMs: null, usage: null, liveUsage: null, costUsd: null, error: null, ...more } as unknown as TimelineItem;
}

/** Put the conversation on stage with these items. */
function onStage(items: TimelineItem[]) {
  act(() => useAgentChatStore.setState({ activeSessionId: "lead", timeline: { ...EMPTY_TIMELINE, items } }));
}

beforeEach(() => {
  localStorage.clear();
  chats.rows = [];
  chats.active = "";
  chats.open.mockReset();
  skills.list = [];
  skills.set.mockReset();
  tasks.setTaskEnabled.mockClear();
  call.live = false;
  call.busy = false;
  call.toggle.mockReset();
  external.open.mockClear();
  local.open.mockClear();
  takePluginFocus();
  useEventStore.setState({ activeSection: "chats", connected: true, visualStage: null, assistantName: "Nova" });
  useAgentChatStore.setState({ activeSessionId: null, timeline: EMPTY_TIMELINE, sessions: [] });
  useIdeThreadsStore.setState({ seen: {} });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AssistantPanel", () => {
  it("shows the person's pet and the name they gave the assistant, and they lead back to the conversation", () => {
    const onConversation = mount([]);
    const face = screen.getByTestId("assistant-panel-conversation");
    expect(face.textContent).toContain("Nova");
    expect(face.textContent).not.toContain("Dodaios");
    expect(face.querySelector('[data-testid="pet"]')).toBeTruthy();
    fireEvent.click(face);
    expect(onConversation).toHaveBeenCalledTimes(1);
  });

  it("falls back to the product's name while the assistant has none of its own", () => {
    useEventStore.setState({ assistantName: "Assistant" });
    mount([]);
    expect(screen.getByTestId("assistant-panel-conversation").textContent).toContain("Dodaios");
  });

  it("lists the routines with a switch each, without the scheduler's name tag", async () => {
    mount([
      { id: "r1", title: "[agent:Dodaios] Morning mail", state: "scheduled" },
      { id: "r2", title: "Weekly review", state: "paused" },
    ]);
    library();
    const first = await screen.findByTestId("assistant-automation-r1");
    expect(first.textContent).toContain("Morning mail");
    expect(first.textContent).not.toContain("[agent:");
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/society/agents/jarvis/routines");
    expect(screen.getByTestId("assistant-automation-switch-r1").getAttribute("aria-checked")).toBe("true");
    const paused = screen.getByTestId("assistant-automation-switch-r2");
    expect(paused.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(paused);
    await waitFor(() => expect(tasks.setTaskEnabled).toHaveBeenCalledWith("r2", true));
  });

  it("opens a routine's own page from its row", async () => {
    mount([{ id: "r1", title: "Morning mail", state: "scheduled" }]);
    library();
    fireEvent.click(await screen.findByTestId("assistant-automation-r1"));
    expect((await screen.findByTestId("routine-dialog")).textContent).toContain("r1");
    fireEvent.click(screen.getByText("Close routine"));
    expect(screen.queryByTestId("routine-dialog")).toBeNull();
  });

  it("says so when there is no routine yet", async () => {
    mount([]);
    library();
    await waitFor(() => expect(screen.getByTestId("assistant-automations-empty").textContent).toMatch(/None yet/));
  });

  it("names the voice model and the wake word, and each leads to its settings", () => {
    mount([]);
    library();
    expect(screen.getByTestId("assistant-voice-model").textContent).toContain("Test Voice");
    const wake = screen.getByTestId("assistant-voice-wake");
    expect(wake.textContent).toContain("Hey Nova");
    fireEvent.click(wake);
    expect(useSettingsJump.getState().take()).toBe("wake-word");
    expect(useEventStore.getState().activeSection).toBe("settings");
  });

  it("lists the newest earlier chats without the conversation itself", async () => {
    chats.rows = [chat("lead", "The one conversation", 9), ...Array.from({ length: 6 }, (_, index) => chat(`c${index}`, `Chat ${index}`, 8 - index))];
    mount([]);
    library();
    await waitFor(() => expect(screen.queryByTestId("assistant-recent-lead")).toBeNull());
    expect(screen.getAllByTestId(/^assistant-recent-c\d$/)).toHaveLength(4);
    fireEvent.click(screen.getByTestId("assistant-recent-c2"));
    expect(chats.open).toHaveBeenCalledWith(chats.rows[3]);
    expect(screen.getByTestId("earlier-chats")).toBeTruthy();
  });

  it("keeps the files and the skills in the library, and remembers the tab", async () => {
    skills.list = [{ name: "zeta", state: "disabled" }, { name: "alpha", state: "active" }, { name: "draft-one", state: "draft" }];
    mount([]);
    expect(screen.queryByTestId("assistant-file-user")).toBeNull();
    fireEvent.click(screen.getByTestId("assistant-panel-tab-library"));
    expect(localStorage.getItem("jarvis.sidebar.assistantTab.v1")).toBe("library");
    expect(["soul", "instructions", "memory", "user"].map((id) => screen.getByTestId(`assistant-file-${id}`).textContent))
      .toEqual(["SOUL.md", "Nova.md", "MEMORY.md", "USER.md"]);
    fireEvent.click(screen.getByTestId("assistant-file-user"));
    expect((await screen.findByTestId("file-dialog")).textContent).toBe("user");
    // Active skills lead; a draft has no switch to flip.
    const switches = screen.getAllByTestId(/^assistant-skill-switch-/).map((node) => node.getAttribute("data-testid"));
    expect(switches).toEqual(["assistant-skill-switch-alpha", "assistant-skill-switch-zeta"]);
    fireEvent.click(screen.getByTestId("assistant-skill-switch-zeta"));
    expect(skills.set).toHaveBeenCalledWith({ name: "zeta", enabled: true });
    fireEvent.click(screen.getByTestId("assistant-skills-all"));
    expect(useEventStore.getState().activeSection).toBe("skills");
  });

  it("says what the assistant is doing right now, under its name", async () => {
    mount([]);
    const status = () => screen.getByTestId("assistant-panel-status");
    expect(status().getAttribute("data-state")).toBe("idle");
    expect(status().textContent).toBe("Ready");

    // A turn that answers: the activity line's own words.
    onStage([turn("running")]);
    await waitFor(() => expect(status().getAttribute("data-state")).toBe("working"));
    // The phrase is paced like the activity line: it settles within its hold.
    await waitFor(
      () => expect(status().textContent).toMatch(/Thinking|Planning the next step|Weighing it up|Connecting the dots/),
      { timeout: 2000 },
    );

    // A card that waits for the person comes first.
    onStage([turn("running", [{ kind: "tool", callId: "c1", name: "shell", output: null, approval: { summary: "Run it?", decision: null } }])]);
    await waitFor(() => expect(status().textContent).toBe("Needs you"));

    // Work handed off still runs after its turn closed.
    onStage([turn("done", [], { background: ["Scout", "Atlas"] })]);
    await waitFor(() => expect(status().textContent).toBe("2 agents at work"));
  });

  it("follows the chat list while an earlier chat is on stage, and says when the app is not connected", async () => {
    mount([]);
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/agent-chat/lead"));
    // Another chat's running turn is not the assistant's.
    act(() => useAgentChatStore.setState({ activeSessionId: "earlier", timeline: { ...EMPTY_TIMELINE, items: [turn("running")] } }));
    await waitFor(() => expect(screen.getByTestId("assistant-panel-status").textContent).toBe("Ready"));
    act(() => useAgentChatStore.setState({ sessions: [{ session_id: "lead", running: true }] as never }));
    await waitFor(() => expect(screen.getByTestId("assistant-panel-status").textContent).toBe("Working"));
    act(() => useEventStore.setState({ connected: false, wsWarming: false }));
    await waitFor(() => expect(screen.getByTestId("assistant-panel-status").textContent).toBe("Offline"));
  });

  it("starts and ends a call from its button", () => {
    mount([]);
    const button = screen.getByTestId("assistant-panel-call");
    expect(button.textContent).toBe("Call");
    fireEvent.click(button);
    expect(call.toggle).toHaveBeenCalledTimes(1);
    cleanup();
    call.live = true;
    mount([]);
    expect(screen.getByTestId("assistant-panel-call").textContent).toBe("Hang up");
    expect(screen.getByTestId("assistant-panel-status").textContent).toBe("On a call");
  });

  it("opens a connected channel where it lives, and leads an unconnected one to its setup", async () => {
    mount([], { "/api/agent-chat/lead/channels": { channels: [
      { id: "slack", kind: "tool", connected: false, handle: "", url: "" },
      { id: "telegram", kind: "chat", connected: true, handle: "@nova_bot", url: "https://t.me/nova_bot" },
    ] } });
    const telegram = screen.getByTestId("assistant-panel-channel-telegram");
    await waitFor(() => expect(telegram.getAttribute("data-connected")).toBe("true"));
    expect(telegram.textContent).toBe("@nova_bot");
    expect(telegram.getAttribute("title")).toBe("Open the chat with Nova in Telegram");
    fireEvent.click(telegram);
    expect(external.open).toHaveBeenCalledWith("https://t.me/nova_bot");
    expect(useEventStore.getState().activeSection).toBe("chats");

    const slack = screen.getByTestId("assistant-panel-channel-slack");
    expect(slack.textContent).toBe("Slack");
    expect(slack.getAttribute("title")).toBe("Connect Slack");
    fireEvent.click(slack);
    expect(external.open).toHaveBeenCalledTimes(1);
    expect(takePluginFocus()).toBe("slack");
    expect(useEventStore.getState().activeSection).toBe("plugins");
  });

  it("names a connected Slack workspace and opens it", async () => {
    mount([], { "/api/agent-chat/lead/channels": { channels: [
      { id: "slack", kind: "tool", connected: true, handle: "Acme", url: "https://app.slack.com/client/T024BE7LD" },
    ] } });
    const slack = screen.getByTestId("assistant-panel-channel-slack");
    await waitFor(() => expect(slack.textContent).toBe("Acme"));
    expect(slack.getAttribute("title")).toBe("Open Acme in Slack");
    fireEvent.click(slack);
    expect(external.open).toHaveBeenCalledWith("https://app.slack.com/client/T024BE7LD");
  });

  it("leads its work with what it looks after over time", async () => {
    mount([], {
      "/api/agent-chat/lead/standing": {
        available: true,
        tasks: [
          { id: "s1", title: "Meta ads campaign", goal: "", how: "", autonomy: "prepare", limits: "", state: "active", interval_min: 180,
            origin: "owner", reason: "", notes: "", task_id: "t1", created_ms: 1, updated_ms: 2, last_run_ms: 3, next_run_ms: null,
            last_outcome: "reported", last_summary: "CPA rose to 18.40 EUR.", runs: 1 },
        ],
        limits: { min_interval_min: 15, max_interval_min: 10080, default_interval_min: 180, max_open: 12 },
        autonomy: ["watch", "prepare", "act"],
      },
    });
    const block = await screen.findByTestId("assistant-panel-standing");
    expect(block.textContent).toContain("Looks after");
    expect(screen.getByTestId("assistant-standing-task-s1").textContent).toBe("Meta ads campaignTold you: CPA rose to 18.40 EUR.");
    // It comes before the computers, the chats and the files.
    const computers = screen.getByTestId("assistant-panel-computers");
    expect(block.compareDocumentPosition(computers) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The library is about what belongs to the assistant, not about its work.
    library();
    expect(screen.queryByTestId("assistant-panel-standing")).toBeNull();
  });

  it("keeps quiet about standing tasks on a backend that does not offer them", async () => {
    mount([]);
    await screen.findByTestId("assistant-computer-this");
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/agent-chat/lead/standing", undefined));
    expect(screen.queryByTestId("assistant-panel-standing")).toBeNull();
  });

  it("lists this computer first with the green dot while the conversation runs on it, and folds the rest", async () => {
    mount([], { "/api/computers": { computers: [computer("c1", "Build box"), computer("c2", "Mac mini", "offline"),
      { ...computer("c3", "Switched off"), enabled: false }] } });
    await screen.findByTestId("assistant-computer-c1");
    const shown = () => screen.getAllByTestId(/^assistant-computer-(this|c\d)$/).map((row) => row.getAttribute("data-testid"));
    expect(shown()).toEqual(["assistant-computer-this", "assistant-computer-c1"]);
    const own = screen.getByTestId("assistant-computer-this");
    await waitFor(() => expect(own.textContent).toContain("Adas-MacBook-Pro.local"));
    expect(own.textContent).toContain("Your computer");
    expect(own.getAttribute("data-home")).toBe("true");
    expect(screen.getAllByTestId("assistant-computer-home")).toHaveLength(1);
    expect(screen.getByTestId("assistant-computer-home").getAttribute("aria-label")).toBe("Nova runs here");

    // A computer that is switched off is not offered; the third one unfolds.
    fireEvent.click(screen.getByTestId("assistant-computers-more"));
    expect(shown()).toEqual(["assistant-computer-this", "assistant-computer-c1", "assistant-computer-c2"]);
    fireEvent.click(screen.getByTestId("assistant-computer-c2"));
    expect(useEventStore.getState().activeSection).toBe("computers");
  });

  it("puts the computer the conversation runs on first", async () => {
    mount([], {
      "/api/agent-chat/lead": { session_id: "lead", computer_id: "c2" },
      "/api/computers": { computers: [computer("c1", "Build box"), computer("c2", "Mac mini")] },
    });
    await waitFor(() => expect(screen.getByTestId("assistant-computer-c2").getAttribute("data-home")).toBe("true"));
    expect(screen.getAllByTestId(/^assistant-computer-(this|c\d)$/).map((row) => row.getAttribute("data-testid")))
      .toEqual(["assistant-computer-c2", "assistant-computer-this"]);
    expect(screen.getByTestId("assistant-computer-this").getAttribute("data-home")).toBe("false");
    expect(screen.queryByTestId("assistant-computers-more")).toBeTruthy();
  });

  it("lists the IDE chats the assistant sent a task to, with their state, and opens one in the IDE", async () => {
    useIdeThreadsStore.setState({ seen: { seen: 500 } });
    mount([], { "/api/agent-chat/lead/threads": { threads: [
      thread("busy", "Fix the login", { running: true, agent: "codex", agent_label: "Codex" }),
      thread("asks", "Deploy the site", { waiting: true, running: true, agent: "kimi", agent_label: "Kimi Code" }),
      thread("news", "Write the docs", { briefed_ms: 100, updated_ms: 300, agent: "claude", agent_label: "Claude Code" }),
      thread("seen", "Rename the module", { updated_ms: 500, provider: "openai" }),
      thread("old", "", { cli_title: "Tidy the tests" }),
    ] } });
    await screen.findByTestId("assistant-activity-busy");
    // Each row leads with the logo of the coding agent that got the task; a
    // provider with no coding CLI behind it keeps the plain chat glyph.
    const row = (id: string) => screen.getByTestId(`assistant-activity-${id}`);
    expect(row("busy").querySelector("[data-testid='agent-mark-codex']")).toBeTruthy();
    expect(row("asks").querySelector("[data-testid='agent-mark-kimi']")).toBeTruthy();
    expect(row("news").querySelector("[data-testid='agent-mark-claude']")).toBeTruthy();
    expect(row("seen").querySelector("[data-testid^='agent-mark-']")).toBeNull();
    const state = (id: string) => screen.getByTestId(`assistant-activity-${id}`).getAttribute("data-state");
    expect([state("busy"), state("asks"), state("news"), state("seen")]).toEqual(["running", "waiting", "unseen", "idle"]);
    expect(screen.getByTestId("assistant-activity-asks").textContent).toContain("Needs your approval");
    // Four show; the fifth unfolds and wears the name its CLI gave it.
    expect(screen.queryByTestId("assistant-activity-old")).toBeNull();
    fireEvent.click(screen.getByTestId("assistant-activity-more"));
    expect(screen.getByTestId("assistant-activity-old").textContent).toBe("Tidy the tests");

    fireEvent.click(screen.getByTestId("assistant-activity-news"));
    expect(useEventStore.getState().activeSection).toBe("agentic-ide");
    expect(useIdeThreadsStore.getState().layout).toBe("threads");
    expect(useIdeThreadsStore.getState().selection).toMatchObject({ sessionId: "news" });
  });

  it("says so while no chat was handed a task and nothing was made yet", async () => {
    mount([]);
    await waitFor(() => expect(screen.getByTestId("assistant-activity-empty").textContent)
      .toBe("Nothing yet. Chats in the Agentic IDE that Nova hands a task to show up here."));
    await waitFor(() => expect(screen.getByTestId("assistant-outputs-empty").textContent)
      .toBe("Nothing yet. Files Nova makes show up here."));
  });

  it("lists what the newest finished runs made, newest file first, and opens one on the Artifacts page", async () => {
    const file = (path: string, mtime: number, title: string | null = null) =>
      ({ path: `tasks/t1/artifacts/files/${path}`, size: 10, mtime, is_text: false, preview: null, title });
    mount([], {
      "/api/outputs": [{ slug: "run-b", status: "success" }, { slug: "run-live", status: "running" }, { slug: "run-a", status: "success" }],
      "/api/outputs/run-a/artifacts": { files: [file("index.html", 10, "Sales dashboard"), file("clip.mp4", 40)] },
      "/api/outputs/run-b/artifacts": { files: [file("cover.png", 30), file("marketing.mjs", 20)] },
    });
    await waitFor(() => expect(screen.getAllByTestId("assistant-output")).toHaveLength(4));
    const rows = screen.getAllByTestId("assistant-output");
    expect(rows.map((row) => row.textContent)).toEqual(["clip.mp4", "cover.png", "marketing.mjs", "Sales dashboard"]);
    expect(rows.map((row) => row.getAttribute("data-kind"))).toEqual(["video", "image", "code", "page"]);
    // A run that still builds is not read.
    expect(vi.mocked(fetch)).not.toHaveBeenCalledWith("/api/outputs/run-live/artifacts");

    fireEvent.click(rows[3]);
    expect(useEventStore.getState().visualStage?.target).toBe("run-a::tasks/t1/artifacts/files/index.html");
    expect(useEventStore.getState().activeSection).toBe("visualization");
  });

  it("lists the files handed over in the conversation among the runs' files, and opens one on this computer", async () => {
    const file = (path: string, mtime: number) =>
      ({ path: `tasks/t1/artifacts/files/${path}`, size: 10, mtime, is_text: false, preview: null, title: null });
    mount([], {
      "/api/outputs": [{ slug: "run-a", status: "success" }],
      "/api/outputs/run-a/artifacts": { files: [file("cover.png", 30)] },
      "/api/agent-chat/lead/files": { files: [
        { path: "/Users/ada/work/Nvidia.xlsx", name: "Nvidia.xlsx", size: 7871, mtime: 40, linked_ms: 1 },
        { path: "/Users/ada/Desktop/notes.md", name: "notes.md", size: 12, mtime: 20, linked_ms: 2 },
      ] },
    });
    await waitFor(() => expect(screen.getAllByTestId("assistant-output")).toHaveLength(3));
    const rows = screen.getAllByTestId("assistant-output");
    expect(rows.map((row) => row.textContent)).toEqual(["Nvidia.xlsx", "cover.png", "notes.md"]);
    expect(rows.map((row) => row.getAttribute("data-source"))).toEqual(["chat", "run", "chat"]);
    expect(rows[0].getAttribute("data-kind")).toBe("document");
    expect(rows[0].getAttribute("title")).toBe("/Users/ada/work/Nvidia.xlsx");

    fireEvent.click(rows[0]);
    expect(local.open).toHaveBeenCalledWith("/Users/ada/work/Nvidia.xlsx");
    // It opens with the system's program; the page stays where it is.
    expect(useEventStore.getState().visualStage).toBeNull();
    expect(useEventStore.getState().activeSection).toBe("chats");
  });

  it("shows a conversation's file even when no run has made anything", async () => {
    mount([], { "/api/agent-chat/lead/files": { files: [
      { path: "/Users/ada/work/Nvidia.xlsx", name: "Nvidia.xlsx", size: 7871, mtime: 40, linked_ms: 1 },
    ] } });
    await waitFor(() => expect(screen.getAllByTestId("assistant-output").map((row) => row.textContent)).toEqual(["Nvidia.xlsx"]));
    expect(screen.queryByTestId("assistant-outputs-empty")).toBeNull();
  });
});
