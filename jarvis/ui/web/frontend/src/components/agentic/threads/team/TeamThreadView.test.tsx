import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import type { IdeProject } from "@/lib/agenticIdeApi";
import type { TeamThread } from "@/lib/teamThreadsApi";
import { TEAM_DRAFT, useIdeThreadsStore } from "@/store/ideThreads";
import { TeamThreadView } from "./TeamThreadView";

vi.mock("@/i18n", () => ({
  useT: () => (key: string) => key,
  fill: (template: string, vars: Record<string, unknown>) => `${template} ${JSON.stringify(vars)}`,
}));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const project = { id: "p1", name: "Shop", path: "/work/shop", workspaces: [] } as unknown as IdeProject;

const member = (id: string, name: string, extra: Partial<TeamThread["members"][number]> = {}) => ({
  member_id: id, name, provider: name.toLowerCase(), model: "", effort: "", family: name.toLowerCase(),
  session_id: `session-${id}`, state: "active" as const, left_reason: "", working: false, since_ms: 0, waiting: false,
  ...extra,
});

const entry = (seq: number, kind: string, author: string, payload: object, round = 0) =>
  ({ seq, ts_ms: seq, kind, author, phase: "review", round, payload }) as TeamThread["entries"][number];

const thread: TeamThread = {
  team_id: "t1", title: "Add a retry", task: "Add a retry", cwd: "/work/shop",
  state: "needs_input", phase: "review", reason: "review_disagreement", note: "",
  limits: { max_minutes: 90, max_turns: 40, plan_rounds: 3, review_rounds: 3, turn_minutes: 30, max_cost_usd: 0 },
  usage: { elapsed_ms: 12 * 60_000, turns: 14, cost_usd: 0, cost_partial: true },
  rounds: { plan: 1, review: 3 },
  builder: "m1",
  members: [member("m1", "Claude"), member("m2", "GPT", { working: true }), member("m3", "Gemini", { state: "left", left_reason: "not signed in" })],
  entries: [
    entry(1, "user", "user", { text: "Add a retry" }),
    entry(2, "draft", "m1", { text: "Plan **A**" }),
    entry(3, "plan", "m1", { text: "The master plan" }, 1),
    entry(4, "vote", "m2", { text: "ok", agree: true, objections: [] }, 1),
    entry(5, "notice", "team", { code: "plan_agreed", rounds: 1, by: "m1" }),
    entry(6, "build", "m1", { text: "Built it", files: ["app.py", "test_app.py"], stat: "2 files" }),
    entry(7, "review", "m2", {
      text: "Not yet", approve: false,
      findings: [{ severity: "blocking", where: "app.py:3", issue: "Loops forever on a 404", fix: "Stop on 4xx" }],
    }, 3),
    entry(8, "summary", "team", {
      outcome: "review_disagreement", rounds: 3,
      open: [{ member_id: "m2", name: "GPT", items: ["app.py:3: Loops forever on a 404"] }],
    }),
  ],
  issues: [{ seq: 7, stage: "review", round: 3, by: "m2", severity: "blocking", where: "app.py:3", issue: "Loops forever on a 404", fix: "Stop on 4xx", resolved: false }],
  created_ms: 1, updated_ms: 2,
};

function mount(team: string, data: unknown) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body as string) : undefined });
    if (url.endsWith("/seats")) {
      return { ok: true, json: async () => ({
        seats: [
          { provider: "claude-api", label: "Claude", family: "claude", runner: "claude-cli", agent: "claude", model: "", models: [], ready: true, local: false },
          { provider: "openai-codex", label: "Codex", family: "openai", runner: "codex-cli", agent: "codex", model: "", models: [], ready: true, local: false },
          { provider: "grok-build", label: "Grok", family: "xai", runner: "grok-cli", agent: "grok-build", model: "", models: [], ready: false, local: false },
        ],
        default: [{ provider: "claude-api", model: "" }, { provider: "openai-codex", model: "" }],
        min_members: 2, max_members: 4,
      }) };
    }
    // Like the server: a read with `after` returns only the entries past it.
    const after = Number(new URL(url, "http://x").searchParams.get("after") ?? 0);
    const entries = (data as TeamThread).entries.filter((entry) => entry.seq > after);
    return { ok: true, json: async () => (init?.method ? data : { ...(data as TeamThread), entries }) };
  });
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><TeamThreadView team={team} project={project} onScreen /></QueryClientProvider>);
  return calls;
}

it("shows who said what, what was caught and why the team waits", async () => {
  const calls = mount("t1", thread);

  expect((await screen.findByTestId("team-thread-state")).textContent).toBe("team_threads.state.needs_input");
  // The person's task, the plan, the report and the review are one thread.
  expect(screen.getByTestId("team-entry-user").textContent).toBe("Add a retry");
  expect(screen.getByText("The master plan")).toBeTruthy();
  expect(screen.getByText("Built it")).toBeTruthy();
  expect(screen.getByTestId("team-notice-plan_agreed").textContent).toContain('"member":"Claude"');
  // A first plan opens folded; the master plan supersedes it.
  expect(screen.queryByText("A")).toBeNull();
  fireEvent.click(screen.getAllByRole("button", { expanded: false })[0]);
  expect(screen.getByText("A").tagName).toBe("STRONG");
  // The finding is in the review, in the open points and in the record.
  expect(screen.getAllByText("Loops forever on a 404")).toHaveLength(2);
  expect(screen.getByTestId("team-summary-review_disagreement").textContent).toContain("app.py:3: Loops forever on a 404");
  expect(screen.getByTestId("team-thread-issues").textContent).toContain("team_threads.issues.open");
  // Members: one working, one gone with its reason.
  expect(screen.getByTestId("team-member-m2").textContent).toContain("team_threads.member.working");
  expect(screen.getByTestId("team-member-m3").getAttribute("title")).toBe("not signed in");
  expect(screen.getByTestId("team-thread-usage").textContent).toContain('"minutes":12');

  fireEvent.click(screen.getByRole("button", { name: "team_threads.accept_work" }));
  await waitFor(() => expect(calls.some((call) => call.url === "/api/team-threads/t1/accept" && call.method === "POST")).toBe(true));
  // The first read asks for everything; nothing was fetched twice.
  expect(calls.find((call) => call.url.startsWith("/api/team-threads/t1?"))?.url).toBe("/api/team-threads/t1?after=0");
  expect(screen.getAllByTestId("team-entry-user")).toHaveLength(1);
});

it("sends what the person says to the team and opens a member's own thread", async () => {
  const calls = mount("t1", { ...thread, state: "running", reason: "" });

  const field = await screen.findByTestId("team-thread-message");
  fireEvent.change(field, { target: { value: "Keep the public API unchanged" } });
  fireEvent.keyDown(field, { key: "Enter" });
  await waitFor(() => expect(calls.find((call) => call.url.endsWith("/message"))?.body).toEqual({ text: "Keep the public API unchanged" }));
  // A working thread offers pause and stop, never the waiting banner.
  expect(screen.getByRole("button", { name: "team_threads.pause" })).toBeTruthy();
  expect(screen.queryByTestId("team-thread-waiting")).toBeNull();

  fireEvent.click(screen.getByTestId("team-member-m1"));
  expect(useIdeThreadsStore.getState().selection).toEqual({ projectId: "p1", sessionId: "session-m1" });
});

it("starts the suggested team with one prompt", async () => {
  const calls = mount(TEAM_DRAFT, { ...thread, team_id: "t9" });

  await screen.findByTestId("team-draft-member-1");
  expect(screen.queryByTestId("team-draft-member-2")).toBeNull();
  const start = screen.getByTestId("team-draft-start") as HTMLButtonElement;
  expect(start.disabled).toBe(true);
  fireEvent.change(screen.getByTestId("team-draft-task"), { target: { value: "Add a retry to the uploader" } });
  expect(start.disabled).toBe(false);
  fireEvent.click(start);

  await waitFor(() => expect(calls.find((call) => call.method === "POST")?.body).toEqual({
    task: "Add a retry to the uploader",
    cwd: "/work/shop",
    seats: [{ provider: "claude-api", model: "" }, { provider: "openai-codex", model: "" }],
  }));
  await waitFor(() => expect(useIdeThreadsStore.getState().selection).toEqual({ projectId: "p1", sessionId: null, team: "t9" }));
});
