/**
 * Every change the grid makes to a sheet, written as mutations of a sheet.
 *
 * The editor runs them inside `apply` of `useNodeSpecEditor`, which hands a
 * draft (`../produce.ts`) and turns the mutations into the next immutable spec
 * with everything untouched shared; one call is one undo step. Tests run them
 * on plain objects. Rows are addressed by their STORED index here: the editor
 * maps the grid's view rows (filtered) to stored rows before it calls.
 *
 * What each operation keeps true, because `normalize` in `sheets.py` would
 * otherwise refuse the save or change what the person sees:
 * * an empty cell is a missing key, never null or "";
 * * blank rows trailing the sheet are dropped (the grid offers empty rows
 *   below the last one), blank rows between filled ones stay;
 * * a formula column never stores cells, and no formula may name a column
 *   that is gone;
 * * a chart only names columns that exist, and its row range follows rows
 *   inserted or deleted above or inside it.
 */
import {
  MAX_CHARTS,
  MAX_COLUMNS,
  MAX_ROWS,
  MAX_SHEETS,
  blankSheet,
  clean,
  columnLetter,
  convertCell,
  isNumber,
  MAX_LABEL_CHARS,
  MAX_NAME_CHARS,
  slug,
  uniqueKey,
  type CellValue,
  type ColumnType,
  type Row,
  type Sheet,
  type SheetChart,
  type SheetColumn,
  type SheetsSpec,
  type BoundSeries,
} from "./model";
import { formulaNames, parseFormula } from "./formula";

export interface CellWrite {
  row: number;
  key: string;
  /** null empties the cell. */
  value: CellValue | null;
}

/** Drop blank rows at the end of the sheet (as `normalize` does on save). */
export function trimRows(sheet: Sheet): void {
  let end = sheet.rows.length;
  while (end > 0 && Object.keys(sheet.rows[end - 1]).length === 0) end -= 1;
  if (end < sheet.rows.length) sheet.rows.splice(end);
}

/** Write cells; rows past the end are created (up to the sheet's row limit). */
export function writeCells(sheet: Sheet, writes: readonly CellWrite[]): void {
  const formulas = new Set(sheet.columns.filter((c) => c.formula).map((c) => c.key));
  const known = new Set(sheet.columns.map((c) => c.key));
  for (const write of writes) {
    if (write.row < 0 || write.row >= MAX_ROWS || formulas.has(write.key) || !known.has(write.key)) continue;
    if (write.value === null && write.row >= sheet.rows.length) continue;
    while (sheet.rows.length <= write.row) sheet.rows.push({});
    const row = sheet.rows[write.row];
    if (write.value === null || write.value === "") {
      if (write.key in row) delete row[write.key];
    } else if (!sameCell(row[write.key], write.value)) {
      row[write.key] = write.value;
    }
  }
  trimRows(sheet);
}

function sameCell(a: CellValue | undefined, b: CellValue): boolean {
  if (typeof a === "object" && typeof b === "object" && a && b) {
    return a.text === b.text && a.href === b.href && a.tone === b.tone;
  }
  return a === b;
}

/** Empty every cell of `rows` × `keys`. */
export function clearCells(sheet: Sheet, rows: readonly number[], keys: readonly string[]): void {
  writeCells(
    sheet,
    rows.flatMap((row) => keys.map((key) => ({ row, key, value: null }))),
  );
}

/**
 * Add columns so a block `count` columns wide fits from column `from`: the
 * columns a paste wider than the sheet needs. Returns how many were added.
 */
export function ensureColumns(sheet: Sheet, count: number): number {
  const missing = Math.min(count, MAX_COLUMNS) - sheet.columns.length;
  if (missing <= 0) return 0;
  insertColumns(sheet, sheet.columns.length, missing);
  return missing;
}

/** Copy the first row of the block to the others (`down`), or the first column (`right`). */
export function fill(
  sheet: Sheet,
  rows: readonly number[],
  keys: readonly string[],
  direction: "down" | "right",
  convert: (value: CellValue, key: string) => CellValue | null,
): void {
  const writes: CellWrite[] = [];
  if (direction === "down") {
    const [source, ...targets] = rows;
    for (const key of keys) {
      const value = sheet.rows[source]?.[key];
      for (const row of targets) writes.push({ row, key, value: value === undefined ? null : value });
    }
  } else {
    const [source, ...targets] = keys;
    for (const row of rows) {
      const value = sheet.rows[row]?.[source];
      for (const key of targets) writes.push({ row, key, value: value === undefined ? null : convert(value, key) });
    }
  }
  writeCells(sheet, writes);
}

function shiftCharts(sheet: Sheet, at: number, delta: number): void {
  // 1-based inclusive ranges, as the spec writes them.
  for (const chart of sheet.charts ?? []) {
    if (!chart.rows) continue;
    let [first, last] = chart.rows;
    const position = at + 1;
    if (delta > 0) {
      if (position <= first) first += delta;
      if (position <= last) last += delta;
    } else {
      const gone = -delta;
      const end = position + gone - 1;
      const before = (n: number) => (n < position ? n : n > end ? n - gone : position);
      first = before(first);
      last = Math.max(first, last > end ? last - gone : Math.min(last, position - 1));
    }
    chart.rows = [Math.max(1, first), Math.max(1, last)];
  }
}

/** `count` blank rows before stored row `at`. */
export function insertRows(sheet: Sheet, at: number, count: number): void {
  const room = MAX_ROWS - sheet.rows.length;
  const n = Math.max(0, Math.min(count, room));
  if (!n) return;
  if (at >= sheet.rows.length) return; // below the data the grid already shows empty rows
  sheet.rows.splice(at, 0, ...Array.from({ length: n }, () => ({})));
  shiftCharts(sheet, at, n);
}

/** Delete stored rows (any order, duplicates ignored). */
export function deleteRows(sheet: Sheet, rows: readonly number[]): void {
  const sorted = [...new Set(rows)].filter((row) => row >= 0 && row < sheet.rows.length).sort((a, b) => b - a);
  for (const row of sorted) {
    sheet.rows.splice(row, 1);
    shiftCharts(sheet, row, -1);
  }
  trimRows(sheet);
}

/** `count` new columns before column `at`, labelled with their letter. */
export function insertColumns(sheet: Sheet, at: number, count: number): string[] {
  const n = Math.max(0, Math.min(count, MAX_COLUMNS - sheet.columns.length));
  const used = new Set(sheet.columns.map((c) => c.key));
  const labels = new Set(sheet.columns.map((c) => c.label));
  const made: SheetColumn[] = [];
  let letter = sheet.columns.length;
  for (let i = 0; i < n; i += 1) {
    let label = columnLetter(letter);
    while (labels.has(label)) label = columnLetter(++letter);
    letter += 1;
    labels.add(label);
    const key = uniqueKey(slug(label, sheet.columns.length + i), used);
    used.add(key);
    made.push({ key, label });
  }
  sheet.columns.splice(Math.max(0, Math.min(at, sheet.columns.length)), 0, ...made);
  return made.map((c) => c.key);
}

/** The formula columns (other than `keys` themselves) that read any of `keys`. */
export function formulaUsers(sheet: Sheet, keys: readonly string[]): SheetColumn[] {
  const gone = new Set(keys);
  return sheet.columns.filter((column) => {
    if (!column.formula || gone.has(column.key)) return false;
    try {
      return formulaNames(parseFormula(column.formula)).some((name) => gone.has(name));
    } catch {
      return false;
    }
  });
}

/**
 * Delete columns by key. Refused (returns the formula columns in the way)
 * when a remaining formula reads one of them: the save would be refused.
 */
export function deleteColumns(sheet: Sheet, keys: readonly string[]): SheetColumn[] {
  const users = formulaUsers(sheet, keys);
  if (users.length) return users;
  const gone = new Set(keys);
  if (gone.size >= sheet.columns.length) return []; // a sheet keeps at least one column
  sheet.columns = sheet.columns.filter((column) => !gone.has(column.key));
  for (const row of sheet.rows) for (const key of gone) if (key in row) delete row[key];
  if (sheet.charts) {
    const kept: SheetChart[] = [];
    for (const chart of sheet.charts) {
      if (typeof chart.x === "string" && gone.has(chart.x)) delete chart.x;
      const bound = chart.series.some((s) => "column" in s);
      if (bound) chart.series = chart.series.filter((s) => !("column" in s) || !gone.has((s as BoundSeries).column));
      if (!bound || chart.series.length) kept.push(chart);
    }
    if (kept.length) sheet.charts = kept;
    else delete sheet.charts;
  }
  sheet.freeze = Math.min(sheet.freeze ?? 1, sheet.columns.length);
  trimRows(sheet);
  return [];
}

/** Move column `from` to position `to`. */
export function moveColumn(sheet: Sheet, from: number, to: number): void {
  if (from === to || from < 0 || from >= sheet.columns.length) return;
  const [column] = sheet.columns.splice(from, 1);
  sheet.columns.splice(Math.max(0, Math.min(to, sheet.columns.length)), 0, column);
}

const collator = (() => {
  try {
    return new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
  } catch {
    return null;
  }
})();

/**
 * Sort the stored rows by one column, the way the page sorts: numbers (and
 * checks) by value, other cells as text in natural order, empty cells last
 * whatever the direction, equal cells in their order before.
 *
 * `keyRows` are the rows with their formula cells computed (so a formula
 * column sorts by its values); they line up with `sheet.rows`.
 */
export function sortRows(sheet: Sheet, key: string, direction: 1 | -1, numeric: boolean, keyRows: readonly Row[]): void {
  const values = keyRows.map((row) => {
    const cell = row[key];
    if (cell === undefined || cell === "") return null;
    if (numeric) {
      if (typeof cell === "boolean") return cell ? 1 : 0;
      return isNumber(cell) ? cell : null;
    }
    return typeof cell === "object" ? String(cell.text ?? "") : String(cell);
  });
  const order = sheet.rows.map((_, index) => index);
  order.sort((a, b) => {
    const x = values[a];
    const y = values[b];
    if (x === null || y === null) return x === y ? a - b : x === null ? 1 : -1;
    let result: number;
    if (typeof x === "number" && typeof y === "number") result = x - y;
    else result = collator ? collator.compare(String(x), String(y)) : String(x) < String(y) ? -1 : String(x) > String(y) ? 1 : 0;
    return result ? result * direction : a - b;
  });
  const before = sheet.rows.slice();
  sheet.rows = order.map((index) => before[index]);
  trimRows(sheet);
}

export type ColumnPatch = Partial<Omit<SheetColumn, "key">>;

/**
 * Change a column. A new type carries every cell into it (text that reads as
 * a number becomes one); a formula, once set, empties the column's stored
 * cells; empty fields are removed rather than stored as "".
 */
export function patchColumn(sheet: Sheet, index: number, patch: ColumnPatch, locale?: string): void {
  const column = sheet.columns[index];
  if (!column) return;
  const record = column as unknown as Record<string, unknown>;
  for (const [field, value] of Object.entries(patch)) {
    if (value === undefined || value === "" || value === null || value === false) delete record[field];
    else record[field] = field === "label" ? clean(value, MAX_LABEL_CHARS) || column.label : value;
  }
  if ("type" in patch && patch.type) {
    const kind = patch.type as ColumnType;
    for (const row of sheet.rows) {
      if (!(column.key in row)) continue;
      const next = convertCell(row[column.key], kind, column.unit ?? "", locale);
      if (next === null) delete row[column.key];
      else if (!sameCell(row[column.key], next)) row[column.key] = next;
    }
  }
  if (column.formula) {
    for (const row of sheet.rows) if (column.key in row) delete row[column.key];
    if (column.type && !["number", "currency", "percent"].includes(column.type)) delete column.type;
  }
  if (column.total && column.total !== "count" && column.type && !["number", "currency", "percent", "check"].includes(column.type)) {
    delete column.total;
  }
  trimRows(sheet);
}

/** A formula as `normalize` stores it: one line, no leading "=", lower case. */
export function normalFormula(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ").replace(/^=+/, "").trim().toLowerCase();
}

// ------------------------------------------------------------------ sheets

export function addSheet(spec: SheetsSpec, name: string, at = spec.sheets.length): number {
  if (spec.sheets.length >= MAX_SHEETS) return -1;
  const sheet = blankSheet(name, spec.sheets);
  const index = Math.max(0, Math.min(at, spec.sheets.length));
  spec.sheets.splice(index, 0, sheet);
  return index;
}

export function duplicateSheet(spec: SheetsSpec, index: number, copyWord: string): number {
  const source = spec.sheets[index];
  if (!source || spec.sheets.length >= MAX_SHEETS) return -1;
  const taken = new Set(spec.sheets.map((s) => s.name));
  let name = clean(`${source.name} ${copyWord}`, MAX_NAME_CHARS);
  for (let n = 2; taken.has(name); n += 1) name = clean(`${source.name} ${copyWord} ${n}`, MAX_NAME_CHARS);
  const copy = JSON.parse(JSON.stringify(source)) as Sheet;
  copy.name = name;
  spec.sheets.splice(index + 1, 0, copy);
  return index + 1;
}

export function renameSheet(spec: SheetsSpec, index: number, name: string): void {
  const text = clean(name, MAX_NAME_CHARS);
  if (text && spec.sheets[index] && spec.sheets[index].name !== text) spec.sheets[index].name = text;
}

export function moveSheet(spec: SheetsSpec, from: number, to: number): void {
  if (from === to || !spec.sheets[from] || to < 0 || to >= spec.sheets.length) return;
  const [sheet] = spec.sheets.splice(from, 1);
  spec.sheets.splice(to, 0, sheet);
}

export function deleteSheet(spec: SheetsSpec, index: number): void {
  if (spec.sheets.length <= 1 || !spec.sheets[index]) return;
  spec.sheets.splice(index, 1);
}

// ------------------------------------------------------------------ charts

export function addChart(sheet: Sheet, chart: SheetChart): number {
  const charts = sheet.charts ?? [];
  if (charts.length >= MAX_CHARTS) return -1;
  sheet.charts = [...charts, chart];
  return sheet.charts.length - 1;
}

export function replaceChart(sheet: Sheet, index: number, chart: SheetChart): void {
  if (sheet.charts?.[index]) sheet.charts[index] = chart;
}

export function deleteChart(sheet: Sheet, index: number): void {
  if (!sheet.charts?.[index]) return;
  sheet.charts.splice(index, 1);
  if (!sheet.charts.length) delete sheet.charts;
}
