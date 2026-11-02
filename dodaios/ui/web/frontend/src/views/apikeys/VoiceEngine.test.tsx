/**
 * The Pipeline's brain row (#1028): it names the VOICE brain, offers the brain
 * list inline, and warns when the active voice brain has no credential.
 *
 * No jest-dom in this repo — assertions use plain values.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

import { _resetProvidersCacheForTests } from "@/hooks/useProviders";
import { loadLocaleChunk } from "@/i18n";
import { PipelinePane } from "@/views/apikeys/VoiceEngine";

const BASE = {
  dashboard_url: null, login_cli: null, install_hint: null, credential_path_hint: null,
  cli_installed: null, credential_help: null, signup_url: null, alt_credential: null,
};

let providers: Record<string, unknown>[] = [];

function brain(id: string, label: string, over: Record<string, unknown> = {}) {
  return {
    ...BASE, id, label, tier: "brain", auth_mode: "api_key", secret_keys: [`${id}_api_key`],
    secrets_set: {}, configured: false, active: false, billing: "api", ...over,
  };
}

beforeEach(async () => {
  await loadLocaleChunk("providers");
  _resetProvidersCacheForTests();
  providers = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.startsWith("/api/providers/section-health")
        ? { sections: {}, checked_at: 0, cached: false }
        : url.startsWith("/api/providers")
          ? { providers }
          : {};
      return { ok: true, status: 200, json: async () => body, text: async () => "" } as Response;
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("PipelinePane brain", () => {
  it("names the voice brain, not the agent default, and lists the brains inline", async () => {
    providers = [
      brain("claude-api", "Claude (API-Key)", { active: true, configured: true, secrets_set: { "claude-api_api_key": true } }),
      brain("openai", "OpenAI"),
    ];
    render(<PipelinePane />);
    const row = await screen.findByTestId("voice-pipeline-brain");
    await within(row).findByText(/voice brain: Claude \(API-Key\)/);
    expect(row.textContent).not.toContain("default agent provider");
    expect(screen.queryByTestId("voice-pipeline-brain-missing")).toBeNull();
    const picker = screen.getByTestId("voice-pipeline-brain-picker");
    expect(within(picker).getByTestId("provider-row-claude-api")).toBeTruthy();
    expect(within(picker).getByTestId("provider-row-openai")).toBeTruthy();
  });

  it("warns when the active voice brain has no key", async () => {
    providers = [
      brain("claude-api", "Claude (API-Key)", { active: true }),
      brain("openai", "OpenAI", { configured: true, secrets_set: { openai_api_key: true } }),
    ];
    render(<PipelinePane />);
    const warning = await screen.findByTestId("voice-pipeline-brain-missing");
    expect(warning.getAttribute("role")).toBe("alert");
    expect(warning.textContent).toContain("Claude (API-Key) is not set up yet");
  });
});
