/**
 * The selected routine run or agent conversation occupies the agent's chat
 * lane and loads only on navigation.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowLeft, Send, Square } from "lucide-react";
import { AgentTimeline } from "@/components/agentchat/AgentTimeline";
import { ChatMarkdown } from "@/components/agentchat/ChatMarkdown";
import { EMPTY_TIMELINE, reduceEvents, runningTurn, type TimelineItem } from "@/components/agentchat/reduce";
import { AgentChatStoreProvider } from "@/components/agentchat/AgentChatStoreContext";
import { fetchAgentChatSession } from "@/lib/agentChatApi";
import { createAgentChatStore, useAgentChatStore } from "@/store/agentChat";
import { useStickToBottom } from "@/hooks/useStickToBottom";
import { useT } from "@/i18n";
import { useRunLocale } from "@/components/runs/format";
import { legacyRoutineEvents, routineTask, type RoutineChatTarget } from "../chat/routineExecution";

function displayItems(items: TimelineItem[]): TimelineItem[] {
  return items.map((item) => item.type === "user" ? { ...item, text: routineTask(item.text) ?? item.text } : item);
}

/**
 * A run opens with the scheduler's instructions to the agent. The person
 * reads the routine's name there; the full prompt stays one click away.
 */
export function splitOpening(items: TimelineItem[]): { prompt: string | null; rest: TimelineItem[] } {
  const index = items.findIndex((item) => item.type === "user");
  const first = index >= 0 ? items[index] : null;
  const prompt = first && first.type === "user" ? routineTask(first.text) : null;
  if (prompt === null) return { prompt: null, rest: displayItems(items) };
  return { prompt, rest: displayItems(items.filter((_, i) => i !== index)) };
}

function RoutineOpening({ title, prompt }: { title: string; prompt: string }) {
  const t = useT();
  return <div className="ml-auto flex max-w-[min(85%,42rem)] flex-col gap-1 rounded-lg bg-card px-4 py-2.5 text-sm" data-testid="routine-opening">
    <p className="font-medium text-foreground">{title}</p>
    {prompt.trim() && prompt.trim() !== title.trim() ? <details className="text-xs text-muted-foreground">
      <summary className="cursor-pointer select-none">{t("society.routine_detail.full_prompt")}</summary>
      <ChatMarkdown text={prompt} className="mt-1 text-muted-foreground" />
    </details> : null}
  </div>;
}

/** Readable provider and model names from the chat catalog; the raw id until it loads. */
function useSeatLabels() {
  const catalog = useAgentChatStore((s) => s.catalog);
  const catalogStale = useAgentChatStore((s) => s.catalogStale);
  const loadCatalog = useAgentChatStore((s) => s.loadCatalog);
  useEffect(() => {
    if (!catalog || catalogStale) void loadCatalog();
  }, [catalog, catalogStale, loadCatalog]);
  const providerLabel = useCallback(
    (id: string) => catalog?.providers.find((p) => p.id === id)?.label ?? id,
    [catalog],
  );
  const modelLabel = useCallback(
    (providerId: string, modelId: string) =>
      catalog?.providers.find((p) => p.id === providerId)?.curated_models.find((m) => m.id === modelId)?.label
      ?? catalog?.providers.flatMap((p) => p.curated_models).find((m) => m.id === modelId)?.label
      ?? modelId,
    [catalog],
  );
  return { providerLabel, modelLabel };
}

export default function RoutineChat({ target, onClose, face }: {
  target: RoutineChatTarget; onClose: () => void;
  /** The agent's face for the live line of a running trace. */
  face?: ReactNode;
}) {
  const t = useT();
  const locale = useRunLocale();
  return <section className="flex h-full min-h-0 flex-1 flex-col bg-background p-4 text-foreground sm:p-6" data-testid="routine-chat" data-session-id={target.sessionId}>
    <header className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-border pb-3">
      <button type="button" className="flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground" onClick={onClose}><ArrowLeft size={14} />{t("society.routine_detail.back_to_agent")}</button>
      <div className="min-w-0 flex-1"><h3 className="truncate text-sm font-medium">{target.title}</h3>
        <time className="text-xs text-muted-foreground" dateTime={new Date(target.timestamp).toISOString()}>{new Date(target.timestamp).toLocaleString(locale)}</time>
      </div>
      <span className="text-xs text-muted-foreground">{t(target.kind === "conversation" ? "society.conversations.badge" : "society.routine_detail.background_chat")}</span>
    </header>
    {target.legacy ? <HistoricalExecution target={target} /> : <LiveExecution sessionId={target.sessionId} title={target.title} conversation={target.kind === "conversation"} face={face} />}
  </section>;
}

function HistoricalExecution({ target }: { target: RoutineChatTarget }) {
  const t = useT();
  const [snapshot, setSnapshot] = useState<{ name: string; items: TimelineItem[]; opening: string | null; resultInChat: boolean } | null>(null);
  const [error, setError] = useState("");
  const labels = useSeatLabels();
  useEffect(() => {
    let alive = true;
    void fetchAgentChatSession(target.sessionId).then(({ session, events }) => {
      if (!alive) return;
      const selected = legacyRoutineEvents(events, target);
      const { prompt: opening, rest } = splitOpening(reduceEvents(EMPTY_TIMELINE, selected).items);
      const items = rest.map((item) => item.type === "turn"
        ? { ...item, blocks: item.blocks.map((block) => block.kind === "tool" ? { ...block, approval: null } : block) } : item);
      const replies = items.flatMap((item) => item.type === "turn" ? item.blocks.flatMap((block) => block.kind === "text" ? [block.text] : []) : []).join("\n");
      setSnapshot({ name: session.title, items, opening, resultInChat: Boolean(target.result?.trim() && replies.includes(target.result.trim())) });
    }).catch((err) => { if (alive) setError(err instanceof Error ? err.message : String(err)); });
    return () => { alive = false; };
  }, [target]);
  return <>
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto py-4" data-testid="routine-historical-transcript">
      {!snapshot && !error && <p role="status">{t("tasks_view.loading_details")}</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {snapshot?.opening != null ? <RoutineOpening title={target.title} prompt={snapshot.opening} /> : null}
      {snapshot?.items.length ? <AgentTimeline items={snapshot.items} assistantName={snapshot.name} providerLabel={labels.providerLabel} modelLabel={labels.modelLabel} onDecide={async () => { /* Historical approvals are hidden; this transcript cannot act. */ }} /> : null}
      {(snapshot?.items.length === 0 && snapshot.opening == null || error) && <>
        <p className="text-sm text-muted-foreground">{t("society.routine_detail.trace_unavailable")}</p>
      </>}
      {(snapshot || error) && target.result && !snapshot?.resultInChat && <section className="space-y-2 border-t border-border pt-3" data-testid="routine-saved-result">
        <h4 className="text-xs font-medium text-muted-foreground">{t("society.routine_detail.saved_result")}</h4>
        <ChatMarkdown text={target.result} />
      </section>}
    </div>
    <p className="shrink-0 border-t border-border pt-3 text-xs text-muted-foreground">{t("society.routine_detail.historical_chat")}</p>
  </>;
}

function LiveExecution({ sessionId, title, conversation = false, face }: { sessionId: string; title: string; conversation?: boolean; face?: ReactNode }) {
  const t = useT();
  const label = (key: string) => t(`society.routine_detail.${key}`);
  const followUp = conversation ? t("society.conversations.follow_up") : label("follow_up");
  const [store] = useState(() => createAgentChatStore("society", "routine"));
  const timeline = store((state) => state.timeline);
  const { prompt: opening, rest: visibleItems } = useMemo(() => splitOpening(timeline.items), [timeline.items]);
  const labels = useSeatLabels();
  const session = store((state) => state.activeSession);
  const busy = store((state) => state.busy);
  const socketState = store((state) => state.socketState);
  const error = store((state) => state.lastError);
  const [message, setMessage] = useState("");
  const running = Boolean(runningTurn(timeline)) || busy;
  const ready = session?.session_id === sessionId && socketState === "open";
  const scroll = useStickToBottom();
  useEffect(() => {
    store.getState().openSession(sessionId);
    return () => store.getState().disconnect();
  }, [sessionId, store]);
  return <AgentChatStoreProvider store={store}>
    <div ref={scroll.rootRef} className="min-h-0 flex-1 overflow-y-auto py-4"><div ref={scroll.contentRef} className="space-y-3">
      {!ready && !error && <p role="status" className="text-sm">{t("tasks_view.loading_details")}</p>}
      {opening !== null ? <RoutineOpening title={title} prompt={opening} /> : null}
      <AgentTimeline items={visibleItems} assistantName={session?.title.split(" · ")[0] ?? ""} providerLabel={labels.providerLabel} modelLabel={labels.modelLabel} onDecide={store.getState().decide} traceFace={face} />
    </div></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <form className="mt-3 flex shrink-0 items-end gap-2" onSubmit={(event) => {
      event.preventDefault();
      if (!message.trim() || !ready || running) return;
      void store.getState().send(message).then(() => { if (!store.getState().lastError) setMessage(""); });
    }}>
      <textarea className="min-w-0 flex-1 rounded-lg border border-border bg-background p-2 text-sm" rows={2} aria-label={followUp} placeholder={followUp} value={message} onChange={(event) => setMessage(event.target.value)} />
      {running ? <button type="button" className="rounded p-2 hover:bg-secondary" aria-label={label("stop_run")} onClick={() => void store.getState().cancel()}><Square size={16} /></button>
        : <button type="submit" className="rounded p-2 hover:bg-secondary disabled:opacity-50" disabled={!ready || !message.trim()} aria-label={label("send")}><Send size={16} /></button>}
    </form>
  </AgentChatStoreProvider>;
}
