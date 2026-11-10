import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { NotificationsView } from "./NotificationsView";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const SETTINGS = {
  enabled: true,
  kinds: { reminder: true, needs_you: true, approval: true, finished: true },
  quiet_hours: { enabled: false, start: "22:00", end: "07:00" },
  telegram_approvals: true,
};

function stubFetch(telegram = { connected: false, owner_known: false }) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    if (url.endsWith("/api/notify/telegram")) return new Response(JSON.stringify(telegram));
    if (url.endsWith("/api/notify/test")) {
      return new Response(JSON.stringify({ shown: false, held: "quiet_hours", how: "" }));
    }
    if (init?.method === "PUT") {
      const patch = JSON.parse(String(init.body)) as Record<string, unknown>;
      const merged = {
        ...SETTINGS,
        ...patch,
        kinds: { ...SETTINGS.kinds, ...((patch.kinds as object) ?? {}) },
        quiet_hours: { ...SETTINGS.quiet_hours, ...((patch.quiet_hours as object) ?? {}) },
      };
      return new Response(JSON.stringify(merged));
    }
    return new Response(JSON.stringify(SETTINGS));
  });
  vi.stubGlobal("fetch", fetcher);
  return calls;
}

it("loads the settings and saves a kind switch on the spot", async () => {
  const calls = stubFetch();
  render(<NotificationsView />);
  await waitFor(() => expect(screen.getByTestId("notify-enabled")).toBeTruthy());
  expect(screen.getByTestId("notify-kind-approval").getAttribute("aria-checked")).toBe("true");
  fireEvent.click(screen.getByTestId("notify-kind-finished"));
  await waitFor(() =>
    expect(screen.getByTestId("notify-kind-finished").getAttribute("aria-checked")).toBe("false"));
  const put = calls.find((c) => c.init?.method === "PUT");
  expect(put?.url).toBe("/api/notify/settings");
  expect(JSON.parse(String(put?.init?.body))).toEqual({ kinds: { finished: false } });
  // Telegram is not connected: the hint says how to connect it.
  expect(screen.getByText("notify.telegram_not_connected")).toBeTruthy();
});

it("quiet hours take a start and an end", async () => {
  const calls = stubFetch({ connected: true, owner_known: true });
  render(<NotificationsView />);
  await waitFor(() => expect(screen.getByTestId("notify-quiet")).toBeTruthy());
  fireEvent.click(screen.getByTestId("notify-quiet"));
  await waitFor(() => expect(screen.getByTestId("notify-quiet").getAttribute("aria-checked")).toBe("true"));
  fireEvent.change(screen.getByTestId("notify-quiet-start"), { target: { value: "23:30" } });
  await waitFor(() => expect((screen.getByTestId("notify-quiet-start") as HTMLInputElement).value).toBe("23:30"));
  const bodies = calls.filter((c) => c.init?.method === "PUT").map((c) => JSON.parse(String(c.init?.body)));
  expect(bodies).toEqual([{ quiet_hours: { enabled: true } }, { quiet_hours: { start: "23:30" } }]);
  expect(screen.getByText("notify.telegram_hint")).toBeTruthy();
});

it("the test button reports what the backend did", async () => {
  stubFetch();
  render(<NotificationsView />);
  await waitFor(() => expect(screen.getByTestId("notify-enabled")).toBeTruthy());
  fireEvent.click(screen.getByTestId("notify-test"));
  await waitFor(() => expect(screen.getByTestId("notify-test-result").textContent).toBe("notify.test_held"));
});

it("says when the settings cannot be loaded", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 503 })));
  render(<NotificationsView />);
  await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("notify.load_failed"));
});
