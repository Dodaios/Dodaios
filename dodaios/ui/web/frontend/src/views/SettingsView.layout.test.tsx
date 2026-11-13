import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The General settings page as the hub uses it: a slice shows exactly the
 * groups it names, in the order it names them, and nothing is folded away.
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
vi.mock("@/views/settings/VolumeGroup", () => ({ VolumeGroup: stub("volume") }));
vi.mock("@/views/settings/AudioDevicesGroup", () => ({ AudioDevicesGroup: stub("audio-devices") }));
vi.mock("@/views/settings/SystemPromptGroup", () => ({ SystemPromptGroup: stub("system-prompt") }));
vi.mock("@/views/settings/SelfBuildGroup", () => ({ SelfBuildGroup: stub("self-build") }));
vi.mock("@/views/settings/ApprovalModesGroup", () => ({ ApprovalModesGroup: stub("approvals") }));

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

describe("SettingsView slices", () => {
  it("shows only the groups a slice names, under the slice's title", () => {
    render(wrap(<SettingsView sections={["voice", "wake-word"]} title="Voice & wake word" />));
    expect(sectionIds()).toEqual(["voice", "wake-word"]);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Voice & wake word");
    expect(screen.queryByTestId("settings-more-options")).toBeNull();
  });

  it("reads a slice in the order its entry names the groups", () => {
    render(wrap(<SettingsView sections={["languages", "app", "overlay-taskbar", "music"]} />));
    // Music follows Bar & Overlay here although the page defines it first.
    expect(sectionIds()).toEqual(["languages", "app", "overlay-taskbar", "music"]);
    expect(screen.queryByTestId("settings-more-options-toggle")).toBeNull();
  });

  it("leaves the voice engine to the API Keys page", () => {
    render(wrap(<SettingsView sections={["voice"]} />));
    expect(screen.getByTestId("group-volume")).toBeTruthy();
    expect(screen.getByTestId("group-audio-devices")).toBeTruthy();
    expect(document.getElementById("settings-realtime-voice")).toBeNull();
  });

  it("scrolls to a search hit inside the slice", async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scrollIntoView });
    const handled = vi.fn();
    try {
      render(wrap(
        <SettingsView
          sections={["languages", "app", "overlay-taskbar", "music"]}
          searchTarget="music"
          onSearchTargetHandled={handled}
        />,
      ));
      await waitFor(() => expect(handled).toHaveBeenCalledOnce());
      expect(sectionIds()).toContain("music");
      expect(scrollIntoView).toHaveBeenCalled();
    } finally {
      delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  });
});
