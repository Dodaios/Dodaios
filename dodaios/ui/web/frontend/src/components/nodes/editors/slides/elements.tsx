/**
 * A slide's free elements and its background, drawn as the deck page draws
 * them (`slide_elements.py`: `element_html`, `line_svg`, `background_html`),
 * so with the page's stylesheet they look exactly like the page. The markup
 * fixture test compares both sides; change them together.
 *
 * While the editor edits a slide, a text element (or a table) the person
 * double-clicked becomes a field to write into; everything else stays plain
 * markup, and the canvas around it handles selecting, moving and resizing.
 */
import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  type CSSProperties,
  type ClipboardEvent as ReactClipboardEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";

import {
  cssColor,
  hexLuminance,
  PATH_SHAPES,
  type Background,
  type ChartElement,
  type ImageElement,
  type LineElement,
  type ShapeElement,
  type SlideElement,
  type TableElement,
  type TextElement,
} from "./elementModel";
import { esc, inlineHtml } from "./inline";

/** What the elements of a slide need from the deck around them. */
export interface ElementsContext {
  /** The drawn figure of a chart element (server HTML), or null while it loads. */
  chartFigure: (chart: Record<string, unknown>) => string | null;
}
const FiguresContext = createContext<ElementsContext | null>(null);
export const ElementFiguresProvider = FiguresContext.Provider;

/** The element editing the canvas hands the slide (only on the editing canvas). */
export interface ElementEditing {
  /** The element whose text is being written (by index), or -1. */
  writing: number;
  /** A text element's text (or a table cell) was typed. */
  setText: (index: number, path: readonly (string | number)[], value: string) => void;
  /** Writing ended (Escape, focus left). */
  stopWriting: () => void;
  undo: () => void;
  redo: () => void;
}
const ElementEditingContext = createContext<ElementEditing | null>(null);

/** How many of a slide's click-elements are in (the presenter sets it; elsewhere none). */
export const BuiltContext = createContext(0);
export const ElementEditingProvider = ElementEditingContext.Provider;

// --- numbers as the page writes them -----------------------------------------------------

/** `_fmt`: up to two decimals, no trailing zeros. */
export function fmt(value: number): string {
  const rounded = Math.round(value * 100) / 100;
  const text = rounded.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  return text === "-0" || text === "" ? "0" : text;
}

function px(value: number): string {
  return `${fmt(value)}px`;
}

type Style = Record<string, string>;

function boxStyle(element: SlideElement & { x: number; y: number; w: number; h: number }): Style {
  const style: Style = { left: px(element.x), top: px(element.y), width: px(element.w), height: px(element.h) };
  if (element.rotate) style.rotate = `${fmt(element.rotate)}deg`;
  if (element.opacity !== undefined) style.opacity = fmt(element.opacity / 100);
  return style;
}

function paint(element: { fill?: string; stroke?: string; stroke_width?: number; dash?: string; radius?: number }, style: Style): void {
  if (element.fill) style.background = cssColor(element.fill);
  if (element.stroke) {
    const dash = element.dash === "dash" ? "dashed" : element.dash === "dot" ? "dotted" : "solid";
    style.border = `${px(element.stroke_width ?? 2)} ${dash} ${cssColor(element.stroke)}`;
  }
  if (element.radius) style.borderRadius = px(element.radius);
}

/** The attributes every element's outer box carries (`_opening`). */
function opening(element: SlideElement, kind: string, classes: string[], style: Style, index: number, delay: number | null, built = false) {
  let className = ["el", `el-${kind}`, ...classes].join(" ");
  if ("shadow" in element && element.shadow) className += " is-shadow";
  if (built) className += " is-built";
  const attrs: Record<string, string | boolean | undefined> = { "data-el": String(index) };
  if (element.id) attrs["data-id"] = element.id;
  const full = { ...style };
  if (element.anim) {
    attrs["data-anim"] = element.anim;
    if (element.click) attrs["data-click"] = "";
    else if (delay !== null) full["--ad"] = `${delay}ms`;
  }
  return { className, ...attrs, style: full as CSSProperties };
}

function Linked({ element, children }: { element: SlideElement; children: ReactNode }) {
  if (!element.link) return <>{children}</>;
  return (
    <a className="el-a" href={element.link} rel="noopener noreferrer">
      {children}
    </a>
  );
}

// --- text -----------------------------------------------------------------------------

/** A text element's words as HTML (`text_content`). */
export function textContent(text: string, kind: string | undefined): string {
  if (kind === "bullet" || kind === "number") {
    const tag = kind === "bullet" ? "ul" : "ol";
    const items = text
      .split("\n")
      .filter((line) => line.trim())
      .map((line) => `<li>${inlineHtml(line)}</li>`)
      .join("");
    return `<${tag}>${items}</${tag}>`;
  }
  return text
    .split("\n")
    .map((part) => inlineHtml(part))
    .join("<br>");
}

/** The text colour that reads on a shape's own fill, when the fill says it (`shape_ink`). */
export function shapeInk(fill: string): string {
  if (!fill) return "";
  if (fill.toLowerCase() === "transparent") return "var(--ink)";
  const light = hexLuminance(fill);
  if (light === null) return "";
  return light > 0.4 ? "#111111" : "#ffffff";
}

function innerStyle(element: TextElement | ShapeElement, shape: boolean): Style {
  const style: Style = { fontSize: px(element.size ?? (shape ? 24 : 28)) };
  if (element.color) style.color = cssColor(element.color);
  else if (shape && shapeInk(element.fill ?? "")) style.color = shapeInk(element.fill ?? "");
  const align = element.align ?? (shape ? "center" : "left");
  if (align !== "left") style.textAlign = align;
  if (element.line !== undefined) style.lineHeight = fmt(element.line);
  if (element.spacing) style.letterSpacing = `${fmt(element.spacing)}em`;
  return style;
}

function innerClasses(element: TextElement | ShapeElement): string {
  const classes = ["el-t"];
  if (element.font) classes.push(`ff-${element.font}`);
  if (element.bold) classes.push("is-b");
  if (element.italic) classes.push("is-i");
  if (element.underline) classes.push("is-u");
  if (element.strike) classes.push("is-s");
  if (element.caps) classes.push("is-c");
  return classes.join(" ");
}

function placeCaretAtEnd(el: HTMLElement): void {
  const selection = el.ownerDocument.defaultView?.getSelection();
  if (!selection) return;
  const range = el.ownerDocument.createRange();
  range.selectNodeContents(el);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}

function selectAll(el: HTMLElement): void {
  const selection = el.ownerDocument.defaultView?.getSelection();
  if (!selection) return;
  const range = el.ownerDocument.createRange();
  range.selectNodeContents(el);
  selection.removeAllRanges();
  selection.addRange(range);
}

/** The words of a field as typed (`innerText` keeps the line breaks the person made). */
function typed(el: HTMLElement): string {
  return (el.innerText ?? el.textContent ?? "").replace(/\r/g, "").replace(/\n$/, "");
}

/**
 * A text (or a cell) of an element the person writes into. React draws the
 * element but never its content while it is focused, so typing is never
 * undone by a render; it shows the plain source (`**bold**`, one line per
 * point) while written and the drawn marks again when left.
 */
function WritableText({
  tag,
  className,
  style,
  value,
  html,
  multiline,
  limit,
  onValue,
  editing,
  autoFocus,
}: {
  tag: "div" | "td" | "th";
  className?: string;
  style?: CSSProperties;
  value: string;
  html: string;
  multiline: boolean;
  limit: number;
  onValue: (value: string) => void;
  editing: ElementEditing;
  autoFocus: boolean;
}) {
  const ref = useRef<HTMLElement | null>(null);
  const focused = useRef(false);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (focused.current) {
      if (typed(el) !== value) {
        el.textContent = value;
        placeCaretAtEnd(el);
      }
    } else if (el.innerHTML !== html) el.innerHTML = html;
  }, [value, html]);

  useEffect(() => {
    const el = ref.current;
    if (!el || !autoFocus) return;
    el.focus();
    selectAll(el);
  }, [autoFocus]);

  const Tag = tag;
  return (
    <Tag
      ref={ref as never}
      className={className}
      style={style}
      contentEditable="plaintext-only"
      suppressContentEditableWarning
      spellCheck
      role="textbox"
      aria-multiline={multiline || undefined}
      data-el-text=""
      onInput={() => {
        const el = ref.current;
        if (!el) return;
        let text = typed(el);
        if (!multiline) text = text.replace(/\n+/g, " ");
        if (text.length > limit) {
          text = text.slice(0, limit);
          el.textContent = text;
          placeCaretAtEnd(el);
        }
        onValue(text);
      }}
      onKeyDown={(event: ReactKeyboardEvent<HTMLElement>) => {
        const mod = event.metaKey || event.ctrlKey;
        const lower = event.key.toLowerCase();
        if (mod && !event.altKey && (lower === "z" || (lower === "y" && !event.shiftKey))) {
          event.preventDefault();
          event.stopPropagation();
          if (lower === "z" && !event.shiftKey) editing.undo();
          else editing.redo();
          return;
        }
        if (mod && (lower === "b" || lower === "i")) {
          // Bold and italic are marks in the text: wrap the selection in them.
          event.preventDefault();
          const doc = ref.current?.ownerDocument;
          const selection = doc?.defaultView?.getSelection();
          const picked = selection?.toString() ?? "";
          const mark = lower === "b" ? "**" : "*";
          if (doc && picked) doc.execCommand("insertText", false, `${mark}${picked}${mark}`);
          event.stopPropagation();
          return;
        }
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          ref.current?.blur();
          return;
        }
        if (event.key === "Enter" && !multiline) {
          event.preventDefault();
          ref.current?.blur();
        }
        if (event.key === "Tab") {
          event.preventDefault();
          ref.current?.blur();
        }
        event.stopPropagation();
      }}
      onPaste={(event: ReactClipboardEvent<HTMLElement>) => {
        event.preventDefault();
        let pasted = event.clipboardData.getData("text/plain").replace(/\r\n?/g, "\n");
        if (!multiline) pasted = pasted.replace(/\n+/g, " ");
        const doc = ref.current?.ownerDocument;
        if (doc && pasted) doc.execCommand("insertText", false, pasted);
      }}
      onFocus={() => {
        focused.current = true;
        const el = ref.current;
        if (el && el.textContent !== value) el.textContent = value;
      }}
      onBlur={() => {
        focused.current = false;
        const el = ref.current;
        if (el) el.innerHTML = html;
        editing.stopWriting();
      }}
      onPointerDown={(event) => event.stopPropagation()}
    />
  );
}

function TextOrShape({ element, index, delay, built = false }: { built?: boolean; element: TextElement | ShapeElement; index: number; delay: number | null }) {
  const editing = useContext(ElementEditingContext);
  const shape = element.type === "shape";
  const name = shape ? (element as ShapeElement).shape || "rect" : "";
  const style = boxStyle(element);
  const classes: string[] = [];
  if (shape) classes.push(`is-${name}`);
  const valign = element.valign ?? (shape ? "middle" : "top");
  if (valign === "middle") classes.push("v-m");
  else if (valign === "bottom") classes.push("v-b");
  let figure: ReactNode = null;
  if (shape && name in PATH_SHAPES) {
    const draw: Style = { fill: cssColor(element.fill) || "var(--da)" };
    if (element.stroke) {
      draw.stroke = cssColor(element.stroke);
      draw.strokeWidth = fmt(element.stroke_width ?? 2);
      if (element.dash === "dash") draw.strokeDasharray = "8 6";
      else if (element.dash === "dot") draw.strokeDasharray = "2 5";
    }
    figure = (
      <svg className="el-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <path d={PATH_SHAPES[name]} vectorEffect="non-scaling-stroke" style={draw as CSSProperties} />
      </svg>
    );
  } else {
    if (shape && !element.fill) style.background = "var(--da)";
    paint(element, style);
    if (shape && name === "rounded" && !element.radius) style.borderRadius = px(Math.min(element.w, element.h) * 0.18);
    else if (shape && name === "ellipse") style.borderRadius = "50%";
  }
  let padding = element.padding;
  if (padding === undefined) padding = shape || element.fill || element.stroke ? 16 : 0;
  if (padding) style.padding = px(padding);
  const text = element.text ?? "";
  let inner: ReactNode = null;
  if (text || element.type === "text" || (editing && editing.writing === index)) {
    const html = textContent(text, element.list);
    const className = innerClasses(element);
    const textStyle = innerStyle(element, shape) as CSSProperties;
    inner =
      editing && editing.writing === index ? (
        <WritableText
          tag="div"
          className={className}
          style={textStyle}
          value={text}
          html={html}
          multiline
          limit={2_000}
          onValue={(value) => editing.setText(index, ["text"], value)}
          editing={editing}
          autoFocus
        />
      ) : (
        <div className={className} style={textStyle} dangerouslySetInnerHTML={{ __html: html }} />
      );
  }
  return (
    <div {...opening(element, element.type, classes, style, index, delay, built)}>
      {figure}
      <Linked element={element}>{inner}</Linked>
    </div>
  );
}

function ImageBox({ element, index, delay, built = false }: { built?: boolean; element: ImageElement; index: number; delay: number | null }) {
  const style = boxStyle(element);
  paint(element, style);
  const fit = element.fit ?? "cover";
  return (
    <div {...opening(element, "image", [], style, index, delay, built)}>
      <Linked element={element}>
        {element.image ? <img src={element.image} alt={element.alt ?? ""} className={fit !== "cover" ? `is-${fit}` : undefined} /> : null}
      </Linked>
    </div>
  );
}

function TableBox({ element, index, delay, built = false }: { built?: boolean; element: TableElement; index: number; delay: number | null }) {
  const editing = useContext(ElementEditingContext);
  const writing = editing && editing.writing === index ? editing : null;
  const style = boxStyle(element);
  const head = element.head !== false;
  const tableStyle: Style = { fontSize: px(element.size ?? 20) };
  if (element.color) tableStyle.color = cssColor(element.color);
  if (element.fill) tableStyle["--tf"] = cssColor(element.fill);
  if (element.stroke) tableStyle["--tl"] = cssColor(element.stroke);
  const align = element.align ?? "left";
  if (align !== "left") tableStyle.textAlign = align;
  const classes = ["el-table"];
  if (head) classes.push("has-head");
  if (element.font) classes.push(`ff-${element.font}`);
  return (
    <div {...opening(element, "table", [], style, index, delay, built)}>
      <table className={classes.join(" ")} style={tableStyle as CSSProperties}>
        <tbody>
          {element.rows.map((row, r) => (
            <tr key={r}>
              {row.map((cell, c) => {
                const Tag = head && r === 0 ? "th" : "td";
                return writing ? (
                  <WritableText
                    key={c}
                    tag={Tag}
                    value={cell}
                    html={esc(cell)}
                    multiline={false}
                    limit={160}
                    onValue={(value) => writing.setText(index, ["rows", r, c], value)}
                    editing={writing}
                    autoFocus={r === 0 && c === 0}
                  />
                ) : (
                  <Tag key={c}>{cell}</Tag>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChartBox({ element, index, delay, built = false }: { built?: boolean; element: ChartElement; index: number; delay: number | null }) {
  const figures = useContext(FiguresContext);
  const figure = figures?.chartFigure(element.chart) ?? "";
  return <div {...opening(element, "chart", [], boxStyle(element), index, delay, built)} dangerouslySetInnerHTML={{ __html: figure }} />;
}

/** The points of an arrow head at (x, y) pointing along (ux, uy) (`_arrow_head`). */
function arrowHead(x: number, y: number, ux: number, uy: number, size: number): string {
  const backX = x - ux * size * 1.6;
  const backY = y - uy * size * 1.6;
  const nx = -uy * size;
  const ny = ux * size;
  return [
    [x, y],
    [backX + nx, backY + ny],
    [backX - nx, backY - ny],
  ]
    .map(([a, b]) => `${fmt(a)},${fmt(b)}`)
    .join(" ");
}

/** The geometry of a line's box (`line_svg`), shared with the canvas's hit line. */
export function lineBox(element: LineElement) {
  const width = element.width ?? 4;
  const pad = width * 3 + 4;
  const left = Math.min(element.x1, element.x2) - pad;
  const top = Math.min(element.y1, element.y2) - pad;
  return {
    left,
    top,
    w: Math.abs(element.x2 - element.x1) + 2 * pad,
    h: Math.abs(element.y2 - element.y1) + 2 * pad,
    a: [element.x1 - left, element.y1 - top] as const,
    b: [element.x2 - left, element.y2 - top] as const,
  };
}

function LineBox({ element, index, delay, built = false }: { built?: boolean; element: LineElement; index: number; delay: number | null }) {
  const editing = useContext(ElementEditingContext);
  const width = element.width ?? 4;
  const { left, top, w, h, a, b } = lineBox(element);
  const ink = cssColor(element.color) || "var(--ink)";
  const length = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
  const ux = (b[0] - a[0]) / length;
  const uy = (b[1] - a[1]) / length;
  const head = width * 1.8 + 3;
  const start = element.start === "arrow" ? [a[0] + ux * head * 1.4, a[1] + uy * head * 1.4] : a;
  const end = element.end === "arrow" ? [b[0] - ux * head * 1.4, b[1] - uy * head * 1.4] : b;
  let stroke = `stroke:${ink};stroke-width:${fmt(width)}`;
  if (element.dash === "dash") stroke += `;stroke-dasharray:${fmt(width * 3)} ${fmt(width * 2)}`;
  else if (element.dash === "dot") stroke += `;stroke-dasharray:0 ${fmt(width * 2)};stroke-linecap:round`;
  const ends: ReactNode[] = [];
  (
    [
      ["start", a, -ux, -uy],
      ["end", b, ux, uy],
    ] as const
  ).forEach(([key, point, dx, dy]) => {
    const kind = element[key];
    if (kind === "arrow") ends.push(<polygon key={key} points={arrowHead(point[0], point[1], dx, dy, head)} style={{ fill: ink }} />);
    else if (kind === "dot") ends.push(<circle key={key} cx={fmt(point[0])} cy={fmt(point[1])} r={fmt(width * 1.6 + 2)} style={{ fill: ink }} />);
  });
  const style: Style = { left: px(left), top: px(top), width: px(w), height: px(h) };
  if (element.opacity !== undefined) style.opacity = fmt(element.opacity / 100);
  const svg = (
    <svg className="el-svg" viewBox={`0 0 ${fmt(w)} ${fmt(h)}`} aria-hidden="true">
      <line x1={fmt(start[0])} y1={fmt(start[1])} x2={fmt(end[0])} y2={fmt(end[1])} style={cssText(stroke)} />
      {ends}
      {/* The canvas only: a wide, unseen line to pick the line by. */}
      {editing && <line className="el-hit" x1={fmt(a[0])} y1={fmt(a[1])} x2={fmt(b[0])} y2={fmt(b[1])} />}
    </svg>
  );
  return (
    <div {...opening(element, "line", [], style, index, delay, built)}>
      <Linked element={element}>{svg}</Linked>
    </div>
  );
}

/** A `prop:value;…` text as a React style object (custom properties kept). */
function cssText(text: string): CSSProperties {
  const style: Style = {};
  for (const part of text.split(";")) {
    const at = part.indexOf(":");
    if (at < 0) continue;
    const name = part.slice(0, at).trim();
    const camel = name.startsWith("--") ? name : name.replace(/-([a-z])/g, (_m, c: string) => c.toUpperCase());
    style[camel] = part.slice(at + 1).trim();
  }
  return style as CSSProperties;
}

/** One element as the page draws it. */
export function ElementView({ element, index, delay, built = false }: { element: SlideElement; index: number; delay: number | null; built?: boolean }) {
  switch (element.type) {
    case "text":
    case "shape":
      return <TextOrShape element={element} index={index} delay={delay} built={built} />;
    case "image":
      return <ImageBox element={element} index={index} delay={delay} built={built} />;
    case "table":
      return <TableBox element={element} index={index} delay={delay} built={built} />;
    case "chart":
      return <ChartBox element={element} index={index} delay={delay} built={built} />;
    case "line":
      return <LineBox element={element} index={index} delay={delay} built={built} />;
  }
}

/** The layer of a slide's free elements, in drawing order (`elements_html`). */
export function ElementsLayer({ elements }: { elements: readonly SlideElement[] | undefined }) {
  const built = useContext(BuiltContext);
  if (!elements?.length) return null;
  let step = 0;
  let clicks = 0;
  return (
    <div className="sl-els">
      {elements.map((element, index) => {
        let delay: number | null = null;
        let isBuilt = false;
        if (element.anim && !element.click) {
          delay = 150 + 120 * step;
          step += 1;
        } else if (element.anim && element.click) {
          isBuilt = clicks < built;
          clicks += 1;
        }
        return <ElementView key={element.id ?? `#${index}`} element={element} index={index} delay={delay} built={isBuilt} />;
      })}
    </div>
  );
}

/** The layer behind a slide's content (`background_html`). */
export function BackgroundLayer({ background }: { background: Background | undefined }) {
  if (!background) return null;
  let style: CSSProperties | undefined;
  if (background.gradient) {
    const g = background.gradient;
    style = { background: `linear-gradient(${g.angle}deg,${cssColor(g.from)},${cssColor(g.to)})` };
  } else if (background.color) style = { background: cssColor(background.color) };
  return (
    <div className="sl-bg" style={style}>
      {background.image && <img src={background.image} alt="" className={background.fit === "contain" ? "is-contain" : undefined} />}
      {background.dim ? <i className="sl-dim" style={{ opacity: fmt(background.dim / 100) }} /> : null}
    </div>
  );
}
