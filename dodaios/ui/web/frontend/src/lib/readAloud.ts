import { useSyncExternalStore } from "react";

/**
 * Reading an answer aloud with the person's own voice (POST /api/tts/read-aloud).
 *
 * One answer reads at a time, anywhere in the app: starting another stops the
 * first. A long answer is spoken in stretches: the first is short so the voice
 * starts quickly, and the next stretch is synthesised while the current one plays.
 */

export type ReadAloudPhase = "loading" | "playing" | "error";
export interface ReadAloudState {
  /** The answer being read (the caller's key), or null when nothing reads. */
  id: string | null;
  phase: ReadAloudPhase | null;
  error: string;
}

const IDLE: ReadAloudState = { id: null, phase: null, error: "" };
let state: ReadAloudState = IDLE;
const listeners = new Set<() => void>();
let session = 0;
let audio: HTMLAudioElement | null = null;
let finishPlayback: (() => void) | null = null;
let errorTimer: number | undefined;

function set(next: ReadAloudState): void {
  state = next;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The read-aloud state for one answer: idle unless that answer is the one reading. */
export function useReadAloud(id: string): { phase: ReadAloudPhase | null; error: string } {
  const current = useSyncExternalStore(subscribe, () => state);
  return current.id === id ? { phase: current.phase, error: current.error } : { phase: null, error: "" };
}

/** The words of text that may hold inline HTML: parsed inert, never run or shown. */
function textOfHtml(text: string): string {
  if (!/[<&]/.test(text)) return text;
  return new DOMParser().parseFromString(text, "text/html").body.textContent ?? "";
}

/**
 * Markdown as it should sound: code blocks, tables and links' addresses are
 * left out, markup signs dropped, a link read by its words.
 */
export function speakableText(markdown: string): string {
  const lines: string[] = [];
  let fence: string | null = null;
  for (const raw of markdown.replace(/\r\n?/g, "\n").split("\n")) {
    const mark = /^ {0,3}(`{3,}|~{3,})/.exec(raw)?.[1];
    if (fence) {
      if (mark && mark[0] === fence[0] && mark.length >= fence.length) fence = null;
      continue;
    }
    if (mark) { fence = mark; continue; }
    // A table row and its rule are data, not sentences.
    if (/^\s*\|.*\|\s*$/.test(raw)) continue;
    if (/^ {0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(raw)) continue;
    if (/^ {0,3}\[[^\]]+\]:\s/.test(raw)) continue;
    let line = raw
      .replace(/^ {0,3}#{1,6}\s+/, "")
      .replace(/^\s*>\s?/, "")
      .replace(/^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?/, "")
      .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/\[([^\]]+)\]\[[^\]]*\]/g, "$1")
      // A web address is not read; an autolink leaves its empty brackets behind.
      .replace(/https?:\/\/[^\s>]+/g, "")
      .replace(/<>/g, "")
      .replace(/`([^`]*)`/g, "$1")
      .replace(/(\*\*|__)(.+?)\1/g, "$2")
      .replace(/(^|[^\w*])[*_]([^*_\n]+)[*_](?=[^\w*]|$)/g, "$1$2")
      .replace(/~~(.+?)~~/g, "$1")
      .trim();
    // A list item or heading without a closing mark still ends where it ends.
    if (line && !/[.!?:;,…]$/.test(line) && /^ {0,3}(?:#{1,6}\s|[-*+]\s|\d+[.)]\s)/.test(raw)) line += ".";
    lines.push(line);
  }
  return textOfHtml(lines.join("\n")).replace(/\n{3,}/g, "\n\n").replace(/[ \t]+/g, " ").trim();
}

/** The first stretch is short so the voice starts at once; the rest are paragraph-sized. */
const FIRST_STRETCH = 220;
const STRETCH = 900;

/** Text cut into stretches at sentence ends (or, for a run-on sentence, at a space). */
export function speechStretches(text: string): string[] {
  const sentences = text.replace(/\s+/g, " ").trim().match(/[^.!?…]+(?:[.!?…]+["')\]]*\s*|$)/g) ?? [];
  const out: string[] = [];
  let current = "";
  const limit = () => (out.length === 0 ? FIRST_STRETCH : STRETCH);
  const push = () => { if (current.trim()) out.push(current.trim()); current = ""; };
  for (let sentence of sentences) {
    if (current && (current + sentence).length > limit()) push();
    while (sentence.length > limit()) {
      const cut = sentence.lastIndexOf(" ", limit());
      const at = cut > limit() / 2 ? cut : limit();
      current = sentence.slice(0, at);
      push();
      sentence = sentence.slice(at);
    }
    current += sentence;
  }
  push();
  return out;
}

async function synthesise(text: string, language: string): Promise<{ url: string; language: string }> {
  const res = await fetch("/api/tts/read-aloud", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, language }),
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), language: res.headers.get("X-Read-Language") ?? language };
}

function play(url: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const element = new Audio(url);
    audio = element;
    finishPlayback = resolve;
    element.onended = () => resolve();
    element.onerror = () => reject(new Error("The audio could not be played."));
    element.play().catch(reject);
  });
}

/** Whether the answer `id` is the one being read (or about to be). */
export function isReadingAloud(id: string): boolean {
  return state.id === id && state.phase !== "error";
}

/** Stops whatever is being read. */
export function stopReadAloud(): void {
  session++;
  audio?.pause();
  audio = null;
  finishPlayback?.();
  finishPlayback = null;
  window.clearTimeout(errorTimer);
  if (state.id !== null) set(IDLE);
}

/** Reads `markdown` aloud as the answer `id`; a second call for the same answer stops it. */
export async function toggleReadAloud(id: string, markdown: string): Promise<void> {
  const reading = isReadingAloud(id);
  stopReadAloud();
  if (reading) return;
  const stretches = speechStretches(speakableText(markdown));
  if (!stretches.length) return;
  const mine = session;
  set({ id, phase: "loading", error: "" });
  let language = "";
  const urls: string[] = [];
  try {
    let next = synthesise(stretches[0], language);
    for (let index = 0; index < stretches.length; index++) {
      const part = await next;
      urls.push(part.url);
      if (mine !== session) return;
      language = part.language;
      if (index + 1 < stretches.length) {
        next = synthesise(stretches[index + 1], language);
        // A stop before it is awaited must neither leak its audio nor leave an unhandled rejection.
        next.then((later) => { if (mine !== session) URL.revokeObjectURL(later.url); }, () => undefined);
      }
      set({ id, phase: "playing", error: "" });
      await play(part.url);
      if (mine !== session) return;
    }
    if (mine === session) set(IDLE);
  } catch (error) {
    if (mine !== session) return;
    audio = null;
    set({ id, phase: "error", error: error instanceof Error ? error.message : String(error) });
    errorTimer = window.setTimeout(() => { if (mine === session) set(IDLE); }, 5000);
  } finally {
    urls.forEach((url) => URL.revokeObjectURL(url));
  }
}
