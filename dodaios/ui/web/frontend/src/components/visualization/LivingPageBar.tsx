/**
 * The strip above a living page on the Artifacts stage: when it was last
 * updated, how often it refreshes, and the one control to stop (or restart)
 * the refresh. The page itself runs in a sandbox with no network, so the
 * control lives here, in the app.
 *
 * Lazy-loaded by the stage (it is only needed when a living page is open).
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useT, useUiLanguage } from "@/i18n";
import { localeForUiLanguage } from "@/components/runs/format";
import { cn } from "@/lib/utils";
import { cadence, relativeTime, type LivingPageState } from "./livingPage";

const POLL_MS = 30_000;

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as T;
}

export default function LivingPageBar({
  slug,
  onUpdated,
}: {
  slug: string;
  /** Called with the page's update time, so the stage reloads the frame. */
  onUpdated?: (updatedAt: number) => void;
}) {
  const t = useT();
  const locale = localeForUiLanguage(useUiLanguage());
  const client = useQueryClient();
  const key = ["living-page", slug];
  const page = useQuery<LivingPageState>({
    queryKey: key,
    queryFn: async () => readJson(await fetch(`/api/living-pages/by-slug/${encodeURIComponent(slug)}`)),
    refetchInterval: POLL_MS,
    retry: false,
  });
  const toggle = useMutation({
    mutationFn: async (action: "stop" | "resume") =>
      readJson<LivingPageState>(
        await fetch(`/api/living-pages/${page.data?.id ?? ""}/${action}`, { method: "POST" }),
      ),
    onSuccess: (data) => client.setQueryData(key, data),
  });
  // Re-render the relative time while the page stays open.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), POLL_MS);
    return () => window.clearInterval(timer);
  }, []);
  const updatedAt = page.data?.updated_at;
  useEffect(() => {
    if (updatedAt) onUpdated?.(updatedAt);
  }, [updatedAt, onUpdated]);

  if (!page.data) return null;
  const { refreshing } = page.data;
  const failed = toggle.isError
    ? t(toggle.variables === "stop" ? "living_pages.stop_failed" : "living_pages.resume_failed")
    : "";

  return (
    <div
      data-testid="living-page-bar"
      className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-border px-4 py-2 text-sm text-muted-foreground"
    >
      <span className="inline-flex items-center gap-2 text-foreground">
        <span
          aria-hidden
          className={cn("h-2 w-2 rounded-full", refreshing ? "bg-accent" : "bg-muted-foreground/50")}
        />
        {t("living_pages.label")}
      </span>
      <span title={new Date(page.data.updated_at * 1000).toLocaleString(locale)}>
        {t("living_pages.updated").replace("{0}", relativeTime(page.data.updated_at, now, locale))}
      </span>
      <span>
        {refreshing
          ? t("living_pages.every").replace("{0}", cadence(page.data.every_minutes, locale))
          : t("living_pages.stopped")}
      </span>
      {failed ? (
        <span role="alert" className="text-destructive">
          {failed}
        </span>
      ) : null}
      <Button
        variant="outline"
        size="sm"
        className="ml-auto"
        disabled={toggle.isPending}
        onClick={() => toggle.mutate(refreshing ? "stop" : "resume")}
      >
        {toggle.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
        {refreshing ? t("living_pages.stop") : t("living_pages.resume")}
      </Button>
    </div>
  );
}
