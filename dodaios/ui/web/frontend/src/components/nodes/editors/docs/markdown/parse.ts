/**
 * A document's Markdown as the editor's content (ProseMirror JSON).
 *
 * The page is drawn by Python-Markdown (`dodaios/artifacts/report.py`, with
 * the "extra", "sane_lists" and "toc" extensions, raw HTML shown as text) and
 * the report blocks (`dodaios/artifacts/report_blocks.py`). This reader is
 * markdown-it with raw HTML off, which agrees with that renderer on
 * everything the editor offers. Where the two dialects differ (a list that
 * interrupts a paragraph, a list nested by two spaces, a definition list or
 * a footnote definition, which only the page knows), the original text of an
 * untouched block is written back as it was (`DocMarkdown` in
 * `./document.ts`), and the shapes only the page knows become a raw Markdown
 * block that is edited as text, so nothing the page draws is lost.
 *
 * Shapes beyond plain Markdown, read here into their own nodes:
 * - a quote opening with `[!NOTE]` … `[!CAUTION]` → `callout` (tone);
 * - a fenced `chart` block → `chartBlock` (its JSON kept verbatim);
 * - a fenced `metrics` block → `metricsBlock` (its lines kept verbatim);
 * - a bullet list whose every item opens with `[ ]` or `[x]` → `taskList`;
 * - `~~text~~` → strike (the docs page draws it, `kinds/docs.py`).
 */
import MarkdownIt, { type Token } from "markdown-it";
import type { JSONContent } from "@tiptap/core";

export const CALLOUT_TONES = ["note", "tip", "important", "warning", "caution"] as const;
export type CalloutTone = (typeof CALLOUT_TONES)[number];

export function isCalloutTone(value: unknown): value is CalloutTone {
  return typeof value === "string" && (CALLOUT_TONES as readonly string[]).includes(value);
}

export type CellAlign = "left" | "center" | "right" | null;

/** One top-level block and the source lines it came from (`[start, end)`). */
export interface ParsedBlock {
  node: JSONContent;
  lines: [number, number];
}

export interface ParsedMarkdown {
  blocks: ParsedBlock[];
  /** The document's source lines, for writing untouched blocks back verbatim. */
  sourceLines: string[];
  /**
   * Link reference definitions (`[label]: https://…`) as written. markdown-it
   * resolves them into the links and drops the lines, so they are kept here
   * and written back when a block that still uses one keeps its original text.
   */
  references: string[];
}

// CommonMark plus tables and strike; no raw HTML (the page shows it as text),
// no bare-URL linking and no typographic replacements (the page does neither).
const reader = new MarkdownIt("commonmark", { html: false, linkify: false, typographer: false }).enable([
  "table",
  "strikethrough",
]);

const CALLOUT_MARKER = /^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*/i;
const TASK_MARKER = /^\[([ xX])\](?:[ \t]+|$)/;
const REFERENCE_LINE = /^ {0,3}\[(?!\^)[^\]]+\]:[ \t]*\S/;
/**
 * Paragraph shapes only Python-Markdown's "extra" understands: a footnote or
 * abbreviation definition, a definition list's `: ` line, a lone attribute
 * list. markdown-it reads them as running text, so editing them as rich text
 * would lose what they are; they stay raw Markdown instead.
 */
const PAGE_ONLY_PARAGRAPH = /^(?:\[\^[^\]]+\]:|\*\[[^\]]+\]:|:[ \t]|\{:[^}]*\}\s*$)/m;

const MARK_OF: Record<string, string> = { strong_open: "bold", em_open: "italic", s_open: "strike" };

function alignOf(token: Token): CellAlign {
  const style = String(token.attrGet("style") ?? "");
  const found = /text-align:\s*(left|center|right)/.exec(style);
  return found ? (found[1] as CellAlign) : null;
}

function sameMarks(a: JSONContent["marks"], b: JSONContent["marks"]): boolean {
  return JSON.stringify(a ?? []) === JSON.stringify(b ?? []);
}

/** Inline tokens as text nodes with marks, hard breaks and pictures. */
export function inlineContent(children: Token[] | null): JSONContent[] {
  const out: JSONContent[] = [];
  const marks: NonNullable<JSONContent["marks"]> = [];
  const pushText = (text: string, extra?: JSONContent["marks"]) => {
    if (!text) return;
    const nodeMarks = extra ?? (marks.length ? marks.map((mark) => ({ ...mark })) : undefined);
    const last = out[out.length - 1];
    if (last && last.type === "text" && sameMarks(last.marks, nodeMarks)) {
      last.text = `${last.text ?? ""}${text}`;
      return;
    }
    const node: JSONContent = { type: "text", text };
    if (nodeMarks && nodeMarks.length) node.marks = nodeMarks;
    out.push(node);
  };
  for (const token of children ?? []) {
    switch (token.type) {
      case "text":
      case "text_special":
        pushText(token.content);
        break;
      case "softbreak":
        // A line break inside a paragraph is a space on the page.
        pushText(" ");
        break;
      case "hardbreak":
        out.push({ type: "hardBreak" });
        break;
      case "code_inline": {
        // The code mark excludes every other mark but a link.
        const link = marks.filter((mark) => mark.type === "link");
        pushText(token.content, [...link.map((mark) => ({ ...mark })), { type: "code" }]);
        break;
      }
      case "strong_open":
      case "em_open":
      case "s_open":
        marks.push({ type: MARK_OF[token.type] });
        break;
      case "strong_close":
      case "em_close":
      case "s_close": {
        const name = MARK_OF[token.type.replace("_close", "_open")];
        const at = marks.map((mark) => mark.type).lastIndexOf(name);
        if (at >= 0) marks.splice(at, 1);
        break;
      }
      case "link_open": {
        const attrs: Record<string, string> = { href: String(token.attrGet("href") ?? "") };
        const title = token.attrGet("title");
        if (title) attrs.title = String(title);
        marks.unshift({ type: "link", attrs });
        break;
      }
      case "link_close": {
        const at = marks.findIndex((mark) => mark.type === "link");
        if (at >= 0) marks.splice(at, 1);
        break;
      }
      case "image": {
        const alt = (token.children ?? []).map((child: Token) => child.content).join("") || token.content;
        out.push({
          type: "image",
          attrs: { src: token.attrGet("src") ?? "", alt: alt || null, title: token.attrGet("title") || null },
        });
        break;
      }
      default:
        // html_inline cannot occur (raw HTML is off); anything else unknown
        // keeps its text so no words are lost.
        if (token.content) pushText(token.content);
    }
  }
  return out;
}

function firstText(node: JSONContent | undefined): JSONContent | undefined {
  const first = node?.content?.[0];
  return first && first.type === "text" ? first : undefined;
}

/** Drop a prefix from a paragraph's first text node; the node goes when nothing is left. */
function stripPrefix(paragraph: JSONContent, pattern: RegExp): string | null {
  const text = firstText(paragraph);
  const found = text ? pattern.exec(text.text ?? "") : null;
  if (!text || !found) return null;
  const rest = (text.text ?? "").slice(found[0].length).replace(/^\s+/, "");
  if (rest) text.text = rest;
  else paragraph.content = (paragraph.content ?? []).slice(1);
  // A break right after the marker only separated it from the text.
  if (paragraph.content?.[0]?.type === "hardBreak" && !rest) paragraph.content = paragraph.content.slice(1);
  if (paragraph.content && !paragraph.content.length) delete paragraph.content;
  return found[1];
}

/** A quote that opens with a tone marker is a callout. */
function asCallout(quote: JSONContent): JSONContent {
  const first = quote.content?.[0];
  if (!first || first.type !== "paragraph" || !CALLOUT_MARKER.test(firstText(first)?.text ?? "")) return quote;
  const tone = (stripPrefix(first, CALLOUT_MARKER) ?? "note").toLowerCase();
  const content = (quote.content ?? []).filter((child, index) => index > 0 || child.content?.length);
  return { type: "callout", attrs: { tone }, content: content.length ? content : [{ type: "paragraph" }] };
}

/** A bullet list whose every item opens with `[ ]` or `[x]` is a checklist. */
function asTaskList(list: JSONContent): JSONContent {
  const items = list.content ?? [];
  const shaped = items.length > 0 && items.every((item) => {
    const first = item.content?.[0];
    return first?.type === "paragraph" && TASK_MARKER.test(firstText(first)?.text ?? "");
  });
  if (!shaped) return list;
  return {
    type: "taskList",
    content: items.map((item) => {
      const first = item.content![0];
      const mark = stripPrefix(first, TASK_MARKER);
      return { type: "taskItem", attrs: { checked: mark === "x" || mark === "X" }, content: item.content };
    }),
  };
}

function fenceNode(token: Token): JSONContent {
  const info = token.info.trim().split(/\s+/, 1)[0] ?? "";
  const body = token.content.replace(/\n$/, "");
  if (info === "chart") return { type: "chartBlock", attrs: { source: body } };
  if (info === "metrics") return { type: "metricsBlock", attrs: { source: body } };
  const node: JSONContent = { type: "codeBlock", attrs: { language: info || null } };
  if (body) node.content = [{ type: "text", text: body }];
  return node;
}

/** Turn markdown-it's flat token stream into nested nodes. */
function buildBlocks(tokens: Token[], sourceLines: string[]): ParsedBlock[] {
  const root: JSONContent = { type: "doc", content: [] };
  const stack: JSONContent[] = [root];
  const blocks: ParsedBlock[] = [];
  const top = () => stack[stack.length - 1];
  const append = (node: JSONContent, token: Token) => {
    const parent = top();
    (parent.content ??= []).push(node);
    if (parent === root) blocks.push({ node, lines: (token.map as [number, number]) ?? [0, 0] });
  };
  const open = (node: JSONContent, token: Token) => {
    append(node, token);
    stack.push(node);
  };
  const close = (finish?: (node: JSONContent) => JSONContent) => {
    const node = stack.pop();
    if (!node || !finish) return;
    const parent = top();
    const replaced = finish(node);
    if (replaced === node) return;
    const siblings = parent.content ?? [];
    siblings[siblings.lastIndexOf(node)] = replaced;
    const block = blocks.find((entry) => entry.node === node);
    if (block) block.node = replaced;
  };

  for (const token of tokens) {
    switch (token.type) {
      case "paragraph_open": {
        const lines = token.map ? sourceLines.slice(token.map[0], token.map[1]) : [];
        if (top() === root && lines.length && PAGE_ONLY_PARAGRAPH.test(lines.join("\n"))) {
          open({ type: "rawBlock", content: [{ type: "text", text: lines.join("\n") }] }, token);
        } else {
          open({ type: "paragraph" }, token);
        }
        break;
      }
      case "heading_open":
        open({ type: "heading", attrs: { level: Number(token.tag.slice(1)) || 2 } }, token);
        break;
      case "blockquote_open":
        open({ type: "blockquote", content: [] }, token);
        break;
      case "bullet_list_open":
        open({ type: "bulletList", content: [] }, token);
        break;
      case "ordered_list_open":
        open({ type: "orderedList", attrs: { start: Number(token.attrGet("start") ?? 1) || 1 } }, token);
        break;
      case "list_item_open":
        open({ type: "listItem", content: [] }, token);
        break;
      case "table_open":
        open({ type: "table", content: [] }, token);
        break;
      case "tr_open":
        open({ type: "tableRow", content: [] }, token);
        break;
      case "th_open":
      case "td_open":
        open({ type: token.type === "th_open" ? "tableHeader" : "tableCell", attrs: { align: alignOf(token) } }, token);
        break;
      case "inline": {
        const parent = top();
        if (parent.type === "rawBlock") break;
        const content = inlineContent(token.children);
        if (parent.type === "tableHeader" || parent.type === "tableCell") {
          parent.content = [content.length ? { type: "paragraph", content } : { type: "paragraph" }];
        } else if (content.length) {
          parent.content = content;
        }
        break;
      }
      case "paragraph_close": {
        // The writer's separator between two quotes or lists (`BLOCK_SEPARATOR`).
        const node = top();
        const text = (node.content ?? []).map((child) => (child.type === "text" ? child.text : "x")).join("");
        close();
        if (node.type === "paragraph" && text.includes("\u200b") && !text.replace(/[\u200b\s]/g, "")) {
          const parent = top();
          parent.content = (parent.content ?? []).filter((child) => child !== node);
          const at = blocks.findIndex((entry) => entry.node === node);
          if (at >= 0) blocks.splice(at, 1);
        }
        break;
      }
      case "heading_close":
      case "list_item_close":
      case "table_close":
      case "tr_close":
      case "th_close":
      case "td_close":
      case "ordered_list_close":
        close();
        break;
      case "blockquote_close":
        close(asCallout);
        break;
      case "bullet_list_close":
        close(asTaskList);
        break;
      case "fence":
        append(fenceNode(token), token);
        break;
      case "code_block": {
        const body = token.content.replace(/\n$/, "");
        append({ type: "codeBlock", attrs: { language: null }, ...(body ? { content: [{ type: "text", text: body }] } : {}) }, token);
        break;
      }
      case "hr":
        append({ type: "horizontalRule" }, token);
        break;
      default:
        // thead/tbody wrappers carry nothing of their own.
        break;
    }
  }
  // A list item or cell needs at least one block; an empty one gets a paragraph.
  const fill = (node: JSONContent) => {
    if (["listItem", "taskItem", "tableCell", "tableHeader", "blockquote", "callout"].includes(node.type ?? "")) {
      if (!node.content?.length) node.content = [{ type: "paragraph" }];
    }
    // A list item opens with a line of text in the editor's schema.
    if ((node.type === "listItem" || node.type === "taskItem") && node.content?.[0]?.type !== "paragraph") {
      node.content = [{ type: "paragraph" }, ...(node.content ?? [])];
    }
    node.content?.forEach(fill);
  };
  root.content?.forEach(fill);
  return blocks;
}

/** The document's Markdown read into top-level blocks with their source lines. */
export function parseMarkdown(markdown: string): ParsedMarkdown {
  const source = markdown.replace(/\r\n?/g, "\n");
  const sourceLines = source.split("\n");
  const blocks = buildBlocks(reader.parse(source, {}), sourceLines);
  // Reference definitions live in the lines no block covers.
  const covered = new Set<number>();
  for (const block of blocks) for (let line = block.lines[0]; line < block.lines[1]; line += 1) covered.add(line);
  const references = sourceLines.filter((line, index) => !covered.has(index) && REFERENCE_LINE.test(line)).map((line) => line.trim());
  return { blocks, sourceLines, references };
}

/** The editor's whole document for a Markdown text. */
export function markdownToDoc(markdown: string): JSONContent {
  const { blocks } = parseMarkdown(markdown);
  return { type: "doc", content: blocks.length ? blocks.map((block) => block.node) : [{ type: "paragraph" }] };
}
