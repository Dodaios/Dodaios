import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { mockState } = vi.hoisted(() => ({
  mockState: {
    activeSection: "dictation" as string,
    setActiveSection: vi.fn(),
    chunkReady: true,
  },
}));

vi.mock("@/store/events", () => ({
  useEventStore: (selector: (s: typeof mockState) => unknown) => selector(mockState),
}));

vi.mock("@/components/layout/tiling/tileSection", () => ({
  useStageSection: () => mockState.activeSection,
}));

vi.mock("@/i18n", () => ({
  // Identity translator: a label is its key, so assertions match exactly.
  useT: () => (key: string) => key,
  useLocaleChunk: () => mockState.chunkReady,
}));

// ViewHeader lives in ChatsView, which pulls in the whole chat surface.
vi.mock("@/views/ChatsView", () => ({
  ViewHeader: ({ title, subtitle }: { title: string; subtitle?: string }) => (
    <header data-testid="view-header">
      <span data-testid="view-header-title">{title}</span>
      <span data-testid="view-header-subtitle">{subtitle}</span>
    </header>
  ),
}));

function stub(name: string) {
  return () => <div data-testid={name}>{name}</div>;
}

vi.mock("@/views/voice/DictationTab", () => ({ DictationTab: stub("DICTATION") }));
vi.mock("@/views/voice/DictionaryTab", () => ({ DictionaryTab: stub("DICTIONARY") }));
vi.mock("@/views/voice/ShortcutsTab", () => ({ ShortcutsTab: stub("SHORTCUTS") }));
vi.mock("@/views/voice/LanguageTab", () => ({ LanguageTab: stub("LANGUAGE") }));
vi.mock("@/views/voice/ApiKeysTab", () => ({ ApiKeysTab: stub("API_KEYS") }));

import { VoiceHubView } from "@/views/VoiceHubView";

const TAB_LABELS = [
  "nav.dictation",
  "nav.dictionary",
  "nav.voice_shortcuts",
  "nav.voice_language",
  "nav.voice_api_keys",
];

beforeEach(() => {
  mockState.activeSection = "dictation";
  mockState.setActiveSection = vi.fn();
  mockState.chunkReady = true;
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("VoiceHubView", () => {
  it("opens on Dictation and shows all five tabs", () => {
    render(<VoiceHubView />);

    expect(screen.getByTestId("DICTATION")).toBeTruthy();
    expect(screen.queryByTestId("DICTIONARY")).toBeNull();
    expect(
      screen.getByRole("button", { name: "nav.dictation" }).getAttribute("aria-current"),
    ).toBe("page");
    for (const label of TAB_LABELS) {
      expect(screen.getByRole("button", { name: label })).toBeTruthy();
    }
  });

  it.each([
    ["dictation", "DICTATION"],
    ["dictionary", "DICTIONARY"],
    ["voice-shortcuts", "SHORTCUTS"],
    ["voice-language", "LANGUAGE"],
    ["voice-api-keys", "API_KEYS"],
  ])("shows the tab of section %s", (section, testId) => {
    mockState.activeSection = section;
    render(<VoiceHubView />);

    expect(screen.getByTestId("voice-tab-content").children).toHaveLength(1);
    expect(screen.getByTestId(testId)).toBeTruthy();
  });

  it("selects a section when its tab is clicked", () => {
    render(<VoiceHubView />);

    fireEvent.click(screen.getByRole("button", { name: "nav.voice_shortcuts" }));
    expect(mockState.setActiveSection).toHaveBeenCalledWith("voice-shortcuts");
  });

  it("falls back to Dictation for a section id it does not own", () => {
    mockState.activeSection = "chats";
    render(<VoiceHubView />);

    expect(screen.getByTestId("DICTATION")).toBeTruthy();
  });

  it("has one header, titled with the assistant's name, and no subtitle", () => {
    render(<VoiceHubView />);

    expect(screen.getAllByTestId("view-header")).toHaveLength(1);
    expect(screen.getByTestId("view-header-title").textContent).toBe("nav.voice");
    expect(screen.getByTestId("view-header-subtitle").textContent).toBe("");
  });

  it("paints no tab before the section's strings are loaded", () => {
    mockState.chunkReady = false;
    render(<VoiceHubView />);

    expect(screen.getByTestId("voice-tab-content").children).toHaveLength(0);
    for (const label of TAB_LABELS) {
      expect(screen.getByRole("button", { name: label })).toBeTruthy();
    }
  });
});
