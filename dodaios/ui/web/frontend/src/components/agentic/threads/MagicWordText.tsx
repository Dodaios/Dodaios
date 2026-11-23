import type { ReactNode } from "react";
import { Code2 } from "lucide-react";
import type { TokenSpan } from "@/components/agentchat/typeahead";
import { AgentMark } from "@/components/agentic/AgentMark";
import { splitMagicWords } from "@/lib/magicWords";
import type { MentionSpan } from "./threadMentions";

/** The coding agent behind a mentioned thread, for its logo. */
export type MentionAgent = (provider: string) => { agent: string; label: string } | undefined;

/**
 * Another thread named in the sentence: the agent's logo where the `@`
 * stands and the thread's title after it, on a quiet pill. The pill adds no
 * width — its padding is taken back by a negative margin and its edge is a
 * ring — so under the composer's textarea every glyph still lines up.
 */
export function ThreadMentionPill({ text, provider, agentOf }: { text: string; provider: string; agentOf?: MentionAgent }) {
  const mark = agentOf?.(provider);
  return <span data-testid="thread-mention"
    className="-mx-[3px] rounded-md bg-foreground/[0.07] px-[3px] text-foreground ring-1 ring-inset ring-foreground/15 [box-decoration-break:clone]">
    <span className="relative text-transparent">{text.slice(0, 1)}
      <span aria-hidden className="absolute inset-0 flex items-center justify-center">
        {mark
          ? <AgentMark agent={mark.agent} label={mark.label} variant="plain" size="sm" />
          : <Code2 className="h-3.5 w-3.5 text-muted-foreground" />}
      </span>
    </span>{text.slice(1)}
  </span>;
}

/**
 * `text` with the words the agent acts on drawn in their colours: commands
 * (a slash command, a skill, a picked file) in the command blue, and, when
 * `magic` is on, Claude Code's magic words ("ultrathink", "ultracode") in the
 * rainbow. Other threads named in it show as pills. Only colour and
 * decoration change — no weight, size or spacing — so the composer can lay
 * this under its textarea and every glyph lines up.
 */
export function MagicWordText({ text, magic = true, commands = [], mentions = [], agentOf }: {
  text: string;
  magic?: boolean;
  commands?: readonly TokenSpan[];
  mentions?: readonly MentionSpan[];
  agentOf?: MentionAgent;
}) {
  const parts: ReactNode[] = [];
  const plain = (stretch: string) => {
    if (!stretch) return;
    if (!magic) { parts.push(stretch); return; }
    for (const part of splitMagicWords(stretch)) {
      parts.push(part.magic
        ? <span key={parts.length} className="magic-word-rainbow" data-testid="magic-word">{part.text}</span>
        : part.text);
    }
  };
  const spans = [
    ...commands.map((span) => ({ start: span.start, end: span.end, mention: null })),
    ...mentions.map((span) => ({ start: span.start, end: span.end, mention: span.mention })),
  ].sort((a, b) => a.start - b.start);
  let at = 0;
  for (const span of spans) {
    if (span.start < at || span.end <= span.start) continue;
    plain(text.slice(at, span.start));
    const words = text.slice(span.start, span.end);
    parts.push(span.mention
      ? <ThreadMentionPill key={parts.length} text={words} provider={span.mention.provider} agentOf={agentOf} />
      : <span key={parts.length} className="text-info" data-testid="command-word">{words}</span>);
    at = span.end;
  }
  plain(text.slice(at));
  return <>{parts}</>;
}
