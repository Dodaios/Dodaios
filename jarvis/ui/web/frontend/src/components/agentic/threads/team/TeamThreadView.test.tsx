import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { IdeProject } from "@/lib/agenticIdeApi";
import type { TeamThread } from "@/lib/teamThreadsApi";
import { TEAM_DRAFT, useIdeThreadsStore } from "@/store/ideThreads";
import { buildBoard, gist, type StepBand } from "./board";
import { closeAllMemberStreams } from "./memberStreams";
import { TeamThreadView } from "./TeamThreadView";

// The canvas draws with a graph library that needs a real layout engine; this
// stand-in keeps its contract: a button per node and per line.
vi.mock("./TeamCanvas", () => ({
  default: ({ graph, onOpenNode, onOpenEdge, selectedNode, selectedEdge }: {
    graph: { nodes: { id: string }[]; edges: { id: string; tier: string }[] };
    onOpenNode: (id: string) => void; onOpenEdge: (id: string) => void; selectedNode: string | null; selectedEdge: string | null;
  }) => <div data-testid="team-canvas">
    {graph.nodes.map((node) => <button key={node.id} type="button" data-testid={`team-node-${node.id}`}
      aria-pressed={selectedNode === node.id} onClick={() => onOpenNode(node.id)}>{node.id}</button>)}
    {graph.edges.map((line) => <button key={line.id} type="button" data-testid={`team-edge-${line.id}`} data-tier={line.tier}
      aria-pressed={selectedEdge === line.id} onClick={() => onOpenEdge(line.id)}>{line.id}</button>)}
  </div>,
}));

vi.mock("@/i18n", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/i18n")>()),
  useT: () => (key: string) => key,
  fill: (template: string, vars: Record<string, unknown>) => `${template} ${JSON.stringify(vars)}`,
}));

/** A member's own thread socket, driven by hand. */
class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((message: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(readonly url: string) { FakeSocket.instances.push(this); }
  close() { this.closed = true; }
  frame(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) }); }
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
});
afterEach(() => { cleanup(); closeAllMemberStreams(); vi.unstubAllGlobals(); });

const project = { id: "p1", name: "Shop", path: "/work/shop", workspaces: [] } as unknown as IdeProject;

const member = (id: string, name: string, extra: Partial<TeamThread["members"][number]> = {}) => ({
  member_id: id, name, provider: name.toLowerCase(), model: "", effort: "", family: name.toLowerCase(),
  session_id: `session-${id}`, state: "active" as const, left_reason: "", working: false, since_ms: 0, waiting: false,
  role: "" as TeamThread["members"][number]["role"],
  ...extra,
});

const entry = (seq: number, kind: string, author: string, payload: object, phase = "review", round = 0) =>
  ({ seq, ts_ms: seq, kind, author, phase, round, payload }) as TeamThread["entries"][number];

const thread: TeamThread = {
  team_id: "t1", title: "Add a retry", task: "Add a retry", cwd: "/work/shop", mode: "peers", plan: null,
  state: "needs_input", phase: "review", reason: "review_disagreement", note: "",
  limits: { max_minutes: 90, max_turns: 40, plan_rounds: 3, review_rounds: 3, turn_minutes: 30, max_cost_usd: 0 },
  usage: { elapsed_ms: 12 * 60_000, turns: 14, cost_usd: 0, cost_partial: true },
  rounds: { plan: 1, review: 3 },
  builder: "m1",
  members: [member("m1", "Claude"), member("m2", "GPT"), member("m3", "Gemini", { state: "left", left_reason: "not signed in" })],
  entries: [
    entry(1, "user", "user", { text: "Add a retry" }, "draft"),
    entry(2, "draft", "m1", { text: "## Plan\nUse **backoff** with jitter.\n\n```py\nretry()\n```" }, "draft"),
    entry(3, "draft", "m2", { text: "Retry three times." }, "draft"),
    entry(4, "plan", "m1", { text: "The master plan" }, "converge", 1),
    entry(5, "vote", "m2", { text: "ok", agree: true, objections: [], plan_seq: 4 }, "converge", 1),
    entry(6, "notice", "team", { code: "plan_agreed", rounds: 1, by: "m1" }, "converge"),
    entry(7, "build", "m1", { text: "Built it", files: ["app.py", "test_app.py"], stat: "2 files" }, "build"),
    entry(8, "review", "m2", {
      text: "Not yet", approve: false,
      findings: [{ severity: "blocking", where: "app.py:3", issue: "Loops forever on a 404", fix: "Stop on 4xx" }],
    }, "review", 3),
    entry(9, "summary", "team", {
      outcome: "review_disagreement", rounds: 3,
      open: [{ member_id: "m2", name: "GPT", items: ["app.py:3: Loops forever on a 404"] }],
    }, "review"),
  ],
  issues: [{ seq: 8, stage: "review", round: 3, by: "m2", severity: "blocking", where: "app.py:3", issue: "Loops forever on a 404", fix: "Stop on 4xx", resolved: false }],
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
    const entries = (data as TeamThread).entries.filter((item) => item.seq > after);
    return { ok: true, json: async () => (init?.method ? data : { ...(data as TeamThread), entries }) };
  });
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><TeamThreadView team={team} project={project} onScreen /></QueryClientProvider>);
  return calls;
}

it("opens as a room: the team on a canvas, the story beside it, the bounds above", async () => {
  const calls = mount("t1", thread);

  expect((await screen.findByTestId("team-thread-state")).textContent).toBe("team_threads.state.needs_input");
  // Every member and the person are on the canvas, every handoff is a line.
  const canvas = await screen.findByTestId("team-canvas");
  for (const id of ["you", "m1", "m2", "m3"]) expect(within(canvas).getByTestId(`team-node-${id}`)).toBeTruthy();
  expect(within(canvas).getByTestId("team-edge-m2->m1").textContent).toBe("m2->m1");
  // Nobody works: the side column shows the shared story, step by step.
  const story = screen.getByTestId("team-story");
  expect(screen.getByTestId("team-tab-story").getAttribute("aria-selected")).toBe("true");
  expect(within(story).getByTestId("team-entry-user").textContent).toBe("Add a retry");
  expect(within(story).getAllByTestId("team-story-draft").map((row) => row.textContent)).toEqual([
    expect.stringContaining("Plan · Use backoff with jitter."), expect.stringContaining("Retry three times."),
  ]);
  // A contribution says to whom it went; a review shows its blocking finding.
  expect(within(story).getByTestId("team-story-plan").textContent).toContain("→ GPT");
  expect(within(story).getByTestId("team-story-review").textContent).toContain("app.py:3: Loops forever on a 404");
  expect(within(story).getByTestId("team-notice-plan_agreed").textContent).toContain('"member":"Claude"');
  expect(within(story).getByTestId("team-summary-review_disagreement").textContent).toContain("app.py:3: Loops forever on a 404");
  expect(within(story).getByTestId("team-thread-issues").textContent).toContain("team_threads.issues.open");
  expect(screen.getByTestId("team-thread-usage").textContent).toContain('"minutes":12');
  expect(screen.getByTestId("team-thread-usage").textContent).toContain('"turns":14');

  fireEvent.click(screen.getByRole("button", { name: "team_threads.accept_work" }));
  await waitFor(() => expect(calls.some((call) => call.url === "/api/team-threads/t1/accept" && call.method === "POST")).toBe(true));
  // The first read asks for everything; nothing was fetched twice.
  expect(calls.find((call) => call.url.startsWith("/api/team-threads/t1?"))?.url).toBe("/api/team-threads/t1?after=0");
  expect(screen.getAllByTestId("team-entry-user")).toHaveLength(1);
  // Nobody works and no chat is open, so no member's thread is listened to.
  expect(FakeSocket.instances).toHaveLength(0);
});

it("unfolds a contribution of the story in place", async () => {
  mount("t1", thread);

  const [first] = await screen.findAllByTestId("team-story-draft");
  expect(within(first).queryByTestId("team-entry-body")).toBeNull();
  fireEvent.click(within(first).getByRole("button"));
  const body = within(first).getByTestId("team-entry-body");
  expect(within(body).getByText("backoff").tagName).toBe("STRONG");
  fireEvent.click(within(first).getByRole("button"));
  expect(within(first).queryByTestId("team-entry-body")).toBeNull();
});

it("follows the member at work: its chat streams in beside the canvas over one socket", async () => {
  const working: TeamThread = {
    ...thread, state: "running", reason: "", phase: "challenge", builder: "", rounds: { plan: 0, review: 0 },
    members: [member("m1", "Claude", { working: true, since_ms: Date.now() - 65_000 }), member("m2", "GPT")],
    entries: thread.entries.slice(0, 3).concat(entry(4, "critique", "m2", { text: "Claude skips the timeout." }, "challenge")),
    issues: [],
  };
  mount("t1", working);

  // Following is on: the working member's chat is open, its node marked.
  const chat = await screen.findByTestId("team-chat-m1");
  expect(screen.getByTestId("team-tab-member:m1").getAttribute("aria-selected")).toBe("true");
  expect(screen.getByTestId("team-node-m1").getAttribute("aria-pressed")).toBe("true");
  // What it works on flows on the canvas: the other member's plan.
  expect(screen.getByTestId("team-edge-m2->m1").dataset.tier).toBe("live");
  // The chat and the member's status share one socket.
  await waitFor(() => expect(FakeSocket.instances).toHaveLength(1));
  const socket = FakeSocket.instances[0];
  expect(socket.url).toContain("/api/agent-chat/sessions/session-m1/ws");
  expect(chat.textContent).toContain("team_threads.live_starting");

  vi.useFakeTimers();
  try {
    act(() => {
      socket.frame({ type: "snapshot", events: [
        { seq: 1, ts_ms: 1, kind: "user_message", payload: { text: "Team thread: challenge the other plans\n\nThe plan of GPT", author: { agent_id: "team", name: "Team" } } },
        { seq: 2, ts_ms: 2, kind: "turn_started", payload: { turn_id: "t", provider: "claude-api", model: "", runner: "claude-cli" } },
        { seq: 3, ts_ms: 3, kind: "tool_call", payload: { turn_id: "t", call_id: "c1", name: "Read", input: { file_path: "/work/shop/app.py" } } },
      ] });
      socket.frame({ type: "event", event: { seq: 4, ts_ms: 4, kind: "tool_call", payload: { turn_id: "t", call_id: "c2", name: "Bash", input: { command: "pytest -q" } } } });
      vi.advanceTimersByTime(400);
    });
  } finally {
    vi.useRealTimers();
  }
  // The coordinator's brief is folded to its first line; the turn shows its steps.
  expect(within(chat).getByTestId("team-chat-brief").textContent).toContain("Team thread: challenge the other plans");
  expect(chat.textContent).toContain("pytest -q");
  expect(chat.textContent).not.toContain("team_threads.live_starting");
  expect(FakeSocket.instances).toHaveLength(1);
  // A working thread offers pause and stop, never the waiting banner.
  expect(screen.getByRole("button", { name: "team_threads.pause" })).toBeTruthy();
  expect(screen.queryByTestId("team-thread-waiting")).toBeNull();
});

it("switches chats and exchanges in place, and leaves for a member's full thread only with a way back", async () => {
  const calls = mount("t1", { ...thread, state: "running", reason: "" });

  // A node opens that member's chat in the side column; nothing navigates.
  fireEvent.click(await screen.findByTestId("team-node-m2"));
  expect(screen.getByTestId("team-chat-m2")).toBeTruthy();
  expect(screen.getByTestId("team-follow").getAttribute("aria-pressed")).toBe("false");
  expect(useIdeThreadsStore.getState().selection.sessionId).not.toBe("session-m2");
  // A line shows what went across it, both ways, the newest open; Escape returns to the chat.
  fireEvent.click(screen.getByTestId("team-edge-m2->m1"));
  const exchange = screen.getByTestId("team-exchange");
  expect(within(exchange).getAllByTestId("team-exchange-item").length).toBeGreaterThan(2);
  expect(within(exchange).getAllByTestId("team-entry-body")).toHaveLength(1);
  expect(exchange.textContent).toContain("Loops forever on a 404");
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByTestId("team-exchange")).toBeNull();
  expect(screen.getByTestId("team-chat-m2")).toBeTruthy();
  // Arrow keys walk the tabs.
  fireEvent.keyDown(screen.getByTestId("team-tab-member:m2"), { key: "ArrowLeft" });
  expect(screen.getByTestId("team-chat-m1")).toBeTruthy();

  // The person steps in for the whole team.
  const field = screen.getByTestId("team-thread-message");
  fireEvent.change(field, { target: { value: "Keep the public API unchanged" } });
  fireEvent.keyDown(field, { key: "Enter" });
  await waitFor(() => expect(calls.find((call) => call.url.endsWith("/message"))?.body).toEqual({ text: "Keep the public API unchanged" }));

  // The full thread remembers the team it came from.
  fireEvent.click(screen.getByTestId("team-chat-open-full"));
  expect(useIdeThreadsStore.getState().selection).toEqual({ projectId: "p1", sessionId: "session-m1", fromTeam: "t1" });
});

it("comes back to the chat it left for a member's full thread", async () => {
  mount("t1", { ...thread, state: "running", reason: "" });
  fireEvent.click(await screen.findByTestId("team-node-m2"));
  fireEvent.click(screen.getByTestId("team-chat-open-full"));
  cleanup();
  mount("t1", { ...thread, state: "running", reason: "" });
  expect(await screen.findByTestId("team-chat-m2")).toBeTruthy();
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

it("leaves the start form for what was open before it", async () => {
  useIdeThreadsStore.getState().openThread("s1", "p1");
  useIdeThreadsStore.getState().newTeam("p1");
  mount(TEAM_DRAFT, { ...thread, team_id: "t9" });
  fireEvent.click(await screen.findByTestId("team-draft-cancel"));
  expect(useIdeThreadsStore.getState().selection).toEqual({ projectId: "p1", sessionId: "s1" });
});

it("derives the board: roles in a step nobody has filed for, rounds as bands of their own", () => {
  const start: TeamThread = {
    ...thread, state: "running", reason: "", phase: "draft", builder: "", rounds: { plan: 0, review: 0 },
    members: [member("m1", "Claude", { working: true }), member("m2", "GPT", { working: true })],
    entries: [thread.entries[0]], issues: [],
  };
  const [note, band] = buildBoard(start);
  expect(note.type).toBe("note");
  const draft = band as StepBand;
  expect(draft.key).toBe("draft");
  expect(draft.current).toBe(true);
  expect(draft.cells.map((cell) => [cell.role, cell.live])).toEqual([["plans", true], ["plans", true]]);

  // Two master-plan rounds are two bands; the author of each is who wrote its plan.
  const rounds: TeamThread = {
    ...start, phase: "converge", rounds: { plan: 2, review: 0 },
    members: [member("m1", "Claude"), member("m2", "GPT", { working: true })],
    entries: [
      thread.entries[0],
      entry(2, "plan", "m1", { text: "v1" }, "converge", 1),
      entry(3, "vote", "m2", { text: "no", agree: false, objections: ["No tests"] }, "converge", 1),
    ],
  };
  const steps = buildBoard(rounds).filter((item): item is StepBand => item.type === "step");
  expect(steps.map((item) => [item.key, item.current])).toEqual([["converge:1", false], ["converge:2", true]]);
  expect(steps[0].cells.map((cell) => cell.role)).toEqual(["author", "voter"]);
  expect(steps[1].cells.map((cell) => [cell.role, cell.live])).toEqual([["voter", false], ["author", true]]);

  // A paused thread keeps its current band but shows nobody as working.
  const paused = buildBoard({ ...rounds, state: "paused" }).filter((item): item is StepBand => item.type === "step");
  expect(paused.map((item) => item.key)).toEqual(["converge:1"]);
  expect(paused.flatMap((item) => item.cells.map((cell) => cell.live))).toEqual([false, false]);

  expect(gist("# Title\n\n- **Bold** point with `code`\n```\nskipped()\n```\n[link](http://x)")).toBe("Title · Bold point with code · link");
  expect(gist("x".repeat(400)).length).toBe(320);
});
