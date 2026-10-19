/**
 * The switch for the wiki's semantic search.
 *
 * Off by default. Switching it on downloads a search model once and then
 * reads the wiki pages on this computer; the row says which of those steps is
 * running and how far it is, and polls only while one is. The switch shows
 * what the server holds: it flips once the server confirmed the change and
 * springs back with a sentence when the save failed.
 *
 * A backend without the route answers nothing, and then there is no row.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Sparkles } from "lucide-react";

import { Switch } from "@/components/ui/switch";
import { useT } from "@/i18n";
import {
  fetchWikiSemanticSearch,
  setWikiSemanticSearch,
  type WikiSemanticSearchStatus,
} from "@/lib/wikiApi";
import { SettingRow } from "@/views/profile/ProfileGroup";

export const SEMANTIC_SEARCH_KEY = ["wiki", "semantic-search"] as const;

const POLL_MS = 1000;

function working(status: WikiSemanticSearchStatus | null | undefined): boolean {
  return status?.state === "downloading" || status?.state === "indexing";
}

/** Switched on, but the app has not picked the work up yet (the moment after a start). */
function pending(status: WikiSemanticSearchStatus | null | undefined): boolean {
  return !!status?.enabled && status.state === "off";
}

function percent(progress: number | null): string {
  return String(Math.round(Math.min(Math.max(progress ?? 0, 0), 1) * 100));
}

export function SemanticSearchRow() {
  const t = useT();
  const client = useQueryClient();
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const query = useQuery({
    queryKey: SEMANTIC_SEARCH_KEY,
    queryFn: fetchWikiSemanticSearch,
    retry: false,
    // Keeps polling through a failed request: react-query holds the last good
    // state, and that state still says a step is running.
    refetchInterval: ({ state }) => (working(state.data) || pending(state.data) ? POLL_MS : false),
  });
  const status = query.data ?? null;
  if (status === null) return null;

  const megabytes = String(Math.round(status.download_bytes / 1_000_000));
  let hint: string;
  if (!status.available) hint = t("profile_view.semantic_unavailable");
  else if (!status.enabled) hint = t("profile_view.semantic_off").replace("{0}", megabytes);
  else if (status.state === "downloading")
    hint = t("profile_view.semantic_downloading").replace("{0}", percent(status.progress));
  else if (status.state === "indexing")
    hint = t("profile_view.semantic_indexing").replace("{0}", percent(status.progress));
  else if (status.state === "ready")
    hint = t("profile_view.semantic_ready").replace("{0}", String(status.pages));
  else if (status.state === "error") hint = t("profile_view.semantic_failed");
  else hint = t("profile_view.semantic_starting");

  const toggle = async (enabled: boolean) => {
    setSaving(true);
    setSaveFailed(false);
    try {
      client.setQueryData(SEMANTIC_SEARCH_KEY, await setWikiSemanticSearch(enabled));
    } catch {
      setSaveFailed(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <SettingRow
      testId="semantic-search-row"
      label={
        <span className="flex items-center gap-2.5">
          <span aria-hidden className="text-muted-foreground [&>svg]:h-4 [&>svg]:w-4">
            <Sparkles />
          </span>
          {t("profile_view.semantic_title")}
        </span>
      }
      hint={
        <span className="block pl-[1.625rem]">
          <span data-testid="semantic-search-status" aria-live="polite">
            {hint}
          </span>
          {saveFailed ? (
            <span role="alert" className="block text-destructive">
              {t("profile_view.semantic_save_failed")}
            </span>
          ) : null}
        </span>
      }
      control={
        <>
          {(saving || working(status) || pending(status)) && (
            <Loader2 aria-hidden className="h-4 w-4 animate-spin text-muted-foreground" />
          )}
          <Switch
            data-testid="semantic-search-switch"
            aria-label={t("profile_view.semantic_title")}
            checked={status.enabled}
            disabled={saving || (!status.available && !status.enabled)}
            onCheckedChange={(next) => void toggle(next)}
          />
        </>
      }
    />
  );
}
