import { describe, expect, it } from "vitest";
import { Terminal } from "@xterm/xterm";
import { MIN_SHOWN_ROWS, drawGlyph, fitTerminal, gridShape, opaque, paletteFor, shownRows, snapshotText, snapshotXterm, type TermSnapshot } from "./terminalCanvas";

function write(term: Terminal, data: string): Promise<void> {
  return new Promise((resolve) => term.write(data, resolve));
}

describe("terminal palette", () => {
  it("uses the theme's 16 colours and the standard cube and greys", () => {
    const p = paletteFor({ red: "#ff0000" });
    expect(p).toHaveLength(256);
    expect(p[1]).toBe("#ff0000");
    expect(p[16]).toBe("#000000");
    expect(p[231]).toBe("#ffffff");
    expect(p[232]).toBe("#080808");
  });

  it("drops the alpha of a glass ground", () => {
    expect(opaque("rgba(18, 20, 26, 0)", "#000")).toBe("#12141a");
    expect(opaque("#fcfbf8", "#000")).toBe("#fcfbf8");
    expect(opaque(undefined, "#121212")).toBe("#121212");
  });
});

describe("xterm snapshot", () => {
  it("copies cells with their colours, cell for cell", async () => {
    const term = new Terminal({ cols: 20, rows: 4, allowProposedApi: true, theme: { foreground: "#dddddd", background: "rgba(1, 2, 3, 0)", red: "#aa0000", brightRed: "#ff5555" } });
    await write(term, "\x1b[31mred\x1b[0m ok\r\n\x1b[1;31mbold\x1b[0m\r\n\x1b[38;2;1;2;3mrgb\x1b[0m");
    const snap = snapshotXterm(term);
    expect(snap.cols).toBe(20);
    expect(snap.ground).toBe("#010203");
    const [first, second, third] = snap.lines;
    expect(first[0]).toMatchObject({ col: 0, text: "red", fg: "#aa0000" });
    expect(first.map((r) => r.text).join("")).toMatch(/^red ok/);
    expect(first[1]).toMatchObject({ col: 3, fg: "#dddddd" });
    // Bold low colours draw bright, like xterm.
    expect(second[0]).toMatchObject({ text: "bold", fg: "#ff5555", bold: true });
    expect(third[0]).toMatchObject({ text: "rgb", fg: "#010203" });
    term.dispose();
  });

  it("keeps a wide glyph as one run of two cells", async () => {
    const term = new Terminal({ cols: 10, rows: 2, allowProposedApi: true });
    await write(term, "a中b");
    const runs = snapshotXterm(term).lines[0];
    const wide = runs.find((r) => r.text === "中");
    expect(wide).toMatchObject({ col: 1, cells: 2 });
    expect(runs.find((r) => r.text.startsWith("b"))).toMatchObject({ col: 3 });
    term.dispose();
  });
});

describe("text fallback and layout", () => {
  const snap: TermSnapshot = snapshotText({ cols: 80, lines: ["one", "  two  spaced", "", "", ""], cursor: null }, { foreground: "#eee" });

  it("keeps the server replay's spacing", () => {
    expect(snap.lines[1][0].text).toBe("  two  spaced");
    expect(snap.lines[2]).toEqual([]);
  });

  it("shows the bottom block that fits, ending at the last row with content", () => {
    expect(shownRows(snap, 1)).toEqual({ first: 1, end: 2 });
    expect(shownRows(snap, 10)).toEqual({ first: 0, end: 5 });
    expect(shownRows({ ...snap, cursor: [3, 0] }, 2)).toEqual({ first: 2, end: 4 });
  });

  it("fits the terminal's width and counts the rows that fit", () => {
    const f = fitTerminal(160, 1920, 1000, 0.6);
    expect(f.font).toBe(20);
    expect(f.fit).toBe(Math.floor(1000 / (20 * 1.22)));
  });

  it("fills the monitor's width, but always keeps MIN_SHOWN_ROWS rows; a very narrow pane sits centred", () => {
    // A wide pane: its width fills the screen.
    const wide = fitTerminal(160, 1920, 1000, 0.6);
    expect(wide.cellW * 160).toBeCloseTo(1920, 0);
    expect(wide.left).toBe(0);
    // A 60-column pane on a wide monitor: as large as MIN_SHOWN_ROWS rows allow, centred.
    const narrow = fitTerminal(60, 1920, 1000, 0.6);
    expect(narrow.fit).toBeGreaterThanOrEqual(MIN_SHOWN_ROWS);
    expect(narrow.cellW * 60).toBeGreaterThan(1920 * 0.75);
    expect(narrow.left).toBeCloseTo((1920 - narrow.cellW * 60) / 2, 0);
  });

  it("chooses the grid that gives each pane the largest text", () => {
    expect(gridShape(1, 1000, 500, 0)).toEqual({ cols: 1, rows: 1 });
    expect(gridShape(4, 2048, 956, 10)).toEqual({ cols: 2, rows: 2 });
    expect(gridShape(6, 2048, 523, 8)).toEqual({ cols: 6, rows: 1 });
  });
});

describe("box and block glyphs", () => {
  function recorder() {
    const rects: number[][] = [];
    const ctx = { fillRect: (...a: number[]) => rects.push(a), beginPath() {}, moveTo() {}, arcTo() {}, lineTo() {}, stroke() {}, globalAlpha: 1, lineWidth: 1 };
    return { ctx: ctx as unknown as CanvasRenderingContext2D, rects };
  }

  it("draws a horizontal rule edge to edge, so neighbouring cells join", () => {
    const { ctx, rects } = recorder();
    expect(drawGlyph(ctx, "─", 10, 0, 8, 16)).toBe(true);
    const left = Math.min(...rects.map((r) => r[0])), right = Math.max(...rects.map((r) => r[0] + r[2]));
    expect(left).toBe(10);
    expect(right).toBe(18);
  });

  it("fills block quadrants", () => {
    const { ctx, rects } = recorder();
    drawGlyph(ctx, "▛", 0, 0, 8, 16);
    expect(rects).toHaveLength(3);
    expect(drawGlyph(ctx, "a", 0, 0, 8, 16)).toBe(false);
  });
});
