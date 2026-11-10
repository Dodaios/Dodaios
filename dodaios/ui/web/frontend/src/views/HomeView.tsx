import { lazy, Suspense, useState } from "react";
import { PanelRightOpen } from "lucide-react";

import { useT } from "@/i18n";
import { useHomeStore } from "@/store/home";
import { AssistantChat } from "@/components/home/AssistantChat";

// The activity panel is not needed for first paint.
const LeadActivityPanel = lazy(() =>
  import("@/components/home/LeadActivityPanel").then((m) => ({ default: m.LeadActivityPanel })),
);

const PANEL_KEY = "dodaios.home.activity.v1";

function readOpen(): boolean {
  try {
    return localStorage.getItem(PANEL_KEY) !== "closed";
  } catch {
    return true;
  }
}

/**
 * The front page — the "chats" section.
 *
 * ONE endless conversation with the assistant, with a voice mode inside it
 * (components/home/AssistantChat), and on wide windows an activity panel on
 * the right: what waits on the person, what runs, what finished, and the
 * morning brief. `data-surface` says which mode the chat is in (store/home.ts).
 */
export function HomeView() {
  const t = useT();
  const surface = useHomeStore((s) => s.surface);
  const agentChatId = useHomeStore((s) => s.agentChatId);
  const [open, setOpen] = useState(readOpen);
  const remember = (next: boolean) => {
    setOpen(next);
    try { localStorage.setItem(PANEL_KEY, next ? "open" : "closed"); }
    catch { /* Storage denied: keep the choice for this visit. */ }
  };
  const showPanel = surface === "chat" && !agentChatId;
  return (
    <div className="flex h-full min-h-0" data-testid="home-view" data-surface={surface}>
      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        <AssistantChat />
        {showPanel && !open && (
          <button type="button" onClick={() => remember(true)} data-testid="lead-activity-open"
            aria-label={t("home.activity.open")} title={t("home.activity.open")}
            className="absolute right-3 top-3 hidden rounded-md p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:block">
            <PanelRightOpen aria-hidden className="h-4 w-4" />
          </button>
        )}
      </div>
      {showPanel && open && (
        <div className="hidden lg:flex">
          <Suspense fallback={null}>
            <LeadActivityPanel onClose={() => remember(false)} />
          </Suspense>
        </div>
      )}
    </div>
  );
}
