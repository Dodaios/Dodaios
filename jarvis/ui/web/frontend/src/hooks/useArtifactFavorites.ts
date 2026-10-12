/**
 * The artifacts the reader starred.
 *
 * A star is a per-reader mark on a card, kept in this browser profile's
 * storage: it survives restarts of the desktop app and is shared by every
 * window of it (a detached Artifacts window stars and the main one follows,
 * through the `storage` event). Nothing about it reaches the run archive — a
 * starred run is the same folder on disk as any other.
 *
 * The key is the card's key (`<slug>::<path>` for an artifact, `run:<slug>`
 * for a run without one), so a star stays with exactly the thing it was put on.
 */
import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "jarvis.artifacts.favorites";
/** A star on something long deleted is harmless; a list without end is not. */
const MAX_FAVORITES = 500;

const EMPTY: ReadonlySet<string> = new Set();

let cachedRaw: string | null | undefined;
let cachedSet: ReadonlySet<string> = EMPTY;
const listeners = new Set<() => void>();

function read(): ReadonlySet<string> {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable (private window, blocked site data) — no stars then.
  }
  if (raw === cachedRaw) return cachedSet;
  cachedRaw = raw;
  cachedSet = EMPTY;
  if (raw) {
    try {
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        cachedSet = new Set(parsed.filter((key): key is string => typeof key === "string"));
      }
    } catch {
      // A value something else wrote under this key is not a list of stars.
    }
  }
  return cachedSet;
}

function write(next: ReadonlySet<string>): void {
  const keys = [...next].slice(-MAX_FAVORITES);
  cachedSet = new Set(keys);
  cachedRaw = JSON.stringify(keys);
  try {
    window.localStorage.setItem(STORAGE_KEY, cachedRaw);
  } catch {
    // The star still holds for this window; it just will not outlive it.
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === STORAGE_KEY) listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export interface ArtifactFavorites {
  favorites: ReadonlySet<string>;
  /** Star the card, or take its star away. */
  toggle: (key: string) => void;
}

export function useArtifactFavorites(): ArtifactFavorites {
  const favorites = useSyncExternalStore(subscribe, read, () => EMPTY);
  const toggle = useCallback((key: string) => {
    const next = new Set(read());
    if (!next.delete(key)) next.add(key);
    write(next);
  }, []);
  return { favorites, toggle };
}
