import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { CallWindow } from "@/components/home/CallWindow";
import { useEventStore } from "@/store/events";
import { useHomeStore } from "@/store/home";

describe("CallWindow (a call inside the conversation)", () => {
  let muted = false;
  beforeEach(() => {
    muted = false;
    vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url) === "/api/voice/mic-mute") {
        if (init?.method === "POST") muted = !muted;
        return new Response(JSON.stringify({ muted }));
      }
      return new Response(JSON.stringify({ stopped: true }));
    }));
    useEventStore.setState({ voiceState: "idle", assistantName: "Dodaios", transcription: "", transcriptionFinal: true });
    useHomeStore.setState({ transcript: [], liveReply: "", callPending: false, callProblem: null });
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows nothing without a call", () => {
    render(<CallWindow />);
    expect(screen.queryByTestId("call-window")).toBeNull();
  });

  it("opens with the voice light, the pet and the controls as soon as a call connects", () => {
    // The complaint this guards (maintainer, 2026-11-10): calling changed
    // nothing on screen that anyone noticed.
    useEventStore.setState({ voiceState: "connecting" });
    render(<CallWindow />);
    const call = screen.getByTestId("call-window");
    expect(call.textContent).toContain("Dodaios");
    expect(within(call).getByTestId("voice-glow")).toBeTruthy();
    // Nothing said yet: the pet alone stands for the call.
    expect(within(call).getByTestId("call-waiting")).toBeTruthy();
    expect(within(call).queryByTestId("call-transcript")).toBeNull();
    for (const id of ["call-settings", "call-mute", "call-hang-up"]) expect(within(call).getByTestId(id)).toBeTruthy();
    // A call that is still connecting cannot be hung up twice.
    expect((within(call).getByTestId("call-hang-up") as HTMLButtonElement).disabled).toBe(true);
  });

  it("says what the call is doing", () => {
    useEventStore.setState({ voiceState: "listening" });
    const { rerender } = render(<CallWindow />);
    expect(screen.getByTestId("call-status").textContent).toContain("Listening");
    useEventStore.setState({ voiceState: "speaking" });
    rerender(<CallWindow />);
    expect(screen.getByTestId("call-status").textContent).toContain("Speaking");
    expect(screen.getByTestId("call-window").getAttribute("data-state")).toBe("speaking");
  });

  it("shows this call's words as they are said, without the work behind an answer", () => {
    useEventStore.setState({ voiceState: "speaking", transcription: "and tomorrow", transcriptionFinal: false });
    useHomeStore.setState({
      transcript: [
        { id: "u1", who: "user", text: "What is on today?", ts: 1 },
        { id: "s1", who: "steps", text: "", ts: 2, steps: [], live: false, durationMs: 900 },
        { id: "a1", who: "assistant", text: "One meeting at ten.", ts: 3 },
      ] as never,
      liveReply: "",
    });
    render(<CallWindow />);
    const words = screen.getByTestId("call-transcript");
    const lines = within(words).getAllByTestId("transcript-line");
    expect(lines.map((line) => line.getAttribute("data-who"))).toEqual(["user", "assistant"]);
    expect(words.textContent).toContain("What is on today?");
    expect(words.textContent).toContain("One meeting at ten.");
    // Words still being said are in the window too.
    expect(within(words).getByTestId("transcript-live").textContent).toContain("and tomorrow");
    expect(screen.queryByTestId("call-waiting")).toBeNull();
  });

  it("turns the microphone off and on through the backend", async () => {
    useEventStore.setState({ voiceState: "listening" });
    render(<CallWindow />);
    fireEvent.click(screen.getByTestId("call-mute"));
    await waitFor(() => expect(screen.getByTestId("call-mute").getAttribute("aria-pressed")).toBe("true"));
    expect(screen.getByTestId("call-status").textContent).toBe("Microphone off");
    fireEvent.click(screen.getByTestId("call-mute"));
    await waitFor(() => expect(screen.getByTestId("call-mute").getAttribute("aria-pressed")).toBe("false"));
  });

  it("opens at the click, before the host has answered", () => {
    useHomeStore.setState({ callPending: true });
    render(<CallWindow />);
    const call = screen.getByTestId("call-window");
    expect(call.getAttribute("data-state")).toBe("connecting");
    expect(screen.getByTestId("call-status").textContent).toBe("Connecting…");
    // Nothing to mute or hang up yet.
    expect((screen.getByTestId("call-mute") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId("call-hang-up") as HTMLButtonElement).disabled).toBe(true);
  });

  it("stays and says why when a call ends on its own, until it is closed", () => {
    // The complaint this guards (maintainer, 2026-11-10): the provider refused
    // the call after twelve seconds and the screen showed nothing at all.
    useEventStore.setState({ voiceState: "error" });
    useHomeStore.setState({ callProblem: { message: "The selected account is not offered subscription voice." } });
    const { rerender } = render(<CallWindow />);
    const call = screen.getByTestId("call-window");
    expect(call.getAttribute("data-state")).toBe("failed");
    expect(within(call).getByRole("alert").textContent).toContain("This call did not work");
    expect(screen.getByTestId("call-problem").textContent).toBe("The selected account is not offered subscription voice.");
    expect(screen.queryByTestId("call-hang-up")).toBeNull();
    // The way to fix it is one press away.
    fireEvent.click(screen.getByTestId("call-settings"));
    expect(useEventStore.getState().activeSection).toBe("voice-api-keys");
    // It does not go away with the state falling back to idle.
    useEventStore.setState({ voiceState: "idle" });
    rerender(<CallWindow />);
    expect(screen.getByTestId("call-window")).toBeTruthy();
    fireEvent.click(screen.getByTestId("call-close"));
    expect(useHomeStore.getState().callProblem).toBeNull();
    rerender(<CallWindow />);
    expect(screen.queryByTestId("call-window")).toBeNull();
  });

  it("says so when a call failed and nobody named the reason", () => {
    useHomeStore.setState({ callProblem: { message: "" } });
    render(<CallWindow />);
    expect(screen.getByTestId("call-problem").textContent).toContain("No reason was reported");
  });

  it("shows the running call, not an old problem, once a new call is up", () => {
    useEventStore.setState({ voiceState: "listening" });
    useHomeStore.setState({ callProblem: { message: "old" } });
    render(<CallWindow />);
    expect(screen.getByTestId("call-window").getAttribute("data-state")).toBe("listening");
    expect(screen.queryByTestId("call-problem")).toBeNull();
  });

  it("hangs up with the red button", async () => {
    useEventStore.setState({ voiceState: "listening" });
    render(<CallWindow />);
    fireEvent.click(screen.getByTestId("call-hang-up"));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("/api/voice/hangup"))).toBe(true));
  });
});
