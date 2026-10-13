import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TimelineItem, TurnBlock, TurnItem, TurnStatus } from "@/components/agentchat/reduce";
import type { WorkspacePaneRow } from "@/lib/agenticIdeApi";
import { useIdeChatStore } from "@/store/ideChat";
import { useIdeSkillsStore } from "@/store/ideSkills";
import { useWorkspacePanesStore } from "@/store/workspacePanes";
import { SideChatTab } from "./SideChatTab";
import { useSideChatStore } from "./sideChatStore";

function turn(blocks: TurnBlock[], status: TurnStatus = "done"): TurnItem {
  return {
    type: "turn", id: "t1", provider: "fake", model: "", effort: "", runner: "api", status, blocks,
    startedMs: Date.now(), durationMs: status === "running" ? null : 9000, usage: null, liveUsage: null, costUsd: null, error: null,
  };
}

const USER: TimelineItem = { type: "user", id: "u1", text: "improve my prompt", tsMs: Date.now(), attachments: [] } as unknown as TimelineItem;
const THOUGHT: TurnBlock = { kind: "reasoning", id: "r1", text: "The person wants a goal, not steps.", durationMs: 3000, live: false, startedMs: Date.now() };
const ANSWER: TurnBlock = { kind: "text", id: "a1", text: "Make the login form accessible." };

function pane(over: Partial<WorkspacePaneRow>): WorkspacePaneRow {
  return {
    workspace_id: "w1", workspace_name: "App", folder: "/repo", workspace_active: true,
    key: "t1", history_id: "h1", name: "T1", agent: "claude", display_name: "Claude Code",
    accepts_prompts: true, status: "live", exit_code: null, activity: "idle", activity_since: 0,
    worked: false, started_at: null, last_output_at: null, last_prompt: "", last_prompt_at: null,
    recap: "", has_resume: false, readable: false, account: null, account_label: null, archived: false,
    ...over,
  } as WorkspacePaneRow;
}

const PROVIDER = {
  id: "fake", label: "Fake", family: "fake", runner: "api", models_source: "curated", curated_models: [{ id: "m1", label: "Model One" }],
  default_model: "m1", keyless: true, effort_levels: [], default_effort: "", permission_modes: [], default_permission_mode: "", cli_installed: null,
};

/** The store as it is once the catalog has loaded, with `items` on screen. */
function seed(items: TimelineItem[], extra: Record<string, unknown> = {}) {
  const send = vi.fn(async () => "sent" as const);
  const cancel = vi.fn(async () => undefined);
  useSideChatStore.setState({
    catalog: { providers: [PROVIDER], default_cwd: "", shell: "", selection: null },
    catalogStale: false,
    connections: [],
    draft: { provider: "fake", model: "m1", effort: "", permissionMode: "", buildMode: "", cwd: "" },
    timeline: { items, pendingApprovals: [], lastSeq: 0, sessionPatch: null },
    sessions: [],
    activeSessionId: items.length ? "s1" : null,
    busy: false,
    lastError: null,
    catalogError: null,
    send,
    cancel,
    loadCatalog: vi.fn(async () => undefined),
    loadSessions: vi.fn(async () => undefined),
    setDraft: vi.fn(async () => undefined),
    ...extra,
  } as never);
  return { send, cancel };
}

beforeEach(() => {
  localStorage.clear();
  useIdeChatStore.setState({ workspace: null });
  useIdeSkillsStore.setState({ target: null });
  useWorkspacePanesStore.setState({ panes: [pane({}), pane({ key: "t2", history_id: "h2", name: "T2" })] });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SideChatTab", () => {
  it("says what the chat is and opens a message from a starter", () => {
    seed([]);
    render(<SideChatTab />);

    expect(screen.getByTestId("side-chat-empty").textContent).toContain("cannot change anything");
    fireEvent.click(screen.getByTestId("side-chat-starter-prompt"));

    expect((screen.getByTestId("side-chat-input") as HTMLTextAreaElement).value).toContain("Improve this prompt");
  });

  it("sends on Enter, keeps Shift+Enter for a new line, and clears the box", async () => {
    const { send } = seed([]);
    render(<SideChatTab />);
    const input = screen.getByTestId("side-chat-input") as HTMLTextAreaElement;

    fireEvent.change(input, { target: { value: "hello" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(send).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(send).toHaveBeenCalledWith("hello"));
    expect(input.value).toBe("");
  });

  it("puts a message that never left back into the box", async () => {
    seed([], { send: vi.fn(async () => "failed" as const) });
    render(<SideChatTab />);
    const input = screen.getByTestId("side-chat-input") as HTMLTextAreaElement;

    fireEvent.change(input, { target: { value: "hello" } });
    fireEvent.click(screen.getByTestId("side-chat-send"));

    await waitFor(() => expect(input.value).toBe("hello"));
  });

  it("folds a finished answer's thinking behind the time it took", () => {
    seed([USER, turn([THOUGHT, ANSWER])]);
    render(<SideChatTab />);

    expect(screen.getByText("Make the login form accessible.")).toBeTruthy();
    const fold = screen.getByTestId("thread-worked-for");
    expect(fold.textContent).toContain("Thought for 3.0s");
    // The thought itself is one click away, not in the way.
    expect(screen.queryByText("The person wants a goal, not steps.")).toBeNull();
    fireEvent.click(fold);
    expect(screen.getByText("The person wants a goal, not steps.")).toBeTruthy();
  });

  it("shows a stop button while the model answers", () => {
    const { cancel } = seed([USER, turn([], "running")]);
    render(<SideChatTab />);

    expect(screen.getByTestId("thread-working").textContent).toContain("Thinking for");
    fireEvent.click(screen.getByTestId("side-chat-stop"));
    expect(cancel).toHaveBeenCalled();
  });

  it("sends an answer, as written, to the terminal that was picked", async () => {
    const calls: { url: string; body: Record<string, unknown> }[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      calls.push({ url, body });
      const answer = url.includes("/terminals/")
        ? { terminal: "T2", sent: body.prompt, composed_by: "raw", files: [], submitted: true }
        : { panes: useWorkspacePanesStore.getState().panes, active_id: "w1" };
      return new Response(JSON.stringify(answer), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    seed([USER, turn([ANSWER])]);
    render(<SideChatTab />);

    fireEvent.click(screen.getByTestId("side-chat-send-to-terminal"));
    fireEvent.click(await screen.findByRole("menuitem", { name: /T2/ }));

    await waitFor(() => expect(calls.some((call) => call.url.includes("/terminals/"))).toBe(true));
    const sent = calls.find((call) => call.url.includes("/terminals/"))!;
    expect(sent.url).toContain("/terminals/t2/prompt?workspace=w1");
    // Never composed a second time: the terminal gets the answer the person read.
    expect(sent.body).toMatchObject({ prompt: "Make the login form accessible.", compose: false });
  });
});
