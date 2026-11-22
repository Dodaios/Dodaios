/**
 * How a sheet is revealed while an agent builds it.
 *
 * Built by hand, a sheet grows in a fixed order: the tab first, then the
 * header row, then the body row by row from the top. The frame wraps the
 * range written so far and grows downward; the cursor rests at the end of the
 * last row written. A row brings its values and its formatting together (it is one
 * table row, so frozen columns fade with it). Totals that change because of
 * the new rows update in place with a brief, quiet highlight once the rows
 * are in.
 *
 * The grid marks its elements (docs/node-live-build.md, "How a step names its
 * target"): the tab `/sheets/<n>`, the header row `/sheets/<n>/columns`, a body
 * row `/sheets/<n>/rows/<stored index>`, and the scroller carries the shown
 * sheet's index in `data-live-sheet`.
 */
import { columnTotal, computeRows, formulaPlan, totalAllowed } from "../../editors/sheets/formula";
import { columnKind, type Row, type Sheet, type SheetColumn, type SheetsSpec } from "../../editors/sheets/model";
import { LIVE_TIMING, prefersReducedMotion, revealDelays } from "../playback";
import type { RevealAdapter, RevealInput, RevealStep } from "../reveal";

/** How long the quiet highlight on a changed total lasts. */
const MARK_MS = 900;
/** The tab's slide: a few pixels in from the left, together with its fade. */
const TAB_SLIDE_PX = 12;

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** What the header row shows and how the rows are formatted: a change here restyles every row (widths are layout only). */
function shapeOf(columns: readonly SheetColumn[]): unknown {
  return columns.map((c) => ({ ...c, width: undefined }));
}

/** The stored row indices an edit changed or added, in order. */
export function changedRows(before: SheetsSpec | null, after: SheetsSpec, sheet: number): number[] {
  const next = after.sheets[sheet];
  if (!next) return [];
  const prev = before?.sheets[sheet];
  if (!prev || !same(shapeOf(prev.columns), shapeOf(next.columns))) return next.rows.map((_, i) => i);
  const out: number[] = [];
  next.rows.forEach((row, i) => {
    if (!same(prev.rows[i], row)) out.push(i);
  });
  return out;
}

/** The first sheet an edit touched (a new sheet, or one whose content changed), or -1. */
export function firstChangedSheet(before: SheetsSpec | null, after: SheetsSpec): number {
  return after.sheets.findIndex((sheet, i) => !before?.sheets[i] || !same(before.sheets[i], sheet));
}

function totalsOf(sheet: Sheet): Array<number | null> {
  const rows: Row[] = computeRows(sheet.rows, formulaPlan(sheet.columns));
  return sheet.columns.map((column) => {
    if (!column.total) return null;
    const kind = columnKind(column, rows);
    return totalAllowed(column.total, kind) ? columnTotal(column.total, kind, column.key, rows) : null;
  });
}

/** The columns whose total changed with the rows: those cells get the quiet highlight. */
export function changedTotals(before: SheetsSpec | null, after: SheetsSpec, sheet: number): number[] {
  const prev = before?.sheets[sheet];
  const next = after.sheets[sheet];
  if (!prev || !next || !same(shapeOf(prev.columns), shapeOf(next.columns))) return [];
  const was = totalsOf(prev);
  return totalsOf(next).flatMap((value, col) => (value !== was[col] ? [col] : []));
}

/** A quiet monochrome wash on `el` that fades out; nothing moves. */
function mark(el: Element): void {
  if (typeof el.animate !== "function") return;
  el.animate(
    [
      { boxShadow: "inset 0 0 0 999px hsl(var(--foreground) / 0.14)" },
      { boxShadow: "inset 0 0 0 999px hsl(var(--foreground) / 0)" },
    ],
    { duration: MARK_MS, easing: "ease-out" },
  );
}

/** A new tab slides into the bar from the left. */
function slideIn(el: Element): void {
  if (typeof el.animate !== "function") return;
  el.animate(
    [
      { transform: `translateX(-${TAB_SLIDE_PX}px)` },
      { transform: "translateX(0)" },
    ],
    { duration: LIVE_TIMING.fadeMs, easing: "ease-out" },
  );
}

function shownSheet(root: HTMLElement): number {
  const value = root.querySelector("[data-live-sheet]")?.getAttribute("data-live-sheet");
  const index = value === null || value === undefined ? NaN : Number(value);
  return Number.isInteger(index) ? index : -1;
}

export const sheetsReveal: RevealAdapter = {
  steps: (input) => {
    const { previous, next, initial, root } = input as RevealInput<SheetsSpec>;
    const sheet = shownSheet(root);
    if (sheet < 0 || !next.sheets[sheet]) return [];
    const before = initial ? null : previous;
    const steps: RevealStep[] = [];

    // 1. A new (or renamed) tab slides into the bar before its content plays.
    const tabs: number[] = [];
    if (before) {
      if (sheet >= before.sheets.length) tabs.push(sheet);
      else if (before.sheets[sheet].name !== next.sheets[sheet].name) tabs.push(sheet);
    }
    for (const tab of tabs) {
      const el = root.querySelector(`[data-live-path="/sheets/${tab}"]`);
      if (el && !prefersReducedMotion()) slideIn(el);
      steps.push({ target: { path: `/sheets/${tab}` }, framed: false });
    }

    // 2. The structure: the header row, when the columns are new or changed.
    const prev = before?.sheets[sheet];
    const cur = next.sheets[sheet];
    if (!prev || !same(shapeOf(prev.columns), shapeOf(cur.columns)) || !same(prev.freeze, cur.freeze)) {
      steps.push({ target: { path: `/sheets/${sheet}/columns` } });
    }

    // 3. The body, row by row from the top, each with its values and formatting.
    for (const row of changedRows(before, next, sheet)) steps.push({ target: { path: `/sheets/${sheet}/rows/${row}` } });

    // 4. Totals that moved with the new rows update in place, once the rows are in.
    const cols = changedTotals(before, next, sheet);
    if (cols.length > 0 && steps.length > 0 && !prefersReducedMotion()) {
      const delays = revealDelays(steps.length);
      const wait = (delays[delays.length - 1] ?? 0) + LIVE_TIMING.fadeMs;
      window.setTimeout(() => {
        for (const col of cols) {
          const el = root.querySelector(`[data-testid="sheet-total-${col}"]`);
          if (el) mark(el);
        }
      }, wait);
    }
    return steps;
  },
};
