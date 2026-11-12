/**
 * The merged voice section is named after the user, not after the product.
 *
 * Its row on the deck's rail resolves `nav.voice`, whose locale value carries the
 * `{name}` token, so the row reads "Nova Voice" on an install whose wake word is "Hey
 * Nova". Two ways that can silently break: the token stops being interpolated
 * (the row then literally says "{name} Voice"), or someone "fixes" the label by
 * hardcoding a name into it. Both are invisible to the type checker, and both
 * would put a trademarked name in front of every user.
 *
 * The row also fronts five sections at once — dictation, the dictionary, the
 * shortcuts, the language and the speech-to-text keys — so it must stay
 * highlighted for all of them.
 *
 * The label is only the entrance: the screens behind it have to hold the same
 * rule. The section's Language and API Keys tabs say nothing about the
 * assistant, so for them the rule is the negative half: no name is written
 * into what they render or into any string of the section's locale files.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import enJson from "@/i18n/locales/en.json";
import deJson from "@/i18n/locales/de.json";
import esJson from "@/i18n/locales/es.json";
import ptJson from "@/i18n/locales/pt.json";

// usePluginAttention polls /api/marketplace/plugins — mocked so the rail
// renders without a fetch.
vi.mock("@/hooks/usePluginAttention", () => ({
  usePluginAttention: () => ({ count: 0, names: [] }),
}));

// useVoiceMode fetches /api/settings/voice-mode — same reason.
vi.mock("@/hooks/useVoiceMode", () => ({
  useVoiceMode: () => ({
    mode: "pipeline",
    realtimeAvailable: false,
    statusKnown: true,
    transitioning: false,
    setMode: vi.fn(),
    isLoading: false,
    isSaving: false,
    activeProvider: null,
    activeProviderLabel: null,
    activeModel: null,
    sessionActive: false,
    activeSessionMode: null,
    activeSessionProvider: "",
    activeSessionModel: "",
  }),
}));

// Only the two data hooks are replaced; `sectionHealthForSubject` and the
// provider-switch helpers stay real, so the rendered markup is the production
// one and the assertions below describe what a user actually sees.
vi.mock("@/hooks/useProviders", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useProviders")>();
  // Stable identities: `useTierHealth` memoises on the health map, and a fresh
  // object literal per render would invalidate it on every pass.
  const noop = vi.fn();
  const emptyHealth = { health: {} };
  // Built on first call, not here: the fixture below is still in its temporal
  // dead zone while this factory runs.
  let providers: (typeof STT_PROVIDER)[] | null = null;
  return {
    ...actual,
    useProviders: () => ({
      providers: (providers ??= [STT_PROVIDER]),
      loading: false,
      error: null,
      refetch: noop,
      setActiveOptimistic: noop,
    }),
    useSectionHealth: () => emptyHealth,
  };
});

// The Language tab reads the dictation settings. Every option is on and a
// company's model answers, so each sentence the tab can show is on screen.
vi.mock("@/hooks/useDictation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useDictation")>();
  const state = {
    settings: {
      language: "en",
      polish: true,
      polish_provider: "auto",
      polish_model: "",
      polish_precision: true,
      polish_conversation: true,
      prompt_mode: true,
      translate: true,
      translate_target: "en",
    },
    choices: {
      language: ["auto", "de", "en"],
      polish_provider: ["auto", "test-model"],
      translate_target: ["de", "en"],
    },
    wordingProvider: {
      family: "test-model",
      label: "Test Model Service",
      spec_id: "test-model-polish",
      secret_key: "TEST_MODEL_API_KEY",
      needs_key: true,
      ready: true,
    },
    loading: false,
    error: null,
    saveSettings: vi.fn(),
    refetch: vi.fn(),
  };
  return { ...actual, useDictation: () => state };
});

import { DockRail } from "@/components/layout/DockRail";
import { ApiKeysTab } from "@/views/voice/ApiKeysTab";
import { LanguageTab } from "@/views/voice/LanguageTab";
import type { ProviderDescriptor } from "@/hooks/useProviders";
import { loadLocaleChunk } from "@/i18n";
import { useEventStore, type SectionId } from "@/store/events";

/**
 * A deliberately name-free speech-to-text provider: every occurrence of the
 * pinned brand in the rendered output then comes from the locale copy under
 * test, never from fixture data.
 */
const STT_PROVIDER: ProviderDescriptor = {
  id: "test-speech",
  label: "Test Speech Service",
  tier: "stt",
  auth_mode: "api_key",
  secret_keys: ["TEST_SPEECH_API_KEY"],
  secrets_set: { TEST_SPEECH_API_KEY: false },
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
};

/** An arbitrary brand — never the host's live wake-word configuration. */
const PINNED_BRAND = "Nova";

/**
 * Every product name that must never reach a user-visible string. Kept as
 * fragments so a compound ("Personal Jarvis", "Jarvis-Agent") is caught too.
 */
const FORBIDDEN_NAMES = ["jarvis"] as const;

/** Holds for a locale source value as well as for rendered output. */
function expectNoHardcodedBrand(text: string, where: string): void {
  for (const forbidden of FORBIDDEN_NAMES) {
    expect(
      text.toLowerCase().includes(forbidden),
      `${where} must not hardcode "${forbidden}": ${text}`,
    ).toBe(false);
  }
}

/**
 * Rendered output only: the raw locale value is SUPPOSED to carry `{name}`, so
 * this is the check that the substitution actually ran on the way to the DOM.
 */
function expectBrandInterpolated(text: string, where: string): void {
  expectNoHardcodedBrand(text, where);
  expect(text, `${where} must interpolate the {name} token`).not.toContain("{name}");
}

function renderRail() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <DockRail />
    </QueryClientProvider>,
  );
}

/** The product's own name is held to the same rule on the section's screens. */
const FORBIDDEN_ON_VOICE_SCREENS = [...FORBIDDEN_NAMES, "dodaios"] as const;

function expectNoNameOnVoiceScreen(text: string, where: string): void {
  for (const forbidden of FORBIDDEN_ON_VOICE_SCREENS) {
    expect(
      text.toLowerCase().includes(forbidden),
      `${where} must not hardcode "${forbidden}": ${text}`,
    ).toBe(false);
  }
  // A `{name}` left in the output is a token nobody filled in.
  expect(text, `${where} must not show a raw {name} token`).not.toContain("{name}");
}

/** Every section the one voice row fronts. */
const VOICE_SECTIONS: readonly SectionId[] = [
  "dictation",
  "dictionary",
  "voice-shortcuts",
  "voice-language",
  "voice-api-keys",
];

describe("voice section row brand", () => {
  beforeEach(() => {
    useEventStore.setState({
      voiceState: "idle",
      transcription: "",
      transcriptionFinal: true,
      connected: true,
      activeSection: "chats",
      assistantName: PINNED_BRAND,
    });
  });

  afterEach(() => {
    cleanup();
    useEventStore.setState({ assistantName: "Assistant" });
  });

  it("names the row after the configured assistant", () => {
    renderRail();

    // The rail shows icons; a row's name is its accessible name.
    const label = screen.getByTestId("nav-row-dictation").getAttribute("aria-label") ?? "";
    expect(label).toBe(`${PINNED_BRAND} Voice`);
    expectBrandInterpolated(label, "the voice row");
  });

  it("falls back to the neutral default when no name is configured", () => {
    useEventStore.setState({ assistantName: "Assistant" });
    renderRail();

    const label = screen.getByTestId("nav-row-dictation").getAttribute("aria-label") ?? "";
    expect(label).toBe("Assistant Voice");
    expectBrandInterpolated(label, "the neutral-default voice row");
  });

  it("collapses the former Dictation and Dictionary rows into one", () => {
    renderRail();

    expect(screen.queryByTestId("nav-row-dictionary")).toBeNull();
    expect(screen.getByTestId("nav-row-dictation")).toBeTruthy();
  });

  it("stays highlighted for every section it fronts", () => {
    for (const section of VOICE_SECTIONS) {
      useEventStore.setState({ activeSection: section });
      renderRail();
      // The active row carries the inset primary bar; asserting on the class
      // keeps this independent of the (translated) label.
      expect(
        screen.getByTestId("nav-row-dictation").className,
        `active section ${section} must highlight the voice row`,
      ).toContain("jarvis-nav-active");
      cleanup();
    }
  });
});

describe("voice tab brand", () => {
  // The tabs are painted only once the section's strings are resident; without
  // them the screens would show keys, and the checks below would pass on text
  // nobody ever sees.
  beforeAll(async () => {
    await loadLocaleChunk("voice");
  });

  beforeEach(() => {
    useEventStore.setState({ assistantName: PINNED_BRAND });
  });

  afterEach(() => {
    cleanup();
    useEventStore.setState({ assistantName: "Assistant" });
  });

  it("keeps every rendered word of the API Keys tab free of a hardcoded name", () => {
    const { container } = render(<ApiKeysTab />);

    const text = container.textContent ?? "";
    // Real strings are on screen, not keys.
    expect(text).toContain("Speech to text");
    expect(text).not.toContain("voiceui.");
    expectNoNameOnVoiceScreen(text, "the voice API Keys tab");
  });

  it("keeps every rendered word of the Language tab free of a hardcoded name", () => {
    const { container } = render(<LanguageTab />);

    const text = container.textContent ?? "";
    // The sentences about where the text goes name the model's company and
    // nothing else.
    expect(text).toContain("Your text is sent to Test Model Service.");
    expect(text).not.toContain("voiceui.");
    expectNoNameOnVoiceScreen(text, "the voice Language tab");
  });
});

/**
 * The same rule at its source: every string of the Voice section, in every
 * language and for every tab, including the ones no test above renders.
 */
describe("voice section locale files", () => {
  const files = import.meta.glob<{ default: unknown }>("@/i18n/locales/voice/*.json", {
    eager: true,
  });

  function strings(value: unknown): string[] {
    if (typeof value === "string") return [value];
    if (!value || typeof value !== "object") return [];
    return Object.values(value as Record<string, unknown>).flatMap(strings);
  }

  it("finds the section's files", () => {
    expect(Object.keys(files).length).toBeGreaterThan(0);
  });

  it.each(Object.keys(files))("%s names neither the assistant nor the product", (path) => {
    for (const value of strings(files[path].default)) {
      for (const forbidden of FORBIDDEN_ON_VOICE_SCREENS) {
        expect(
          value.toLowerCase().includes(forbidden),
          `${path} must not hardcode "${forbidden}": ${value}`,
        ).toBe(false);
      }
    }
  });
});

/**
 * The app's main API Keys screen still describes its speech tiers with the
 * assistant's name. These pin the values themselves, in every locale, so a
 * translation cannot reintroduce the literal name through a surface no test
 * renders.
 */
describe("voice locale copy", () => {
  const LOCALES = { en: enJson, de: deJson, es: esJson, pt: ptJson } as const;

  // The descriptions of the voice tiers on the main API Keys screen.
  const NAME_BEARING_KEYS = [
    "voice_engine_desc",
    "cat_tts_desc",
    "cat_stt_desc",
  ] as const;

  for (const [locale, bundle] of Object.entries(LOCALES)) {
    const strings = (bundle as { apikeys_view: Record<string, string> }).apikeys_view;

    for (const key of NAME_BEARING_KEYS) {
      it(`${locale}: apikeys_view.${key} refers to the assistant by token`, () => {
        const value = strings[key];
        expect(value, `apikeys_view.${key} is missing from ${locale}.json`).toBeTruthy();
        expect(value).toContain("{name}");
        expectNoHardcodedBrand(value, `${locale}.json apikeys_view.${key}`);
      });
    }
  }
});
