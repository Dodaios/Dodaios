/**
 * Other coding threads named inside a thread's message.
 *
 * A thread row dragged from the sidebar into a composer lands where it is
 * dropped as `@<short name>`, drawn as a pill with the agent's logo, so it
 * reads as part of the sentence. The box keeps plain text (the caret, undo
 * and the IME stay a textarea's); which thread each name means is kept here,
 * per composer. On send every name becomes a thread link,
 * `[<short name>](thread:<session id>)`: the bubble draws it as the thread's
 * link, and the backend tells the receiving agent who that thread is
 * (dodaios/agent_chat/thread_mentions.py).
 */

export interface ThreadMention {
  sessionId: string;
  /** The words after the `@`: a short form of the thread's title. */
  label: string;
  /** The thread's chat provider, for its agent's logo. */
  provider: string;
}

/** A mention's place in the box's text, `@` included. */
export interface MentionSpan {
  start: number;
  end: number;
  mention: ThreadMention;
}

/** About three words: the pill names the thread, it does not repeat its whole title. */
const LABEL_CHARS = 26;

/** The short name a dragged thread gets in the sentence. */
export function mentionLabel(title: string, taken: readonly string[] = []): string {
  const words = title.replace(/[[\]()@\n\r\t]/g, " ").split(/\s+/).filter(Boolean);
  let label = "";
  for (const word of words) {
    const next = label ? `${label} ${word}` : word;
    if (next.length > LABEL_CHARS && label) break;
    label = next;
  }
  if (label.length > LABEL_CHARS) label = `${label.slice(0, LABEL_CHARS - 1)}…`;
  label = label || "agent";
  if (!taken.includes(label)) return label;
  for (let n = 2; ; n++) {
    const numbered = `${label} ${n}`;
    if (!taken.includes(numbered)) return numbered;
  }
}

/** Every place in `text` where a mention still stands whole; edited ones are plain text again. */
export function mentionSpans(text: string, mentions: readonly ThreadMention[]): MentionSpan[] {
  const spans: MentionSpan[] = [];
  // The longest name first: "Login fix 2" must not be read as "Login fix".
  const byLength = [...mentions].sort((a, b) => b.label.length - a.label.length);
  const taken = (start: number, end: number) => spans.some((span) => start < span.end && end > span.start);
  for (const mention of byLength) {
    const token = `@${mention.label}`;
    for (let at = text.indexOf(token); at >= 0; at = text.indexOf(token, at + 1)) {
      const end = at + token.length;
      // A name runs on into more letters: "@Login fixes" is not "@Login fix".
      if (/[\p{L}\p{N}_]/u.test(text.charAt(end))) continue;
      if (!taken(at, end)) spans.push({ start: at, end, mention });
    }
  }
  return spans.sort((a, b) => a.start - b.start);
}

/** The text that is sent: every mention as a thread link. */
export function mentionsToLinks(text: string, mentions: readonly ThreadMention[]): string {
  let out = "";
  let at = 0;
  for (const span of mentionSpans(text, mentions)) {
    out += text.slice(at, span.start) + `[${span.mention.label}](thread:${span.mention.sessionId})`;
    at = span.end;
  }
  return out + text.slice(at);
}

const LINK = /\[([^[\]\n]{1,200})\]\(thread:([0-9A-Za-z-]{8,64})\)/g;

/**
 * A sent message coming back into the box (it did not go, or Escape took it
 * back): its thread links become mentions again.
 */
export function linksToMentions(
  text: string,
  providerOf: (sessionId: string) => string = () => "",
): { text: string; mentions: ThreadMention[] } {
  const mentions: ThreadMention[] = [];
  const back = text.replace(LINK, (_whole, label: string, sessionId: string) => {
    let mention = mentions.find((row) => row.sessionId === sessionId);
    if (!mention) {
      mention = { sessionId, label: mentionLabel(label, mentions.map((row) => row.label)), provider: providerOf(sessionId) };
      mentions.push(mention);
    }
    return `@${mention.label}`;
  });
  return { text: back, mentions };
}

/** A sent message split into its words and the thread links in it, for the bubble. */
export function splitThreadLinks(text: string): Array<{ text: string } | { label: string; sessionId: string }> {
  const parts: Array<{ text: string } | { label: string; sessionId: string }> = [];
  let at = 0;
  for (const match of text.matchAll(LINK)) {
    const start = match.index ?? 0;
    if (start > at) parts.push({ text: text.slice(at, start) });
    parts.push({ label: match[1], sessionId: match[2] });
    at = start + match[0].length;
  }
  if (at < text.length) parts.push({ text: text.slice(at) });
  return parts;
}

/**
 * Where a drop lands: the text offset `insertMention` puts the name at, and
 * the box's text with the name in, the caret after it. A space keeps the
 * name apart from the words on either side.
 */
export function insertMention(text: string, offset: number, label: string): { text: string; caret: number } {
  const at = Math.max(0, Math.min(offset, text.length));
  const before = text.slice(0, at);
  const after = text.slice(at);
  const lead = before && !/\s$/.test(before) ? " " : "";
  const tail = after.startsWith(" ") ? "" : " ";
  const inserted = `${lead}@${label}${tail}`;
  return { text: before + inserted + after, caret: before.length + inserted.length + (tail ? 0 : 1) };
}

/**
 * Where a drop at `offset` lands: never inside a word or a name. Inside a
 * name it moves to the name's end; inside a word to the nearer edge of it.
 */
export function outsideMentions(offset: number, spans: readonly MentionSpan[], text = ""): number {
  const inside = spans.find((span) => offset > span.start && offset < span.end);
  if (inside) return inside.end;
  const word = /\S/;
  if (!word.test(text.charAt(offset - 1)) || !word.test(text.charAt(offset))) return offset;
  let start = offset;
  while (start > 0 && word.test(text.charAt(start - 1))) start--;
  let end = offset;
  while (end < text.length && word.test(text.charAt(end))) end++;
  return offset - start <= end - offset ? start : end;
}

/**
 * The text offset under a point of the composer's mirror, the element that
 * draws the box's text in the same place as the textarea. Counted over its
 * text nodes; a pill's logo is an element without text, so it counts nothing.
 */
export function offsetInMirror(mirror: HTMLElement, x: number, y: number): number | null {
  const doc = mirror.ownerDocument;
  let node: Node | null = null;
  let offset = 0;
  const legacy = doc as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null };
  const modern = doc as Document & { caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null };
  if (typeof modern.caretPositionFromPoint === "function") {
    const position = modern.caretPositionFromPoint(x, y);
    if (position) { node = position.offsetNode; offset = position.offset; }
  } else if (typeof legacy.caretRangeFromPoint === "function") {
    const range = legacy.caretRangeFromPoint(x, y);
    if (range) { node = range.startContainer; offset = range.startOffset; }
  }
  if (!node || !mirror.contains(node)) return null;
  const walker = doc.createTreeWalker(mirror, NodeFilter.SHOW_TEXT);
  let count = 0;
  for (let text = walker.nextNode(); text; text = walker.nextNode()) {
    if (text === node) return count + offset;
    count += text.textContent?.length ?? 0;
  }
  // The point is on an element (a line's end, a pill's logo): before its children at `offset`.
  if (node.nodeType === Node.ELEMENT_NODE) {
    const range = doc.createRange();
    range.selectNodeContents(mirror);
    range.setEnd(node, Math.min(offset, node.childNodes.length));
    return range.toString().length;
  }
  return null;
}

/** Where the drop caret stands for `offset`, relative to `frame`, or null. */
export function caretRectInMirror(mirror: HTMLElement, frame: HTMLElement, offset: number): { left: number; top: number; height: number } | null {
  const doc = mirror.ownerDocument;
  const walker = doc.createTreeWalker(mirror, NodeFilter.SHOW_TEXT);
  let count = 0;
  for (let text = walker.nextNode(); text; text = walker.nextNode()) {
    const length = text.textContent?.length ?? 0;
    if (offset <= count + length) {
      const range = doc.createRange();
      range.setStart(text, offset - count);
      range.collapse(true);
      // A web view without range geometry (and jsdom) draws no caret; the drop still lands.
      if (typeof range.getClientRects !== "function") return null;
      const rect = range.getClientRects()[0] ?? range.getBoundingClientRect();
      const box = frame.getBoundingClientRect();
      if (!rect || (rect.height === 0 && rect.top === 0)) return null;
      return { left: rect.left - box.left, top: rect.top - box.top, height: rect.height || 20 };
    }
    count += length;
  }
  return null;
}
