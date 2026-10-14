import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TimelineItem, TurnBlock, TurnItem, TurnStatus } from "@/components/agentchat/reduce";
import { useIdeChatStore } from "@/store/ideChat";
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
});

afterEach(() => {
  cleanup();
});

describe("SideChatTab", () => {
  it("greets an empty chat as a plain chat, with nothing about a workspace or terminals", () => {
    seed([]);
    render(<SideChatTab />);

    const empty = screen.getByTestId("side-chat-empty").textContent ?? "";
    expect(empty).toContain("How can I help?");
    expect(empty).not.toMatch(/workspace|terminal/i);
    expect(screen.queryByTestId("side-chat-send-to-terminal")).toBeNull();
  });

  it("never points the chat at a folder", () => {
    useIdeChatStore.setState({ workspace: { id: "w1", name: "App", path: "/repo/now" } });
    const setDraft = vi.fn(async () => undefined);
    seed([], { setDraft });
    render(<SideChatTab />);
    expect(setDraft).not.toHaveBeenCalled();
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
    // An answer offers Copy and nothing that reaches into the IDE.
    expect(screen.queryByTestId("side-chat-send-to-terminal")).toBeNull();
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

  it("asks for a restart when the running backend does not know the chat yet", () => {
    seed([], { catalog: null, catalogError: "422: Input should be 'jarvis', 'agent'" });
    render(<SideChatTab />);
    expect(screen.getByTestId("side-chat-error").textContent).toContain("Restart the app once");
  });

  it("keeps the stop button while text is typed during an answer", () => {
    seed([USER, turn([], "running")]);
    render(<SideChatTab />);
    fireEvent.change(screen.getByTestId("side-chat-input"), { target: { value: "next question" } });
    expect(screen.getByTestId("side-chat-stop")).toBeTruthy();
  });
});
