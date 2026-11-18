/**
 * The document's blocks as the live-build reveal reads them.
 *
 * A revision by an agent replaces the editor's content in one go. To show it
 * growing, the reveal must know which blocks are new and which are edited.
 * The editor remembers the blocks as they stood just before it draws a
 * revision (`rememberBlocks`); the reveal compares them with the blocks that
 * stand after (`diffBlocks`). Pure DOM reads; nothing here changes the page.
 *
 * A block here is the smallest piece that arrives whole: a paragraph, a
 * heading, one list item, one table row, a callout, a picture or chart.
 */

export type BlockKind = "text" | "block" | "media";

export interface DocBlock {
  kind: BlockKind;
  tag: string;
  /** The text as the editor holds it (offsets into it are character offsets). */
  raw: string;
  /** The same text with its whitespace collapsed. */
  text: string;
  /** Equal keys are the same block. */
  key: string;
}

export interface LiveBlock extends DocBlock {
  el: Element;
}

export type BlockChange =
  | { type: "new"; block: LiveBlock }
  | { type: "edit"; block: LiveBlock; before: DocBlock };

const remembered = new WeakMap<Element, DocBlock[]>();

const MEDIA = "img, svg, canvas, [data-doc-chart], [data-doc-metrics]";

function norm(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function make(el: Element, kind: BlockKind, tag: string): LiveBlock {
  const raw = el.textContent ?? "";
  const text = norm(raw);
  const src = kind === "media" ? (el.querySelector("img")?.getAttribute("src") ?? "") : "";
  return { el, kind, tag, raw, text, key: `${tag}|${src}|${text}` };
}

/** The editor's content element inside a body, or null. */
export function editorOf(root: Element): Element | null {
  return root.matches(".ProseMirror") ? root : root.querySelector(".ProseMirror");
}

/** The blocks of the editor's content, in reading order. */
export function blocksOf(content: Element): LiveBlock[] {
  const out: LiveBlock[] = [];
  for (const child of content.children) {
    const tag = child.tagName.toLowerCase();
    if (child.hasAttribute("data-doc-summary")) out.push(make(child, "block", "summary"));
    else if (child.matches(MEDIA) || child.querySelector(MEDIA)) out.push(make(child, "media", "media"));
    else if (tag === "ul" || tag === "ol") {
      for (const item of child.querySelectorAll("li")) out.push(make(item, "block", "li"));
    } else if (tag === "table" || child.querySelector("table")) {
      for (const row of child.querySelectorAll("tr")) out.push(make(row, "block", "tr"));
    } else if (tag === "p") out.push(make(child, "text", "p"));
    else out.push(make(child, "block", tag));
  }
  return out.filter((b) => b.kind === "media" || b.text !== "" || b.tag === "hr");
}

/** Remember the blocks that stand now: call just before the editor draws a revision. */
export function rememberBlocks(content: Element): void {
  remembered.set(
    content,
    blocksOf(content).map(({ el: _el, ...block }) => block),
  );
}

/** The blocks that stood before the last revision, or null when none was remembered. */
export function blocksBefore(content: Element): DocBlock[] | null {
  return remembered.get(content) ?? null;
}

/** How much of two texts is shared at the start and at the end. */
export function sharedEdges(before: string, after: string): { head: number; tail: number } {
  const limit = Math.min(before.length, after.length);
  let head = 0;
  while (head < limit && before[head] === after[head]) head += 1;
  let tail = 0;
  while (tail < limit - head && before[before.length - 1 - tail] === after[after.length - 1 - tail]) tail += 1;
  return { head, tail };
}

/** Is `after` an edit of `before` (same kind of block, most of it kept)? */
function related(before: DocBlock, after: DocBlock): boolean {
  if (before.tag !== after.tag || before.kind === "media") return false;
  const { head, tail } = sharedEdges(before.raw, after.raw);
  const least = Math.min(before.raw.length, after.raw.length);
  return least > 0 && head + tail >= Math.max(8, Math.floor(least * 0.3));
}

const MAX_CELLS = 250_000;

/** Which blocks of `after` stand for a block of `before` unchanged: pairs of indices. */
function matches(before: readonly DocBlock[], after: readonly DocBlock[]): Array<[number, number]> {
  const n = before.length;
  const m = after.length;
  const out: Array<[number, number]> = [];
  if (n * m > MAX_CELLS) {
    // Too many to compare all pairs: keep what is shared at both ends.
    let head = 0;
    while (head < n && head < m && before[head].key === after[head].key) {
      out.push([head, head]);
      head += 1;
    }
    let tail = 0;
    while (tail < n - head && tail < m - head && before[n - 1 - tail].key === after[m - 1 - tail].key) tail += 1;
    for (let k = tail; k > 0; k -= 1) out.push([n - k, m - k]);
    return out;
  }
  const table: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      table[i][j] = before[i].key === after[j].key ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (before[i].key === after[j].key) {
      out.push([i, j]);
      i += 1;
      j += 1;
    } else if (table[i + 1][j] >= table[i][j + 1]) i += 1;
    else j += 1;
  }
  return out;
}

/**
 * What a revision changed, in reading order: each block that is not in the
 * old document is `new`, or an `edit` when it is the old block with some
 * words changed.
 */
export function diffBlocks(before: readonly DocBlock[], after: readonly LiveBlock[]): BlockChange[] {
  const kept = matches(before, after);
  const changes: BlockChange[] = [];
  let prevAt = 0;
  let nextAt = 0;
  const gap = (prevEnd: number, nextEnd: number) => {
    const old = before.slice(prevAt, prevEnd);
    const used = new Set<number>();
    for (let j = nextAt; j < nextEnd; j += 1) {
      const block = after[j];
      const found = old.findIndex((b, k) => !used.has(k) && related(b, block));
      if (found >= 0) {
        used.add(found);
        changes.push({ type: "edit", block, before: old[found] });
      } else changes.push({ type: "new", block });
    }
  };
  for (const [i, j] of kept) {
    gap(i, j);
    prevAt = i + 1;
    nextAt = j + 1;
  }
  gap(before.length, after.length);
  return changes;
}

/** The part of a text an edit rewrote, widened to whole words. */
export function editedSpan(before: string, after: string): { from: number; to: number; removed: string } {
  const { head, tail } = sharedEdges(before, after);
  let from = head;
  // Back to the start of the word the change starts in.
  while (from > 0 && !/\s/.test(after[from - 1] ?? " ")) from -= 1;
  const toRaw = after.length - tail;
  let to = toRaw;
  while (to < after.length && !/\s/.test(after[to] ?? " ")) to += 1;
  const cut = after.length - to;
  const removed = before.slice(from, Math.max(from, before.length - cut));
  return { from, to, removed };
}
