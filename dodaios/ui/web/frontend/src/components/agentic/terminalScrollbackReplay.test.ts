/**
 * A pane that is looked at again can be scrolled back as far as one that was
 * never left.
 *
 * The report (2026-11-12): in a Grid pane running Claude Code "I could scroll a
 * little, but not all the way to the top". A pane's scrollback lives in its
 * xterm instance, and that instance is rebuilt — `term.reset()`, then the
 * server's replay — on every switch between Chat and Grid, every workspace
 * switch and every reload. The replay used to be the last 128 KB of raw output
 * (nothing at all after a resize), so the rebuilt pane held a few screens.
 *
 * The server now keeps the rows that scroll off (`ScrollbackMirror` in
 * dodaios/agentic_ide/scrollback.py) and writes them back in front of the
 * screen. That mirror is a second terminal emulator, and the only thing that
 * makes it right is agreeing with THIS one. So each shared case is played
 * through the real xterm twice — once as the viewer that stayed, once as the
 * viewer rebuilt from the replay the backend recorded for it
 * (tests/unit/agentic_ide/test_scrollback.py pins that recording to the
 * mirror's current output) — and the two buffers have to hold the same rows.
 */
import { describe, expect, it } from "vitest";
import { Terminal } from "@xterm/xterm";
import { Unicode11Addon } from "@xterm/addon-unicode11";
import cases from "../../../../../../../tests/fakes/terminal_scrollback_cases.json";

type Step = { write?: string; resize?: number[] };
type Case = { cols: number; rows: number; steps: Step[]; replay: string; history_rows: number };

/** The options that decide what a pane's buffer holds; see AgenticTerminal. */
function paneTerminal(cols: number, rows: number): Terminal {
  const term = new Terminal({ cols, rows, scrollback: 10000, allowProposedApi: true });
  term.loadAddon(new Unicode11Addon());
  term.unicode.activeVersion = "11";
  return term;
}

function write(term: Terminal, text: string): Promise<void> {
  return new Promise((resolve) => term.write(text, resolve));
}

function rowsOf(term: Terminal): string[] {
  const buffer = term.buffer.active;
  const rows: string[] = [];
  for (let y = 0; y < buffer.length; y += 1) {
    rows.push(buffer.getLine(y)?.translateToString(true) ?? "");
  }
  return rows;
}

async function stayed(spec: Case): Promise<Terminal> {
  const term = paneTerminal(spec.cols, spec.rows);
  for (const step of spec.steps) {
    if (step.resize) term.resize(step.resize[0], step.resize[1]);
    else await write(term, step.write ?? "");
  }
  return term;
}

describe("a pane rebuilt from the server's replay", () => {
  it.each(Object.entries(cases as Record<string, Case>))(
    "holds the rows of a pane that was never left: %s",
    async (_name, spec) => {
      const live = await stayed(spec);
      const rebuilt = paneTerminal(live.cols, live.rows);
      // What the pane does with a replay: reset, then write it.
      rebuilt.reset();
      await write(rebuilt, spec.replay);

      expect(rowsOf(rebuilt)).toEqual(rowsOf(live));
      expect([rebuilt.buffer.active.cursorX, rebuilt.buffer.active.cursorY]).toEqual([
        live.buffer.active.cursorX,
        live.buffer.active.cursorY,
      ]);
      // The point of it all: the history is above the screen, as many rows of
      // it as the pane that stayed has, and so just as far to scroll back.
      expect(rebuilt.buffer.active.baseY).toBe(live.buffer.active.baseY);
      live.dispose();
      rebuilt.dispose();
    },
  );

  it("starts with the first row the agent ever printed", async () => {
    const spec = (cases as Record<string, Case>).inline_agent;
    const rebuilt = paneTerminal(spec.cols, spec.rows);
    await write(rebuilt, spec.replay);

    const rows = rowsOf(rebuilt);
    expect(rows[0]).toContain("Agent v1");
    expect(rows.filter((row) => row.startsWith("> question 0")).length).toBe(1);
    expect(rows.length).toBeGreaterThan(spec.rows * 4);
    rebuilt.dispose();
  });
});
