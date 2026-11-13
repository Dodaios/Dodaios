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
import { PipelinePane, VoiceEngineSwitch } from "@/views/apikeys/VoiceEngine";

/** What `useVoiceMode` reports to the engine row; a test sets it before rendering. */
const voice = vi.hoisted(() => ({ state: {} as Record<string, unknown> }));
vi.mock("@/hooks/useVoiceMode", () => ({ useVoiceMode: () => voice.state }));

const ENGINE = { view: "live" as const, configured: "live" as const, choose: () => {}, busy: false, error: null };

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

describe("VoiceEngineSwitch call status", () => {
  beforeEach(() => {
    voice.state = { mode: "realtime", sessionActive: false, activeSessionMode: null };
  });

  it("draws no status line while no call runs and nothing went wrong", () => {
    render(<VoiceEngineSwitch engine={ENGINE} />);
    expect(screen.getByTestId("voice-engine-switch")).toBeTruthy();
    expect(screen.queryByTestId("voice-engine-runtime")).toBeNull();
    expect(screen.queryByTestId("realtime-last-start-error")).toBeNull();
  });

  it("says that the session is connecting before anything else", () => {
    voice.state = { mode: "realtime", connecting: true, sessionActive: true, activeSessionMode: "pipeline" };
    render(<VoiceEngineSwitch engine={ENGINE} />);
    expect(screen.getByTestId("voice-engine-runtime").textContent).toContain("Connecting the Realtime session");
  });

  it("names the engine and model a running call really uses", () => {
    voice.state = {
      mode: "realtime", sessionActive: true, activeSessionMode: "realtime",
      activeSessionProvider: "openai", activeSessionModel: "gpt-live",
    };
    render(<VoiceEngineSwitch engine={ENGINE} />);
    expect(screen.getByTestId("voice-engine-runtime").textContent).toBe("Current session: Realtime · openai · gpt-live");
  });

  it("says when a GPT-Live call fell back to the pipeline", () => {
    voice.state = { mode: "realtime", sessionActive: true, activeSessionMode: "pipeline" };
    render(<VoiceEngineSwitch engine={ENGINE} />);
    expect(screen.getByTestId("voice-engine-runtime").textContent).toContain("fell back to Pipeline");
  });

  it("shows why the last GPT-Live call did not start, and the transport's own reason", () => {
    voice.state = {
      mode: "realtime", sessionActive: false,
      lastStartError: { provider: "openai", message: "401 unauthorized" },
      requiresWebRtcOffer: true, transportOfferReady: false, transportOfferDetail: "app-server is not signed in",
    };
    render(<VoiceEngineSwitch engine={ENGINE} />);
    expect(screen.getByTestId("realtime-last-start-error").textContent).toBe("Voice connect failed (openai): 401 unauthorized");
    expect(screen.getByTestId("realtime-transport-offer-detail").textContent).toBe("app-server is not signed in");
  });

  it("keeps a GPT-Live start error to itself while the pipeline is the engine", () => {
    voice.state = { mode: "pipeline", sessionActive: false, lastStartError: { provider: "openai", message: "x" } };
    render(<VoiceEngineSwitch engine={{ ...ENGINE, view: "pipeline", configured: "pipeline" }} />);
    expect(screen.queryByTestId("realtime-last-start-error")).toBeNull();
  });
});
