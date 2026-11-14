/**
 * A slide drawn as the deck page draws it: the same elements, classes and
 * size steps as `dodaios/nodes/kinds/slides.py` (`_title_slide` …
 * `_closing_slide` and the `<section>` around them), so with the page's
 * stylesheet it looks exactly like the page. A test compares this markup
 * with the server's for one slide of every layout (`SlideView.test.tsx` and
 * `slides_markup.json`); change both sides together.
 *
 * Drawn inside an editing context, every text the slide shows becomes a
 * field the person writes into directly; elsewhere (thumbnails, the
 * presenter) the slide is plain markup.
 */
import {
  createContext,
  createElement,
  memo,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  type CSSProperties,
  type ClipboardEvent as ReactClipboardEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import type { Slide } from "./deckModel";
import { clean, esc, inlineHtml } from "./inline";

/** A place inside a slide: `["bullets", 2]`, `["stats", 0, "value"]`. */
export type FieldPath = readonly (string | number)[];

export function pathKey(path: FieldPath): string {
  return path.join("/");
}

/** What the editing canvas hands its fields. */
export interface SlideEditing {
  /** The person typed: the field at `path` now holds `value`. */
  setText: (path: FieldPath, value: string) => void;
  /** Enter in a list item: a new item after it (returns false when the list is full). */
  splitItem: (path: FieldPath) => void;
  /** Backspace in an empty list item: the item goes, focus moves to the one before. */
  removeItem: (path: FieldPath) => void;
  undo: () => void;
  redo: () => void;
  /** Focus moved to another field: its typing is a new undo step. */
  breakRun: () => void;
  /** A field to focus after the next render (a new point, a new slide's title). */
  focusRequest: { key: string; select: "all" | "end" } | null;
  clearFocusRequest: () => void;
  /** The faint prompt an empty field shows ("Title", "Subtitle"). */
  placeholder: (field: string) => string;
  /** The field the person is in, for the inspector. */
  onFieldFocus?: (path: FieldPath | null) => void;
}

const EditingContext = createContext<SlideEditing | null>(null);
export const SlideEditingProvider = EditingContext.Provider;

/** The limit of each field, by its last path part (the server clips to these). */
const FIELD_LIMITS: Record<string, number> = {
  kicker: 60,
  title: 110,
  subtitle: 180,
  text: 280,
  quote: 320,
  by: 80,
  caption: 140,
  value: 12,
  label: 48,
  detail: 80,
};

function limitOf(path: FieldPath): number {
  const head = path[0];
  const last = path[path.length - 1];
  if (head === "bullets" && typeof last === "number") return 160;
  if (head === "columns") {
    if (path.includes("bullets")) return 80;
    return last === "title" ? 60 : 200;
  }
  if (head === "steps") return last === "title" ? 48 : 140;
  if (head === "table") return path[1] === "columns" ? 32 : 60;
  return FIELD_LIMITS[String(last)] ?? 280;
}

/** Python's `len()`: code points, not UTF-16 units. */
function len(text: string | undefined): number {
  return text ? Array.from(text).length : 0;
}

/** 1 for a text up to `bounds[0]` characters, 2 up to the next, and so on (`_step`). */
export function sizeStep(length: number, bounds: readonly number[]): number {
  return 1 + bounds.filter((bound) => length > bound).length;
}

/** The size step at which points fit their column (`_list_fit`). */
export function listFit(bullets: readonly string[], width: number): number {
  const sizes = [34, 28, 24, 21, 18];
  for (let step = 0; step < sizes.length; step++) {
    const size = sizes[step];
    const perLine = width / (0.5 * size);
    const rows = bullets.reduce((sum, bullet) => sum + Math.max(1, Math.ceil(len(bullet) / perLine)), 0);
    if (rows * 1.3 * size + bullets.length * 1.28 * size <= 540) return step + 1;
  }
  return sizes.length;
}

const NUMERIC_CELL_RE = /^[+\-−–]?\s?[$€£¥]?\s?\d[\d.,\s]*\s?(?:[%‰]|[A-Za-z€$£¥°/²³µ]{1,5})?$/;

/** Python's `f"{x:.2f}"` (round half to even differs from toFixed only on exact halves, never here). */
function fixed2(value: number): string {
  return value.toFixed(2);
}

// --- fields ---------------------------------------------------------------------

interface FieldProps {
  tag: string;
  value: string;
  path: FieldPath;
  className?: string;
  rich?: boolean;
  /** Attributes the page sets on this element (`data-len`). */
  attrs?: Record<string, string>;
  /** An empty field still drawn, showing this prompt (editing only). */
  placeholder?: string;
}

function placeCaret(el: HTMLElement, select: "all" | "end"): void {
  const selection = el.ownerDocument.defaultView?.getSelection();
  if (!selection) return;
  const range = el.ownerDocument.createRange();
  range.selectNodeContents(el);
  if (select === "end") range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}

function isAtStart(el: HTMLElement): boolean {
  const selection = el.ownerDocument.defaultView?.getSelection();
  if (!selection || selection.rangeCount === 0) return false;
  const range = selection.getRangeAt(0);
  if (!range.collapsed) return false;
  const before = el.ownerDocument.createRange();
  before.selectNodeContents(el);
  before.setEnd(range.startContainer, range.startOffset);
  return before.toString().length === 0;
}

/**
 * A text of the slide the person writes into. React draws the element but
 * never its content: the content is set here, so typing is never undone by
 * a render. While the field has focus it shows its source (`**bold**`
 * stays visible as typed, as the page's own edit mode does); when it loses
 * focus, the drawn marks come back.
 */
function EditableField({ tag, value, path, className, rich, attrs, placeholder, editing }: FieldProps & { editing: SlideEditing }) {
  const ref = useRef<HTMLElement | null>(null);
  const focused = useRef(false);
  const key = pathKey(path);
  const html = rich ? inlineHtml(value) : esc(value);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (focused.current) {
      // An undo while writing here: show the restored text.
      if ((el.textContent ?? "") !== value) {
        el.textContent = value;
        placeCaret(el, "end");
      }
    } else if (el.innerHTML !== html) {
      el.innerHTML = html;
    }
  }, [value, html]);

  const request = editing.focusRequest;
  useEffect(() => {
    const el = ref.current;
    if (!el || !request || request.key !== key) return;
    el.focus();
    placeCaret(el, request.select);
    editing.clearFocusRequest();
  }, [request, key, editing]);

  const isItem = typeof path[path.length - 1] === "number" && (path.includes("bullets") || path[0] === "bullets");
  const limit = limitOf(path);

  const onInput = () => {
    const el = ref.current;
    if (!el) return;
    let text = (el.textContent ?? "").replace(/[\r\n]+/g, " ");
    if (len(text) > limit) {
      text = Array.from(text).slice(0, limit).join("");
      el.textContent = text;
      placeCaret(el, "end");
    }
    // A field emptied by the browser can keep a stray <br>; then :empty shows the prompt.
    if (text === "" && el.innerHTML !== "") el.innerHTML = "";
    editing.setText(path, text);
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    const el = ref.current;
    if (!el) return;
    const mod = event.metaKey || event.ctrlKey;
    const lower = event.key.toLowerCase();
    if (mod && !event.altKey && (lower === "z" || (lower === "y" && !event.shiftKey))) {
      // Text and structure share one history: the editor's undo, not the browser's.
      event.preventDefault();
      event.stopPropagation();
      if (lower === "z" && !event.shiftKey) editing.undo();
      else editing.redo();
      return;
    }
    if (mod && ["b", "i", "u"].includes(lower)) {
      // No rich formatting commands: the browser would put tags in the field.
      event.preventDefault();
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (isItem && !event.shiftKey) editing.splitItem(path);
      else el.blur();
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      el.blur();
      return;
    }
    if (event.key === "Backspace" && isItem && (el.textContent ?? "") === "" && isAtStart(el)) {
      event.preventDefault();
      editing.removeItem(path);
    }
    // Keys typed here are the field's: the strip and the shortcuts must not see them.
    event.stopPropagation();
  };

  const onPaste = (event: ReactClipboardEvent<HTMLElement>) => {
    // Plain text only, on one line: a slide's fields hold no markup.
    event.preventDefault();
    const text = event.clipboardData.getData("text/plain").replace(/[\r\n]+/g, " ");
    const doc = ref.current?.ownerDocument;
    if (doc && text) doc.execCommand("insertText", false, text);
  };

  return createElement(tag, {
    ref,
    className: className || undefined,
    ...attrs,
    contentEditable: "plaintext-only",
    suppressContentEditableWarning: true,
    spellCheck: true,
    role: "textbox",
    "aria-label": placeholder || editing.placeholder(String(typeof path[path.length - 1] === "number" ? path[0] : path[path.length - 1])),
    "data-field": key,
    "data-placeholder": placeholder || undefined,
    onInput,
    onKeyDown,
    onPaste,
    onFocus: () => {
      focused.current = true;
      editing.breakRun();
      editing.onFieldFocus?.(path);
      const el = ref.current;
      if (el && rich && el.textContent !== value) el.textContent = value;
    },
    onBlur: () => {
      focused.current = false;
      editing.breakRun();
      editing.onFieldFocus?.(null);
      const el = ref.current;
      if (el) el.innerHTML = rich ? inlineHtml(value) : esc(value);
    },
  });
}

/** One text of the slide: plain markup, or a field when the slide is being edited. */
function Field(props: FieldProps) {
  const editing = useContext(EditingContext);
  if (editing) return <EditableField {...props} editing={editing} />;
  const { tag, value, className, rich, attrs } = props;
  if (rich) return createElement(tag, { className: className || undefined, ...attrs, dangerouslySetInnerHTML: { __html: inlineHtml(value) } });
  return createElement(tag, { className: className || undefined, ...attrs }, value);
}

/** Whether empty fields are drawn as prompts (only while editing). */
function useEditing(): SlideEditing | null {
  return useContext(EditingContext);
}

/**
 * Whether an optional text is drawn. On the page an empty text is absent;
 * while editing, a text the person has just emptied is "" until the field
 * is left (the editor then removes it), and it must stay drawn meanwhile or
 * the field would vanish under the caret.
 */
function useShown(): (value: string | undefined) => value is string {
  const editing = useEditing();
  return editing
    ? (value: string | undefined): value is string => value !== undefined
    : (value: string | undefined): value is string => !!value;
}

// --- the layouts (one function per `_<layout>_slide` in slides.py) ----------------------

function Head({ slide, lede }: { slide: Slide; lede?: string }) {
  const editing = useEditing();
  const shown = useShown();
  const title = slide.title ?? "";
  const showTitle = shown(slide.title) || (!!editing && !shown(lede));
  if (!shown(slide.kicker) && !showTitle && !shown(lede)) return null;
  return (
    <header className="sl-head">
      {shown(slide.kicker) && <Field tag="p" className="sl-kicker" value={slide.kicker} path={["kicker"]} />}
      {showTitle && (
        <Field
          tag="h2"
          className="sl-h"
          value={title}
          path={["title"]}
          attrs={{ "data-len": String(sizeStep(len(title), [44, 78])) }}
          placeholder={editing?.placeholder("title")}
        />
      )}
      {shown(lede) && <Field tag="p" className="sl-lede" value={lede} path={["text"]} rich />}
    </header>
  );
}

function Hero({ slide, tag, shift, rule }: { slide: Slide; tag: "h1" | "h2"; shift: number; rule: boolean }) {
  const editing = useEditing();
  const shown = useShown();
  const title = slide.title ?? "";
  const size = Math.min(4, sizeStep(len(title), [22, 44, 76]) + shift);
  const subtitle = slide.subtitle ?? "";
  const promptSubtitle = !!editing && slide.layout === "title";
  return (
    <div className="sl-hero">
      {rule && <i className="sl-rule" />}
      {tag !== "h1" && shown(slide.kicker) && <Field tag="p" className="sl-kicker" value={slide.kicker} path={["kicker"]} />}
      <Field
        tag={tag}
        className="sl-big"
        value={title}
        path={["title"]}
        attrs={{ "data-len": String(size) }}
        placeholder={editing?.placeholder("title")}
      />
      {(shown(slide.subtitle) || promptSubtitle) && (
        <Field tag="p" className="sl-sub" value={subtitle} path={["subtitle"]} rich placeholder={editing?.placeholder("subtitle")} />
      )}
    </div>
  );
}

function TitleSlide({ slide }: { slide: Slide }) {
  const shown = useShown();
  return (
    <>
      {shown(slide.kicker) && <Field tag="p" className="sl-kicker" value={slide.kicker} path={["kicker"]} />}
      <Hero slide={slide} tag="h1" shift={0} rule />
    </>
  );
}

function SectionSlide({ slide, section }: { slide: Slide; section: number }) {
  return (
    <>
      <div className="sl-mark">
        <span>{String(section).padStart(2, "0")}</span>
        <i />
      </div>
      <Hero slide={slide} tag="h2" shift={1} rule={false} />
    </>
  );
}

function Items({ items, path }: { items: readonly string[]; path: FieldPath }) {
  const editing = useEditing();
  return (
    <>
      {items.map((item, index) => (
        <Field key={index} tag="li" value={item} path={[...path, index]} rich placeholder={editing?.placeholder("bullets")} />
      ))}
    </>
  );
}

function BulletsSlide({ slide }: { slide: Slide }) {
  const shown = useShown();
  const bullets = slide.bullets ?? [];
  const text = slide.text ?? "";
  const hasHead = shown(slide.kicker) || shown(slide.title) || (bullets.length > 0 && shown(slide.text));
  if (bullets.length) {
    const solo = !hasHead;
    const fit = listFit(bullets, solo ? 1088 : 593);
    return (
      <div className={`sl-split${solo ? " is-solo" : ""}`}>
        {hasHead && (
          <div className="sl-side">
            <Head slide={slide} lede={slide.text} />
          </div>
        )}
        <ul className="sl-body sl-list" data-fit={String(fit)}>
          <Items items={bullets} path={["bullets"]} />
        </ul>
      </div>
    );
  }
  const side = shown(slide.kicker) || shown(slide.title);
  const solo = !side || !shown(slide.text);
  return (
    <div className={`sl-split${solo ? " is-solo" : ""}`}>
      {side && (
        <div className="sl-side">
          <Head slide={slide} />
        </div>
      )}
      {shown(slide.text) && <Field tag="p" className="sl-body sl-prose" value={text} path={["text"]} rich />}
    </div>
  );
}

function ColumnsSlide({ slide }: { slide: Slide }) {
  const shown = useShown();
  const columns = slide.columns ?? [];
  let longest = 0;
  for (const column of columns) {
    const bullets = column.bullets ?? [];
    longest = Math.max(longest, len(column.title) + len(column.text) + bullets.reduce((sum, b) => sum + len(b) + 30, 0));
  }
  const [roomy, tight] = columns.length === 2 ? [260, 420] : [170, 280];
  const fit = sizeStep(longest, [roomy, tight]);
  return (
    <>
      <Head slide={slide} />
      <div className="sl-body sl-cols" data-fit={String(fit)} style={{ "--n": columns.length } as CSSProperties}>
        {columns.map((column, index) => (
          <div key={index} className="sl-col">
            {shown(column.title) && <Field tag="h3" value={column.title} path={["columns", index, "title"]} />}
            {shown(column.text) && <Field tag="p" value={column.text} path={["columns", index, "text"]} rich />}
            {column.bullets?.length ? (
              <ul>
                <Items items={column.bullets} path={["columns", index, "bullets"]} />
              </ul>
            ) : null}
          </div>
        ))}
      </div>
    </>
  );
}

function QuoteSlide({ slide }: { slide: Slide }) {
  const editing = useEditing();
  const quote = slide.quote ?? "";
  return (
    <figure className="sl-q">
      <span className="sl-qmark" aria-hidden="true">
        {"“"}
      </span>
      <Field
        tag="blockquote"
        value={quote}
        path={["quote"]}
        attrs={{ "data-len": String(sizeStep(len(quote), [120, 210])) }}
        placeholder={editing?.placeholder("quote")}
      />
      {(slide.by || editing) && <Field tag="figcaption" value={slide.by ?? ""} path={["by"]} placeholder={editing?.placeholder("by")} />}
    </figure>
  );
}

function StatsSlide({ slide }: { slide: Slide }) {
  const shown = useShown();
  const stats = slide.stats ?? [];
  const count = Math.max(1, stats.length);
  const longest = stats.length ? Math.max(...stats.map((stat) => len(stat.value))) : 1;
  const room = 1088 / count - 72;
  const scale = Math.min([9.2, 6.8, 5.2, 4.2][count - 1], room / (0.56 * Math.max(1, longest) * 22));
  return (
    <>
      <Head slide={slide} />
      <div className="sl-body sl-stats" style={{ "--n": count, "--vs": fixed2(scale) } as CSSProperties}>
        {stats.map((stat, index) => (
          <div key={index} className="sl-stat">
            <Field tag="div" className="sl-v" value={stat.value} path={["stats", index, "value"]} />
            {shown(stat.label) && <Field tag="div" className="sl-l" value={stat.label} path={["stats", index, "label"]} />}
            {shown(stat.detail) && <Field tag="div" className="sl-d" value={stat.detail} path={["stats", index, "detail"]} rich />}
          </div>
        ))}
      </div>
    </>
  );
}

function ChartSlide({ slide, figure }: { slide: Slide; figure: string | null }) {
  const shown = useShown();
  const text = slide.text ?? "";
  const aside = shown(slide.text);
  return (
    <>
      <Head slide={slide} />
      <div className={`sl-body sl-chart${aside ? " has-aside" : ""}`}>
        {/* The server's own drawing of this chart (deckPage.loadChartFigure): escaped SVG markup. */}
        <div className="sl-plot" dangerouslySetInnerHTML={{ __html: figure ?? "" }} />
        {aside && <Field tag="p" className="sl-aside" value={text} path={["text"]} rich />}
      </div>
    </>
  );
}

function TableSlide({ slide }: { slide: Slide }) {
  const shown = useShown();
  const table = slide.table ?? { columns: [], rows: [] };
  const { columns, rows } = table;
  const numeric = columns.map(
    (_, index) => rows.some((row) => row[index]) && rows.every((row) => !row[index] || NUMERIC_CELL_RE.test(row[index])),
  );
  const fit = Math.min(4, sizeStep(rows.length, [4, 6, 8]) + (columns.length > 5 ? 1 : 0));
  const caption = slide.caption ?? "";
  return (
    <>
      <Head slide={slide} />
      <div className="sl-body sl-tab" data-fit={String(fit)}>
        <table className="sl-table">
          <thead>
            <tr>
              {columns.map((name, index) => (
                <Field key={index} tag="th" className={numeric[index] ? "n" : ""} value={name} path={["table", "columns", index]} />
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, number) => (
              <tr key={number}>
                {row.map((text, index) => (
                  <Field key={index} tag="td" className={numeric[index] ? "n" : ""} value={text} path={["table", "rows", number, index]} />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {shown(slide.caption) && <Field tag="p" className="sl-cap" value={caption} path={["caption"]} rich />}
      </div>
    </>
  );
}

function ImageSlide({ slide }: { slide: Slide }) {
  const shown = useShown();
  const source = slide.image ?? "";
  const caption = slide.caption ?? "";
  const alt = clean(caption || slide.title || "", 140);
  const picture = source ? <img src={source} alt={alt} /> : null;
  const contain = slide.fit === "contain";
  if (!shown(slide.title)) {
    return (
      <figure className={contain ? "is-contain" : undefined}>
        {picture}
        {shown(slide.caption) && <Field tag="figcaption" value={caption} path={["caption"]} rich />}
      </figure>
    );
  }
  return (
    <>
      <Head slide={slide} />
      {shown(slide.caption) && <Field tag="p" className="sl-note" value={caption} path={["caption"]} rich />}
      <figure className={contain ? "sl-pic is-contain" : "sl-pic"}>{picture}</figure>
    </>
  );
}

function StepsSlide({ slide }: { slide: Slide }) {
  const shown = useShown();
  const steps = slide.steps ?? [];
  const perRow = steps.length <= 4 ? steps.length : 3;
  const fit = sizeStep(steps.length, [3, 4]);
  return (
    <>
      <Head slide={slide} />
      <ol className="sl-body sl-steps" data-fit={String(fit)} style={{ "--n": Math.max(1, perRow) } as CSSProperties}>
        {steps.map((step, index) => {
          const end = index % perRow === perRow - 1 || index === steps.length - 1;
          return (
            <li key={index} className={end ? "is-end" : undefined}>
              <div className="sl-step-n">
                <b>{index + 1}</b>
                <i />
              </div>
              {shown(step.title) && <Field tag="h3" value={step.title} path={["steps", index, "title"]} />}
              {shown(step.text) && <Field tag="p" value={step.text} path={["steps", index, "text"]} rich />}
            </li>
          );
        })}
      </ol>
    </>
  );
}

function ClosingSlide({ slide }: { slide: Slide }) {
  const bullets = slide.bullets ?? [];
  const hero = <Hero slide={slide} tag="h2" shift={bullets.length ? 1 : 0} rule />;
  if (!bullets.length) return hero;
  const fit = bullets.length > 3 || Math.max(...bullets.map(len)) > 70 ? 2 : 1;
  return (
    <>
      {hero}
      <ul className="sl-body sl-next" data-fit={String(fit)} style={{ "--n": bullets.length } as CSSProperties}>
        <Items items={bullets} path={["bullets"]} />
      </ul>
    </>
  );
}

// --- the slide ------------------------------------------------------------------------

/** The section number a section slide shows: how many sections there are up to it. */
export function sectionNumber(slides: readonly Slide[], index: number): number {
  let count = 0;
  for (let i = 0; i <= index && i < slides.length; i++) if (slides[i].layout === "section") count++;
  return count;
}

/** `_slide_label`: what a screen reader calls the slide. */
export function slideLabel(slide: Slide, index: number): string {
  const name = slide.title || slide.quote || slide.caption || "";
  return name ? `Slide ${index + 1}: ${clean(name, 80)}` : `Slide ${index + 1}`;
}

export interface SlideViewProps {
  slide: Slide;
  index: number;
  /** The deck's name, shown in every slide's footer (`clean(node.title, 80)`). */
  deckTitle: string;
  /** For a section slide: its chapter number. */
  section: number;
  /** A chart slide's figure (HTML from the server), or null while it is drawn. */
  figure?: string | null;
  /** The accessible name of the slide (the page's English label by default). */
  label?: string;
}

function SlideBody({ slide, section, figure }: { slide: Slide; section: number; figure: string | null }) {
  switch (slide.layout) {
    case "title":
      return <TitleSlide slide={slide} />;
    case "section":
      return <SectionSlide slide={slide} section={section} />;
    case "bullets":
      return <BulletsSlide slide={slide} />;
    case "columns":
      return <ColumnsSlide slide={slide} />;
    case "quote":
      return <QuoteSlide slide={slide} />;
    case "stats":
      return <StatsSlide slide={slide} />;
    case "chart":
      return <ChartSlide slide={slide} figure={figure} />;
    case "table":
      return <TableSlide slide={slide} />;
    case "image":
      return <ImageSlide slide={slide} />;
    case "steps":
      return <StepsSlide slide={slide} />;
    case "closing":
      return <ClosingSlide slide={slide} />;
  }
}

/** The `<section class="sl …">` of one slide, with its footer. */
export const SlideView = memo(function SlideView({ slide, index, deckTitle, section, figure = null, label }: SlideViewProps) {
  const shown = useShown();
  const layout = slide.layout;
  let classes = `sl l-${layout}`;
  let footer = layout !== "title";
  if (layout === "image" && !shown(slide.title)) {
    classes = "sl l-bleed";
    footer = false;
  } else if (layout === "closing" && !slide.bullets?.length) {
    classes += " is-bare";
  }
  return (
    <section className={classes} aria-roledescription="slide" aria-label={label ?? slideLabel(slide, index)}>
      <SlideBody slide={slide} section={section} figure={figure} />
      {footer && (
        <footer className="sl-foot">
          <span>{deckTitle}</span>
          <span>{index + 1}</span>
        </footer>
      )}
    </section>
  );
});
