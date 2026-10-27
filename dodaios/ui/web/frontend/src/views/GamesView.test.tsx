import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GamesView, profileSummary } from "@/views/GamesView";
import { resolvePreset } from "@/components/games/PerformancePanel";
import type { GameDefinition, GamePreset, GameProfile, GameSetting, SystemInfo } from "@/lib/gamesApi";

const RESOLUTIONS = ["1920x1080", "2560x1440", "3840x2160", "5120x2880"];
const FPS = ["60", "144", "165", "240", "Unlimited"];
const HZ = ["60 Hz", "144 Hz", "165 Hz", "240 Hz"];

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
      id: "perf_display",
      settings: [
        { key: "perf_resolution", label: "Resolution", type: "select", options: RESOLUTIONS, default: "1920x1080" },
        { key: "perf_refresh_rate", label: "Refresh Rate", type: "select", options: HZ, default: null },
        { key: "perf_fps_cap", label: "FPS Limit", type: "select", options: FPS, default: null },
        { key: "perf_vsync", label: "V-Sync", type: "select", options: ["Off", "On", "Adaptive"], default: "Off" },
      ],
    },
    {
      id: "perf_rendering",
      settings: [
        { key: "perf_upscaler", label: "Upscaler", type: "select", options: ["Off", "DLSS", "FSR"], default: "Off" },
      ],
    },
    { id: "perf_detail", settings: [] },
    { id: "perf_raytracing", settings: [] },
    { id: "perf_effects", settings: [{ key: "perf_motion_blur", label: "Motion Blur", type: "toggle", default: false }] },
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
    { id: "video", settings: [] },
    { id: "gameplay", settings: [{ key: "hud", label: "Show HUD", type: "toggle", default: true }] },
  ],
  keybinds: [
    { id: "jump", action: "Jump", default: "Space" },
    { id: "crouch", action: "Crouch", default: "Left Ctrl" },
    { id: "sprint", action: "Sprint", default: "Left Shift" },
  ],
};

const PRESETS: GamePreset[] = [
  { id: "competitive", values: { perf_fps_cap: "Unlimited", perf_vsync: "Off", perf_upscaler: "Off" } },
  { id: "balanced", values: { perf_fps_cap: "monitor", perf_upscaler: "DLSS" } },
  { id: "quality", values: { perf_fps_cap: "monitor", perf_upscaler: "DLSS" } },
  { id: "epic", values: { perf_fps_cap: "Unlimited", perf_upscaler: "DLSS" } },
];

const SYSTEM: SystemInfo = {
  os: "Windows",
  cpu: "AMD Ryzen 7 7800X3D",
  ram_gb: 32,
  gpus: [{ name: "NVIDIA GeForce RTX 5070 Ti", vram_gb: 15.9 }],
  monitors: [
    { name: "Display 1", primary: true, width: 2560, height: 1440, refresh_hz: 60, max_width: 3840, max_height: 2160, max_refresh_hz: 165 },
  ],
  gpu_tier: "high",
  recommended_preset: "quality",
};

function blankProfile(): GameProfile {
  return { values: {}, keybinds: {}, alt_keybinds: {}, bind_modes: {}, custom_binds: [], dpi: null, notes: "", updated_at: null };
}

interface Call {
  method: string;
  url: string;
  body: Record<string, unknown> | undefined;
}

function stubServer() {
  const profile = blankProfile();
  const calls: Call[] = [];
  const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: unknown, init?: { method?: string; body?: string }) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      const body = init?.body ? (JSON.parse(init.body) as Record<string, unknown>) : undefined;
      calls.push({ method, url, body });
      if (url === "/api/games") {
        return json({
          dpi: 800,
          presets: PRESETS,
          games: [
            { id: "cs2", name: "Counter-Strike 2", publisher: "Valve", convertible: true, has_profile: false, updated_at: null },
          ],
        });
      }
      if (url === "/api/games/system") return json(SYSTEM);
      if (url === "/api/games/cs2" && method === "GET") {
        return json({ game: CS2, profile, default_dpi: 800 });
      }
      if (url === "/api/games/cs2/profile" && method === "PUT" && body) {
        for (const field of ["values", "keybinds", "alt_keybinds", "bind_modes"] as const) {
          Object.assign(profile[field], (body[field] as object | undefined) ?? {});
        }
        if (body.custom_binds) profile.custom_binds = body.custom_binds as GameProfile["custom_binds"];
        profile.updated_at = "2026-10-27T00:00:00+00:00";
        return json({ profile });
      }
      if (url === "/api/games/convert" && body) {
        return json({
          game_id: "cs2",
          sens: body.sens,
          dpi: 800,
          to_dpi: 800,
          cm_per_360: 25.97,
          edpi: Number(body.sens) * 800,
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

const putWith = (calls: Call[], body: Record<string, unknown>) =>
  calls.some((c) => c.method === "PUT" && c.url === "/api/games/cs2/profile" && JSON.stringify(c.body) === JSON.stringify(body));

async function openTab(name: RegExp) {
  await screen.findByTestId("game-panel-cs2");
  fireEvent.click(screen.getByRole("button", { name }));
}

async function pressAfterListening(events: Event[]) {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 5));
  });
  act(() => {
    for (const event of events) window.dispatchEvent(event);
  });
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

  it("opens on graphics & performance with this PC and the low-refresh tip", async () => {
    renderView();
    expect(await screen.findByTestId("games-performance")).toBeTruthy();
    const system = await screen.findByTestId("games-system");
    expect(within(system).getByText(/RTX 5070 Ti/)).toBeTruthy();
    expect(within(system).getByText(/2560 × 1440 · 60 Hz/)).toBeTruthy();
    expect(screen.getByTestId("games-refresh-tip").textContent).toMatch(/60.*165/);
  });

  it("applies a preset with the monitor's resolution and refresh rate", async () => {
    renderView();
    await screen.findByTestId("games-system");
    await waitFor(() => expect(screen.getByTestId("games-apply-recommended")).toBeTruthy());
    fireEvent.click(screen.getByTestId("games-preset-balanced"));
    await waitFor(() =>
      expect(
        putWith(calls, {
          values: {
            perf_fps_cap: "165",
            perf_upscaler: "DLSS",
            perf_resolution: "2560x1440",
            perf_refresh_rate: "165 Hz",
          },
        }),
      ).toBe(true),
    );
  });

  it("picks 5K from the resolution tiles and unlimited FPS from the chips", async () => {
    renderView();
    fireEvent.click(await screen.findByTestId("games-res-5120x2880"));
    await waitFor(() => expect(putWith(calls, { values: { perf_resolution: "5120x2880" } })).toBe(true));
    const fps = screen.getByRole("radiogroup", { name: /FPS limit/ });
    fireEvent.click(within(fps).getByRole("radio", { name: "Unlimited" }));
    await waitFor(() => expect(putWith(calls, { values: { perf_fps_cap: "Unlimited" } })).toBe(true));
  });

  it("saves a typed sensitivity and shows its cm/360", async () => {
    renderView();
    await openTab(/^Mouse$/);
    expect(within(screen.getByTestId("games-mouse-summary")).getByText(/41[.,]6 cm/)).toBeTruthy();
    const setting = screen.getByTestId("game-setting-sensitivity");
    const input = within(setting).getByRole("textbox", { name: "Mouse Sensitivity" });
    fireEvent.change(input, { target: { value: "2" } });
    fireEvent.blur(input);
    await waitFor(() => expect(putWith(calls, { values: { sensitivity: 2 } })).toBe(true));
  });

  it("binds a combination while a modifier is held", async () => {
    renderView();
    await openTab(/^Keybinds/);
    const row = await screen.findByTestId("game-keybind-jump");
    fireEvent.click(within(row).getByRole("button", { name: /^Jump:/ }));
    const key = new KeyboardEvent("keydown", { code: "KeyF", shiftKey: true, bubbles: true, cancelable: true });
    await pressAfterListening([
      new KeyboardEvent("keydown", { code: "ShiftLeft", shiftKey: true, bubbles: true, cancelable: true }),
      key,
    ]);
    expect(key.defaultPrevented).toBe(true);
    await waitFor(() => expect(putWith(calls, { keybinds: { jump: "Shift + F" } })).toBe(true));
  });

  it("binds a modifier on its own and a mouse button as the secondary bind", async () => {
    renderView();
    await openTab(/^Keybinds/);
    const row = await screen.findByTestId("game-keybind-crouch");
    fireEvent.click(within(row).getByRole("button", { name: /^Crouch:/ }));
    await pressAfterListening([
      new KeyboardEvent("keydown", { code: "AltLeft", altKey: true, bubbles: true, cancelable: true }),
      new KeyboardEvent("keyup", { code: "AltLeft", bubbles: true, cancelable: true }),
    ]);
    await waitFor(() => expect(putWith(calls, { keybinds: { crouch: "Left Alt" } })).toBe(true));

    fireEvent.click(within(row).getByRole("button", { name: /^Crouch \(Secondary\)/ }));
    await pressAfterListening([new MouseEvent("mousedown", { button: 4, bubbles: true, cancelable: true })]);
    await waitFor(() => expect(putWith(calls, { alt_keybinds: { crouch: "Mouse 5" } })).toBe(true));
  });

  it("switches sprint to toggle and adds a custom action", async () => {
    renderView();
    await openTab(/^Keybinds/);
    const sprint = await screen.findByTestId("game-keybind-sprint");
    fireEvent.click(within(sprint).getByRole("radio", { name: "Toggle" }));
    await waitFor(() => expect(putWith(calls, { bind_modes: { sprint: "toggle" } })).toBe(true));
    expect(within(screen.getByTestId("game-keybind-jump")).queryByRole("radio", { name: "Toggle" })).toBeNull();

    fireEvent.click(screen.getByTestId("games-add-custom"));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "PUT" && Array.isArray(c.body?.custom_binds) && c.body.custom_binds.length === 1)).toBe(true),
    );
  });

  it("lights up the keyboard keys that are bound", async () => {
    renderView();
    await openTab(/^Keybinds/);
    const keyboard = await screen.findByTestId("games-keyboard");
    expect(within(keyboard).getByTestId("games-key-Space").getAttribute("data-bound")).toBe("true");
    expect(within(keyboard).getByTestId("games-key-Q").getAttribute("data-bound")).toBe("false");
  });

  it("converts the sensitivity to other games and applies one", async () => {
    renderView();
    await openTab(/^Converter$/);
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

describe("resolvePreset", () => {
  const settings = Object.fromEntries(
    CS2.sections.flatMap((s) => s.settings).map((s) => [s.key, s]),
  ) as Record<string, GameSetting>;

  it("caps FPS at the highest option the monitor shows", () => {
    expect(resolvePreset(PRESETS[1], settings, SYSTEM).perf_fps_cap).toBe("165");
  });

  it("leaves the monitor-dependent values out when the PC is unknown", () => {
    expect(resolvePreset(PRESETS[1], settings, undefined)).toEqual({ perf_upscaler: "DLSS" });
  });
});

describe("profileSummary", () => {
  it("lists only what the player set, with combos, secondary binds and custom actions", () => {
    const text = profileSummary(
      CS2,
      {
        ...blankProfile(),
        values: { sensitivity: 1.1, hud: false },
        keybinds: { jump: "Shift + Mouse 4" },
        alt_keybinds: { jump: "Mouse Wheel Down" },
        bind_modes: { jump: "hold" },
        custom_binds: [{ id: "c1", action: "Buy AK", key: "F5", alt: "" }],
        dpi: 400,
      },
      400,
    );
    expect(text).toBe(
      [
        "Counter-Strike 2 — DPI 400",
        "",
        "[mouse]",
        "Mouse Sensitivity: 1.1",
        "",
        "[gameplay]",
        "Show HUD: Off",
        "",
        "[keybinds]",
        "Jump: Shift + Mouse 4 / Mouse Wheel Down (hold)",
        "",
        "[custom]",
        "Buy AK: F5",
      ].join("\n"),
    );
  });
});
