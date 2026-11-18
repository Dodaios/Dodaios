/**
 * The last picture of each agent's live browser, for small views that only watch.
 *
 * `useBrowserView` holds the one live connection to an agent's browser and
 * publishes each picture it draws here. An approval card shows the page the
 * click is on from this store instead of opening a second connection, so
 * watching never launches or competes for the browser. Pictures are passed
 * on at most a few times a second.
 */
import { useEffect, useState } from "react";

const PUBLISH_EVERY_MS = 250;

const latest = new Map<string, string>();
const lastPublished = new Map<string, number>();
const listeners = new Map<string, Set<(src: string) => void>>();

/** Hand on the picture just drawn for `agentId` (a `data:` or `blob:` URL). */
export function publishBrowserFrame(agentId: string, src: string): void {
  const now = Date.now();
  latest.set(agentId, src);
  if (now - (lastPublished.get(agentId) ?? 0) < PUBLISH_EVERY_MS) return;
  lastPublished.set(agentId, now);
  for (const listener of listeners.get(agentId) ?? []) listener(src);
}

/** The view disconnected: its picture is no longer the page. */
export function clearBrowserFrame(agentId: string): void {
  latest.delete(agentId);
  lastPublished.delete(agentId);
  for (const listener of listeners.get(agentId) ?? []) listener("");
}

/** The latest picture of `agentId`'s browser, or "" while none is known. */
export function useLatestBrowserFrame(agentId: string, enabled = true): string {
  const [src, setSrc] = useState(() => (enabled ? latest.get(agentId) ?? "" : ""));
  useEffect(() => {
    if (!enabled || !agentId) {
      setSrc("");
      return undefined;
    }
    setSrc(latest.get(agentId) ?? "");
    const set = listeners.get(agentId) ?? new Set();
    set.add(setSrc);
    listeners.set(agentId, set);
    return () => {
      set.delete(setSrc);
      if (set.size === 0) listeners.delete(agentId);
    };
  }, [agentId, enabled]);
  return src;
}
