import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Design } from "@/lib/designs/designsApi";
import { useDesignsStore } from "@/store/designs";
import { useEventStore } from "@/store/events";
import { DesignsView } from "@/views/DesignsView";

function design(id: string, name: string, builtin: boolean): Design {
  return {
    id,
    name,
    description: `${name} from the API`,
    builtin,
    dark: { background: "#0b1020", foreground: "#e8ecf8", accent: "#7c9cff" },
    light: { background: "#f6f7fb", foreground: "#141a2e", accent: "#3a5bd9" },
    background: { style: "glow", colors: ["#1d3b8f"], speed: "slow", strength: 0.5 },
    created_at: 1,
    updated_at: 1,
  };
}

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stubServer() {
  const server = {
    active: "standard",
    designs: [design("deep-sea", "Deep Sea", true), design("midnight", "Midnight", false)],
  };
  const calls: Call[] = [];
  const snapshot = () => ({ active: server.active, standard_id: "standard", designs: server.designs });
  const json = (body: unknown, status = 200) =>
    Promise.resolve(new Response(JSON.stringify(body), { status }));
  vi.stubGlobal(
    "fetch",
    vi.fn((input: unknown, init?: { method?: string; body?: string }) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      const body = init?.body ? JSON.parse(init.body) : undefined;
      calls.push({ method, url, body });
      if (url === "/api/designs" && method === "GET") return json(snapshot());
      if (url === "/api/designs/active") {
        server.active = body.id;
        return json({ ok: true, state: snapshot() });
      }
      if (url === "/api/designs/reset") {
        server.active = "standard";
        return json({ ok: true, state: snapshot() });
      }
      if (url === "/api/designs" && method === "POST") {
        server.designs = server.designs.map((d) => (d.id === body.id ? { ...d, name: body.name } : d));
        return json({ ok: true, state: snapshot() });
      }
      if (url.startsWith("/api/designs/") && method === "DELETE") {
        const id = decodeURIComponent(url.split("/").pop() ?? "");
        server.designs = server.designs.filter((d) => d.id !== id);
        if (server.active === id) server.active = "standard";
        return json({ ok: true, state: snapshot() });
      }
      if (url === "/api/agent-chat/lead") return json({ session_id: "lead-1" });
      if (url === "/api/agent-chat/sessions/lead-1/messages") return json({ ok: true });
      return json({}, 404);
    }),
  );
  return { server, calls };
}

beforeEach(() => {
  window.localStorage.clear();
  useEventStore.setState({ toasts: [], assistantName: "Dodaios" });
  useDesignsStore.setState({ loaded: false, active: "standard", designs: [], current: null });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  document.documentElement.classList.remove("dodaios-design");
  document.getElementById("dodaios-design")?.remove();
});

describe("DesignsView", () => {
  it("lists Standard first, the person's designs, then the examples", async () => {
    stubServer();
    render(<DesignsView />);
    const own = await screen.findByTestId("designs-own");
    await within(own).findByTestId("design-tile-midnight");
    expect(within(own).getByTestId("design-tile-standard").getAttribute("data-active")).toBe("true");
    expect(within(own).queryByTestId("design-tile-deep-sea")).toBeNull();
    expect(within(screen.getByTestId("designs-examples")).getByTestId("design-tile-deep-sea")).toBeTruthy();
    expect((screen.getByTestId("designs-reset") as HTMLButtonElement).disabled).toBe(true);
  });

  it("switches to a design with one click and back to standard from the header", async () => {
    const { calls } = stubServer();
    render(<DesignsView />);
    const tile = await screen.findByTestId("design-tile-midnight");
    fireEvent.click(within(tile).getByRole("button", { pressed: false }));
    await waitFor(() => expect(screen.getByTestId("design-tile-midnight").getAttribute("data-active")).toBe("true"));
    expect(document.documentElement.classList.contains("dodaios-design")).toBe(true);
    expect(calls.some((c) => c.url === "/api/designs/active" && (c.body as { id: string }).id === "midnight")).toBe(true);

    const reset = screen.getByTestId("designs-reset") as HTMLButtonElement;
    expect(reset.disabled).toBe(false);
    fireEvent.click(reset);
    await waitFor(() => expect(screen.getByTestId("design-tile-standard").getAttribute("data-active")).toBe("true"));
    expect(document.documentElement.classList.contains("dodaios-design")).toBe(false);
  });

  it("deletes one of the person's designs after a confirmation; examples have no delete", async () => {
    const { calls } = stubServer();
    render(<DesignsView />);
    await screen.findByTestId("design-tile-midnight");
    expect(screen.queryByTestId("design-delete-deep-sea")).toBeNull();
    fireEvent.click(screen.getByTestId("design-delete-midnight"));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    fireEvent.click(screen.getByTestId("design-delete-confirm-midnight"));
    await waitFor(() => expect(screen.queryByTestId("design-tile-midnight")).toBeNull());
    expect(screen.getByTestId("designs-own-empty")).toBeTruthy();
  });

  it("sends the description to the assistant as the person's own message and waits for the design", async () => {
    const { calls, server } = stubServer();
    render(<DesignsView />);
    await screen.findByTestId("design-tile-midnight");
    fireEvent.change(screen.getByTestId("designs-ask-input"), { target: { value: "dark blue with a glow" } });
    fireEvent.click(screen.getByTestId("designs-ask-send"));
    await screen.findByTestId("designs-pending");
    const sent = calls.find((c) => c.url === "/api/agent-chat/sessions/lead-1/messages");
    expect(JSON.stringify(sent?.body)).toContain("dark blue with a glow");

    // The design the assistant made arrives (UiDesignChanged -> load).
    server.designs = [...server.designs, design("dark-blue-glow", "Dark Blue Glow", false)];
    server.active = "dark-blue-glow";
    await act(async () => {
      await useDesignsStore.getState().load();
    });
    await waitFor(() => expect(screen.queryByTestId("designs-pending")).toBeNull());
    expect(screen.getByTestId("design-tile-dark-blue-glow").getAttribute("data-active")).toBe("true");
  });
});
