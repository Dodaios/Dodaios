import { useMemo } from "react";
import { isChartFenceLine } from "@/lib/chartSpec";
import { cn } from "@/lib/utils";
import { ChatMarkdown } from "./ChatMarkdown";
import { linkBareThreadCodes } from "./chatLinks";
import "./leadConversation.css";

/**
 * The assistant's reply in its one conversation, drawn the way a messenger
 * draws a message: one message is one bubble, however many paragraphs it
 * has. Until 2026-11-12 every paragraph was a bubble of its own, so a turn
 * of four messages filled the chat with a dozen (maintainer: "a thousand
 * messages for a simple question"). An answer that is really a document (it
 * has headings or a table, or it runs long) is a note: wider, with an edge.
 * A chart is the one thing that leaves the bubble: it is a card of its own
 * between the bubbles, the way a messenger shows a picture.
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

/** The person's own message in the conversation look, wherever it is drawn. */
export const OWN_BUBBLE = "jarvis-chat-out jarvis-chat-tinted lead-bubble-own max-w-[80%] px-4 py-2";

export type ReplyBlockKind = "para" | "list" | "code" | "chart" | "quote" | "heading" | "table" | "rule" | "reference";
export interface ReplyBlock { kind: ReplyBlockKind; text: string }
export interface ReplyPart {
  text: string;
  /** A document-like reply kept whole, drawn wider than a message. */
  note: boolean;
  /** A chart block on its own: drawn as its card, without a bubble around it. */
  chart?: true;
}

const FENCE = /^ {0,3}(`{3,}|~{3,})/;
const TABLE_RULE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function kindOf(lines: string[]): ReplyBlockKind {
  const first = lines[0];
  if (isChartFenceLine(first)) return "chart";
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

/** More paragraphs than this read as a text, not as a message. */
const MAX_MESSAGES = 5;
/** A reply longer than this is a text too, however it is laid out. */
const MAX_MESSAGE_CHARS = 1400;

/**
 * A reply as the one message it is. `note` says it reads as a document:
 * headings, a table or reference links, many paragraphs, or a long text.
 * Only a chart divides a message: the words before it, the chart, the words after.
 */
export function splitReply(markdown: string): ReplyPart[] {
  const text = markdown.trim();
  if (!text) return [];
  const blocks = replyBlocks(text);
  const charts = blocks.some((block) => block.kind === "chart");
  // A chart's numbers are not reading text: they make an answer neither long nor a document.
  const written = charts ? blocks.reduce((sum, block) => sum + (block.kind === "chart" ? 0 : block.text.length + 2), 0) : text.length;
  const paragraphs = blocks.filter((block) => block.kind === "para").length;
  const note = written > MAX_MESSAGE_CHARS || paragraphs > MAX_MESSAGES
    || blocks.some((block) => block.kind === "heading" || block.kind === "table" || block.kind === "reference");
  // A document stays whole, its chart inside it. In a message the chart stands between the bubbles.
  if (note || !charts) return [{ text, note }];
  const parts: ReplyPart[] = [];
  let run: string[] = [];
  const flush = () => {
    if (run.length) parts.push({ text: run.join("\n\n"), note: false });
    run = [];
  };
  for (const block of blocks) {
    if (block.kind !== "chart") { run.push(block.text); continue; }
    flush();
    parts.push({ text: block.text, note: false, chart: true });
  }
  flush();
  return parts;
}

/**
 * The reply as message bubbles. `live` marks a reply that is being written
 * right now: only then does a new bubble ease in, so a finished conversation
 * loads still.
 */
export function LeadReply({ text, live = false }: { text: string; live?: boolean }) {
  // A coding agent's code in the words ("#bddece") opens its thread.
  const parts = useMemo(() => splitReply(linkBareThreadCodes(text)), [text]);
  if (!parts.length) return null;
  return (
    <div data-testid="agent-text" className="lead-bubbles" data-live={live ? "" : undefined}>
      {parts.map((part, index) => (
        <div
          key={index}
          data-testid="lead-bubble"
          data-note={part.note ? "" : undefined}
          data-chart={part.chart ? "" : undefined}
          // A message is a grey bubble; a document stays a card with an edge; a chart brings its own card.
          className={cn("lead-bubble", part.chart ? "" : part.note ? "border border-border bg-card shadow-rim" : "jarvis-chat-in")}
        >
          <div className={REPLY_PROSE}>
            <ChatMarkdown text={part.text} />
          </div>
        </div>
      ))}
    </div>
  );
}
