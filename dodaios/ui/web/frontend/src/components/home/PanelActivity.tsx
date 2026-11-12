import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Hand, LoaderCircle, MessageCircle } from "lucide-react";

import { openCodingThread } from "@/components/agentic/threads/openCodingThread";
import { PANEL_ICON, PANEL_ROW_BUTTON, PanelEmpty, PanelSection, ShowMore } from "@/components/home/panelParts";
import { fill, useT } from "@/i18n";
import { fetchLeadThreads, type LeadThread } from "@/lib/agentChatApi";
import { cn } from "@/lib/utils";
import { useIdeThreadsStore } from "@/store/ideThreads";

/** How many chats show before the rest folds away. */
export const ACTIVITY_SHOWN = 4;
const ACTIVITY_READ = 12;

export type ThreadState = "waiting" | "running" | "unseen" | "idle";

/**
 * A row's state: an approval that waits first, then work, then news since
 * the person last looked. A chat they never opened counts from the moment
 * the assistant wrote into it, so its first result is news.
 */
export function leadThreadState(thread: LeadThread, seen: Readonly<Record<string, number>>): ThreadState {
  if (thread.waiting) return "waiting";
  if (thread.running) return "running";
  return thread.updated_ms > (seen[thread.session_id] ?? thread.briefed_ms) ? "unseen" : "idle";
}

function title(thread: LeadThread, fallback: string): string {
  return thread.cli_title.trim() || thread.title.trim() || fallback;
}

/**
 * The chats in the Agentic IDE the assistant sent a task to, the newest
 * task first. A row says whether its agent still works, waits for an
 * approval, or has brought something the person has not seen, and opens
 * that chat in the IDE.
 */
export function PanelActivity({ name }: { name: string }) {
  const t = useT();
  const seen = useIdeThreadsStore((s) => s.seen);
  const [open, setOpen] = useState(false);
  const threads = useQuery({
    queryKey: ["sidebar", "lead-threads"],
    queryFn: () => fetchLeadThreads(ACTIVITY_READ),
    staleTime: 5_000,
    refetchInterval: import.meta.env.MODE === "test" ? false : 15_000,
    retry: false,
  });
  const rows = threads.data ?? [];
  const shown = open ? rows : rows.slice(0, ACTIVITY_SHOWN);

  return (
    <PanelSection id="activity" title={t("sidebar.recent_activity")}>
      {shown.map((thread) => {
        const state = leadThreadState(thread, seen);
        const label = title(thread, t("sidebar.activity_untitled"));
        const note = state === "idle" ? "" : t(`sidebar.activity_${state}`);
        return (
          <button key={thread.session_id} type="button" data-testid={`assistant-activity-${thread.session_id}`} data-state={state}
            onClick={() => openCodingThread(thread.session_id)} title={note ? `${label} · ${note}` : label}
            className={PANEL_ROW_BUTTON}>
            {state === "running" ? (
              <LoaderCircle aria-hidden strokeWidth={1.75} className={cn(PANEL_ICON, "text-success motion-safe:animate-spin")} />
            ) : state === "waiting" ? (
              <Hand aria-hidden strokeWidth={1.75} className={cn(PANEL_ICON, "text-warning")} />
            ) : (
              <MessageCircle aria-hidden strokeWidth={1.75} className={PANEL_ICON} />
            )}
            <span className="min-w-0 flex-1 truncate text-sm text-foreground">{label}</span>
            {note && <span className="sr-only">{note}</span>}
            {state === "unseen" && <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-info" />}
          </button>
        );
      })}
      {rows.length === 0 && (
        <PanelEmpty testId="assistant-activity-empty">
          {threads.isLoading ? t("common.loading") : fill(t("sidebar.recent_activity_empty"), { assistant: name })}
        </PanelEmpty>
      )}
      {rows.length > ACTIVITY_SHOWN && (
        <ShowMore testId="assistant-activity-more" open={open} onToggle={() => setOpen((value) => !value)} />
      )}
    </PanelSection>
  );
}
