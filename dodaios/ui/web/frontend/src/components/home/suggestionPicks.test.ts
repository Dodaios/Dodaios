import { describe, expect, it } from "vitest";

import { MAX_SUGGESTIONS, buildSuggestions, type AgentItem, type DueItem } from "./suggestionPicks";

const t = (key: string) => ({
  "design.greeting.due": "Prepare: {text}",
  "design.greeting.agent_working": "What is {agent} doing?",
  "design.greeting.agent_waiting": "What does {agent} need?",
}[key] ?? key);

const due = (id: string, at: string | null, text = `item ${id}`): DueItem => ({ id, text, due_at: at });
const agent = (id: string, state: string): AgentItem => ({ agentId: id, name: `Agent ${id}`, state });

describe("buildSuggestions", () => {
  it("offers nothing on a quiet day", () => {
    expect(buildSuggestions([], [agent("a", "idle")], t)).toEqual([]);
  });

  it("takes the soonest due items first and skips undated ones", () => {
    const out = buildSuggestions([due("late", "2026-11-12"), due("none", null), due("soon", "2026-11-10")], [], t);
    expect(out.map((s) => s.text)).toEqual(["Prepare: item soon", "Prepare: item late"]);
  });

  it("mixes two due items with one agent, never more than three", () => {
    const out = buildSuggestions(
      [due("1", "2026-11-10"), due("2", "2026-11-11"), due("3", "2026-11-12")],
      [agent("w", "working"), agent("x", "waiting")],
      t,
    );
    expect(out).toHaveLength(MAX_SUGGESTIONS);
    expect(out.map((s) => s.kind)).toEqual(["due", "due", "agent"]);
    // Waiting on the person beats working.
    expect(out[2].text).toBe("What does Agent x need?");
  });

  it("lets agents fill the places due items leave", () => {
    const out = buildSuggestions([], [agent("a", "working"), agent("b", "working"), agent("c", "waiting"), agent("d", "working")], t);
    expect(out).toHaveLength(3);
    expect(out.every((s) => s.kind === "agent")).toBe(true);
  });

  it("keeps a long memory to one chip's length", () => {
    const [only] = buildSuggestions([due("1", "2026-11-10", "x".repeat(200))], [], t);
    expect(only.text.length).toBeLessThan(100);
    expect(only.text.endsWith("…")).toBe(true);
  });
});
