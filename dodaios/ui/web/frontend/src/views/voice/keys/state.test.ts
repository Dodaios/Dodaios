import { describe, expect, it } from "vitest";

import type { ProviderDescriptor, SectionHealth } from "@/hooks/useProviders";
import { faultKey, rowState } from "@/views/voice/keys/state";

function provider(overrides: Partial<ProviderDescriptor> = {}): ProviderDescriptor {
  return {
    id: "openai-api",
    label: "OpenAI Whisper STT",
    tier: "stt",
    auth_mode: "api_key",
    secret_keys: ["openai_api_key"],
    secrets_set: { openai_api_key: true },
    dashboard_url: null,
    login_cli: null,
    install_hint: null,
    credential_path_hint: null,
    configured: true,
    active: false,
    cli_installed: null,
    credential_help: null,
    signup_url: null,
    billing: "api",
    alt_credential: null,
    ...overrides,
  };
}

const LOCAL = {
  runtime: "faster-whisper",
  engine_installed: true,
  model_present: true,
  model_label: "Whisper",
  ready: true,
  detail: "",
};

function health(status: SectionHealth["status"]): SectionHealth {
  return { status, reason: status, detail: "", subject_id: "openai-api" };
}

describe("rowState", () => {
  it("calls a stored key saved, not connected", () => {
    expect(rowState(provider(), { verification: null })).toBe("key_saved");
  });

  it("calls a provider connected once it answered", () => {
    expect(rowState(provider(), { verification: "ok" })).toBe("connected");
  });

  it("takes the health record as an answer for the provider in use only", () => {
    expect(rowState(provider({ active: true }), { verification: null, health: health("ok") })).toBe(
      "connected",
    );
    expect(rowState(provider({ active: false }), { verification: null, health: health("ok") })).toBe(
      "key_saved",
    );
    expect(
      rowState(provider({ active: true }), { verification: null, health: health("error") }),
    ).toBe("not_working");
    expect(
      rowState(provider({ active: false }), { verification: null, health: health("error") }),
    ).toBe("key_saved");
  });

  it("puts a check made in this session above an older health record", () => {
    expect(
      rowState(provider({ active: true }), { verification: "ok", health: health("error") }),
    ).toBe("connected");
    expect(
      rowState(provider({ active: true }), { verification: "failed", health: health("ok") }),
    ).toBe("not_working");
  });

  it("says no key for a provider without one", () => {
    expect(
      rowState(provider({ configured: false, secrets_set: { openai_api_key: false } }), {
        verification: null,
      }),
    ).toBe("no_key");
  });

  it("counts a key the provider shares with another place as a saved key", () => {
    expect(
      rowState(
        provider({
          secrets_set: { openai_api_key: false },
          secrets_effective: { openai_api_key: true },
        }),
        { verification: null },
      ),
    ).toBe("key_saved");
  });

  it("says set up when the provider is ready with no key in any slot", () => {
    expect(
      rowState(provider({ secrets_set: { openai_api_key: false } }), { verification: null }),
    ).toBe("set_up");
  });

  it("says where a provider on this computer runs, or that it is not installed", () => {
    const local = provider({ auth_mode: "none", secret_keys: [], secrets_set: {} });
    expect(rowState(local, { verification: null })).toBe("local");
    expect(rowState({ ...local, local_runtime: LOCAL }, { verification: null })).toBe("local");
    expect(
      rowState(
        { ...local, configured: false, local_runtime: { ...LOCAL, ready: false } },
        { verification: null },
      ),
    ).toBe("not_installed");
  });

  it("shows work in progress before anything else", () => {
    expect(rowState(provider(), { verification: "failed", installing: true })).toBe("installing");
    expect(rowState(provider(), { verification: "failed", checking: true })).toBe("checking");
  });
});

describe("faultKey", () => {
  it("has a sentence for each cause a check reports", () => {
    expect(faultKey("bad_key")).toBe("voiceui.keys.fault.bad_key");
    expect(faultKey("no_credits")).toBe("voiceui.keys.fault.no_credits");
  });

  it("reads an unknown or missing cause as a plain failure", () => {
    expect(faultKey("something_new")).toBe("voiceui.keys.fault.error");
    expect(faultKey(undefined)).toBe("voiceui.keys.fault.error");
  });
});
