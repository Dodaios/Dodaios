/**
 * The sheet spec as the editor holds it, and how a cell is read, shown and typed.
 *
 * The spec is the one `dodaios/nodes/kinds/sheets.py` normalizes: every value
 * the editor writes must be one that `normalize` keeps unchanged, or the saved
 * spec the server hands back would differ from what the person sees (a number
 * typed as "1,5" must be stored as the number 1.5, a label must be one line).
 * So the rules here mirror the Python ones on purpose: the limits, the column
 * types and their aliases, the key slugs, the type inference, the cleaning of
 * texts and the words a check column reads as yes or no.
 *
 * Numbers and dates are shown in the viewer's locale (`navigator.language`),
 * the same locale the node's page uses, so the grid and the page agree.
 */

export const MAX_SHEETS = 12;
export const MAX_COLUMNS = 30;
export const MAX_ROWS = 1_000;
export const MAX_FREEZE = 3;
export const MAX_DECIMALS = 4;
export const MAX_CELL_CHARS = 500;
export const MAX_NAME_CHARS = 40;
export const MAX_LABEL_CHARS = 60;
export const MAX_KEY_CHARS = 40;
export const MAX_UNIT_CHARS = 12;
export const MAX_NOTE_CHARS = 200;
export const MAX_STATUS_CHARS = 60;
export const MAX_DATE_CHARS = 40;
export const MAX_FORMULA_CHARS = 200;
export const MAX_CHARTS = 8;
export const MIN_WIDTH = 48;
export const MAX_WIDTH = 480;

export const COLUMN_TYPES = ["text", "number", "currency", "percent", "date", "check", "status", "link"] as const;
export type ColumnType = (typeof COLUMN_TYPES)[number];
export const TOTALS = ["sum", "avg", "min", "max", "count"] as const;
export type TotalKind = (typeof TOTALS)[number];
export const ALIGNS = ["left", "center", "right"] as const;
export type Align = (typeof ALIGNS)[number];
export const COLUMN_COLORS = ["blue", "orange", "green", "amber", "violet", "pink", "good", "warn", "bad", "muted"] as const;
export type ColumnColor = (typeof COLUMN_COLORS)[number];
export const TONES = ["good", "info", "warn", "bad"] as const;

/**
 * How the editor draws the column colours. The page maps the same names to
 * its theme tokens (`NAMED_COLORS` in `nodes/shell.py`); the app has no such
 * tokens, so the series colours are the kit's (`KIT_COLORS` in
 * `../controls.tsx`, the page's light theme) and the tones the app's own.
 */
export const COLOR_TOKENS: Record<ColumnColor, string> = {
  blue: "#2A6FD0",
  orange: "#D4532E",
  green: "#158F6B",
  amber: "#A86B00",
  violet: "#5B46C2",
  pink: "#C23F86",
  good: "hsl(var(--success))",
  warn: "hsl(var(--warning))",
  bad: "hsl(var(--destructive))",
  muted: "hsl(var(--muted-foreground))",
};

const NUMERIC: ReadonlySet<string> = new Set(["number", "currency", "percent"]);

export interface LinkCell {
  text: string;
  href?: string;
  tone?: string;
}

/** A stored cell: what `_cell` in `sheets.py` keeps. A missing key is an empty cell. */
export type CellValue = string | number | boolean | LinkCell;

export type Row = Record<string, CellValue>;

export interface SheetColumn {
  key: string;
  label: string;
  type?: ColumnType;
  unit?: string;
  decimals?: number;
  total?: TotalKind;
  formula?: string;
  width?: number;
  align?: Align;
  bold?: boolean;
  color?: ColumnColor;
}

/** A chart bound to the sheet's columns (see `drawn_chart` in `sheets.py`). */
export interface BoundSeries {
  column: string;
  name?: string;
}

/** A chart in its stored form: literal (report chart grammar) or bound to columns. */
export interface SheetChart {
  type: string;
  title?: string;
  unit?: string;
  note?: string;
  stacked?: boolean;
  colors?: string[];
  value?: string;
  delta?: string;
  x?: string | string[];
  series: Array<BoundSeries | { name?: string; data: Array<number | null> }>;
  rows?: [number, number];
}

export interface Sheet {
  name: string;
  columns: SheetColumn[];
  rows: Row[];
  freeze?: number;
  charts?: SheetChart[];
}

export interface SheetsSpec {
  sheets: Sheet[];
  note?: string;
}

export function isNumericType(kind: string): boolean {
  return NUMERIC.has(kind);
}

export function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** One line of text: whitespace collapsed, clipped (`clean` in `nodes/shell.py`). */
export function clean(value: unknown, limit: number): string {
  const text = String(value ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
  return text.slice(0, limit).trimEnd();
}

export function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

/** The spec as the editor can work on it, whatever the server handed over. */
export function readSpec(raw: unknown): SheetsSpec {
  const spec = (raw && typeof raw === "object" ? raw : {}) as Partial<SheetsSpec>;
  const sheets = Array.isArray(spec.sheets) ? spec.sheets.filter((s) => s && typeof s === "object") : [];
  return {
    ...spec,
    sheets: sheets.length
      ? sheets.map((sheet) => ({
          ...sheet,
          name: String(sheet.name ?? ""),
          columns: Array.isArray(sheet.columns) ? sheet.columns : [],
          rows: Array.isArray(sheet.rows) ? sheet.rows : [],
        }))
      : [blankSheet("Sheet", [])],
  } as SheetsSpec;
}

// ------------------------------------------------------------------- keys

const KEYWORDS = new Set(
  (
    "False None True and as assert async await break class continue def del elif else except finally for from " +
    "global if import in is lambda nonlocal not or pass raise return try while with yield"
  ).split(" "),
);

/** A column key from a label: what `_slug` in `sheets.py` makes of it. */
export function slug(value: string, index: number): string {
  let text = String(value ?? "")
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}_]/gu, "_");
  text = text.replace(/_+/g, "_").replace(/^_+|_+$/g, "").slice(0, MAX_KEY_CHARS).replace(/_+$/, "");
  if (!text) return `col${index + 1}`;
  if (/^\p{N}/u.test(text)) text = `_${text}`.slice(0, MAX_KEY_CHARS);
  if (KEYWORDS.has(text)) text += "_";
  return text;
}

/** `key`, or `key_2`, `key_3` … when it is taken (`_unique` in `sheets.py`). */
export function uniqueKey(key: string, used: ReadonlySet<string>): string {
  let candidate = key;
  let count = 1;
  while (used.has(candidate)) {
    count += 1;
    const suffix = `_${count}`;
    candidate = key.slice(0, MAX_KEY_CHARS - suffix.length).replace(/_+$/, "") + suffix;
  }
  return candidate;
}

/** A spreadsheet-style letter name for a column position: A … Z, AA … */
export function columnLetter(index: number): string {
  let n = index + 1;
  let out = "";
  while (n > 0) {
    const rest = (n - 1) % 26;
    out = String.fromCharCode(65 + rest) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

export function blankSheet(name: string, existing: readonly Sheet[]): Sheet {
  // "Sheet 3" after two sheets, or the next number nobody uses yet.
  const taken = new Set(existing.map((sheet) => sheet.name));
  let n = existing.length + 1;
  let label = `${name} ${n}`;
  while (taken.has(label)) label = `${name} ${++n}`;
  return {
    name: clean(label, MAX_NAME_CHARS),
    columns: [
      { key: "a", label: "A" },
      { key: "b", label: "B" },
      { key: "c", label: "C" },
    ],
    rows: [],
    freeze: 1,
  };
}

// ---------------------------------------------------------- reading cells

/** The column's type: the given one, else what its cells are (`_kind` in `sheets.py`). */
export function columnKind(column: SheetColumn, rows: readonly Row[]): ColumnType {
  if (column.formula) return column.type && isNumericType(column.type) ? column.type : "number";
  if (column.type && (COLUMN_TYPES as readonly string[]).includes(column.type)) return column.type;
  let seen = 0;
  let numbers = 0;
  let checks = 0;
  for (const row of rows) {
    if (!(column.key in row)) continue;
    const cell = row[column.key];
    seen += 1;
    if (isNumber(cell)) numbers += 1;
    else if (typeof cell === "boolean") checks += 1;
  }
  if (seen && numbers === seen) return "number";
  if (seen && checks === seen) return "check";
  return "text";
}

function neededDecimals(value: number, cap = 2): number {
  const text = Math.abs(value).toFixed(cap).replace(/0+$/, "");
  return text.length - text.indexOf(".") - 1;
}

const ZERO_DECIMAL = new Set(["JPY", "KRW", "VND", "CLP", "ISK"]);
const CURRENCY_SIGNS: Record<string, string> = { $: "USD", "€": "EUR", "£": "GBP", "¥": "JPY" };

export function currencyCode(unit: string): string {
  return CURRENCY_SIGNS[unit] ?? unit.toUpperCase();
}

/** How many decimals the whole column shows, so its numbers line up (`_decimals`). */
export function columnDecimals(column: SheetColumn, kind: ColumnType, values: readonly number[]): number {
  if (isNumber(column.decimals)) return clamp(Math.trunc(column.decimals), 0, MAX_DECIMALS);
  if (kind === "currency") return ZERO_DECIMAL.has(currencyCode(column.unit ?? "")) ? 0 : 2;
  let most = 0;
  for (const value of values) most = Math.max(most, neededDecimals(value));
  return most;
}

/** What the grid needs to draw one column, computed once per render of the sheet. */
export interface ColumnView {
  column: SheetColumn;
  kind: ColumnType;
  decimals: number;
  numeric: boolean;
  format: (value: number) => string;
}

const formatters = new Map<string, Intl.NumberFormat | null>();

function numberFormat(locale: string | undefined, options: Intl.NumberFormatOptions): Intl.NumberFormat | null {
  const id = `${locale ?? ""}|${JSON.stringify(options)}`;
  if (!formatters.has(id)) {
    try {
      formatters.set(id, new Intl.NumberFormat(locale, options));
    } catch {
      formatters.set(id, null); // an unknown currency code: the plain number with its unit
    }
  }
  return formatters.get(id) ?? null;
}

/** A number as the page script writes it for this column (`make`/`put` in the page). */
export function numberFormatter(
  kind: ColumnType,
  unit: string,
  decimals: number,
  locale: string | undefined,
): (value: number) => string {
  const digits = { minimumFractionDigits: decimals, maximumFractionDigits: decimals };
  if (kind === "currency" && /^[A-Za-z]{3}$/.test(currencyCode(unit))) {
    const own = numberFormat(locale, {
      style: "currency",
      currency: currencyCode(unit),
      currencyDisplay: "narrowSymbol",
      ...digits,
    });
    if (own) return (value) => own.format(value);
  }
  if (kind === "percent") {
    const own = numberFormat(locale, { style: "percent", ...digits });
    if (own) return (value) => own.format(value / 100);
  }
  const plain = numberFormat(locale, digits);
  const suffix = unit && kind !== "percent" ? ` ${unit}` : kind === "percent" ? "%" : "";
  return (value) => (plain ? plain.format(value) : String(value)) + suffix;
}

export function columnViews(columns: readonly SheetColumn[], rows: readonly Row[], locale?: string): ColumnView[] {
  return columns.map((column) => {
    const kind = columnKind(column, rows);
    const numeric = isNumericType(kind);
    const values = numeric ? rows.map((row) => row[column.key]).filter(isNumber) : [];
    const decimals = numeric ? columnDecimals(column, kind, values) : 0;
    return {
      column,
      kind,
      decimals,
      numeric,
      format: numberFormatter(kind, numeric ? column.unit ?? "" : "", decimals, locale),
    };
  });
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?$/;
const dateFormats = new Map<string, Intl.DateTimeFormat>();

/** An ISO date as the locale writes it, or null for any other text. */
export function formatDate(value: string, locale?: string): string | null {
  const match = ISO_DATE.exec(value.trim());
  if (!match) return null;
  const withTime = Boolean(match[4]);
  const date = new Date(+match[1], +match[2] - 1, +match[3], withTime ? +match[4] : 0, withTime ? +match[5] : 0);
  if (Number.isNaN(date.getTime()) || date.getMonth() !== +match[2] - 1) return null;
  const id = `${locale ?? ""}|${withTime}`;
  let format = dateFormats.get(id);
  if (!format) {
    try {
      format = new Intl.DateTimeFormat(locale, withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" });
    } catch {
      format = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
    }
    dateFormats.set(id, format);
  }
  return format.format(date);
}

/** The text any cell stands for (`_text_of` in `sheets.py`). */
export function textOf(value: CellValue | undefined | null): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "object") return String(value.text ?? value.href ?? "");
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

/** What the grid shows in a cell (a check is drawn as a box, so it has no text). */
export function displayText(value: CellValue | undefined, view: ColumnView, locale?: string): string {
  if (value === undefined || value === null || value === "") return "";
  if (typeof value === "boolean") return "";
  if (isNumber(value)) return view.numeric ? view.format(value) : rawNumber(value);
  if (view.kind === "date" && typeof value === "string") return formatDate(value, locale) ?? value;
  if (typeof value === "object" && value.href && (!value.text || value.text === value.href)) {
    return value.href.replace(/^(?:https?:\/\/(?:www\.)?|mailto:)/, "").replace(/\/+$/, "") || value.href;
  }
  return textOf(value);
}

/** A number as plain text a person can type again: no grouping, the locale's decimal mark. */
export function rawNumber(value: number, locale?: string): string {
  const text = Number.isInteger(value) || Math.abs(value) >= 1e21 ? String(value) : String(Number(value.toPrecision(15)));
  return decimalMark(locale) === "," ? text.replace(".", ",") : text;
}

const marks = new Map<string, string>();

/** The locale's decimal mark ("." or ","). */
export function decimalMark(locale?: string): string {
  const id = locale ?? "";
  let mark = marks.get(id);
  if (mark === undefined) {
    try {
      const part = new Intl.NumberFormat(locale).formatToParts(1.5).find((p) => p.type === "decimal");
      mark = part?.value === "," ? "," : ".";
    } catch {
      mark = ".";
    }
    marks.set(id, mark);
  }
  return mark;
}

/** The text an edit of the cell starts from (F2, double-click, Enter). */
export function editText(value: CellValue | undefined, locale?: string): string {
  if (value === undefined || value === null) return "";
  if (isNumber(value)) return rawNumber(value, locale);
  return textOf(value);
}

/** Status words plain enough to carry a tone by themselves (`_STATUS_TONES` in `sheets.py`). */
const STATUS_TONES: Record<string, string> = Object.fromEntries([
  ...["done", "paid", "delivered", "ok", "complete", "completed", "shipped", "approved", "active", "won", "passed", "resolved"].map(
    (word) => [word, "good"],
  ),
  ...["pending", "open", "in progress", "in transit", "in review", "waiting", "planned", "scheduled", "sent", "new", "todo"].map(
    (word) => [word, "info"],
  ),
  ...["at risk", "delayed", "due soon", "on hold", "paused"].map((word) => [word, "warn"]),
  ...["late", "overdue", "blocked", "failed", "rejected", "cancelled", "canceled", "error", "lost", "missing"].map(
    (word) => [word, "bad"],
  ),
]);

/** A status cell's tone: the one it carries, else the word's own, else none (a neutral chip). */
export function statusTone(value: CellValue): string {
  if (typeof value === "object") return value.tone ?? "";
  return STATUS_TONES[String(value).trim().toLowerCase().replace(/[.!]+$/, "")] ?? "";
}

// ------------------------------------------------------------ typing cells

const TRUE_WORDS = new Set(["true", "yes", "y", "x", "1", "on", "done", "✓", "✔"]);
const FALSE_WORDS = new Set(["false", "no", "n", "0", "off", "-", "–"]);

/**
 * A number from what a person typed or pasted, or null.
 *
 * The locale's decimal mark decides an ambiguous "1.234" (a thousand where a
 * comma marks decimals); currency signs, codes, spaces, a percent sign and
 * the column's unit around the number are ignored, a leading minus may be the
 * typographic one, and "(12)" is a negative number as accounting writes it.
 */
export function parseNumber(input: string, locale?: string, unit = ""): number | null {
  let text = input.trim();
  if (!text) return null;
  if (unit) text = text.split(unit).join(" ");
  text = text.replace(/[\s\u00a0\u202f']/g, "").replace(/^[\u2212\u2013]/, "-");
  let negative = false;
  if (/^\(.*\)$/.test(text)) {
    negative = true;
    text = text.slice(1, -1);
  }
  const takeSign = () => {
    if (/^[+-]/.test(text)) {
      if (text[0] === "-") negative = !negative;
      text = text.slice(1);
      return true;
    }
    return false;
  };
  const signed = takeSign();
  text = text.replace(/^(?:[$€£¥]|[A-Z]{3})/, "").replace(/(?:[$€£¥%]|[A-Z]{3})$/, "");
  if (!signed) takeSign(); // "€-5" as well as "-€5"
  if (/^\d*\.?\d+e[+-]?\d+$/i.test(text)) {
    const scientific = Number(text);
    return Number.isFinite(scientific) ? (negative ? -scientific : scientific) : null;
  }
  if (!/^(\d|[.,]\d)/.test(text)) return null;
  const comma = decimalMark(locale) === ",";
  const decimal = comma ? "," : ".";
  const group = comma ? "." : ",";
  const grouped = new RegExp(`^\\d{1,3}(\\${group}\\d{3})+$`);
  let body = text;
  // Grouping marks only where they group thousands; the other mark is the decimal.
  if (body.includes(group) && body.includes(decimal)) {
    const at = body.lastIndexOf(decimal);
    const whole = body.slice(0, at);
    if (at < body.lastIndexOf(group) || !grouped.test(whole)) return null;
    body = `${whole.split(group).join("")}.${body.slice(at + 1)}`;
  } else if (body.includes(group)) {
    if (grouped.test(body)) body = body.split(group).join("");
    else if (body.split(group).length === 2) body = body.replace(group, ".");
    else return null;
  } else if (comma) {
    body = body.replace(",", ".");
  }
  if (!/^(\d+\.?\d*|\.\d+)$/.test(body)) return null;
  const value = Number(body);
  if (!Number.isFinite(value)) return null;
  return negative ? -value : value;
}

/** The locale's numeric date order, e.g. ["day","month","year"]. */
function dateOrder(locale?: string): string[] {
  try {
    return new Intl.DateTimeFormat(locale, { year: "numeric", month: "2-digit", day: "2-digit" })
      .formatToParts(new Date(2026, 10, 23))
      .filter((part) => part.type === "day" || part.type === "month" || part.type === "year")
      .map((part) => part.type);
  } catch {
    return ["year", "month", "day"];
  }
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/**
 * An ISO date from what a person typed: ISO itself, or the locale's numeric
 * order ("31.03.2026", "3/31/2026"), with an optional "HH:MM". Null otherwise.
 */
export function parseDate(input: string, locale?: string): string | null {
  const text = input.trim();
  const iso = ISO_DATE.exec(text);
  if (iso) return formatDate(text, "en") ? (iso[4] ? `${iso[1]}-${iso[2]}-${iso[3]}T${iso[4]}:${iso[5]}` : text) : null;
  const match = /^(\d{1,4})[./-](\d{1,2})[./-](\d{1,4})\.?(?:[ ,T]+(\d{1,2}):(\d{2}))?$/.exec(text);
  if (!match) return null;
  const order = dateOrder(locale);
  const parts: Record<string, number> = {};
  order.forEach((name, index) => {
    parts[name] = Number(match[index + 1]);
  });
  let year = parts.year;
  if (year < 100) year += 2000;
  const month = parts.month;
  const day = parts.day;
  const date = new Date(year, month - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return null;
  const head = `${year}-${pad(month)}-${pad(day)}`;
  if (match[4] === undefined) return head;
  const hours = Number(match[4]);
  const minutes = Number(match[5]);
  if (hours > 23 || minutes > 59) return null;
  return `${head}T${pad(hours)}:${pad(minutes)}`;
}

function safeLink(text: string): string {
  const href = text.trim();
  return /^(https?:\/\/|mailto:)/i.test(href) && href.length <= 2_000 && !/\s/.test(href) ? href : "";
}

/**
 * What a typed or pasted text becomes in a column, or null for an empty cell.
 *
 * The result is what `_cell` in `sheets.py` would keep for it, so the saved
 * spec reads back exactly as typed. `previous` keeps a link's address and a
 * status chip's tone when only the text of one is changed.
 */
export function parseInput(
  input: string,
  view: Pick<ColumnView, "kind"> & { column: Pick<SheetColumn, "type" | "unit"> },
  locale?: string,
  previous?: CellValue,
): CellValue | null {
  const kind = view.kind;
  const text = clean(input, MAX_CELL_CHARS);
  if (!text) return null;
  if (isNumericType(kind)) {
    const value = parseNumber(text, locale, view.column.unit ?? "");
    return value ?? text;
  }
  if (kind === "check") {
    const word = text.toLowerCase();
    return TRUE_WORDS.has(word) ? true : FALSE_WORDS.has(word) ? false : null;
  }
  if (kind === "date") return parseDate(text, locale) ?? clean(text, MAX_DATE_CHARS);
  if (kind === "status") {
    const word = clean(text, MAX_STATUS_CHARS);
    if (previous && typeof previous === "object" && previous.tone) return { text: word, tone: previous.tone };
    return word;
  }
  if (kind === "link") {
    const href = safeLink(text);
    if (href) return { text: href, href };
    if (previous && typeof previous === "object" && previous.href) return { text, href: previous.href };
    return text;
  }
  // A column without a strict type keeps numbers as numbers, so an inferred
  // number column stays one when a number is typed into it.
  if (!view.column.type) {
    const value = parseNumber(text, locale);
    if (value !== null && /^[\s+\-−–(]*[\d.,]/.test(text)) return value;
  }
  return text;
}

/** A cell carried into a column of another type: what `parseInput` makes of its text. */
export function convertCell(value: CellValue, kind: ColumnType, unit: string, locale?: string): CellValue | null {
  if (isNumericType(kind) && isNumber(value)) return value;
  if (kind === "check" && typeof value === "boolean") return value;
  if (kind === "check" && isNumber(value)) return value !== 0;
  if ((kind === "status" || kind === "link") && typeof value === "object") return value;
  const text = isNumber(value) ? rawNumber(value, locale) : textOf(value);
  return parseInput(text, { kind, column: { type: kind, unit } }, locale);
}
