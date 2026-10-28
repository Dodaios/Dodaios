import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import en from "@/i18n/locales/en.json";
import { EMPTY_TIMELINE, reduceEvents, type TurnItem } from "../reduce";
import type { AgentChatEvent } from "@/lib/agentChatApi";
import { inspectorRows, previewOf, rowCounts } from "./inspectorRows";
import { clampWidth, inspectorDocked, INSPECTOR_MAX, INSPECTOR_MIN } from "./inspectorWidth";
import { WorkInspector } from "./WorkInspector";

afterEach(cleanup);

function t(key: string): string {
  let at: unknown = en;
  for (const part of key.split(".")) at = (at as Record<string, unknown>)?.[part];
  return typeof at === "string" ? at : key;
}

let seq = 0;
const ev = (kind: string, payload: Record<string, unknown>): AgentChatEvent =>
  ({ seq: ++seq, ts_ms: 1_000 + seq, kind, payload } as AgentChatEvent);
const turnOf = (events: AgentChatEvent[]) =>
  reduceEvents(EMPTY_TIMELINE, events).items.find((item) => item.type === "turn") as TurnItem;

/** Our own agent on a provider API: a thought, an edit and a reply. */
function brainTurn(): TurnItem {
  return turnOf([
    ev("user_message", { text: "Fix the typo" }),
    ev("turn_started", { turn_id: "t1", provider: "openai", model: "gpt-x", runner: "brain" }),
    ev("reasoning", { turn_id: "t1", message_id: "r1", text: "The typo is in the header.", duration_ms: 1200 }),
    ev("tool_call", { turn_id: "t1", call_id: "e1", name: "Edit", input: { file_path: "src/head.ts", old_string: "Helo", new_string: "Hello" } }),
    ev("tool_result", { turn_id: "t1", call_id: "e1", output: "ok", is_error: false, duration_ms: 40 }),
    ev("assistant_text", { turn_id: "t1", message_id: "m1", text: "Fixed it." }),
    ev("turn_finished", { turn_id: "t1", status: "done", duration_ms: 5_000 }),
  ]);
}

/** A coding CLI that reported a sub-agent with its own steps (Claude Code, Codex). */
function cliTurn(): TurnItem {
  return turnOf([
    ev("turn_started", { turn_id: "t2", provider: "claude-cli", runner: "claude-cli" }),
    ev("tool_call", { turn_id: "t2", call_id: "spawn", name: "Agent", input: { description: "Count files", prompt: "Run ls" } }),
    ev("subagent_started", { turn_id: "t2", agent_id: "spawn", description: "Count files", agent_type: "Explore", prompt: "Run ls", background: false }),
    ev("tool_call", { turn_id: "t2", agent_id: "spawn", call_id: "ls", name: "Bash", input: { command: "ls" } }),
    ev("tool_result", { turn_id: "t2", agent_id: "spawn", call_id: "ls", output: "a\nb", is_error: false }),
    ev("subagent_finished", { turn_id: "t2", agent_id: "spawn", status: "done", summary: "Two files.", duration_ms: 900 }),
    ev("tool_result", { turn_id: "t2", call_id: "spawn", output: "Two files.", is_error: false }),
    ev("assistant_text", { turn_id: "t2", message_id: "m2", text: "There are two files." }),
    ev("turn_finished", { turn_id: "t2", status: "done", duration_ms: 3_000 }),
  ]);
}

/** A runtime that streams nothing: only finished blocks arrive (Kimi, dsh). */
function quietTurn(): TurnItem {
  return turnOf([
    ev("turn_started", { turn_id: "t3", provider: "kimi", runner: "kimi-cli" }),
    ev("assistant_text", { turn_id: "t3", message_id: "m3", text: "All done." }),
    ev("turn_finished", { turn_id: "t3", status: "done", duration_ms: 2_000 }),
  ]);
}

function draw(turn: TurnItem, extra: Partial<Parameters<typeof WorkInspector>[0]> = {}) {
  const onClose = vi.fn();
  render(<WorkInspector turn={turn} agentName="Scout" color="#7ab6ef" width={420} onWidth={() => undefined}
    floating={false} onClose={onClose} {...extra} />);
  return { onClose };
}

describe("inspectorRows", () => {
  it("reads a brain turn in order: request, thought, call, reply", () => {
    const turn = brainTurn();
    const rows = inspectorRows(turn.blocks, { t, lang: "en", status: turn.status, prompt: "Fix the typo" });
    expect(rows.map((row) => row.kind)).toEqual(["prompt", "thought", "call", "reply"]);
    const edit = rows[2];
    expect(edit.label).toContain("head.ts");
    expect(edit.added).toBe(1);
    expect(edit.removed).toBe(1);
    expect(rowCounts(rows)).toEqual({ steps: 1, thoughts: 1, failed: 0 });
  });

  it("a CLI's helper is one row in the main trace; its steps stay in its own", () => {
    const turn = cliTurn();
    const rows = inspectorRows(turn.blocks, { t, lang: "en", status: turn.status });
    expect(rows.map((row) => row.kind)).toEqual(["helper", "reply"]);
    expect(rows[0].preview).toBe("Count files");
  });

  it("an ACP runtime (Hermes, OpenClaw) reads the same as any other", () => {
    const turn = turnOf([
      ev("turn_started", { turn_id: "t4", provider: "openrouter", runner: "hermes-cli" }),
      ev("reasoning", { turn_id: "t4", message_id: "r4", text: "", duration_ms: 300 }),
      ev("tool_call", { turn_id: "t4", call_id: "w1", name: "mcp__dodaios__society_wiki_note", input: { title: "Plan" } }),
      ev("tool_result", { turn_id: "t4", call_id: "w1", output: "{\"ok\":true}", is_error: false }),
      ev("assistant_text", { turn_id: "t4", message_id: "m4", text: "Noted." }),
      ev("turn_finished", { turn_id: "t4", status: "done", duration_ms: 1_000 }),
    ]);
    const rows = inspectorRows(turn.blocks, { t, lang: "en", status: turn.status });
    expect(rows.map((row) => row.kind)).toEqual(["thought", "call", "reply"]);
    // A thought whose words the provider keeps private still says it happened.
    expect(rows[0].label).toBe(en.run_view.row.thought_hidden);
  });

  it("a CLI that reports no sub-agent events still shows its spawn call as a helper", () => {
    const turn = turnOf([
      ev("turn_started", { turn_id: "t5", provider: "opencode", runner: "opencode-cli" }),
      ev("tool_call", { turn_id: "t5", call_id: "s1", name: "task", input: { description: "Scan logs", prompt: "Look for errors" } }),
      ev("tool_result", { turn_id: "t5", call_id: "s1", output: "No errors.", is_error: false }),
      ev("turn_finished", { turn_id: "t5", status: "done", duration_ms: 1_000 }),
    ]);
    const [row] = inspectorRows(turn.blocks, { t, lang: "en", status: turn.status });
    expect(row.kind).toBe("helper");
    expect(row.status).toBe("done");
  });

  it("a runtime without a stream degrades to its finished blocks", () => {
    const turn = quietTurn();
    expect(inspectorRows(turn.blocks, { t, lang: "en", status: turn.status }).map((row) => row.kind)).toEqual(["reply"]);
  });

  it("internal tools read in the product's words, never as raw ids", () => {
    const turn = turnOf([
      ev("turn_started", { turn_id: "t5", provider: "openrouter", runner: "hermes-cli" }),
      ev("tool_call", { turn_id: "t5", call_id: "d1", name: "tool_describe", input: { name: "mcp_dodaios_society_ask_user" } }),
      ev("tool_result", { turn_id: "t5", call_id: "d1", output: "tool_search result: schema", is_error: false }),
      ev("tool_call", { turn_id: "t5", call_id: "s1", name: "tool_search", input: { query: "ask the person" } }),
      ev("tool_result", { turn_id: "t5", call_id: "s1", output: "[]", is_error: false }),
      ev("tool_call", { turn_id: "t5", call_id: "a1", name: "mcp_dodaios_society_ask_user", input: { questions: [{ question: "Which repo?" }] } }),
      ev("tool_result", { turn_id: "t5", call_id: "a1", output: "main", is_error: false }),
      ev("tool_call", { turn_id: "t5", call_id: "x1", name: "mcp_dodaios_society_status_board", input: {} }),
      ev("tool_result", { turn_id: "t5", call_id: "x1", output: "ok", is_error: false }),
      ev("turn_finished", { turn_id: "t5", status: "done", duration_ms: 1_000 }),
    ]);
    const rows = inspectorRows(turn.blocks, { t, lang: "en", status: turn.status });
    expect(rows.map((row) => [row.label, row.preview])).toEqual([
      ["Looked up tools", "Ask user"],
      ["Looked up tools", "ask the person"],
      ["Asked you", "Which repo?"],
      ["Society status board", "ok"],
    ]);
  });

  it("a call's own words keep their underscores in the preview", () => {
    const turn = turnOf([
      ev("turn_started", { turn_id: "t6", provider: "openai", runner: "brain" }),
      ev("tool_call", { turn_id: "t6", call_id: "g1", name: "Grep", input: { pattern: "my_flag_name" } }),
      ev("tool_result", { turn_id: "t6", call_id: "g1", output: "", is_error: false }),
      ev("turn_finished", { turn_id: "t6", status: "done", duration_ms: 1_000 }),
    ]);
    const rows = inspectorRows(turn.blocks, { t, lang: "en", status: turn.status });
    expect(rows[0].label).toContain("my_flag_name");
  });

  it("previews take the first meaningful line, capped", () => {
    expect(previewOf("## Title\n\nbody")).toBe("Title");
    expect(previewOf("x".repeat(200)).length).toBe(80);
  });
});

describe("WorkInspector", () => {
  it("shows the reasoning the chat never shows, and opens a call to its diff", () => {
    draw(brainTurn(), { prompt: "Fix the typo" });
    const rows = screen.getAllByTestId("work-inspector-row");
    expect(rows).toHaveLength(4);
    fireEvent.click(within(rows[1]).getByRole("button"));
    expect(rows[1].querySelector(".wi-detail")?.textContent).toContain("The typo is in the header.");
    fireEvent.click(within(rows[2]).getByRole("button"));
    expect(screen.getByText("Changes")).toBeTruthy();
    const added = rows[2].querySelector(".wi-diff-line[data-kind=\"add\"]");
    expect(added?.textContent).toContain("Hello");
  });

  it("gives every helper a tab with its own trace and status", () => {
    draw(cliTurn());
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual([expect.stringContaining("Scout"), expect.stringContaining("Count files")]);
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(screen.getAllByRole("tab")[1].getAttribute("aria-selected")).toBe("true");
    const kinds = screen.getAllByTestId("work-inspector-row").map((row) => row.dataset.kind);
    expect(kinds).toEqual(["prompt", "call", "reply"]);
  });

  it("hides the tab strip when nobody else worked on the turn", () => {
    draw(brainTurn());
    expect(screen.queryByRole("tablist")).toBeNull();
  });

  it("opens a helper's tab from its row", () => {
    draw(cliTurn());
    fireEvent.click(within(screen.getAllByTestId("work-inspector-row")[0]).getByRole("button"));
    fireEvent.click(screen.getByText("Open the helper's trace"));
    expect(screen.getAllByRole("tab")[1].getAttribute("aria-selected")).toBe("true");
  });

  it("Esc closes it, but not while typing", () => {
    const { onClose } = draw(brainTurn());
    const input = document.createElement("textarea");
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    input.remove();
  });

  it("an empty live turn says that steps will show up", () => {
    draw(turnOf([ev("turn_started", { turn_id: "t9", provider: "kimi" })]));
    expect(screen.getByText(en.run_view.inspector.empty_live)).toBeTruthy();
  });

  it("the edge resizes within bounds by keyboard", () => {
    const widths: number[] = [];
    draw(brainTurn(), { onWidth: (w) => widths.push(w) });
    const edge = screen.getByTestId("work-inspector-edge");
    fireEvent.keyDown(edge, { key: "ArrowLeft" });
    fireEvent.keyDown(edge, { key: "End" });
    expect(widths).toEqual([436, INSPECTOR_MIN]);
  });
});

describe("inspector width", () => {
  it("clamps and decides between side by side and floating", () => {
    expect(clampWidth(10)).toBe(INSPECTOR_MIN);
    expect(clampWidth(5_000)).toBe(INSPECTOR_MAX);
    expect(clampWidth(600, 500)).toBe(500);
    expect(inspectorDocked(1200, 420)).toBe(true);
    expect(inspectorDocked(700, 420)).toBe(false);
  });
});

describe("the inspector's cost", () => {
  const costed = (runner: string, extra: Record<string, unknown> = {}) => turnOf([
    ev("turn_started", { turn_id: "c1", provider: "claude-api", runner }),
    ev("assistant_text", { turn_id: "c1", message_id: "m", text: "ok" }),
    ev("turn_finished", { turn_id: "c1", status: "done", duration_ms: 1_000, cost_usd: 0.3427, ...extra }),
  ]);

  it("names no price for a subscription seat: the plan covers it", () => {
    draw(costed("claude-cli"));
    const meta = screen.getByTestId("work-inspector").querySelector(".wi-meta")!.textContent ?? "";
    expect(meta).toContain("Included in your plan");
    expect(meta).not.toContain("$");
    // Cost and model have a line of their own, so a narrow pane never cuts them off.
    expect(screen.getByTestId("work-inspector-seat").textContent).toContain("Included in your plan");
  });

  it("keeps the amount for a per-token key", () => {
    draw(costed("api"));
    expect(screen.getByTestId("work-inspector").querySelector(".wi-meta")!.textContent).toContain("$0.3427");
    cleanup();
    draw(costed("claude-cli", { billed_via_key: true }));
    expect(screen.getByTestId("work-inspector").querySelector(".wi-meta")!.textContent).toContain("$0.3427");
    cleanup();
    // A CLI on the person's own key (Grok Build bills per turn) is real money, not a seat.
    draw(costed("grok-cli"));
    expect(screen.getByTestId("work-inspector").querySelector(".wi-meta")!.textContent).toContain("$0.3427");
  });
});
