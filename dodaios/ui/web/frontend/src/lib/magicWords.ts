// Claude Code's magic words: typed in a prompt, they change how the turn runs
// ("ultrathink" asks for deeper reasoning on this turn, "ultracode" opts the
// turn into multi-agent workflow orchestration). The CLI reads them from the
// prompt text itself, so the composer only has to show that they were
// recognised, in the same rainbow Claude Code's own input uses.

/** Whole words only, any case: the CLI's own test is `/\bultrathink\b/i`. */
const WORDS = String.raw`\b(ultrathink|ultracode)\b`;

/** The runners whose CLI acts on the words (Claude Code itself). */
export const MAGIC_WORD_RUNNERS: ReadonlySet<string> = new Set(["claude-cli"]);

export interface TextPart {
  text: string;
  magic: boolean;
}

/** Whether `text` holds a magic word. */
export function hasMagicWord(text: string): boolean {
  return new RegExp(WORDS, "i").test(text);
}

/** `text` cut into plain stretches and magic words, in order; joined they give `text` back. */
export function splitMagicWords(text: string): TextPart[] {
  const parts: TextPart[] = [];
  let at = 0;
  for (const match of text.matchAll(new RegExp(WORDS, "gi"))) {
    const start = match.index ?? 0;
    if (start > at) parts.push({ text: text.slice(at, start), magic: false });
    parts.push({ text: match[0], magic: true });
    at = start + match[0].length;
  }
  if (at < text.length) parts.push({ text: text.slice(at), magic: false });
  return parts;
}
