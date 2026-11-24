import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ComposerDraft, ProviderOption } from "@/store/agentChat";

import { AgentModelPicker } from "./ThreadPickers";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));

afterEach(cleanup);

const providers = [
  { id: "claude", label: "Claude Code", connected: true, curated_models: [{ id: "claude-opus-5-5", label: "Opus 5.5" }] },
] as unknown as ProviderOption[];
const draft = { provider: "claude", model: "claude-opus-5-5" } as unknown as ComposerDraft;

describe("AgentModelPicker for a sub-agent", () => {
  it("names the sub-agent's own model and offers no pick while it is open", () => {
    render(<AgentModelPicker providers={providers} liveModels={{}} draft={draft} lockedProvider="claude"
      subagentModel="Haiku 5.5" onPick={() => undefined} />);
    const shown = screen.getByTestId("thread-model-picker-subagent");
    expect(shown.textContent).toContain("Haiku 5.5");
    expect(shown.tagName).not.toBe("BUTTON");
    expect(screen.queryByTestId("thread-model-picker")).toBeNull();
  });

  it("keeps the main agent's pick when no sub-agent model is named", () => {
    render(<AgentModelPicker providers={providers} liveModels={{}} draft={draft} lockedProvider="claude"
      onPick={() => undefined} />);
    expect(screen.queryByTestId("thread-model-picker-subagent")).toBeNull();
    expect(screen.getByTestId("thread-model-picker").textContent).toContain("Opus 5.5");
  });
});
