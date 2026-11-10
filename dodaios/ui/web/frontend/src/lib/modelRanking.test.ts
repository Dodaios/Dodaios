import { describe, expect, it } from "vitest";

import { bestModelId, rankModels } from "./modelRanking";

const ids = (models: { id: string }[]) => models.map((model) => model.id);

describe("rankModels", () => {
  it("ranks Claude Fable, Opus, Sonnet, Haiku and folds earlier versions", () => {
    const { current, older } = rankModels([
      { id: "claude-haiku-5-5", label: "Claude Haiku 5.5" },
      { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5" },
      { id: "claude-opus-5-5", label: "Claude Opus 5.5" },
      { id: "claude-fable-5-2", label: "Claude Fable 5.2" },
      { id: "claude-fable-5-1", label: "Claude Fable 5.1" },
      { id: "claude-opus-5", label: "Claude Opus 5" },
      { id: "claude-sonnet-5", label: "Claude Sonnet 5" },
      { id: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
      { id: "opusplan", label: "Opus plans, Sonnet builds" },
      { id: "claude-opus-4-8", label: "Claude Opus 4.8" },
    ]);
    expect(ids(current)).toEqual(["claude-fable-5-2", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]);
    expect(ids(older)).toEqual(["claude-fable-5-1", "claude-opus-5", "claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5-20251001", "opusplan"]);
  });

  it("keeps variants of the newest version together in the lineup", () => {
    const { current } = rankModels([
      { id: "claude-opus-5", label: "Claude Opus 5" },
      { id: "claude-opus-5[1m]", label: "Claude Opus 5", note: "1M context" },
    ]);
    expect(ids(current)).toEqual(["claude-opus-5", "claude-opus-5[1m]"]);
  });

  it("ranks named GPT tiers and puts Pro above its base model", () => {
    const { current, older } = rankModels([
      { id: "gpt-5.6-luna", label: "GPT-5.6 Luna" },
      { id: "gpt-5.6-terra", label: "GPT-5.6 Terra" },
      { id: "gpt-5.6-sol", label: "GPT-5.6 Sol" },
      { id: "gpt-5.6-sol-pro", label: "GPT-5.6 Sol Pro" },
      { id: "gpt-5.5", label: "GPT-5.5" },
      { id: "gpt-5.2", label: "GPT-5.2" },
    ]);
    expect(ids(current)).toEqual(["gpt-5.6-sol-pro", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.5", "gpt-5.6-luna"]);
    expect(ids(older)).toEqual(["gpt-5.2"]);
  });

  it("ranks Gemini Pro above Flash above Flash-Lite whatever the version", () => {
    const { current } = rankModels([
      { id: "gemini-3.1-flash-lite", label: "Gemini 3.1 Flash-Lite" },
      { id: "gemini-3.8-flash", label: "Gemini 3.8 Flash" },
      { id: "gemini-3.1-pro", label: "Gemini 3.1 Pro" },
    ]);
    expect(ids(current)).toEqual(["gemini-3.1-pro", "gemini-3.8-flash", "gemini-3.1-flash-lite"]);
  });

  it("falls back to the newest version first for lines without a tier word", () => {
    const { current } = rankModels([
      { id: "grok-4.3", label: "Grok 4.3" },
      { id: "grok-4.7", label: "Grok 4.7" },
    ]);
    expect(ids(current)).toEqual(["grok-4.7"]);
  });

  it("folds nothing when no model carries a version", () => {
    const models = [{ id: "auto", label: "Auto" }, { id: "composer", label: "Composer" }];
    expect(rankModels(models)).toEqual({ current: models, older: [] });
  });
});

describe("bestModelId", () => {
  it("is the top of the lineup, or empty when the provider lists nothing", () => {
    expect(bestModelId([
      { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5" },
      { id: "claude-fable-5-2", label: "Claude Fable 5.2" },
    ])).toBe("claude-fable-5-2");
    expect(bestModelId([])).toBe("");
  });
});
