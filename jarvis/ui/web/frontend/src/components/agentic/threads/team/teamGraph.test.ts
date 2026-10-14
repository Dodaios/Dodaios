import { describe, expect, it } from "vitest";
import type { TeamThread } from "@/lib/teamThreadsApi";
import { plainCommand } from "./memberLive";
import { buildGraph, canvasLines, exchangeLabel, exchangesBetween, latestExchange, withShortNames, YOU, type TeamGraph } from "./teamGraph";

type Member = TeamThread["members"][number];
const member = (id: string, name: string, extra: Partial<Member> = {}): Member => ({
  member_id: id, name, provider: name.toLowerCase(), model: "", effort: "", family: name.toLowerCase(),
  session_id: `session-${id}`, state: "active", left_reason: "", working: false, since_ms: 0, waiting: false, role: "",
  ...extra,
});

const entry = (seq: number, kind: string, author: string, payload: object, phase: string, round = 0) =>
  ({ seq, ts_ms: seq, kind, author, phase, round, payload }) as TeamThread["entries"][number];

const base: TeamThread = {
  team_id: "t1", title: "Add a retry", task: "Add a retry", cwd: "/work", mode: "peers", plan: null,
  state: "running", phase: "draft", reason: "", note: "",
  limits: { max_minutes: 90, max_turns: 40, plan_rounds: 3, review_rounds: 3, turn_minutes: 30, max_cost_usd: 0 },
  usage: { elapsed_ms: 0, turns: 0, cost_usd: 0, cost_partial: false },
  rounds: { plan: 0, review: 0 }, builder: "",
  members: [member("m1", "Claude"), member("m2", "GPT"), member("m3", "Gemini")],
  entries: [], issues: [], created_ms: 1, updated_ms: 1,
};

/** The lines as `from->to: kinds (tier)`, sorted, for a readable comparison. */
const lines = (graph: TeamGraph) => graph.edges
  .map((line) => `${line.id}: ${line.exchanges.map((item) => item.kind).join(",")} (${line.tier})`)
  .sort();

const t = (key: string) => key;

/** A peers thread through a whole run: own plans, challenge, a master plan, a build and one review round. */
const peers: TeamThread = {
  ...base, phase: "review", builder: "m1", rounds: { plan: 1, review: 1 },
  entries: [
    entry(1, "user", "user", { text: "Add a retry" }, "draft"),
    entry(2, "draft", "m1", { text: "A" }, "draft"),
    entry(3, "draft", "m2", { text: "B" }, "draft"),
    entry(4, "draft", "m3", { text: "C" }, "draft"),
    entry(5, "critique", "m2", { text: "x" }, "challenge"),
    entry(6, "critique", "m3", { text: "y" }, "challenge"),
    entry(7, "critique", "m1", { text: "z" }, "challenge"),
    entry(8, "plan", "m1", { text: "The plan" }, "converge", 1),
    entry(9, "vote", "m2", { agree: true, objections: [], plan_seq: 8 }, "converge", 1),
    entry(10, "vote", "m3", { agree: false, objections: ["No tests", "No timeout"], plan_seq: 8 }, "converge", 1),
    entry(11, "build", "m1", { text: "Built", files: ["app.py", "test_app.py"] }, "build"),
    entry(12, "review", "m2", { approve: true, findings: [] }, "review", 1),
  ],
};

describe("the team graph", () => {
  it("draws every handoff of the peers mode as a line from who sent it to who read it", () => {
    const graph = buildGraph({ ...peers, members: [member("m1", "Claude"), member("m2", "GPT"), member("m3", "Gemini", { working: true })] });
    expect(lines(graph)).toEqual([
      // A build goes to every reviewer; the reviewer still at work is reading it now.
      "m1->m2: own_plan,master_plan,change (current)",
      "m1->m3: own_plan,master_plan,change (live)",
      // Votes and the review go back to the plan's author and builder.
      "m2->m1: own_plan,critique,vote,review (current)",
      "m2->m3: own_plan (past)",
      "m3->m1: own_plan,critique,vote (past)",
      "m3->m2: own_plan (past)",
      // The task reached everyone; it is an old line by now.
      "you->m1: task (past)",
      "you->m2: task (past)",
      "you->m3: task (past)",
    ]);
    // The nodes: the person, then each member in its place; nothing depends on the entries.
    expect(graph.nodes.map((node) => node.id)).toEqual([YOU, "m1", "m2", "m3"]);
    expect(buildGraph(base).nodes.map((node) => [node.x, node.y])).toEqual(graph.nodes.map((node) => [node.x, node.y]));
  });

  it("marks what a working member works on as live, in every step of the peers mode", () => {
    const working = (id: string) => base.members.map((item) => (item.member_id === id ? { ...item, working: true } : item));
    const live = (thread: TeamThread) => buildGraph(thread).edges.filter((line) => line.tier === "live").map((line) => line.id).sort();

    // Own plans: the task.
    expect(live({ ...base, members: working("m2"), entries: peers.entries.slice(0, 1) })).toEqual(["you->m2"]);
    // Challenge: the other members' plans.
    expect(live({ ...base, phase: "challenge", members: working("m3"), entries: peers.entries.slice(0, 4) })).toEqual(["m1->m3", "m2->m3"]);
    // Master plan: its author reads the challenges; a voter reads the plan.
    expect(live({ ...base, phase: "converge", rounds: { plan: 1, review: 0 }, members: working("m1"), entries: peers.entries.slice(0, 7) }))
      .toEqual(["m2->m1", "m3->m1"]);
    expect(live({ ...base, phase: "converge", rounds: { plan: 1, review: 0 }, members: working("m3"), entries: peers.entries.slice(0, 9) }))
      .toEqual(["m1->m3"]);
    // The builder answers the review that asked for changes.
    const changes = entry(13, "review", "m3", { approve: false, findings: [{ severity: "blocking", where: "app.py:3", issue: "Loops", fix: "Stop" }] }, "review", 1);
    expect(live({ ...peers, members: working("m1"), entries: [...peers.entries, changes] })).toEqual(["m3->m1"]);
    // A paused team has nothing in flight.
    expect(live({ ...peers, state: "paused", members: working("m3") })).toEqual([]);
  });

  it("follows the planner-and-builder mode: plan to its readers, steps to the reviewer, a blocked step back to the planner", () => {
    const steps = [{ title: "Setting", goal: "g", done_when: "d" }, { title: "Use it", goal: "g", done_when: "d" }];
    const planned: TeamThread = {
      ...base, mode: "planner_builder", phase: "steps", builder: "m2", rounds: { plan: 1, review: 1, step: 2, plan_round: 1, final: 0 },
      members: [member("m1", "Claude", { role: "planner" }), member("m2", "Codex", { role: "builder", working: true }), member("m3", "Gemini", { role: "reviewer" })],
      entries: [
        entry(1, "user", "user", { text: "Add a retry" }, "planning"),
        entry(2, "plan_version", "m1", { valid: false, error: "no block" }, "planning", 1),
        entry(3, "plan_version", "m1", { valid: true, version: 1, steps }, "planning", 1),
        entry(4, "plan_review", "m3", { agree: true, objections: [], plan_seq: 3, version: 1 }, "planning", 1),
        entry(5, "step_build", "m2", { version: 1, number: 1, title: "Setting", status: "done", files: ["config.py"] }, "steps", 1),
        entry(6, "step_review", "m3", { approve: true, findings: [], version: 1, number: 1 }, "steps", 1),
        entry(7, "step_build", "m2", { version: 1, number: 2, title: "Use it", status: "blocked", note: "No hook" }, "steps", 1),
        entry(8, "step_review", "m3", {
          approve: false, version: 1, number: 2,
          findings: [{ severity: "blocking", where: "a", issue: "b", fix: "c" }, { severity: "minor", where: "", issue: "d", fix: "" }],
        }, "steps", 1),
      ],
    };
    const graph = buildGraph(planned);
    expect(lines(graph)).toEqual([
      // An unreadable plan goes nowhere; the readable one reaches the reviewer and the builder.
      "m1->m2: plan_version (past)",
      "m1->m3: plan_version (past)",
      // The step the builder works on came back with findings: that line is live.
      "m2->m1: plan_change (current)",
      "m2->m3: step,step (current)",
      "m3->m1: plan_review (past)",
      "m3->m2: step_review,step_review (live)",
      "you->m1: task (past)",
      "you->m2: task (past)",
      "you->m3: task (past)",
    ]);
    const labels = graph.edges.map((line) => [line.id, exchangeLabel(latestExchange(line)!, t, "en")]);
    expect(Object.fromEntries(labels)).toMatchObject({
      "m1->m2": "team_threads.plan.version_tag",
      "m2->m3": "team_threads.plan.step · team_threads.plan.blocked",
      "m3->m2": "team_threads.plan.step · team_threads.graph.findings_other · team_threads.graph.blocking_one",
      "m2->m1": "team_threads.graph.plan_change",
    });
    // Both ways between two members, in order, for the exchange view.
    expect(exchangesBetween(graph, "m2", "m3").map((item) => [item.seq, item.from])).toEqual([[5, "m2"], [6, "m3"], [7, "m2"], [8, "m3"]]);

    // Once the review is answered by a new build, the plan step is what the builder reads next.
    const next = { ...planned, rounds: { ...planned.rounds, step: 3 } };
    expect(buildGraph(next).edges.filter((line) => line.tier === "live").map((line) => line.id)).toEqual(["m1->m2"]);
  });

  it("draws both directions as one two-way line where they carried the same", () => {
    const challenge: TeamThread = { ...base, phase: "challenge", members: base.members.slice(0, 2), entries: peers.entries.slice(0, 3) };
    const drawn = canvasLines(buildGraph(challenge));
    // The two own plans crossed: one line both ways, counted once per plan.
    expect(drawn.map((item) => [item.line.id, item.partner?.id ?? null, item.count])).toEqual(
      expect.arrayContaining([["m1->m2", "m2->m1", 2]]),
    );
    // A vote back is not the plan that went out: two lines.
    const voted = canvasLines(buildGraph({ ...peers, phase: "converge", rounds: { plan: 1, review: 0 }, entries: peers.entries.slice(0, 9) }));
    expect(voted.find((item) => item.line.id === "m2->m1")?.partner).toBeNull();
    expect(voted.find((item) => item.line.id === "m1->m2")?.partner).toBeNull();
  });

  it("puts what went across into words", () => {
    const say = (kind: string, payload: object, round = 0) => {
      const graph = buildGraph({ ...base, phase: "done", state: "done", entries: [entry(1, "user", "user", { text: "x" }, "draft"), entry(2, kind, "m1", payload, "review", round)] });
      const line = graph.edges.find((item) => item.from === "m1");
      return line ? exchangeLabel(latestExchange(line)!, t, "en") : "";
    };
    expect(say("plan", { text: "p" }, 2)).toBe("team_threads.graph.master_plan · team_threads.round");
    expect(say("build", { files: ["a.py"] })).toBe("team_threads.graph.change · team_threads.graph.files_one");
    expect(say("draft", { text: "d" })).toBe("team_threads.graph.own_plan");
  });

  it("shows a member that left only on the lines it could still read", () => {
    const left = buildGraph({
      ...base, phase: "challenge",
      members: [member("m1", "Claude"), member("m2", "GPT"), member("m3", "Gemini", { state: "left", left_reason: "not signed in" })],
      entries: [entry(1, "user", "user", { text: "x" }, "draft"), entry(2, "draft", "m1", { text: "a" }, "draft")],
    });
    expect(left.edges.map((line) => line.id).sort()).toEqual(["m1->m2", "you->m1", "you->m2"]);
  });

  it("drops the model from a name unless two members would then be called the same", () => {
    const named = withShortNames({ ...base, members: [
      member("m1", "Anthropic Claude · claude-sonnet-5-5", { model: "claude-sonnet-5-5" }),
      member("m2", "OpenAI Codex · gpt-6-luna", { model: "gpt-6-luna" }),
      member("m3", "Anthropic Claude · claude-haiku-5-5", { model: "claude-haiku-5-5" }),
    ] });
    expect(named.members.map((item) => item.name)).toEqual([
      "Anthropic Claude · claude-sonnet-5-5", "OpenAI Codex", "Anthropic Claude · claude-haiku-5-5",
    ]);
    expect(withShortNames(base)).toBe(base);
  });

  it("reads a shell call without its shell", () => {
    expect(plainCommand(String.raw`"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -Command "pytest -q"`)).toBe("pytest -q");
    expect(plainCommand("bash -lc 'ls -la'")).toBe("ls -la");
    expect(plainCommand("git status")).toBe("git status");
    expect(plainCommand(String.raw`"C:\pwsh.exe" -Command "Get-ChildItem -Force; Write-Output …`)).toBe("Get-ChildItem -Force; Write-Output …");
  });
});
