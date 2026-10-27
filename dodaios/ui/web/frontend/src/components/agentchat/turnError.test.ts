import { describe, expect, it } from "vitest";
import de from "@/i18n/locales/de.json";
import en from "@/i18n/locales/en.json";
import es from "@/i18n/locales/es.json";
import pt from "@/i18n/locales/pt.json";
import zh from "@/i18n/locales/zh.json";
import { resetTimeLabel, turnErrorText } from "./turnError";

const CODES = [
  "mandated_tool_unfulfilled",
  "unbacked_action_claim",
  "guarded_response",
  "delegation_continuation_limit",
];

describe("turnErrorText", () => {
  it("translates a known backend code and passes any other text through", () => {
    const t = (key: string) => `T:${key}`;
    expect(turnErrorText("guarded_response", t)).toBe("T:thread_turn.errors.guarded_response");
    expect(turnErrorText("Provider timed out", t)).toBe("Provider timed out");
    expect(turnErrorText(null, t)).toBeNull();
    expect(turnErrorText("", t)).toBeNull();
  });

  it("has a sentence for every code in every UI language", () => {
    for (const locale of [en, de, es, pt, zh]) {
      const errors = (locale as { thread_turn: { errors: Record<string, string> } }).thread_turn.errors;
      for (const code of CODES) expect(errors[code]?.length).toBeGreaterThan(10);
    }
  });
});

describe("turnErrorText for a spent allowance and a full context window", () => {
  const t = (key: string) => (key === "thread_turn.errors.usage_limit_until" ? "T:until {time}" : `T:${key}`);

  it("says the plan's allowance is used up, never a short wait", () => {
    const gateway = "The ChatGPT subscription reached its usage limit: the plan's allowance is used up until it resets. Until then, choose another connected model in the agent's settings. No fallback provider was called.";
    expect(turnErrorText(gateway, t)).toBe("T:thread_turn.errors.usage_limit");
    // A turn stored before the gateway told the two apart.
    expect(turnErrorText("openai-codex returned HTTP 429 (rate limit). Try again in 30 s, or choose another connected model in the agent's settings. No fallback provider was called.", t))
      .toBe("T:thread_turn.errors.usage_limit");
  });

  it("names the reset time when the gateway knows it", () => {
    const text = turnErrorText("OpenAI reached its usage limit: the plan's allowance is used up until it resets (it resets at 2026-10-27T15:04:00Z). Until then …", t);
    expect(text).toMatch(/^T:until .+/);
    expect(text).not.toContain("{time}");
  });

  it("keeps a real short rate limit as sent", () => {
    const limited = "openai returned HTTP 429 (rate limit). Try again in 30 s, or choose another connected model in the agent's settings.";
    expect(turnErrorText(limited, t)).toBe(limited);
    const subscription = "The ChatGPT subscription returned HTTP 429 (rate limit). Try again in 30 s, or choose another connected model in the agent's settings. No fallback provider was called.";
    expect(turnErrorText(subscription, t)).toBe(subscription);
  });

  it("explains a conversation that no longer fits the model's context window", () => {
    for (const reason of [
      "The conversation no longer fits this model's context window (context window exceeded). Start a fresh chat, or pick a model with a larger context window.",
      "Context length exceeded: the conversation is longer than qwen3.5:9b's context window on Ollama. Compress or shorten the conversation and send it again.",
      "Context window exceeded: estimated input 184592 leaves only 1 output tokens within the 65536-token context.",
    ]) expect(turnErrorText(reason, t)).toBe("T:thread_turn.errors.context_window");
  });

  it("has the new sentences in every UI language", () => {
    for (const locale of [en, de, es, pt, zh]) {
      const errors = (locale as { thread_turn: { errors: Record<string, string> } }).thread_turn.errors;
      expect(errors.usage_limit?.length).toBeGreaterThan(10);
      expect(errors.usage_limit_until).toContain("{time}");
      expect(errors.context_window?.length).toBeGreaterThan(10);
      expect(errors.usage_limit).not.toMatch(/30 ?s/);
    }
  });
});

describe("resetTimeLabel", () => {
  it("shows only the time on the same day and the day too otherwise", () => {
    const now = new Date("2026-10-27T10:00:00Z");
    const same = resetTimeLabel(new Date(now.getTime() + 60 * 60 * 1000).toISOString(), now);
    const later = resetTimeLabel(new Date(now.getTime() + 3 * 86400 * 1000).toISOString(), now);
    expect(same).toBeTruthy();
    expect(later && later.length).toBeGreaterThan(same!.length);
    expect(resetTimeLabel("not a date", now)).toBeNull();
  });
});
