/**
 * The little Markdown a slide's line may carry (**bold**, *italic*, `code`,
 * [links](https://…)), drawn as HTML exactly as `dodaios/nodes/shell.py`
 * draws it: `inline` and `lines` there, step for step.
 *
 * Why HTML text and not React elements: the editor's slide must look like the
 * page, and the surest way is to produce the very same markup the server
 * produces. The algorithm is the server's and it is safe the same way:
 * everything is escaped FIRST, the marks are then read from the escaped
 * text, and a link keeps only a web or mail address, so no tag or attribute
 * from a spec ever survives. The result only ever holds `<code>`, `<strong>`,
 * `<em>`, `<br>` and `<a href="https…|mailto:…" rel="noopener noreferrer">`.
 */

const LINK_SCHEMES = ["https://", "http://", "mailto:"];

/** `html.escape(text, quote=False)`. */
export function esc(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** `html.escape(text, quote=True)`. */
export function attr(value: string): string {
  return esc(value).replace(/"/g, "&quot;").replace(/'/g, "&#x27;");
}

/** `shell.clean`: whitespace collapsed, clipped to `limit`. */
export function clean(value: string, limit: number): string {
  return value.split(/\s+/).filter(Boolean).join(" ").slice(0, limit).trimEnd();
}

function safeLink(value: string): string {
  const href = value.trim();
  const lower = href.toLowerCase();
  return LINK_SCHEMES.some((scheme) => lower.startsWith(scheme)) && href.length <= 2_000 ? href : "";
}

const CODE_RE = /`([^`\n]+)`/g;
const BOLD_RE = /\*\*(?=\S)(.+?)(?<=\S)\*\*/g;
// Python's \w is Unicode-aware; JavaScript's is not, hence the classes.
const ITALIC_RE = /(?<![\p{L}\p{N}_*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\p{L}\p{N}_*])/gu;
const LINK_RE = /\[([^\]\n]+)\]\(([^)\s]+)\)/g;

/** One line of text as HTML, with bold, italic, code and links (`shell.inline`). */
export function inlineHtml(value: string, limit = 2_000): string {
  // NUL marks the held spans below; a spec must not be able to forge one.
  let text = esc(clean(value, limit).replace(/\0/g, ""));
  const held: string[] = [];
  const hold = (html: string) => {
    held.push(html);
    return `\0${held.length - 1}\0`;
  };
  text = text.replace(CODE_RE, (_m, code: string) => hold(`<code>${code}</code>`));
  text = text.replace(LINK_RE, (_m, label: string, address: string) => {
    const href = safeLink(address.replace(/&amp;/g, "&"));
    if (!href) return label;
    // The address is held back so the marks below never read inside it.
    return `${hold(`<a href="${attr(href)}" rel="noopener noreferrer">`)}${label}${hold("</a>")}`;
  });
  text = text.replace(BOLD_RE, "<strong>$1</strong>");
  text = text.replace(ITALIC_RE, "<em>$1</em>");
  return text.replace(/\0(\d+)\0/g, (_m, index: string) => held[Number(index)]);
}

/** Several lines as HTML: inline marks, line breaks kept (`shell.lines`). */
export function linesHtml(value: string, limit = 4_000): string {
  const block = value.replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim().slice(0, limit);
  return block
    .split("\n")
    .map((part) => inlineHtml(part))
    .join("<br>");
}
