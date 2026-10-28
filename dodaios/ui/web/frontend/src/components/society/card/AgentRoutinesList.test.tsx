/**
 * The per-agent routines list: titles drop the scheduler prefix, + posts
 * through the society route, and a new row appears after save.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { AgentRoutinesList } from "@/components/society/card/AgentRoutinesList";
import { notifyRoutineChanged } from "@/components/society/cardData";

vi.mock("./AgentRoutineDetail", () => ({ AgentRoutineDetail: () => <div data-testid="routine-opened" /> }));

function mount(agentId = "mailbox") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchInterval: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AgentRoutinesList agentId={agentId} />
    </QueryClientProvider>,
  );
}

function json(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

let routines: { id: string; title: string; state: string; trigger: unknown; due_at_ns?: number }[];
let fetchMock: ReturnType<typeof vi.fn>;

describe("AgentRoutinesList", () => {
  beforeEach(() => {
    routines = [
      {
        id: "r1",
        title: "[agent:Mailbox] Morning inbox",
        state: "scheduled",
        trigger: { kind: "every", interval_seconds: 3_600 },
      },
    ];
    fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url);
      const method = init?.method ?? "GET";
      // Run activity, "seen" and parking routes are enrichment; they answer empty here.
      if (path.includes("/routines-") || path.includes("/routine-parking")) return json({});
      if (path.includes("/routines") && method === "POST") {
        const body = JSON.parse(String(init?.body ?? "{}")) as { title?: string; prompt?: string };
        routines = [
          ...routines,
          {
            id: "r2",
            title: `[agent:Mailbox] ${body.title ?? "new"}`,
            state: "scheduled",
            trigger: { kind: "every", interval_seconds: 18_000 },
          },
        ];
        return json({ id: "r2", title: `[agent:Mailbox] ${body.title ?? "new"}` });
      }
      if (path.includes("/routines")) return json({ routines });
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  test("strips the [agent:Name] prefix the scheduler stores", async () => {
    mount();
    await waitFor(() => expect(screen.getByTestId("agent-routines").textContent).toContain("Morning inbox"));
    expect(screen.getByTestId("agent-routines").textContent).not.toContain("[agent:Mailbox]");
  });

  test("a routine created in chat appears immediately in the open card", async () => {
    mount();
    await screen.findByRole("button", { name: "Morning inbox" });
    routines.push({
      id: "r-chat",
      title: "[agent:Mailbox] GitHub issues",
      state: "scheduled",
      trigger: { kind: "calendar", local_time: "08:00", timezone: "Europe/Berlin" },
    });
    act(() => notifyRoutineChanged("mailbox"));
    await screen.findByRole("button", { name: "GitHub issues" });
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/routines")).length)
      .toBeGreaterThan(1);
  });

  test("shows an empty list only after the routine request succeeds", async () => {
    let respond!: (response: Response) => void;
    fetchMock.mockImplementation((url: string) => String(url).endsWith("/routines")
      ? new Promise<Response>((resolve) => { respond = resolve; })
      : Promise.resolve(json({})));
    mount();
    expect(await screen.findByText("Loading…")).toBeTruthy();
    expect(screen.queryByText("No routines yet.")).toBeNull();
    respond(json({ routines: [] }));
    await screen.findByText("No routines yet.");
  });

  test.each(["schedule", "next-run", "padding"])("opens the routine when clicking %s", async (area) => {
    routines[0].due_at_ns = Date.UTC(2026, 8, 13, 8) * 1e6;
    mount();
    const card = await screen.findByRole("button", { name: "Morning inbox" });
    const target = area === "schedule" ? screen.getByText("Every hour")
      : area === "next-run" ? screen.getByText(/^Next run:/)
      : card;
    expect(card.contains(target)).toBe(true);
    fireEvent.click(target);
    expect(await screen.findByTestId("routine-opened")).toBeTruthy();
  });

  test("closing the form drops its draft, so new text never lands in front of a hidden one", async () => {
    mount();
    await screen.findByRole("button", { name: "Morning inbox" });
    const add = screen.getByTestId("agent-routines-add");
    fireEvent.click(add);
    const composer = screen.getByTestId("agent-routines-composer");
    const [title] = composer.querySelectorAll("input");
    const prompt = composer.querySelector("textarea")!;
    fireEvent.change(title, { target: { value: "Old title" } });
    fireEvent.change(prompt, { target: { value: "Old prompt" } });
    fireEvent.change(screen.getByTestId("agent-routines-when"), { target: { value: "every day at 7" } });
    fireEvent.click(add); // the X
    expect(screen.queryByTestId("agent-routines-composer")).toBeNull();
    fireEvent.click(add);
    const reopened = screen.getByTestId("agent-routines-composer");
    expect((reopened.querySelector("input") as HTMLInputElement).value).toBe("");
    expect((reopened.querySelector("textarea") as HTMLTextAreaElement).value).toBe("");
    expect((screen.getByTestId("agent-routines-when") as HTMLInputElement).value).toBe("");
  });

  test("adding a routine posts to this agent and shows the new row", async () => {
    mount();
    fireEvent.click(await screen.findByTestId("agent-routines-add"));
    fireEvent.change(screen.getByPlaceholderText("Title"), { target: { value: "X marketing" } });
    fireEvent.change(screen.getByPlaceholderText("What to do"), { target: { value: "Draft the post." } });
    // The schedule in plain words; the sentence it became shows before saving.
    fireEvent.change(screen.getByTestId("agent-routines-when"), { target: { value: "every 5 hours" } });
    expect(screen.getByTestId("agent-routines-when-preview").textContent).toBe("Every 5 hours");
    fireEvent.click(screen.getByText("Add"));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes("/api/society/agents/mailbox/routines") && (c[1] as RequestInit | undefined)?.method === "POST",
      );
      expect(post).toBeTruthy();
      const body = JSON.parse(String(post?.[1]?.body));
      expect(body.title).toBe("X marketing");
      expect(body.prompt).toBe("Draft the post.");
      expect(body.schedule).toEqual({ type: "every", interval_seconds: 18_000 });
    });

    await waitFor(() => expect(screen.getByTestId("agent-routines").textContent).toContain("X marketing"));
  });
  test("the webhook composer preserves typed JSON filters", async () => {
    mount();
    fireEvent.click(await screen.findByTestId("agent-routines-add"));
    fireEvent.change(screen.getByPlaceholderText("Title"), { target: { value: "Customer event" } });
    fireEvent.change(screen.getByPlaceholderText("What to do"), { target: { value: "Summarize the new customer." } });
    fireEvent.click(screen.getByTestId("agent-routines-more"));
    fireEvent.click(screen.getByTestId("routine-trigger-group"));
    fireEvent.click(await screen.findByRole("option", { name: "From another app" }));
    fireEvent.change(screen.getByLabelText("Payload filters (JSON field equality)"), { target: { value: '{"customer.vip":true}' } });
    fireEvent.click(screen.getByText("Add"));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((call) => (call[1] as RequestInit | undefined)?.method === "POST");
      expect(post).toBeTruthy();
      expect(JSON.parse(String(post?.[1]?.body)).schedule).toEqual({ type: "webhook", provider: "generic", conditions: { "customer.vip": true } });
    });
  });

});
