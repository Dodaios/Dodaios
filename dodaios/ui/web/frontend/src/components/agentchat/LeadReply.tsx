import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { ChatMarkdown } from "./ChatMarkdown";
import "./leadConversation.css";

/**
 * The assistant's reply in its one conversation, written the way a person
 * writes in a messenger: a short answer arrives as a few short messages, one
 * per paragraph, instead of one block of text. An answer that is really a
 * document (it has headings or a table, or it runs long) stays in one piece
 * as a note, because cutting a document into bubbles makes it harder to read.
 */

/** Reading type shared by every reply on the front page. */
export const REPLY_PROSE = cn(
  // Compact reading size: headings stay close to body size and are set
  // apart by weight and spacing, not by scale.
  "prose prose-neutral max-w-none text-[15px] leading-[25px] text-foreground dark:prose-invert dark:text-foreground [overflow-wrap:anywhere]",
  "[&>div>:first-child]:mt-0 [&>div>:last-child]:mb-0",
  "prose-p:my-2.5 prose-p:text-foreground prose-li:text-foreground prose-strong:text-foreground-strong",
  "prose-headings:mb-1.5 prose-headings:mt-5 prose-headings:font-semibold prose-headings:tracking-normal prose-headings:text-foreground-strong",
  "prose-h1:text-[17px] prose-h1:leading-[25px] prose-h2:text-[16px] prose-h2:leading-[25px] prose-h3:text-[15px] prose-h3:leading-[25px] prose-h4:text-[15px]",
  "prose-a:text-foreground-strong prose-a:underline prose-a:decoration-border-strong prose-a:underline-offset-2",
  "prose-code:rounded prose-code:bg-secondary prose-code:px-1 prose-code:py-0.5 prose-code:font-mono prose-code:text-[0.85em] prose-code:font-normal prose-code:before:hidden prose-code:after:hidden",
  "prose-pre:my-2.5 prose-pre:bg-card prose-pre:text-[13px] prose-pre:leading-[20px]",
  "prose-li:my-1 prose-ul:my-2.5 prose-ol:my-2.5 prose-ul:pl-5 prose-ol:pl-5 prose-li:pl-1",
  "prose-hr:my-5",
  "prose-table:my-3 prose-table:text-[14px] prose-table:leading-[21px]",
  "prose-thead:text-foreground-strong prose-th:text-foreground-strong prose-td:text-foreground",
);

export type ReplyBlockKind = "para" | "list" | "code" | "quote" | "heading" | "table" | "rule" | "reference";
export interface ReplyBlock { kind: ReplyBlockKind; text: string }
export interface ReplyPart {
  text: string;
  /** A document-like reply kept whole, drawn wider than a message. */
  note: boolean;
}

const FENCE = /^ {0,3}(`{3,}|~{3,})/;
const TABLE_RULE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function kindOf(lines: string[]): ReplyBlockKind {
  const first = lines[0];
  if (lines.some((line) => FENCE.test(line))) return "code";
  if (/^ {0,3}#{1,6}\s/.test(first)) return "heading";
  if (lines.length > 1 && lines[0].includes("|") && TABLE_RULE.test(lines[1])) return "table";
  if (/^ {0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(first)) return "rule";
  if (/^ {0,3}\[[^\]]+\]:\s/.test(first)) return "reference";
  if (/^ {0,3}>/.test(first)) return "quote";
  // A line indented under a list item continues that item.
  if (/^\s*(?:[-*+]|\d+[.)])\s+/.test(first) || /^(?: {2,}|\t)\S/.test(first)) return "list";
  return "para";
}

/** A reply's top-level Markdown blocks: split at blank lines, never inside a code fence. */
export function replyBlocks(markdown: string): ReplyBlock[] {
  const blocks: ReplyBlock[] = [];
  let lines: string[] = [];
  let fence: string | null = null;
  const flush = () => {
    if (lines.length) blocks.push({ kind: kindOf(lines), text: lines.join("\n") });
    lines = [];
  };
  for (const line of markdown.replace(/\r\n?/g, "\n").split("\n")) {
    const mark = FENCE.exec(line)?.[1];
    if (fence) {
      lines.push(line);
      if (mark && mark[0] === fence[0] && mark.length >= fence.length && line.trim() === mark) fence = null;
      continue;
    }
    if (mark) fence = mark;
    if (!line.trim()) flush();
    else lines.push(line);
  }
  flush();
  return blocks;
}

/** More paragraphs than this read as a text, not as messages. */
const MAX_MESSAGES = 5;
/** A reply longer than this is a text too, however it is laid out. */
const MAX_MESSAGE_CHARS = 1400;

/**
 * A reply as the messages it is sent in. Each paragraph is a message; a
 * list, quote or code block belongs to the paragraph that introduces it.
 */
export function splitReply(markdown: string): ReplyPart[] {
  const text = markdown.trim();
  if (!text) return [];
  const blocks = replyBlocks(text);
  const whole = [{ text, note: true }];
  // Headings and tables make a document; reference links only resolve inside one piece.
  if (text.length > MAX_MESSAGE_CHARS || blocks.some((block) => block.kind === "heading" || block.kind === "table" || block.kind === "reference")) return whole;
  const parts: ReplyPart[] = [];
  for (const block of blocks) {
    const last = parts[parts.length - 1];
    if (last && block.kind !== "para") last.text += `\n\n${block.text}`;
    else parts.push({ text: block.text, note: false });
  }
  return parts.length > MAX_MESSAGES ? whole : parts;
}

/**
 * The reply as message bubbles. `live` marks a reply that is being written
 * right now: only then does a new bubble ease in, so a finished conversation
 * loads still.
 */
export function LeadReply({ text, live = false }: { text: string; live?: boolean }) {
  const parts = useMemo(() => splitReply(text), [text]);
  if (!parts.length) return null;
  return (
    <div data-testid="agent-text" className="lead-bubbles" data-live={live ? "" : undefined}>
      {parts.map((part, index) => (
        <div
          key={index}
          data-testid="lead-bubble"
          data-note={part.note ? "" : undefined}
          className="lead-bubble border border-border bg-card shadow-rim"
        >
          <div className={REPLY_PROSE}>
            <ChatMarkdown text={part.text} />
          </div>
        </div>
      ))}
    </div>
  );
}
