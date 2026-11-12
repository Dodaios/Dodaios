import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { PanelRightOpen } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useHomeStore } from "@/store/home";
import { useAgentChatStore } from "@/store/agentChat";
import { AssistantChat } from "@/components/home/AssistantChat";
import { startNewTextChat } from "@/lib/newChat";
import {
  hasActivityDemand,
  panelOpen,
  readPanelChoice,
  writePanelChoice,
  type PanelChoice,
} from "@/components/home/activityDemand";

// Neither panel is needed for first paint.
// Who the assistant is and what belongs to it; reads its routines, files and skills.
const AssistantPanel = lazy(() => import("@/components/home/AssistantPanel"));
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
 * (components/home/AssistantChat), and on wide windows one panel on the
 * right. It is the assistant's own panel: its face, what it is doing right
 * now, the ways to reach it, its computers, the chats it handed a task to
 * and the files it made (components/home/AssistantPanel). The activity
 * panel takes that place while it is open: what waits on the person, what
 * runs, what finished, and the morning brief. A running call shows as a
 * card over the conversation.
 *
 * The activity panel opens only when the person opens it, and stays until
 * they close it; the choice is remembered under `dodaios.home.activity.v1`.
 * Work that runs does not open it: the assistant's panel stays and says
 * what it is doing, and the open button wears a small live dot while
 * something waits on the person or work runs
 * (components/home/activityDemand).
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
  const open = showPanel && panelOpen(choice);
  const { mounted, shown } = usePresence(open);
  /** From an earlier chat on the stage back to the one conversation. */
  const backToConversation = () => {
    useHomeStore.getState().setSurface("chat");
    startNewTextChat();
  };
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
      {showPanel && !mounted && (
        <div data-testid="assistant-panel-frame" className="hidden lg:flex">
          <Suspense fallback={null}>
            <AssistantPanel onConversation={backToConversation} />
          </Suspense>
        </div>
      )}
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
