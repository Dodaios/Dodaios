import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { ProviderDescriptor, SectionHealth } from "@/hooks/useProviders";
import { loadLocaleChunk, useI18nStore } from "@/i18n";
import { useProviderTestStore } from "@/store/providerTests";
import { ApiKeysTab } from "@/views/voice/ApiKeysTab";

function provider(overrides: Partial<ProviderDescriptor>): ProviderDescriptor {
  return {
    id: "openai-api",
    label: "OpenAI Whisper STT",
    tier: "stt",
    auth_mode: "api_key",
    secret_keys: ["openai_api_key"],
    secrets_set: { openai_api_key: false },
    dashboard_url: null,
    login_cli: null,
    install_hint: null,
    credential_path_hint: null,
    configured: false,
    active: false,
    cli_installed: null,
    credential_help: null,
    signup_url: null,
    billing: "api",
    alt_credential: null,
    ...overrides,
  };
}

/** A speech provider with a stored key. */
const OPENAI = provider({ secrets_set: { openai_api_key: true }, configured: true });
/** A speech provider without a key. */
const GEMINI = provider({
  id: "gemini-api",
  label: "Gemini STT",
  secret_keys: ["gemini_api_key"],
  secrets_set: { gemini_api_key: false },
});
/** A speech provider on this computer that is installed. */
const WHISPER = provider({
  id: "faster-whisper",
  label: "Whisper (on this machine)",
  auth_mode: "none",
  secret_keys: [],
  secrets_set: {},
  configured: true,
  billing: "local",
  local_runtime: {
    runtime: "faster-whisper",
    engine_installed: true,
    model_present: true,
    model_label: "Whisper",
    ready: true,
    detail: "",
  },
});
/** A speech provider on this computer that is not installed yet. */
const NEMOTRON = provider({
  id: "nemotron-local",
  label: "Nemotron (on this machine)",
  auth_mode: "none",
  secret_keys: [],
  secrets_set: {},
  configured: false,
  billing: "local",
  local_runtime: {
    runtime: "sherpa-onnx",
    engine_installed: false,
    model_present: false,
    model_label: "Nemotron",
    ready: false,
    detail: "",
  },
});
/** A wording provider with a stored key. */
const GROQ_WORDING = provider({
  id: "groq-polish",
  label: "Groq: dictation polish",
  tier: "dictation",
  secret_keys: ["groq_api_key"],
  secrets_set: { groq_api_key: true },
  configured: true,
  polish_family: "groq",
});

const hooks = vi.hoisted(() => ({
  state: {
    providers: [] as unknown[],
    loading: false,
    error: null as string | null,
    refetch: vi.fn(),
    setActiveOptimistic: vi.fn(),
  },
  health: {} as Record<string, unknown>,
}));

// The two data hooks are replaced. The save, remove, switch, check and install
// helpers stay real and talk to the fake `fetch` below.
vi.mock("@/hooks/useProviders", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useProviders")>()),
  useProviders: () => hooks.state,
  useSectionHealth: () => ({ health: hooks.health, reload: vi.fn() }),
}));

interface Reply {
  status?: number;
  body?: unknown;
}

/** What the fake backend answers, by "METHOD path". A test replaces entries. */
let replies: Record<string, Reply | (() => Reply)> = {};

const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const key = `${(init?.method ?? "GET").toUpperCase()} ${String(input)}`;
  const entry = replies[key];
  // Unless a test says otherwise, a write succeeds and a check finds a
  // working provider.
  const fallback: Reply = key.endsWith("/test")
    ? { body: { provider: "", status: "ok", detail: "", latency_ms: 50, integration_ok: true } }
    : { body: { ok: true } };
  const reply = (typeof entry === "function" ? entry() : entry) ?? fallback;
  const status = reply.status ?? 200;
  return { ok: status < 300, status, json: async () => reply.body ?? {} };
});

function calls(method: string, path: string) {
  return fetchMock.mock.calls.filter(
    ([url, init]) => String(url) === path && (init?.method ?? "GET").toUpperCase() === method,
  );
}

function body(call: unknown[]): unknown {
  return JSON.parse(String((call[1] as RequestInit).body));
}

/** Records the window events the tab sends. */
function listen(...types: string[]) {
  const heard: { type: string; detail: unknown }[] = [];
  const handler = (event: Event) =>
    heard.push({ type: event.type, detail: (event as CustomEvent).detail });
  for (const type of types) window.addEventListener(type, handler);
  return {
    heard,
    stop: () => types.forEach((type) => window.removeEventListener(type, handler)),
  };
}

function show(...providers: ProviderDescriptor[]) {
  hooks.state.providers = providers;
  return render(<ApiKeysTab />);
}

function state(id: string): string {
  return screen.getByTestId(`voice-provider-state-${id}`).textContent ?? "";
}

function openKey(id: string) {
  fireEvent.click(screen.getByTestId(`voice-provider-edit-${id}`));
}

function typeKey(id: string, value: string) {
  fireEvent.change(screen.getByTestId(`voice-provider-key-${id}-input`), { target: { value } });
}

beforeAll(async () => {
  useI18nStore.setState({ ui: "en" });
  await loadLocaleChunk("voice");
});

beforeEach(() => {
  hooks.state.loading = false;
  hooks.state.error = null;
  hooks.state.refetch.mockReset().mockResolvedValue(undefined);
  hooks.state.setActiveOptimistic.mockReset();
  hooks.health = {};
  replies = {};
  fetchMock.mockClear();
  vi.stubGlobal("fetch", fetchMock);
  useProviderTestStore.setState({ results: {} });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("ApiKeysTab states", () => {
  it("shows the shape of the page while the providers load", () => {
    hooks.state.loading = true;
    show();

    expect(screen.getByTestId("voice-keys-loading")).toBeTruthy();
    expect(screen.queryByTestId("voice-keys-stt")).toBeNull();
  });

  it("says that the providers could not be loaded and loads them again on request", async () => {
    hooks.state.error = "HTTP 500";
    show();

    const notice = screen.getByTestId("voice-keys-error");
    expect(notice.textContent).toContain("The providers could not be loaded.");
    expect(notice.textContent).not.toContain("HTTP 500");
    // No list was read, so no group claims to be empty.
    expect(screen.queryByTestId("voice-keys-stt")).toBeNull();

    fireEvent.click(screen.getByText("Try again"));
    await waitFor(() => expect(hooks.state.refetch).toHaveBeenCalledTimes(1));
  });

  it("keeps the last list on screen when reading it again failed", () => {
    hooks.state.error = "HTTP 500";
    show(OPENAI);

    expect(screen.getByTestId("voice-keys-error")).toBeTruthy();
    expect(screen.getByTestId("voice-provider-openai-api")).toBeTruthy();
  });

  it("says when a group has no providers", () => {
    show(OPENAI);

    expect(screen.getByTestId("voice-keys-dictation").textContent).toContain(
      "No providers are available.",
    );
  });
});

describe("ApiKeysTab rows", () => {
  it("lists speech providers and wording providers in their own groups, by plain name", () => {
    show(OPENAI, GEMINI, WHISPER, GROQ_WORDING);

    const speech = screen.getByTestId("voice-keys-stt");
    const wording = screen.getByTestId("voice-keys-dictation");
    expect(speech.textContent).toContain("Speech to text");
    expect(wording.textContent).toContain("Wording");
    expect(speech.contains(screen.getByTestId("voice-provider-openai-api"))).toBe(true);
    expect(wording.contains(screen.getByTestId("voice-provider-groq-polish"))).toBe(true);

    // The catalog's own labels name the tier and carry notes in brackets.
    expect(screen.getByTestId("voice-provider-openai-api").textContent).toContain("OpenAI Whisper");
    expect(screen.getByTestId("voice-provider-openai-api").textContent).not.toContain("STT");
    expect(screen.getByTestId("voice-provider-faster-whisper").textContent).not.toContain("machine");
    expect(screen.getByTestId("voice-provider-groq-polish").textContent).not.toContain("polish");
  });

  it("says each provider's state in a word or two", () => {
    show(OPENAI, GEMINI, WHISPER, NEMOTRON);

    expect(state("openai-api")).toBe("Key saved");
    expect(state("gemini-api")).toBe("No key");
    expect(state("faster-whisper")).toBe("On this computer");
    expect(state("nemotron-local")).toBe("Not installed");
  });

  it("says connected only once the provider answered", () => {
    useProviderTestStore.getState().record("openai-api", {
      provider: "openai-api",
      status: "ok",
      detail: "",
      latency_ms: 120,
      integration_ok: true,
    });
    show(OPENAI);

    expect(state("openai-api")).toBe("Connected");
  });

  it("says set up for a provider that is ready without a key in any slot", () => {
    show(provider({ id: "vertex-stt", label: "Vertex AI STT", configured: true }));

    expect(state("vertex-stt")).toBe("Set up");
  });

  it("marks the provider in use, and only that one", () => {
    show({ ...OPENAI, active: true }, { ...WHISPER, active: false });

    expect(screen.getByTestId("voice-provider-in-use-openai-api")).toBeTruthy();
    expect(screen.queryByTestId("voice-provider-use-openai-api")).toBeNull();
    expect(screen.queryByTestId("voice-provider-in-use-faster-whisper")).toBeNull();
    expect(screen.getByTestId("voice-provider-use-faster-whisper")).toBeTruthy();
  });

  it("offers no use action for a provider that has no key or is not installed", () => {
    show(GEMINI, NEMOTRON);

    expect(screen.queryByTestId("voice-provider-use-gemini-api")).toBeNull();
    expect(screen.queryByTestId("voice-provider-use-nemotron-local")).toBeNull();
  });

  it("offers no key field for a provider on this computer", () => {
    show(WHISPER);

    expect(screen.queryByTestId("voice-provider-edit-faster-whisper")).toBeNull();
  });

  it("says in one sentence what is wrong with the provider in use", () => {
    const health: SectionHealth = {
      status: "error",
      reason: "no_credits",
      detail: "OpenAI: out of credits",
      subject_id: "openai-api",
    };
    hooks.health = { stt: health };
    show({ ...OPENAI, active: true });

    expect(state("openai-api")).toBe("Not working");
    const fault = screen.getByTestId("voice-provider-fault-openai-api");
    expect(fault.textContent).toBe("This account has no credit left.");
  });

  it("does not blame the provider in use for a failure recorded for another one", () => {
    hooks.health = {
      stt: { status: "error", reason: "bad_key", detail: "", subject_id: "gemini-api" },
    };
    show({ ...OPENAI, active: true });

    expect(state("openai-api")).toBe("Key saved");
    expect(screen.queryByTestId("voice-provider-fault-openai-api")).toBeNull();
  });
});

describe("ApiKeysTab choosing a provider", () => {
  it("makes a speech provider the one in use", async () => {
    const events = listen("jarvis:stt-switched");
    show({ ...OPENAI, active: true }, WHISPER);

    fireEvent.click(screen.getByTestId("voice-provider-use-faster-whisper"));

    await waitFor(() => expect(events.heard).toHaveLength(1));
    events.stop();
    expect(hooks.state.setActiveOptimistic).toHaveBeenCalledWith("stt", "faster-whisper");
    const [call] = calls("POST", "/api/stt/switch");
    expect(body(call)).toEqual({ provider: "faster-whisper", persist: true });
    expect(hooks.state.refetch).toHaveBeenCalled();
    // A speech provider is checked when its key is saved, not when it is chosen.
    expect(calls("POST", "/api/providers/faster-whisper/test")).toHaveLength(0);
  });

  it("makes a wording provider the one in use by its family, then checks that it answers", async () => {
    const events = listen("jarvis:dictation-polish-switched");
    replies["POST /api/providers/groq-polish/test"] = {
      body: { provider: "groq-polish", status: "ok", detail: "", latency_ms: 90, integration_ok: true },
    };
    show(GROQ_WORDING);

    fireEvent.click(screen.getByTestId("voice-provider-use-groq-polish"));

    await waitFor(() => expect(state("groq-polish")).toBe("Connected"));
    events.stop();
    expect(events.heard).toHaveLength(1);
    expect(hooks.state.setActiveOptimistic).toHaveBeenCalledWith("dictation", "groq-polish");
    const [call] = calls("PUT", "/api/dictation/settings");
    // The family, not the row's id: an id the setting does not know is ignored.
    expect(body(call)).toEqual({ polish_provider: "groq", persist: true });
  });

  it("says so when the chosen wording provider does not answer", async () => {
    replies["POST /api/providers/groq-polish/test"] = {
      body: {
        provider: "groq-polish",
        status: "rate_limited",
        detail: "429",
        latency_ms: 90,
        integration_ok: true,
      },
    };
    show(GROQ_WORDING);

    fireEvent.click(screen.getByTestId("voice-provider-use-groq-polish"));

    await waitFor(() => expect(state("groq-polish")).toBe("Not working"));
    expect(screen.getByTestId("voice-provider-fault-groq-polish").textContent).toBe(
      "This provider is getting too many requests right now.",
    );
  });

  it("stays quiet when the check of a chosen wording provider could not run", async () => {
    replies["POST /api/providers/groq-polish/test"] = { status: 500, body: { detail: "boom" } };
    show(GROQ_WORDING);

    fireEvent.click(screen.getByTestId("voice-provider-use-groq-polish"));

    await waitFor(() => expect(calls("POST", "/api/providers/groq-polish/test")).toHaveLength(1));
    await waitFor(() => expect(state("groq-polish")).toBe("Key saved"));
    expect(screen.queryByTestId("voice-provider-fault-groq-polish")).toBeNull();
  });

  it("says when the switch failed and reads the real choice again", async () => {
    const events = listen("jarvis:provider-switch-failed", "jarvis:stt-switched");
    replies["POST /api/stt/switch"] = { status: 409, body: { detail: "not ready" } };
    show({ ...OPENAI, active: true }, WHISPER);

    fireEvent.click(screen.getByTestId("voice-provider-use-faster-whisper"));

    await waitFor(() =>
      expect(screen.getByTestId("voice-provider-fault-faster-whisper").textContent).toBe(
        "This provider could not be selected.",
      ),
    );
    events.stop();
    expect(hooks.state.refetch).toHaveBeenCalled();
    expect(events.heard.map((event) => event.type)).toEqual(["jarvis:provider-switch-failed"]);
    expect(events.heard[0].detail).toEqual({ section: "stt", provider: "faster-whisper" });
  });
});

describe("ApiKeysTab keys", () => {
  it("opens the key field in the row and closes it again", () => {
    show(GEMINI);
    expect(screen.queryByTestId("voice-provider-key-gemini-api")).toBeNull();

    openKey("gemini-api");
    expect(screen.getByTestId("voice-provider-key-gemini-api-input")).toBeTruthy();
    // Nothing is stored, so there is nothing to remove.
    expect(screen.queryByTestId("voice-provider-key-gemini-api-remove")).toBeNull();

    openKey("gemini-api");
    expect(screen.queryByTestId("voice-provider-key-gemini-api")).toBeNull();
  });

  it("saves a key to the provider's slot and tells the other screens", async () => {
    const events = listen("jarvis:secret-configured");
    replies["POST /api/secrets/gemini_api_key"] = {
      body: { ok: true, key: "gemini_api_key", written: ["gemini_api_key", "google_api_key"] },
    };
    show({ ...OPENAI, active: true }, GEMINI);

    openKey("gemini-api");
    const save = screen.getByTestId("voice-provider-key-gemini-api-save") as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    typeKey("gemini-api", "  AIza-example  ");
    expect(save.disabled).toBe(false);
    fireEvent.click(save);

    await waitFor(() => expect(events.heard).toHaveLength(2));
    events.stop();
    const [call] = calls("POST", "/api/secrets/gemini_api_key");
    expect(body(call)).toEqual({ value: "AIza-example" });
    // Every slot the server wrote is announced, and only by name.
    expect(events.heard.map((event) => event.detail)).toEqual([
      { key: "gemini_api_key", action: "set" },
      { key: "google_api_key", action: "set" },
    ]);
    expect(hooks.state.refetch).toHaveBeenCalled();
    // Another provider is in use, so the new key does not take over.
    expect(calls("POST", "/api/stt/switch")).toHaveLength(0);
    await waitFor(() => expect(screen.queryByTestId("voice-provider-key-gemini-api")).toBeNull());
  });

  it("checks a saved speech key at once and says when it was rejected", async () => {
    const events = listen("jarvis:provider-tested");
    replies["POST /api/providers/gemini-api/test"] = {
      body: {
        provider: "gemini-api",
        status: "bad_key",
        detail: "401",
        latency_ms: 80,
        integration_ok: true,
      },
    };
    show({ ...OPENAI, active: true }, GEMINI);

    openKey("gemini-api");
    typeKey("gemini-api", "AIza-example");
    fireEvent.click(screen.getByTestId("voice-provider-key-gemini-api-save"));

    await waitFor(() =>
      expect(screen.getByTestId("voice-provider-fault-gemini-api").textContent).toBe(
        "This key was rejected.",
      ),
    );
    events.stop();
    expect(state("gemini-api")).toBe("Not working");
    expect(events.heard).toHaveLength(1);
    expect(events.heard[0].detail).toMatchObject({
      section: "stt",
      provider: "gemini-api",
      active: false,
      result: { status: "bad_key" },
    });
  });

  it("puts the first key of a group in use", async () => {
    show(GEMINI);

    openKey("gemini-api");
    typeKey("gemini-api", "AIza-example");
    fireEvent.click(screen.getByTestId("voice-provider-key-gemini-api-save"));

    await waitFor(() => expect(calls("POST", "/api/stt/switch")).toHaveLength(1));
    expect(body(calls("POST", "/api/stt/switch")[0])).toEqual({
      provider: "gemini-api",
      persist: true,
    });
  });

  it("does not check a wording key when it is saved", async () => {
    const waiting = provider({
      id: "openai-polish",
      label: "OpenAI: dictation polish",
      tier: "dictation",
      polish_family: "openai",
    });
    show({ ...GROQ_WORDING, active: true }, waiting);

    openKey("openai-polish");
    typeKey("openai-polish", "sk-example");
    fireEvent.click(screen.getByTestId("voice-provider-key-openai-polish-save"));

    await waitFor(() => expect(calls("POST", "/api/secrets/openai_api_key")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByTestId("voice-provider-key-openai-polish")).toBeNull());
    expect(calls("POST", "/api/providers/openai-polish/test")).toHaveLength(0);
  });

  it("says when the key could not be saved and keeps what was typed", async () => {
    replies["POST /api/secrets/gemini_api_key"] = { status: 500, body: { detail: "disk full" } };
    show(GEMINI);

    openKey("gemini-api");
    typeKey("gemini-api", "AIza-example");
    fireEvent.click(screen.getByTestId("voice-provider-key-gemini-api-save"));

    await waitFor(() =>
      expect(screen.getByTestId("voice-provider-key-gemini-api-fault").textContent).toBe(
        "The key could not be saved.",
      ),
    );
    const input = screen.getByTestId("voice-provider-key-gemini-api-input") as HTMLInputElement;
    expect(input.value).toBe("AIza-example");
    expect(calls("POST", "/api/providers/gemini-api/test")).toHaveLength(0);
  });

  it("asks where a second, different key of the same provider should apply", async () => {
    let asked = false;
    replies["POST /api/secrets/openai_api_key"] = () => {
      if (asked) return { body: { ok: true, key: "openai_api_key" } };
      asked = true;
      return {
        body: {
          ok: false,
          key: "openai_api_key",
          choice_required: true,
          choice_kind: "dedicated_vs_family",
          family_label: "OpenAI",
        },
      };
    };
    show({ ...OPENAI, active: true });

    openKey("openai-api");
    typeKey("openai-api", "sk-second");
    fireEvent.click(screen.getByTestId("voice-provider-key-openai-api-save"));

    const question = await waitFor(() => screen.getByTestId("voice-provider-key-openai-api-scope"));
    expect(question.textContent).toContain("OpenAI already has a different key.");
    // Nothing was written yet, so nothing is announced or checked.
    expect(calls("POST", "/api/providers/openai-api/test")).toHaveLength(0);

    fireEvent.click(screen.getByText("Only here"));
    await waitFor(() => expect(calls("POST", "/api/secrets/openai_api_key")).toHaveLength(2));
    expect(body(calls("POST", "/api/secrets/openai_api_key")[1])).toEqual({
      value: "sk-second",
      scope: "here",
    });
  });

  it("removes a stored key", async () => {
    const events = listen("jarvis:secret-configured");
    show({ ...OPENAI, active: true });

    openKey("openai-api");
    fireEvent.click(screen.getByTestId("voice-provider-key-openai-api-remove"));

    await waitFor(() => expect(events.heard).toHaveLength(1));
    events.stop();
    expect(calls("DELETE", "/api/secrets/openai_api_key")).toHaveLength(1);
    expect(events.heard[0].detail).toEqual({ key: "openai_api_key", action: "delete" });
    expect(hooks.state.refetch).toHaveBeenCalled();
  });

  it("names the other places that use a key before it removes it", async () => {
    show({
      ...OPENAI,
      active: true,
      secret_shared_with: { openai_api_key: ["OpenAI GPT", "OpenAI: dictation polish"] },
    });

    openKey("openai-api");
    fireEvent.click(screen.getByTestId("voice-provider-key-openai-api-remove"));

    const question = screen.getByTestId("voice-provider-key-openai-api-shared");
    expect(question.textContent).toContain("This key is also used by OpenAI GPT, OpenAI.");
    expect(calls("DELETE", "/api/secrets/openai_api_key")).toHaveLength(0);

    fireEvent.click(screen.getByText("Remove anyway"));
    await waitFor(() => expect(calls("DELETE", "/api/secrets/openai_api_key")).toHaveLength(1));
  });

  it("says when the key could not be removed", async () => {
    replies["DELETE /api/secrets/openai_api_key"] = { status: 500, body: { detail: "locked" } };
    show({ ...OPENAI, active: true });

    openKey("openai-api");
    fireEvent.click(screen.getByTestId("voice-provider-key-openai-api-remove"));

    await waitFor(() =>
      expect(screen.getByTestId("voice-provider-key-openai-api-fault").textContent).toBe(
        "The key could not be removed.",
      ),
    );
  });
});

describe("ApiKeysTab providers on this computer", () => {
  it("installs a provider and follows the install to its end", async () => {
    vi.useFakeTimers();
    replies["POST /api/providers/nemotron-local/local-install"] = {
      body: { state: "running", ready: false, message: "" },
    };
    let polls = 0;
    replies["GET /api/providers/nemotron-local/local-install/status"] = () => {
      polls += 1;
      return { body: { state: polls < 2 ? "running" : "done", ready: polls >= 2, message: "" } };
    };
    show(NEMOTRON);

    fireEvent.click(screen.getByTestId("voice-provider-install-nemotron-local"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(state("nemotron-local")).toBe("Installing");
    expect(screen.queryByTestId("voice-provider-install-nemotron-local")).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(state("nemotron-local")).toBe("Installing");
    expect(hooks.state.refetch).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    // The install ended: the list is read again, and the row follows it.
    expect(hooks.state.refetch).toHaveBeenCalledTimes(1);
    expect(state("nemotron-local")).toBe("Not installed");
    expect(screen.queryByTestId("voice-provider-fault-nemotron-local")).toBeNull();
  });

  it("says when the install did not finish", async () => {
    replies["POST /api/providers/nemotron-local/local-install"] = {
      status: 500,
      body: { detail: "no disk space" },
    };
    show(NEMOTRON);

    fireEvent.click(screen.getByTestId("voice-provider-install-nemotron-local"));

    await waitFor(() =>
      expect(screen.getByTestId("voice-provider-fault-nemotron-local").textContent).toBe(
        "The installation did not finish.",
      ),
    );
    expect(state("nemotron-local")).toBe("Not installed");
  });
});
