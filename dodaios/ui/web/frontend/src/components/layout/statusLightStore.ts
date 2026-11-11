import { create } from "zustand";

import { useAttentionStore } from "@/components/society/attention/attentionStore";

/**
 * The status light's data, held once for the window.
 *
 * One read of `GET /api/status-light` (dodaios/core/status_light.py). It is
 * refreshed when the attention list changes (that list already rides the
 * socket's `AgentAttentionChanged` push), when the window gets focus, and on a
 * slow interval only while the window is visible. It never notifies: this
 * store only feeds a glanceable chip.
 */

export interface StatusLink {
  agent_id?: string;
  session_id?: string;
  ref_id?: string;
  section?: string;
}

export interface StatusRow {
  kind: string;
  id: string;
  title: string;
  state: string;
  since_ms?: number;
  link: StatusLink;
}

export interface StatusTrouble {
  provider: string;
  account: string;
  class: string;
  reason: string;
  blocked: boolean;
}

export interface StatusFinding {
  id: string;
  kind: string;
  title: string;
}

export interface StatusLightData {
  counts: { running: number; needs_you: number };
  running: StatusRow[];
  needs_you: StatusRow[];
  trouble: StatusTrouble[];
  findings: StatusFinding[];
  tone: "calm" | "warn";
}

interface StatusLightState {
  light: StatusLightData | null;
  error: boolean;
}

export const useStatusLightStore = create<StatusLightState>(() => ({ light: null, error: false }));

/** Slow safety read; the attention push covers the changes that matter most. */
export const STATUS_POLL_MS = 45_000;

let inflight: Promise<void> | null = null;

/** Read the light, one request at a time. A failed read keeps the last good one. */
export function refreshStatusLight(): Promise<void> {
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const res = await fetch("/api/status-light");
      if (!res.ok) throw new Error(`status-light ${res.status}`);
      const body = (await res.json()) as Partial<StatusLightData>;
      useStatusLightStore.setState({
        error: false,
        light: {
          counts: { running: body.counts?.running ?? 0, needs_you: body.counts?.needs_you ?? 0 },
          running: body.running ?? [],
          needs_you: body.needs_you ?? [],
          trouble: body.trouble ?? [],
          findings: body.findings ?? [],
          tone: body.tone === "warn" ? "warn" : "calm",
        },
      });
    } catch {
      useStatusLightStore.setState({ error: true });
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

/** Keep the light fresh while the window is in sight; returns the stop function. */
export function watchStatusLight(): () => void {
  const refresh = () => {
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
    void refreshStatusLight();
  };
  refresh();
  const timer = window.setInterval(refresh, STATUS_POLL_MS);
  window.addEventListener("focus", refresh);
  document.addEventListener("visibilitychange", refresh);
  // The attention list changed (a card opened or was answered): read again.
  let last = useAttentionStore.getState().count;
  const unsubscribe = useAttentionStore.subscribe((state) => {
    if (state.count === last) return;
    last = state.count;
    refresh();
  });
  return () => {
    window.clearInterval(timer);
    window.removeEventListener("focus", refresh);
    document.removeEventListener("visibilitychange", refresh);
    unsubscribe();
  };
}
