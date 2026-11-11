import { splitMagicWords } from "@/lib/magicWords";

/**
 * `text` with Claude Code's magic words ("ultrathink", "ultracode") drawn in
 * the rainbow. Only colour changes — no weight, size or spacing — so the
 * composer can lay this under its textarea and every glyph lines up.
 */
export function MagicWordText({ text }: { text: string }) {
  return <>
    {splitMagicWords(text).map((part, index) => part.magic
      ? <span key={index} className="magic-word-rainbow" data-testid="magic-word">{part.text}</span>
      : part.text)}
  </>;
}
