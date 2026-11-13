/**
 * Where the browser tile sits when the assistant's panel is open: a slot the
 * panel's Computers section offers, so the tile stands beside the other
 * computers instead of over the conversation. Without the panel (closed,
 * other tab, narrow window) the tile floats in the chat's corner.
 *
 * While the stage is open it takes the panel's place: the front page hides
 * the panel (`useAgentBrowserStaged`), and brings it back with the tile.
 */
import { useSyncExternalStore } from "react";

let slot: HTMLElement | null = null;
let staged = false;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** A callback ref for the panel's slot element. */
export function setAgentBrowserSlot(element: HTMLElement | null): void {
  if (slot === element) return;
  slot = element;
  notify();
}

export function useAgentBrowserSlot(): HTMLElement | null {
  return useSyncExternalStore(subscribe, () => slot, () => null);
}

export function setAgentBrowserStaged(value: boolean): void {
  if (staged === value) return;
  staged = value;
  notify();
}

/** The browser stage is open beside the chat. */
export function useAgentBrowserStaged(): boolean {
  return useSyncExternalStore(subscribe, () => staged, () => false);
}
