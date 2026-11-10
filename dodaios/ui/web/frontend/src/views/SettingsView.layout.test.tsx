import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The General settings page as the hub's five groups use it: a slice shows
 * exactly the groups it names, and the whole page folds the rarely changed
 * groups under "More options" — which a search hit inside them opens.
 */

function stub(name: string) {
  return () => <div data-testid={`group-${name}`} />;
}

vi.mock("@/views/settings/OverlayTaskbarGroup", () => ({ OverlayTaskbarGroup: stub("overlay-taskbar") }));
vi.mock("@/views/settings/LanguagesGroup", () => ({ LanguagesGroup: stub("languages") }));
vi.mock("@/views/settings/MusicGroup", () => ({ MusicGroup: stub("music") }));
vi.mock("@/views/settings/AppSettingsGroup", () => ({
  AppSettingsGroup: ({ children }: { children?: React.ReactNode }) => <div data-testid="group-app">{children}</div>,
}));
vi.mock("@/views/settings/RealtimeVoiceGroup", () => ({ RealtimeVoiceGroup: stub("realtime-voice") }));
vi.mock("@/views/settings/VolumeGroup", () => ({ VolumeGroup: stub("volume") }));
vi.mock("@/views/settings/AudioDevicesGroup", () => ({ AudioDevicesGroup: stub("audio-devices") }));
vi.mock("@/views/settings/SystemPromptGroup", () => ({ SystemPromptGroup: stub("system-prompt") }));
vi.mock("@/views/settings/SelfBuildGroup", () => ({ SelfBuildGroup: stub("self-build") }));
vi.mock("@/views/settings/ApprovalModesGroup", () => ({ ApprovalModesGroup: stub("approvals") }));
vi.mock("@/components/verseHost/VerseSettingsGroup", () => ({ VerseSettingsGroup: stub("verse") }));

import { SettingsView } from "@/views/SettingsView";

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({}),
    text: async () => "{}",
  }) as Response));
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const sectionIds = () =>
  [...document.querySelectorAll("[data-settings-section]")].map((node) => node.getAttribute("data-settings-section"));

describe("SettingsView slices and folds", () => {
  it("shows only the groups a slice names, under the slice's title", () => {
    render(wrap(<SettingsView sections={["voice", "wake-word"]} title="Voice & wake word" />));
    expect(sectionIds()).toEqual(["voice", "wake-word"]);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Voice & wake word");
    expect(screen.queryByTestId("settings-more-options")).toBeNull();
  });

  it("folds music, overlay and game options on the whole page", () => {
    render(wrap(<SettingsView />));
    expect(sectionIds()).not.toContain("music");
    expect(sectionIds()).not.toContain("overlay-taskbar");
    expect(sectionIds()).not.toContain("verse");
    // The first-run guide's anchor stays on the page, unfolded.
    expect(sectionIds()).toContain("wake-word");

    const toggle = screen.getByTestId("settings-more-options-toggle");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(sectionIds()).toEqual(expect.arrayContaining(["music", "overlay-taskbar", "verse"]));
  });

  it("opens the fold for a search hit inside it and scrolls there", async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scrollIntoView });
    const handled = vi.fn();
    try {
      render(wrap(<SettingsView searchTarget="music" onSearchTargetHandled={handled} />));
      await waitFor(() => expect(handled).toHaveBeenCalledOnce());
      expect(sectionIds()).toContain("music");
      expect(scrollIntoView).toHaveBeenCalled();
    } finally {
      delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  });
});
