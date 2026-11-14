/**
 * The composer's typeahead, the pure part: which token under the caret opens
 * a list, and how a pick lands back in the text.
 *
 * Three gestures, the ones every coding CLI has: `/` for skills and commands,
 * `@` for files (and Claude Code's subagents), `$` for Codex's explicit skill
 * mention. In the front page's Jarvis chat `@` names the user's agents and
 * the connected plugins and tools instead — a picked tool lands as the same
 * brand chip the Add menu inserts. Which of them a chat honours is the backend's word — the catalog
 * row's `typeahead` list, decided from the seat's runner — so the box never
 * opens a `/` list for a seat that would read the slash as plain text.
 */

import { choiceTag } from "./composerChips";
import { browseToolRows, type ToolChoice } from "./toolChoices";

export interface TypeaheadItem {
  /** What lands after the trigger character — `commit`, `github:issue`, `src/app.py`. */
  value: string;
  label: string;
  hint: string;
  /** skill | command | agent | file | folder */
  kind: string;
  /** cli | project | account | plugins | jarvis | agents | teammates | files | tool:<category> */
  group: string;
  /** What a command takes after its name, in the CLI's own words (`[on|off]`). */
  argument_hint?: string;
  /** Other names the CLI accepts for the same command (`/cost` for `/usage`). */
  aliases?: string[];
  /** A plugin or tool from the composer's catalog: the pick becomes its chip. */
  choice?: ToolChoice;
}

export interface TypeaheadResponse {
  trigger: string;
  items: TypeaheadItem[];
  truncated: boolean;
}

export interface ActiveToken {
  trigger: string;
  /** The text typed after the trigger, up to the caret. */
  query: string;
  /** Index of the trigger character. */
  start: number;
  /** The caret. */
  end: number;
}

/**
 * The token the caret sits in, when a trigger character opens it.
 *
 * A token runs from the last whitespace before the caret to the caret. `@`
 * and `$` open anywhere a word starts; `/` only at the very start of the
 * message, because that is the only place a CLI reads a slash command — a
 * `/` inside a path or a URL must not throw a list over the sentence. An
 * address like `a@b` never opens: the token's first character is `a`.
 */
export function activeToken(
  text: string,
  caret: number,
  triggers: readonly string[],
): ActiveToken | null {
  if (!triggers.length) return null;
  const at = Math.max(0, Math.min(caret, text.length));
  let start = at;
  while (start > 0 && !/\s/.test(text[start - 1])) start -= 1;
  const trigger = text[start];
  if (!trigger || !triggers.includes(trigger)) return null;
  if (trigger === "/" && text.slice(0, start).trim() !== "") return null;
  return { trigger, query: text.slice(start + 1, at), start, end: at };
}

/**
 * The text with `item` written over the token, and where the caret goes.
 *
 * A file or a name is followed by one space so typing continues past it. A
 * folder is not: it ends in `/`, and the next keystroke should narrow the
 * list to what is inside it, the way a shell completes a path.
 */
export function applyPick(
  text: string,
  token: ActiveToken,
  item: TypeaheadItem,
): { text: string; caret: number } {
  const trailing = item.kind === "folder" ? "" : " ";
  const inserted = `${token.trigger}${item.value}${trailing}`;
  const next = text.slice(0, token.start) + inserted + text.slice(token.end);
  return { text: next, caret: token.start + inserted.length };
}

/**
 * A name that starts with the query first, then an alias that does, then a
 * name that contains it, then a description that does.
 *
 * Short queries stay strict, the way a CLI's own list does: one letter matches
 * the start of a name only, and a description counts from three letters up,
 * because two letters sit inside almost every description.
 */
export function filterItems(items: readonly TypeaheadItem[], query: string): TypeaheadItem[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...items];
  const ranked: { score: number; index: number; item: TypeaheadItem }[] = [];
  items.forEach((item, index) => {
    const value = item.value.toLowerCase();
    const label = item.label.toLowerCase();
    let score: number;
    if (value.startsWith(q) || label.startsWith(q)) score = 0;
    else if (item.aliases?.some((alias) => alias.toLowerCase().startsWith(q))) score = 1;
    else if (q.length < 2) return;
    else if (value.includes(q) || label.includes(q)) score = 2;
    else if (q.length >= 3 && item.hint.toLowerCase().includes(q)) score = 3;
    else return;
    ranked.push({ score, index, item });
  });
  ranked.sort((a, b) => a.score - b.score || a.index - b.index);
  return ranked.map((r) => r.item);
}

/** A stretch of the composer's text, in characters. */
export interface TokenSpan {
  start: number;
  end: number;
}

/** What the seat is known to understand: these words are drawn in the command colour. */
export interface KnownTokens {
  /** The names and aliases of the seat's `/` list. */
  slash: ReadonlySet<string>;
  /** The names of the seat's `$` list. */
  skills: ReadonlySet<string>;
}

/** The names a fetched `/` or `$` list answers to, lower-cased. */
export function tokenNames(items: readonly TypeaheadItem[]): Set<string> {
  const names = new Set<string>();
  for (const item of items) {
    names.add(item.value.toLowerCase());
    for (const alias of item.aliases ?? []) names.add(alias.toLowerCase());
  }
  return names;
}

/**
 * Paths and names picked from an `@` list. A picked one is a real file, folder
 * or agent, so it keeps the command colour; a hand-typed `@word` is not checked
 * against the disk and stays plain. Kept for the life of the page, so a draft
 * that comes back after a thread switch still knows its mentions.
 */
const pickedMentions = new Set<string>();

export function rememberMention(value: string): void {
  if (value) pickedMentions.add(value);
}

const TRAILING_PUNCTUATION = /[.,;:!?)\]]+$/;

/**
 * The words of `text` the seat will act on: the slash command that opens the
 * message, every `$skill` it knows and every picked `@mention`.
 *
 * Only a known name counts, as in a coding CLI: `/goal` turns blue, `/gaol`
 * does not, which is how a typo shows before the message is sent. A slash
 * counts only as the first thing of the message, the one place a CLI reads it.
 */
export function knownTokenSpans(
  text: string,
  triggers: readonly string[],
  known: KnownTokens,
): TokenSpan[] {
  const spans: TokenSpan[] = [];
  if (triggers.includes("/")) {
    const command = /^(\s*)\/(\S+)/.exec(text);
    if (command && known.slash.has(command[2].toLowerCase())) {
      spans.push({ start: command[1].length, end: command[1].length + 1 + command[2].length });
    }
  }
  const words = /(^|\s)([@$])(\S+)/g;
  for (let match = words.exec(text); match; match = words.exec(text)) {
    const trigger = match[2];
    if (!triggers.includes(trigger)) continue;
    const start = match.index + match[1].length;
    const raw = match[3];
    const bare = raw.replace(TRAILING_PUNCTUATION, "");
    const name = [raw, bare].find((candidate) =>
      trigger === "$" ? known.skills.has(candidate.toLowerCase()) : pickedMentions.has(candidate),
    );
    if (name) spans.push({ start, end: start + 1 + name.length });
  }
  return spans.sort((a, b) => a.start - b.start);
}

/**
 * Catalog rows (`/api/agent-chat/tools`) as `@` rows, in the Add menu's order
 * and with its rules: connectors, not the skills behind them, and nothing
 * disconnected until someone types a name.
 */
export function toolTypeaheadItems(rows: readonly ToolChoice[], query: string): TypeaheadItem[] {
  return browseToolRows([...rows], query).map((row) => ({
    value: choiceTag(row),
    label: row.label,
    hint: row.description,
    kind: "tool",
    group: `tool:${row.category}`,
    choice: row,
  }));
}

/** Triggers whose list is read once and filtered here; `@` asks the backend per keystroke. */
export function isStaticTrigger(trigger: string): boolean {
  return trigger === "/" || trigger === "$";
}

/** Items in the order they arrived, cut into runs of one group for headings. */
export function groupRuns(items: readonly TypeaheadItem[]): { group: string; items: TypeaheadItem[] }[] {
  const runs: { group: string; items: TypeaheadItem[] }[] = [];
  for (const item of items) {
    const last = runs[runs.length - 1];
    if (last && last.group === item.group) last.items.push(item);
    else runs.push({ group: item.group, items: [item] });
  }
  return runs;
}
