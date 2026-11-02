import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useUserName } from "./useUserName";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient();
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useUserName", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("asks again when the backend is still booting, so the name still arrives", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 503 }))
      .mockResolvedValue(new Response(JSON.stringify({ user: { name: "Ruben" } }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useUserName(), { wrapper });

    await waitFor(() => expect(result.current).toBe("Ruben"), { timeout: 4_000 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not keep asking a host that has no profile route", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useUserName(), { wrapper });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await new Promise((r) => setTimeout(r, 1_500));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current).toBeNull();
  });
});
