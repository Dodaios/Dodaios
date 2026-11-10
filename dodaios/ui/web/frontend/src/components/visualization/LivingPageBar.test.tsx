import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("@/i18n", () => ({
  useT: () => (key: string) => (key === "living_pages.updated" ? "Updated {0}" : key === "living_pages.every" ? "Refreshes every {0}" : key),
  useUiLanguage: () => "en",
}));

import LivingPageBar from "./LivingPageBar";
import { cadence, isLivingSlug, relativeTime } from "./livingPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const page = (refreshing: boolean) => ({
  id: "0123456789ab",
  title: "My parcels",
  slug: "20261110T080000__living-page__0123456789ab",
  page_path: "tasks/living/artifacts/files/my-parcels.html",
  visual_id: "x::y",
  updated_at: Math.floor(Date.now() / 1000) - 600,
  every_minutes: 180,
  refreshing,
  note: "",
});

function renderBar() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <LivingPageBar slug="20261110T080000__living-page__0123456789ab" />
    </QueryClientProvider>,
  );
}

it("says when the page was updated and stops its refresh from the page", async () => {
  const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) =>
    new Response(JSON.stringify(init?.method === "POST" ? page(false) : page(true))),
  );
  vi.stubGlobal("fetch", fetcher);
  renderBar();
  await waitFor(() => expect(screen.getByTestId("living-page-bar")).toBeTruthy());
  expect(screen.getByText("Updated 10 minutes ago")).toBeTruthy();
  expect(screen.getByText("Refreshes every 3 hours")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "living_pages.stop" }));
  await waitFor(() => expect(screen.getByText("living_pages.stopped")).toBeTruthy());
  expect(String(fetcher.mock.calls[1][0])).toBe("/api/living-pages/0123456789ab/stop");
  expect(screen.getByRole("button", { name: "living_pages.resume" })).toBeTruthy();
});

it("shows nothing for a run that is not a living page", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
  const { container } = renderBar();
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(container.textContent).toBe("");
});

it("formats times and cadences in the reader's locale", () => {
  expect(isLivingSlug("20261110T080000__living-page__0123456789ab")).toBe(true);
  expect(isLivingSlug("mission_0123")).toBe(false);
  const now = 1_800_000_000_000;
  expect(relativeTime(now / 1000 - 600, now, "en-US")).toBe("10 minutes ago");
  expect(relativeTime(now / 1000 - 600, now, "de-DE")).toBe("vor 10 Minuten");
  expect(cadence(180, "en-US")).toBe("3 hours");
  expect(cadence(1440, "en-US")).toBe("1 day");
  expect(cadence(45, "en-US")).toBe("45 minutes");
});
