/**
 * A coding pane's terminal drawn onto a ship monitor, cell for cell.
 *
 * `snapshotXterm` copies the live screen out of the pane's own xterm buffer
 * (the one the IDE draws), with every cell's colours and attributes resolved
 * against the pane's theme. `snapshotText` turns the server's plain-text
 * replay into the same shape for a pane the IDE has not mounted. The painters
 * then lay one or several snapshots onto a canvas: the width of the terminal
 * fills the tile, the bottom block of rows that fits is shown (TUIs keep their
 * prompt and newest output there), and box-drawing and block characters are
 * drawn as geometry, the way xterm does, so frames join without gaps.
 *
 * Pure apart from the canvas it is handed.
 */
import type { IBufferCell, ITheme, Terminal } from "@xterm/xterm";
import { TERMINAL_FONT_STACK } from "@/lib/terminalFont";
import type { ScreenTone } from "./screenPainter";

/** A run of neighbouring cells sharing one look. */
export interface CellRun {
  col: number;
  /** Cells covered; a wide glyph counts two. */
  cells: number;
  text: string;
  fg: string;
  /** Null: the terminal's own ground. */
  bg: string | null;
  bold: boolean;
  italic: boolean;
  underline: boolean;
  strike: boolean;
}

export interface TermSnapshot {
  cols: number;
  /** Rows of the visible screen, top first. */
  lines: CellRun[][];
  /** `[row, col]` of a visible cursor, or null. */
  cursor: [number, number] | null;
  ground: string;
  ink: string;
  cursorColor: string;
}

const ANSI_KEYS = [
  "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
  "brightBlack", "brightRed", "brightGreen", "brightYellow", "brightBlue", "brightMagenta", "brightCyan", "brightWhite",
] as const;
/** xterm's own defaults, for a theme that leaves a slot out. */
const ANSI_DEFAULT = [
  "#2e3436", "#cc0000", "#4e9a06", "#c4a000", "#3465a4", "#75507b", "#06989a", "#d3d7cf",
  "#555753", "#ef2929", "#8ae234", "#fce94f", "#729fcf", "#ad7fa8", "#34e2e2", "#eeeeec",
];

function hex2(n: number): string {
  return n.toString(16).padStart(2, "0");
}

/** The 256-colour palette for a theme: its 16 ANSI slots, then the standard cube and greys. Pure. */
export function paletteFor(theme: ITheme): string[] {
  const out: string[] = ANSI_KEYS.map((k, i) => theme[k] ?? ANSI_DEFAULT[i]);
  const steps = [0, 95, 135, 175, 215, 255];
  for (let r = 0; r < 6; r += 1) {
    for (let g = 0; g < 6; g += 1) {
      for (let b = 0; b < 6; b += 1) out.push(`#${hex2(steps[r])}${hex2(steps[g])}${hex2(steps[b])}`);
    }
  }
  for (let i = 0; i < 24; i += 1) { const v = 8 + i * 10; out.push(`#${hex2(v)}${hex2(v)}${hex2(v)}`); }
  const extended = theme.extendedAnsi ?? [];
  extended.forEach((c, i) => { if (c && 16 + i < 256) out[16 + i] = c; });
  return out;
}

/** A CSS colour with its alpha dropped, so a glass pane's ground becomes a solid one. Pure. */
export function opaque(color: string | undefined, fallback: string): string {
  if (!color) return fallback;
  const m = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i.exec(color);
  if (m) return `#${hex2(+m[1])}${hex2(+m[2])}${hex2(+m[3])}`;
  if (/^#[0-9a-f]{8}$/i.test(color)) return color.slice(0, 7);
  return color;
}

function rgb(n: number): string {
  return `#${hex2((n >> 16) & 255)}${hex2((n >> 8) & 255)}${hex2(n & 255)}`;
}

/** Mix two #rrggbb colours: the terminal's dim attribute. */
function mix(a: string, b: string, t: number): string {
  const pa = parseInt(a.slice(1, 7), 16), pb = parseInt(b.slice(1, 7), 16);
  if (Number.isNaN(pa) || Number.isNaN(pb)) return a;
  const ch = (s: number) => Math.round(((pa >> s) & 255) * (1 - t) + ((pb >> s) & 255) * t);
  return `#${hex2(ch(16))}${hex2(ch(8))}${hex2(ch(0))}`;
}

/** The cells of one buffer line as runs, colours resolved. */
function lineRuns(cellAt: (x: number) => IBufferCell | undefined, cols: number, palette: string[], ink: string, ground: string): CellRun[] {
  const runs: CellRun[] = [];
  let cur: CellRun | null = null;
  for (let x = 0; x < cols; x += 1) {
    const cell = cellAt(x);
    if (!cell) break;
    const width = cell.getWidth();
    if (width === 0) continue; // the second half of a wide glyph
    const bold = cell.isBold() !== 0;
    let fg: string;
    if (cell.isFgRGB()) fg = rgb(cell.getFgColor());
    else if (cell.isFgPalette()) {
      let idx = cell.getFgColor();
      // xterm's drawBoldTextInBrightColors default.
      if (bold && idx < 8) idx += 8;
      fg = palette[idx] ?? ink;
    } else fg = ink;
    let bg: string | null = null;
    if (cell.isBgRGB()) bg = rgb(cell.getBgColor());
    else if (cell.isBgPalette()) bg = palette[cell.getBgColor()] ?? null;
    if (cell.isInverse()) { const f = fg; fg = bg ?? ground; bg = f; }
    if (cell.isDim()) fg = mix(fg, bg ?? ground, 0.45);
    const chars = cell.isInvisible() ? " " : (cell.getChars() || " ");
    const italic = cell.isItalic() !== 0, underline = cell.isUnderline() !== 0, strike = cell.isStrikethrough() !== 0;
    if (cur && width === 1 && cur.fg === fg && cur.bg === bg && cur.bold === bold && cur.italic === italic
      && cur.underline === underline && cur.strike === strike && cur.col + cur.cells === x) {
      cur.text += chars;
      cur.cells += 1;
    } else {
      cur = { col: x, cells: width, text: chars, fg, bg, bold, italic, underline, strike };
      runs.push(cur);
      // A wide glyph stands alone, so every run is either one wide glyph or one cell per character.
      if (width !== 1) cur = null;
    }
  }
  return runs;
}

/** Is xterm's cursor hidden (DECTCEM)? Read defensively from the private core. */
function cursorHidden(term: Terminal): boolean {
  const core = (term as unknown as { _core?: { coreService?: { isCursorHidden?: boolean } } })._core;
  return core?.coreService?.isCursorHidden ?? true;
}

/** The live screen of a pane's xterm, read-only. */
export function snapshotXterm(term: Terminal): TermSnapshot {
  const theme = term.options.theme ?? {};
  const ground = opaque(theme.background, "#121212");
  const ink = theme.foreground ?? "#e6e6e6";
  const palette = paletteFor(theme);
  const buffer = term.buffer.active;
  const cols = term.cols;
  const lines: CellRun[][] = [];
  const reuse = buffer.getNullCell();
  for (let y = 0; y < term.rows; y += 1) {
    const line = buffer.getLine(buffer.baseY + y);
    lines.push(line ? lineRuns((x) => line.getCell(x, reuse), cols, palette, ink, ground) : []);
  }
  const cursor: [number, number] | null = cursorHidden(term) ? null : [buffer.cursorY, buffer.cursorX];
  return { cols, lines, cursor, ground, ink, cursorColor: theme.cursor ?? ink };
}

/** The server's plain replay of a pane, in the same shape (one colour, layout intact). Pure. */
export function snapshotText(screen: { cols: number; lines: readonly string[]; cursor: [number, number] | null }, theme: ITheme): TermSnapshot {
  const ground = opaque(theme.background, "#121212");
  const ink = theme.foreground ?? "#e6e6e6";
  const lines = screen.lines.map((text): CellRun[] => (text
    ? [{ col: 0, cells: [...text].length, text, fg: ink, bg: null, bold: false, italic: false, underline: false, strike: false }]
    : []));
  return { cols: Math.max(1, screen.cols), lines, cursor: screen.cursor, ground, ink, cursorColor: theme.cursor ?? ink };
}

function runText(run: CellRun): string {
  return run.text;
}

/**
 * The rows to show when only `fit` rows fit: the block ending at the last
 * row with content, or at the cursor row if that is lower. Pure.
 */
export function shownRows(snap: TermSnapshot, fit: number): { first: number; end: number } {
  let end = snap.lines.length;
  while (end > 0 && !snap.lines[end - 1].some((r) => runText(r).trim() || r.bg)) end -= 1;
  if (snap.cursor && snap.cursor[0] + 1 > end) end = snap.cursor[0] + 1;
  end = Math.max(end, Math.min(snap.lines.length, Math.max(1, fit)));
  return { first: Math.max(0, end - Math.max(1, fit)), end };
}

// ── Box drawing and blocks, as geometry ──────────────────────────────────

/** Arms of a box-drawing glyph: left, right, up, down; 1 light, 2 heavy, 3 double. */
const BOX: Record<string, [number, number, number, number]> = {
  "─": [1, 1, 0, 0], "━": [2, 2, 0, 0], "│": [0, 0, 1, 1], "┃": [0, 0, 2, 2],
  "┌": [0, 1, 0, 1], "┐": [1, 0, 0, 1], "└": [0, 1, 1, 0], "┘": [1, 0, 1, 0],
  "╭": [0, 1, 0, 1], "╮": [1, 0, 0, 1], "╰": [0, 1, 1, 0], "╯": [1, 0, 1, 0],
  "┏": [0, 2, 0, 2], "┓": [2, 0, 0, 2], "┗": [0, 2, 2, 0], "┛": [2, 0, 2, 0],
  "├": [0, 1, 1, 1], "┤": [1, 0, 1, 1], "┬": [1, 1, 0, 1], "┴": [1, 1, 1, 0], "┼": [1, 1, 1, 1],
  "═": [3, 3, 0, 0], "║": [0, 0, 3, 3], "╔": [0, 3, 0, 3], "╗": [3, 0, 0, 3], "╚": [0, 3, 3, 0], "╝": [3, 0, 3, 0],
  "╴": [1, 0, 0, 0], "╶": [0, 1, 0, 0], "╵": [0, 0, 1, 0], "╷": [0, 0, 0, 1],
};
const ROUNDED = new Set(["╭", "╮", "╰", "╯"]);
/** Quadrants lit: top-left, top-right, bottom-left, bottom-right. */
const QUAD: Record<string, [number, number, number, number]> = {
  "▘": [1, 0, 0, 0], "▝": [0, 1, 0, 0], "▖": [0, 0, 1, 0], "▗": [0, 0, 0, 1],
  "▀": [1, 1, 0, 0], "▄": [0, 0, 1, 1], "▌": [1, 0, 1, 0], "▐": [0, 1, 0, 1],
  "▚": [1, 0, 0, 1], "▞": [0, 1, 1, 0], "▙": [1, 0, 1, 1], "▛": [1, 1, 1, 0],
  "▜": [1, 1, 0, 1], "▟": [0, 1, 1, 1], "█": [1, 1, 1, 1],
};
const SHADE: Record<string, number> = { "░": 0.25, "▒": 0.5, "▓": 0.75 };

/** Draw `ch` as geometry if it is a box or block glyph; false when it is not one. */
export function drawGlyph(ctx: CanvasRenderingContext2D, ch: string, x: number, y: number, w: number, h: number): boolean {
  const quad = QUAD[ch];
  if (quad) {
    const hw = w / 2, hh = h / 2;
    if (quad[0]) ctx.fillRect(x, y, hw, hh);
    if (quad[1]) ctx.fillRect(x + hw, y, w - hw, hh);
    if (quad[2]) ctx.fillRect(x, y + hh, hw, h - hh);
    if (quad[3]) ctx.fillRect(x + hw, y + hh, w - hw, h - hh);
    return true;
  }
  const shade = SHADE[ch];
  if (shade) {
    const a = ctx.globalAlpha;
    ctx.globalAlpha = a * shade;
    ctx.fillRect(x, y, w, h);
    ctx.globalAlpha = a;
    return true;
  }
  const arms = BOX[ch];
  if (!arms) return false;
  const light = Math.max(1, Math.round(w / 8));
  const cx = x + w / 2, cy = y + h / 2;
  if (ROUNDED.has(ch)) {
    const r = Math.min(w, h) / 2;
    ctx.lineWidth = light;
    ctx.beginPath();
    const [l, , u] = arms;
    const ex = l ? x : x + w, ey = u ? y : y + h;
    ctx.moveTo(ex, cy);
    ctx.arcTo(cx, cy, cx, ey, r);
    ctx.lineTo(cx, ey);
    ctx.stroke();
    return true;
  }
  const thick = (k: number) => (k === 2 ? light * 2 : light);
  const [l, rr, u, d] = arms;
  const hline = (x0: number, x1: number, k: number) => {
    if (k === 3) { ctx.fillRect(x0, cy - light * 1.5, x1 - x0, light); ctx.fillRect(x0, cy + light * 0.5, x1 - x0, light); }
    else ctx.fillRect(x0, cy - thick(k) / 2, x1 - x0, thick(k));
  };
  const vline = (y0: number, y1: number, k: number) => {
    if (k === 3) { ctx.fillRect(cx - light * 1.5, y0, light, y1 - y0); ctx.fillRect(cx + light * 0.5, y0, light, y1 - y0); }
    else ctx.fillRect(cx - thick(k) / 2, y0, thick(k), y1 - y0);
  };
  const ov = light; // overlap at the centre so the arms meet
  if (l) hline(x, cx + (rr ? 0 : ov), l);
  if (rr) hline(cx - (l ? 0 : ov), x + w, rr);
  if (u) vline(y, cy + (d ? 0 : ov), u);
  if (d) vline(cy - (u ? 0 : ov), y + h, d);
  return true;
}

// ── Painting ─────────────────────────────────────────────────────────────

export const LINE_RATIO = 1.22;
const MIN_FONT = 5;
const MAX_FONT = 30;

const TONE_DOT: Readonly<Record<ScreenTone, string>> = { live: "#4ade80", attention: "#fbbf24", fault: "#f87171", standby: "#6b7280" };
const SANS = "Inter, system-ui, -apple-system, 'Segoe UI', sans-serif";

/** Monospace advance per pixel of font size, measured once per context. */
const ratioCache = new WeakMap<CanvasRenderingContext2D, number>();
function charRatio(ctx: CanvasRenderingContext2D): number {
  let r = ratioCache.get(ctx);
  if (r === undefined) {
    ctx.font = `500 100px ${TERMINAL_FONT_STACK}`;
    r = (ctx.measureText("MMMMMMMMMM").width / 10) / 100 || 0.6;
    ratioCache.set(ctx, r);
  }
  return r;
}

export interface TileHeader {
  title: string;
  status: string;
  tone: ScreenTone;
}

/** Font and rows for a terminal `cols` wide in a body `w` x `h`. Pure. */
export function fitTerminal(cols: number, w: number, h: number, ratio: number): { font: number; cellW: number; lineH: number; fit: number } {
  const font = Math.max(MIN_FONT, Math.min(MAX_FONT, w / (Math.max(20, cols) * ratio)));
  const cellW = font * ratio;
  const lineH = font * LINE_RATIO;
  return { font, cellW, lineH, fit: Math.max(1, Math.floor(h / lineH)) };
}

/** One pane: a slim title row over its terminal, inside the rectangle. */
export function paintTerminalTile(
  ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number,
  header: TileHeader, snap: TermSnapshot | null, blinkOn: boolean,
): void {
  const ground = snap?.ground ?? "#121212";
  const ink = snap?.ink ?? "#e6e6e6";
  ctx.save();
  ctx.beginPath();
  ctx.rect(x, y, w, h);
  ctx.clip();
  ctx.fillStyle = ground;
  ctx.fillRect(x, y, w, h);
  // Title row: status dot, name, status word.
  const headH = Math.max(12, Math.min(48, Math.round(h * 0.07)));
  ctx.fillStyle = mix(ground, ink, 0.07);
  ctx.fillRect(x, y, w, headH);
  ctx.fillStyle = mix(ground, ink, 0.18);
  ctx.fillRect(x, y + headH - 1, w, 1);
  const hf = Math.round(headH * 0.56);
  ctx.textBaseline = "middle";
  ctx.fillStyle = TONE_DOT[header.tone];
  ctx.beginPath();
  ctx.arc(x + headH * 0.5, y + headH / 2, Math.max(2, headH * 0.16), 0, Math.PI * 2);
  ctx.fill();
  ctx.font = `600 ${hf}px ${SANS}`;
  const status = header.status;
  const statusW = ctx.measureText(status).width;
  ctx.textAlign = "right";
  ctx.fillStyle = mix(ink, ground, 0.35);
  ctx.fillText(status, x + w - headH * 0.4, y + headH / 2 + 1);
  ctx.textAlign = "left";
  ctx.fillStyle = ink;
  const titleMax = w - headH - statusW - headH * 0.8;
  let title = header.title;
  while (title.length > 1 && ctx.measureText(title).width > titleMax) title = title.slice(0, -2);
  if (title !== header.title) title = `${title}…`;
  ctx.fillText(title, x + headH, y + headH / 2 + 1);

  const pad = Math.max(2, Math.round(Math.min(w, h) * 0.015));
  const bx = x + pad, by = y + headH + pad, bw = w - 2 * pad, bh = h - headH - 2 * pad;
  if (!snap) {
    ctx.fillStyle = mix(ground, ink, 0.25);
    ctx.font = `500 ${Math.round(Math.min(bh * 0.3, bw * 0.12))}px ${TERMINAL_FONT_STACK}`;
    ctx.textAlign = "center";
    ctx.fillText(">_", x + w / 2, by + bh / 2);
    ctx.restore();
    return;
  }
  const ratio = charRatio(ctx);
  const { font, cellW, lineH, fit } = fitTerminal(snap.cols, bw, bh, ratio);
  const { first, end } = shownRows(snap, fit);
  const top = by;
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  for (let row = first; row < end; row += 1) {
    const ry = top + (row - first) * lineH;
    for (const run of snap.lines[row] ?? []) {
      if (!run.bg) continue;
      ctx.fillStyle = run.bg;
      ctx.fillRect(bx + run.col * cellW, ry, run.cells * cellW + 0.5, lineH + 0.5);
    }
    for (const run of snap.lines[row] ?? []) {
      if (!run.text.trim()) continue;
      ctx.fillStyle = run.fg;
      ctx.strokeStyle = run.fg;
      ctx.font = `${run.italic ? "italic " : ""}${run.bold ? 700 : 500} ${font}px ${TERMINAL_FONT_STACK}`;
      const rx = bx + run.col * cellW;
      const chars = [...run.text];
      const perCell = chars.length === run.cells;
      // One fillText per run when the font keeps to the grid; cell by cell otherwise.
      const plain = perCell && !chars.some((ch) => BOX[ch] || QUAD[ch] || SHADE[ch])
        && Math.abs(ctx.measureText(run.text).width - run.cells * cellW) < cellW * 0.25;
      if (plain) ctx.fillText(run.text, rx, ry + lineH / 2);
      else {
        let col = 0;
        for (const ch of chars) {
          const step = perCell ? 1 : run.cells;
          const cx = rx + col * cellW;
          if (!drawGlyph(ctx, ch, cx, ry, cellW * step, lineH) && ch !== " ") ctx.fillText(ch, cx, ry + lineH / 2);
          col += step;
        }
      }
      if (run.underline) ctx.fillRect(rx, ry + lineH - Math.max(1, font / 12), run.cells * cellW, Math.max(1, font / 12));
      if (run.strike) ctx.fillRect(rx, ry + lineH / 2, run.cells * cellW, Math.max(1, font / 12));
    }
  }
  if (snap.cursor && blinkOn) {
    const [cr, cc] = snap.cursor;
    if (cr >= first && cr < end) {
      ctx.fillStyle = snap.cursorColor;
      ctx.fillRect(bx + cc * cellW, top + (cr - first) * lineH + 1, Math.max(1, cellW * 0.15), lineH - 2);
    }
  }
  ctx.restore();
}

/** Columns x rows for `n` tiles in a `w` x `h` screen, so each terminal gets the largest text. Pure. */
export function gridShape(n: number, w: number, h: number, gap: number): { cols: number; rows: number } {
  let best = { cols: 1, rows: Math.max(1, n), score: -1 };
  for (let cols = 1; cols <= Math.max(1, n); cols += 1) {
    const rows = Math.ceil(n / cols);
    const tw = (w - gap * (cols + 1)) / cols, th = (h - gap * (rows + 1)) / rows;
    // A coding pane is about 80 x 30: score by the font that such a terminal gets.
    const score = Math.min(tw / (80 * 0.6), th / (30 * LINE_RATIO));
    if (score > best.score) best = { cols, rows, score };
  }
  return { cols: best.cols, rows: best.rows };
}

export interface GridTile {
  header: TileHeader;
  snap: TermSnapshot | null;
}

/** All panes on one screen, in a grid; a single pane fills the screen. */
export function paintTerminalGrid(ctx: CanvasRenderingContext2D, tiles: readonly GridTile[], blinkOn: boolean, ground = "#0b0c0f"): void {
  const { width: w, height: h } = ctx.canvas;
  ctx.fillStyle = ground;
  ctx.fillRect(0, 0, w, h);
  if (tiles.length === 0) return;
  const gap = tiles.length === 1 ? 0 : Math.max(4, Math.round(Math.min(w, h) * 0.012));
  const { cols, rows } = gridShape(tiles.length, w, h, gap);
  const tw = (w - gap * (cols + 1)) / cols, th = (h - gap * (rows + 1)) / rows;
  tiles.forEach((tile, i) => {
    const c = i % cols, r = Math.floor(i / cols);
    paintTerminalTile(ctx, Math.round(gap + c * (tw + gap)), Math.round(gap + r * (th + gap)), Math.floor(tw), Math.floor(th), tile.header, tile.snap, blinkOn);
  });
}

// ── What a terminal screen shows ─────────────────────────────────────────

/** A pane to draw: where its live terminal is registered, and the server's replay as a fallback. */
export interface TerminalTileFace {
  header: TileHeader;
  workspaceId: string;
  /** Names the pane may be registered under (call-sign, title). */
  names: readonly string[];
  /** The server's plain replay, for a pane the IDE has not mounted. */
  fallback?: { cols: number; lines: readonly string[]; cursor: [number, number] | null; at: number };
}

/** A screen that shows one pane (a desk) or every pane (the grid screens). */
export interface TerminalFace {
  kind: "terminals";
  tiles: readonly TerminalTileFace[];
}
