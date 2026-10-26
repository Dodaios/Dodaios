/**
 * Routines as tasks: the list's last result and cost, the away-parking note,
 * "set up / edit in chat", run history with duration and cost, and the
 * webhook card's masked key and header line.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import type { ReactNode } from "react";
import en from "@/i18n/locales/society/en.json";
import type { TaskStep } from "@/lib/tasksApi";

const seed = vi.fn(async (_agent: unknown, _text: string) => {});
vi.mock("./editThroughChat", () => ({ seedAgentComposer: (agent: unknown, text: string) => seed(agent, text) }));
vi.mock("@/components/agentchat/AgentTimeline", () => ({ AgentTimeline: () => null }));
vi.mock("@/i18n", () => ({
  useLocaleChunk: () => true,
  useUiLanguage: () => "en",
  useI18nStore: { getState: () => ({ ui: "en" }) },
  useT: () => (key: string) => key.split(".").reduce<unknown>((value, part) => (value as Record<string, unknown>)?.[part], en) as string ?? key,
}));

import { AgentRoutinesList } from "../AgentRoutinesList";
import { AgentRoutineDetail } from "../AgentRoutineDetail";
import { WebhookConnection } from "../WebhookConnection";
import { mergeRunDetails, routineRuns } from "./runs";
import { resetSeenThrottle, type RoutineRunRow } from "./routinesApi";
import type { LiveRoutine } from "../../cardData";

const json = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body }) as Response;

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchInterval: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function runRow(overrides: Partial<RoutineRunRow>): RoutineRunRow {
  return {
    id: "r1:1", task_id: "r1", status: "completed", origin: "automatic", started_ms: Date.now() - 3_600_000,
    finished_ms: Date.now() - 3_590_000, duration_ms: 10_000, cost_usd: 0.042, billed_via_key: false,
    provider: "claude-cli", model: "sonnet", session_id: "", summary: "Three new invoices", error: "",
    skip_code: "", skip_provider: "", ...overrides,
  };
}

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { resetSeenThrottle(); seed.mockClear(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("routine list", () => {
  function mountList(activity: unknown) {
    fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/routines-activity")) return json(activity);
      if (url.endsWith("/routines-parking")) return json({ parking: { banner: false } });
      if (url.endsWith("/routine-parking")) return json({ days: 7 });
      if (url.endsWith("/routines") && (init?.method ?? "GET") === "GET") return json({ routines: [
        { id: "r1", title: "[agent:Mail] Inbox digest", state: "scheduled", trigger: { type: "cron", expression: "30 7 * * 1-5", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }, due_at_ns: (Date.now() + 3 * 3_600_000) * 1e6 },
        { id: "r2", title: "[agent:Mail] Weekly cleanup", state: "paused", trigger: { type: "every", interval_seconds: 604800 } },
      ] });
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    return wrap(<AgentRoutinesList agentId="mail" />);
  }

  test("rows read as sentences with the last result and its cost, and looking is recorded", async () => {
    mountList({ last_runs: { r1: runRow({}), r2: runRow({ id: "r2:9", task_id: "r2", status: "failed", error: "RuntimeError: seat offline", cost_usd: null }) }, parking: null });
    const row = (await screen.findByRole("button", { name: "Inbox digest" })).closest("li")!;
    expect(row.textContent).toMatch(/Weekdays at 07:30( AM)?/);
    await waitFor(() => expect(row.textContent).toContain("$0.042"));
    expect(row.textContent).toMatch(/next_run: in 3 hours/);
    const paused = screen.getByRole("button", { name: "Weekly cleanup" }).closest("li")!;
    expect(paused.textContent).toContain("Every week");
    expect(paused.textContent).toContain("state.paused");
    expect(paused.textContent).toContain("RuntimeError: seat offline");
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/routines-seen") && init?.method === "POST")).toBe(true);
  });

  test("a parked agent shows the note once, and Resume answers it", async () => {
    mountList({ last_runs: {}, parking: { enabled: true, days: 7, banner: true, parked_ids: ["r2"], parked_ms: 1, parked_days: 7, unread: 5, never_ask: false } });
    const banner = await screen.findByTestId("routine-parking-banner");
    expect(banner.textContent).toContain("This routine made 5 results in 7 days");
    expect(screen.getByRole("button", { name: "Weekly cleanup" }).closest("li")!.textContent).toContain("Paused while you were away");
    fireEvent.click(within(banner).getByText("Resume"));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/routines-parking"));
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ choice: "keep_running" });
    });
  });

  test("set up in chat seeds the agent's composer instead of a form", async () => {
    mountList({ last_runs: {}, parking: null });
    fireEvent.click(await screen.findByTestId("agent-routines-chat"));
    await waitFor(() => expect(seed).toHaveBeenCalledWith({ tier: "specialist", chatSessionId: "society:mail" }, "Set up a routine for me: "));
  });

  test("the row's test run starts it right away", async () => {
    mountList({ last_runs: {}, parking: null });
    await screen.findByRole("button", { name: "Inbox digest" });
    fireEvent.click(screen.getAllByRole("button", { name: "Test run now" })[0]);
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === "/api/tasks/r1/run" && init?.method === "POST")).toBe(true));
  });
});

describe("routine detail", () => {
  const steps = (events: Record<string, unknown>[]) => events.map((payload, seq) => ({ seq, kind: "log", timestamp_ns: (Date.now() - (events.length - seq) * 60_000) * 1e6, payload } as TaskStep));

  function mountDetail(taskSteps: TaskStep[], runs: RoutineRunRow[] = []) {
    const trigger = { type: "calendar", local_time: "08:00", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, weekdays: [0, 1, 2, 3, 4] };
    const routine: LiveRoutine = { id: "r1", title: "[agent:Mail] Inbox", prompt: "Read mail.", trigger, schedule: "", state: "scheduled", dueMs: null, lastRunMs: null };
    fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/runs")) return json({ runs });
      if (url === "/api/tasks/r1") return json({ ...routine, trigger_type: "calendar", trigger, state: "scheduled", spec: { action: { kind: "agent", prompt: "Identity\nRoutine:\nRead mail." } }, steps: taskSteps });
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    return wrap(<AgentRoutineDetail agentId="mail" routine={routine} onClose={() => {}} />);
  }

  test("the header says what triggers it; edit in chat names the routine and its schedule", async () => {
    mountDetail([]);
    const sentence = (await screen.findByTestId("routine-schedule-sentence")).textContent ?? "";
    expect(sentence).toMatch(/^Weekdays at 08:00( AM)?$/);
    fireEvent.click(screen.getByText("Edit in chat"));
    await waitFor(() => expect(seed).toHaveBeenCalledWith(
      { tier: "specialist", chatSessionId: "society:mail" }, `Change my routine "Inbox" (${sentence}): `,
    ));
    expect(await screen.findByText("No runs yet. Use Test run to try it now.")).toBeTruthy();
  });

  test("runs show manual starts, duration and cost; a failed latest run is explained", async () => {
    const taskSteps = steps([
      { event: "run_now" }, { event: "run_started" }, { event: "routine_summary", duration_ms: 42_000, cost_usd: 0.31, billed_via_key: true },
      { event: "agent_result", text: "**Done**: sorted 12 mails" }, { event: "run_completed" },
      { event: "run_started" }, { event: "error", message: "RuntimeError: quota exhausted" },
    ]);
    mountDetail(taskSteps, [runRow({ id: "r1:0", cost_usd: 9 })]);
    const manual = await screen.findByTestId("routine-run-r1:1");
    expect(manual.textContent).toContain("Manual");
    expect(manual.textContent).toContain("42 s");
    expect(manual.textContent).toContain("$0.31");
    expect(manual.textContent).toContain("Done: sorted 12 mails");
    const failure = screen.getByTestId("routine-last-failure");
    expect(failure.textContent).toContain("RuntimeError: quota exhausted");
  });
});

describe("run model", () => {
  test("the route fills cost and summary the steps do not know", () => {
    const runs = routineRuns("r1", [
      { seq: 1, kind: "log", timestamp_ns: 1e12, payload: { event: "run_started" } },
      { seq: 2, kind: "log", timestamp_ns: 2e12, payload: { event: "run_completed", duration_ms: 1500 } },
    ] as TaskStep[]);
    const merged = mergeRunDetails(runs, [runRow({ id: "r1:1", cost_usd: 0.5, summary: "From the chat", duration_ms: 99 })]);
    expect(merged[0]).toMatchObject({ costUsd: 0.5, summary: "From the chat", durationMs: 1500, origin: "automatic" });
  });

  test("an away-parked skip reads in plain words", async () => {
    const { runReason } = await import("./RunHistory");
    const t = (key: string) => key;
    expect(runReason(t, { id: "x", taskId: "r1", timestamp: 0, status: "skipped", text: "", origin: "automatic", skipCode: "away_parked" }))
      .toBe("society.agent_routines.runs.skip_away");
  });
});

describe("webhook card", () => {
  test("the key and header stay masked until revealed, and copy takes the full line", async () => {
    const writeText = vi.fn(async () => {});
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ path: "/api/tasks/hooks/r1", token: "tok-123" }), { status: 200 })));
    render(<WebhookConnection taskId="r1" />);
    fireEvent.click(await screen.findByText("Connect webhook"));
    const key = await screen.findByDisplayValue("tok-123");
    expect(key.getAttribute("type")).toBe("password");
    expect(screen.getByTestId("webhook-header-line").textContent).not.toContain("tok-123");
    fireEvent.click(screen.getByRole("button", { name: "Copy header line" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("Authorization: Bearer tok-123"));
    fireEvent.click(screen.getByRole("button", { name: "Show key" }));
    expect(key.getAttribute("type")).toBe("text");
    expect(screen.getByTestId("webhook-header-line").textContent).toBe("Authorization: Bearer tok-123");
  });
});
