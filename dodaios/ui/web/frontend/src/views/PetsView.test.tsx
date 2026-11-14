import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
 * A stand-in for the pets endpoints that keeps state, so a click followed by
 * the refetch it triggers reads back what the click wrote.
 */
function stubServer({ active = "gigi" }: { active?: string } = {}) {
  const state = {
    active,
    pets: [pet("gigi", "Gigi", true), pet("miso", "Miso", true), pet("u0123456789abcdef", "Pixel", false)],
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

      if (url === "/api/pets" && method === "GET") return json(state);
      if (url === "/api/pets/active") {
        state.active = String((body as { pet_id: string }).pet_id);
        return json({ ok: true });
      }
      if (url.startsWith("/api/pets/u") && method === "DELETE") {
        state.pets = state.pets.filter((p) => url !== `/api/pets/${p.id}`);
        return json({ ok: true });
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
  vi.unstubAllGlobals();
});

describe("PetsView", () => {
  it("lists every pet, with no None tile, and rings the active one", async () => {
    stubServer();
    renderView();

    const grid = await screen.findByTestId("pets-grid");
    await within(grid).findByText("Miso");
    const tiles = within(grid).getAllByRole("button");
    expect(tiles[0].getAttribute("data-testid")).toBe("pet-tile-gigi");
    expect(screen.queryByTestId("pet-tile-none")).toBeNull();
    expect(screen.getByTestId("pet-tile-gigi").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("pet-tile-miso").getAttribute("aria-pressed")).toBe("false");
    // Built-in copy comes from the locale, a custom pet keeps its own text.
    expect(within(grid).getByText("A cat: ears up while listening, curls up to sleep.")).toBeTruthy();
    expect(within(grid).getByText("Pixel from the API")).toBeTruthy();
  });

  it("carries a tile's whole description as its tooltip, since the tile shows two lines", async () => {
    stubServer();
    renderView();

    const grid = await screen.findByTestId("pets-grid");
    const text = await within(grid).findByText("A cat: ears up while listening, curls up to sleep.");
    expect(text.getAttribute("title")).toBe("A cat: ears up while listening, curls up to sleep.");
    expect(within(grid).getByText("Pixel from the API").getAttribute("title")).toBe("Pixel from the API");
  });

  it("explains pets as the app's own figures, not a desktop companion", async () => {
    stubServer();
    renderView();
    expect(await screen.findByText(/Your pet is how Jarvis looks inside the app\./)).toBeTruthy();
    expect(screen.queryByText(/desktop/i)).toBeNull();
  });

  it("offers nothing that belongs to a desktop pet", async () => {
    stubServer();
    renderView();
    await screen.findByTestId("pet-tile-miso");
    for (const id of ["pets-visibility", "pets-style-notice", "pets-use-pet", "pets-settings-panel", "pets-size", "pets-bubble", "pets-strip-always"]) {
      expect(screen.queryByTestId(id)).toBeNull();
    }
    expect(screen.queryByTestId("pet-strip-preview")).toBeNull();
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

  it("shows Gigi as the active pet when an old install still holds \"none\"", async () => {
    stubServer({ active: "none" });
    renderView();

    await screen.findByTestId("pet-tile-miso");
    expect(screen.getByTestId("pet-tile-gigi").getAttribute("aria-pressed")).toBe("true");
    expect(within(screen.getByTestId("pets-active-card")).getByText("Gigi")).toBeTruthy();
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
