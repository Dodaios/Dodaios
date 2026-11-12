import { describe, expect, it } from "vitest";

import { providerName } from "@/views/voice/keys/names";

describe("providerName", () => {
  it.each([
    ["OpenAI Whisper STT", "OpenAI Whisper"],
    ["OpenRouter (STT)", "OpenRouter"],
    ["Gemini STT", "Gemini"],
    ["Vertex AI STT", "Vertex AI"],
    ["Groq STT (Whisper)", "Groq"],
    ["Whisper (on this machine)", "Whisper"],
    ["Groq: dictation polish", "Groq"],
    ["Google Gemini: dictation polish", "Google Gemini"],
    ["Ollama (local): dictation polish", "Ollama"],
  ])("reads %s as %s", (label, name) => {
    expect(providerName(label)).toBe(name);
  });

  it("leaves a plain name as it is", () => {
    expect(providerName("Deepgram")).toBe("Deepgram");
  });

  it("keeps the label when nothing but the tier word would be left", () => {
    expect(providerName("STT")).toBe("STT");
  });
});
