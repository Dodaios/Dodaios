/**
 * PhoneView: a pairing code shows as a QR with its LAN link; paired phones list
 * and can be removed; the WhatsApp switch writes the flag; a loopback-only
 * bind says why phones cannot connect yet.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PhoneView } from "@/views/PhoneView";

interface Call {
  url: string;
  method: string;
  body: unknown;
}

function installFetch(routes: Record<string, (body: unknown) => unknown>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    const handler = routes[`${method} ${url}`];
    if (!handler) throw new Error(`unexpected fetch ${method} ${url}`);
    return {
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => handler(body),
    } as Response;
  });
  (globalThis as unknown as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;
  return calls;
}

function status(overrides: Record<string, unknown> = {}) {
  return {
    devices: [],
    open_codes: 0,
    push_ready: true,
    listening: { bind_host: "0.0.0.0", loopback_only: false, port: 47821, https: false, lan_addresses: ["192.168.1.20"] },
    whatsapp: { enabled: false, running: false, owner_claimed: false, linked: false, bridge_url: "http://127.0.0.1:3737", missing: "bridge" },
    ...overrides,
  };
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PhoneView />
    </QueryClientProvider>,
  );
}

afterEach(() => cleanup());

describe("PhoneView", () => {
  it("mints a code and shows the QR with its LAN link", async () => {
    const calls = installFetch({
      "GET /api/mobile/status": () => status(),
      "POST /api/mobile/pair/code": () => ({
        code: "ABCDE23456",
        expires_in: 300,
        urls: ["http://192.168.1.20:47821/m/#pair=ABCDE23456"],
        listening: status().listening,
      }),
    });
    mount();
    const button = (await screen.findByTestId("phone-pair-button")) as HTMLButtonElement;
    // Pairing waits for the status (reachability) before it is offered.
    await waitFor(() => expect(button.disabled).toBe(false));
    expect(screen.queryByTestId("phone-not-reachable")).toBeNull();
    fireEvent.click(button);
    await screen.findByTestId("phone-pair-code");
    expect(screen.getByTestId("phone-pair-code-text").textContent).toBe("ABCDE 23456");
    expect(screen.getByTestId("phone-pair-code").querySelector("svg")).not.toBeNull();
    expect(screen.getByText(/192\.168\.1\.20:47821\/m\//)).toBeTruthy();
    expect(screen.getByTestId("phone-https-note")).toBeTruthy();
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/mobile/pair/code")).toBe(true);
  });

  it("explains a loopback-only bind and disables pairing", async () => {
    installFetch({
      "GET /api/mobile/status": () =>
        status({ listening: { bind_host: "127.0.0.1", loopback_only: true, port: 47821, https: false, lan_addresses: [] } }),
    });
    mount();
    await screen.findByTestId("phone-not-reachable");
    expect((screen.getByTestId("phone-pair-button") as HTMLButtonElement).disabled).toBe(true);
  });

  it("lists paired phones and removes one", async () => {
    let devices = [
      { id: "d1", name: "Kitchen phone", created_at: 1_700_000_000, last_seen_at: 1_700_000_500, push: true },
    ];
    const calls = installFetch({
      "GET /api/mobile/status": () => status({ devices }),
      "DELETE /api/mobile/devices/d1": () => {
        devices = [];
        return { removed: true };
      },
    });
    mount();
    await screen.findByTestId("phone-device-d1");
    expect(screen.getByText("Kitchen phone")).toBeTruthy();
    fireEvent.click(screen.getByTestId("phone-remove-d1"));
    await waitFor(() => expect(screen.queryByTestId("phone-device-d1")).toBeNull());
    expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/mobile/devices/d1")).toBe(true);
  });

  it("turns the WhatsApp channel on through its switch", async () => {
    let enabled = false;
    const calls = installFetch({
      "GET /api/mobile/status": () => status({ whatsapp: { ...status().whatsapp, enabled } }),
      "PUT /api/mobile/whatsapp": (body) => {
        enabled = Boolean((body as { enabled: boolean }).enabled);
        return { ...status().whatsapp, enabled };
      },
    });
    mount();
    const toggle = (await screen.findByTestId("phone-whatsapp-switch")) as HTMLButtonElement;
    await waitFor(() => expect(toggle.disabled).toBe(false));
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle.getAttribute("aria-checked")).toBe("true"));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ enabled: true });
  });
});
