import { describe, expect, it } from "vitest";
import de from "@/i18n/locales/de.json";
import en from "@/i18n/locales/en.json";
import es from "@/i18n/locales/es.json";
import pt from "@/i18n/locales/pt.json";
import zh from "@/i18n/locales/zh.json";
import { redactDetails, resetTimeLabel, turnErrorText, turnErrorView } from "./turnError";

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

describe("turnErrorView for runtime failures", () => {
  const t = (key: string) => `T:${key}`;
  const HERMES_DUMP = [
    "2026-10-27 17:05:19 [INFO] tools.tool_search: tool_search activated (tier 1): 10 core/visible tools kept",
    "2026-10-27 17:05:19 [INFO] acp_adapter.server: New session 6d5a (cwd=C:\\Users\\Someone\\Desktop\\Personal Jarvis\\data\\society\\qa)",
    "2026-10-27 17:05:21 [INFO] acp_adapter.server: Prompt on session 6d5a: <jarvis_identity>",
    "## You are QA Hermes local",
    "Tier: specialist. Permission ceiling: ask.",
    "2026-10-27 17:05:21 [INFO] agent.turn_context: conversation turn: msg='<jarvis_identity> ## You are QA Hermes local...'",
    "2026-10-27 17:05:25 [INFO] run_agent: OpenAI client created provider=custom base_url=http://127.0.0.1:47821/api/runtime-gateway/v1?token=abc model=qwen3.5:9b",
  ].join("\n");

  it("never puts a raw stderr dump on the card; the redacted tail goes to the details", () => {
    const view = turnErrorView(HERMES_DUMP, null, t)!;
    expect(view.reason).toBe("T:thread_turn.errors.crashed");
    expect(view.reason).not.toContain("jarvis_identity");
    expect(view.details).toBeTruthy();
    for (const leak of ["You are QA Hermes", "<jarvis_identity>", "127.0.0.1:47821", "runtime-gateway", "token=abc", "Someone", "Permission ceiling"]) {
      expect(view.details).not.toContain(leak);
    }
    expect(view.details).toContain("tool_search activated");
  });

  it("redacts the backend's details too, and keeps them out of the reason", () => {
    const view = turnErrorView("Hermes stopped with an error. Try again.", "see https://x.example/a?key=1 at /home/someone/x", t)!;
    expect(view.reason).toBe("T:thread_turn.errors.crashed");
    expect(view.details).toBe("see [url] at ~/x");
  });

  it("maps gateway UNAVAILABLE replies to a readable reason", () => {
    expect(turnErrorView("Internal error: UNAVAILABLE: OpenClaw agent database C:/x uses schema version 3; run openclaw doctor --fix to migrate persisted media before using it.", null, t)!.reason)
      .toBe("T:thread_turn.errors.runtime_updating");
    expect(turnErrorView("Internal error: Agent main has not completed startup inspection and preparation. busy", null, t)!.reason)
      .toBe("T:thread_turn.errors.still_starting");
    expect(turnErrorView("The agent is still starting up. Try again in a moment.", null, t)!.reason)
      .toBe("T:thread_turn.errors.still_starting");
    const bare = turnErrorView("Internal error", null, t)!;
    expect(bare.reason).toBe("T:thread_turn.errors.internal");
    expect(bare.details).toBeNull();
  });

  it("names the runtime by its display name when it went silent, and blames a local model gently", () => {
    const legacy = turnErrorView("openclaw-cli stopped responding (nothing for 5 minutes); the turn was stopped.", null, (key) => key === "thread_turn.errors.stall" ? "{runtime}/{minutes}" : key)!;
    expect(legacy.reason).toBe("OpenClaw/5");
    const local = turnErrorView("OpenClaw got no reply from the local model for 5 minutes, so the turn was stopped. The model may be busy.", null, (key) => key === "thread_turn.errors.stall_local" ? "L:{runtime}/{minutes}" : key)!;
    expect(local.reason).toBe("L:OpenClaw/5");
  });

  it("says the app restarted, in the old wording too", () => {
    for (const text of [
      "Dodaios restarted while this turn was running. Everything after the last step shown here was not captured.",
      "Jarvis restarted while this turn was running.",
      "The app restarted while this turn was running. Send it again.",
    ]) expect(turnErrorView(text, null, t)!.reason).toBe("T:thread_turn.errors.app_restarted");
  });

  it("offers no Retry while a spent allowance waits for a future reset", () => {
    const now = new Date("2026-10-27T10:00:00Z");
    const future = "The ChatGPT subscription reached its usage limit: the plan's allowance is used up until it resets (it resets at 2026-11-18T17:19:20Z).";
    expect(turnErrorView(future, null, t, now)!.retryable).toBe(false);
    const past = "The ChatGPT subscription reached its usage limit: the plan's allowance is used up until it resets (it resets at 2026-10-01T17:19:20Z).";
    expect(turnErrorView(past, null, t, now)!.retryable).toBe(true);
    const vendor = "You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at Nov 15th, 2026 3:37 PM.";
    expect(turnErrorView(vendor, null, t, now)!.retryable).toBe(false);
    expect(turnErrorView("Provider timed out", null, t, now)!.retryable).toBe(true);
  });

  it("swaps a runner id for its name and leaves a plain reason alone", () => {
    expect(turnErrorView("openclaw-cli exited with code 1.", null, t)!.reason).toBe("OpenClaw exited with code 1.");
    expect(turnErrorView("Ollama is not reachable.", null, t)!.reason).toBe("Ollama is not reachable.");
  });

  it("has the runtime sentences in every UI language", () => {
    for (const locale of [en, de, es, pt, zh]) {
      const block = (locale as { thread_turn: { technical_details: string; errors: Record<string, string> } }).thread_turn;
      expect(block.technical_details?.length).toBeGreaterThan(2);
      for (const key of ["runtime_updating", "still_starting", "app_restarted", "the_agent"]) expect(block.errors[key]?.length).toBeGreaterThan(1);
      for (const key of ["stall", "stall_local"]) expect(block.errors[key]).toMatch(/\{runtime\}[\s\S]*\{minutes\}|\{minutes\}[\s\S]*\{runtime\}/);
      for (const key of ["internal", "crashed"]) expect(block.errors[key]).toContain("{runtime}");
    }
  });
});

describe("redactDetails for a profile folder with spaces", () => {
  it("hides the whole folder name, not only its first word", () => {
    const out = redactDetails("C:/Users/First Last/proj/a.py and /home/first last/b");
    expect(out).toBe("~/proj/a.py and ~/b");
  });
});

describe("turnErrorView for the backend's usage-limit reason", () => {
  it("keeps Retry hidden until the vendor's reset time", () => {
    const t = (key: string) => key;
    const now = new Date("2026-10-14T12:00:00");
    const view = turnErrorView("The usage limit for this model is used up. You can try again at Oct 15th, 2026 3:37 PM.", "raw", t, now)!;
    expect(view.reason).toBe("thread_turn.errors.usage_limit_until");
    expect(view.retryable).toBe(false);
    const iso = turnErrorView("The usage limit for this model is used up. It resets at 2026-10-28T15:04:00Z.", null, t, now)!;
    expect(iso.retryable).toBe(false);
  });
});
