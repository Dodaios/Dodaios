/**
 * The deck on screen, loaded from its cooked content. Decks are cached per
 * content folder for the session, so riding the lift back is instant.
 *
 * In a development build `?verseContent=<folder>` (or the localStorage key
 * `verse.content`) shows that folder for every deck, so the testbed can be
 * driven through the real stage before the decks are cooked.
 */
import { useEffect, useState } from "react";
import type { DeckId } from "../decks";
import type { Deck } from "./deck";
import { loadDeck } from "./loadDeck";

const cache = new Map<string, Promise<Deck>>();

export function contentFor(deck: DeckId): string {
  if (import.meta.env.DEV && typeof window !== "undefined") {
    const fromUrl = new URLSearchParams(window.location.search).get("verseContent");
    let stored: string | null = null;
    try { stored = window.localStorage.getItem("verse.content"); } catch { /* storage blocked */ }
    const override = fromUrl ?? stored;
    if (override && /^[a-z][a-z0-9_-]*$/.test(override)) return override;
  }
  return deck;
}

export type DeckState =
  | { status: "loading"; deck: null; error: null }
  | { status: "ready"; deck: Deck; error: null }
  | { status: "failed"; deck: null; error: Error };

export function useDeck(id: DeckId): DeckState {
  const [state, setState] = useState<DeckState>({ status: "loading", deck: null, error: null });
  useEffect(() => {
    const contentId = contentFor(id);
    const key = `${id}:${contentId}`;
    let alive = true;
    setState({ status: "loading", deck: null, error: null });
    let pending = cache.get(key);
    if (!pending) {
      // Not tied to this effect's lifetime: a cached load must survive a quick unmount.
      pending = loadDeck(id, contentId, new AbortController().signal);
      cache.set(key, pending);
      pending.catch(() => cache.delete(key));
    }
    pending.then(
      (deck) => { if (alive) setState({ status: "ready", deck, error: null }); },
      (error: unknown) => { if (alive) setState({ status: "failed", deck: null, error: error instanceof Error ? error : new Error(String(error)) }); },
    );
    return () => { alive = false; };
  }, [id]);
  return state;
}
