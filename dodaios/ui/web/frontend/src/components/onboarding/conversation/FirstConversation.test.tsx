import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { loadLocaleChunk } from "@/i18n";
import { useEventStore } from "@/store/events";
import { FirstConversation } from "./FirstConversation";
import { _resetFirstConversationCache } from "./firstConversationApi";

let due = true;
let calls: Array<{ url: string; method: string; body?: unknown }> = [];

function stubFetch() {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ url, method, body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined });
      const reply = (body: unknown, status = 200) =>
        Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });
      if (url === "/api/onboarding/state") return reply({ completed: true, first_conversation_due: due });
      if (url === "/api/marketplace/plugins")
        return reply({
          plugins: [
            { id: "gmail", display_name: "Gmail", status: "available" },
            { id: "github", display_name: "GitHub", status: "connected" },
            { id: "spotify", display_name: "Spotify", status: "available" },
          ],
        });
      if (url.includes("/connect/start")) return reply({ detail: "needs a token" }, 400);
      return reply({ ok: true });
    }),
  );
}

function renderIt(fallback: React.ReactNode = <p>greeting</p>) {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <FirstConversation fallback={fallback} />
    </QueryClientProvider>,
  );
}

beforeAll(async () => {
  await loadLocaleChunk("onboarding");
});

beforeEach(() => {
  due = true;
  _resetFirstConversationCache();
  useEventStore.setState({ assistantName: "Nova" });
  stubFetch();
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, writable: true, value: vi.fn() });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const posted = (url: string) => calls.filter((c) => c.url === url && c.method !== "GET");

describe("FirstConversation", () => {
  it("shows the greeting when the introduction is not due (an existing install)", async () => {
    due = false;
    renderIt();
    await waitFor(() => expect(calls.some((c) => c.url === "/api/onboarding/state")).toBe(true));
    expect(screen.getByText("greeting")).toBeTruthy();
    expect(screen.queryByTestId("first-conversation")).toBeNull();
  });

  it("asks three things one at a time and saves each answer", async () => {
    renderIt();
    const hello = await screen.findByTestId("first-conversation-hello");
    expect(hello.textContent).toContain("Nova");
    // One question at a time: only the name is asked so far.
    expect(screen.queryByTestId("first-conversation-help")).toBeNull();

    fireEvent.change(screen.getByTestId("first-conversation-name"), { target: { value: "  Ana " } });
    fireEvent.click(screen.getByTestId("first-conversation-name-save"));
    const help = await screen.findByTestId("first-conversation-help");
    expect(help.textContent).toContain("Ana");
    expect(posted("/api/profile/field")[0].body).toEqual({
      cluster: "identity",
      field: "name",
      operation: "set",
      value: "Ana",
    });
    expect(posted("/api/memory/vault/items")[0].body).toMatchObject({ text: "The user's name is Ana.", kind: "profile" });

    fireEvent.click(screen.getByTestId("first-conversation-topic-email"));
    fireEvent.click(screen.getByTestId("first-conversation-topic-coding"));
    expect(screen.getByTestId("first-conversation-topic-email").getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByTestId("first-conversation-help-save"));
    await screen.findByTestId("first-conversation-accounts");
    expect(posted("/api/memory/vault/items")[1].body).toMatchObject({
      text: "The user wants help with: email, coding.",
      kind: "preference",
    });

    // The topics put their accounts first; a connected one says so.
    const gmail = await screen.findByTestId("first-conversation-account-gmail");
    expect(gmail).toBeTruthy();
    expect(screen.getByTestId("first-conversation-account-github").getAttribute("data-phase")).toBe("connected");
    // A plugin without a browser sign-in sends the person to its page in Plugins.
    fireEvent.click(within(gmail).getByTestId("first-conversation-account-connect-gmail"));
    await waitFor(() => expect(gmail.getAttribute("data-phase")).toBe("page"));

    fireEvent.click(screen.getByTestId("first-conversation-accounts-done"));
    const done = await screen.findByTestId("first-conversation-done");
    expect(done.textContent).toContain("Ana");
    await waitFor(() =>
      expect(posted("/api/onboarding/first-conversation")[0]?.body).toEqual({ outcome: "done" }),
    );
    fireEvent.click(screen.getByTestId("first-conversation-close"));
    expect(screen.queryByTestId("first-conversation")).toBeNull();
    expect(screen.getByText("greeting")).toBeTruthy();
  });

  it("can skip a question or the whole introduction", async () => {
    renderIt();
    await screen.findByTestId("first-conversation-hello");
    fireEvent.click(screen.getByTestId("first-conversation-name-skip"));
    await screen.findByTestId("first-conversation-help");
    expect(posted("/api/profile/field")).toHaveLength(0);
    expect(screen.getByTestId("first-conversation-answer").textContent).toBe("Skipped");

    fireEvent.click(screen.getByTestId("first-conversation-skip"));
    expect(screen.queryByTestId("first-conversation")).toBeNull();
    await waitFor(() =>
      expect(posted("/api/onboarding/first-conversation")[0]?.body).toEqual({ outcome: "skipped" }),
    );
  });
});
