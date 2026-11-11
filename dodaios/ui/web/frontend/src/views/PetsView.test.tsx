import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const motionPref = vi.hoisted(() => ({ reduced: false }));
vi.mock("framer-motion", async () => {
  const actual = await vi.importActual<typeof import("framer-motion")>("framer-motion");
  return { ...actual, useReducedMotion: () => motionPref.reduced };
});

import { PetsView } from "@/views/PetsView";
import { useEventStore } from "@/store/events";

const IDLE = { row: 0, frames: 4, fps: 4, loop: true };

function pet(id: string, name: string, builtin: boolean) {
  return {
    id,
    name,
    description: `${name} from the API`,
    builtin,
    frame_size: 48,
    animations: { idle: IDLE },
    sheet_url: `/api/pets/${id}/sheet.png`,
  };
}

interface Call {
  method: string;
  url: string;
  body: unknown;
}

/**
 * A stand-in for the pets, overlay-style and keybind endpoints that keeps
 * state, so a click followed by the refetch it triggers reads back what the
 * click wrote.
 */
function stubServer({ style = "pet" }: { style?: string } = {}) {
  const state = {
    active: "gigi",
    scale: 1,
    bubble: true,
    strip_always: false,
    visible: true,
    style,
    pets: [
      pet("gigi", "Gigi", true),
      pet("miso", "Miso", true),
      {
        ...pet("wisp-swarm", "Wisp Swarm", true),
        kind: "shader" as const,
        frame_size: 0,
        sheet_url: "",
        shader_url: "/api/pets/wisp-swarm/shader.frag",
        animations: {},
      },
      {
        ...pet("cube-cat", "Cube Cat", true),
        kind: "model" as const,
        frame_size: 0,
        sheet_url: "",
        animations: {},
        clips: { idle: "idle", listening: "look" },
      },
      {
        ...pet("jarvis-orb", "Dodaios Orb", true),
        kind: "scene" as const,
        frame_size: 0,
        sheet_url: "",
        animations: {},
        description: "A glowing orb with rings.",
      },
      pet("u0123456789abcdef", "Pixel", false),
    ],
  };
  const calls: Call[] = [];
  const json = (body: unknown, status = 200) => ({
    ok: status < 400,
    status,
    json: async () => body,
  });

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: unknown, init?: { method?: string; body?: unknown }) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      const body =
        typeof init?.body === "string" ? (JSON.parse(init.body) as Record<string, unknown>) : init?.body;
      calls.push({ method, url, body });

      if (url === "/api/pets" && method === "GET") {
        const { style: _style, ...rest } = state;
        return json(rest);
      }
      if (url === "/api/pets/active") {
        state.active = String((body as { pet_id: string }).pet_id);
        return json({ ok: true });
      }
      if (url === "/api/pets/settings") {
        Object.assign(state, body);
        return json({ ok: true });
      }
      if (url === "/api/pets/visibility") {
        state.visible = Boolean((body as { visible: boolean }).visible);
        return json({ ok: true });
      }
      if (url.startsWith("/api/pets/u") && method === "DELETE") {
        state.pets = state.pets.filter((p) => url !== `/api/pets/${p.id}`);
        return json({ ok: true });
      }
      if (url === "/api/settings/overlay-style" && method === "GET") {
        return json({ style: state.style, options: ["jarvis_bar", "mascot", "voice_orb", "pet", "none"] });
      }
      if (url === "/api/settings/overlay-style" && method === "PUT") {
        state.style = String((body as { style: string }).style);
        return json({
          ok: true,
          style: state.style,
          persisted: true,
          applied_live: false,
          restart_required: true,
        });
      }
      if (url === "/api/settings/keybinds") {
        return json({
          keybinds: { pet_toggle: "alt+win+p" },
          defaults: { pet_toggle: "alt+win+p" },
          suggestions: [],
          restart_required: false,
        });
      }
      return json({}, 404);
    }),
  );
  return { state, calls };
}

function renderView() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <PetsView />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useEventStore.setState({ toasts: [], assistantName: "Jarvis" });
});

afterEach(() => {
  cleanup();
  motionPref.reduced = false;
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("PetsView", () => {
  it("walks the hero through states and leaves a grid tile on idle", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    stubServer();
    renderView();

    const card = await screen.findByTestId("pets-active-card");
    const hero = within(card).getByTestId("pet-sprite");
    const tile = within(screen.getByTestId("pet-tile-gigi")).getByTestId("pet-sprite");
    expect(hero.getAttribute("data-state")).toBe("idle");
    expect(tile.getAttribute("data-state")).toBe("idle");
    expect(within(card).getByTestId("pets-state-label").textContent).toBe("Idle");

    await act(async () => {
      vi.advanceTimersByTime(2500);
    });
    expect(hero.getAttribute("data-state")).toBe("listening");
    expect(tile.getAttribute("data-state")).toBe("idle");
    expect(within(screen.getByTestId("pet-tile-miso")).getByTestId("pet-sprite").getAttribute("data-state")).toBe("idle");
    expect(within(card).getByTestId("pets-state-label").textContent).toBe("Listening");
  });

  it("keeps the hero on idle when motion is reduced", async () => {
    motionPref.reduced = true;
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    stubServer();
    renderView();
    const card = await screen.findByTestId("pets-active-card");
    await act(async () => {
      vi.advanceTimersByTime(2500);
    });
    expect(within(card).getByTestId("pet-sprite").getAttribute("data-state")).toBe("idle");
  });

  it("offers a backdrop slider for a shader and the orb, not a pixel pet", async () => {
    const { calls } = stubServer();
    renderView();
    await screen.findByTestId("pet-tile-gigi");
    expect(screen.queryByTestId("pets-backdrop")).toBeNull();

    fireEvent.click(screen.getByTestId("pet-tile-wisp-swarm"));
    const slider = await screen.findByTestId("pets-backdrop");
    expect((slider as HTMLInputElement).value).toBe("0");
    expect(screen.getByText("Backdrop")).toBeTruthy();
    const card = screen.getByTestId("pets-active-card");
    expect(within(card).getByTestId("shader-pet-preview").getAttribute("data-backdrop")).toBe("0");
    expect(
      within(screen.getByTestId("pet-tile-wisp-swarm")).getByTestId("shader-pet-preview").getAttribute("data-backdrop"),
    ).toBe("0");

    fireEvent.pointerDown(slider);
    fireEvent.change(slider, { target: { value: "0.4" } });
    expect(within(card).getByTestId("shader-pet-preview").getAttribute("data-backdrop")).toBe("0.4");
    expect(
      within(screen.getByTestId("pet-tile-wisp-swarm")).getByTestId("shader-pet-preview").getAttribute("data-backdrop"),
    ).toBe("0");
    fireEvent.pointerUp(window);

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: "PUT",
        url: "/api/pets/settings",
        body: { shader_backdrop: 0.4 },
      }),
    );
    await waitFor(() => expect((screen.getByTestId("pets-backdrop") as HTMLInputElement).value).toBe("0.4"));

    fireEvent.click(screen.getByTestId("pet-tile-jarvis-orb"));
    await waitFor(() =>
      expect(screen.getByTestId("pet-tile-jarvis-orb").getAttribute("aria-pressed")).toBe("true"),
    );
    expect((screen.getByTestId("pets-backdrop") as HTMLInputElement).value).toBe("0.4");
    expect(within(screen.getByTestId("pets-active-card")).getByTestId("jarvis-orb-preview").getAttribute("data-backdrop")).toBe("0.4");
    expect(
      within(screen.getByTestId("pet-tile-jarvis-orb")).getByTestId("jarvis-orb-preview").getAttribute("data-backdrop"),
    ).toBe("0");

    fireEvent.click(screen.getByTestId("pet-tile-gigi"));
    await waitFor(() => expect(screen.getByTestId("pet-tile-gigi").getAttribute("aria-pressed")).toBe("true"));
    expect(screen.queryByTestId("pets-backdrop")).toBeNull();
  });

  it("lists None first, then every pet, and rings the active one", async () => {
    stubServer();
    renderView();

    const grid = await screen.findByTestId("pets-grid");
    await within(grid).findByText("Miso");
    const tiles = within(grid).getAllByRole("button");
    expect(tiles[0].getAttribute("data-testid")).toBe("pet-tile-none");
    expect(screen.getByTestId("pet-tile-gigi").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("pet-tile-miso").getAttribute("aria-pressed")).toBe("false");
    // Built-in copy comes from the locale, a custom pet keeps its own text.
    expect(within(grid).getByText("A cat: ears up while listening, curls up to sleep.")).toBeTruthy();
    expect(screen.getByTestId("pets-filter-all").getAttribute("aria-checked")).toBe("true");
    expect(screen.queryByTestId("wisp-swarm-stage")).toBeNull();
    expect(screen.queryByTestId("cube-cat-stage")).toBeNull();
    expect(within(grid).getByText("Pixel from the API")).toBeTruthy();
  });

  it("names the shortcut in the explanation", async () => {
    stubServer();
    renderView();
    expect(await screen.findByText(/Press Alt \+ Win \+ P to hide or show it\./)).toBeTruthy();
  });

  it("selects the wisp wedding shader and the cube cat from the grid", async () => {
    const { calls } = stubServer();
    renderView();

    fireEvent.click(await screen.findByTestId("pet-tile-wisp-swarm"));
    await waitFor(() =>
      expect(calls).toContainEqual({
        method: "PUT",
        url: "/api/pets/active",
        body: { pet_id: "wisp-swarm" },
      }),
    );
    expect(screen.getAllByTestId("shader-pet-preview")).toHaveLength(2);
    expect(within(screen.getByTestId("pet-tile-wisp-swarm")).getByTestId("shader-pet-preview")).toBeTruthy();
    expect(screen.getByTestId("pets-shader-note")).toBeTruthy();
    expect(
      screen.getAllByText(
        "A midsummer cloud of wisps that leans in to listen, churns while it thinks, and flares gold when something goes right.",
      ).length,
    ).toBeGreaterThan(0);

    fireEvent.click(screen.getByTestId("pet-tile-cube-cat"));
    await waitFor(() =>
      expect(screen.getByTestId("pet-tile-cube-cat").getAttribute("aria-pressed")).toBe("true"),
    );
    const cats = screen.getAllByTestId("model-pet-preview");
    expect(cats).toHaveLength(2);
    expect(cats.every((cat) => cat.getAttribute("data-clip") === "idle")).toBe(true);
    expect(within(screen.getByTestId("pet-tile-cube-cat")).getByTestId("model-pet-preview")).toBeTruthy();
    expect(screen.getByTestId("pets-model-note")).toBeTruthy();
  });

  it("filters the grid by pixels, shaders and models", async () => {
    stubServer();
    renderView();
    await screen.findByTestId("pet-tile-gigi");

    fireEvent.click(screen.getByTestId("pets-filter-shader"));
    expect(screen.getByTestId("pet-tile-wisp-swarm")).toBeTruthy();
    expect(screen.queryByTestId("pet-tile-gigi")).toBeNull();
    expect(screen.queryByTestId("pet-tile-cube-cat")).toBeNull();
    expect(screen.queryByTestId("pet-tile-jarvis-orb")).toBeNull();

    fireEvent.click(screen.getByTestId("pets-filter-model"));
    expect(screen.getByTestId("pet-tile-cube-cat")).toBeTruthy();
    expect(screen.queryByTestId("pet-tile-wisp-swarm")).toBeNull();
    expect(screen.queryByTestId("pet-tile-jarvis-orb")).toBeNull();

    fireEvent.click(screen.getByTestId("pets-filter-pixel"));
    expect(screen.getByTestId("pet-tile-gigi")).toBeTruthy();
    expect(screen.queryByTestId("pet-tile-wisp-swarm")).toBeNull();
    expect(screen.queryByTestId("pet-tile-jarvis-orb")).toBeNull();
    expect(screen.queryByTestId("pet-tile-none")).toBeNull();

    fireEvent.click(screen.getByTestId("pets-filter-all"));
    expect(screen.getByTestId("pet-tile-jarvis-orb")).toBeTruthy();
    expect(within(screen.getByTestId("pet-tile-jarvis-orb")).getByTestId("jarvis-orb-preview")).toBeTruthy();
  });

  it("selects a pet with one click", async () => {
    const { calls } = stubServer();
    renderView();

    fireEvent.click(await screen.findByTestId("pet-tile-miso"));

    await waitFor(() =>
      expect(calls).toContainEqual({ method: "PUT", url: "/api/pets/active", body: { pet_id: "miso" } }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("pet-tile-miso").getAttribute("aria-pressed")).toBe("true"),
    );
  });

  it("offers only the control strip for None", async () => {
    const { calls } = stubServer();
    renderView();

    fireEvent.click(await screen.findByTestId("pet-tile-none"));

    await waitFor(() =>
      expect(calls).toContainEqual({ method: "PUT", url: "/api/pets/active", body: { pet_id: "none" } }),
    );
  });

  it("hides the pet from the header button", async () => {
    const { calls } = stubServer();
    renderView();

    const button = await screen.findByTestId("pets-visibility");
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    expect(button.textContent).toBe("Hide pet");
    fireEvent.click(button);

    await waitFor(() =>
      expect(calls).toContainEqual({ method: "POST", url: "/api/pets/visibility", body: { visible: false } }),
    );
    await waitFor(() => expect(button.textContent).toBe("Show pet"));
  });

  it("switches the display style to the pet and offers the restart", async () => {
    const { calls } = stubServer({ style: "jarvis_bar" });
    renderView();

    fireEvent.click(await screen.findByTestId("pets-use-pet"));

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: "PUT",
        url: "/api/settings/overlay-style",
        body: { style: "pet", persist: true },
      }),
    );
    expect(await screen.findByTestId("pets-restart-notice")).toBeTruthy();
    expect(screen.queryByTestId("pets-style-notice")).toBeNull();
  });

  it("turns the pet off from the header switch and keeps the chosen pet", async () => {
    const { calls } = stubServer();
    renderView();

    const toggle = await screen.findByTestId("pets-enabled");
    await waitFor(() => expect(toggle.getAttribute("aria-checked")).toBe("true"));
    fireEvent.click(toggle);

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: "PUT",
        url: "/api/settings/overlay-style",
        body: { style: "jarvis_bar", persist: true },
      }),
    );
    expect(calls.some((call) => call.url === "/api/pets/active")).toBe(false);
  });

  it("shows Pet on chat on by default and saves turning it off", async () => {
    const { calls } = stubServer();
    renderView();

    const chat = await screen.findByTestId("pets-chat");
    const desktop = await screen.findByTestId("pets-enabled");
    expect(desktop.compareDocumentPosition(chat) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(desktop.closest("label")?.className).toContain("justify-between");
    expect(chat.closest("label")?.className).toContain("justify-between");
    await waitFor(() => expect((chat as HTMLButtonElement).disabled).toBe(false));
    expect(chat.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(chat);

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: "PUT",
        url: "/api/pets/settings",
        body: { chat: false },
      }),
    );
    await waitFor(() => expect(chat.getAttribute("aria-checked")).toBe("false"));
  });

  it("turns the pet on from the header switch", async () => {
    const { calls } = stubServer({ style: "jarvis_bar" });
    renderView();

    const toggle = await screen.findByTestId("pets-enabled");
    await waitFor(() => expect((toggle as HTMLButtonElement).disabled).toBe(false));
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    expect(screen.queryByTestId("pets-visibility")).toBeNull();
    fireEvent.click(toggle);

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: "PUT",
        url: "/api/settings/overlay-style",
        body: { style: "pet", persist: true },
      }),
    );
  });

  it("shows no style notice while the pet is already the display style", async () => {
    stubServer();
    renderView();
    await screen.findByTestId("pet-tile-miso");
    expect(screen.queryByTestId("pets-style-notice")).toBeNull();
  });

  it("switches the status bubble off from the customize panel", async () => {
    const { calls } = stubServer();
    renderView();

    const customize = await screen.findByTestId("pets-customize");
    await waitFor(() => expect((customize as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(customize);
    fireEvent.click(await screen.findByTestId("pets-bubble"));

    await waitFor(() =>
      expect(calls).toContainEqual({ method: "PUT", url: "/api/pets/settings", body: { bubble: false } }),
    );
  });

  it("switches the always-on buttons on from the customize panel", async () => {
    const { calls } = stubServer();
    renderView();

    const customize = await screen.findByTestId("pets-customize");
    await waitFor(() => expect((customize as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(customize);
    fireEvent.click(await screen.findByTestId("pets-strip-always"));

    await waitFor(() =>
      expect(calls).toContainEqual({ method: "PUT", url: "/api/pets/settings", body: { strip_always: true } }),
    );
  });

  it("resizes the pet live while dragging and saves once on release", async () => {
    const { calls } = stubServer();
    renderView();

    const customize = await screen.findByTestId("pets-customize");
    await waitFor(() => expect((customize as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(customize);
    const slider = await screen.findByTestId("pets-size");
    expect((slider as HTMLInputElement).max).toBe("4");
    expect((slider as HTMLInputElement).value).toBe("1");
    fireEvent.pointerDown(slider);
    fireEvent.change(slider, { target: { value: "1.37" } });

    await waitFor(() =>
      expect(calls).toContainEqual({
        method: "PUT",
        url: "/api/pets/settings",
        body: { scale: 1.37, preview: true },
      }),
    );
    expect((slider as HTMLInputElement).disabled).toBe(false);
    expect(calls.filter((c) => c.method === "PUT" && !(c.body as { preview?: boolean }).preview)).toEqual([]);

    // Released away from the track: the window still sees it.
    fireEvent.pointerUp(window);
    await waitFor(() =>
      expect(calls).toContainEqual({ method: "PUT", url: "/api/pets/settings", body: { scale: 1.37 } }),
    );
  });

  it("deletes a custom pet after confirming, and never offers it for a built-in", async () => {
    const { calls } = stubServer();
    renderView();

    await screen.findByTestId("pet-tile-miso");
    expect(screen.queryByTestId("pet-delete-miso")).toBeNull();
    fireEvent.click(screen.getByTestId("pet-delete-u0123456789abcdef"));
    fireEvent.click(await screen.findByTestId("delete-pet-confirm"));

    await waitFor(() =>
      expect(calls).toContainEqual({ method: "DELETE", url: "/api/pets/u0123456789abcdef", body: undefined }),
    );
    await waitFor(() => expect(screen.queryByTestId("pet-tile-u0123456789abcdef")).toBeNull());
  });
});
