/**
 * The semantic search switch: it shows what the server holds, says which step
 * is running, and never pretends a change that was not saved.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { WikiSemanticSearchStatus } from "@/lib/wikiApi";
import { SemanticSearchRow } from "@/views/profile/SemanticSearchRow";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const OFF: WikiSemanticSearchStatus = {
  enabled: false,
  available: true,
  state: "off",
  message: "",
  progress: null,
  model_present: false,
  download_bytes: 135_391_039,
  pages: 0,
  passages: 0,
};

interface Reply {
  status?: number;
  body?: unknown;
}

function installBackend(get: Reply, put: Reply = {}) {
  const calls: { method: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    expect(String(input)).toBe("/api/wiki/semantic-search");
    const method = init?.method ?? "GET";
    calls.push({ method, body: init?.body ? JSON.parse(String(init.body)) : null });
    const { status = 200, body = null } = method === "PUT" ? put : get;
    return {
      ok: status >= 200 && status < 300,
      status,
      statusText: status === 200 ? "OK" : "Error",
      json: async () => body,
    } as Response;
  });
  (globalThis as unknown as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;
  return calls;
}

function renderRow() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <SemanticSearchRow />
    </QueryClientProvider>,
  );
}

describe("SemanticSearchRow", () => {
  it("is absent when the backend has no such setting", async () => {
    const calls = installBackend({ status: 404 });
    const { container } = renderRow();
    await waitFor(() => expect(calls.length).toBe(1));
    expect(container.querySelector('[data-testid="semantic-search-row"]')).toBeNull();
  });

  it("is off at first and says what switching it on costs", async () => {
    installBackend({ body: OFF });
    renderRow();
    const status = await screen.findByTestId("semantic-search-status");
    expect(status.textContent).toContain("135 MB");
    expect(status.textContent).toContain("only on this computer");
    expect(screen.getByTestId("semantic-search-switch").getAttribute("aria-checked")).toBe("false");
  });

  it("switches on through the server and shows the download", async () => {
    const downloading = { ...OFF, enabled: true, state: "downloading", progress: 0.4 };
    const calls = installBackend({ body: OFF }, { body: downloading });
    renderRow();
    fireEvent.click(await screen.findByTestId("semantic-search-switch"));

    await waitFor(() =>
      expect(screen.getByTestId("semantic-search-status").textContent).toContain("40%"),
    );
    expect(calls.find((call) => call.method === "PUT")?.body).toEqual({ enabled: true });
    expect(screen.getByTestId("semantic-search-switch").getAttribute("aria-checked")).toBe("true");
  });

  it("reports how many pages are covered once it is ready", async () => {
    installBackend({ body: { ...OFF, enabled: true, state: "ready", progress: 1, pages: 70 } });
    renderRow();
    const status = await screen.findByTestId("semantic-search-status");
    expect(status.textContent).toContain("70 pages");
  });

  it("names the encoding step while the wiki is being read", async () => {
    installBackend({ body: { ...OFF, enabled: true, state: "indexing", progress: 0.25 } });
    renderRow();
    const status = await screen.findByTestId("semantic-search-status");
    expect(status.textContent).toContain("Reading your wiki pages");
    expect(status.textContent).toContain("25%");
  });

  it("cannot be switched on where the system cannot run it", async () => {
    installBackend({ body: { ...OFF, available: false } });
    renderRow();
    const status = await screen.findByTestId("semantic-search-status");
    expect(status.textContent).toContain("Not available on this system");
    expect(screen.getByTestId("semantic-search-switch").hasAttribute("disabled")).toBe(true);
  });

  it("offers a retry after a failed setup", async () => {
    installBackend({ body: { ...OFF, enabled: true, state: "error", message: "boom" } });
    renderRow();
    const status = await screen.findByTestId("semantic-search-status");
    expect(status.textContent).toContain("could not be set up");
    expect(screen.getByTestId("semantic-search-switch").hasAttribute("disabled")).toBe(false);
  });

  it("stays off and says so when the change could not be saved", async () => {
    installBackend({ body: OFF }, { status: 500 });
    renderRow();
    fireEvent.click(await screen.findByTestId("semantic-search-switch"));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("could not be saved");
    expect(screen.getByTestId("semantic-search-switch").getAttribute("aria-checked")).toBe("false");
  });

  it("keeps the last state on screen when one poll fails", async () => {
    const downloading = { ...OFF, enabled: true, state: "downloading", progress: 0.4 };
    let requests = 0;
    const fetchMock = vi.fn(async () => {
      requests += 1;
      if (requests > 1) throw new Error("network blip");
      return { ok: true, status: 200, statusText: "OK", json: async () => downloading } as Response;
    });
    (globalThis as unknown as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;
    renderRow();
    await screen.findByTestId("semantic-search-status");

    await waitFor(() => expect(requests).toBeGreaterThan(1), { timeout: 3000 });
    expect(screen.getByTestId("semantic-search-status").textContent).toContain("40%");
  });

  it("keeps asking while it is switched on but not picked up yet", async () => {
    const pending = { ...OFF, enabled: true, state: "off" };
    const ready = { ...OFF, enabled: true, state: "ready", progress: 1, pages: 3 };
    let requests = 0;
    const fetchMock = vi.fn(async () => {
      requests += 1;
      const body = requests > 1 ? ready : pending;
      return { ok: true, status: 200, statusText: "OK", json: async () => body } as Response;
    });
    (globalThis as unknown as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;
    renderRow();
    const status = await screen.findByTestId("semantic-search-status");
    expect(status.textContent).toContain("Starting");

    await waitFor(() => expect(status.textContent).toContain("3 pages"), { timeout: 3000 });
  });
});
