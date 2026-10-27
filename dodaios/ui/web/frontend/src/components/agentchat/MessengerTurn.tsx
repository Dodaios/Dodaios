import { memo, useEffect, useMemo, useState, type ReactNode } from "react";
import { BookmarkPlus, CircleAlert, Clock3, Feather, NotebookPen, RotateCcw, SlidersHorizontal } from "lucide-react";
import { ChatMarkdown } from "./ChatMarkdown";
import { CredentialCard } from "./CredentialCard";
import { QuestionCard } from "./QuestionCard";
import { ApprovalActionCard, type ApprovalDecide } from "./actionCard/ApprovalActionCard";
import type { TurnItem } from "./reduce";
import { actionNoticeOf, type ActionNotice } from "./messengerPresence";
import { BotStage, useDoneFlourish } from "./botStage/BotStage";
import { ActivityLine } from "./activity/ActivityLine";
import type { NameOf } from "./activity/activityModel";
import { WorkDisclosure } from "./activity/WorkDisclosure";
import { PROSE, THREAD_MEDIA } from "@/components/agentic/threads/ThreadTimeline";
import { SubagentCard } from "@/components/agentic/threads/ThreadSubagents";
import { isSubagentCall } from "@/components/agentic/threads/subagents";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { turnErrorText } from "./turnError";

/**
 * One agent turn read like a messenger conversation. The agent's messages
 * are grey bubbles; what it changed for the person (a routine, a rule, a
 * saved skill) is a quiet centred line between them; while it works, its
 * own face plays a little scene of what it is doing on a stage below
 * (BotStage) with one paced phrase for the step it is on (ActivityLine),
 * and hops once when the turn is done. No reasoning and no work log in the
 * conversation: the agent's own messages say what is happening, and one
 * quiet line under the turn (WorkDisclosure) opens the whole trace in the
 * work inspector.
 */
export const MessengerTurn = memo(function MessengerTurn({ turn, avatar, color, onDecide, memoryLinks, nameOf, peerFace, onShowWork, workOpen = false, onRetry }: {
  turn: TurnItem;
  /** The agent's face at 30 px; it plays the scenes. */
  avatar: ReactNode;
  /** The agent's colour, for the accents of the scenes. */
  color: string;
  onDecide: ApprovalDecide;
  /** Memory receipts posted after the turn: each a "Noted" quill line that opens the file. */
  memoryLinks?: MemoryLink[];
  /** A teammate's roster id or name → the name the activity line says. */
  nameOf?: NameOf;
  /** A teammate's face beside "Writing to …". */
  peerFace?: (peer: string) => ReactNode;
  /** Opens this turn's work in the inspector; without it the turn shows no "show work" line. */
  onShowWork?: () => void;
  /** The inspector shows this turn right now. */
  workOpen?: boolean;
  /** Sends the person's last message again; a failed turn offers it as "Retry". */
  onRetry?: () => void;
}) {
  const t = useT();
  const textLength = useMemo(() => turn.blocks.reduce((n, block) => n + (block.kind === "text" ? block.text.length : 0), 0), [turn.blocks]);
  const hasText = textLength > 0 && turn.blocks.some((block) => block.kind === "text" && block.text.trim());
  const flourish = useDoneFlourish(turn.status === "running", turn.status === "done");
  const running = turn.status === "running";
  // A turn the runtime ended with an error, or that ended silent with an
  // error on record, failed: it says why, whatever runtime ran it.
  const failed = turn.status === "error" || (turn.status === "done" && !hasText && Boolean(turn.error));
  const work = onShowWork ? <WorkDisclosure turn={turn} open={workOpen} onOpen={onShowWork} /> : null;
  let noteIndex = 0;
  return <div className="flex min-w-0 flex-col gap-1.5" data-testid="messenger-turn" data-status={turn.status}>
    {turn.blocks.map((block) => {
      if (block.kind === "text") {
        return block.text.trim() ? <MessageBubble key={block.id} text={block.text} /> : null;
      }
      if (block.kind !== "tool") return null;
      if (block.credential) return <CredentialCard key={block.callId} credential={block.credential} />;
      if (block.question) return <QuestionCard key={block.callId} question={block.question} />;
      // Open, the card asks; answered, it stays as the one line that says what happened.
      if (block.approval) return <ApprovalActionCard key={block.callId} block={block} onDecide={onDecide} />;
      if (isSubagentCall(block)) return <SubagentCard key={block.callId} block={block} turn={turn} />;
      const notice = actionNoticeOf(block);
      if (!notice) return null;
      // The turn's own "Noted" lines open its memory receipts first, in order.
      const link = notice.icon === "note" ? memoryLinks?.[noteIndex++] : undefined;
      return <ActionLine key={block.callId} notice={notice} link={link} />;
    })}
    {memoryLinks?.slice(noteIndex).map((link) => <ActionLine key={`memory:${link.key}`} notice={NOTED} link={link} />)}
    {/* While it works: the face and one paced phrase for the step it is on,
        with the live work one click away. Once done: a short flourish. */}
    {running ? <div className="flex min-w-0 flex-wrap items-center gap-x-2">
      <ActivityLine turn={turn} avatar={avatar} color={color} nameOf={nameOf} peerFace={peerFace} />
      {work}
    </div> : flourish ? <BotStage presence="done" seed={turn.id} avatar={avatar} color={color} /> : null}
    {failed && <TurnFailure reason={turnErrorText(turn.error, t) || t("thread_turn.failed_no_reason")} onRetry={onRetry} />}
    {turn.status === "cancelled" && <SystemLine>{t("thread_turn.stopped")}</SystemLine>}
    {turn.status === "done" && !failed && !hasText && !flourish && <SystemLine>{t("thread_turn.no_answer")}</SystemLine>}
    {!running ? work : null}
  </div>;
});

/** How long a sent message may wait for its turn before the stage stops reading it. */
const AWAIT_MS = 90_000;

/**
 * The person's message is in and the agent's turn has not started yet: its
 * face reads the message, so the chat never sits silent after a send.
 */
export function AwaitingTurn({ since, seed, avatar, color }: { since: number; seed: string; avatar: ReactNode; color: string }) {
  const [, tick] = useState(0);
  const left = AWAIT_MS - (Date.now() - since);
  const waiting = left > 0;
  useEffect(() => {
    if (!waiting) return;
    const id = window.setTimeout(() => tick((n) => n + 1), left + 50);
    return () => window.clearTimeout(id);
    // `left` shrinks every render; only the start of the wait matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [waiting, since]);
  return waiting ? <BotStage presence="reading" seed={seed} avatar={avatar} color={color} /> : null;
}

/** One message of the agent's: a grey bubble on the left. */
export function MessageBubble({ text }: { text: string }) {
  return <div className="flex min-w-0" data-testid="agent-message-bubble">
    <div className="jarvis-chat-in min-w-0 max-w-[min(85%,42rem)] rounded-[20px] px-4 py-2.5">
      <div className={cn(PROSE, THREAD_MEDIA, "py-0")}><ChatMarkdown text={text} /></div>
    </div>
  </div>;
}

/** A failed turn: the reason the runtime gave, and one click to send the message again. */
export function TurnFailure({ reason, onRetry }: { reason: string; onRetry?: () => void }) {
  const t = useT();
  return <div role="alert" data-testid="turn-failure"
    className="flex min-w-0 max-w-[min(85%,42rem)] items-start gap-2 rounded-2xl border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
    <CircleAlert aria-hidden className="mt-px h-3.5 w-3.5 shrink-0" />
    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
      <span className="font-medium">{t("thread_turn.failed_title")}</span>
      <span className="[overflow-wrap:anywhere] text-destructive/90" data-testid="turn-failure-reason">{reason}</span>
    </div>
    {onRetry ? <button type="button" onClick={onRetry} data-testid="turn-retry"
      className="flex shrink-0 items-center gap-1 rounded-md border border-destructive/40 px-2 py-0.5 font-medium transition-colors hover:bg-destructive/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <RotateCcw aria-hidden className="h-3 w-3" />
      {t("thread_turn.retry")}
    </button> : null}
  </div>;
}

function SystemLine({ children }: { children: ReactNode }) {
  return <p className="py-1 text-center text-xs text-muted-foreground">{children}</p>;
}

const NOTICE_ICON: Record<ActionNotice["icon"], typeof Clock3> = {
  routine: Clock3,
  rule: BookmarkPlus,
  skill: NotebookPen,
  settings: SlidersHorizontal,
  note: Feather,
};

export interface MemoryLink {
  key: string;
  /** What the line opens ("Memory updated · USER.md"), as its tooltip. */
  title: string;
  onOpen: () => void;
}

const NOTED: ActionNotice = { key: "note_saved", subject: "", icon: "note" };

/** A "Noted" quill line that opens a memory file, for a receipt with no turn of its own. */
export function NotedLine({ link }: { link: MemoryLink }) {
  return <ActionLine notice={NOTED} link={link} />;
}

/**
 * "Created: Routine  ⏱ Daily contributor check" — centred, quiet, not a
 * message. With a memory link it is a button that opens the changed file.
 */
function ActionLine({ notice, link }: { notice: ActionNotice; link?: MemoryLink }) {
  const t = useT();
  const Icon = NOTICE_ICON[notice.icon];
  const body = <>
    <span>{t(`messenger_turn.${notice.key}`)}</span>
    <Icon aria-hidden className="h-3.5 w-3.5 shrink-0" />
    {notice.subject ? <span className="text-foreground-secondary">{notice.subject}</span> : null}
  </>;
  if (link) {
    return <div className="flex justify-center py-1">
      <button type="button" onClick={link.onOpen} title={link.title} aria-label={link.title}
        className="flex flex-wrap items-center justify-center gap-x-1.5 rounded-md px-1.5 text-center text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        data-testid="messenger-action" data-memory-link={link.key}>
        {body}
      </button>
    </div>;
  }
  return <p className="flex flex-wrap items-center justify-center gap-x-1.5 py-1 text-center text-xs text-muted-foreground" data-testid="messenger-action">
    {body}
  </p>;
}
