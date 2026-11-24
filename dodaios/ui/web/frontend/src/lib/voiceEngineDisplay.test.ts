import { describe, expect, it } from "vitest";

import { resolveVoiceEngineDisplay, type VoiceEngineDisplayInput } from "@/lib/voiceEngineDisplay";

const IDLE: VoiceEngineDisplayInput = {
  activeProvider: "vertex-live",
  activeProviderLabel: "Vertex AI Live",
  activeModel: "gemini-live-2.5-flash-preview-native-audio-dialog",
  sessionActive: false,
  activeSessionProvider: "",
  activeSessionModel: "",
};

describe("resolveVoiceEngineDisplay", () => {
  it("names the configured realtime pick while no call runs", () => {
    const got = resolveVoiceEngineDisplay(IDLE);
    expect(got.providerId).toBe("vertex-live");
    expect(got.providerLabel).toBe("Vertex AI Live");
    expect(got.model).toBe("gemini-live-2.5-flash-preview-native-audio-dialog");
  });

  it("a running session's live provider/model outrank the configured pick", () => {
    const got = resolveVoiceEngineDisplay({
      ...IDLE,
      sessionActive: true,
      activeSessionProvider: "openai-realtime",
      activeSessionModel: "gpt-realtime-2.1",
    });
    expect(got.providerLabel).toBe("OpenAI Realtime");
    expect(got.model).toBe("gpt-realtime-2.1");
  });

  it("falls back to a pretty id when the backend label has not landed", () => {
    const got = resolveVoiceEngineDisplay({
      ...IDLE,
      activeProvider: "vertex-live",
      activeProviderLabel: null,
      activeModel: null,
    });
    expect(got.providerLabel).toBe("Vertex AI Live");
    expect(got.model).toBe("");
  });

  it("names Grok Live by its id before the backend label lands", () => {
    const got = resolveVoiceEngineDisplay({
      ...IDLE,
      activeProvider: "grok-realtime",
      activeProviderLabel: null,
      activeModel: null,
    });
    expect(got.providerLabel).toBe("Grok Live");
  });

  it("renders an em dash when no provider is resolved yet", () => {
    const got = resolveVoiceEngineDisplay({
      ...IDLE,
      activeProvider: null,
      activeProviderLabel: null,
      activeModel: null,
    });
    expect(got.providerLabel).toBe("—");
  });

  it("names Gemini Live and the self-hosted transport the same way", () => {
    expect(
      resolveVoiceEngineDisplay({
        ...IDLE,
        activeProvider: "gemini-live",
        activeProviderLabel: "Gemini Live",
        activeModel: "gemini-3.1-flash-live-preview",
      }).providerLabel,
    ).toBe("Gemini Live");
    expect(
      resolveVoiceEngineDisplay({
        ...IDLE,
        activeProvider: "local-realtime",
        activeProviderLabel: "Self-hosted realtime (OpenAI-compatible)",
        activeModel: "auto",
      }).providerLabel,
    ).toBe("Self-hosted realtime (OpenAI-compatible)");
  });

  it("keeps the registry label when a live session is still on the configured pick", () => {
    const got = resolveVoiceEngineDisplay({
      ...IDLE,
      activeProvider: "local-realtime",
      activeProviderLabel: "Self-hosted realtime (OpenAI-compatible)",
      activeModel: "auto",
      sessionActive: true,
      activeSessionProvider: "local-realtime",
      activeSessionModel: "auto",
    });
    expect(got.providerLabel).toBe("Self-hosted realtime (OpenAI-compatible)");
  });
});
