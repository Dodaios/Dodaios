import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { AppSurfaceSwitch } from "@/components/layout/AppSurfaceSwitch";
import { useEventStore } from "@/store/events";
import { useHomeStore } from "@/store/home";

// useVoiceMode fetches /api/settings/voice-mode; a plain pipeline install here.
vi.mock("@/hooks/useVoiceMode", () => ({
  useVoiceMode: () => ({ mode: "pipeline", connecting: false }),
}));

// The two places of the app, in the window caption: the conversation with the
// assistant and the Agentic IDE.
describe("AppSurfaceSwitch", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        String(url).startsWith("/api/chats")
          ? new Response(JSON.stringify([]), { status: 200 })
          : new Response(JSON.stringify({ sessions: [] }), { status: 200 }),
      ),
    );
    useEventStore.setState({
      connected: true,
      voiceReady: true,
      voiceState: "idle",
      activeSection: "board",
      conversations: [],
      messages: [],
      activeThreadId: "old-voice-thread",
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    useEventStore.setState({ conversations: [], messages: [], activeThreadId: null, activeSection: "chats" });
  });

  const half = (id: "dodaios" | "ide") => screen.getByTestId(`surface-${id}`);

  test("names both places, Dodaios first", () => {
    render(<AppSurfaceSwitch />);
    const radios = screen.getAllByRole("radio");
    expect(radios.map((r) => r.getAttribute("data-testid"))).toEqual(["surface-dodaios", "surface-ide"]);
    expect(half("dodaios").textContent).toContain("Dodaios");
    expect(half("ide").textContent).toContain("IDE");
    for (const radio of radios) expect(radio.getAttribute("title")).toBe(radio.getAttribute("aria-label"));
  });

  test("lights neither half while another page is on screen", () => {
    render(<AppSurfaceSwitch />);
    expect(half("dodaios").getAttribute("aria-checked")).toBe("false");
    expect(half("ide").getAttribute("aria-checked")).toBe("false");
    expect(screen.queryByTestId("surface-switch-thumb")).toBeNull();
  });

  test("lights the place on screen", () => {
    useEventStore.setState({ activeSection: "agentic-ide" });
    render(<AppSurfaceSwitch />);
    expect(half("ide").getAttribute("aria-checked")).toBe("true");
    act(() => useEventStore.setState({ activeSection: "chats" }));
    expect(half("dodaios").getAttribute("aria-checked")).toBe("true");
  });

  test("opens the one conversation in one click, even from voice mode", async () => {
    useHomeStore.setState({ surface: "voice", transcript: [] });
    render(<AppSurfaceSwitch />);
    await act(async () => { half("dodaios").click(); await Promise.resolve(); });
    expect(useHomeStore.getState().surface).toBe("chat");
    expect(useEventStore.getState().activeSection).toBe("chats");
  });

  test("never starts a voice run — voice is a mode inside the chat now", async () => {
    useHomeStore.setState({ surface: "chat", transcript: [] });
    render(<AppSurfaceSwitch />);
    await act(async () => { half("dodaios").click(); await Promise.resolve(); });
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    expect(calls.some((c) => String(c[0]) === "/api/chats/voice/new")).toBe(false);
  });

  test("the other half opens the Agentic IDE", () => {
    render(<AppSurfaceSwitch />);
    act(() => { half("ide").click(); });
    expect(useEventStore.getState().activeSection).toBe("agentic-ide");
  });

  test("the assistant's half carries the pet mark and the voice dot", () => {
    render(<AppSurfaceSwitch />);
    const pet = screen.getByTestId("surface-pet");
    expect(half("dodaios").contains(pet)).toBe(true);
    expect(pet.querySelector('[data-testid="pet-mark"]')).toBeTruthy();
    expect(pet.querySelector("img")).toBeNull();
    expect(screen.getByRole("img", { name: "Ready" })).toBeTruthy();
    expect(screen.queryByTestId("voice-starting-spinner")).toBeNull();
  });

  test("spins while voice is still warming up", () => {
    useEventStore.setState({ connected: true, voiceReady: false });
    render(<AppSurfaceSwitch />);
    expect(screen.getByTestId("voice-starting-spinner")).toBeTruthy();
    expect(screen.queryByTestId("surface-voice-dot")).toBeNull();
  });
});
