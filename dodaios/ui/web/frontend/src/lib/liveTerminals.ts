/**
 * The IDE's live pane terminals, readable by anything that wants to show them.
 *
 * Every mounted Agentic-IDE pane registers its xterm instance here under
 * `<workspaceId>:<name>`. The ship's monitors read the very same buffer the
 * pane draws from, so a monitor shows the pane's screen cell for cell, with
 * its colours, instead of a server-side text replay.
 *
 * Read-only by contract: nothing here writes to, resizes or focuses a
 * terminal. `version` grows on every parsed write and resize, so a reader
 * can tell cheaply whether there is anything new to draw.
 */
import type { Terminal } from "@xterm/xterm";

export interface LiveTerminal {
  readonly term: Terminal;
  /** Bumped on every parsed write and resize. */
  version: number;
}

const live = new Map<string, LiveTerminal>();
const listeners = new Set<() => void>();
let generation = 0;

function keyOf(workspaceId: string, name: string): string {
  return `${workspaceId}:${name}`;
}

function changed(): void {
  generation += 1;
  for (const listener of listeners) listener();
}

/** Register a pane's terminal; returns the matching unregister. */
export function registerLiveTerminal(workspaceId: string, name: string, term: Terminal): () => void {
  const key = keyOf(workspaceId, name);
  const entry: LiveTerminal = { term, version: 0 };
  const bump = () => { entry.version += 1; };
  // Optional calls: a monitor feed must never be able to break the pane that registers it.
  const subs = [term.onWriteParsed?.(bump), term.onResize?.(bump)].filter((s): s is { dispose(): void } => !!s);
  live.set(key, entry);
  changed();
  return () => {
    for (const sub of subs) sub.dispose();
    // A newer viewer of the same pane may have taken the slot meanwhile.
    if (live.get(key) === entry) {
      live.delete(key);
      changed();
    }
  };
}

/** The live terminal of a pane, trying each of its names (call-sign, title). */
export function liveTerminal(workspaceId: string, names: readonly string[]): LiveTerminal | undefined {
  for (const name of names) {
    const entry = live.get(keyOf(workspaceId, name));
    if (entry) return entry;
  }
  return undefined;
}

/** For useSyncExternalStore: changes whenever a terminal comes or goes. */
export function subscribeLiveTerminals(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function liveTerminalsGeneration(): number {
  return generation;
}
