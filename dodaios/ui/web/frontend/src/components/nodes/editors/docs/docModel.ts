/**
 * The docs spec (`{summary, markdown}`, `dodaios/nodes/kinds/docs.py`) and the
 * editor's document (a summary node, then the body's blocks), both ways.
 */
import type { JSONContent } from "@tiptap/core";

import { DocMarkdown, type BlockLike, type DocLike } from "./markdown/document";

export interface DocsSpec {
  summary: string;
  markdown: string;
}

/** Mirrors `MAX_SUMMARY_CHARS` / `MAX_BODY_CHARS` in `kinds/docs.py`. */
export const MAX_SUMMARY_CHARS = 600;
export const MAX_BODY_CHARS = 200_000;

/** The spec as the editor reads it; anything missing is empty. */
export function readSpec(spec: unknown): DocsSpec {
  const value = spec && typeof spec === "object" ? (spec as Record<string, unknown>) : {};
  return {
    summary: typeof value.summary === "string" ? value.summary : "",
    markdown: typeof value.markdown === "string" ? value.markdown : "",
  };
}

/** The summary as the server keeps it: one line, no control characters. */
export function cleanSummary(text: string): string {
  // eslint-disable-next-line no-control-regex
  return text.replace(/[\x00-\x1f\x7f]/g, " ").replace(/\s+/g, " ").trim().slice(0, MAX_SUMMARY_CHARS);
}

/** What the editor needs of a ProseMirror document. */
export interface EditorDocLike {
  childCount: number;
  child(index: number): BlockLike & { textContent: string };
  forEach(callback: (node: BlockLike, offset: number, index: number) => void): void;
}

/** The body: every top-level node after the summary. */
export function bodyOf(doc: EditorDocLike): DocLike {
  return {
    forEach(callback) {
      doc.forEach((node, _offset, index) => {
        if (index > 0) callback(node);
      });
    },
  };
}

/** One loaded spec: its Markdown reader/writer and the editor's starting content. */
export class DocSession {
  readonly markdown: DocMarkdown;

  constructor(readonly spec: DocsSpec) {
    this.markdown = new DocMarkdown(spec.markdown);
  }

  get content(): JSONContent {
    const summary: JSONContent = { type: "summary" };
    if (this.spec.summary) summary.content = [{ type: "text", text: cleanSummary(this.spec.summary) }];
    return { type: "doc", content: [summary, ...(this.markdown.doc.content ?? [])] };
  }

  /** Pair the editor's loaded nodes with their source (see `DocMarkdown.remember`). */
  remember(doc: EditorDocLike): void {
    this.markdown.remember(bodyOf(doc));
  }

  /** The spec the editor's document stands for now. */
  specOf(doc: EditorDocLike): DocsSpec {
    const summary = doc.childCount > 0 ? cleanSummary(doc.child(0).textContent) : "";
    return { summary, markdown: this.markdown.serialize(bodyOf(doc)) };
  }
}
