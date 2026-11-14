/**
 * The grid's selection and how the keys move it, as pure functions.
 *
 * Positions are in VIEW space: `row` counts the rows the grid shows (the
 * sheet's rows minus those a filter hides, then the empty rows offered below
 * them), `col` counts columns from 0. The editor maps a view row to the
 * stored row when it changes the spec.
 *
 * A selection is a range (from `anchor` to `focus`, either corner first) and
 * an `active` cell inside it: the one typing goes into. Shift with an arrow
 * moves `focus` and keeps `active`; Enter and Tab inside a range of several
 * cells move `active` through the range and keep the range, so a block can be
 * filled in one value after another.
 */

export interface CellPos {
  row: number;
  col: number;
}

export interface Selection {
  anchor: CellPos;
  focus: CellPos;
  active: CellPos;
}

export interface CellRange {
  top: number;
  left: number;
  bottom: number;
  right: number;
}

/** How big the grid is: rows (with the empty rows below the data) and columns. */
export interface GridSize {
  rows: number;
  cols: number;
}

export function at(row: number, col: number): Selection {
  const pos = { row, col };
  return { anchor: pos, focus: pos, active: pos };
}

export function rangeOf(selection: Selection): CellRange {
  const { anchor, focus } = selection;
  return {
    top: Math.min(anchor.row, focus.row),
    bottom: Math.max(anchor.row, focus.row),
    left: Math.min(anchor.col, focus.col),
    right: Math.max(anchor.col, focus.col),
  };
}

export function isSingle(selection: Selection): boolean {
  const range = rangeOf(selection);
  return range.top === range.bottom && range.left === range.right;
}

export function inRange(range: CellRange, row: number, col: number): boolean {
  return row >= range.top && row <= range.bottom && col >= range.left && col <= range.right;
}

function clampPos(pos: CellPos, size: GridSize): CellPos {
  return {
    row: Math.max(0, Math.min(size.rows - 1, pos.row)),
    col: Math.max(0, Math.min(size.cols - 1, pos.col)),
  };
}

/** The selection kept inside a grid that may have shrunk (rows or columns deleted). */
export function clampSelection(selection: Selection, size: GridSize): Selection {
  return {
    anchor: clampPos(selection.anchor, size),
    focus: clampPos(selection.focus, size),
    active: clampPos(selection.active, size),
  };
}

/** One step with an arrow key; with `extend` (Shift) the range grows from its anchor. */
export function move(selection: Selection, rows: number, cols: number, size: GridSize, extend = false): Selection {
  if (extend) {
    const focus = clampPos({ row: selection.focus.row + rows, col: selection.focus.col + cols }, size);
    return { anchor: selection.anchor, focus, active: selection.active };
  }
  const next = clampPos({ row: selection.active.row + rows, col: selection.active.col + cols }, size);
  return { anchor: next, focus: next, active: next };
}

/**
 * Where Cmd/Ctrl with an arrow lands: the edge of the block of filled cells
 * the cell is in, or the next filled cell after a gap, or the grid's edge.
 */
export function jumpTarget(
  from: CellPos,
  rows: number,
  cols: number,
  size: GridSize,
  filled: (row: number, col: number) => boolean,
): CellPos {
  const step = (pos: CellPos): CellPos => ({ row: pos.row + rows, col: pos.col + cols });
  const inside = (pos: CellPos) => pos.row >= 0 && pos.row < size.rows && pos.col >= 0 && pos.col < size.cols;
  let pos = from;
  let next = step(pos);
  if (!inside(next)) return pos;
  if (filled(pos.row, pos.col) && filled(next.row, next.col)) {
    // Inside a block: to its last filled cell.
    while (inside(next) && filled(next.row, next.col)) {
      pos = next;
      next = step(pos);
    }
    return pos;
  }
  // At a block's edge or in a gap: to the next filled cell, else the grid's edge.
  pos = next;
  while (inside(step(pos)) && !filled(pos.row, pos.col)) pos = step(pos);
  return pos;
}

export function jump(
  selection: Selection,
  rows: number,
  cols: number,
  size: GridSize,
  filled: (row: number, col: number) => boolean,
  extend = false,
): Selection {
  const origin = extend ? selection.focus : selection.active;
  const target = jumpTarget(origin, rows, cols, size, filled);
  if (extend) return { anchor: selection.anchor, focus: target, active: selection.active };
  return at(target.row, target.col);
}

/**
 * Enter (down), Shift+Enter (up), Tab (right), Shift+Tab (left).
 *
 * In a range of several cells the active cell walks through the range and
 * wraps at its edges; otherwise the selection moves one cell.
 */
export function advance(selection: Selection, byRow: boolean, forward: boolean, size: GridSize): Selection {
  if (isSingle(selection)) return byRow ? move(selection, forward ? 1 : -1, 0, size) : move(selection, 0, forward ? 1 : -1, size);
  const range = rangeOf(selection);
  const height = range.bottom - range.top + 1;
  const width = range.right - range.left + 1;
  // The cell's place in reading order: by rows for Tab, by columns for Enter.
  const { row, col } = selection.active;
  let index = byRow ? (col - range.left) * height + (row - range.top) : (row - range.top) * width + (col - range.left);
  const total = height * width;
  index = (index + (forward ? 1 : -1) + total) % total;
  const active = byRow
    ? { row: range.top + (index % height), col: range.left + Math.floor(index / height) }
    : { row: range.top + Math.floor(index / width), col: range.left + (index % width) };
  return { anchor: selection.anchor, focus: selection.focus, active };
}

/** Whole rows `top` … `bottom` (a click on row numbers). */
export function selectRows(top: number, bottom: number, size: GridSize): Selection {
  return {
    anchor: { row: top, col: 0 },
    focus: { row: bottom, col: size.cols - 1 },
    active: { row: top, col: 0 },
  };
}

/** Whole columns `left` … `right` (a click on column heads), over the rows that hold data. */
export function selectColumns(left: number, right: number, dataRows: number): Selection {
  const last = Math.max(0, dataRows - 1);
  return {
    anchor: { row: 0, col: left },
    focus: { row: last, col: right },
    active: { row: 0, col: left },
  };
}

export function selectAll(size: GridSize, dataRows: number): Selection {
  return {
    anchor: { row: 0, col: 0 },
    focus: { row: Math.max(0, dataRows - 1), col: size.cols - 1 },
    active: { row: 0, col: 0 },
  };
}
