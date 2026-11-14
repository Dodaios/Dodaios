/**
 * The bridge between one document's Markdown and the editor's content that
 * keeps what the person did not touch exactly as it was written.
 *
 * Why: the document is written by the assistant (and read back by it) as
 * Markdown, in its own style, sometimes with shapes only the page's renderer
 * knows. Writing the whole text again from the editor's content after one
 * changed word would restyle every block and risk losing those shapes. So a
 * top-level block whose content is still exactly what was read keeps its
 * original lines, and the original gap between two such neighbours (blank
 * lines, reference definitions) stays too; only changed or new blocks are
 * written by `serializeBlock`.
 *
 * A block is recognised by its content (its JSON), not by its position, so
 * moving an untouched block keeps its text as well. ProseMirror keeps
 * unchanged nodes as the same objects across edits, which the cache below
 * uses so a keystroke only re-reads the block it changed.
 */
import type { JSONContent } from "@tiptap/core";

import { parseMarkdown, type ParsedMarkdown } from "./parse";
import { blockGap, serializeBlock } from "./serialize";

/** What the serializer needs of a ProseMirror node (kept minimal for tests). */
export interface BlockLike {
  toJSON(): JSONContent;
  /** The node's type (a ProseMirror node has it; JSON is read when it is missing). */
  type?: { name: string };
}

export interface DocLike {
  forEach(callback: (node: BlockLike) => void): void;
}

interface Original {
  index: number;
  source: string;
}

/** Where each block's trimmed text starts and ends in the original Markdown. */
interface Span {
  from: number;
  to: number;
}

export class DocMarkdown {
  readonly parsed: ParsedMarkdown;
  private readonly originals = new Map<string, Original[]>();
  private readonly keys = new WeakMap<object, string>();
  private readonly written = new WeakMap<object, string>();
  private readonly source: string;
  private readonly spans: Span[];

  constructor(markdown: string) {
    this.source = markdown.replace(/\r\n?/g, "\n");
    this.parsed = parseMarkdown(this.source);
    const offsets = [0];
    for (const line of this.parsed.sourceLines) offsets.push(offsets[offsets.length - 1] + line.length + 1);
    this.spans = this.parsed.blocks.map(({ lines: [start, end] }) => {
      const from = offsets[start];
      const text = this.source.slice(from, Math.min(offsets[end], this.source.length) || from);
      return { from, to: from + text.replace(/\s+$/, "").length };
    });
  }

  /** The editor's starting content. */
  get doc(): JSONContent {
    const content = this.parsed.blocks.map((block) => block.node);
    return { type: "doc", content: content.length ? content : [{ type: "paragraph" }] };
  }

  /**
   * Learn the loaded document: pair each top-level node of the editor (after
   * its schema filled in default attributes) with the lines it was read from.
   * When the editor did not keep one node per block, nothing is paired and
   * every block is written fresh, which is safe, only less faithful.
   */
  remember(doc: DocLike): void {
    this.originals.clear();
    const nodes: BlockLike[] = [];
    doc.forEach((node) => nodes.push(node));
    if (nodes.length !== this.spans.length) return;
    nodes.forEach((node, index) => {
      const source = this.source.slice(this.spans[index].from, this.spans[index].to);
      const key = this.keyOf(node);
      const list = this.originals.get(key) ?? [];
      list.push({ index, source });
      this.originals.set(key, list);
    });
  }

  private keyOf(node: BlockLike): string {
    const cached = this.keys.get(node);
    if (cached !== undefined) return cached;
    const key = JSON.stringify(node.toJSON());
    this.keys.set(node, key);
    return key;
  }

  /** The Markdown of the editor's current document. */
  serialize(doc: DocLike): string {
    const { references } = this.parsed;
    const used = new Set<number>();
    const parts: string[] = [];
    let previous: number | null = null;
    let previousType = "";
    doc.forEach((node) => {
      const type = node.type?.name ?? node.toJSON().type ?? "";
      const candidates = this.originals.get(this.keyOf(node)) ?? [];
      // The same block may appear twice; each original is used once, the
      // one right after the previous block first.
      const original =
        candidates.find((entry) => previous !== null && entry.index === previous + 1 && !used.has(entry.index)) ??
        candidates.find((entry) => !used.has(entry.index));
      if (original) {
        used.add(original.index);
        if (previous !== null && original.index === previous + 1) {
          // Neighbours in the original too: keep the gap between them as written.
          parts.push(this.source.slice(this.spans[previous].to, this.spans[original.index].from));
        } else if (parts.length) {
          parts.push(blockGap(previousType, type));
        }
        parts.push(original.source);
        previous = original.index;
        previousType = type;
        return;
      }
      let text = this.written.get(node);
      if (text === undefined) {
        text = serializeBlock(node.toJSON());
        this.written.set(node, text);
      }
      if (!text) return;
      if (parts.length) parts.push(blockGap(previousType, type));
      parts.push(text);
      previous = null;
      previousType = type;
    });
    let markdown = parts.join("").trim();
    // A reference definition dropped with its gap is written again at the end
    // while a block that still uses it keeps its original text.
    const missing = references.filter((line) => !markdown.includes(line));
    if (missing.length && used.size) markdown = `${markdown}\n\n${missing.join("\n")}`;
    return markdown;
  }
}
