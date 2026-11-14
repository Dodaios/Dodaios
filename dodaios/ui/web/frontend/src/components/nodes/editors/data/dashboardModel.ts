/**
 * The Analytics (``data``) spec as the editor works on it, and every
 * structural change the editor makes to it.
 *
 * The grammar is `dodaios/nodes/kinds/data.py`: a summary, the named
 * sources, and sections that each hold metric tiles, charts and tables. The
 * limits below mirror that file, so the editor never offers a tile, chart or
 * row the server would cut off.
 *
 * Every change here is written against a DRAFT (`produce` in `../produce`):
 * the functions mutate what they are given and are meant to run inside the
 * editor hook's `apply(draft => …)`, which turns them into one immutable,
 * undoable step. They are also plain enough to test on ordinary objects.
 */

/** Mirrors of the limits in `dodaios/nodes/kinds/data.py`. */
export const LIMITS = {
  sections: 12,
  metrics: 8,
  charts: 8,
  tables: 4,
  columns: 12,
  rows: 200,
  sources: 8,
  summary: 600,
  title: 120,
  text: 600,
  label: 80,
  value: 40,
  detail: 120,
  cell: 300,
  source: 80,
} as const;

export interface DashMetric {
  label: string;
  value: string;
  detail?: string;
  delta?: string;
  /** "lower": a falling figure is the good news (the delta's colour flips). */
  better?: "lower";
}

/**
 * A chart in the shared report grammar (`report_blocks.parse_chart`), plus
 * the dashboard's own `wide`. Kept loose here: the chart editor owns the
 * grammar, this editor only places charts.
 */
export interface DashChart {
  type: string;
  title?: string;
  x: string[];
  series: { name: string; data: (number | null)[] }[];
  unit?: string;
  note?: string;
  value?: string;
  delta?: string;
  stacked?: boolean;
  colors?: string[];
  wide?: boolean;
  [key: string]: unknown;
}

export type DashCell = string | number;

export interface DashTable {
  title: string;
  columns: string[];
  rows: DashCell[][];
}

export interface DashSection {
  title: string;
  text: string;
  metrics: DashMetric[];
  charts: DashChart[];
  tables: DashTable[];
}

export interface DashSpec {
  summary: string;
  sources?: string[];
  sections: DashSection[];
}

/** The three kinds of things a section holds, in the order the page draws them. */
export const PARTS = ["metrics", "charts", "tables"] as const;
export type Part = (typeof PARTS)[number];

/** What is selected in the editor: a section, or one item in one of its lists. */
export type DashSelection =
  | { kind: "section"; section: number }
  | { kind: Part; section: number; index: number };

/* --------------------------------------------------------------- reading */

function text(value: unknown): string {
  return typeof value === "string" ? value : typeof value === "number" ? String(value) : "";
}

function list<T>(value: unknown, read: (item: unknown) => T | null): T[] {
  if (!Array.isArray(value)) return [];
  const out: T[] = [];
  for (const item of value) {
    const read_ = read(item);
    if (read_ !== null) out.push(read_);
  }
  return out;
}

function readMetric(raw: unknown): DashMetric | null {
  if (!raw || typeof raw !== "object") return null;
  const source = raw as Record<string, unknown>;
  const metric: DashMetric = { label: text(source.label), value: text(source.value) };
  if (text(source.detail)) metric.detail = text(source.detail);
  if (text(source.delta)) metric.delta = text(source.delta);
  if (source.better === "lower") metric.better = "lower";
  return metric;
}

function readCell(value: unknown): DashCell {
  return typeof value === "number" && Number.isFinite(value) ? value : text(value);
}

function readTable(raw: unknown): DashTable | null {
  if (!raw || typeof raw !== "object") return null;
  const source = raw as Record<string, unknown>;
  const columns = list(source.columns, (name) => text(name));
  const rows = list(source.rows, (row) => {
    if (!Array.isArray(row)) return null;
    const cells = row.slice(0, columns.length).map(readCell);
    while (cells.length < columns.length) cells.push("");
    return cells;
  });
  return { title: text(source.title), columns, rows };
}

function readSection(raw: unknown): DashSection | null {
  if (!raw || typeof raw !== "object") return null;
  const source = raw as Record<string, unknown>;
  return {
    title: text(source.title),
    text: text(source.text),
    metrics: list(source.metrics, readMetric),
    charts: list(source.charts, (chart) =>
      chart && typeof chart === "object" && !Array.isArray(chart) ? ({ ...(chart as object) } as DashChart) : null,
    ),
    tables: list(source.tables, readTable),
  };
}

/**
 * The saved spec in the editor's shape. The server hands out normalized
 * specs, so this mostly fills in what a hand-written spec may leave out
 * (top-level parts become the first section, as `normalize` does).
 */
export function readDashSpec(raw: unknown): DashSpec {
  const source = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const sections = list(source.sections, readSection);
  const lead = readSection({ metrics: source.metrics, charts: source.charts, tables: source.tables });
  if (lead && PARTS.some((part) => lead[part].length > 0)) sections.unshift(lead);
  const spec: DashSpec = { summary: text(source.summary), sections };
  const sources = list(source.sources, (name) => text(name) || null);
  if (sources.length) spec.sources = sources;
  if (spec.sections.length === 0) spec.sections.push(emptySection());
  return spec;
}

/* ------------------------------------------------------------- templates */

export function emptySection(): DashSection {
  return { title: "", text: "", metrics: [], charts: [], tables: [] };
}

export function newMetric(label: string): DashMetric {
  return { label, value: "0" };
}

export function newTable(title: string, columns: [string, string]): DashTable {
  return { title, columns: [...columns], rows: [["", ""]] };
}

/* ------------------------------------------------------------ inspecting */

/** How many metrics, charts and tables the whole dashboard holds. */
export function partCount(spec: DashSpec): number {
  return spec.sections.reduce((sum, section) => sum + PARTS.reduce((n, part) => n + section[part].length, 0), 0);
}

/**
 * Whether removing `count` parts would leave nothing to show. The server
 * refuses a dashboard without a single metric, chart or table, so the editor
 * keeps the last one rather than letting the save fail.
 */
export function wouldEmpty(spec: DashSpec, count: number): boolean {
  return partCount(spec) - count <= 0;
}

export function canAdd(spec: DashSpec, section: number, part: Part): boolean {
  const holder = spec.sections[section];
  return !!holder && holder[part].length < LIMITS[part];
}

/**
 * Metrics per row on the page (`data._metrics`): rows of even length, so
 * five values read as three and two, not four and one.
 */
export function metricsPerRow(count: number): number {
  return count <= 4 ? Math.max(1, count) : count <= 6 ? 3 : 4;
}

/**
 * Which charts take a whole row on a wide window (`data._charts`): a chart
 * marked wide, and a chart that would otherwise sit alone in its row.
 */
export function chartRowSpans(charts: readonly { wide?: boolean }[]): boolean[] {
  const spans: boolean[] = [];
  let column = 0;
  charts.forEach((chart, index) => {
    let wide = chart.wide === true;
    if (!wide && column === 0) wide = index === charts.length - 1 || charts[index + 1]?.wide === true;
    column = wide || column === 1 ? 0 : 1;
    spans.push(wide);
  });
  return spans;
}

/** Problems the server would refuse, worded for the person, keyed like a selection. */
export interface DashProblem {
  section: number;
  part: Part;
  index: number;
  field: "label" | "value" | "columns";
}

export function findProblems(spec: DashSpec): DashProblem[] {
  const problems: DashProblem[] = [];
  spec.sections.forEach((section, s) => {
    section.metrics.forEach((metric, index) => {
      if (!metric.label.trim()) problems.push({ section: s, part: "metrics", index, field: "label" });
      if (!metric.value.trim()) problems.push({ section: s, part: "metrics", index, field: "value" });
    });
    section.tables.forEach((table, index) => {
      if (!table.columns.some((name) => name.trim())) problems.push({ section: s, part: "tables", index, field: "columns" });
    });
  });
  return problems;
}

/* --------------------------------------------------------------- changes */

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/** Move `list[from]` to `to` (clamped). Returns the index it landed on. */
export function moveInList<T>(items: T[], from: number, to: number): number {
  if (from < 0 || from >= items.length) return from;
  const target = Math.max(0, Math.min(items.length - 1, to));
  if (target === from) return from;
  const [item] = items.splice(from, 1);
  items.splice(target, 0, item as T);
  return target;
}

export function addSection(spec: DashSpec, after: number, title: string): number {
  if (spec.sections.length >= LIMITS.sections) return -1;
  const at = Math.max(0, Math.min(spec.sections.length, after + 1));
  // A section without a title or any part would be dropped by `normalize`,
  // which would make it vanish on the first save: it starts with a title.
  spec.sections.splice(at, 0, { ...emptySection(), title });
  return at;
}

export function duplicateSection(spec: DashSpec, index: number): number {
  const section = spec.sections[index];
  if (!section || spec.sections.length >= LIMITS.sections) return -1;
  spec.sections.splice(index + 1, 0, clone(section));
  return index + 1;
}

/** Remove a section, unless it holds the dashboard's last parts. */
export function removeSection(spec: DashSpec, index: number): boolean {
  const section = spec.sections[index];
  if (!section) return false;
  const holds = PARTS.reduce((n, part) => n + section[part].length, 0);
  if (wouldEmpty(spec, holds) || spec.sections.length === 1) return false;
  spec.sections.splice(index, 1);
  return true;
}

export function addItem(spec: DashSpec, section: number, part: Part, item: DashMetric | DashChart | DashTable, at?: number): number {
  const holder = spec.sections[section];
  if (!holder || holder[part].length >= LIMITS[part]) return -1;
  const items = holder[part] as unknown[];
  const index = at === undefined ? items.length : Math.max(0, Math.min(items.length, at));
  items.splice(index, 0, item);
  return index;
}

export function duplicateItem(spec: DashSpec, section: number, part: Part, index: number): number {
  const items = spec.sections[section]?.[part] as unknown[] | undefined;
  if (!items || index < 0 || index >= items.length || items.length >= LIMITS[part]) return -1;
  items.splice(index + 1, 0, clone(items[index]));
  return index + 1;
}

/** Remove one item, unless it is the dashboard's last part. */
export function removeItem(spec: DashSpec, section: number, part: Part, index: number): boolean {
  const items = spec.sections[section]?.[part] as unknown[] | undefined;
  if (!items || index < 0 || index >= items.length || wouldEmpty(spec, 1)) return false;
  items.splice(index, 1);
  return true;
}

/**
 * Move an item to another section (to its end). Returns its new index there,
 * or -1 when that section is full.
 */
export function moveItemToSection(spec: DashSpec, section: number, part: Part, index: number, target: number): number {
  const from = spec.sections[section]?.[part] as unknown[] | undefined;
  const to = spec.sections[target]?.[part] as unknown[] | undefined;
  if (!from || !to || section === target || index < 0 || index >= from.length) return -1;
  if (to.length >= LIMITS[part]) return -1;
  const [item] = from.splice(index, 1);
  to.push(item);
  return to.length - 1;
}

/* ------------------------------------------------------------- the table */

const PLAIN_NUMBER = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i;

/**
 * What a typed cell is stored as. Only a plain number ("412", "-3.5")
 * becomes a number; anything with a unit, a grouping mark or a currency
 * ("14,420 €") stays the text the person wrote, which the page still reads
 * as a number for alignment and sorting (`data._cell_number`).
 */
export function cellFromInput(typed: string): DashCell {
  const trimmed = typed.trim();
  if (trimmed !== "" && PLAIN_NUMBER.test(trimmed) && trimmed.length <= 17) {
    const number = Number(trimmed);
    if (Number.isFinite(number)) return number;
  }
  return typed.slice(0, LIMITS.cell);
}

export function cellToInput(cell: DashCell | undefined): string {
  return cell === undefined ? "" : String(cell);
}

export function setCell(table: DashTable, row: number, column: number, typed: string): void {
  const cells = table.rows[row];
  if (!cells || column < 0 || column >= table.columns.length) return;
  cells[column] = cellFromInput(typed);
}

export function addRow(table: DashTable, at = table.rows.length): number {
  if (table.rows.length >= LIMITS.rows) return -1;
  const index = Math.max(0, Math.min(table.rows.length, at));
  table.rows.splice(index, 0, table.columns.map(() => ""));
  return index;
}

export function removeRow(table: DashTable, row: number): void {
  if (row >= 0 && row < table.rows.length) table.rows.splice(row, 1);
}

export function addColumn(table: DashTable, name: string, at = table.columns.length): number {
  if (table.columns.length >= LIMITS.columns) return -1;
  const index = Math.max(0, Math.min(table.columns.length, at));
  table.columns.splice(index, 0, name);
  for (const row of table.rows) row.splice(index, 0, "");
  return index;
}

/** Remove a column, but never the table's last one (a table needs a column). */
export function removeColumn(table: DashTable, column: number): boolean {
  if (table.columns.length <= 1 || column < 0 || column >= table.columns.length) return false;
  table.columns.splice(column, 1);
  for (const row of table.rows) row.splice(column, 1);
  return true;
}

export function moveColumn(table: DashTable, from: number, to: number): number {
  const landed = moveInList(table.columns, from, to);
  if (landed !== from) for (const row of table.rows) moveInList(row, from, landed);
  return landed;
}

/**
 * Text copied from a spreadsheet or a CSV file, as rows of cells: tabs
 * between cells when there are any, else commas or semicolons. Quoted cells
 * may hold the separator and line breaks.
 */
export function parsePastedGrid(text: string): string[][] {
  const source = text.replace(/\r\n?/g, "\n").replace(/\n$/, "");
  if (!source) return [];
  const firstLine = source.split("\n", 1)[0] ?? "";
  const separator = firstLine.includes("\t") ? "\t" : firstLine.includes(";") ? ";" : firstLine.includes(",") ? "," : "\t";
  const rows: string[][] = [[]];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < source.length; index++) {
    const char = source[index] as string;
    if (quoted) {
      if (char === '"' && source[index + 1] === '"') {
        cell += '"';
        index++;
      } else if (char === '"') quoted = false;
      else cell += char;
    } else if (char === '"' && cell === "") quoted = true;
    else if (char === separator) {
      (rows[rows.length - 1] as string[]).push(cell);
      cell = "";
    } else if (char === "\n") {
      (rows[rows.length - 1] as string[]).push(cell);
      rows.push([]);
      cell = "";
    } else cell += char;
  }
  (rows[rows.length - 1] as string[]).push(cell);
  return rows;
}

/**
 * Paste a grid into the table with its top-left cell at (`row`, `column`),
 * adding rows (and columns, up to the limits) as needed. Returns whether it
 * pasted more than one cell; a single cell is left to the field's own paste.
 */
export function pasteGrid(table: DashTable, row: number, column: number, grid: string[][]): boolean {
  if (grid.length === 0 || (grid.length === 1 && (grid[0]?.length ?? 0) <= 1)) return false;
  const width = Math.max(...grid.map((cells) => cells.length));
  while (table.columns.length < Math.min(LIMITS.columns, column + width)) addColumn(table, "");
  grid.forEach((cells, offset) => {
    const target = row + offset;
    if (target >= LIMITS.rows) return;
    while (table.rows.length <= target) addRow(table);
    cells.forEach((typed, step) => setCell(table, target, column + step, typed));
  });
  return true;
}
