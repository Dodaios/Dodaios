import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { PanelRightOpen } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useHomeStore } from "@/store/home";
import { useAgentChatStore } from "@/store/agentChat";
import { AssistantChat } from "@/components/home/AssistantChat";
import {
  hasActivityDemand,
  panelOpen,
  readPanelChoice,
  writePanelChoice,
  type PanelChoice,
} from "@/components/home/activityDemand";

// The activity panel is not needed for first paint.
const LeadActivityPanel = lazy(() =>
  import("@/components/home/LeadActivityPanel").then((m) => ({ default: m.LeadActivityPanel })),
);

/** How long the panel takes to leave (index.css `--motion-exit`). */
const EXIT_MS = 150;

/**
 * Keeps the panel mounted while it leaves, so it can fade out instead of
 * vanishing. "in" one frame after mounting starts the arrival transition; a
 * reopen during the exit turns the same transition around.
 */
function usePresence(open: boolean): { mounted: boolean; shown: boolean } {
  const [mounted, setMounted] = useState(open);
  const [shown, setShown] = useState(open);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (open) {
      setMounted(true);
      const frame = window.requestAnimationFrame(() => setShown(true));
      return () => window.cancelAnimationFrame(frame);
    }
    setShown(false);
    timer.current = window.setTimeout(() => setMounted(false), EXIT_MS);
    return () => window.clearTimeout(timer.current);
  }, [open]);
  return { mounted, shown };
}

/**
 * The front page — the "chats" section.
 *
 * ONE endless conversation with the assistant, with a voice mode inside it
 * (components/home/AssistantChat), and on wide windows an activity panel on
 * the right: what waits on the person, what runs, what finished, and the
 * morning brief. A running call shows as a card over the conversation.
 *
 * The panel is closed on a quiet page and opens by itself once something
 * waits on the person or work runs (components/home/activityDemand). A
 * person who opened or closed it by hand keeps that choice — remembered
 * under `dodaios.home.activity.v1` — and a closed panel with something
 * waiting shows a small live dot on its open button instead.
 */
export function HomeView() {
  const t = useT();
  const agentChatId = useHomeStore((s) => s.agentChatId);
  const demand = useAgentChatStore((s) => hasActivityDemand(s.timeline.items));
  const [choice, setChoice] = useState<PanelChoice>(readPanelChoice);
  const remember = (next: "open" | "closed") => {
    setChoice(next);
    writePanelChoice(next);
  };
  const showPanel = !agentChatId;
  const open = showPanel && panelOpen(choice, demand);
  const { mounted, shown } = usePresence(open);
  return (
    <div className="flex h-full min-h-0" data-testid="home-view">
      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        <AssistantChat />
        {showPanel && !open && (
          <button type="button" onClick={() => remember("open")} data-testid="lead-activity-open"
            aria-label={t("home.activity.open")} title={demand ? t("design.activity.waiting") : t("home.activity.open")}
            className="absolute right-3 top-3 hidden rounded-md p-1.5 text-muted-foreground transition-colors duration-fast hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:block">
            <PanelRightOpen aria-hidden className="h-4 w-4" />
            {demand && (
              <span data-testid="lead-activity-live" aria-hidden
                className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-accent" />
            )}
          </button>
        )}
      </div>
      {showPanel && mounted && (
        <div
          data-testid="lead-activity-frame"
          data-state={shown ? "open" : "closed"}
          className={cn(
            "hidden transition-[opacity,transform] motion-reduce:transition-none lg:flex",
            shown
              ? "translate-x-0 opacity-100 duration-slow ease-out-soft"
              : "translate-x-3 opacity-0 duration-exit ease-in-soft",
          )}
        >
          <Suspense fallback={null}>
            <LeadActivityPanel onClose={() => remember("closed")} />
          </Suspense>
        </div>
      )}
    </div>
  );
}
