import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { ChatsSurface } from "@/views/ChatsSurface";
import { useHomeStore } from "@/store/home";
import { readHomeSurface } from "@/lib/homeSurface";
import { useEventStore } from "@/store/events";
import { useAgentChatStore } from "@/store/agentChat";

/**
 * The front page is ONE conversation, and a call happens inside it: the chat
 * stays on screen while the call runs. What is under test is the shell; the
 * composer's voice button and the call window are ChatStage's own tests.
 */
vi.mock("@/components/home/ChatStage", () => ({
  ChatStage: () => <div data-testid="chat">chat</div>,
}));
vi.mock("@/components/home/HomeAgentChat", () => ({
  default: ({ agentId }: { agentId: string }) => <div data-testid="agent-chat">{agentId}</div>,
}));

const STORAGE_KEY = "jarvis.home.surface.v2";

describe("ChatsSurface (the front page)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useHomeStore.setState({ surface: readHomeSurface(), agentChatId: null, freshVoicePending: false, continuedVoiceId: null, voiceSwitchStopping: false });
    useEventStore.setState({ activeSection: "chats", voiceState: "idle", activeKind: "voice", activeThreadId: null });
  });

  afterEach(cleanup);

  it("gives the page to an agent's chat picked in the sidebar, and back on a new chat", async () => {
    useHomeStore.getState().openAgentChat("agent-7");
    render(<ChatsSurface />);
    expect((await screen.findByTestId("agent-chat")).textContent).toBe("agent-7");
    expect(screen.queryByTestId("chat")).toBeNull();
    const { startNewTextChat } = await import("@/lib/newChat");
    act(() => startNewTextChat());
    expect(await screen.findByTestId("chat")).toBeTruthy();
    expect(useHomeStore.getState().agentChatId).toBeNull();
  });

  it("opens on the chat by default, with nothing above it", async () => {
    render(<ChatsSurface />);
    expect(await screen.findByTestId("chat")).toBeTruthy();
  });

  it("keeps the conversation on screen when a wake-word call starts", async () => {
    render(<ChatsSurface />);
    expect(await screen.findByTestId("chat")).toBeTruthy();
    act(() => {
      useHomeStore.getState().ingest("VoiceSessionStarted", { session_id: "wake-call", wake_keyword: "jarvis" }, 1);
      useEventStore.setState({ voiceState: "listening" });
    });
    expect(screen.getByTestId("chat")).toBeTruthy();
    expect(useHomeStore.getState().surface).toBe("chat");
    act(() => useEventStore.setState({ voiceState: "idle" }));
    expect(screen.getByTestId("chat")).toBeTruthy();
  });

  it("keeps an agent's chat open when Jarvis starts speaking", async () => {
    useHomeStore.getState().openAgentChat("agent-7");
    render(<ChatsSurface />);
    expect(await screen.findByTestId("agent-chat")).toBeTruthy();
    act(() => useHomeStore.getState().ingest("VoiceSessionStarted", { session_id: "call" }, 1));
    expect(screen.getByTestId("agent-chat").textContent).toBe("agent-7");
    expect(useHomeStore.getState().surface).toBe("chat");
  });

  it("stays in the one conversation after hangup", async () => {
    const fetcher = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify({ providers: [], sessions: [], session_id: "lead" })));
    vi.stubGlobal("fetch", fetcher);
    try {
      useAgentChatStore.setState({ activeSessionId: "lead" });
      render(<ChatsSurface />);
      await act(async () => {
        useHomeStore.getState().ingest("VoiceSessionStarted", { session_id: "call" }, 1);
        useHomeStore.getState().ingest("VoiceSessionEnded", { session_id: "call", hangup_reason: "hotkey" }, 2);
      });
      expect(screen.getByTestId("chat")).toBeTruthy();
      expect(useHomeStore.getState().transcript).toEqual([]);
      expect(useAgentChatStore.getState().activeSessionId).toBe("lead");
    } finally {
      vi.unstubAllGlobals();
      useAgentChatStore.setState({ activeSessionId: null });
    }
  });

  it("ignores the retired Voice | Chat switch's stored choice", async () => {
    window.localStorage.setItem("jarvis.home.surface.v1", "voice");
    useHomeStore.setState({ surface: readHomeSurface() });
    render(<ChatsSurface />);
    expect(await screen.findByTestId("chat")).toBeTruthy();
  });

  it("opens the chat even when an older build stored the voice surface", async () => {
    window.localStorage.setItem(STORAGE_KEY, "voice");
    useHomeStore.setState({ surface: readHomeSurface() });
    render(<ChatsSurface />);
    expect(await screen.findByTestId("chat")).toBeTruthy();
  });

  it("lands on the chat when the stored value is corrupt", async () => {
    window.localStorage.setItem(STORAGE_KEY, "garbage");
    useHomeStore.setState({ surface: readHomeSurface() });
    render(<ChatsSurface />);
    expect(await screen.findByTestId("chat")).toBeTruthy();
  });
});
