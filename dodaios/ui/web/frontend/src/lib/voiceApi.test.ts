import { afterEach, describe, expect, it, vi } from "vitest";

import {
  WARM_MIN_INTERVAL_MS,
  fetchCallVoices,
  fetchVoiceRuntimeState,
  requestVoiceCall,
  resetVoiceWarm,
  setCallVoice,
  warmVoiceCall,
} from "./voiceApi";

function answer(body: unknown, status = 200) {
  return vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  })) as unknown as typeof fetch;
}

describe("voiceApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    resetVoiceWarm();
  });

  it("warms the next call once per window, silently", () => {
    const fetchMock = answer({ warming: true });
    vi.stubGlobal("fetch", fetchMock);
    expect(warmVoiceCall(1_000)).toBe(true);
    expect(warmVoiceCall(1_000 + WARM_MIN_INTERVAL_MS - 1)).toBe(false);
    expect(warmVoiceCall(1_000 + WARM_MIN_INTERVAL_MS)).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe("/api/voice/warm");
  });

  it("reads and picks the call's voice through one endpoint", async () => {
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PUT") {
        expect(JSON.parse(String(init.body))).toEqual({ voice: "Puck" });
        return new Response(JSON.stringify({ ok: true, applies: "now" }));
      }
      return new Response(JSON.stringify({
        path: "tts", provider: "gemini-flash-tts", voices: [{ id: "Kore", label: "Kore" }],
        current: "Kore", default: "Kore", applies: "now",
      }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const voices = await fetchCallVoices();
    expect(voices.voices.map((v) => v.id)).toEqual(["Kore"]);
    expect(await setCallVoice("Puck")).toEqual({ ok: true, applies: "now" });
    expect(String(fetchMock.mock.calls[1][0])).toBe("/api/voice/voices");
  });

  it("names the failure when a voice cannot be picked", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "unknown-voice" }), { status: 422 })));
    await expect(setCallVoice("x")).rejects.toThrow("unknown-voice");
  });

  it("reads whether this browser should hold the call", async () => {
    vi.stubGlobal(
      "fetch",
      answer({ available: false, state: "unavailable", voice_state: "idle", browser_call: true }),
    );

    expect(await fetchVoiceRuntimeState()).toEqual({
      available: false,
      voiceState: "idle",
      browserCall: true,
    });
  });

  it("never offers a browser call when an older backend does not say so", async () => {
    vi.stubGlobal("fetch", answer({ available: true, state: "idle" }));

    expect(await fetchVoiceRuntimeState()).toEqual({
      available: true,
      voiceState: "idle",
      browserCall: false,
    });
  });

  it("tells a host without a speech pipeline apart by its status", async () => {
    vi.stubGlobal("fetch", answer({ detail: "voice-pipeline-unavailable" }, 503));

    const failure = await requestVoiceCall().catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(Error);
    expect((failure as Error).message).toBe("Voice is not running on this computer.");
    expect((failure as { status?: number }).status).toBe(503);
  });
});
