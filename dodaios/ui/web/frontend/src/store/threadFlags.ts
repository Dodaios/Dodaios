import { create } from "zustand";

/**
 * Flags on threads, the way a mail app flags important mail: three kinds,
 * each in its own colour, set and cleared from a thread's row menu.
 *
 * A kind's name is the person's own ("Waiting for review", "Ship today", …)
 * and holds for every thread with that flag; it shows when the pointer rests
 * on the flag. An empty name falls back to the kind's default words in the
 * UI language, so nothing here is stored in one language.
 *
 * Both survive a reload through localStorage, which may be blocked: every
 * read and write degrades to the defaults instead of throwing.
 */

export type ThreadFlagKind = "red" | "orange" | "blue";

export const THREAD_FLAG_KINDS: readonly ThreadFlagKind[] = ["red", "orange", "blue"];

/** A flag's own colour, from the theme's status hues so it reads in light and dark. */
export const THREAD_FLAG_COLOR: Record<ThreadFlagKind, string> = {
  red: "text-destructive",
  orange: "text-warning",
  blue: "text-info",
};

/** The longest name a flag takes: it has to fit a tooltip and a menu row. */
export const MAX_FLAG_NAME = 60;

const FLAGS_KEY = "jarvis.agenticIde.threadFlags.v1";
const NAMES_KEY = "jarvis.agenticIde.threadFlagNames.v1";
/** Bound on the flagged threads kept in storage; the oldest flag goes first. */
const MAX_FLAGGED = 2000;

const isKind = (value: unknown): value is ThreadFlagKind =>
  typeof value === "string" && (THREAD_FLAG_KINDS as readonly string[]).includes(value);

function read<T>(key: string, parse: (raw: unknown) => T, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : parse(JSON.parse(raw));
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* a convenience only: the flag just does not survive this session */
  }
}

const parseFlags = (raw: unknown): Record<string, ThreadFlagKind> => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  return Object.fromEntries(Object.entries(raw).filter(([, kind]) => isKind(kind))) as Record<string, ThreadFlagKind>;
};

const parseNames = (raw: unknown): Partial<Record<ThreadFlagKind, string>> => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  return Object.fromEntries(Object.entries(raw)
    .filter(([kind, name]) => isKind(kind) && typeof name === "string" && name.trim())
    .map(([kind, name]) => [kind, (name as string).trim().slice(0, MAX_FLAG_NAME)]));
};

interface ThreadFlagsState {
  /** The flag on each flagged thread, by session id; insertion order is flag order. */
  flags: Record<string, ThreadFlagKind>;
  /** The person's own name for a kind; absent means the default words. */
  names: Partial<Record<ThreadFlagKind, string>>;
  /** Flag a thread, or move it to another kind; the same kind again clears it. */
  toggleFlag: (sessionId: string, kind: ThreadFlagKind) => void;
  clearFlag: (sessionId: string) => void;
  /** Name a kind; an empty name brings the default words back. */
  renameFlag: (kind: ThreadFlagKind, name: string) => void;
}

export const useThreadFlagsStore = create<ThreadFlagsState>((set, get) => ({
  flags: read(FLAGS_KEY, parseFlags, {}),
  names: read(NAMES_KEY, parseNames, {}),
  toggleFlag: (sessionId, kind) => {
    const { [sessionId]: previous, ...rest } = get().flags;
    if (previous === kind) {
      write(FLAGS_KEY, rest);
      set({ flags: rest });
      return;
    }
    const entries = Object.entries({ ...rest, [sessionId]: kind });
    const flags = Object.fromEntries(entries.slice(Math.max(0, entries.length - MAX_FLAGGED)));
    write(FLAGS_KEY, flags);
    set({ flags });
  },
  clearFlag: (sessionId) => {
    if (!(sessionId in get().flags)) return;
    const { [sessionId]: _flag, ...flags } = get().flags;
    write(FLAGS_KEY, flags);
    set({ flags });
  },
  renameFlag: (kind, name) => {
    const clean = name.trim().slice(0, MAX_FLAG_NAME);
    const { [kind]: _previous, ...rest } = get().names;
    const names = clean ? { ...rest, [kind]: clean } : rest;
    write(NAMES_KEY, names);
    set({ names });
  },
}));
