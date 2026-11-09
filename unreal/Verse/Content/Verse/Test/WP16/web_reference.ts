/**
 * The A16.3 reference, captured from the IDE's own web painter.
 *
 * Bundled by make_web_reference.py with the frontend's esbuild and run in headless Chrome:
 * the colour test screen is written as escape sequences into a real xterm buffer with the
 * IDE theme, read with snapshotXterm, painted with paintTerminalTile, and every sample cell
 * is read back from the canvas pixels. The page prints the samples as JSON into #out.
 *
 * Each sample covers three cells: a full block (block geometry), "M" (a glyph drawn as text)
 * and a blank (the run's background, or the ground).
 */
import { Terminal } from "@xterm/xterm";
import { DARK_TERMINAL_THEME } from "@/components/agentic/terminalThemes";
import { fitTerminal, paintTerminalTile, shownRows, snapshotXterm } from "@/components/society/verse/effects/terminalCanvas";
import { TERMINAL_FONT_STACK } from "@/lib/terminalFont";

type Colour = { i: number } | string | null;

interface Sample {
  row: number;
  col: number;
  fg: Colour;
  bg: Colour;
  attrs: string[];
}

interface Screen {
  cols: number;
  rows: number;
  width: number;
  height: number;
  glyphs: string;
  samples: Sample[];
}

declare global {
  interface Window {
    VERSE_SCREEN: Screen;
  }
}

function hex2(n: number): string {
  return n.toString(16).padStart(2, "0");
}

function sgrColour(c: Colour, base: number): string[] {
  if (c === null) return [];
  if (typeof c === "string") {
    const v = parseInt(c.slice(1), 16);
    return [`${base}`, "2", `${(v >> 16) & 255}`, `${(v >> 8) & 255}`, `${v & 255}`];
  }
  return [`${base}`, "5", `${c.i}`];
}

function sgr(s: Sample): string {
  const p = ["0"];
  if (s.attrs.includes("bold")) p.push("1");
  if (s.attrs.includes("dim")) p.push("2");
  if (s.attrs.includes("inverse")) p.push("7");
  p.push(...sgrColour(s.fg, 38), ...sgrColour(s.bg, 48));
  return `\x1b[${p.join(";")}m`;
}

function pixel(img: ImageData, x: number, y: number): [number, number, number] {
  const cx = Math.max(0, Math.min(img.width - 1, Math.round(x)));
  const cy = Math.max(0, Math.min(img.height - 1, Math.round(y)));
  const o = (cy * img.width + cx) * 4;
  return [img.data[o], img.data[o + 1], img.data[o + 2]];
}

function hex(p: [number, number, number]): string {
  return `#${hex2(p[0])}${hex2(p[1])}${hex2(p[2])}`;
}

/** The pixel of a cell's inner box farthest from the cell's ground: the core of the glyph. */
function core(img: ImageData, x: number, y: number, w: number, h: number, ground: [number, number, number]): [number, number, number] {
  let best = ground;
  let bestD = -1;
  for (let py = Math.ceil(y + h * 0.15); py < y + h * 0.85; py += 1) {
    for (let px = Math.ceil(x + w * 0.15); px < x + w * 0.85; px += 1) {
      const p = pixel(img, px, py);
      const d = (p[0] - ground[0]) ** 2 + (p[1] - ground[1]) ** 2 + (p[2] - ground[2]) ** 2;
      if (d > bestD) {
        bestD = d;
        best = p;
      }
    }
  }
  return best;
}

function run(): void {
  const screen = window.VERSE_SCREEN;
  const term = new Terminal({ cols: screen.cols, rows: screen.rows, theme: DARK_TERMINAL_THEME, allowProposedApi: true });
  let data = "\x1b[?25l";
  for (const s of screen.samples) data += `\x1b[${s.row + 1};${s.col + 1}H${sgr(s)}${screen.glyphs}\x1b[0m`;
  term.write(data, () => {
    const snap = snapshotXterm(term);
    const canvas = document.createElement("canvas");
    canvas.width = screen.width;
    canvas.height = screen.height;
    document.body.appendChild(canvas);
    const ctx = canvas.getContext("2d", { alpha: false, willReadFrequently: true })!;
    const w = screen.width;
    const h = screen.height;
    paintTerminalTile(ctx, 0, 0, w, h, { title: "colour test", status: "", tone: "live" }, snap, false);

    // The body rectangle and grid exactly as paintTerminalTile lays them out.
    const headH = Math.max(12, Math.min(48, Math.round(h * 0.07)));
    const pad = Math.max(2, Math.round(Math.min(w, h) * 0.015));
    ctx.font = `500 100px ${TERMINAL_FONT_STACK}`;
    const ratio = ctx.measureText("MMMMMMMMMM").width / 10 / 100 || 0.6;
    const fitted = fitTerminal(snap.cols, w - 2 * pad, h - headH - 2 * pad, ratio);
    const { first, end } = shownRows(snap, fitted.fit);
    const bx = pad + fitted.left;
    const by = headH + pad;
    const img = ctx.getImageData(0, 0, w, h);

    const out = [];
    for (const s of screen.samples) {
      if (s.row < first || s.row >= end) throw new Error(`row ${s.row} not shown (${first}..${end})`);
      const y = by + (s.row - first) * fitted.lineH;
      const x = (c: number) => bx + c * fitted.cellW;
      const ground = pixel(img, x(s.col + 2) + fitted.cellW / 2, y + fitted.lineH / 2);
      const runs = snap.lines[s.row] ?? [];
      const r = runs.find((q) => q.col <= s.col && s.col < q.col + q.cells);
      out.push({
        ...s,
        web_run: r ? (r.bg ? { fg: r.fg, bg: r.bg } : { fg: r.fg }) : null,
        web: {
          // The web draws a full block as four quadrants: sample a quadrant's centre, not the seam.
          block: hex(pixel(img, x(s.col) + fitted.cellW / 4, y + fitted.lineH / 4)),
          text: hex(core(img, x(s.col + 1), y, fitted.cellW, fitted.lineH, ground)),
          bg: hex(ground),
        },
      });
    }
    const pre = document.createElement("pre");
    pre.id = "out";
    pre.textContent = JSON.stringify({
      ground: snap.ground,
      ink: snap.ink,
      layout: { cell_w: fitted.cellW, line_h: fitted.lineH, font_px: fitted.font, first_row: first, left: bx, top: by },
      font_stack: TERMINAL_FONT_STACK,
      samples: out,
    });
    document.body.appendChild(pre);
  });
}

run();
