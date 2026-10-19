/**
 * The memory writer's health, honestly: a dot that says whether writes and
 * the search index work, and a small panel with the reason and the one
 * repair a person can start from here (rebuilding the search index).
 */
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RefreshCw } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { fetchWikiHealth, rebuildWikiIndex, type WikiHealthSnapshot } from "@/lib/wikiApi";
import { Button } from "@/components/ui/button";

type Visual = "green" | "amber" | "red" | "unknown";

export function classifyHealth(health: WikiHealthSnapshot): Visual {
  if (health.bootstrap_ok === false || health.last_write?.ok === false || health.last_chain_failure) return "red";
  if (health.journal_backlog > 0 || health.vault_legacy_conflict || health.index_state === "stale") return "amber";
  return health.bootstrap_ok ? "green" : "unknown";
}

const DOT: Record<Visual, string> = {
  green: "bg-success",
  amber: "bg-warning",
  red: "bg-destructive",
  unknown: "bg-faint-foreground",
};

export function MemoryHealth() {
  const t = useT();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const health = useQuery({ queryKey: ["wiki", "health"], queryFn: fetchWikiHealth, refetchInterval: 30_000, staleTime: 5_000 });
  const visual: Visual = health.data ? classifyHealth(health.data) : "unknown";

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const reindex = async () => {
    setBusy(true);
    setResult(null);
    try {
      const response = await rebuildWikiIndex();
      setResult(
        response.ok
          ? fill(t("memory_view.health_reindexed"), { count: response.indexed_pages ?? 0 })
          : response.error ?? t("memory_view.health_reindex_failed"),
      );
      await queryClient.invalidateQueries({ queryKey: ["wiki"] });
    } catch (err) {
      setResult(err instanceof Error ? err.message : t("memory_view.health_reindex_failed"));
    } finally {
      setBusy(false);
    }
  };

  const data = health.data;
  const reason = !data
    ? t("memory_view.health_checking")
    : data.bootstrap_ok === false
      ? data.bootstrap_error ?? t("memory_view.health_writer_off")
      : data.last_write?.ok === false
        ? data.last_write.error ?? t("memory_view.health_write_failed")
        : data.last_chain_failure
          ? data.last_chain_failure.detail
          : data.index_state === "stale"
            ? fill(t("memory_view.health_index_stale"), { indexed: data.indexed_pages, pages: data.vault_pages })
            : data.journal_backlog > 0
              ? fill(t("memory_view.health_backlog"), { count: data.journal_backlog })
              : t("memory_view.health_ok");

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        data-testid="memory-health"
        data-visual={visual}
        className="inline-flex h-8 items-center gap-2 rounded-md px-2.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
      >
        <span className={cn("h-2 w-2 rounded-full", health.isLoading ? "animate-pulse bg-faint-foreground" : DOT[visual])} aria-hidden />
        {t(`memory_view.health_${visual}`)}
      </button>
      {open && (
        <div className="absolute right-0 top-10 z-30 w-[300px] rounded-xl border border-border bg-popover p-4 text-sm shadow-float" role="dialog" aria-label={t("memory_view.health_title")}>
          <p className="font-medium text-foreground-strong">{t("memory_view.health_title")}</p>
          <p className="mt-1.5 leading-relaxed text-muted-foreground">{reason}</p>
          {data && (
            <dl className="mt-3 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-xs">
              <dt className="text-muted-foreground">{t("memory_view.health_indexed")}</dt>
              <dd className="text-right tabular-nums text-foreground">
                {data.indexed_pages} / {data.vault_pages}
              </dd>
              <dt className="text-muted-foreground">{t("memory_view.health_queue")}</dt>
              <dd className="text-right tabular-nums text-foreground">{data.journal_backlog}</dd>
            </dl>
          )}
          <Button variant="outline" size="sm" className="mt-4 w-full" onClick={() => void reindex()} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />}
            {t("memory_view.health_reindex")}
          </Button>
          {result && <p className="mt-2 text-xs text-muted-foreground">{result}</p>}
        </div>
      )}
    </div>
  );
}
