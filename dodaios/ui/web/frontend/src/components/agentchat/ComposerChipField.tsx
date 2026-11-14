import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  type ClipboardEvent,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import { cn } from "@/lib/utils";
import { choiceLookup, choiceToken } from "./composerChips";
import type { ToolChoice } from "./toolChoices";
import { toolIdentity, toolIdentityStyle } from "./toolIdentity";
import type { TokenSpan } from "./typeahead";
import "./toolIdentity.css";

export interface ComposerDraft {
  text: string;
  choices: ToolChoice[];
  caret: number;
}

export interface ComposerChipFieldHandle {
  insertChip: (row: ToolChoice) => void;
  insertText: (text: string) => void;
  hydrate: (text: string, choices?: ToolChoice[]) => void;
  getDraft: () => ComposerDraft;
  clear: () => void;
  focus: () => void;
  setText: (text: string) => void;
}

function readChoice(node: HTMLElement): ToolChoice | null {
  const raw = node.dataset.choice;
  if (!raw) return null;
  try {
    return JSON.parse(decodeURIComponent(raw)) as ToolChoice;
  } catch {
    return null;
  }
}

function createChipEl(row: ToolChoice): HTMLSpanElement {
  const identity = toolIdentity(row);
  const el = document.createElement("span");
  el.contentEditable = "false";
  el.className = "tool-identity tool-choice-chip";
  el.dataset.inline = "true";
  el.dataset.toolChip = "true";
  el.dataset.toolId = row.id;
  el.dataset.brand = identity.key ?? row.category;
  el.dataset.choice = encodeURIComponent(JSON.stringify(row));
  el.title = row.description || row.label;
  Object.assign(el.style, toolIdentityStyle(row));

  const icon = document.createElement("span");
  icon.className = "tool-choice-icon";
  icon.style.width = "16px";
  icon.style.height = "16px";
  icon.setAttribute("aria-hidden", "true");
  if (identity.logo && identity.mark === "mono") {
    const mask = document.createElement("span");
    mask.className = "tool-choice-mask";
    mask.style.setProperty("--tool-logo", `url("${identity.logo}")`);
    icon.appendChild(mask);
  } else if (identity.logo) {
    const img = document.createElement("img");
    img.src = identity.logo;
    img.alt = "";
    icon.appendChild(img);
  }
  const label = document.createElement("span");
  label.textContent = row.label;
  el.append(icon, label);
  return el;
}

/** One text node of the field and where its characters sit in the draft's text. */
interface TextRun {
  node: Text;
  start: number;
}

function serialize(root: HTMLElement, runs?: TextRun[]): ComposerDraft {
  const choices: ToolChoice[] = [];
  let text = "";
  const sel = root.ownerDocument.getSelection();
  let caret = 0;
  let seenCaret = false;

  const walk = (node: Node) => {
    if (!seenCaret && sel && sel.anchorNode === node) {
      caret = text.length + (node.nodeType === Node.TEXT_NODE ? sel.anchorOffset : 0);
      seenCaret = true;
    }
    if (node.nodeType === Node.TEXT_NODE) {
      runs?.push({ node: node as Text, start: text.length });
      text += node.textContent ?? "";
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const el = node as HTMLElement;
    if (el.dataset.toolChip) {
      const row = readChoice(el);
      if (row) {
        const token = `${choiceToken(row)}`;
        if (!seenCaret && sel && el.contains(sel.anchorNode)) {
          caret = text.length + token.length;
          seenCaret = true;
        }
        text += token;
        choices.push(row);
      }
      return;
    }
    if (el.tagName === "BR") {
      text += "\n";
      return;
    }
    if (el.tagName === "DIV" || el.tagName === "P") {
      if (text && !text.endsWith("\n")) text += "\n";
    }
    for (const child of Array.from(node.childNodes)) walk(child);
  };
  for (const child of Array.from(root.childNodes)) walk(child);
  if (!seenCaret) caret = text.length;
  return { text, choices, caret };
}

/**
 * The words the seat will act on (a slash command, a skill, a picked mention)
 * are drawn in the command colour, as a coding CLI colours them in its prompt.
 *
 * Painted with the CSS Custom Highlight API: ranges over the existing text
 * nodes, styled by `::highlight(composer-token)`. Nothing is wrapped or
 * inserted, so the caret, the selection, undo and the IME see plain text. One
 * registry entry serves every text box on the page, hence the shared map. A
 * web view without the API (WebKit before 17.2) shows the words uncoloured.
 */
const TOKEN_HIGHLIGHT = "composer-token";
const paintedTokens = new Map<HTMLElement, Range[]>();

function paintTokens(root: HTMLElement, spans: readonly TokenSpan[] | null, runs: readonly TextRun[]) {
  const registry = typeof CSS === "undefined" ? undefined : CSS.highlights;
  if (!registry || typeof Highlight === "undefined") return;
  const ranges: Range[] = [];
  for (const span of spans ?? []) {
    for (const run of runs) {
      const from = Math.max(span.start, run.start);
      const to = Math.min(span.end, run.start + run.node.data.length);
      if (from >= to) continue;
      const range = root.ownerDocument.createRange();
      range.setStart(run.node, from - run.start);
      range.setEnd(run.node, to - run.start);
      ranges.push(range);
    }
  }
  if (ranges.length) paintedTokens.set(root, ranges);
  else if (!paintedTokens.delete(root)) return;
  const all = [...paintedTokens.values()].flat();
  if (all.length) registry.set(TOKEN_HIGHLIGHT, new Highlight(...all));
  else registry.delete(TOKEN_HIGHLIGHT);
}

/** Read the field once: its draft, with the known words painted on the way. */
function readPainted(root: HTMLElement, tokenSpans?: (text: string) => TokenSpan[]): ComposerDraft {
  const runs: TextRun[] = [];
  const draft = serialize(root, runs);
  paintTokens(root, tokenSpans?.(draft.text) ?? null, runs);
  return draft;
}

function rangeAtEnd(root: HTMLElement): Range {
  const range = root.ownerDocument.createRange();
  range.selectNodeContents(root);
  range.collapse(false);
  return range;
}

function liveRange(root: HTMLElement): Range | null {
  const sel = root.ownerDocument.getSelection();
  if (sel && sel.rangeCount && sel.anchorNode && root.contains(sel.anchorNode)) {
    return sel.getRangeAt(0);
  }
  return null;
}

/** Park inside a text node. After a non-editable chip, setStartAfter jumps to the start. */
function caretInText(node: Text, offset: number) {
  const pos = Math.max(0, Math.min(offset, node.data.length));
  const range = node.ownerDocument.createRange();
  range.setStart(node, pos);
  range.collapse(true);
  const sel = node.ownerDocument.getSelection();
  sel?.removeAllRanges();
  sel?.addRange(range);
  return range;
}

function hydrateRoot(root: HTMLElement, text: string, choices: ToolChoice[] = []) {
  root.innerHTML = "";
  const tags = choiceLookup(choices);
  const chunks = text.split(/(@[^\s@]+)/g);
  const doc = root.ownerDocument;
  for (const chunk of chunks) {
    if (!chunk) continue;
    const name = chunk.startsWith("@") ? chunk.slice(1).toLowerCase() : "";
    const row = name ? tags.get(name) : undefined;
    if (row) root.appendChild(createChipEl(row));
    else root.appendChild(doc.createTextNode(chunk));
  }
}

export const ComposerChipField = forwardRef<
  ComposerChipFieldHandle,
  {
    placeholder: string;
    disabled?: boolean;
    autoFocus?: boolean;
    onSubmit: () => void;
    onDraftChange: (draft: ComposerDraft) => void;
    onKeyDown?: (event: KeyboardEvent<HTMLDivElement>) => boolean | void;
    onPasteFiles?: (event: ClipboardEvent<HTMLElement>) => void;
    /** Which stretches of the text are words the seat acts on; drawn in the command colour. */
    tokenSpans?: (text: string) => TokenSpan[];
    className?: string;
  }
>(function ComposerChipField(
  {
    placeholder,
    disabled,
    autoFocus,
    onSubmit,
    onDraftChange,
    onKeyDown: onKeyDownProp,
    onPasteFiles,
    tokenSpans,
    className,
  },
  ref,
) {
  const elRef = useRef<HTMLDivElement>(null);
  const savedRange = useRef<Range | null>(null);
  const onDraftChangeRef = useRef(onDraftChange);
  onDraftChangeRef.current = onDraftChange;
  const tokenSpansRef = useRef(tokenSpans);
  tokenSpansRef.current = tokenSpans;

  const rememberRange = (root: HTMLElement) => {
    const range = liveRange(root);
    if (range) savedRange.current = range.cloneRange();
  };

  const rangeForInsert = (root: HTMLElement): Range => {
    const live = liveRange(root);
    if (live) return live;
    const saved = savedRange.current;
    if (saved && root.contains(saved.startContainer)) return saved.cloneRange();
    return rangeAtEnd(root);
  };

  const emit = () => {
    const root = elRef.current;
    if (!root) return;
    // The document selection listener outlives a render or session switch.
    // Always notify the current draft owner, including after session creation.
    onDraftChangeRef.current(readPainted(root, tokenSpansRef.current));
  };

  const insertNode = (node: Node, afterSpace = true) => {
    const root = elRef.current;
    if (!root) return;
    const range = rangeForInsert(root);
    root.focus();
    range.deleteContents();
    range.insertNode(node);
    if (afterSpace) {
      const space = root.ownerDocument.createTextNode(" ");
      node.parentNode?.insertBefore(space, node.nextSibling);
      savedRange.current = caretInText(space, space.data.length).cloneRange();
    } else if (node.nodeType === Node.TEXT_NODE) {
      const text = node as Text;
      savedRange.current = caretInText(text, text.data.length).cloneRange();
    } else {
      const tail = root.ownerDocument.createTextNode("");
      node.parentNode?.insertBefore(tail, node.nextSibling);
      savedRange.current = caretInText(tail, 0).cloneRange();
    }
    emit();
  };

  useImperativeHandle(ref, () => ({
    insertChip(row) {
      // A connector is a per-message selection, not a repeatable word. The
      // Add menu may be reopened after the field has emitted its draft, so
      // reject the second insertion at the source rather than serializing two
      // identical connector IDs to the turn.
      if (elRef.current && serialize(elRef.current).choices.some((choice) => choice.id === row.id)) {
        elRef.current.focus();
        return;
      }
      insertNode(createChipEl(row));
    },
    insertText(text) {
      insertNode(elRef.current!.ownerDocument.createTextNode(text), false);
    },
    hydrate(text, choices = []) {
      const root = elRef.current;
      if (!root) return;
      hydrateRoot(root, text, choices);
      root.focus();
      savedRange.current = rangeAtEnd(root).cloneRange();
      const sel = root.ownerDocument.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(savedRange.current);
      emit();
    },
    getDraft() {
      return elRef.current ? serialize(elRef.current) : { text: "", choices: [], caret: 0 };
    },
    clear() {
      const root = elRef.current;
      if (!root) return;
      root.innerHTML = "";
      savedRange.current = null;
      emit();
    },
    focus() {
      const root = elRef.current;
      if (!root) return;
      root.focus();
      const range = savedRange.current;
      if (range && root.contains(range.startContainer)) {
        const sel = root.ownerDocument.getSelection();
        sel?.removeAllRanges();
        sel?.addRange(range);
      }
    },
    setText(text) {
      const root = elRef.current;
      if (!root) return;
      // Rebuilt with the chips the field holds, so a chip whose `@name` is
      // still in `text` stays a chip. Dictated text is appended through
      // here; written as plain text it would turn every chip into its name
      // and drop the tool choice with it.
      const typingHere = liveRange(root) !== null;
      hydrateRoot(root, text, serialize(root).choices);
      savedRange.current = rangeAtEnd(root).cloneRange();
      if (typingHere) {
        // The rewrite dropped the caret; someone typing here goes on at the end.
        const sel = root.ownerDocument.getSelection();
        sel?.removeAllRanges();
        sel?.addRange(savedRange.current);
      }
      emit();
    },
  }));

  useEffect(() => {
    if (autoFocus) elRef.current?.focus();
  }, [autoFocus]);

  // The seat's command list arrives after the text (and changes with the
  // seat): repaint what is already in the box, and let go of it on unmount.
  useEffect(() => {
    const root = elRef.current;
    if (root) readPainted(root, tokenSpans);
  }, [tokenSpans]);
  useEffect(() => {
    const root = elRef.current;
    return () => {
      if (root) paintTokens(root, null, []);
    };
  }, []);

  useEffect(() => {
    const root = elRef.current;
    if (!root) return;
    const onSel = () => {
      rememberRange(root);
      const sel = root.ownerDocument.getSelection();
      if (sel?.anchorNode && root.contains(sel.anchorNode)) emit();
    };
    root.ownerDocument.addEventListener("selectionchange", onSel);
    return () => root.ownerDocument.removeEventListener("selectionchange", onSel);
  }, []);

  function onInput(_ev: FormEvent<HTMLDivElement>) {
    emit();
  }

  function onKeyDown(ev: KeyboardEvent<HTMLDivElement>) {
    if (onKeyDownProp?.(ev)) return;
    if (ev.defaultPrevented) return;
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      onSubmit();
    }
  }

  function onPaste(ev: ClipboardEvent<HTMLElement>) {
    onPasteFiles?.(ev);
    if (ev.defaultPrevented) return;
    const text = ev.clipboardData.getData("text/plain");
    if (!text) return;
    ev.preventDefault();
    insertNode(ev.currentTarget.ownerDocument.createTextNode(text), false);
  }

  return (
    <div
      ref={elRef}
      role="textbox"
      aria-multiline="true"
      aria-placeholder={placeholder}
      aria-disabled={disabled || undefined}
      contentEditable={!disabled}
      data-placeholder={placeholder}
      data-testid="composer-chip-field"
      data-jarvis-chat-input=""
      suppressContentEditableWarning
      onInput={onInput}
      onKeyDown={onKeyDown}
      onPaste={onPaste}
      onBlur={() => {
        const root = elRef.current;
        if (root) rememberRange(root);
      }}
      className={cn(
        "composer-chip-field min-h-[32px] flex-1 bg-transparent px-1 py-1.5 text-sm leading-relaxed text-foreground outline-none",
        className,
      )}
    />
  );
});
