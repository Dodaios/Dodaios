/**
 * Markdown emphasis taken off a line of text, and nothing else.
 *
 * Previews, titles and status lines show a message as one plain line. Their
 * old filters dropped every `*`, `_` and backtick, which also took the
 * underscores out of file names and identifiers ("qa_note.txt" became
 * "qanote.txt" or "qa note.txt"). Here a marker goes only when it opens and
 * closes emphasis: at a word's edge, never inside a word, and a dunder name
 * ("__init__.py", "__main__") keeps its underscores.
 */

/** `text` without code ticks, bold, italics and strike marks; underscores inside words stay. */
export function stripInlineMarks(text: string): string {
  return text
    .replace(/`+/g, "")
    .replace(/(^|[^\w*])(\*\*|__)(?=\S)(.+?)(?<=\S)\2(?![\w*])/g,
      (whole: string, lead: string, mark: string, inner: string) =>
        (mark === "__" && /^\w+$/.test(inner) ? whole : lead + inner))
    .replace(/(^|[^\w*])\*(?=[^\s*])([^*\n]*?)(?<=[^\s*])\*(?![\w*])/g, "$1$2")
    .replace(/(^|[^\w])_(?=[^\s_])([^_\n]*?)(?<=[^\s_])_(?!\w)/g, "$1$2")
    .replace(/~~(?=\S)(.+?)(?<=\S)~~/g, "$1");
}

/**
 * A Markdown message as one plain line: code fences, heading, quote and list
 * marks and inline emphasis gone, whitespace collapsed; file names stay whole.
 */
export function flattenMarks(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .split(/\r?\n/)
    .map((line) => stripInlineMarks(line.replace(/^\s*(?:[#>]+|[-*+]\s)\s*/, "")).replace(/\|/g, " "))
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}
