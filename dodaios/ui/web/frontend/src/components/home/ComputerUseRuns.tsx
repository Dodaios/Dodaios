import { useCallback, useEffect, useRef, useState } from "react";
import { Monitor, Square } from "lucide-react";

import { useT } from "@/i18n";

type ComputerUseRun = {
  mission_id: string;
  goal: string;
  source: string;
  status: "queued" | "running" | "finished" | "error" | "cancelled" | "timeout";
  started_at: number;
  result_text: string;
};

type ComputerUsePayload = {
  runs: ComputerUseRun[];
  active: number;
};

const POLL_MS = 2500;
const RECENT_RUNS = 4;

/** Live control for desktop missions; the backend already owns run lifecycle. */
export function ComputerUseRuns() {
  const t = useT();
  const loadFailed = t("home.computer_use.load_failed");
  const [runs, setRuns] = useState<ComputerUseRun[]>([]);
  const [active, setActive] = useState(0);
  const [error, setError] = useState("");
  const [stopping, setStopping] = useState<string | null>(null);
  const mounted = useRef(false);

  const refresh = useCallback(async () => {
    const response = await fetch("/api/computer-use/goals?limit=8");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = (await response.json()) as ComputerUsePayload;
    if (!mounted.current) return;
    setRuns(payload.runs ?? []);
    setActive(payload.active ?? 0);
    setError("");
  }, []);

  useEffect(() => {
    let live = true;
    let timer: number | undefined;
    mounted.current = true;
    const poll = async () => {
      try {
        await refresh();
      } catch {
        if (live) setError(loadFailed);
      }
      if (live) timer = window.setTimeout(poll, POLL_MS);
    };
    void poll();
    return () => {
      live = false;
      mounted.current = false;
      window.clearTimeout(timer);
    };
  }, [refresh, loadFailed]);

  async function stop(missionId: string) {
    if (stopping) return;
    setStopping(missionId);
    setError("");
    try {
      const response = await fetch(
        `/api/computer-use/goals/${encodeURIComponent(missionId)}/cancel`,
        { method: "POST" },
      );
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`);
      }
      if (mounted.current) await refresh();
    } catch {
      if (mounted.current) setError(t("home.computer_use.stop_failed"));
    } finally {
      if (mounted.current) setStopping(null);
    }
  }

  const visibleRuns = runs.slice(0, RECENT_RUNS);
  return (
    <section className="space-y-1.5" data-testid="computer-use-runs">
      <h3 className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <Monitor aria-hidden className="h-3.5 w-3.5" />
        {t("home.computer_use.title")}
        {active > 0 && <span className="rounded-full bg-accent-soft px-1.5 text-accent">{active}</span>}
      </h3>
      {visibleRuns.length === 0 ? (
        <p className="pl-5 text-xs text-foreground-faint">{error || t("home.computer_use.empty")}</p>
      ) : (
        <ul className="space-y-1.5 pl-5">
          {visibleRuns.map((run) => {
            const running = run.status === "running";
            return (
              <li key={run.mission_id} className="rounded-md bg-secondary/60 px-2 py-1.5" data-testid={`computer-use-run-${run.mission_id}`}>
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 flex-1 break-words text-sm text-foreground">{run.goal}</p>
                  {running && (
                    <button
                      type="button"
                      aria-label={t("home.computer_use.stop")}
                      title={t("home.computer_use.stop")}
                      disabled={stopping !== null}
                      onClick={() => void stop(run.mission_id)}
                      className="shrink-0 rounded p-1 text-muted-foreground hover:bg-background hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                    >
                      <Square aria-hidden className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
                <p className="text-xs text-foreground-faint">
                  {t(`home.computer_use.status_${run.status}`)}
                  {run.source ? ` · ${run.source}` : ""}
                </p>
                {run.result_text && run.status !== "running" && (
                  <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{run.result_text}</p>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {error && visibleRuns.length > 0 && <p className="pl-5 text-xs text-destructive">{error}</p>}
    </section>
  );
}
