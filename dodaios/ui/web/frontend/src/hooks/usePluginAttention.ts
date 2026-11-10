import { useSyncExternalStore } from "react";

import { bootSettled } from "@/lib/bootStagger";

/** One plugin whose connection needs the person. */
export interface PluginAttentionItem {
  id: string;
  name: string;
  status: "needs_reauth" | "error";
  /** When the connection was flagged; `null` when the backend recorded none. */
  reauthAt: string | null;
}

/** What the shell needs to surface a plugin problem: how many connected
 *  plugins need attention, their display names (for a concrete tooltip) and
 *  the rows themselves (for the reconnect notices). */
export interface PluginAttention {
  count: number;
  names: string[];
  items: PluginAttentionItem[];
}

const CALM: PluginAttention = { count: 0, names: [], items: [] };
const POLL_MS = 60_000;

let current: PluginAttention = CALM;
let timer: ReturnType<typeof setInterval> | null = null;
let generation = 0;
const listeners = new Set<() => void>();

async function check(run: number): Promise<void> {
  try {
    const res = await fetch("/api/marketplace/plugins", { cache: "no-store" });
    if (!res.ok) return;
    const data = (await res.json()) as {
      plugins?: { id?: string; status?: string; display_name?: string; reauth_at?: string | null }[];
    };
    if (run !== generation) return;
    const items: PluginAttentionItem[] = (data.plugins ?? [])
      .filter((p) => p.status === "needs_reauth" || p.status === "error")
      .map((p) => ({
        id: p.id ?? "",
        name: p.display_name ?? "",
        status: p.status as PluginAttentionItem["status"],
        reauthAt: p.reauth_at ?? null,
      }));
    const next: PluginAttention = {
      count: items.length,
      names: items.map((p) => p.name).filter(Boolean),
      items,
    };
    // Same answer, same object: nothing re-renders on a quiet poll.
    if (JSON.stringify(next) === JSON.stringify(current)) return;
    current = next;
    listeners.forEach((listener) => listener());
  } catch {
    // Offline / no backend / no fetch — stay calm, surface nothing.
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (listeners.size === 1) {
    const run = ++generation;
    // Non-critical: the first check waits out the boot burst (see bootStagger).
    void bootSettled().then(() => check(run));
    timer = setInterval(() => void check(run), POLL_MS);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      generation += 1;
      if (timer !== null) clearInterval(timer);
      timer = null;
      current = CALM;
    }
  };
}

/** Read the plugin list again now, e.g. right after a reconnect. */
export function refreshPluginAttention(): Promise<void> {
  return listeners.size > 0 ? check(generation) : Promise.resolve();
}

/**
 * Reports which connected plugins need attention — a revoked/expired token
 * (`needs_reauth`) or an `error`.
 *
 * One poll of the marketplace plugin list serves every caller (sidebar, dock
 * rail, reconnect notices). Standalone (no React-Query) so it works in the
 * Sidebar, which renders without a QueryClientProvider. Fully fault-tolerant:
 * with no backend / no `fetch`, it stays calm (count 0) rather than throwing —
 * a sidebar dot must never crash the shell.
 */
export function usePluginAttention(): PluginAttention {
  return useSyncExternalStore(subscribe, () => current, () => CALM);
}
