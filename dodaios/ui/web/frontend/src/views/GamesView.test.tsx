import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GamesView, profileSummary } from "@/views/GamesView";
import type { GameDefinition, GameProfile } from "@/lib/gamesApi";

const CS2: GameDefinition = {
  id: "cs2",
  name: "Counter-Strike 2",
  publisher: "Valve",
  yaw: 0.022,
  yaw_note: "",
  sens_key: "sensitivity",
  config_file: "Steam\\userdata\\cfg",
  sources: [],
  sections: [
    {
      id: "mouse",
      settings: [
        { key: "sensitivity", label: "Mouse Sensitivity", type: "slider", min: 0.01, max: 8, step: 0.01, default: 1.25 },
      ],
    },
    {
      id: "audio",
      settings: [{ key: "master", label: "Master Volume", type: "slider", min: 0, max: 100, step: 1, default: null }],
    },
    {
      id: "video",
      settings: [
        { key: "mode", label: "Display Mode", type: "select", options: ["Fullscreen", "Windowed"], default: "Fullscreen" },
      ],
    },
    { id: "gameplay", settings: [{ key: "hud", label: "Show HUD", type: "toggle", default: true }] },
  ],
  keybinds: [
    { id: "jump", action: "Jump", default: "Space" },
    { id: "crouch", action: "Crouch", default: "Left Ctrl" },
  ],
};

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stubServer() {
  const profile: GameProfile = { values: {}, keybinds: {}, dpi: null, notes: "", updated_at: null };
  const calls: Call[] = [];
  const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: unknown, init?: { method?: string; body?: string }) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      const body = init?.body ? JSON.parse(init.body) : undefined;
      calls.push({ method, url, body });
      if (url === "/api/games") {
        return json({
          dpi: 800,
          games: [
            { id: "cs2", name: "Counter-Strike 2", publisher: "Valve", convertible: true, has_profile: false, updated_at: null },
          ],
        });
      }
      if (url === "/api/games/cs2" && method === "GET") {
        return json({ game: CS2, profile, default_dpi: 800 });
      }
      if (url === "/api/games/cs2/profile" && method === "PUT") {
        Object.assign(profile.values, body.values ?? {});
        Object.assign(profile.keybinds, body.keybinds ?? {});
        profile.updated_at = "2026-10-27T00:00:00+00:00";
        return json({ profile });
      }
      if (url === "/api/games/convert") {
        return json({
          game_id: "cs2",
          sens: body.sens,
          dpi: 800,
          to_dpi: 800,
          cm_per_360: 25.97,
          edpi: body.sens * 800,
          results: [{ id: "valorant", name: "Valorant", sens_key: "aim_sens", sens: 0.3143, edpi: 251.4 }],
        });
      }
      return json({ detail: "unexpected" }, 404);
    }),
  );
  return calls;
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <GamesView />
    </QueryClientProvider>,
  );
}

describe("GamesView", () => {
  let calls: Call[];
  beforeEach(() => {
    calls = stubServer();
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("opens the first game with its mouse settings and the cm/360 of its default", async () => {
    renderView();
    expect(await screen.findByTestId("game-panel-cs2")).toBeTruthy();
    expect(screen.getByTestId("game-setting-sensitivity")).toBeTruthy();
    // 1.25 default @ 800 DPI with yaw 0.022 → 41.6 cm.
    expect(within(screen.getByTestId("games-mouse-summary")).getByText(/41[.,]6 cm/)).toBeTruthy();
  });

  it("saves a typed sensitivity when the field loses focus", async () => {
    renderView();
    const setting = await screen.findByTestId("game-setting-sensitivity");
    const input = within(setting).getByRole("textbox", { name: "Mouse Sensitivity" });
    fireEvent.change(input, { target: { value: "2" } });
    fireEvent.blur(input);
    await waitFor(() =>
      expect(calls.some((c) => c.method === "PUT" && JSON.stringify(c.body) === '{"values":{"sensitivity":2}}')).toBe(true),
    );
  });

  it("binds a key by pressing it and swallows the press", async () => {
    renderView();
    await screen.findByTestId("game-panel-cs2");
    fireEvent.click(screen.getByRole("button", { name: /^Keybinds/ }));
    const row = await screen.findByTestId("game-keybind-jump");
    fireEvent.click(within(row).getByRole("button", { name: /Jump/ }));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 5));
    });
    const event = new KeyboardEvent("keydown", { code: "KeyF", bubbles: true, cancelable: true });
    act(() => {
      window.dispatchEvent(event);
    });
    expect(event.defaultPrevented).toBe(true);
    await waitFor(() =>
      expect(calls.some((c) => c.method === "PUT" && JSON.stringify(c.body) === '{"keybinds":{"jump":"F"}}')).toBe(true),
    );
  });

  it("converts the sensitivity to other games and applies one", async () => {
    renderView();
    await screen.findByTestId("game-panel-cs2");
    fireEvent.click(screen.getByRole("button", { name: /^Converter$/ }));
    fireEvent.change(await screen.findByTestId("games-converter-sens"), { target: { value: "1" } });
    const table = await screen.findByTestId("games-converter-results");
    expect(within(table).getByText("Valorant")).toBeTruthy();
    fireEvent.click(within(table).getByRole("button"));
    await waitFor(() =>
      expect(
        calls.some((c) => c.url === "/api/games/valorant/profile" && JSON.stringify(c.body) === '{"values":{"aim_sens":0.314}}'),
      ).toBe(true),
    );
  });
});

describe("profileSummary", () => {
  it("lists only what the player set", () => {
    const text = profileSummary(
      CS2,
      { values: { sensitivity: 1.1, hud: false }, keybinds: { jump: "Mouse Wheel Down" }, dpi: 400, notes: "", updated_at: null },
      400,
    );
    expect(text).toBe(
      ["Counter-Strike 2 — DPI 400", "", "[mouse]", "Mouse Sensitivity: 1.1", "", "[gameplay]", "Show HUD: Off", "", "[keybinds]", "Jump: Mouse Wheel Down"].join("\n"),
    );
  });
});
