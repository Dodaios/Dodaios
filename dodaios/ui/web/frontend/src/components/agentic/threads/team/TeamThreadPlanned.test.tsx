import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { IdeProject } from "@/lib/agenticIdeApi";
import type { TeamThread } from "@/lib/teamThreadsApi";
import { TEAM_DRAFT } from "@/store/ideThreads";
import { buildBoard, type StepBand } from "./board";
import { closeAllMemberStreams } from "./memberStreams";
import { TeamThreadView } from "./TeamThreadView";

vi.mock("@/i18n", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/i18n")>()),
  useT: () => (key: string) => key,
  fill: (template: string, vars: Record<string, unknown>) => `${template} ${JSON.stringify(vars)}`,
}));

// A plain stand-in for the combobox, so a test can pick an option.
vi.mock("@/components/ui/select", () => ({
  BrandedSelect: ({ options, onValueChange, testId, value }: {
    options: { value: string; label: string }[]; onValueChange: (value: string) => void; testId: string; value: string;
  }) => <div data-testid={testId} data-value={value}>
    {options.map((option) => <button key={option.value} type="button" onClick={() => onValueChange(option.value)}>{option.label}</button>)}
  </div>,
}));

class QuietSocket {
  onopen: (() => void) | null = null;
  onmessage: ((message: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close() {}
}

/** jsdom lays nothing out; the canvas only needs to be told its size once. */
class StillResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}
  observe(target: Element) {
    this.callback([{ target, contentRect: { width: 1000, height: 600 } } as unknown as ResizeObserverEntry], this as unknown as ResizeObserver);
  }
  unobserve() {}
  disconnect() {}
}

/** The one matrix the canvas reads: its zoom. */
class ScaleMatrix {
  m22: number;
  constructor(transform?: string) {
    const scale = /scale\(([\d.]+)\)/.exec(transform ?? "")?.[1];
    this.m22 = scale ? Number(scale) : 1;
  }
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", QuietSocket);
  vi.stubGlobal("ResizeObserver", StillResizeObserver);
  vi.stubGlobal("DOMMatrixReadOnly", ScaleMatrix);
});
afterEach(() => { cleanup(); closeAllMemberStreams(); vi.unstubAllGlobals(); });

const project = { id: "p1", name: "Shop", path: "/work/shop", workspaces: [] } as unknown as IdeProject;

type Member = TeamThread["members"][number];
const member = (id: string, name: string, role: Member["role"], extra: Partial<Member> = {}): Member => ({
  member_id: id, name, provider: name.toLowerCase(), model: "", effort: "", family: name.toLowerCase(),
  session_id: `session-${id}`, state: "active", left_reason: "", working: false, since_ms: 0, waiting: false, role,
  ...extra,
});

const entry = (seq: number, kind: string, author: string, payload: object, phase: string, round = 1) =>
  ({ seq, ts_ms: seq, kind, author, phase, round, payload }) as TeamThread["entries"][number];

const steps = [
  { title: "Add the setting", goal: "A retry count in config.py", done_when: "pytest tests/test_config.py passes" },
  { title: "Use it in the uploader", goal: "Retry on 5xx", done_when: "The uploader retries three times" },
];

/** A thread whose step 1 is accepted and whose step 2 the reviewer is reading. */
const thread: TeamThread = {
  team_id: "t1", title: "Add a retry", task: "Add a retry", cwd: "/work/shop", mode: "planner_builder",
  state: "running", phase: "steps", reason: "", note: "",
  limits: { max_minutes: 90, max_turns: 40, plan_rounds: 3, review_rounds: 3, turn_minutes: 30, max_cost_usd: 0 },
  usage: { elapsed_ms: 4 * 60_000, turns: 7, cost_usd: 0, cost_partial: true },
  rounds: { plan: 1, review: 1, step: 2, plan_round: 1, final: 0 },
  builder: "m2",
  members: [
    member("m1", "Claude", "planner"),
    member("m2", "Codex", "builder"),
    member("m3", "Gemini", "reviewer", { working: true, since_ms: Date.now() - 5_000 }),
  ],
  entries: [
    entry(1, "user", "user", { text: "Add a retry" }, "planning", 0),
    entry(2, "plan_version", "m1", { text: "Unreadable", valid: false, error: "The reply has no team-plan block." }, "planning"),
    entry(3, "plan_version", "m1", { text: "Two small steps.", valid: true, version: 1, steps, carried: [] }, "planning"),
    entry(4, "plan_review", "m3", { text: "Good", agree: true, objections: [], plan_seq: 3, version: 1 }, "planning"),
    entry(5, "notice", "team", { code: "plan_version_agreed", version: 1, rounds: 1, count: 2, by: "m1" }, "planning", 0),
    entry(6, "step_build", "m2", { text: "Added it.", version: 1, number: 1, title: "Add the setting", status: "done", files: ["config.py"] }, "steps"),
    entry(7, "step_review", "m3", {
      text: "Missing test", approve: false, version: 1, number: 1,
      findings: [{ severity: "blocking", where: "config.py:3", issue: "No test for the default", fix: "Add one" }],
    }, "steps"),
    entry(8, "step_build", "m2", { text: "Added the test.", version: 1, number: 1, title: "Add the setting", status: "done" }, "steps", 2),
    entry(9, "step_review", "m3", { text: "Fine", approve: true, findings: [], version: 1, number: 1 }, "steps", 2),
    entry(10, "notice", "team", { code: "step_accepted", number: 1, version: 1, title: "Add the setting", rounds: 2 }, "steps", 0),
    entry(11, "step_build", "m2", {
      text: "Cannot", version: 1, number: 2, title: "Use it in the uploader", status: "blocked", note: "No retry hook",
    }, "steps"),
  ],
  plan: {
    version: 1, seq: 3, agreed: true, author: "m1", versions: 1, revision: null,
    steps: [
      { number: 1, ...steps[0], status: "accepted", holders: [], rounds: 2, open_findings: false },
      { number: 2, ...steps[1], status: "in_review", holders: ["m3"], rounds: 1, open_findings: false },
    ],
  },
  issues: [{ seq: 7, stage: "step", number: 1, round: 1, by: "m3", severity: "blocking", where: "config.py:3", issue: "No test for the default", fix: "Add one", resolved: true }],
  created_ms: 1, updated_ms: 2,
};

function mount(team: string, data: unknown) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body as string) : undefined });
    if (url.endsWith("/seats")) {
      return { ok: true, json: async () => ({
        seats: [
          { provider: "claude-api", label: "Claude", family: "claude", runner: "claude-cli", agent: "claude", model: "", models: [], ready: true, local: false },
          { provider: "openai-codex", label: "Codex", family: "openai", runner: "codex-cli", agent: "codex", model: "", models: [], ready: true, local: false },
          { provider: "antigravity", label: "Gemini", family: "antigravity", runner: "agy", agent: "antigravity", model: "", models: [], ready: true, local: false },
        ],
        default: [{ provider: "claude-api", model: "" }, { provider: "openai-codex", model: "" }, { provider: "antigravity", model: "" }],
        min_members: 2, max_members: 4,
      }) };
    }
    return { ok: true, json: async () => data };
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><TeamThreadView team={team} project={project} onScreen /></QueryClientProvider>);
  return calls;
}

it("shows a planner-and-builder team as a room: roles on the canvas, the plan a tab away, the steps in the story", async () => {
  mount("t1", thread);

  // The real canvas: each member with its role, the reviewer at work.
  // The canvas and its graph library load lazily; a busy machine takes a while.
  const canvas = await screen.findByTestId("team-canvas", {}, { timeout: 8000 });
  await waitFor(() => expect(within(canvas).getByTestId("team-node-m1")).toBeTruthy(), { timeout: 8000 });
  expect(within(screen.getByTestId("team-node-m1")).getByTestId("team-role-planner")).toBeTruthy();
  expect(within(screen.getByTestId("team-node-m2")).getByTestId("team-role-builder")).toBeTruthy();
  expect(screen.getByTestId("team-node-m3").dataset.state).toBe("working");
  // (jsdom measures no handles, so the canvas draws no lines here: teamGraph.test.ts covers them.)
  // The rail has the mode's three steps; the header says how far the plan is.
  expect(screen.getByLabelText("team_threads.steps").querySelectorAll("li")).toHaveLength(3);
  expect(screen.getByTestId("team-plan-progress").textContent).toContain('{"done":1,"total":2}');

  // Following the reviewer at work; the plan is a tab of its own.
  expect(await screen.findByTestId("team-chat-m3")).toBeTruthy();
  fireEvent.click(screen.getByTestId("team-plan-progress"));
  const panel = await screen.findByTestId("team-plan");
  expect(panel.textContent).toContain('team_threads.plan.title {"version":1}');
  expect(screen.getByTestId("team-plan-step-1").dataset.status).toBe("accepted");
  const second = screen.getByTestId("team-plan-step-2");
  expect(second.dataset.status).toBe("in_review");
  expect(second.getAttribute("aria-current")).toBe("step");
  expect(second.textContent).toContain("Gemini");

  // The story: a heading per step, the unreadable plan said plainly, the blocked step with its reason.
  fireEvent.click(screen.getByTestId("team-tab-story"));
  const story = screen.getByTestId("team-story");
  expect(story.textContent).toContain('team_threads.plan.step {"number":1} · Add the setting');
  expect(story.textContent).toContain("team_threads.plan.unreadable");
  expect(story.textContent).toContain("The reply has no team-plan block.");
  const builds = within(story).getAllByTestId("team-story-step_build");
  expect(builds).toHaveLength(3);
  expect(builds[2].textContent).toContain("No retry hook");
  expect(within(story).getByTestId("team-notice-step_accepted").textContent).toContain('"title":"Add the setting"');
  expect(within(story).getByTestId("team-thread-issues").textContent).toContain('team_threads.issues.step {"number":1}');
  expect(within(story).getByTestId("team-story-live-m3")).toBeTruthy();

  // The whole plan unfolds in place.
  const [, readable] = within(story).getAllByTestId("team-story-plan_version");
  fireEvent.click(within(readable).getByRole("button"));
  const plan = within(readable).getByTestId("team-entry-plan");
  expect(plan.textContent).toContain("Use it in the uploader");
  expect(plan.textContent).toContain("pytest tests/test_config.py passes");
}, 20_000);

it("asks the person about a step the reviewer never approves, and can take it as it is", async () => {
  const stuck: TeamThread = {
    ...thread, state: "needs_input", reason: "step_disagreement", rounds: { ...thread.rounds, review: 3 },
    members: thread.members.map((item) => ({ ...item, working: false })),
    plan: { ...thread.plan!, revision: { step: 2, title: "Use it", status: "blocked", note: "No retry hook", plan_change: "", by: "m2" } },
  };
  const calls = mount("t1", stuck);

  const waiting = await screen.findByTestId("team-thread-waiting");
  expect(waiting.textContent).toContain('team_threads.reason.step_disagreement');
  expect(waiting.textContent).toContain('"number":2');
  fireEvent.click(screen.getByTestId("team-plan-progress"));
  expect(screen.getByTestId("team-plan-revision").textContent).toContain("No retry hook");
  fireEvent.click(screen.getByRole("button", { name: "team_threads.accept_step" }));
  await waitFor(() => expect(calls.some((call) => call.url === "/api/team-threads/t1/accept" && call.method === "POST")).toBe(true));
});

it("derives the board of the new mode, with the band the team works in before anything is filed", () => {
  const planning: TeamThread = {
    ...thread, phase: "planning", rounds: { plan: 1, review: 0, step: 0, plan_round: 2, final: 0 },
    members: [member("m1", "Claude", "planner", { working: true }), member("m2", "Codex", "builder")],
    entries: thread.entries.slice(0, 5),
  };
  const bands = buildBoard(planning).filter((band): band is StepBand => band.type === "step");
  expect(bands.map((band) => [band.key, band.current])).toEqual([["planning:1", false], ["planning:2", true]]);
  // Without a reviewer the builder reads the plan.
  expect(bands[1].cells.map((cell) => [cell.role, cell.live])).toEqual([["writes_plan", true], ["reviews_plan", false]]);

  const final: TeamThread = { ...thread, phase: "final", rounds: { ...thread.rounds, final: 1 }, entries: thread.entries.slice(0, 1) };
  const [finalBand] = buildBoard(final).filter((band): band is StepBand => band.type === "step");
  expect(finalBand.key).toBe("final:1");
  expect(finalBand.cells.map((cell) => cell.role)).toEqual(["final_reviewer", "answers", "final_reviewer"]);

  const building: TeamThread = { ...thread, rounds: { ...thread.rounds, step: 0 }, entries: thread.entries.slice(0, 5) };
  const [stepBand] = buildBoard(building).filter((band): band is StepBand => band.type === "step" && band.step === "step");
  expect([stepBand.key, stepBand.number, stepBand.title]).toEqual(["step:1:2", 2, "Use it in the uploader"]);
  expect(stepBand.cells.map((cell) => cell.role)).toEqual(["none", "builds_step", "reviews_step"]);
});

it("starts a planner-and-builder team with a role per member", async () => {
  const calls = mount(TEAM_DRAFT, { ...thread, team_id: "t9" });

  await screen.findByTestId("team-draft-member-2");
  expect(screen.queryByTestId("team-draft-role-0")).toBeNull();
  fireEvent.click(screen.getByTestId("team-draft-mode-planner_builder"));
  expect(screen.getByTestId("team-draft-mode-planner_builder").getAttribute("aria-checked")).toBe("true");
  expect(screen.getByText("team_threads.draft.body_planned")).toBeTruthy();
  expect([0, 1, 2].map((index) => screen.getByTestId(`team-draft-role-${index}`).dataset.value)).toEqual(["planner", "builder", "reviewer"]);

  fireEvent.change(screen.getByTestId("team-draft-task"), { target: { value: "Add a retry to the uploader" } });
  fireEvent.click(screen.getByTestId("team-draft-start"));
  await waitFor(() => expect(calls.find((call) => call.method === "POST")?.body).toEqual({
    task: "Add a retry to the uploader",
    cwd: "/work/shop",
    mode: "planner_builder",
    seats: [
      { provider: "claude-api", model: "", role: "planner" },
      { provider: "openai-codex", model: "", role: "builder" },
      { provider: "antigravity", model: "", role: "reviewer" },
    ],
  }));
});

it("will not start a team without exactly one planner and one builder", async () => {
  const calls = mount(TEAM_DRAFT, thread);

  await screen.findByTestId("team-draft-member-2");
  fireEvent.click(screen.getByTestId("team-draft-mode-planner_builder"));
  fireEvent.change(screen.getByTestId("team-draft-task"), { target: { value: "Add a retry" } });
  const start = screen.getByTestId("team-draft-start") as HTMLButtonElement;
  expect(start.disabled).toBe(false);

  // Two planners and no builder: nobody would build, and nobody check the plan.
  fireEvent.click(within(screen.getByTestId("team-draft-role-1")).getByText("team_threads.member_role.planner"));
  expect(screen.getByTestId("team-draft-roles-invalid")).toBeTruthy();
  expect(start.disabled).toBe(true);
  fireEvent.click(within(screen.getByTestId("team-draft-role-2")).getByText("team_threads.member_role.builder"));
  expect(start.disabled).toBe(true);
  fireEvent.click(within(screen.getByTestId("team-draft-role-0")).getByText("team_threads.member_role.reviewer"));
  expect(screen.queryByTestId("team-draft-roles-invalid")).toBeNull();
  expect(start.disabled).toBe(false);
  // Back to peers: no roles go out, whatever was picked.
  fireEvent.click(screen.getByTestId("team-draft-mode-peers"));
  fireEvent.click(start);
  await waitFor(() => expect(calls.find((call) => call.method === "POST")?.body).toEqual({
    task: "Add a retry",
    cwd: "/work/shop",
    seats: [{ provider: "claude-api", model: "" }, { provider: "openai-codex", model: "" }, { provider: "antigravity", model: "" }],
  }));
});
