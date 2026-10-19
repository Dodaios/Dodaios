/**
 * The arithmetic of follow mode: one file laid out over several columns that
 * read on from each other, the way a newspaper page does.
 *
 * The first column scrolls to `top`; every later column `index` scrolls to
 * `top + index * step + lead`, so it starts on the line after the last full
 * line of the column before it. `lead` is the blank space the editor keeps
 * above the first line: the first column shows it, the others skip it. Kept
 * free of the editor engine so the maths can be tested on its own.
 */

/** Narrower than this, a column cuts off too much of an ordinary line of code. */
export const FOLLOW_COLUMN_MIN_PX = 440;
/** More columns than this stop being readable on any monitor. */
export const FOLLOW_COLUMNS_MAX = 6;

/** How many columns fit a text area this wide; follow mode always shows at least two. */
export function followColumnCount(width: number): number {
  return Math.max(2, Math.min(FOLLOW_COLUMNS_MAX, Math.floor(width / FOLLOW_COLUMN_MIN_PX)));
}

/**
 * How far each column scrolls past the one before it: the full lines that fit
 * one column below the blank space above the first line. A line cut off at
 * the bottom of a column is the first line of the next one, so no line is
 * ever missing.
 */
export function followStep(viewportHeight: number, lineHeight: number, lead = 0): number {
  if (lineHeight <= 0) return Math.max(1, viewportHeight - lead);
  return Math.max(lineHeight, Math.floor((viewportHeight - lead) / lineHeight) * lineHeight);
}

/** Where column `index` scrolls to when the first one is at `top`. */
export function followOffset(top: number, index: number, step: number, lead = 0): number {
  return index === 0 ? top : top + index * step + lead;
}

/**
 * The scroll offset of the first column, kept in range: never above the
 * file's start, and never further down than the point where the file's end
 * reaches the bottom of the last column.
 */
export function clampFollowTop(
  top: number,
  contentHeight: number,
  viewportHeight: number,
  step: number,
  count: number,
  lead = 0,
): number {
  const last = followOffset(0, count - 1, step, lead);
  const max = Math.max(0, contentHeight - viewportHeight - last);
  return Math.min(max, Math.max(0, top));
}

/**
 * The column that shows a line starting `lineTop` pixels into the file, with
 * the first column scrolled to `top`; null when no column shows it.
 */
export function followColumnOf(lineTop: number, top: number, step: number, count: number, lead = 0): number | null {
  if (lineTop < top || step <= 0) return null;
  for (let index = count - 1; index >= 0; index -= 1) {
    if (lineTop >= followOffset(top, index, step, lead)) {
      return index === count - 1 && lineTop >= followOffset(top, count, step, lead) ? null : index;
    }
  }
  return null;
}
