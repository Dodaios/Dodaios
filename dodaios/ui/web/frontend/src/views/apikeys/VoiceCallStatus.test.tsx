/**
 * The call status at the top of the Live calls tab: quiet while no call runs,
 * "connecting" first, then the provider a running call really uses, and the
 * reason a call did not start.
 *
 * No jest-dom in this repo — assertions use plain values.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { VoiceCallStatus } from "@/views/apikeys/VoiceCallStatus";

/** What `useVoiceMode` reports; a test sets it before rendering. */
const voice = vi.hoisted(() => ({ state: {} as Record<string, unknown> }));
vi.mock("@/hooks/useVoiceMode", () => ({ useVoiceMode: () => voice.state }));

afterEach(() => cleanup());

describe("VoiceCallStatus", () => {
  beforeEach(() => {
    voice.state = { sessionActive: false };
  });

  it("draws nothing while no call runs and nothing went wrong", () => {
    render(<VoiceCallStatus />);
    expect(screen.queryByTestId("voice-call-status")).toBeNull();
  });

  it("says that the session is connecting before anything else", () => {
    voice.state = { connecting: true, sessionActive: true };
    render(<VoiceCallStatus />);
    expect(screen.getByTestId("voice-call-runtime").textContent).toContain("Connecting the Realtime session");
  });

  it("names the provider and model a running call really uses", () => {
    voice.state = { sessionActive: true, activeSessionProvider: "grok-realtime", activeSessionModel: "grok-voice" };
    render(<VoiceCallStatus />);
    expect(screen.getByTestId("voice-call-runtime").textContent).toBe(
      "Current session: Realtime · grok-realtime · grok-voice",
    );
  });

  it("shows why the last call did not start, and the transport's own reason", () => {
    voice.state = {
      sessionActive: false,
      lastStartError: { provider: "openai", message: "401 unauthorized" },
      requiresWebRtcOffer: true, transportOfferReady: false, transportOfferDetail: "app-server is not signed in",
    };
    render(<VoiceCallStatus />);
    expect(screen.getByTestId("realtime-last-start-error").textContent).toBe("Voice connect failed (openai): 401 unauthorized");
    expect(screen.getByTestId("realtime-transport-offer-detail").textContent).toBe("app-server is not signed in");
  });
});
