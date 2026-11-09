import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadLocaleChunk, setUiLanguage } from "@/i18n";
import { keyFromCode, keyLabel, readValue, addToPatch, type Catalogue } from "@/lib/verseSettingsApi";
import { VerseSettingsView } from "./VerseSettingsView";

const CATALOGUE: Catalogue = {
  schema: "verse.settings.catalogue/1",
  tabs: ["graphics", "audio", "keybinds", "interface"],
  preset_groups: ["graphics.shadows", "graphics.textures"],
  settings: [
    { id: "graphics.preset", tab: "graphics", section: "quality", kind: "choice", default: "auto", options: ["auto", "low", "medium", "high", "epic", "cinematic", "custom"] },
    { id: "graphics.shadows", tab: "graphics", section: "quality", kind: "choice", default: "high", options: ["low", "medium", "high", "epic", "cinematic"], tags: ["preset"], impact: "high" },
    { id: "graphics.textures", tab: "graphics", section: "quality", kind: "choice", default: "epic", options: ["low", "medium", "high", "epic", "cinematic"], tags: ["preset"] },
    { id: "graphics.motion_blur", tab: "graphics", section: "effects", kind: "toggle", default: false },
    { id: "audio.master", tab: "audio", section: "volume", kind: "range", default: 0.7, min: 0, max: 1, step: 0.01, unit: "%", path: "view.volume" },
    { id: "keybinds.jump", tab: "keybinds", section: "movement", kind: "key", default: "SpaceBar" },
    { id: "keybinds.crouch", tab: "keybinds", section: "movement", kind: "key", default: "LeftControl" },
    { id: "hud.crosshair_style", tab: "interface", section: "crosshair", kind: "choice", default: "cross_dot", options: ["cross", "dot", "cross_dot", "circle"] },
  ],
};

let patches: unknown[] = [];

beforeEach(async () => {
  patches = [];
  setUiLanguage("en");
  await loadLocaleChunk("verse_settings");
  let settings: Record<string, unknown> = { gore: "full", view: { volume: 0.7 }, game: { "graphics.preset": "auto", "graphics.shadows": "high", "graphics.textures": "epic", "graphics.motion_blur": false, "keybinds.jump": "SpaceBar", "keybinds.crouch": "LeftControl", "hud.crosshair_style": "cross_dot" } };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url === "/api/verse/settings/catalogue") return json(CATALOGUE);
      if (url === "/api/verse/status") return json({ status: "stopped" });
      if (url === "/api/verse/settings" && init?.method === "PATCH") {
        const patch = JSON.parse(String(init.body)) as Record<string, Record<string, unknown>>;
        patches.push(patch);
        settings = { ...settings, game: { ...(settings.game as object), ...(patch.game ?? {}) } };
        return json({ settings });
      }
      if (url === "/api/verse/settings") return json({ settings });
      return new Response("{}", { status: 404 });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function row(id: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(`[data-setting="${id}"]`);
  if (!el) throw new Error(`no row ${id}`);
  return el;
}

describe("VerseSettingsView", () => {
  it("shows the graphics tab first and a preset sets every quality group", async () => {
    render(<VerseSettingsView />);
    await screen.findByRole("group", { name: "Quality preset" });
    expect(screen.getByRole("tab", { name: "Graphics" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(row("graphics.preset"), { key: "ArrowRight" }); // auto -> low
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({ game: { "graphics.preset": "low", "graphics.shadows": "low", "graphics.textures": "low" } });
    expect(within(row("graphics.shadows")).getByText("Low")).toBeTruthy();
  });

  it("turns the preset to Custom when one group changes", async () => {
    render(<VerseSettingsView />);
    await screen.findByRole("group", { name: "Shadows" });
    fireEvent.keyDown(row("graphics.shadows"), { key: "ArrowLeft" }); // high -> medium
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({ game: { "graphics.shadows": "medium", "graphics.preset": "custom" } });
    expect(screen.getByText(/preset is now Custom/)).toBeTruthy();
  });

  it("swaps two actions when a key is already taken", async () => {
    render(<VerseSettingsView />);
    await screen.findByRole("group", { name: "Quality preset" });
    fireEvent.click(screen.getByRole("tab", { name: "Keybinds" }));
    await screen.findByRole("group", { name: "Jump / mantle" });
    fireEvent.keyDown(row("keybinds.jump"), { key: "Enter" });
    expect(within(row("keybinds.jump")).getByText("Press a key…")).toBeTruthy();
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { code: "ControlLeft", bubbles: true }));
    });
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({ game: { "keybinds.jump": "LeftControl", "keybinds.crouch": "SpaceBar" } });
  });

  it("finds settings across tabs with search", async () => {
    render(<VerseSettingsView />);
    await screen.findByRole("group", { name: "Quality preset" });
    fireEvent.change(screen.getByLabelText("Search settings"), { target: { value: "master" } });
    expect(await screen.findByRole("group", { name: "Master volume" })).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Quality preset" })).toBeNull();
  });
});

describe("verseSettingsApi helpers", () => {
  it("reads legacy paths and writes them back in settings.set shape", () => {
    const master = CATALOGUE.settings[4];
    expect(readValue({ view: { volume: 0.3 } }, master)).toBe(0.3);
    expect(addToPatch({}, master, 0.5)).toEqual({ view: { volume: 0.5 } });
  });

  it("maps browser key codes to Unreal key names", () => {
    expect(keyFromCode("KeyW")).toBe("W");
    expect(keyFromCode("Digit1")).toBe("One");
    expect(keyFromCode("Space")).toBe("SpaceBar");
    expect(keyFromCode("F10")).toBe("F10");
    expect(keyLabel("LeftMouseButton")).toBe("Mouse 1");
    expect(keyLabel("Two")).toBe("2");
  });
});
