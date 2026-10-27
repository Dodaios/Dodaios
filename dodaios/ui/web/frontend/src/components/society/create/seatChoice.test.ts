import { describe, expect, it } from "vitest";

import type { CuratedModel } from "@/lib/agentChatApi";
import type { ProviderOption } from "@/store/agentChat";

import { runtimeSeats } from "../chat/modelChoices";
import type { BrainSeat } from "./brainPicker";
import {
  accessModels,
  API_KEY_ACCOUNT,
  billedPerUse,
  blockedReasonKey,
  costRank,
  defaultModel,
  pickableOption,
  providerChoices,
  SUBSCRIPTION_ACCOUNT,
} from "./seatChoice";

function models(...ids: string[]): CuratedModel[] {
  return ids.map((id) => ({ id, label: id }));
}

function seat(over: Partial<ProviderOption>, kind: BrainSeat["kind"] = "api"): BrainSeat {
  return {
    kind,
    accounts: [],
    provider: {
      id: "openai",
      label: "OpenAI",
      family: "openai",
      runner: "brain",
      models_source: "live",
      curated_models: models("gpt-5.5"),
      default_model: "",
      keyless: false,
      native_resume: false,
      effort_levels: [],
      default_effort: "",
      permission_modes: [],
      default_permission_mode: "",
      cli_installed: null,
      connected: true,
      active: false,
      ...over,
    },
  };
}

const claude = seat({
  id: "claude-api", label: "Anthropic Claude", family: "claude", runner: "claude-cli", cli_installed: true,
  curated_models: models("opusplan", "claude-opus-5", "claude-sonnet-5"),
}, "subscription");
const codex = seat({ id: "openai-codex", label: "OpenAI Codex", family: "openai", runner: "codex-cli", cli_installed: true }, "subscription");
const openai = seat({});
const ollama = seat({ id: "ollama", label: "Ollama", family: "ollama", keyless: true, curated_models: models("qwen3:8b") }, "local");

describe("providerChoices", () => {
  it("respects an explicit empty access list and a missing required CLI", () => {
    expect(providerChoices([claude], { "claude-api": [] })).toEqual([]);
    const missing = { ...claude, provider: { ...claude.provider, cli_installed: false } };
    expect(providerChoices([missing], { "claude-api": ["subscription"] })).toEqual([]);
  });

  it.each([
    ["grok-build", "grok", "xai", "xai", "grok-cli"],
    ["antigravity", "gemini", "antigravity", "gemini", "agy-cli"],
  ])("groups %s with its API brand while retaining each access's own models", (subscription, api, family, brand, runner) => {
    const [choice] = providerChoices([
      seat({ id: api, family: brand, curated_models: models("api-model-1") }),
      seat({ id: subscription, family, runner, cli_installed: true, curated_models: models("subscription-model-2") }, "subscription"),
    ]);
    expect(choice.id).toBe(brand);
    expect(choice.options.map((option) => [option.kind, option.seat.provider.id, accessModels(option)[0].id])).toEqual([
      ["subscription", subscription, "subscription-model-2"], ["api", api, "api-model-1"],
    ]);
  });

  it("folds a brand's subscription and API rows into one provider", () => {
    const [choice] = providerChoices([codex, openai]);
    expect(choice.label).toBe("OpenAI");
    expect(choice.options.map((o) => [o.kind, o.seat.provider.id, o.accountId])).toEqual([
      ["subscription", "openai-codex", ""],
      ["api", "openai", ""],
    ]);
  });

  it("offers Claude both ways on Jarvis when both work, each with its own account value", () => {
    const [choice] = providerChoices([claude], { "claude-api": ["api", "subscription"] });
    const [sub, api] = choice.options;
    expect([sub.kind, sub.accountId, sub.extraUsage]).toEqual(["subscription", SUBSCRIPTION_ACCOUNT, false]);
    // The subscription is Claude Code with its own aliases; the key gets real model ids only.
    expect(accessModels(sub).map((m) => m.id)).toContain("opusplan");
    expect([api.kind, api.accountId]).toEqual(["api", API_KEY_ACCOUNT]);
    expect(accessModels(api).map((m) => m.id)).not.toContain("opusplan");
  });

  it("never offers a subscription on Jarvis' loop without the vendor CLI", () => {
    const missing = { ...claude, provider: { ...claude.provider, cli_installed: false } };
    const [choice] = providerChoices([missing], { "claude-api": ["api", "subscription"] });
    expect(choice.options.map((o) => o.kind)).toEqual(["api"]);
  });

  it("marks Claude's login on Hermes / OpenClaw as extra usage", () => {
    const seats = runtimeSeats([claude, openai], ["claude-api", "openai"], [], ["claude-api"]);
    const [first] = providerChoices(seats, { "claude-api": ["api", "subscription"] }, true);
    expect(first.options.map((o) => [o.kind, o.accountId, o.extraUsage])).toEqual([
      ["subscription", SUBSCRIPTION_ACCOUNT, true],
      ["api", API_KEY_ACCOUNT, false],
    ]);
  });

  it("keeps a single seat as is when the backend names no ways (an older backend)", () => {
    const [choice] = providerChoices([claude]);
    expect(choice.options.map((o) => [o.kind, o.accountId])).toEqual([["subscription", ""]]);
  });

  it("lists a plan first, then a local model, then anything billed per use", () => {
    expect(providerChoices([ollama, openai, claude]).map((c) => c.id)).toEqual(["claude", "ollama", "openai"]);
  });

  it("never starts a Hermes / OpenClaw agent on Claude's extra usage while a plan is connected", () => {
    // Codex on ChatGPT reaches Hermes through the subscription gateway.
    const seats = runtimeSeats([claude, codex, openai], ["claude-api", "openai-codex", "openai"], ["openai-codex"], ["claude-api"]);
    const choices = providerChoices(seats, { "claude-api": ["api", "subscription"] }, true);
    expect(choices[0].id).toBe("openai");
    const picked = pickableOption(choices[0]);
    expect([picked?.kind, picked?.seat.provider.id, billedPerUse(picked)]).toEqual(["subscription", "openai-codex", false]);
    const claudeChoice = choices.find((c) => c.id === "claude")!;
    expect(billedPerUse(pickableOption(claudeChoice))).toBe(true);
  });

  it("prefers a local model over a per-use one, and says when only per-use is left", () => {
    const seats = runtimeSeats([claude, ollama], ["claude-api", "ollama"], [], ["claude-api"]);
    const choices = providerChoices(seats, { "claude-api": ["subscription"] }, true);
    expect(choices.map((c) => c.id)).toEqual(["ollama", "claude"]);
    expect(costRank(pickableOption(choices[0])!)).toBe(1);
    const only = providerChoices(runtimeSeats([claude], ["claude-api"], [], ["claude-api"]), { "claude-api": ["subscription"] }, true);
    expect(billedPerUse(pickableOption(only[0]))).toBe(true);
  });

  it("picks a provider's cheapest open access unless one is asked for", () => {
    const [choice] = providerChoices([codex, openai]);
    expect(pickableOption(choice)?.kind).toBe("subscription");
    expect(pickableOption(choice, "api")?.kind).toBe("api");
    expect(billedPerUse(null)).toBe(false);
  });

  it("shows a refused Claude login with its reason but never picks it", () => {
    const seats = runtimeSeats([claude, openai], ["claude-api", "openai"], [], ["claude-api"]);
    const choices = providerChoices(
      seats, { "claude-api": ["api", "subscription"] }, true,
      { "claude-api": { subscription: "extra_usage_off" } },
    );
    const claudeChoice = choices.find((c) => c.id === "claude")!;
    expect(claudeChoice.options.map((o) => [o.kind, o.blocked ?? ""])).toEqual([
      ["subscription", "extra_usage_off"],
      ["api", ""],
    ]);
    expect(pickableOption(claudeChoice, "subscription")?.kind).toBe("api");
  });

  it("lists a refused access the backend no longer names as working", () => {
    const seats = runtimeSeats([claude], ["claude-api"], [], ["claude-api"]);
    const [choice] = providerChoices(seats, {}, true, { "claude-api": { subscription: "extra_usage_spent" } });
    expect(choice.options.map((o) => [o.kind, o.blocked])).toEqual([["subscription", "extra_usage_spent"]]);
    expect(pickableOption(choice)).toBeNull();
  });

  it("sorts a provider whose every access is refused last", () => {
    const seats = runtimeSeats([claude, openai], ["claude-api", "openai"], [], ["claude-api"]);
    const order = providerChoices(seats, { "claude-api": ["subscription"] }, true, {
      "claude-api": { subscription: "extra_usage_off" },
    }).map((c) => c.id);
    expect(order).toEqual(["openai", "claude"]);
  });

  it("tolerates a backend without access_blocked", () => {
    const seats = runtimeSeats([claude], ["claude-api"], [], ["claude-api"]);
    const [choice] = providerChoices(seats, { "claude-api": ["subscription"] }, true);
    expect(choice.options.every((o) => !o.blocked)).toBe(true);
  });
});

describe("blockedReasonKey", () => {
  it("explains known refusals and falls back to a plain sentence", () => {
    expect(blockedReasonKey("extra_usage_off")).toBe("society.create_agent.access_blocked_extra_usage_off");
    expect(blockedReasonKey("extra_usage_spent")).toBe("society.create_agent.access_blocked_extra_usage_spent");
    expect(blockedReasonKey("something_new")).toBe("society.create_agent.access_blocked");
  });
});

describe("defaultModel", () => {
  it("starts on the row's default when it lists it, else the newest", () => {
    const [choice] = providerChoices([seat({ default_model: "gpt-5.2", curated_models: models("gpt-5.2", "gpt-5.5") })]);
    expect(defaultModel(choice.options[0])).toBe("gpt-5.2");
    const [plain] = providerChoices([seat({ curated_models: models("gpt-5.2", "gpt-5.5") })]);
    expect(defaultModel(plain.options[0])).toBe("gpt-5.5");
    expect(defaultModel(null)).toBe("");
  });
});


describe("startingOption", () => {
  // On Hermes / OpenClaw Claude's login is billed as extra usage; the API key per use.
  const [claudeChoice] = providerChoices([claude], { "claude-api": ["subscription", "api"] }, true);

  it("never starts on a remembered seat billed per use", async () => {
    const { startingOption } = await import("./SeatFields");
    const withLocal = { ...claudeChoice, options: [...claudeChoice.options, { kind: "local" as const, seat: ollama, accountId: "", extraUsage: false }] };
    expect(startingOption(withLocal, undefined, "subscription")?.kind).toBe("local");
    expect(startingOption(withLocal, undefined, "local")?.kind).toBe("local");
  });

  it("keeps what the person picked in this dialog, and warns there", async () => {
    const { startingOption } = await import("./SeatFields");
    const picked = startingOption(claudeChoice, "subscription");
    expect(picked?.extraUsage).toBe(true);
    expect(billedPerUse(picked)).toBe(true);
  });

  it("starts on the plan when the remembered access is the plan", async () => {
    const { startingOption } = await import("./SeatFields");
    const [jarvisClaude] = providerChoices([claude], { "claude-api": ["subscription", "api"] }, false);
    expect(startingOption(jarvisClaude, undefined, "subscription")?.kind).toBe("subscription");
    expect(startingOption(jarvisClaude, undefined, "subscription")?.extraUsage).toBe(false);
  });
});
