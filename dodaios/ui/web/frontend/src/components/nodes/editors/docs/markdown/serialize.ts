/**
 * The editor's content (ProseMirror JSON) written as the Markdown the docs
 * page draws.
 *
 * The page is drawn by Python-Markdown, not by a CommonMark reader, so the
 * output is written in the subset both read the same way:
 * - nested blocks in a list item are indented by four spaces (Python-Markdown
 *   ignores a two-space nesting);
 * - every block is separated by a blank line (Python-Markdown does not let a
 *   list or a rule interrupt a paragraph);
 * - a hard break is two trailing spaces (Python-Markdown has no backslash
 *   break);
 * - only characters Python-Markdown can unescape get a backslash; the few it
 *   cannot (`<`, `~`, `=`, `:` where they would start a construct) are written
 *   as character references, which both readers turn back into the character.
 *
 * Untouched blocks keep their original text (`./document.ts`); this module
 * writes the blocks the person changed or made.
 */
import type { JSONContent } from "@tiptap/core";

import { isCalloutTone } from "./parse";

/** Marks in nesting order, outermost first: a link wraps emphasis, code is innermost. */
const MARK_ORDER = ["link", "bold", "italic", "strike", "code"] as const;
type MarkName = (typeof MARK_ORDER)[number];

interface InlineMark {
  type: MarkName;
  attrs?: Record<string, unknown>;
}

const DELIMITER: Record<Exclude<MarkName, "link" | "code">, string> = { bold: "**", italic: "*", strike: "~~" };

// ------------------------------------------------------------------ escaping

/** Text inside a paragraph, a heading or a cell, escaped for both readers. */
export function escapeText(text: string, options: { inTable?: boolean } = {}): string {
  let out = "";
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const before = index > 0 ? text[index - 1] : "";
    const after = text.slice(index + 1);
    switch (char) {
      case "\\":
      case "*":
      case "`":
        out += `\\${char}`;
        break;
      case "_":
        // An underscore inside a word (snake_case) is never emphasis.
        out += /[\p{L}\p{N}]/u.test(before) && /^[\p{L}\p{N}]/u.test(after) ? "_" : "\\_";
        break;
      case "[":
        // Only a bracket that would open a link or a reference is escaped,
        // so a footnote mark like [^1] stays one.
        out += /^[^\]]*\]\s?[([]/.test(after) || /^[^\]]+\]:/.test(after) ? "\\[" : "[";
        break;
      case "{":
        // An attribute list ({: .class}, {#id}) is read by the page.
        out += /^[:#.]/.test(after) ? "\\{" : "{";
        break;
      case "~":
        // Python-Markdown has no escape for "~"; a reference stops "~~" striking.
        out += before === "~" || after.startsWith("~") ? "&#126;" : "~";
        break;
      case "<":
        // An address in angle brackets would become a link.
        out += /^[^\s<>]+[:@][^\s<>]*>/.test(after) ? "&lt;" : "<";
        break;
      case "&":
        // Text that looks like a character reference must stay text.
        out += /^#?[A-Za-z0-9]+;/.test(after) ? "&amp;" : "&";
        break;
      case "|":
        out += options.inTable ? "\\|" : "|";
        break;
      default:
        out += char;
    }
  }
  return out;
}

/** A line that would start a block (heading, quote, list, rule…) gets that start escaped. */
function escapeLineStart(line: string): string {
  const trimmed = line.replace(/^[ \t]+/, "");
  if (/^#/.test(trimmed)) return `\\${trimmed}`;
  if (/^>/.test(trimmed)) return `\\${trimmed}`;
  if (/^[-+](?:[ \t]|$)/.test(trimmed)) return `\\${trimmed}`;
  const ordered = /^(\d{1,9})([.)])(?=[ \t]|$)/.exec(trimmed);
  if (ordered) return `${ordered[1]}\\${ordered[2]}${trimmed.slice(ordered[0].length)}`;
  if (/^=+[ \t]*$/.test(trimmed)) return `&#61;${trimmed.slice(1)}`;
  if (/^-{2,}[ \t]*$/.test(trimmed)) return `\\${trimmed}`;
  if (/^:[ \t]/.test(trimmed)) return `&#58;${trimmed.slice(1)}`;
  return trimmed;
}

// -------------------------------------------------------------------- inline

function marksOf(node: JSONContent): InlineMark[] {
  return (node.marks ?? [])
    .filter((mark): mark is InlineMark => (MARK_ORDER as readonly string[]).includes(mark.type))
    .sort((a, b) => MARK_ORDER.indexOf(a.type) - MARK_ORDER.indexOf(b.type));
}

function sameMark(a: InlineMark, b: InlineMark): boolean {
  return a.type === b.type && (a.type !== "link" || a.attrs?.href === b.attrs?.href);
}

/** A link or picture address that both readers keep whole. */
export function linkDestination(href: string): string {
  return href.trim().replace(/ /g, "%20").replace(/\(/g, "%28").replace(/\)/g, "%29");
}

function linkTitle(title: unknown): string {
  return typeof title === "string" && title ? ` "${title.replace(/"/g, "&quot;")}"` : "";
}

function codeSpan(text: string): string {
  const longest = Math.max(0, ...(text.match(/`+/g) ?? []).map((run) => run.length));
  const fence = "`".repeat(longest + 1);
  const pad = text.startsWith("`") || text.endsWith("`") ? " " : "";
  return `${fence}${pad}${text}${pad}${fence}`;
}

function openDelimiter(mark: InlineMark): string {
  if (mark.type === "link") return "[";
  if (mark.type === "code") return "";
  return DELIMITER[mark.type];
}

function closeDelimiter(mark: InlineMark): string {
  if (mark.type === "link") {
    return `](${linkDestination(String(mark.attrs?.href ?? ""))}${linkTitle(mark.attrs?.title)})`;
  }
  if (mark.type === "code") return "";
  return DELIMITER[mark.type];
}

/**
 * Inline content as Markdown. Marks stay open across neighbouring text that
 * shares them, whitespace is moved outside a mark's delimiters (`**a** b`,
 * never `**a **b`), and every mark is closed before a hard break.
 */
export function serializeInline(
  content: JSONContent[] | undefined,
  options: { inTable?: boolean; breaks?: boolean } = {},
): string {
  let out = "";
  const open: InlineMark[] = [];
  const closeFrom = (index: number) => {
    const trailing = /[ \t]+$/.exec(out)?.[0] ?? "";
    if (trailing && open.length > index) out = out.slice(0, -trailing.length);
    for (let at = open.length - 1; at >= index; at -= 1) out += closeDelimiter(open[at]);
    open.length = index;
    out += trailing;
  };
  const items = content ?? [];
  for (const node of items) {
    if (node.type === "hardBreak") {
      closeFrom(0);
      out = out.replace(/[ \t]+$/, "");
      out += options.breaks === false || options.inTable ? " " : "  \n";
      continue;
    }
    if (node.type === "image") {
      closeFrom(open.filter((mark) => mark.type === "link").length ? 1 : 0);
      const alt = String(node.attrs?.alt ?? "").replace(/([\\[\]])/g, "\\$1");
      out += `![${alt}](${linkDestination(String(node.attrs?.src ?? ""))}${linkTitle(node.attrs?.title)})`;
      continue;
    }
    if (node.type !== "text" || !node.text) continue;
    const marks = marksOf(node);
    // Keep every open mark the text still has; close from the first it lost.
    let keep = 0;
    while (keep < open.length && marks.some((mark) => sameMark(mark, open[keep]))) keep += 1;
    if (keep < open.length) closeFrom(keep);
    const code = marks.find((mark) => mark.type === "code");
    let text = node.text.replace(/\n/g, " ");
    // Whitespace before the text goes in front of any delimiter that opens now.
    const toOpen = marks.filter((mark) => mark.type !== "code" && !open.some((held) => sameMark(held, mark)));
    if (toOpen.length) {
      const leading = /^[ \t]+/.exec(text)?.[0] ?? "";
      out += leading;
      text = text.slice(leading.length);
      if (!text) continue;
      for (const mark of toOpen) {
        out += openDelimiter(mark);
        open.push(mark);
      }
    }
    out += code ? codeSpan(text) : escapeText(text, options);
  }
  closeFrom(0);
  return out;
}

// --------------------------------------------------------------------- block

function indent(text: string, width: number): string {
  const pad = " ".repeat(width);
  return text
    .split("\n")
    .map((line) => (line ? pad + line : line))
    .join("\n");
}

function paragraph(node: JSONContent): string {
  // An empty line would end the paragraph in Markdown, so a run of breaks
  // keeps one, and a break at either end shows nothing on the page.
  const lines = serializeInline(node.content)
    .split("\n")
    .map((line) => escapeLineStart(line.replace(/[ \t]+$/, "")))
    .filter((line) => line.length > 0);
  // Two trailing spaces mark a break.
  return lines.join("  \n");
}

function fence(body: string, info: string): string {
  const longest = Math.max(2, ...(body.match(/^`{3,}/gm) ?? []).map((run) => run.length));
  const marker = "`".repeat(longest + 1);
  return `${marker}${info}\n${body}\n${marker}`;
}

/** A list item is tight when it holds one paragraph, optionally followed by lists. */
function isTightItem(item: JSONContent): boolean {
  const [first, ...rest] = item.content ?? [];
  return (
    (!first || first.type === "paragraph") &&
    rest.every((child) => ["bulletList", "orderedList", "taskList"].includes(child.type ?? ""))
  );
}

function list(node: JSONContent, marker: (index: number) => string): string {
  const items = node.content ?? [];
  const tight = items.every(isTightItem);
  return items
    .map((item, index) => {
      const head = marker(index);
      const body = serializeBlocks(item.content, tight ? "\n" : "\n\n");
      const width = Math.max(4, head.length);
      const [first, ...rest] = body.split("\n");
      // Continuation lines line up four spaces in, where Python-Markdown looks.
      const tail = rest.length ? `\n${indent(rest.join("\n"), width)}` : "";
      return `${head}${first ?? ""}${tail}`.replace(/[ \t]+$/, "");
    })
    .join(tight ? "\n" : "\n\n");
}

function tableCell(cell: JSONContent): string {
  const text = (cell.content ?? [])
    .map((child) => serializeInline(child.content, { inTable: true }))
    .filter(Boolean)
    .join(" ")
    .trim();
  return text || " ";
}

function table(node: JSONContent): string {
  const rows = (node.content ?? []).map((row) => row.content ?? []);
  if (!rows.length) return "";
  const width = Math.max(...rows.map((row) => row.length), 1);
  const line = (cells: string[]) => `| ${cells.join(" | ")} |`;
  const cellsOf = (row: JSONContent[]) =>
    Array.from({ length: width }, (_, index) => (row[index] ? tableCell(row[index]) : " "));
  const aligns = Array.from({ length: width }, (_, index) => rows[0][index]?.attrs?.align ?? null);
  const rule = aligns.map((align) =>
    align === "center" ? ":---:" : align === "right" ? "---:" : align === "left" ? ":---" : "---",
  );
  return [line(cellsOf(rows[0])), line(rule), ...rows.slice(1).map((row) => line(cellsOf(row)))].join("\n");
}

function quote(body: string): string {
  return body
    .split("\n")
    .map((line) => (line ? `> ${line}` : ">"))
    .join("\n");
}

/** One block as Markdown; an empty paragraph or heading writes nothing. */
export function serializeBlock(node: JSONContent): string {
  switch (node.type) {
    case "paragraph":
      return paragraph(node);
    case "heading": {
      const level = Math.min(6, Math.max(1, Number(node.attrs?.level) || 2));
      const text = serializeInline(node.content, { breaks: false }).trim();
      // A closing "#" run would be read as part of the heading's syntax.
      return text ? `${"#".repeat(level)} ${text.replace(/#+$/, (run) => `\\${run}`)}` : "";
    }
    case "blockquote":
      return quote(serializeBlocks(node.content));
    case "callout": {
      const tone = isCalloutTone(node.attrs?.tone) ? node.attrs.tone : "note";
      const body = serializeBlocks(node.content);
      return quote(body ? `[!${tone.toUpperCase()}]\n${body}` : `[!${tone.toUpperCase()}]`);
    }
    case "bulletList":
      return list(node, () => "- ");
    case "orderedList": {
      const start = Math.max(0, Number(node.attrs?.start ?? 1) || 0);
      return list(node, (index) => `${start + index}. `);
    }
    case "taskList":
      return list(node, (index) => (node.content?.[index]?.attrs?.checked ? "- [x] " : "- [ ] "));
    case "codeBlock": {
      const body = (node.content ?? []).map((child) => child.text ?? "").join("");
      const language = typeof node.attrs?.language === "string" ? node.attrs.language.trim() : "";
      return fence(body, language);
    }
    case "chartBlock":
      return fence(String(node.attrs?.source ?? "").trim(), "chart");
    case "metricsBlock":
      return fence(String(node.attrs?.source ?? "").trim(), "metrics");
    case "rawBlock":
      return (node.content ?? []).map((child) => child.text ?? "").join("").trim();
    case "horizontalRule":
      return "---";
    case "table":
      return table(node);
    default:
      // An unknown block keeps its words as a paragraph rather than vanishing.
      return node.content ? serializeBlocks(node.content) : "";
  }
}

/**
 * The line that keeps two neighbouring blocks apart on the page.
 * Python-Markdown joins a quote with the quote before it, and a list with a
 * list of the same kind before it, even across a blank line, which would
 * swallow a callout into the quote above it or two lists into one. A
 * paragraph holding only a zero-width space sits between them instead: it
 * shows nothing, and the reader (`parse.ts`) drops it again.
 */
export const BLOCK_SEPARATOR = "&#8203;";

const QUOTES = new Set(["blockquote", "callout"]);
const DASH_LISTS = new Set(["bulletList", "taskList"]);

export function needsSeparator(before: string, after: string): boolean {
  if (QUOTES.has(before) && QUOTES.has(after)) return true;
  if (DASH_LISTS.has(before) && DASH_LISTS.has(after)) return true;
  return before === "orderedList" && after === "orderedList";
}

/** What goes between two top-level blocks of these types. */
export function blockGap(before: string, after: string): string {
  return needsSeparator(before, after) ? `\n\n${BLOCK_SEPARATOR}\n\n` : "\n\n";
}

/** Blocks separated by a blank line (or by `separator`), empty ones left out. */
export function serializeBlocks(content: JSONContent[] | undefined, separator = "\n\n"): string {
  let out = "";
  let previous = "";
  for (const node of content ?? []) {
    const text = serializeBlock(node);
    if (!text) continue;
    if (out) out += needsSeparator(previous, node.type ?? "") ? `\n\n${BLOCK_SEPARATOR}\n\n` : separator;
    out += text;
    previous = node.type ?? "";
  }
  return out;
}

/** A whole document as Markdown, without reference to its original text. */
export function docToMarkdown(doc: JSONContent): string {
  return serializeBlocks(doc.content).trim();
}
