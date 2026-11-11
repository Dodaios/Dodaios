import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ComposerDraft, ProviderOption } from "@/store/agentChat";

import { SpeedPicker } from "./ThreadPickers";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));

afterEach(cleanup);

const claude = {
  models_source: "curated",
  curated_models: [
    { id: "claude-opus-5-5", label: "Claude Opus 5.5", speeds: [{ id: "fast", label: "Fast" }] },
    { id: "claude-fable-5-2", label: "Claude Fable 5.2" },
  ],
} as unknown as ProviderOption;

const codex = {
  id: "codex",
  models_source: "curated",
  curated_models: [{
    id: "gpt-6-astra",
    label: "GPT-6 Astra",
    speeds: [
      { id: "priority", label: "Fast", note: "2x speed, increased usage" },
      { id: "ultrafast", label: "Ultrafast", note: "Fastest" },
    ],
  }],
} as unknown as ProviderOption;

function draft(model: string, speed = ""): ComposerDraft {
  return { model, speed } as unknown as ComposerDraft;
}

describe("SpeedPicker", () => {
  it("is absent on a model without a fast mode", () => {
    const { container } = render(
      <SpeedPicker provider={claude} draft={draft("claude-fable-5-2")} liveModels={{}} onPick={() => undefined} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("is a quiet bolt with no words at the standard speed", () => {
    render(<SpeedPicker provider={claude} draft={draft("claude-opus-5-5")} liveModels={{}} onPick={() => undefined} />);
    const trigger = screen.getByTestId("thread-speed-picker");
    expect(trigger.textContent).toBe("agent_chat.speed_standard");
    expect(trigger.querySelector(".sr-only")?.textContent).toBe("agent_chat.speed_standard");
  });

  it("names the tier once fast mode is on", () => {
    render(<SpeedPicker provider={claude} draft={draft("claude-opus-5-5", "fast")} liveModels={{}} onPick={() => undefined} />);
    const trigger = screen.getByTestId("thread-speed-picker");
    expect(trigger.querySelector(".sr-only")).toBeNull();
    expect(trigger.textContent).toContain("Fast");
  });

  it("lists every tier the account has, and picks one by its id", () => {
    const onPick = vi.fn();
    render(<SpeedPicker provider={codex} draft={draft("gpt-6-astra")} liveModels={{}} onPick={onPick} />);
    fireEvent.click(screen.getByTestId("thread-speed-picker"));
    const rows = screen.getAllByRole("option");
    expect(rows.map((row) => row.getAttribute("data-value"))).toEqual(["", "priority", "ultrafast"]);
    expect(rows[1].textContent).toContain("2x speed, increased usage");
    fireEvent.click(rows[2]);
    expect(onPick).toHaveBeenCalledWith("ultrafast");
  });

  it("shows the standard speed when the stored tier is not offered on this model", () => {
    render(<SpeedPicker provider={codex} draft={draft("gpt-6-astra", "flex")} liveModels={{}} onPick={() => undefined} />);
    expect(screen.getByTestId("thread-speed-picker").querySelector(".sr-only")?.textContent).toBe("agent_chat.speed_standard");
  });
});
