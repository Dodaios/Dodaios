import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { CallCard } from "@/components/home/CallCard";
import { useEventStore } from "@/store/events";
import { useHomeStore } from "@/store/home";

describe("CallCard (a call inside the conversation)", () => {
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
    useHomeStore.setState({ transcript: [], liveReply: "" });
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows nothing without a call", () => {
    render(<CallCard />);
    expect(screen.queryByTestId("call-card")).toBeNull();
  });

  it("shows the call with its controls while it runs", () => {
    useEventStore.setState({ voiceState: "listening" });
    render(<CallCard />);
    expect(screen.getByTestId("call-card").textContent).toContain("Dodaios");
    for (const id of ["call-settings", "call-transcript-toggle", "call-mute", "call-hang-up"]) {
      expect(screen.getByTestId(id)).toBeTruthy();
    }
  });

  it("turns the microphone off and on through the backend", async () => {
    useEventStore.setState({ voiceState: "listening" });
    render(<CallCard />);
    fireEvent.click(screen.getByTestId("call-mute"));
    await waitFor(() => expect(screen.getByTestId("call-mute").getAttribute("aria-pressed")).toBe("true"));
    fireEvent.click(screen.getByTestId("call-mute"));
    await waitFor(() => expect(screen.getByTestId("call-mute").getAttribute("aria-pressed")).toBe("false"));
  });

  it("shows this call's words when the transcript is on", () => {
    useEventStore.setState({ voiceState: "speaking" });
    useHomeStore.setState({ transcript: [{ id: "u1", who: "user", text: "What is on today?", ts: 1 }] });
    render(<CallCard />);
    expect(screen.queryByTestId("call-transcript")).toBeNull();
    act(() => { fireEvent.click(screen.getByTestId("call-transcript-toggle")); });
    expect(screen.getByTestId("call-transcript").textContent).toContain("What is on today?");
  });

  it("hangs up with the red button", async () => {
    useEventStore.setState({ voiceState: "listening" });
    render(<CallCard />);
    fireEvent.click(screen.getByTestId("call-hang-up"));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("/api/voice/hangup"))).toBe(true));
  });
});
