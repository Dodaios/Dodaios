import { Fragment, memo, useMemo, type ReactNode } from "react";
import { ChatMarkdown, MediaPreview, mediaKind } from "@/components/agentchat/ChatMarkdown";
import { FileText, ImageIcon } from "lucide-react";
import { InternalMessageRun, groupInternalRuns, type InternalRunItem, type RunFace } from "./InternalMessageRun";
import { CodingThreadActivity } from "@/components/agentic/threads/CodingThreadLink";
import { codingThreadOf, foldRepeatedThreadStatus } from "@/components/agentic/threads/openCodingThread";
import { MessageWithChips } from "./ToolChoiceChips";
import { MemoryLearnedNotice } from "./MemoryLearnedNotice";
import { ReminderDueNotice } from "./reminders/ReminderDueNotice";
import { TasksCapturedCard } from "./reminders/TasksCapturedCard";
import { ProviderLogo } from "@/components/providers/ProviderLogo";
import { effortLabel } from "./AgentComposer";
import { livePetState, TurnTrace, type Decide, type TraceLook } from "./WorkTrace";
import { LeadReply, REPLY_PROSE } from "./LeadReply";
import { PetMark } from "@/components/pets/PetMark";
import { PetStageContext } from "@/components/pets/petStage";
import type { PetState } from "@/lib/petStates";
import type { TimelineItem, TurnItem, TextBlock } from "./reduce";
import { TraceMessageLine } from "./TraceTimeline";
import { attachTurnMessages, type TraceMessage } from "./turnMessages";
import { useI18nStore, useT } from "@/i18n";
import { societyResultHeadline, societyResultText } from "@/lib/skipReasons";
import { localeForUiLanguage } from "@/components/runs/format";
import { cn } from "@/lib/utils";

/** Shared transcript shell; the work trace owns all execution presentation. */
export function AgentTimeline({
  items,
  assistantName,
  providerLabel,
  modelLabel,
  onDecide,
  recipientName,
  agentsById,
  bubbles = false,
  traceLook = "rail",
  traceCompanion = false,
  traceFace,
}: {
  items: TimelineItem[];
  assistantName: string;
  providerLabel: (providerId: string) => string;
  /** The model's readable name; the raw id when absent. */
  modelLabel?: (providerId: string, modelId: string) => string;
  onDecide: Decide;
  /** Who an internal agent message was sent to — the chat owner (defaults to the assistant). */
  recipientName?: string;
  /** Sender faces by agent id, where the caller has a roster. */
  agentsById?: Record<string, RunFace>;
  /**
   * The front page's conversation look: two people writing to each other.
   * Your words in a soft bubble on the right; the assistant's answer as its
   * own messages on the left, one per paragraph, with its pet standing at
   * the foot of the newest one; a quiet centred time stamp wherever the
   * conversation paused. The work behind an answer folds into one line above
   * it. The Agentic IDE keeps the labelled document look (the default).
   */
  bubbles?: boolean;
  /** How turns draw their work; the Agentic IDE keeps the classic rows. */
  traceLook?: TraceLook;
  /** Jarvis's own chat: live traces show the user's pet at work. */
  traceCompanion?: boolean;
  /** An agent's own chat: live traces show that agent's face (or the pet it wears) at work. */
  traceFace?: ReactNode;
}) {
  const t = useT();
  // On the rail look an agent's answer to a working turn is a quiet line in
  // that turn's trace, so the reply stays the last thing in the chat.
  const { items: shown, messagesByTurn } = useMemo(() => {
    // A coding thread's unchanged status is one row, however often it arrived.
    const folded = foldRepeatedThreadStatus(items);
    return traceLook === "rail" ? attachTurnMessages(folded) : { items: folded, messagesByTurn: NO_MESSAGES };
  }, [items, traceLook]);
  const stamps = bubbles ? timeStamps(shown) : null;
  // The assistant's pet stands beside its newest turn only.
  const latestTurnId = useMemo(() => {
    if (!bubbles) return null;
    for (let i = shown.length - 1; i >= 0; i--) if (shown[i].type === "turn") return shown[i].id;
    return null;
  }, [bubbles, shown]);
  // Back-to-back agent-to-agent messages read as one centred line each.
  const rows = useMemo(
    () => groupInternalRuns(shown, (item) => !codingThreadOf(item.message.sender_id)),
    [shown],
  );
  return (
    <>
      {rows.map((item) => {
        const stamp = stamps?.get(item.id);
        const node = renderItem(item);
        return stamp ? (
          <Fragment key={item.id}>
            <div className="flex justify-center pt-2" data-testid="agent-time-stamp" aria-hidden>
              <span className="text-xs font-medium text-muted-foreground">{stamp}</span>
            </div>
            {node}
          </Fragment>
        ) : node;
      })}
    </>
  );

  function renderItem(item: TimelineItem | InternalRunItem) {
    if (item.type === "internal_run") {
      return (
        <InternalMessageRun
          key={item.id}
          run={item}
          agentsById={agentsById}
          recipientName={recipientName ?? assistantName}
        />
      );
    }
    if (item.type === "internal" && codingThreadOf(item.message.sender_id)) {
      return <CodingThreadActivity key={item.id} label={item.message.text}
        threadId={codingThreadOf(item.message.sender_id)} failed={item.message.status === "failed"} />;
    }
    if (item.type === "internal") {
      return <InternalMessageRun key={item.id} run={{ type: "internal_run", id: item.id, items: [item] }}
        agentsById={agentsById} recipientName={recipientName ?? assistantName} />;
    }
    if (item.type === "user") {
      if (item.origin === "control") return <div key={item.id} data-message-id={item.id} className="text-xs text-muted-foreground">{t("slash.control_turn")}{item.attachments.map((file) => <span key={file.name} className="ml-2">{file.name}</span>)}</div>;
      if (item.origin === "background") {
        // An earlier request coming back after other messages: the line
        // names it, so the answer below is read as that request's result.
        return (
          <div
            key={item.id}
            data-message-id={item.id}
            data-testid="background-result"
            className="mx-auto max-w-[85%] text-center text-xs text-muted-foreground"
          >
            {t("society.chat.background_result")} · {item.text}
          </div>
        );
      }
      return (
        <div
          key={item.id}
          className="flex justify-end"
          data-testid="agent-message-user"
          data-message-id={item.id}
        >
          <div
            className={cn(
              "text-[15px] leading-[23px]",
              bubbles
                ? "jarvis-user-bubble lead-bubble-own max-w-[80%] px-4 py-2"
                : "jarvis-user-bubble max-w-[85%] rounded-lg px-4 py-3",
            )}
          >
            <MessageWithChips text={item.text} choices={item.toolChoices ?? []} />
            {item.attachments.length > 0 && (
              <div
                data-testid="agent-message-attachments"
                className={cn("flex flex-wrap gap-row", item.text && "mt-2.5")}
              >
                {item.attachments.map((file) =>
                  // The picture itself, where there is one to fetch: a
                  // screenshot dropped on a pane is a thing the person
                  // wants to SEE in their turn, not a file name with an
                  // icon (maintainer, 2026-08-27). A file with no url —
                  // a document, or the front page's chat, whose drops
                  // are read and not stored — keeps the chip.
                  file.url && (mediaKind(file.url) === "video" || mediaKind(file.url) === "audio") ? (
                    <MediaPreview key={file.name} src={file.url} label={file.name} kind={mediaKind(file.url)!} />
                  ) : (file.kind === "image" || (file.url && mediaKind(file.url) === "image")) && file.url ? (
                    <span key={file.name} data-testid="agent-message-image" className="min-w-0 max-w-full">
                      <MediaPreview src={file.url} label={file.name} kind="image" />
                    </span>
                  ) : (
                  <span
                    key={file.name}
                    // The receipt says whether the model could actually
                    // READ it. "sent" and "could not be read" are the two
                    // outcomes, and the second happens for real wherever no
                    // provider can see an image.
                    title={
                      file.describedBy === "none"
                        ? t("agent_chat.attach_not_described")
                        : file.name
                    }
                    // No box. The user bubble is the loudest surface the
                    // ladder has, so a chip inside it has nowhere to step
                    // up to; the icon and the mono name carry the chip's
                    // whole job on their own.
                    className="flex items-center gap-1.5 text-micro opacity-80"
                  >
                    {file.kind === "image" ? (
                      <ImageIcon className="h-3 w-3 shrink-0" aria-hidden />
                    ) : (
                      <FileText className="h-3 w-3 shrink-0" aria-hidden />
                    )}
                    <span className="max-w-[12rem] truncate font-mono">{file.name}</span>
                  </span>
                  ),
                )}
              </div>
            )}
          </div>
        </div>
      );
    }
    if (item.type === "error") {
      return (
        <div
          key={item.id}
          data-message-id={item.id}
          // A small fault mark on a normal surface, the sentence in the
          // page's own ink. A red panel, or a red sentence, makes the failure
          // the brightest object on the screen and buries what it says under
          // what it looks like.
          role="alert"
          className="trace-note mx-auto"
        >
          <span aria-hidden className="trace-flag" />
          <span className="min-w-0">{item.text}</span>
        </div>
      );
    }
    if (item.type === "notice") {
      if (item.kind === "native_goal_verdict") return <p key={item.id} className="text-xs text-muted-foreground">{t("slash.verifying")}</p>;
      if (item.kind === "message_queued") {
        // A message typed while a turn is still answering: it starts next.
        return (
          <p key={item.id} data-message-id={item.id} data-testid="message-queued"
            className="flex justify-end py-1 text-xs text-muted-foreground">
            {t("society.chat.message_waiting")} · {item.text}
          </p>
        );
      }
      if (item.kind === "message_dequeued") {
        return (
          <p key={item.id} data-message-id={item.id} role="alert"
            className="flex justify-end py-1 text-xs text-destructive">
            {t("society.chat.message_not_sent").replace("{0}", item.text)}
          </p>
        );
      }
      if (item.kind === "memory_learned") return <MemoryLearnedNotice key={item.id} item={item} />;
      if (item.kind === "reminder_due") return <ReminderDueNotice key={item.id} item={item} />;
      if (item.kind === "tasks_captured") return <TasksCapturedCard key={item.id} item={item} />;
      if (item.kind === "context_reset") {
        return (
          <div key={item.id} data-message-id={item.id} data-testid="context-reset"
            className="flex items-center gap-3 py-2 text-xs text-muted-foreground">
            <span className="h-px flex-1 bg-border" aria-hidden />
            {t("society.chat.fresh_start_line")}
            <span className="h-px flex-1 bg-border" aria-hidden />
          </div>
        );
      }
      if (item.kind === "background_result_lost") {
        return (
          <p key={item.id} data-message-id={item.id} role="alert"
            className="mx-auto max-w-[85%] py-1 text-center text-xs text-destructive">
            {t("society.chat.background_result_lost").replace("{0}", item.text)}
          </p>
        );
      }
      if (item.kind === "coding_thread") {
        const started = t("society.chat.coding_thread_started").replace("{0}", String(item.data.agent ?? ""));
        return <CodingThreadActivity key={item.id} label={`${started} · ${String(item.data.title ?? "")}`}
          threadId={String(item.data.thread_id ?? "")} />;
      }
      // The society reporting back on a task Jarvis handed out: the
      // agent's name as the headline, its summary underneath. Muted and
      // centred like a stamp — it is not Jarvis speaking.
      const headline =
        item.kind === "society_result"
          ? societyResultHeadline(t, item)
          : item.agentName;
      return (
        <div
          key={item.id}
          data-message-id={item.id}
          className="mx-auto flex max-w-[85%] flex-col gap-0.5 rounded-lg bg-card px-4 py-3 text-body"
        >
          {headline ? <span className="font-medium text-foreground">{headline}</span> : null}
          {item.text ? <ChatMarkdown text={item.kind === "society_result" ? societyResultText(t, item) : item.text} className="text-muted-foreground" /> : null}
        </div>
      );
    }
    return (
      <Turn
        key={item.id}
        turn={item}
        assistantName={assistantName}
        providerLabel={providerLabel(item.provider)}
        modelName={item.model ? (modelLabel?.(item.provider, item.model) || item.model) : ""}
        onDecide={onDecide}
        bubbles={bubbles}
        traceLook={traceLook}
        traceCompanion={traceCompanion}
        traceFace={traceFace}
        latest={item.id === latestTurnId}
        messages={messagesByTurn.get(item.id)}
      />
    );
  }
}

/** A pause this long between two messages earns a new time stamp. */
const STAMP_GAP_MS = 20 * 60 * 1000;

function itemTime(item: TimelineItem): number {
  return item.type === "turn" ? item.startedMs : item.tsMs;
}

/**
 * Which items open with a time stamp, and what it says: the first one, and
 * every one after a pause of {@link STAMP_GAP_MS}. Today shows the clock
 * only; any other day leads with the date, the way a messenger does.
 */
export function timeStamps(items: TimelineItem[], now: Date = new Date()): Map<string, string> {
  const out = new Map<string, string>();
  let last = 0;
  for (const item of items) {
    const ts = itemTime(item);
    if (!ts || !Number.isFinite(ts)) continue;
    if (!last || ts - last >= STAMP_GAP_MS) out.set(item.id, stampLabel(new Date(ts), now));
    last = ts;
  }
  return out;
}

function stampLabel(at: Date, now: Date): string {
  const locale = localeForUiLanguage(useI18nStore.getState().ui);
  const time = at.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
  if (at.toDateString() === now.toDateString()) return time;
  const date = at.toLocaleDateString(locale, {
    month: "short",
    day: "numeric",
    ...(at.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
  return `${date}, ${time}`;
}

const NO_MESSAGES = new Map<string, TraceMessage[]>();

const Turn = memo(function Turn({ turn, assistantName, providerLabel, modelName, onDecide, bubbles = false, traceLook, traceCompanion = false, traceFace, latest = false, messages }: {
  turn: TurnItem; assistantName: string; providerLabel: string; modelName?: string; onDecide: Decide; bubbles?: boolean; traceLook: TraceLook; traceCompanion?: boolean; traceFace?: ReactNode;
  /** The newest turn of the conversation: the assistant's face stands beside it. */
  latest?: boolean;
  /** Agent messages that arrived while this turn worked. */
  messages?: TraceMessage[];
}) {
  const t = useT();
  const extras = useMemo(
    () => messages?.map((message) => ({ key: message.id, node: <TraceMessageLine message={message} /> })),
    [messages],
  );
  const background = turn.background && turn.background.length > 0 ? (
    <p className="text-xs text-muted-foreground" data-testid="turn-background">
      {t("society.chat.background_running").replace("{0}", turn.background.join(", "))}
    </p>
  ) : null;
  if (bubbles) {
    // The pet plays what the assistant is doing while the turn runs and
    // rests beside its last message afterwards. A turn that waits for the
    // person is not working, so the pet waits too.
    const waiting = turn.blocks.some((block) => block.kind === "tool" && block.approval?.decision === null);
    const pet: PetState = turn.status === "running" && !waiting ? livePetState(turn.blocks) : "idle";
    const face = traceFace
      ? <PetStageContext.Provider value={pet}>{traceFace}</PetStageContext.Provider>
      : traceCompanion ? <PetMark size={32} state={pet} /> : null;
    return <div className="lead-turn" data-testid="agent-turn" data-look="lead" data-message-id={turn.id} data-status={turn.status}>
      <div className="lead-face-lane" aria-hidden>
        {latest && face ? <span className="lead-face" data-testid="lead-face" data-pet={pet}>{face}</span> : null}
      </div>
      <div className="lead-turn-body">
        <TurnTrace turn={turn} look={traceLook} messenger extras={extras} onDecide={onDecide}
          renderText={(text, id) => <Prose block={{ kind: "text", text, id }} />}
          renderAnswer={(text, _id, live) => <LeadReply text={text} live={live} />} />
        {background}
      </div>
    </div>;
  }
  return <div className="flex min-w-0 flex-col gap-3" data-testid="agent-turn" data-message-id={turn.id} data-status={turn.status}>
    {!bubbles && (
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">{assistantName}</span>
        <ProviderLogo providerId={turn.provider} label={providerLabel} size="sm" />
        <span>{providerLabel}{turn.model ? ` · ${modelName || turn.model}` : ""}</span>
        {turn.effort ? <span>{effortLabel(turn.effort, t)}</span> : null}
      </div>
    )}
    <TurnTrace turn={turn} look={traceLook} companion={traceCompanion} face={traceFace} extras={extras} onDecide={onDecide} renderText={(text, id) => <Prose block={{ kind: "text", text, id }} />} />
    {background}
  </div>;
});

function Prose({ block }: { block: TextBlock }) {
  if (!block.text.trim()) return null;
  return (
    <div
      data-testid="agent-text"
      className={REPLY_PROSE}
    >
      <ChatMarkdown text={block.text} />
    </div>
  );
}
