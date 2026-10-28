import { describe, expect, it } from "vitest";
import en from "@/i18n/locales/en.json";
import type { ReasoningBlock, TextBlock, ToolBlock, TurnBlock, TurnItem } from "../reduce";
import {
  activityOf, activityPhrase, capPhrase, PHRASE_MAX, phraseKey, presenceForFamily, sameStep, serviceName, toolActivity,
  type Activity, type ActivityFamily,
} from "./activityModel";

/** The English catalogue as `t`, so the phrases are the real ones. */
function t(key: string): string {
  let at: unknown = en;
  for (const part of key.split(".")) at = (at as Record<string, unknown>)?.[part];
  return typeof at === "string" ? at : key;
}

function turn(blocks: TurnBlock[], status: TurnItem["status"] = "running"): TurnItem {
  return {
    type: "turn", id: "t1", provider: "p", model: "", effort: "", runner: "api", status, blocks,
    startedMs: 1, durationMs: null, usage: null, liveUsage: null, costUsd: null, error: null,
  };
}
const text = (value: string, id = "x1"): TextBlock => ({ kind: "text", id, text: value });
const thought = (id = "r1"): ReasoningBlock => ({ kind: "reasoning", id, text: "…", durationMs: null, live: true, startedMs: 1 });
function call(name: string, input: unknown = {}, output: string | null = null, extra: Partial<ToolBlock> = {}): ToolBlock {
  return { kind: "tool", callId: `c-${name}`, name, input, output, isError: false, durationMs: null, approval: null, startedMs: 1, ...extra };
}

const phrase = (block: ToolBlock, nameOf?: (v: string) => string) => activityPhrase(toolActivity(block, nameOf), t);

describe("toolActivity: every family has its own words", () => {
  const cases: [ToolBlock, ActivityFamily, string][] = [
    [call("WebSearch", { query: "rust async traits" }), "searching", "Looking up “rust async traits”"],
    [call("web_search"), "searching", "Looking it up online"],
    [call("Grep", { pattern: "useStickToBottom" }), "searching", "Searching for “useStickToBottom”"],
    [call("Read", { file_path: "C:/repo/src/app.ts" }), "reading", "Opening app.ts"],
    [call("Read", { file_path: "shot.png" }), "reading", "Looking at an image"],
    [call("WebFetch", { url: "https://www.example.org/docs" }), "reading", "Reading a page on example.org"],
    [call("Edit", { file_path: "/repo/src/store.ts", old_string: "a", new_string: "b" }), "writing", "Editing store.ts"],
    [call("Write", { file_path: "notes.md", content: "x" }), "writing", "Writing notes.md"],
    [call("Bash", { command: "cd \"C:/repo\" && npm test" }), "running", "Running npm"],
    [call("shell", {}), "running", "At the terminal"],
    [call("browser_navigate", { url: "https://github.com/x" }), "browsing", "On github.com"],
    [call("mcp__dodaios__society_memory_recall", { query: "x" }), "recalling", "Checking its notes"],
    [call("mcp__dodaios__society_wiki_note", { title: "Plan" }), "noting", "Making a note"],
    [call("society_routines", {}), "setting_up", "Setting things up"],
    [call("unknown_tool", {}), "working", ""],
  ];
  it.each(cases)("%#: %s", (block, family, words) => {
    const activity = toolActivity(block);
    expect(activity.family).toBe(family);
    if (words) expect(activityPhrase(activity, t)).toBe(words);
    else expect(activityPhrase(activity, t)).not.toMatch(/run_view/);
  });

  it("names a connector after its service, never after its transport", () => {
    expect(phrase(call("mcp__gmail__send_email", { to: "a@b.c" }))).toBe("Working in Gmail");
    expect(phrase(call("mcp__linear-server__list_issues"))).toBe("Working in Linear");
    expect(toolActivity(call("mcp__linear-server__list_issues")).family).toBe("connecting");
    // Our own MCP server is the road; the plugin behind it is the destination.
    expect(phrase(call("mcp__dodaios__gmail_search", { q: "x" }))).toBe("Working in Gmail");
    expect(serviceName("github_mcp")).toBe("Github");
  });

  it("writes to a teammate by the name a person knows", () => {
    const block = call("mcp__dodaios__society_message_agent", { target: "a7", text: "hi" });
    expect(phrase(block, (id) => (id === "a7" ? "Scout" : id))).toBe("Writing to Scout");
    expect(toolActivity(block).peer).toBe("a7");
    expect(phrase(call("society_message_agent", {}))).toBe("Writing to a teammate");
  });

  it("the ask tool and the credential tool wait for the person", () => {
    expect(phrase(call("mcp__dodaios__society_ask_user", { questions: [] }))).toBe("Needs your answer");
    expect(toolActivity(call("AskUserQuestion")).family).toBe("waiting");
    expect(toolActivity(call("society_request_credential")).family).toBe("waiting");
  });

  it("a helper the agent starts is delegation", () => {
    expect(phrase(call("Task", { description: "Explore the auth code", prompt: "…" }))).toBe("Briefing a helper: Explore the auth code");
    expect(phrase(call("spawn_agent", {}))).toBe("A helper is on it");
  });
});

describe("activityOf", () => {
  it("thinks before anything happened and between steps", () => {
    expect(activityOf(turn([]))?.family).toBe("thinking");
    expect(activityOf(turn([thought()]))?.family).toBe("thinking");
    expect(activityOf(turn([call("Read", { file_path: "a.ts" }, "ok")]))?.family).toBe("thinking");
  });

  it("composes while words stream and names the running call", () => {
    expect(activityOf(turn([text("Checking.")]))?.family).toBe("composing");
    expect(activityOf(turn([text("x"), call("Bash", { command: "git status" })]))?.target).toBe("git");
  });

  it("a waiting card wins over every later block", () => {
    const question = call("society_ask_user", {}, null, { question: { closed: false } as ToolBlock["question"] });
    expect(activityOf(turn([question, thought("r2")]))?.phrase).toBe("waiting");
    const approval = call("Bash", { command: "rm -rf x" }, null, { approval: { approvalId: "a", summary: "", decision: null } });
    expect(activityOf(turn([approval]))?.phrase).toBe("waiting_approval");
    // Answered here and on its way: the line stops asking for an OK at once.
    const answering = call("Bash", { command: "rm -rf x" }, null, { approval: { approvalId: "a", summary: "", decision: null, answering: true } });
    expect(activityOf(turn([answering]))?.phrase).not.toBe("waiting_approval");
  });

  it("question polls are plumbing, and running helpers keep the line on delegation", () => {
    const poll = call("society_ask_user", { wait_for: "q1" }, "{\"status\":\"waiting\"}");
    expect(activityOf(turn([thought(), poll]))?.family).toBe("thinking");
    const helper = call("Task", { description: "Run tests" }, "Async agent launched", {
      subagent: { status: "running", description: "Run tests" } as ToolBlock["subagent"],
    });
    expect(activityOf(turn([helper]))?.family).toBe("delegating");
  });

  it("says nothing once the turn is over", () => {
    expect(activityOf(turn([text("Done.")], "done"))).toBeNull();
    expect(activityOf(turn([], "cancelled"))).toBeNull();
  });
});

describe("phrasing", () => {
  const a = (episode: string): Activity => ({ family: "thinking", phrase: "thinking", target: "", episode, brand: "", peer: "" });

  it("keeps one variant per episode, and different episodes vary", () => {
    expect(phraseKey(a("r1"))).toBe(phraseKey(a("r1")));
    const keys = new Set(["r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8"].map((id) => phraseKey(a(id))));
    expect(keys.size).toBeGreaterThan(1);
    for (const key of keys) expect(t(key)).not.toBe(key);
  });

  it("caps at 60 characters and keeps the verb whole", () => {
    const long = toolActivity(call("Grep", { pattern: "x".repeat(200) }));
    const words = activityPhrase(long, t);
    expect(words.length).toBeLessThanOrEqual(PHRASE_MAX);
    expect(words.startsWith("Searching for “")).toBe(true);
    expect(words).toMatch(/x…”$/);
    expect(capPhrase("  a\n\n b  ")).toBe("a b");
  });

  it("same family and target is the same step, whatever the episode", () => {
    const one = toolActivity(call("Read", { file_path: "a.ts" }));
    const two = { ...one, episode: "other" };
    expect(sameStep(one, two)).toBe(true);
    expect(sameStep(one, toolActivity(call("Read", { file_path: "b.ts" })))).toBe(false);
  });

  it("every family plays a scene on the face", () => {
    const families: ActivityFamily[] = ["thinking", "composing", "searching", "reading", "writing", "running", "browsing",
      "recalling", "noting", "messaging", "delegating", "connecting", "setting_up", "waiting", "working"];
    for (const family of families) expect(presenceForFamily(family)).toBeTruthy();
  });
});
