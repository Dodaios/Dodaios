/**
 * The strip above a kept-current node on the stage: when it was last
 * updated, how often the assistant looks again, and the one control to pause
 * (or resume) that. The page itself runs in a sandbox with no network, so
 * the control lives here, in the app.
 *
 * It reads the node by its run slug (`/api/nodes/by-slug/{slug}`) and renders
 * nothing for a node that is not kept current, or while it does not know. It
 * is mounted for EVERY typed node all the same: it is also what tells the
 * stage that the node changed (`onUpdated`), so a page the assistant revises
 * while the person watches is drawn again within seconds.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { localeForUiLanguage } from "@/components/runs/format";
import { Button } from "@/components/ui/button";
import { cadence, relativeTime } from "@/components/visualization/livingPage";
import { useT, useUiLanguage } from "@/i18n";
import { cn } from "@/lib/utils";
import { NodesApiError, fetchNodeBySlug, invalidateNodes, setNodeUpkeep, type NodeState } from "./useNodes";

/** How often the relative time is redrawn. */
const POLL_MS = 30_000;
/**
 * How often the open node is asked whether it changed. Short, because the
 * person is looking at the page while the assistant revises it, and the
 * answer is one small state file.
 */
const WATCH_MS = 5_000;

export { NODE_SLUG_INFIX, isNodeSlug } from "./nodeModel";

export default function NodeUpkeepBar({
  slug,
  onUpdated,
}: {
  slug: string;
  /** Called with the node's update time, so the stage reloads the frame. */
  onUpdated?: (updatedAt: number) => void;
}) {
  const t = useT();
  const locale = localeForUiLanguage(useUiLanguage());
  const client = useQueryClient();
  const key = ["node-upkeep", slug];
  const node = useQuery<NodeState>({
    queryKey: key,
    queryFn: () => fetchNodeBySlug(slug),
    refetchInterval: WATCH_MS,
    retry: false,
  });
  const toggle = useMutation({
    mutationFn: (action: "stop" | "resume") => setNodeUpkeep(node.data?.id ?? "", action),
    onSuccess: (data) => {
      client.setQueryData(key, data);
      // The card in the library says "kept current" or "paused" too.
      invalidateNodes(client);
    },
  });
  // Re-render the relative time while the node stays open.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), POLL_MS);
    return () => window.clearInterval(timer);
  }, []);
  const updatedAt = node.data?.updated_at;
  useEffect(() => {
    if (updatedAt) onUpdated?.(updatedAt);
  }, [updatedAt, onUpdated]);

  const data = node.data;
  if (!data || !data.track) return null;
  const { refreshing } = data;
  const failed = !toggle.isError
    ? ""
    : toggle.error instanceof NodesApiError && toggle.error.status === 503
      ? t("nodes.upkeep.unavailable")
      : t(toggle.variables === "stop" ? "nodes.upkeep.stop_failed" : "nodes.upkeep.resume_failed");

  return (
    <div
      data-testid="node-upkeep-bar"
      className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-border px-4 py-2 text-sm text-muted-foreground"
    >
      <span className="inline-flex items-center gap-2 text-foreground">
        <span
          aria-hidden
          className={cn("h-2 w-2 rounded-full", refreshing ? "bg-success" : "bg-foreground-faint")}
        />
        {t(refreshing ? "nodes.upkeep.label" : "nodes.upkeep.paused")}
      </span>
      <span title={new Date(data.updated_at * 1000).toLocaleString(locale)}>
        {t("nodes.upkeep.updated").replace("{0}", () => relativeTime(data.updated_at, now, locale))}
      </span>
      {refreshing && data.every_minutes > 0 && (
        <span>{t("nodes.upkeep.every").replace("{0}", () => cadence(data.every_minutes, locale))}</span>
      )}
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
        data-testid="node-upkeep-toggle"
      >
        {toggle.isPending ? <Loader2 className="animate-spin" aria-hidden /> : null}
        {t(refreshing ? "nodes.upkeep.stop" : "nodes.upkeep.resume")}
      </Button>
    </div>
  );
}
