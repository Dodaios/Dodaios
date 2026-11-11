import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ComposerDraft, ProviderOption } from "@/store/agentChat";

import { EffortPicker } from "./ThreadPickers";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));

afterEach(cleanup);

const ladder = ["low", "medium", "high"];

const claude = {
  models_source: "curated",
  effort_levels: ladder,
  curated_models: [
    { id: "claude-opus-5-5", label: "Claude Opus 5.5", speeds: [{ id: "fast", label: "Fast" }] },
    { id: "claude-fable-5-2", label: "Claude Fable 5.2" },
  ],
} as unknown as ProviderOption;

const codex = {
  models_source: "curated",
  effort_levels: ladder,
  curated_models: [{
    id: "gpt-6-astra",
    label: "GPT-6 Astra",
    speeds: [
      { id: "priority", label: "Fast", note: "2x speed, increased usage" },
      { id: "ultrafast", label: "Ultrafast" },
    ],
  }],
} as unknown as ProviderOption;

function draft(model: string, speed = ""): ComposerDraft {
  return { model, effort: "high", speed } as unknown as ComposerDraft;
}

function picker(provider: ProviderOption, model: string, speed = "", onPick = vi.fn(), onPickSpeed = vi.fn()) {
  render(<EffortPicker provider={provider} draft={draft(model, speed)} liveModels={{}} onPick={onPick} onPickSpeed={onPickSpeed} />);
  return screen.getByTestId("thread-effort-picker");
}

describe("EffortPicker fast mode", () => {
  it("has no fast-mode section and no bolt on a model without one", () => {
    fireEvent.click(picker(claude, "claude-fable-5-2"));
    expect(screen.queryByText("agent_chat.speed_group")).toBeNull();
    expect(screen.queryByTestId("thread-speed-bolts")).toBeNull();
  });

  it("offers Claude Code's fast mode as On / Off under the effort levels, each pick with its own check", () => {
    const onPick = vi.fn();
    const onPickSpeed = vi.fn();
    fireEvent.click(picker(claude, "claude-opus-5-5", "", onPick, onPickSpeed));
    const rows = screen.getAllByRole("option");
    expect(rows.map((row) => row.getAttribute("data-value"))).toEqual(["low", "medium", "high", "speed:", "speed:fast"]);
    expect(rows.map((row) => row.getAttribute("aria-selected"))).toEqual(["false", "false", "true", "true", "false"]);
    expect(rows[3].textContent).toContain("agent_chat.speed_off");
    expect(rows[4].textContent).toContain("agent_chat.speed_on");
    fireEvent.click(rows[4]);
    expect(onPickSpeed).toHaveBeenCalledWith("fast");
    expect(onPick).not.toHaveBeenCalled();
  });

  it("draws one bolt on the trigger when fast mode is on, none when it is off", () => {
    const trigger = picker(claude, "claude-opus-5-5", "fast");
    expect(trigger.querySelector("[data-testid='thread-speed-bolts']")?.getAttribute("data-bolts")).toBe("1");
    expect(trigger.textContent).toContain("agent_chat.effort_high");
  });

  it("names Codex's tiers and draws two bolts for Ultrafast", () => {
    const onPickSpeed = vi.fn();
    const trigger = picker(codex, "gpt-6-astra", "ultrafast", vi.fn(), onPickSpeed);
    expect(trigger.querySelector("[data-testid='thread-speed-bolts']")?.getAttribute("data-bolts")).toBe("2");
    fireEvent.click(trigger);
    const rows = screen.getAllByRole("option").slice(3);
    expect(rows.map((row) => row.textContent)).toEqual(["agent_chat.speed_off", "Fast", "Ultrafast"]);
    fireEvent.click(rows[0]);
    expect(onPickSpeed).toHaveBeenCalledWith("");
  });

  it("shows no bolt for a stored tier this model does not offer", () => {
    expect(picker(codex, "gpt-6-astra", "flex").querySelector("[data-testid='thread-speed-bolts']")).toBeNull();
  });
});
