import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TimelineItem, TurnBlock, TurnItem, TurnStatus } from "@/components/agentchat/reduce";
import { forgetHeldFiles } from "@/components/agentchat/useChatAttachments";
import { useEventStore } from "@/store/events";
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
  useEventStore.setState({ dictating: false });
  useIdeChatStore.setState({ workspace: null });
});

afterEach(() => {
  cleanup();
  // Held files outlive the tab; one test's file must not leak into the next.
  forgetHeldFiles(useSideChatStore);
  vi.unstubAllGlobals();
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

    await waitFor(() => expect(send).toHaveBeenCalledWith("hello", []));
    expect(input.value).toBe("");
  });

  it("stops an answer that is still coming on Escape", () => {
    const { cancel } = seed([USER, turn([], "running")]);
    render(<SideChatTab />);
    fireEvent.keyDown(screen.getByTestId("side-chat-input"), { key: "Escape" });
    expect(cancel).toHaveBeenCalledWith("side-chat-escape");
  });

  it("puts the cursor in the box when the chat opens", () => {
    seed([]);
    render(<SideChatTab />);
    expect(document.activeElement).toBe(screen.getByTestId("side-chat-input"));
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
    const fold = screen.getByTestId("chat-thought-toggle");
    expect(fold.textContent).toContain("Thought for 3.0s");
    // The thought itself is one click away, not in the way.
    expect(screen.queryByText("The person wants a goal, not steps.")).toBeNull();
    fireEvent.click(fold);
    expect(screen.getByText("The person wants a goal, not steps.")).toBeTruthy();
  });

  it("shows a stop button while the model answers", () => {
    const { cancel } = seed([USER, turn([], "running")]);
    render(<SideChatTab />);

    expect(screen.getByRole("status").textContent).toContain("Thinking");
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

  it("offers the dictation mic beside Send", () => {
    seed([]);
    render(<SideChatTab />);
    expect(screen.getByRole("button", { name: "Dictate" })).toBeTruthy();
  });

  it("puts dictated words into the box, after what was typed", () => {
    seed([]);
    render(<SideChatTab />);
    const input = screen.getByTestId("side-chat-input") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "Question:" } });

    act(() => {
      const seq = useEventStore.getState().dictationCommitSeq + 1;
      useEventStore.setState({ dictationCommitText: "why is the sky blue", dictationCommitSeq: seq });
    });

    expect(input.value).toBe("Question: why is the sky blue");
  });

  it("can send while dictating, before anything is in the box", () => {
    seed([]);
    useEventStore.setState({ dictating: true });
    render(<SideChatTab />);
    expect((screen.getByTestId("side-chat-send") as HTMLButtonElement).disabled).toBe(false);
  });
});

const SHOT = {
  name: "shot.png", reference: '".jarvis/drops/shot.png"', kind: "image" as const,
  detail: "A login form with a red error.", described_by: "vision" as const, note: "",
};

/** A DataTransfer stand-in: jsdom's own carries neither files nor types. */
function transfer(files: File[]) {
  return {
    files,
    items: files.map((file) => ({ kind: "file", type: file.type, getAsFile: () => file })),
    types: files.length ? ["Files"] : [],
    getData: () => "",
    dropEffect: "none",
  };
}

describe("SideChatTab attachments", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async () => ({
      ok: true, status: 200, json: async () => ({ attachments: [SHOT], cwd: "C:\chat" }),
    }) as Response);
    vi.stubGlobal("fetch", fetchMock);
  });

  it("takes a file dropped anywhere on the tab, on the side surface", async () => {
    seed([]);
    render(<SideChatTab />);
    const tab = screen.getByTestId("side-chat-tab");
    const png = new File([new Uint8Array([1])], "shot.png", { type: "image/png" });

    fireEvent.dragEnter(tab, { dataTransfer: transfer([png]) });
    expect(screen.getByTestId("side-chat-drop-overlay")).toBeTruthy();
    await act(async () => {
      fireEvent.drop(tab, { dataTransfer: transfer([png]) });
    });

    await waitFor(() => expect(screen.getByTestId("chat-attachment-shot.png")).toBeTruthy());
    expect(screen.queryByTestId("side-chat-drop-overlay")).toBeNull();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/agent-chat/attachments");
    expect((init.body as FormData).get("surface")).toBe("side");
  });

  it("takes a pasted image and leaves pasted text to the box", async () => {
    seed([]);
    render(<SideChatTab />);
    const input = screen.getByTestId("side-chat-input");

    const textPaste = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(textPaste, "clipboardData", { value: transfer([]) });
    await act(async () => { input.dispatchEvent(textPaste); });
    expect(textPaste.defaultPrevented).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();

    const png = new File([new Uint8Array([1])], "image.png", { type: "image/png" });
    await act(async () => { fireEvent.paste(input, { clipboardData: transfer([png]) }); });
    await waitFor(() => expect(screen.getByTestId("chat-attachment-shot.png")).toBeTruthy());
  });

  it("attaches files picked with the paperclip", async () => {
    seed([]);
    render(<SideChatTab />);
    expect(screen.getByTestId("side-chat-attach")).toBeTruthy();
    const pdf = new File([new Uint8Array([1])], "notes.pdf", { type: "application/pdf" });
    await act(async () => {
      fireEvent.change(screen.getByTestId("side-chat-file-input"), { target: { files: [pdf] } });
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  });

  it("sends a file alone, with what was read from it, and then holds none", async () => {
    const { send } = seed([]);
    render(<SideChatTab />);
    const png = new File([new Uint8Array([1])], "shot.png", { type: "image/png" });
    await act(async () => {
      fireEvent.drop(screen.getByTestId("side-chat-tab"), { dataTransfer: transfer([png]) });
    });
    await waitFor(() => expect(screen.getByTestId("chat-attachment-shot.png")).toBeTruthy());

    expect((screen.getByTestId("side-chat-send") as HTMLButtonElement).disabled).toBe(false);
    fireEvent.keyDown(screen.getByTestId("side-chat-input"), { key: "Enter" });

    await waitFor(() => expect(send).toHaveBeenCalledWith("", [SHOT]));
    await waitFor(() => expect(screen.queryByTestId("chat-attachment-shot.png")).toBeNull());
  });

  it("puts the files of a message that never left back", async () => {
    seed([], { send: vi.fn(async () => "failed" as const) });
    render(<SideChatTab />);
    const png = new File([new Uint8Array([1])], "shot.png", { type: "image/png" });
    await act(async () => {
      fireEvent.drop(screen.getByTestId("side-chat-tab"), { dataTransfer: transfer([png]) });
    });
    await waitFor(() => expect(screen.getByTestId("chat-attachment-shot.png")).toBeTruthy());
    const input = screen.getByTestId("side-chat-input") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "what is wrong" } });
    fireEvent.click(screen.getByTestId("side-chat-send"));

    await waitFor(() => expect(input.value).toBe("what is wrong"));
    expect(screen.getByTestId("chat-attachment-shot.png")).toBeTruthy();
  });
});
