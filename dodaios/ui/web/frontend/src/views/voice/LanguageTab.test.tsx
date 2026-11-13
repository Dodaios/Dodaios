import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import type {
  DictationPolishTest,
  DictationSettings,
  DictationWordingProvider,
} from "@/hooks/useDictation";
import type { ProviderDescriptor } from "@/hooks/useProviders";
import { loadLocaleChunk, useI18nStore } from "@/i18n";
import { LanguageTab } from "@/views/voice/LanguageTab";

const SETTINGS = {
  language: "auto",
  polish: true,
  polish_provider: "auto",
  polish_model: "",
  polish_precision: false,
  polish_conversation: false,
  prompt_mode: false,
  translate: false,
  translate_target: "en",
} as unknown as DictationSettings;

const CHOICES = {
  language: ["auto", "de", "en", "es"],
  polish_provider: ["auto", "groq", "gemini", "ollama"],
  // No automatic entry: there is nothing to detect in the written language.
  translate_target: ["de", "en", "es"],
};

/** The automatic choice lands on a company's model that has its key. */
const GROQ_READY: DictationWordingProvider = {
  family: "groq",
  label: "Groq",
  spec_id: "groq-polish",
  secret_key: "groq_api_key",
  needs_key: true,
  ready: true,
};

/** No model can answer; this is the key that would fix it. */
const GROQ_NO_KEY: DictationWordingProvider = { ...GROQ_READY, ready: false };

/** The model runs on this computer and takes no key. */
const OLLAMA_READY: DictationWordingProvider = {
  family: "ollama",
  label: "Ollama (local)",
  spec_id: "ollama-polish",
  secret_key: "",
  needs_key: false,
  ready: true,
};

const SAMPLE: DictationPolishTest = {
  status: "applied",
  provider: "groq",
  model: "llama",
  latency_ms: 240,
  reason: "",
  sample_in: "so um i think we should ship on tuesday actually wednesday",
  sample_out: "I think we should ship on Wednesday.",
};

function entry(overrides: Partial<ProviderDescriptor>): ProviderDescriptor {
  return {
    id: "groq-polish",
    label: "Groq: dictation polish",
    tier: "dictation",
    auth_mode: "api_key",
    secret_keys: ["groq_api_key"],
    secrets_set: { groq_api_key: false },
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
    polish_family: "groq",
    ...overrides,
  };
}

const PROVIDERS: ProviderDescriptor[] = [
  entry({}),
  entry({
    id: "ollama-polish",
    label: "Ollama (local): dictation polish",
    auth_mode: "none",
    secret_keys: [],
    secrets_set: {},
    configured: true,
    billing: "local",
    polish_family: "ollama",
  }),
];

const dictation = vi.hoisted(() => ({
  state: {
    settings: null as unknown,
    choices: null as unknown,
    wordingProvider: null as unknown,
    loading: false,
    error: null as string | null,
    saveSettings: vi.fn(),
    refetch: vi.fn(),
  },
  test: vi.fn(),
}));

const catalog = vi.hoisted(() => ({
  state: { providers: [] as unknown[], refetch: vi.fn() },
}));

// The two data hooks and the sample request are replaced. The key helpers of
// the provider hook stay real and talk to the fake `fetch` below.
vi.mock("@/hooks/useDictation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useDictation")>()),
  useDictation: () => dictation.state,
  testDictationPolish: () => dictation.test(),
}));

vi.mock("@/hooks/useProviders", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useProviders")>()),
  useProviders: () => ({
    providers: catalog.state.providers,
    loading: false,
    error: null,
    refetch: catalog.state.refetch,
    setActiveOptimistic: vi.fn(),
  }),
}));

const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({
  ok: true,
  status: 200,
  json: async () => ({ ok: true, key: "groq_api_key" }),
}));

function show(
  settings: Partial<DictationSettings> = {},
  wordingProvider: DictationWordingProvider | null = GROQ_READY,
) {
  dictation.state.settings = { ...SETTINGS, ...settings };
  dictation.state.choices = CHOICES;
  dictation.state.wordingProvider = wordingProvider;
  return render(<LanguageTab />);
}

function toggle(name: string): HTMLButtonElement {
  return screen.getByTestId(`voice-language-${name}`) as HTMLButtonElement;
}

/** Opens a select and returns its options in list order. */
function options(testId: string): HTMLElement[] {
  fireEvent.click(screen.getByTestId(testId));
  const panel = screen.getByTestId(`${testId}-panel`);
  return [...panel.querySelectorAll<HTMLElement>('[role="option"]')];
}

function option(testId: string, text: string): HTMLElement {
  const found = options(testId).find((item) => item.textContent?.includes(text));
  if (!found) throw new Error(`no option "${text}" in ${testId}`);
  return found;
}

/** A promise the test settles by hand, for a request that is still on its way. */
function pending<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeAll(async () => {
  useI18nStore.setState({ ui: "en" });
  await loadLocaleChunk("voice");
});

beforeEach(() => {
  dictation.state.loading = false;
  dictation.state.error = null;
  dictation.state.saveSettings.mockReset().mockResolvedValue(undefined);
  dictation.state.refetch.mockReset().mockResolvedValue(undefined);
  dictation.test.mockReset().mockResolvedValue(SAMPLE);
  catalog.state.providers = PROVIDERS;
  catalog.state.refetch.mockReset().mockResolvedValue(undefined);
  fetchMock.mockClear();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("LanguageTab states", () => {
  it("shows the shape of the page while the settings load", () => {
    dictation.state.settings = null;
    dictation.state.loading = true;
    render(<LanguageTab />);

    expect(screen.getByTestId("voice-language-loading")).toBeTruthy();
    expect(screen.queryByTestId("voice-language-polish")).toBeNull();
    expect(screen.queryByTestId("voice-language-error")).toBeNull();
  });

  it("says that the settings could not be loaded and loads them again on request", async () => {
    dictation.state.settings = null;
    dictation.state.error = "HTTP 500";
    render(<LanguageTab />);

    const notice = screen.getByTestId("voice-language-error");
    expect(notice.textContent).toContain("Your language settings could not be loaded.");
    // The server's own error text is not put on the screen.
    expect(notice.textContent).not.toContain("HTTP 500");
    expect(screen.queryByTestId("voice-language-polish")).toBeNull();

    fireEvent.click(screen.getByText("Try again"));
    await waitFor(() => expect(dictation.state.refetch).toHaveBeenCalledTimes(1));
  });

  it("says when a change could not be saved, and stops saying it after the next one that was", async () => {
    dictation.state.saveSettings.mockRejectedValueOnce(new Error("HTTP 500"));
    show();

    fireEvent.click(toggle("polish"));
    await waitFor(() => expect(screen.getByTestId("voice-language-save-failed")).toBeTruthy());

    fireEvent.click(toggle("prompt-mode"));
    await waitFor(() => expect(screen.queryByTestId("voice-language-save-failed")).toBeNull());
  });

  it("holds every control while a change is being saved, and saves nothing twice", async () => {
    const write = pending<void>();
    dictation.state.saveSettings.mockReturnValueOnce(write.promise);
    show();

    fireEvent.click(toggle("polish"));
    await waitFor(() => expect(toggle("precision").disabled).toBe(true));
    expect(toggle("translate").disabled).toBe(true);
    expect((screen.getByTestId("voice-language-test") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(toggle("precision"));
    expect(dictation.state.saveSettings).toHaveBeenCalledTimes(1);

    write.resolve();
    await waitFor(() => expect(toggle("precision").disabled).toBe(false));
    expect(dictation.test).not.toHaveBeenCalled();
  });
});

describe("LanguageTab spoken language", () => {
  it("offers automatic detection and the served languages by name", () => {
    show();

    expect(screen.getByTestId("voice-language-spoken").textContent).toContain("Detect automatically");
    const labels = options("voice-language-spoken").map((item) => item.textContent ?? "");
    expect(labels.some((label) => label.includes("Detect automatically"))).toBe(true);
    expect(labels.some((label) => label.includes("German"))).toBe(true);
    expect(labels.some((label) => label.includes("Spanish"))).toBe(true);
  });

  it("saves the language that is picked", async () => {
    show();

    fireEvent.click(option("voice-language-spoken", "German"));
    await waitFor(() =>
      expect(dictation.state.saveSettings).toHaveBeenCalledWith({ language: "de" }),
    );
  });
});

describe("LanguageTab wording", () => {
  it.each([
    ["polish", { polish: false }, {}],
    ["precision", { polish_precision: true }, {}],
    ["conversation", { polish_conversation: true }, {}],
    ["prompt-mode", { prompt_mode: true }, {}],
    ["translate", { translate: true }, {}],
    ["translate", { translate: false }, { translate: true }],
  ] as const)("saves the %s switch as %o", async (name, patch, start) => {
    show(start);

    fireEvent.click(toggle(name));
    await waitFor(() => expect(dictation.state.saveSettings).toHaveBeenCalledWith(patch));
    expect(dictation.state.saveSettings).toHaveBeenCalledTimes(1);
  });

  it("reads a missing switch as its default: clean-up on, everything else off", () => {
    show({
      polish: undefined,
      polish_precision: undefined,
      polish_conversation: undefined,
      prompt_mode: undefined,
      translate: undefined,
    });

    expect(toggle("polish").getAttribute("aria-checked")).toBe("true");
    expect(toggle("precision").getAttribute("aria-checked")).toBe("false");
    expect(toggle("conversation").getAttribute("aria-checked")).toBe("false");
    expect(toggle("prompt-mode").getAttribute("aria-checked")).toBe("false");
    expect(toggle("translate").getAttribute("aria-checked")).toBe("false");
  });

  it("keeps the exact-words switch reachable while clean-up is off", () => {
    show({ polish: false });

    expect(toggle("precision")).toBeTruthy();
  });

  it("offers the conversation switch only while clean-up is on", () => {
    show({ polish: false, polish_precision: false });
    expect(screen.queryByTestId("voice-language-conversation")).toBeNull();
    cleanup();

    // The conversation pass extends clean-up: the backend skips it while
    // clean-up is off, so exact words alone must not offer a dead switch.
    show({ polish: false, polish_precision: true });
    expect(screen.queryByTestId("voice-language-conversation")).toBeNull();
    cleanup();

    show({ polish: true });
    expect(toggle("conversation")).toBeTruthy();
  });
});

describe("LanguageTab translation", () => {
  it("shows the target language only while translation is on", () => {
    show({ translate: false });
    expect(screen.queryByTestId("voice-language-translate-target")).toBeNull();
    cleanup();

    show({ translate: true, translate_target: "es" });
    expect(screen.getByTestId("voice-language-translate-target").textContent).toContain("Spanish");
  });

  it("offers the target languages by name and no automatic entry", () => {
    show({ translate: true });

    const labels = options("voice-language-translate-target").map((item) => item.textContent ?? "");
    expect(labels.some((label) => label.includes("German"))).toBe(true);
    expect(labels.some((label) => label.includes("Detect automatically"))).toBe(false);
  });

  it("saves the target language that is picked", async () => {
    show({ translate: true });

    fireEvent.click(option("voice-language-translate-target", "German"));
    await waitFor(() =>
      expect(dictation.state.saveSettings).toHaveBeenCalledWith({ translate_target: "de" }),
    );
  });

  it("says when the spoken and the written language are the same", () => {
    show({ translate: true, language: "en", translate_target: "en" });

    expect(screen.getByTestId("voice-language-same-language").textContent).toContain(
      "nothing is translated",
    );
  });

  it.each([
    ["detection is automatic", { translate: true, language: "auto", translate_target: "en" }],
    ["the two languages differ", { translate: true, language: "de", translate_target: "en" }],
    ["translation is off", { translate: false, language: "en", translate_target: "en" }],
  ] as const)("says nothing about the same language while %s", (_case, settings) => {
    show(settings);

    expect(screen.queryByTestId("voice-language-same-language")).toBeNull();
  });
});

describe("LanguageTab where the text goes", () => {
  it("names the company in the wording group while clean-up is on", () => {
    show({ polish: true });

    const sentence = screen.getByTestId("voice-language-sends-text");
    expect(sentence.textContent).toBe("Your text is sent to Groq.");
    expect(screen.getByTestId("voice-language-wording").contains(sentence)).toBe(true);
    expect(screen.queryByTestId("voice-language-translate-sends-text")).toBeNull();
  });

  it("names it for the coding prompt as well, once", () => {
    show({ polish: false, prompt_mode: true });

    expect(screen.getAllByTestId("voice-language-sends-text")).toHaveLength(1);
  });

  it("names it in the translation group while translation is on", () => {
    show({ polish: false, translate: true });

    const sentence = screen.getByTestId("voice-language-translate-sends-text");
    expect(sentence.textContent).toBe("Your text is sent to Groq for translation.");
    expect(screen.getByTestId("voice-language-translation").contains(sentence)).toBe(true);
    // Wording and the coding prompt are off, so their group says nothing.
    expect(screen.queryByTestId("voice-language-sends-text")).toBeNull();
  });

  it("says nothing while every option that uses the model is off", () => {
    show({ polish: false });

    expect(screen.queryByTestId("voice-language-sends-text")).toBeNull();
    expect(screen.queryByTestId("voice-language-translate-sends-text")).toBeNull();
  });

  it("says nothing when the model runs on this computer", () => {
    show({ polish: true, translate: true, polish_provider: "ollama" }, OLLAMA_READY);

    expect(screen.queryByTestId("voice-language-sends-text")).toBeNull();
    expect(screen.queryByTestId("voice-language-translate-sends-text")).toBeNull();
    // The select says where it runs instead.
    expect(screen.getByTestId("voice-language-model").textContent).toContain(
      "Ollama on this computer",
    );
  });

  it("says nothing when no model answers", () => {
    show({ polish: true, translate: true }, GROQ_NO_KEY);

    expect(screen.queryByTestId("voice-language-sends-text")).toBeNull();
    expect(screen.queryByTestId("voice-language-translate-sends-text")).toBeNull();
  });
});

describe("LanguageTab model", () => {
  it.each(Array.from({ length: 16 }, (_, mask) => mask))(
    "shows one model select and one test exactly when an option uses the model (combination %i)",
    (mask) => {
      show({
        polish: Boolean(mask & 1),
        polish_precision: Boolean(mask & 2),
        prompt_mode: Boolean(mask & 4),
        translate: Boolean(mask & 8),
      });

      expect(screen.queryAllByTestId("voice-language-model")).toHaveLength(mask ? 1 : 0);
      expect(screen.queryAllByTestId("voice-language-test")).toHaveLength(mask ? 1 : 0);
    },
  );

  it("lists the served models by name and marks the one on this computer", () => {
    show();

    const labels = options("voice-language-model").map((item) => item.textContent ?? "");
    expect(labels).toHaveLength(4);
    expect(labels[0]).toContain("Automatic");
    expect(labels[1]).toContain("Groq");
    expect(labels[2]).toContain("Google Gemini");
    expect(labels[3]).toContain("Ollama on this computer");
  });

  it("names the model the automatic choice lands on", () => {
    show({ polish_provider: "auto" }, GROQ_READY);

    expect(screen.getByTestId("voice-language-model").textContent).toContain("Automatic (Groq)");
  });

  it("names no model for the automatic choice when none answers", () => {
    show({ polish_provider: "auto" }, GROQ_NO_KEY);

    const text = screen.getByTestId("voice-language-model").textContent ?? "";
    expect(text).toContain("Automatic");
    expect(text).not.toContain("Groq");
  });

  it("saves the picked model and clears the stored version of the old one", async () => {
    show();

    fireEvent.click(option("voice-language-model", "Google Gemini"));
    await waitFor(() =>
      expect(dictation.state.saveSettings).toHaveBeenCalledWith({
        polish_provider: "gemini",
        polish_model: "",
      }),
    );
  });

  it("shows a stored model the served list does not hold as itself", () => {
    show({ polish_provider: "cerebras" });

    expect(screen.getByTestId("voice-language-model").textContent).toContain("Cerebras");
    expect(options("voice-language-model")).toHaveLength(5);
  });

  it("says that no model is set up and asks for the key that is missing", () => {
    show({ polish: false, translate: true }, GROQ_NO_KEY);

    expect(screen.getByTestId("voice-language-no-model").textContent).toContain(
      "No model is set up for this yet.",
    );
    const row = screen.getByTestId("voice-language-key");
    expect(row.textContent).toContain("Groq key");
    expect(screen.getByTestId("voice-language-key-field-input")).toBeTruthy();
  });

  it("asks for no key while a model answers or while nothing uses the model", () => {
    show({ polish: true }, GROQ_READY);
    expect(screen.queryByTestId("voice-language-no-model")).toBeNull();
    expect(screen.queryByTestId("voice-language-key")).toBeNull();
    cleanup();

    show({ polish: false }, GROQ_NO_KEY);
    expect(screen.queryByTestId("voice-language-no-model")).toBeNull();
    expect(screen.queryByTestId("voice-language-key")).toBeNull();
  });

  it("saves the missing key to its slot and reads both lists again", async () => {
    const heard: string[] = [];
    const listen = (event: Event) => heard.push((event as CustomEvent).detail.key);
    window.addEventListener("jarvis:secret-configured", listen);
    show({ polish: true }, GROQ_NO_KEY);

    fireEvent.change(screen.getByTestId("voice-language-key-field-input"), {
      target: { value: "gsk_example" },
    });
    fireEvent.click(screen.getByTestId("voice-language-key-field-save"));

    await waitFor(() => expect(dictation.state.refetch).toHaveBeenCalled());
    window.removeEventListener("jarvis:secret-configured", listen);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/secrets/groq_api_key");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ value: "gsk_example" });
    expect(catalog.state.refetch).toHaveBeenCalled();
    expect(heard).toEqual(["groq_api_key"]);
  });
});

describe("LanguageTab sample test", () => {
  it("shows the sample before and after", async () => {
    show();

    fireEvent.click(screen.getByTestId("voice-language-test"));
    await waitFor(() => expect(screen.getByTestId("voice-language-sample-result")).toBeTruthy());
    expect(screen.getByTestId("voice-language-sample-before").textContent).toBe(SAMPLE.sample_in);
    expect(screen.getByTestId("voice-language-sample-after").textContent).toBe(SAMPLE.sample_out);
  });

  it.each([
    ["unavailable", "No model answered."],
    ["timeout", "The model took too long."],
    ["local_only", "The text stayed on this computer and was not changed."],
    ["a_status_from_a_newer_server", "The text was not changed."],
  ])("says in one sentence why the sample was not changed (%s)", async (status, sentence) => {
    dictation.test.mockResolvedValue({ ...SAMPLE, status, sample_out: SAMPLE.sample_in });
    show();

    fireEvent.click(screen.getByTestId("voice-language-test"));
    await waitFor(() =>
      expect(screen.getByTestId("voice-language-sample-unchanged").textContent).toBe(sentence),
    );
    expect(screen.queryByTestId("voice-language-sample-result")).toBeNull();
  });

  it("says when the test could not run", async () => {
    dictation.test.mockRejectedValue(new Error("HTTP 500"));
    show();

    fireEvent.click(screen.getByTestId("voice-language-test"));
    await waitFor(() =>
      expect(screen.getByTestId("voice-language-sample-fault").textContent).toContain(
        "The test could not run.",
      ),
    );
  });

  it("drops a result that arrives after the settings changed on another screen", async () => {
    const run = pending<DictationPolishTest>();
    dictation.test.mockReturnValue(run.promise);
    const view = show();
    const button = screen.getByTestId("voice-language-test") as HTMLButtonElement;

    fireEvent.click(button);
    await waitFor(() => expect(button.disabled).toBe(true));
    // The hook hands over a new settings object, as it does after a change
    // made on the assistant's bar.
    dictation.state.settings = { ...SETTINGS, polish_precision: true };
    view.rerender(<LanguageTab />);
    run.resolve(SAMPLE);

    await waitFor(() => expect(button.disabled).toBe(false));
    expect(screen.queryByTestId("voice-language-sample-result")).toBeNull();
  });

  it("removes the result when a setting is changed here", async () => {
    show();
    fireEvent.click(screen.getByTestId("voice-language-test"));
    await waitFor(() => expect(screen.getByTestId("voice-language-sample-result")).toBeTruthy());

    fireEvent.click(toggle("precision"));
    await waitFor(() => expect(screen.queryByTestId("voice-language-sample-result")).toBeNull());
  });
});
