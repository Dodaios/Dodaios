import type { ReactNode } from "react";
import { ChevronRight, Clock3 } from "lucide-react";

import { useRoutineNavigation } from "@/components/society/chat/routineNavigation";
import { useT } from "@/i18n";
import { societyResultHeadline } from "@/lib/skipReasons";
import { cn } from "@/lib/utils";

import { ChatMarkdown } from "./ChatMarkdown";
import { LeadReply, REPLY_PROSE } from "./LeadReply";
import type { NoticeItem } from "./reduce";
import { routineResultTitle } from "./routineResult";

/**
 * Where a routine's result is drawn:
 *
 * - "lead": the front page's conversation look. The assistant's own grey
 *   message in its lane, like a normal answer (`LeadReply`) and like a
 *   reminder that came due (`ReminderDueMessage`).
 * - "messenger": an agent's own chat on its card. The caller passes the
 *   agent's message as that chat draws it (its `MessageBubble`) as
 *   `children`, so this module stays out of the thread code that bubble
 *   brings along.
 * - "document": every other timeline (the IDE, a run transcript): the words
 *   as reading type, under the same quiet line.
 */
export type RoutineResultLook = "lead" | "messenger" | "document";

/**
 * A routine's finished result, said by the agent that ran it, in its own
 * chat (see `routineResult.ts` for the notice). It reads as the agent's
 * message, not as a notice about background work: the person asked for this
 * routine, and its answer is what they wait for. One quiet line above the
 * words names the routine; when the run's own chat is known, that line opens
 * it (`RoutineChatHost` shows the run in the chat column, with a way back).
 */
export function RoutineResultMessage({ item, look, children }: {
  item: NoticeItem;
  look: RoutineResultLook;
  /** "messenger" only: the agent's message as its chat draws it. */
  children?: ReactNode;
}) {
  const words = item.text.trim() ? item.text : "";
  if (look === "lead") {
    return (
      <div className="lead-turn" data-testid="routine-result" data-look="lead" data-message-id={item.id}>
        <div className="lead-face-lane" aria-hidden />
        <div className="lead-turn-body">
          <RoutineLine item={item} className="ml-3" />
          {words ? <LeadReply text={words} live={false} /> : null}
        </div>
      </div>
    );
  }
  const prose = words ? <div className={REPLY_PROSE}><ChatMarkdown text={words} /></div> : null;
  return (
    <div className="flex min-w-0 flex-col gap-1.5" data-testid="routine-result" data-look={look} data-message-id={item.id}>
      {/* In the agent's chat the line starts where the bubble's words do; in a document, at the text's edge. */}
      <RoutineLine item={item} className={look === "messenger" ? "ml-3" : "-ml-1"} />
      {look === "messenger" ? (children ?? prose) : prose}
    </div>
  );
}

/** The line's own look: small and muted, so the message stays the thing that is read. */
const LINE = "inline-flex min-w-0 max-w-full items-center gap-1 self-start rounded px-1 py-0.5 text-xs text-muted-foreground";
/** The same line as a button: the run's chat is one click away. */
const PRESSABLE = "transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/**
 * "Routine · Daily issue check" above the words, or "Standing task: Meta ads
 * campaign" for a standing task's look (labelled with the task, as before);
 * a button when the run's chat is known.
 */
function RoutineLine({ item, className }: { item: NoticeItem; className?: string }) {
  const t = useT();
  const title = routineResultTitle(item);
  const standing = typeof item.data.standing_title === "string" && item.data.standing_title.trim() !== "";
  const label = standing
    ? societyResultHeadline(t, item)
    : title ? `${t("agent_chat.routine_result")} · ${title}` : t("agent_chat.routine_result");
  const sessionId = typeof item.data.session_id === "string" ? item.data.session_id.trim() : "";
  const content = (
    <>
      <Clock3 aria-hidden className="h-3 w-3 shrink-0" />
      <span className="min-w-0 truncate">{label}</span>
    </>
  );
  if (!sessionId) {
    return <p data-testid="routine-result-line" className={cn(LINE, className)}>{content}</p>;
  }
  const openWords = t("agent_chat.routine_result_open");
  const open = () => useRoutineNavigation.getState().open({
    agentId: item.agentId || String(item.data.agent_id ?? "") || "jarvis",
    sessionId,
    title: title || t("agent_chat.routine_result"),
    timestamp: item.tsMs,
  });
  return (
    // The name it is read by starts with what it shows, then says what a click does.
    <button type="button" onClick={open} title={openWords} aria-label={`${label} · ${openWords}`}
      data-testid="routine-result-line" className={cn(LINE, PRESSABLE, className)}>
      {content}
      <ChevronRight aria-hidden className="h-3 w-3 shrink-0" />
    </button>
  );
}
