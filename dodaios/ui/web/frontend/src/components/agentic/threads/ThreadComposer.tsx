import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { ArrowUp, Hammer, ListChecks, Loader2, MessageCircleQuestion, ShieldAlert, Square, X } from "lucide-react";
import { ChatAttachmentStrip } from "@/components/agentchat/ChatAttachmentStrip";
import { ChatMarkdown } from "@/components/agentchat/ChatMarkdown";
import { ComposerTypeahead } from "@/components/agentchat/ComposerTypeahead";
import { DictationButton } from "@/components/agentchat/DictationButton";
import { runningTurn, type PendingApproval, type QuestionState, type Timeline, type ToolBlock, type TurnItem, type UserItem } from "@/components/agentchat/reduce";
import { releaseHeldFiles, useChatAttachments, type HeldFiles } from "@/components/agentchat/useChatAttachments";
import { useComposerDictation } from "@/components/agentchat/useComposerDictation";
import { useComposerTypeahead } from "@/components/agentchat/useComposerTypeahead";
import { fill, useT } from "@/i18n";
import { discardQueuedMessage, fetchAgentChatQueue, resumeAgentChatQueue, type AgentChatSession, type ApprovalDecision, type ChatAttachment, type PlanDecision } from "@/lib/agentChatApi";
import { joinProviderOptions, type ComposerDraft, type ProviderOption } from "@/store/agentChat";
import { cn } from "@/lib/utils";
import { effortLadder, snapEffort } from "@/lib/effortLadder";
import { AccessPicker, AgentModelPicker, EffortPicker, modelsOf } from "./ThreadPickers";
import { useRecalledMessages } from "./recalledMessages";
import { rememberSeat, rememberedSeat, threadAgents, useThreadChat } from "./threadModel";

/** Coding agents that take a message while they work: what is typed then steers the running turn. */
const STEERABLE_AGENTS = new Set(["claude-cli", "glm-cli"]);

/** Draft text per thread, so switching threads never loses a half-written message. */
const drafts = new Map<string, string>();

/**
 * The message sent last, with its files, when it went and where the thread
 * stood then, so Escape can take it back. Module-level: a thread's first
 * message swaps the empty-thread composer for the timeline one.
 */
interface SentMessage {
  text: string;
  files: HeldFiles;
  sentMs: number;
  /** The thread it went to; null when the send creates the thread. */
  sessionId: string | null;
  /** The newest event seq the thread had shown before the send. */
  afterSeq: number;
}
let lastSent: SentMessage | null = null;
/** How long after sending Escape still takes a message back once the agent started thinking. */
export const RECALL_WINDOW_MS = 15_000;

/**
 * The composer a dictation's words belong to, by thread key: the one whose
 * mic button was pressed, else the one typed in last. Side-by-side columns
 * each mount a composer, and every one of them hears the same transcript.
 */
let dictationOwner: string | null = null;

/** An Escape pressed in another field, menu or dialog is that control's, never a recall. */
function escapeBelongsElsewhere(target: EventTarget | null, box: HTMLTextAreaElement | null): boolean {
  if (!(target instanceof HTMLElement) || target === box) return false;
  return Boolean(target.closest("input, textarea, select, [contenteditable=true], [contenteditable=''], [role=dialog], [role=menu], [role=listbox]"));
}

function keepSent(next: SentMessage | null): void {
  if (lastSent && lastSent.files !== next?.files) releaseHeldFiles(lastSent.files);
  lastSent = next;
}

/** The event seq a user item was built from (`u-<seq>`), or 0. */
function itemSeq(item: UserItem): number {
  const seq = Number(item.id.slice(2));
  return Number.isFinite(seq) ? seq : 0;
}

/**
 * The user item `sent` became, when Escape may still take it back: the one
 * message that arrived in its thread after the send, with nothing after it
 * but the reply still running and the notices around it. While that reply
 * shows no work the message comes back however long the agent takes to
 * connect; once it reasons or writes, only inside RECALL_WINDOW_MS; once it
 * ran a tool, never — that work may have touched files.
 *
 * Matched by position, never by text: what the backend stores is not always
 * byte for byte what the box held (a dictated transcript can come back with
 * other Unicode forms), and one changed character must not leave the person
 * with nothing but the Stop button.
 */
function recallableItem(timeline: Timeline, sent: SentMessage, sessionId: string | null, now: number): UserItem | null {
  if (!sessionId || (sent.sessionId !== null && sent.sessionId !== sessionId)) return null;
  const fresh = timeline.items.filter((item): item is UserItem => item.type === "user" && itemSeq(item) > sent.afterSeq);
  if (fresh.length !== 1) return null;
  const asked = fresh[0];
  const turn = runningTurn(timeline);
  const after = timeline.items.slice(timeline.items.indexOf(asked) + 1);
  if (after.some((item) => item.type === "user" || (item.type === "turn" && item !== turn))) return null;
  if (!turn) return asked;
  if (turn.blocks.some((block) => block.kind === "tool")) return null;
  const working = turn.blocks.some((block) => block.kind !== "text" || block.text.trim());
  return !working || now - sent.sentMs <= RECALL_WINDOW_MS ? asked : null;
}

/** The open question card of the newest turn, if any. */
function openQuestion(timeline: Timeline): { block: ToolBlock; question: QuestionState } | null {
  for (let i = timeline.items.length - 1; i >= 0; i--) {
    const item = timeline.items[i];
    if (item.type !== "turn") continue;
    for (const block of item.blocks) {
      if (block.kind === "tool" && block.question && !block.question.closed) return { block, question: block.question };
    }
    return null;
  }
  return null;
}

const PLAN_PROSE = cn(
  "prose prose-neutral max-w-none text-sm leading-6 text-foreground dark:prose-invert dark:text-foreground [overflow-wrap:anywhere]",
  "prose-p:my-1.5 prose-p:text-foreground prose-li:text-foreground prose-headings:text-foreground-strong prose-strong:text-foreground-strong",
  // A plan is read inside a small card: its headings stay at reading size.
  "prose-headings:mb-1 prose-headings:mt-3 prose-h1:text-base prose-h2:text-sm prose-h3:text-sm",
  "[&>div>:first-child]:mt-0 [&>div>:last-child]:mb-0",
);

/** The oldest approval the agent waits on, shown at the top of the composer. */
function ApprovalPanel({ timeline }: { timeline: Timeline }) {
  const pending = timeline.pendingApprovals[0];
  if (!pending) return null;
  // Keyed by the card: a new card starts with fresh buttons and no old error.
  return <ApprovalCard key={pending.approvalId} pending={pending} count={timeline.pendingApprovals.length} />;
}

function ApprovalCard({ pending, count }: { pending: PendingApproval; count: number }) {
  const t = useT();
  const chat = useThreadChat();
  const [sending, setSending] = useState<ApprovalDecision | null>(null);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const input = pending.input && typeof pending.input === "object" ? pending.input as Record<string, unknown> : {};
  // Claude Code's finished plan asks here too, and the plan itself is what gets approved.
  const isPlan = pending.name === "ExitPlanMode";
  const plan = isPlan ? String(input.plan ?? "").trim() : "";
  const detail = isPlan ? "" : String(input.command ?? input.file_path ?? input.path ?? input.url ?? "");
  // One answer per card: a second click while the first is on its way would
  // land on a card that is already closed.
  const decide = async (decision: ApprovalDecision) => {
    if (sending) return;
    setSending(decision);
    setError("");
    try {
      if (decision === "deny" && feedback.trim()) await chat.getState().decide(pending.approvalId, decision, undefined, feedback);
      else await chat.getState().decide(pending.approvalId, decision);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSending(null);
    }
  };
  const spinner = (decision: ApprovalDecision) => sending === decision && <Loader2 aria-hidden className="h-3.5 w-3.5 animate-spin" />;
  return <div data-testid="thread-approval" aria-busy={sending !== null} className="border-b border-border px-4 py-3">
    <div className="flex items-start gap-2.5">
      {isPlan
        ? <ListChecks aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
        : <ShieldAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-warning" />}
      <div className="min-w-0 flex-1">
        <p className="flex items-baseline gap-2 text-sm font-medium text-foreground-strong">
          <span className="min-w-0 flex-1">{isPlan ? t("ide_threads.plan_ready") : t("ide_threads.approval_needed")}</span>
          {count > 1 && <span data-testid="thread-approval-count" className="shrink-0 text-xs font-normal tabular-nums text-muted-foreground">{fill(t("ide_threads.one_of"), { count })}</span>}
        </p>
        <p className="mt-0.5 text-sm text-muted-foreground">{isPlan ? t("ide_threads.plan_hint") : pending.summary || pending.name}</p>
        {plan && <div data-testid="thread-approval-plan" className={cn("mt-2 max-h-72 overflow-auto rounded-md bg-secondary px-3 py-2 scrollbar-jarvis", PLAN_PROSE)}><ChatMarkdown text={plan} /></div>}
        {detail && <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap rounded-md bg-secondary px-2.5 py-1.5 font-mono text-xs text-foreground scrollbar-jarvis">{detail}</pre>}
        <input type="text" data-testid="thread-approval-feedback" value={feedback} disabled={sending !== null}
          onChange={(e) => setFeedback(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && feedback.trim()) { e.preventDefault(); void decide("deny"); } }}
          aria-label={t("ide_threads.deny_feedback")} placeholder={t("ide_threads.deny_feedback")}
          className="mt-2 w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50" />
        {error && <p role="alert" className="mt-2 text-xs text-destructive">{error}</p>}
      </div>
    </div>
    <div className="mt-3 flex flex-wrap justify-end gap-2">
      <button type="button" disabled={sending !== null} onClick={() => void decide("deny")}
        className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{spinner("deny")}{isPlan ? t("ide_threads.keep_planning") : t("ide_threads.decline")}</button>
      {!isPlan && <button type="button" disabled={sending !== null} onClick={() => void decide("allow_always")}
        title={t("ide_threads.always_allow_title")}
        className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-foreground hover:bg-secondary disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{spinner("allow_always")}{t("ide_threads.always_allow")}</button>}
      <button type="button" data-testid="thread-approve" disabled={sending !== null} onClick={() => void decide("allow")}
        className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-accent-foreground hover:opacity-90 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{spinner("allow")}{isPlan ? t("ide_threads.build_it") : t("ide_threads.approve")}</button>
    </div>
  </div>;
}

/** The newest turn, when it is the timeline's last item and its plan card still waits. */
function waitingPlan(timeline: Timeline): TurnItem | null {
  const last = timeline.items[timeline.items.length - 1];
  return last && last.type === "turn" && last.plan && last.plan.decision === null ? last : null;
}

/**
 * Any coding agent's finished plan (dodaios/agent_chat/turn_prompts.py): build
 * it in the runner's build mode, or keep planning and type what to change.
 */
function PlanPanel({ timeline, provider }: { timeline: Timeline; provider: ProviderOption | null }) {
  const t = useT();
  const chat = useThreadChat();
  const turn = waitingPlan(timeline);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  if (!turn?.plan) return null;
  const buildMode = turn.plan.buildMode;
  const mode = provider?.permission_modes?.find((row) => row.id === buildMode);
  const decide = async (decision: PlanDecision) => {
    setSending(true);
    setError("");
    try {
      await chat.getState().resolvePlan(turn.id, decision);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  };
  return <div data-testid="thread-plan" className="border-b border-border px-4 py-3">
    <div className="flex items-start gap-2.5">
      <ListChecks aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground-strong">{t("ide_threads.plan_ready")}</p>
        <p className="mt-0.5 text-sm text-muted-foreground">
          {mode ? fill(t("ide_threads.build_switches"), { mode: mode.label }) : t("ide_threads.build_starts")} {t("ide_threads.or_keep_planning")}
        </p>
        {error && <p role="alert" className="mt-1 text-xs text-destructive">{error}</p>}
      </div>
    </div>
    <div className="mt-3 flex flex-wrap justify-end gap-2">
      <button type="button" disabled={sending} onClick={() => void decide("keep")}
        className="rounded-lg px-3 py-1.5 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{t("ide_threads.keep_planning")}</button>
      <button type="button" data-testid="thread-plan-build" disabled={sending} onClick={() => void decide("build")}
        className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-accent-foreground hover:opacity-90 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <Hammer aria-hidden className="h-3.5 w-3.5" />{t("ide_threads.build_it")}
      </button>
    </div>
  </div>;
}

function QuestionPanel({ timeline }: { timeline: Timeline }) {
  const t = useT();
  const chat = useThreadChat();
  const open = openQuestion(timeline);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  if (!open) return null;
  const { question } = open;
  const index = question.answers.findIndex((answer) => answer === null);
  if (index < 0) return null;
  const item = question.questions[index];
  const answer = async (payload: { optionIndex: number } | { text: string }) => {
    setSending(true);
    setError("");
    try {
      await chat.getState().answerQuestion(question.questionId, index, payload);
      setText("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  };
  return <div data-testid="thread-question" className="border-b border-border px-4 py-3">
    <div className="flex items-start gap-2.5">
      <MessageCircleQuestion aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
      <div className="min-w-0 flex-1">
        <p className="text-xs text-muted-foreground">{fill(t("ide_threads.asks"), { asker: question.asker || t("ide_threads.the_agent") })}{question.questions.length > 1 ? ` · ${fill(t("ide_threads.n_of"), { index: index + 1, count: question.questions.length })}` : ""}</p>
        <p className="mt-0.5 text-sm font-medium text-foreground-strong">{item.question}</p>
        <div className="mt-2 flex flex-col gap-1">
          {item.options.map((option, optionIndex) => <button key={optionIndex} type="button" disabled={sending}
            onClick={() => void answer({ optionIndex })}
            className="flex w-full items-start gap-2 rounded-lg border border-border px-3 py-2 text-left text-sm hover:bg-secondary disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <span className="min-w-0 flex-1"><span className="text-foreground">{option.label}</span>
              {option.description && <span className="block text-xs text-muted-foreground">{option.description}</span>}</span>
            {optionIndex === 0 && <span className="shrink-0 text-xs text-accent">{t("ide_git.recommended")}</span>}
          </button>)}
        </div>
        <form className="mt-2 flex gap-2" onSubmit={(event) => { event.preventDefault(); if (text.trim()) void answer({ text: text.trim() }); }}>
          <input value={text} onChange={(event) => setText(event.target.value)} placeholder={t("ide_threads.own_answer")} disabled={sending}
            className="min-w-0 flex-1 rounded-lg border border-input bg-background px-3 py-1.5 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring" />
          <button type="button" disabled={sending} onClick={() => void chat.getState().skipQuestion(question.questionId).catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))}
            className="rounded-lg px-3 py-1.5 text-sm text-muted-foreground hover:bg-secondary">{t("ide_threads.skip")}</button>
        </form>
        {error && <p role="alert" className="mt-1 text-xs text-destructive">{error}</p>}
      </div>
    </div>
  </div>;
}

/**
 * The thread's composer: a rounded card with the text box, the files that
 * will go with the message, and one row of picks — agent and model, effort,
 * access — beside the dictation mic and the send button. Files still come in
 * by paste or drop onto the card. An approval or a
 * question the agent is waiting on opens at the top of the card, where the
 * person's eyes already are.
 *
 * `prepareDraft` runs before a NEW thread's first message and says which
 * folder the thread starts in (its project, or a fresh worktree of it);
 * returning null cancels the send.
 */
export function ThreadComposer({
  threadKey,
  prepareDraft,
  onSessionCreated,
  placeholder,
  autoFocusNonce,
  strip,
  onScreen = true,
}: {
  /** Which thread the box is typing for — the session id, or `draft:<project>`. */
  threadKey: string;
  prepareDraft: () => Promise<string | null>;
  onSessionCreated?: (session: AgentChatSession) => void;
  placeholder?: string;
  autoFocusNonce: number;
  /** The strip that hangs under the card — where the agent works and on which branch. */
  strip?: ReactNode;
  /** False while the IDE section is hidden: its keys belong to whatever is on screen. */
  onScreen?: boolean;
}) {
  const chat = useThreadChat();
  const draft = chat((state) => state.draft);
  const timeline = chat((state) => state.timeline);
  const activeSessionId = chat((state) => state.activeSessionId);
  const activeSession = chat((state) => state.activeSession);
  const catalog = chat((state) => state.catalog);
  const connections = chat((state) => state.connections);
  const liveModels = chat((state) => state.liveModels);
  const busy = chat((state) => state.busy);
  const lastError = chat((state) => state.lastError);
  const [value, setValueState] = useState(() => drafts.get(threadKey) ?? "");
  // Follow-ups waiting for the next turn live on the server (they survive a
  // reload); the timeline carries one waiting notice per message.
  const queue = useMemo(() => timeline.items.flatMap((item) => item.type === "notice" && item.kind === "message_queued"
    ? [{ id: String(item.data.queue_id ?? item.id), text: item.text }] : []), [timeline.items]);
  // After Stop the queue waits: the person halted the agent, it must not start the next job.
  const [paused, setPaused] = useState(false);
  const [problem, setProblem] = useState("");
  const [starting, setStarting] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const t = useT();

  const providers = useMemo(
    () => threadAgents(catalog ? joinProviderOptions(catalog.providers, connections) : []),
    [catalog, connections],
  );
  const provider = providers.find((option) => option.id === draft.provider) ?? null;
  const running = runningTurn(timeline) !== null || Boolean(activeSession?.running);
  const started = timeline.items.length > 0;
  // Claude Code and GLM take a message while they work; every other agent queues it.
  const steers = STEERABLE_AGENTS.has(draft.provider);

  // A coding thread only runs on a coding agent: an API row left in the draft
  // from elsewhere moves to the first connected CLI.
  useEffect(() => {
    if (activeSessionId || providers.length === 0) return;
    if (providers.some((option) => option.id === draft.provider && option.connected)) return;
    const seat = rememberedSeat();
    const remembered = seat && providers.find((option) => option.id === seat.provider && option.connected);
    if (remembered && seat) { void chat.getState().setDraft(seat); return; }
    const first = providers.find((option) => option.connected) ?? providers[0];
    if (first && first.id !== draft.provider) void chat.getState().setDraft({ provider: first.id });
  }, [chat, activeSessionId, providers, draft.provider]);

  // A model change can leave the picked effort off that model's ladder (Opus
  // 4.6 has no xhigh, Gemini 3.1 Pro no medium); fold it the way the backend
  // does, so the label always names the level the agent runs on. With a
  // thread open, only once the draft mirrors that thread — never onto a
  // session whose snapshot has not arrived yet.
  useEffect(() => {
    if (!provider) return;
    if (activeSessionId && (activeSession?.session_id !== activeSessionId
      || activeSession.model !== draft.model || activeSession.effort !== draft.effort)) return;
    const ladder = effortLadder(provider, modelsOf(provider, liveModels), draft.model);
    if (!ladder.some(Boolean)) return;
    const next = snapEffort(draft.effort, ladder, provider.default_effort);
    if (next !== draft.effort) void chat.getState().setDraft({ effort: next });
  }, [chat, provider, liveModels, draft.model, draft.effort, activeSessionId, activeSession]);

  // The thread the box types for now; a send that is still on its way compares against it.
  const keyRef = useRef(threadKey);
  keyRef.current = threadKey;

  const setValue = useCallback((next: string) => {
    setValueState(next);
    drafts.set(threadKey, next);
  }, [threadKey]);

  // The dictated words append to whatever the box holds when they land — in
  // the one composer that owns the dictation, never in a hidden one.
  const setDictated = useCallback((next: string | ((current: string) => string)) => {
    if (!onScreen || (dictationOwner !== null && dictationOwner !== threadKey)) return;
    setValue(typeof next === "function" ? next(drafts.get(threadKey) ?? "") : next);
  }, [setValue, threadKey, onScreen]);
  const dictation = useComposerDictation(setDictated, () => void submit());

  // Another thread: its own half-written text, its own queue.
  useEffect(() => {
    setValueState(drafts.get(threadKey) ?? "");
    setPaused(false);
    setProblem("");
  }, [threadKey]);

  // The server owns the pause: a reloaded page shows a queue Stop paused as paused.
  const waiting = queue.length;
  useEffect(() => {
    if (!activeSessionId || waiting === 0) { setPaused(false); return; }
    let live = true;
    void fetchAgentChatQueue(activeSessionId).then((state) => { if (live) setPaused(state.paused); }, () => undefined);
    return () => { live = false; };
  }, [activeSessionId, waiting]);

  useEffect(() => {
    if (autoFocusNonce > 0) textareaRef.current?.focus();
  }, [autoFocusNonce]);

  // Grow with the text, up to a third of the window.
  useEffect(() => {
    const box = textareaRef.current;
    if (!box) return;
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight, Math.max(160, window.innerHeight / 3))}px`;
  }, [value]);

  const files = useChatAttachments(
    { sessionId: activeSessionId, cwd: draft.cwd, provider: draft.provider, surface: "agent" },
    (message) => setProblem(message),
    { owner: chat, key: threadKey },
  );
  const triggers = useMemo(() => provider?.typeahead ?? [], [provider]);
  const typeahead = useComposerTypeahead(textareaRef, value, setValue, {
    surface: "agent",
    provider: draft.provider,
    cwd: draft.cwd,
    triggers,
  });

  /** Sends `text`; false when it did not reach the agent. `sent` learns the thread a first message creates. */
  const dispatch = useCallback(async (text: string, attachments: ChatAttachment[], sent?: SentMessage) => {
    const store = chat.getState();
    // A second message while the first one still creates the thread rides on
    // that creation (the store's send lane), never on a second worktree.
    if (!store.activeSessionId && !store.busy) {
      setStarting(true);
      try {
        const cwd = await prepareDraft();
        if (cwd === null) return false;
        // The person opened another thread while the worktree was being made:
        // the folder and the message are this draft's, never that thread's.
        if (chat.getState().activeSessionId !== null) return false;
        if (cwd !== chat.getState().draft.cwd) await chat.getState().setDraft({ cwd });
      } catch (error) {
        setProblem(error instanceof Error ? error.message : String(error));
        return false;
      } finally {
        setStarting(false);
      }
    }
    const outcome = await chat.getState().send(text, attachments, [], (session) => {
      if (sent && sent.sessionId === null) sent.sessionId = session.session_id;
      onSessionCreated?.(session);
    });
    return outcome !== "failed";
  }, [chat, prepareDraft, onSessionCreated]);

  /** A message that did not go comes back into its thread's box, ahead of anything typed since. */
  const giveBack = useCallback((key: string, text: string) => {
    const current = drafts.get(key) ?? "";
    const restored = current.trim() ? `${text}\n${current}` : text;
    drafts.set(key, restored);
    if (key === keyRef.current) setValueState(restored);
  }, []);

  const submit = async () => {
    // Send during a dictation ends it first; the message goes once the words land.
    if (dictation.dictating) {
      dictation.stopAndSend();
      return;
    }
    const text = value.trim();
    if (!text && files.attachments.length === 0) return;
    if (files.analyzing > 0 || starting) return;
    if (!provider || !provider.connected) {
      setProblem(t("ide_threads.choose_connected_agent"));
      return;
    }
    const key = threadKey;
    const held = files.take();
    const attachments = held.attachments;
    setValue("");
    setProblem("");
    if (running || busy) {
      // The server decides: a CLI that takes input mid-turn is steered, any
      // other follow-up waits in the server's queue and runs as the next turn.
      releaseHeldFiles(held);
      const sent = await dispatch(text, attachments);
      if (!sent) giveBack(key, text);
      return;
    }
    const before = chat.getState();
    const message: SentMessage = { text, files: held, sentMs: Date.now(), sessionId: before.activeSessionId, afterSeq: before.timeline.lastSeq };
    keepSent(message);
    const sent = await dispatch(text, attachments, message);
    if (!sent) {
      // It never reached the agent: the words and files come back, in a new
      // thread's draft and in an open thread alike.
      if (lastSent === message) lastSent = null;
      giveBack(key, text);
      if (key === keyRef.current) files.restore(held);
      else releaseHeldFiles(held);
    }
  };

  // Escape soon after sending stops the turn, takes the message out of the
  // thread and puts it, files included, back into the box to edit and send again.
  const recall = useRef<() => boolean>(() => false);
  const typeaheadOpen = useRef(false);
  typeaheadOpen.current = typeahead.open;
  recall.current = () => {
    const asked = lastSent && recallableItem(timeline, lastSent, activeSessionId, Date.now());
    if (!lastSent || !asked) return false;
    const { text, files: held } = lastSent;
    lastSent = null;
    setPaused(true);
    if (activeSessionId) useRecalledMessages.getState().hide(activeSessionId, asked.id);
    void chat.getState().cancel("thread-recall");
    const current = drafts.get(threadKey) ?? "";
    setValue(current.trim() ? `${text}\n${current}` : text);
    files.restore(held);
    textareaRef.current?.focus();
    return true;
  };
  useEffect(() => {
    if (!onScreen) return;
    // Capture phase: a handler further down (the IDE's own key layers) must
    // not swallow the Escape first. It only takes the key in the seconds
    // after a send, when the message is still recallable.
    const onEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || event.isComposing) return;
      // A rename field, a picker or the open `/` and `@` list take their own Escape.
      if (escapeBelongsElsewhere(event.target, textareaRef.current) || typeaheadOpen.current) return;
      if (!recall.current()) return;
      event.preventDefault();
      event.stopPropagation();
    };
    window.addEventListener("keydown", onEscape, true);
    return () => window.removeEventListener("keydown", onEscape, true);
  }, [onScreen]);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (typeahead.onKeyDown(event)) return;
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  };

  // A pick the person made is the seat every new thread starts on.
  const pick = async (patch: Partial<Pick<ComposerDraft, "provider" | "model" | "effort" | "permissionMode">>) => {
    const store = chat.getState();
    await store.setDraft(patch);
    rememberSeat(chat.getState().draft);
  };

  const canSend = (value.trim().length > 0 || files.attachments.length > 0 || dictation.dictating) && files.analyzing === 0 && !starting;
  const error = problem || lastError || "";

  return <div className="mx-auto w-full max-w-3xl">
    {queue.length > 0 && <div className="mb-2 flex flex-col gap-1 px-2" data-testid="thread-queue">
      {paused && !running && <div className="flex items-center justify-between gap-2 px-1 text-xs text-muted-foreground">
        <span>{t("ide_threads.queue_paused")}</span>
        <button type="button" onClick={() => { setPaused(false); if (activeSessionId) void resumeAgentChatQueue(activeSessionId).catch(() => setPaused(true)); }} className="rounded px-1.5 py-0.5 text-foreground hover:bg-secondary">{t("ide_threads.send_next")}</button>
      </div>}
      {queue.map((entry) => <div key={entry.id} className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-1.5 text-sm">
        <span className="shrink-0 text-xs text-muted-foreground">{t("ide_threads.queued")}</span>
        <span className="min-w-0 flex-1 truncate text-foreground">{entry.text}</span>
        <button type="button" aria-label={t("ide_threads.remove_queued")} onClick={() => { if (activeSessionId) void discardQueuedMessage(activeSessionId, entry.id).catch((error) => setProblem(error instanceof Error ? error.message : String(error))); }}
          className="rounded p-0.5 text-muted-foreground hover:text-foreground"><X className="h-3.5 w-3.5" /></button>
      </div>)}
    </div>}
    {error && <p role="alert" className="mb-2 px-4 text-xs text-destructive">{error}</p>}
    {running && canSend && <p className="mb-1.5 px-4 text-xs text-muted-foreground" data-testid="thread-send-mode" data-mode={steers ? "steer" : "queue"}>
      {t(steers ? "ide_threads.steer_hint" : "ide_threads.queue_hint")}</p>}
    <div ref={cardRef} {...files.dragHandlers}
      className={cn(
        "relative z-10 overflow-hidden rounded-3xl border border-border bg-card shadow-[0_8px_24px_-12px_rgb(var(--scrim-rgb)/0.5)] transition-colors focus-within:border-border-strong",
        files.dragging && "border-accent ring-2 ring-accent/40",
      )}>
      <ApprovalPanel timeline={timeline} />
      {/* Keyed by thread: a half-typed answer or an old error never carries over to another thread's card. */}
      <QuestionPanel key={`q:${threadKey}`} timeline={timeline} />
      {!running && <PlanPanel key={`p:${threadKey}`} timeline={timeline} provider={provider} />}
      {(files.attachments.length > 0 || files.analyzing > 0) && <div className="px-3 pt-3 sm:px-4">
        <ChatAttachmentStrip attachments={files.attachments} analyzing={files.analyzing}
          onRemove={files.remove} previews={files.previews} look="thumbnail" />
      </div>}
      <textarea ref={textareaRef} value={value} rows={2} data-testid="thread-composer-input"
        aria-label={t("ide_threads.message_agent")}
        placeholder={running ? t(steers ? "ide_threads.steer_placeholder" : "ide_threads.queue_placeholder") : placeholder ?? t("ide_threads.composer_placeholder")}
        onChange={(event) => { setValue(event.target.value); typeahead.refresh(); }}
        onKeyDown={onKeyDown}
        onFocus={() => { dictationOwner = threadKey; }}
        onKeyUp={() => typeahead.refresh()}
        onClick={() => typeahead.refresh()}
        onBlur={() => typeahead.blur()}
        onPaste={files.onPaste}
        className="block max-h-[40vh] min-h-[84px] w-full resize-none bg-transparent px-4 pb-2 pt-4 text-base leading-6 text-foreground outline-none placeholder:text-faint-foreground sm:px-5" />
      <div className="flex min-w-0 items-center justify-between gap-2 px-3 pb-3 sm:px-4 sm:pb-4">
        {/* The pickers keep their width: a narrow column (side by side) scrolls the row instead of stacking them. */}
        <div className="-ms-1 flex min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none] [&>*]:shrink-0">
        <AgentModelPicker providers={providers} liveModels={liveModels} draft={draft}
          lockedProvider={started && activeSessionId ? draft.provider : null}
          onPick={(nextProvider, model) => void pick(nextProvider !== draft.provider ? { provider: nextProvider, model } : { model })} />
        <EffortPicker provider={provider} draft={draft} liveModels={liveModels} separated
          onPick={(effort) => void pick({ effort })} />
        <AccessPicker provider={provider} draft={draft} separated
          onPick={(permissionMode) => void pick({ permissionMode })} />
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <DictationButton dictating={dictation.dictating} onToggle={() => { dictationOwner = threadKey; dictation.toggle(); }}
            startLabel={t("chats_view.dictation_start")} stopLabel={t("chats_view.dictation_stop")} shape="round" />
          {running && !canSend
            ? <button type="button" aria-label={t("ide_threads.stop_agent")} title={t("ide_threads.stop")} data-testid="thread-stop"
              onClick={() => { setPaused(true); void chat.getState().cancel("thread-stop-button"); }}
              className="flex h-8 w-8 items-center justify-center rounded-full bg-foreground text-background transition-transform duration-150 hover:scale-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <Square className="h-3 w-3 fill-current" />
            </button>
            : <button type="button" aria-label={running ? t(steers ? "ide_threads.steer_title" : "ide_threads.queue_message") : t("ide_threads.send_message")} title={running ? t(steers ? "ide_threads.steer_title" : "ide_threads.queue_title") : t("agent_chat.send")}
              data-testid="thread-send" disabled={!canSend} onClick={() => void submit()}
              className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-accent-foreground shadow-[0_1px_2px_rgb(var(--accent-rgb)/0.3)] transition-[opacity,transform] duration-150 hover:scale-105 hover:opacity-95 disabled:opacity-40 disabled:hover:scale-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              {starting || busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
            </button>}
        </div>
      </div>
    </div>
    {strip}
    <ComposerTypeahead anchorRef={cardRef} open={typeahead.open} trigger={typeahead.token?.trigger ?? null}
      items={typeahead.items} loading={typeahead.loading} activeIndex={typeahead.activeIndex}
      onHover={typeahead.setActiveIndex} onPick={typeahead.pick} />
  </div>;
}
