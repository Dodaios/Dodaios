import type { ReactNode } from "react";
import type { TokenSpan } from "@/components/agentchat/typeahead";
import { splitMagicWords } from "@/lib/magicWords";

/**
 * `text` with the words the agent acts on drawn in their colours: commands
 * (a slash command, a skill, a picked file) in the command blue, and, when
 * `magic` is on, Claude Code's magic words ("ultrathink", "ultracode") in the
 * rainbow. Only colour changes — no weight, size or spacing — so the
 * composer can lay this under its textarea and every glyph lines up.
 */
export function MagicWordText({ text, magic = true, commands = [] }: {
  text: string;
  magic?: boolean;
  commands?: readonly TokenSpan[];
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
  let at = 0;
  for (const span of [...commands].sort((a, b) => a.start - b.start)) {
    if (span.start < at || span.end <= span.start) continue;
    plain(text.slice(at, span.start));
    parts.push(<span key={parts.length} className="text-info" data-testid="command-word">{text.slice(span.start, span.end)}</span>);
    at = span.end;
  }
  plain(text.slice(at));
  return <>{parts}</>;
}
