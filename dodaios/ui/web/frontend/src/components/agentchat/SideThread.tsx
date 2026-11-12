import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { CornerDownRight, Split, Square } from "lucide-react";

import { useT } from "@/i18n";
import { moveSideThreadToMain, stopSideThread } from "@/lib/agentChatApi";
import { createAgentChatStore, type AgentChatStoreHook } from "@/store/agentChat";
import { AgentChatStoreProvider, useAgentChat } from "./AgentChatStoreContext";
import { cn } from "@/lib/utils";
import { LeadReply, OWN_BUBBLE } from "./LeadReply";
import type { Decide } from "./WorkTrace";
import type { NoticeItem, TimelineItem } from "./reduce";

/** How a side thread's own conversation is drawn: the timeline it stands in draws it. */
export type RenderSideTimeline = (items: TimelineItem[], onDecide: Decide) => ReactNode;

const ENDED: Record<string, string> = {
  stopped: "society.chat.side_thread_stopped",
  failed: "society.chat.side_thread_failed",
  interrupted: "society.chat.side_thread_interrupted",
};

/**
 * A message the person sent while the conversation was still working on an
 * earlier one, and its answer.
 *
 * It reads like any other exchange of the chat: their bubble, then the reply.
 * The reply is written beside the running request, in a side thread (a chat
 * session of its own), so nothing waited. While it runs, its work and its
 * streaming answer come from that session; afterwards the answer stands on
 * the notice itself, so a reopened chat needs no second connection.
 */
export function SideThread({ item, renderTimeline }: { item: NoticeItem; renderTimeline: RenderSideTimeline }) {
  const t = useT();
  const parentId = useAgentChat((s) => s.activeSessionId);
  const sideId = String(item.data.side_id ?? "");
  const running = item.resolved === "";
  // A side thread seen while it ran keeps its work on screen after it ends:
  // the answer does not jump from a live turn to a plain reply.
  const [watched] = useState(running && sideId !== "");
  const [busy, setBusy] = useState<"" | "stop" | "move">("");
  const [problem, setProblem] = useState("");

  const act = async (what: "stop" | "move") => {
    if (!parentId || !sideId || busy) return;
    setBusy(what);
    setProblem("");
    try {
      if (what === "stop") await stopSideThread(parentId, sideId);
      else await moveSideThreadToMain(parentId, sideId);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy("");
    }
  };

  const answer = String(item.data.answer ?? "");
  // How one that was not answered ended; undefined while it runs and when it was.
  const ended: string | undefined = ENDED[item.resolved];
  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid="side-thread" data-message-id={item.id}
      data-status={running ? "running" : item.resolved}>
      <div className="flex justify-end" data-testid="agent-message-user">
        <div className={cn("text-[15px] leading-[23px] [overflow-wrap:anywhere]", OWN_BUBBLE)}>
          {item.text}
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span className="flex items-center gap-1" data-testid="side-thread-state">
          <Split aria-hidden className="h-3 w-3 shrink-0" />
          {t(running ? "society.chat.side_thread_running" : ended ?? "society.chat.side_thread_done")}
        </span>
        {running && (
          <>
            <button type="button" data-testid="side-thread-to-main" disabled={busy !== ""}
              title={t("society.chat.side_thread_to_main_title")} onClick={() => void act("move")}
              className="flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-foreground transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
              <CornerDownRight aria-hidden className="h-3 w-3" />
              {t("society.chat.side_thread_to_main")}
            </button>
            <button type="button" data-testid="side-thread-stop" disabled={busy !== ""}
              aria-label={t("society.chat.side_thread_stop")} title={t("society.chat.side_thread_stop")}
              onClick={() => void act("stop")}
              className="rounded-full p-1 transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
              <Square aria-hidden className="h-3 w-3" />
            </button>
          </>
        )}
      </div>
      {problem && <p role="alert" className="text-end text-xs text-destructive">{problem}</p>}
      {watched ? (
        <SideThreadLive sideId={sideId} running={running} renderTimeline={renderTimeline}
          fallback={answer ? <StaticReply text={answer} /> : null} />
      ) : answer ? (
        <StaticReply text={answer} />
      ) : null}
    </div>
  );
}

/** The finished answer, in the lane every reply of the conversation is written in. */
function StaticReply({ text }: { text: string }) {
  return (
    <div className="lead-turn" data-testid="side-thread-answer" data-look="lead">
      <div className="lead-face-lane" aria-hidden />
      <div className="lead-turn-body"><LeadReply text={text} live={false} /></div>
    </div>
  );
}

/**
 * The side thread's own session, read live: its work trace, its cards
 * (an approval, a question) and its answer as it is written. The cards answer
 * to this session, so the store is the side thread's own.
 */
function SideThreadLive({ sideId, running, renderTimeline, fallback }: {
  sideId: string; running: boolean; renderTimeline: RenderSideTimeline; fallback: ReactNode;
}) {
  const store = useMemo<AgentChatStoreHook>(
    // Never the chat on stage: a voice call must not continue in a side thread.
    () => createAgentChatStore("jarvis", `side:${sideId}`, { voice: false }),
    [sideId],
  );
  const wasRunning = useRef(running);
  useEffect(() => {
    store.getState().openSession(sideId);
    return () => store.getState().disconnect();
  }, [store, sideId]);
  useEffect(() => {
    // Its answer is complete and stays in the store; the socket is not needed any more.
    if (wasRunning.current && !running) store.getState().disconnect();
    wasRunning.current = running;
  }, [running, store]);
  const items = store((s) => s.timeline.items);
  const decide = store((s) => s.decide);
  // The person's message is the bubble above; here is only what answered it.
  const answering = useMemo(() => items.filter((entry) => entry.type !== "user"), [items]);
  if (answering.length === 0) return <>{fallback}</>;
  return (
    <AgentChatStoreProvider store={store}>
      <div className="flex min-w-0 flex-col gap-3" data-testid="side-thread-live">
        {renderTimeline(answering, (id, decision) => decide(id, decision))}
      </div>
    </AgentChatStoreProvider>
  );
}
