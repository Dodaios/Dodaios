import { describe, expect, it, vi } from "vitest";

import { activityOf, thoughtHeadline, writesNodes } from "./agentActivity";
import { alongPath, cellsWriting, gesture } from "./writing";

const t = (key: string) => (key === "agent_chat.thinking" ? "Thinking…" : key);

function timeline(blocks: unknown[]) {
  return { items: [{ type: "turn", status: "running", blocks }] } as never;
}

describe("the agent's steps at its cursor", () => {
  it("tells the latest call between edits in the trace's words, never the node's own writes", () => {
    const blocks = [
      { kind: "tool", callId: "a", name: "WebSearch", input: { query: "history of the bicycle" }, output: null, isError: false, durationMs: null, approval: null, startedMs: 0 },
      { kind: "tool", callId: "b", name: "mcp__dodaios__node", input: { operation: "update" }, output: null, isError: false, durationMs: null, approval: null, startedMs: 1 },
    ];
    const line = activityOf(timeline(blocks), t, "en");
    expect(line).toContain("history of the bicycle");
    expect(line).not.toMatch(/node/i);
  });

  it("says a thought's headline, or that it thinks while the runner hides the thought", () => {
    expect(thoughtHeadline("Some notes\n**Planning the table**\nmore")).toBe("Planning the table");
    expect(thoughtHeadline("First line\nLast line of thought")).toBe("Last line of thought");
    const live = [{ kind: "reasoning", id: "r", text: "", durationMs: null, live: true, startedMs: 0 }];
    expect(activityOf(timeline(live), t, "en")).toBe("Thinking…");
    expect(activityOf(null, t, "en")).toBe("");
  });

  it("knows the tools that write nodes", () => {
    expect(writesNodes("mcp__dodaios__node")).toBe(true);
    expect(writesNodes("whiteboard")).toBe(true);
    expect(writesNodes("mcp__dodaios__clip")).toBe(true);
    expect(writesNodes("WebSearch")).toBe(false);
  });
});

describe("the hand at work", () => {
  it("walks a path by its length", () => {
    const path = [{ x: 0, y: 0 }, { x: 100, y: 0 }, { x: 100, y: 100 }];
    expect(alongPath(path, 0)).toEqual({ x: 0, y: 0 });
    expect(alongPath(path, 0.5)).toEqual({ x: 100, y: 0 });
    expect(alongPath(path, 0.75)).toEqual({ x: 100, y: 50 });
    expect(alongPath(path, 1)).toEqual({ x: 100, y: 100 });
  });

  it("drags along its path while the element grows, and ends everything on finish", () => {
    const el = document.createElement("div");
    document.body.appendChild(el);
    el.getBoundingClientRect = () => ({ left: 10, top: 20, right: 110, bottom: 40, width: 100, height: 20, x: 10, y: 20, toJSON: () => ({}) }) as DOMRect;
    const progress = vi.fn();
    const motion = gesture({
      element: el,
      durationMs: 400,
      steps: 4,
      path: (box) => [{ x: box.left, y: box.top + box.height / 2 }, { x: box.right, y: box.top + box.height / 2 }],
      progress,
    });
    motion.prepare(document.body);
    motion.start();
    expect(motion.caret?.()).toMatchObject({ x: 10, y: 30, h: 0 });
    motion.advance(4);
    expect(motion.caret?.()).toMatchObject({ x: 110, y: 30 });
    motion.finish();
    expect(progress).toHaveBeenLastCalledWith(1);
  });

  it("types a row cell by cell and shows every cell on finish", () => {
    const row = document.createElement("tr");
    row.innerHTML = "<th>1</th><td>Rent</td><td></td><td>980</td>";
    document.body.appendChild(document.createElement("table")).appendChild(row);
    const animate = vi.fn(() => ({ cancel: vi.fn() }) as unknown as Animation);
    for (const cell of row.querySelectorAll("td")) (cell as unknown as { animate: typeof animate }).animate = animate;
    const motion = cellsWriting(row);
    // The empty cell is not typed; two cells are.
    expect(motion.steps).toBe(2);
    motion.prepare(document.body);
    expect(animate).toHaveBeenCalledTimes(2);
    motion.start();
    motion.advance(1);
    motion.finish();
  });
});
