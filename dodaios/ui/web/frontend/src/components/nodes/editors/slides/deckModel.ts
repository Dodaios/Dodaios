/**
 * The deck as the slides editor holds it, and every structural change to it.
 *
 * The shape mirrors what `dodaios/nodes/kinds/slides.py::normalize` keeps: a
 * theme, an optional accent and a list of slides, each a layout name plus
 * that layout's fields. The limits below are the same numbers the server
 * clips to, so what the person types here is what the page will show; the
 * server stays the judge (its `normalize` runs on every save).
 *
 * Everything here is a pure function over plain JSON. Changes are written as
 * mutations of a draft (`apply` in `useNodeSpecEditor` runs them through
 * `produce`), so untouched slides keep their identity and the thumbnails of
 * those slides do not render again.
 */

export const LAYOUTS = [
  "title",
  "section",
  "bullets",
  "columns",
  "quote",
  "stats",
  "chart",
  "table",
  "image",
  "steps",
  "closing",
] as const;
export type Layout = (typeof LAYOUTS)[number];

export const THEMES = ["auto", "light", "dark"] as const;
export type DeckTheme = (typeof THEMES)[number];

/** Limits, as in `slides.py`. */
export const LIMITS = {
  slides: 60,
  bullets: 6,
  bulletChars: 160,
  columnsMin: 2,
  columns: 3,
  columnBullets: 4,
  columnBulletChars: 80,
  columnTitleChars: 60,
  columnTextChars: 200,
  closingBullets: 4,
  closingBulletChars: 100,
  stats: 4,
  statValueChars: 12,
  statLabelChars: 48,
  statDetailChars: 80,
  steps: 6,
  stepTitleChars: 48,
  stepTextChars: 140,
  tableColumns: 8,
  tableRows: 10,
  tableHeadChars: 32,
  cellChars: 60,
  noteChars: 1_200,
  imageChars: 400_000,
} as const;

/** The one-line texts of a slide and how long each may be (`_LINES`). */
export const LINE_LIMITS = {
  kicker: 60,
  title: 110,
  subtitle: 180,
  text: 280,
  quote: 320,
  by: 80,
  caption: 140,
} as const;
export type LineField = keyof typeof LINE_LIMITS;

export interface Column {
  title?: string;
  text?: string;
  bullets?: string[];
}
export interface Stat {
  value: string;
  label?: string;
  detail?: string;
}
export interface Step {
  title?: string;
  text?: string;
}
export interface Table {
  columns: string[];
  rows: string[][];
}
/** A chart in the report chart grammar (`report_blocks.parse_chart`). */
export type DeckChart = Record<string, unknown> & {
  type?: string;
  x?: string[];
  series?: { name?: string; data: (number | null)[] }[];
};

export interface Slide {
  layout: Layout;
  kicker?: string;
  title?: string;
  subtitle?: string;
  text?: string;
  quote?: string;
  by?: string;
  caption?: string;
  bullets?: string[];
  columns?: Column[];
  stats?: Stat[];
  chart?: DeckChart;
  table?: Table;
  image?: string;
  /** How an image slide fills its box; absent means "cover". */
  fit?: "contain";
  steps?: Step[];
  notes?: string;
}

export interface Deck {
  theme: DeckTheme;
  accent?: string;
  slides: Slide[];
}

/** What each layout shows (`_FIELDS`); every other field is dropped by the server. */
export const LAYOUT_FIELDS: Record<Layout, readonly (keyof Slide)[]> = {
  title: ["kicker", "title", "subtitle"],
  section: ["kicker", "title", "subtitle"],
  bullets: ["kicker", "title", "text", "bullets"],
  columns: ["kicker", "title", "columns"],
  quote: ["quote", "by"],
  stats: ["kicker", "title", "stats"],
  chart: ["kicker", "title", "text", "chart"],
  table: ["kicker", "title", "table", "caption"],
  image: ["kicker", "title", "image", "caption", "fit"],
  steps: ["kicker", "title", "steps"],
  closing: ["kicker", "title", "subtitle", "bullets"],
};

export function isLayout(value: unknown): value is Layout {
  return typeof value === "string" && (LAYOUTS as readonly string[]).includes(value);
}

/** The named accents a deck may take (`shell.NAMED_COLORS`, the series tokens). */
export const NAMED_ACCENTS: Record<string, string> = {
  blue: "var(--s1)",
  orange: "var(--s2)",
  green: "var(--s3)",
  amber: "var(--s4)",
  yellow: "var(--s4)",
  violet: "var(--s5)",
  purple: "var(--s5)",
  pink: "var(--s6)",
  accent: "var(--accent)",
  ink: "var(--ink)",
  muted: "var(--ink-2)",
  good: "var(--good)",
  warn: "var(--warn)",
  bad: "var(--bad)",
};
/** The swatches offered in the toolbar, in this order. */
export const ACCENT_SWATCHES = ["blue", "orange", "green", "amber", "violet", "pink"] as const;

const COLOR_RE = /^(?:#[0-9a-fA-F]{3,8}|(?:rgb|rgba|hsl|hsla)\([0-9a-zA-Z.,%/\s-]{1,60}\))$/;

/** The CSS color an accent stands for (`shell.color`), or "" for the deck's default. */
export function accentColor(accent: string | undefined): string {
  const text = (accent ?? "").trim();
  if (!text) return "";
  const named = NAMED_ACCENTS[text.toLowerCase()];
  if (named) return named;
  return COLOR_RE.test(text) ? text : "";
}

// --- reading a spec ----------------------------------------------------------

function str(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return "";
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(str).filter(Boolean) : [];
}

function objects(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === "object" && !Array.isArray(item))
    : [];
}

/** Copy only the non-empty string fields named in `keys`. */
function pickTexts<T extends object>(raw: Record<string, unknown>, keys: readonly string[]): T {
  const out: Record<string, string> = {};
  for (const key of keys) {
    const value = str(raw[key]);
    if (value) out[key] = value;
  }
  return out as T;
}

/**
 * The deck the editor starts from. The stage hands over the spec the server
 * stored (already normalized); this only makes sure the editor never meets a
 * shape it cannot draw, whatever an old or hand-written spec holds.
 */
export function readDeck(spec: unknown): Deck {
  const raw = spec && typeof spec === "object" && !Array.isArray(spec) ? (spec as Record<string, unknown>) : {};
  const theme = (THEMES as readonly string[]).includes(String(raw.theme)) ? (raw.theme as DeckTheme) : "auto";
  const slides: Slide[] = [];
  for (const item of objects(raw.slides)) {
    if (!isLayout(item.layout)) continue;
    const slide: Slide = {
      layout: item.layout,
      ...pickTexts<Partial<Slide>>(item, ["kicker", "title", "subtitle", "text", "quote", "by", "caption", "notes", "image"]),
    };
    const bullets = strings(item.bullets);
    if (bullets.length) slide.bullets = bullets;
    const columns = objects(item.columns).map((col) => {
      const column: Column = pickTexts<Column>(col, ["title", "text"]);
      const inner = strings(col.bullets);
      if (inner.length) column.bullets = inner;
      return column;
    });
    if (columns.length) slide.columns = columns;
    const stats = objects(item.stats).map((stat) => ({ value: "", ...pickTexts<Partial<Stat>>(stat, ["value", "label", "detail"]) }));
    if (stats.length) slide.stats = stats;
    const steps = objects(item.steps).map((step) => pickTexts<Step>(step, ["title", "text"]));
    if (steps.length) slide.steps = steps;
    if (item.table && typeof item.table === "object") {
      const table = item.table as Record<string, unknown>;
      const cols = Array.isArray(table.columns) ? table.columns.map(str) : [];
      const rows = Array.isArray(table.rows)
        ? table.rows.filter(Array.isArray).map((row) => cols.map((_, index) => str((row as unknown[])[index])))
        : [];
      if (cols.length) slide.table = { columns: cols, rows };
    }
    if (item.chart && typeof item.chart === "object" && !Array.isArray(item.chart)) {
      slide.chart = item.chart as DeckChart;
    }
    if (item.fit === "contain") slide.fit = "contain";
    slides.push(slide);
  }
  const deck: Deck = { theme, slides };
  if (typeof raw.accent === "string" && raw.accent) deck.accent = raw.accent;
  return deck;
}

// --- the person's sample content ----------------------------------------------

/** Translates a key; the editor passes its `t`. */
export type Translate = (key: string, vars?: Record<string, string | number>) => string;

const K = "nodes.editor.slides.sample.";

/** A small chart that reads as a placeholder: three months of one series. */
export function sampleChart(t: Translate): DeckChart {
  return {
    type: "column",
    x: [t(`${K}chart_x1`), t(`${K}chart_x2`), t(`${K}chart_x3`)],
    series: [{ name: t(`${K}chart_series`), data: [12, 18, 24] }],
  };
}

export function sampleTable(t: Translate): Table {
  return {
    columns: [t(`${K}table_col1`), t(`${K}table_col2`)],
    rows: [
      [t(`${K}table_row1`), "1"],
      [t(`${K}table_row2`), "2"],
    ],
  };
}

/**
 * A new slide of `layout`, filled with short sample texts in the person's
 * language. Why samples and not empty placeholders: the server drops empty
 * fields and a slide without its layout's main field changes layout, so an
 * empty new slide would not survive its first save. The editor selects the
 * sample title of a new slide, so typing replaces it at once.
 */
export function blankSlide(layout: Layout, t: Translate): Slide {
  const title = t(`${K}title`);
  switch (layout) {
    case "title":
      return { layout, title: t(`${K}deck_title`), subtitle: t(`${K}subtitle`) };
    case "section":
      return { layout, title: t(`${K}section_title`) };
    case "bullets":
      return { layout, title, bullets: [t(`${K}point`, { n: 1 }), t(`${K}point`, { n: 2 }), t(`${K}point`, { n: 3 })] };
    case "columns":
      return {
        layout,
        title,
        columns: [
          { title: t(`${K}column`, { n: 1 }), text: t(`${K}column_text`) },
          { title: t(`${K}column`, { n: 2 }), text: t(`${K}column_text`) },
        ],
      };
    case "quote":
      return { layout, quote: t(`${K}quote`), by: t(`${K}by`) };
    case "stats":
      return {
        layout,
        title,
        stats: [
          { value: "42%", label: t(`${K}stat_label`, { n: 1 }) },
          { value: "3.5k", label: t(`${K}stat_label`, { n: 2 }) },
        ],
      };
    case "chart":
      return { layout, title, chart: sampleChart(t) };
    case "table":
      return { layout, title, table: sampleTable(t) };
    case "image":
      return { layout, title };
    case "steps":
      return {
        layout,
        title,
        steps: [
          { title: t(`${K}step`, { n: 1 }) },
          { title: t(`${K}step`, { n: 2 }) },
          { title: t(`${K}step`, { n: 3 }) },
        ],
      };
    case "closing":
      return { layout, title: t(`${K}closing_title`), subtitle: t(`${K}closing_subtitle`) };
  }
}

/** A sample item for a list field of a slide (a new point, a new step…). */
export function sampleItem(kind: "bullet" | "stat" | "step" | "column", n: number, t: Translate): string | Stat | Step | Column {
  switch (kind) {
    case "bullet":
      return t(`${K}point`, { n });
    case "stat":
      return { value: "0", label: t(`${K}stat_label`, { n }) };
    case "step":
      return { title: t(`${K}step`, { n }) };
    case "column":
      return { title: t(`${K}column`, { n }), text: t(`${K}column_text`) };
  }
}

// --- clipping ----------------------------------------------------------------

/** A text cut to `limit` characters the way the server cuts it (an ellipsis at the end). */
export function clip(text: string, limit: number): string {
  if (text.length <= limit) return text;
  return `${text.slice(0, limit - 1).trimEnd()}…`;
}

// --- switching a slide's layout --------------------------------------------------

/** One unit of a slide's list content, whatever list it came from. */
interface Item {
  title?: string;
  text?: string;
  value?: string;
  bullets?: string[];
}

function itemsOf(slide: Slide): Item[] {
  if (slide.columns?.length) return slide.columns.map((c) => ({ title: c.title, text: c.text, bullets: c.bullets }));
  if (slide.steps?.length) return slide.steps.map((s) => ({ title: s.title, text: s.text }));
  if (slide.stats?.length) return slide.stats.map((s) => ({ title: s.label, text: s.detail, value: s.value }));
  if (slide.bullets?.length) return slide.bullets.map((b) => ({ title: b }));
  return [];
}

function itemLine(item: Item): string {
  return item.title || item.text || item.value || item.bullets?.[0] || "";
}

const NUMBER_RE = /[+\-−]?[$€£¥]?\d[\d.,]*\s?(?:%|[kKmMbB]n?|[$€£¥])?/;

/** A number-like piece of a text ("18%" from "Revenue grew 18%"), for a stat's value. */
function numberIn(text: string): string {
  const found = NUMBER_RE.exec(text);
  return found ? found[0].trim().slice(0, LIMITS.statValueChars) : "";
}

/** A number from a cell or stat value, read leniently ("€4.2M" → 4.2, "1,200" → 1200). */
export function readAmount(text: string): number | null {
  const found = /[+\-−]?\d[\d.,]*/.exec(text.replace(/\s/g, ""));
  if (!found) return null;
  let digits = found[0].replace("−", "-");
  const marks = digits.replace(/[^.,]/g, "");
  if (marks.length > 1 && new Set(marks).size === 1) digits = digits.replace(/[.,]/g, "");
  else if (new Set(marks).size === 2) {
    const point = digits.lastIndexOf(".") > digits.lastIndexOf(",") ? "." : ",";
    digits = digits.replace(point === "." ? /,/g : /\./g, "").replace(",", ".");
  } else if (marks === "," || marks === ".") {
    // One mark followed by exactly three digits groups thousands ("1.200").
    digits = /[.,]\d{3}$/.test(digits) ? digits.replace(/[.,]/, "") : digits.replace(",", ".");
  }
  const value = Number(digits);
  return Number.isFinite(value) ? value : null;
}

function chartFromTable(table: Table | undefined): DeckChart | undefined {
  if (!table || table.rows.length < 2 || table.columns.length < 2) return undefined;
  const series: { name: string; data: (number | null)[] }[] = [];
  for (let col = 1; col < table.columns.length && series.length < 6; col++) {
    const data = table.rows.map((row) => readAmount(row[col] ?? ""));
    if (data.every((value) => value !== null)) series.push({ name: table.columns[col] || `#${col}`, data });
  }
  if (!series.length) return undefined;
  return { type: "column", x: table.rows.map((row, i) => clip(row[0] || `${i + 1}`, 40)), series };
}

function chartFromStats(stats: Stat[] | undefined): DeckChart | undefined {
  if (!stats || stats.length < 2) return undefined;
  const data = stats.map((s) => readAmount(s.value));
  if (data.some((value) => value === null)) return undefined;
  return { type: "column", x: stats.map((s, i) => clip(s.label || s.value || `${i + 1}`, 40)), series: [{ data }] };
}

function tableFromChart(chart: DeckChart | undefined): Table | undefined {
  const x = chart?.x;
  const series = chart?.series;
  if (!Array.isArray(x) || !Array.isArray(series) || !series.length) return undefined;
  const columns = ["", ...series.map((s, i) => s.name || `#${i + 1}`)].slice(0, LIMITS.tableColumns);
  const rows = x.slice(0, LIMITS.tableRows).map((label, i) => [
    String(label),
    ...series.slice(0, LIMITS.tableColumns - 1).map((s) => (s.data[i] == null ? "" : String(s.data[i]))),
  ]);
  return { columns, rows };
}

function tableFromItems(items: Item[], t: Translate): Table | undefined {
  if (items.length < 1) return undefined;
  const withValue = items.some((item) => item.value);
  const columns = withValue
    ? [t(`${K}table_col1`), t(`${K}table_value`)]
    : [t(`${K}table_col1`), t(`${K}table_col2`)];
  const rows = items
    .slice(0, LIMITS.tableRows)
    .map((item) => [clip(item.title || item.value || "", LIMITS.cellChars), clip((withValue ? item.value : item.text) || "", LIMITS.cellChars)]);
  return { columns, rows };
}

/**
 * `slide` in `layout`, carrying over what the new layout can show.
 *
 * Shared fields (kicker, title, notes) stay. List content moves between the
 * list layouts (points, steps, columns, figures), a short text moves between
 * subtitle, text and quote, and the structured fields convert where it reads
 * naturally (a table or a set of figures becomes a chart, a chart becomes a
 * table). What the new layout cannot show is dropped; the switch is one undo
 * step, so nothing is lost for good. A layout whose main field cannot be
 * made from the content gets the same sample a new slide would.
 */
export function switchLayout(slide: Slide, layout: Layout, t: Translate): Slide {
  if (slide.layout === layout) return slide;
  const items = itemsOf(slide);
  const lede = slide.subtitle || slide.text || "";
  const next: Slide = { layout };
  if (slide.kicker && LAYOUT_FIELDS[layout].includes("kicker")) next.kicker = slide.kicker;
  if (slide.title && LAYOUT_FIELDS[layout].includes("title")) next.title = slide.title;
  const sample = blankSlide(layout, t);
  switch (layout) {
    case "title":
    case "section":
      if (!next.title) next.title = slide.quote ? clip(slide.quote, LINE_LIMITS.title) : sample.title;
      if (lede) next.subtitle = clip(lede, LINE_LIMITS.subtitle);
      break;
    case "closing": {
      if (!next.title) next.title = sample.title;
      if (lede) next.subtitle = clip(lede, LINE_LIMITS.subtitle);
      const points = items.map(itemLine).filter(Boolean).slice(0, LIMITS.closingBullets);
      if (points.length) next.bullets = points.map((p) => clip(p, LIMITS.closingBulletChars));
      break;
    }
    case "bullets": {
      const points = items.flatMap((item) => (item.bullets?.length && !item.title ? item.bullets : [itemLine(item)]));
      const kept = points.filter(Boolean).slice(0, LIMITS.bullets).map((p) => clip(p, LIMITS.bulletChars));
      if (kept.length) next.bullets = kept;
      if (lede) next.text = clip(lede, LINE_LIMITS.text);
      if (!kept.length && !lede) next.bullets = sample.bullets;
      if (!next.title && !next.bullets && !next.text) next.title = sample.title;
      break;
    }
    case "columns": {
      let columns: Column[];
      if (slide.columns?.length) columns = slide.columns;
      else if (items.length >= 2 && items.length <= LIMITS.columns) {
        columns = items.map((item) => {
          const column: Column = {};
          const head = item.title || item.value;
          if (head) column.title = clip(head, LIMITS.columnTitleChars);
          if (item.text) column.text = clip(item.text, LIMITS.columnTextChars);
          return column;
        });
      } else if (items.length > LIMITS.columns) {
        // Many points: share them out over two columns of points.
        const lines = items.map(itemLine).filter(Boolean).map((line) => clip(line, LIMITS.columnBulletChars));
        const half = Math.ceil(lines.length / 2);
        columns = [lines.slice(0, half), lines.slice(half)].map((part) => ({ bullets: part.slice(0, LIMITS.columnBullets) }));
      } else {
        columns = sample.columns ?? [];
        if (items.length === 1) columns = [{ ...columns[0], title: clip(itemLine(items[0]), LIMITS.columnTitleChars) }, columns[1]];
      }
      next.columns = columns;
      break;
    }
    case "quote":
      next.quote = clip(slide.quote || lede || itemLine(items[0] ?? {}) || slide.title || sample.quote || "", LINE_LIMITS.quote);
      if (slide.by) next.by = slide.by;
      break;
    case "stats": {
      const stats = items.slice(0, LIMITS.stats).map((item) => {
        const value = item.value || numberIn(itemLine(item)) || "0";
        const stat: Stat = { value: clip(value, LIMITS.statValueChars) };
        const label = item.value ? item.title : itemLine(item);
        if (label) stat.label = clip(label, LIMITS.statLabelChars);
        if (item.value && item.text) stat.detail = clip(item.text, LIMITS.statDetailChars);
        return stat;
      });
      next.stats = stats.length ? stats : sample.stats;
      break;
    }
    case "chart":
      next.chart = slide.chart ?? chartFromTable(slide.table) ?? chartFromStats(slide.stats) ?? sampleChart(t);
      if (slide.text || slide.subtitle) next.text = clip(slide.text || slide.subtitle || "", LINE_LIMITS.text);
      break;
    case "table":
      next.table = slide.table ?? tableFromChart(slide.chart) ?? tableFromItems(items, t) ?? sampleTable(t);
      if (slide.caption) next.caption = slide.caption;
      break;
    case "image":
      if (slide.image) next.image = slide.image;
      if (slide.fit) next.fit = slide.fit;
      if (slide.caption || slide.text) next.caption = clip(slide.caption || slide.text || "", LINE_LIMITS.caption);
      break;
    case "steps": {
      const steps = items.slice(0, LIMITS.steps).map((item) => {
        const step: Step = {};
        const head = item.title || item.value;
        if (head) step.title = clip(head, LIMITS.stepTitleChars);
        if (item.text) step.text = clip(item.text, LIMITS.stepTextChars);
        return step;
      });
      next.steps = steps.length ? steps : sample.steps;
      break;
    }
  }
  if (slide.notes) next.notes = slide.notes;
  return next;
}

// --- structural changes (on a draft) ------------------------------------------------

/** Move the slide at `from` to `to` (indices in the deck before the move). */
export function moveSlide(deck: Deck, from: number, to: number): void {
  const count = deck.slides.length;
  if (from < 0 || from >= count) return;
  const target = Math.max(0, Math.min(count - 1, to));
  if (target === from) return;
  const [slide] = deck.slides.splice(from, 1);
  deck.slides.splice(target, 0, slide);
}

/** A deep copy of a slide (plain JSON), for duplicating. */
export function copySlide(slide: Slide): Slide {
  return JSON.parse(JSON.stringify(slide)) as Slide;
}

/** Whether another slide fits the deck. */
export function canAddSlide(deck: Deck): boolean {
  return deck.slides.length < LIMITS.slides;
}

/** The position an index lands on after a move (for following the selection). */
export function indexAfterMove(index: number, from: number, to: number): number {
  if (index === from) return to;
  if (from < index && to >= index) return index - 1;
  if (from > index && to <= index) return index + 1;
  return index;
}

/** A short name for a slide, for the strip and for screen readers. */
export function slideName(slide: Slide): string {
  return (slide.title || slide.quote || slide.caption || slide.kicker || "").replace(/\s+/g, " ").trim().slice(0, 80);
}
