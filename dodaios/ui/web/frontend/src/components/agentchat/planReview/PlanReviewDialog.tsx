/**
 * A coding agent's plan at full size: read it, change it, comment on it.
 *
 * The plan card in the composer shows the plan in a small box, which is fine
 * for a glance and too small to go through a long plan in peace. This window
 * is the plan as a document: the person types into it like into any text,
 * marks a passage and comments on it, and leaves a note on the whole plan.
 * "Build it" hands the agent the plan as it stands here; "Keep planning" sends
 * the comments and the edits back (dodaios/agent_chat/plan_review.py).
 *
 * The text is the document editor's (`nodes/editors/docs`): the plan stays
 * Markdown, and a block the person did not touch keeps the exact text the
 * agent wrote. What the person did lives in the plan draft, outside this
 * window, so closing it loses nothing.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { EditorContent, useEditor, useEditorState, type Editor } from "@tiptap/react";
import { Bold, Code, Heading2, Italic, List, ListChecks, ListOrdered, Loader2, MessageSquarePlus, Redo2, Undo2, X } from "lucide-react";

import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { plural } from "@/components/agentchat/traceEntries";
import { docExtensions } from "@/components/nodes/editors/docs/extensions";
import { DocMarkdown } from "@/components/nodes/editors/docs/markdown/document";
import "@/components/nodes/editors/docs/docs.css";
import "./planReview.css";
import { PlanComments, findQuote, inReadingOrder, planCommentsKey, planText, quoteBetween, type PlanCommentsStorage } from "./planComments";
import { newCommentId, usePlanDraft, usePlanDrafts, writtenComments, type PlanComment } from "./planDraft";

export type PlanAnswer = "build" | "keep";

export interface PlanReviewDialogProps {
  /** Which plan card this is: its draft is kept under this id. */
  cardId: string;
  /** The agent's plan, as Markdown. */
  plan: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Absent where the card cannot be answered: the plan is only read. */
  onAnswer?: (answer: PlanAnswer) => void;
  /** The answer on its way, if any. */
  pending?: PlanAnswer | null;
  error?: string;
  /** What "Build it" does next, in the card's words. */
  buildHint?: string;
}

/** Two plan texts that read the same (line ends and outer blank lines aside). */
function sameText(a: string, b: string): boolean {
  const norm = (text: string) => text.replace(/\r\n?/g, "\n").trim();
  return norm(a) === norm(b);
}

function commentsOf(editor: Editor): PlanCommentsStorage {
  return (editor.storage as unknown as { planComments: PlanCommentsStorage }).planComments;
}

function isEditable(target: EventTarget | null): target is HTMLElement {
  return target instanceof HTMLElement && Boolean(target.closest("textarea, input, [contenteditable='true']"));
}

export default function PlanReviewDialog({ cardId, plan, open, onOpenChange, onAnswer, pending = null, error, buildHint }: PlanReviewDialogProps) {
  const t = useT();
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-scrim/75 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in-0 motion-reduce:animate-none" />
        <Dialog.Content
          data-testid="plan-review"
          aria-describedby={undefined}
          // Escape first leaves the field being typed in; the next one closes the window.
          onEscapeKeyDown={(event) => {
            const focused = document.activeElement;
            if (!isEditable(focused)) return;
            event.preventDefault();
            focused.blur();
          }}
          // The caret goes into the plan only when the person clicks there.
          onOpenAutoFocus={(event) => event.preventDefault()}
          className={cn(
            "fixed left-1/2 top-1/2 z-[90] flex h-[min(94dvh,64rem)] w-[min(1240px,calc(100vw-1.5rem))]",
            "-translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-lg border border-border",
            "bg-background shadow-float outline-none",
            "data-[state=open]:animate-in data-[state=open]:fade-in-0 motion-reduce:animate-none",
          )}
        >
          <PlanDocument cardId={cardId} plan={plan} onAnswer={onAnswer} pending={pending} error={error} buildHint={buildHint}
            title={<Dialog.Title className="flex min-w-0 items-center gap-2 text-sm font-medium text-foreground-strong">
              <ListChecks aria-hidden className="h-4 w-4 shrink-0 text-accent" />
              <span className="truncate">{t("plan_review.title")}</span>
            </Dialog.Title>}
            close={<Dialog.Close asChild>
              <button type="button" aria-label={t("plan_review.close")} title={t("plan_review.close")} data-testid="plan-review-close"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <X aria-hidden className="h-4 w-4" />
              </button>
            </Dialog.Close>} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function PlanDocument({ cardId, plan, onAnswer, pending, error, buildHint, title, close }: {
  cardId: string; plan: string; onAnswer?: (answer: PlanAnswer) => void; pending: PlanAnswer | null;
  error?: string; buildHint?: string; title: ReactNode; close: ReactNode;
}) {
  const t = useT();
  const lang = t("trace_report.locale");
  const draft = usePlanDraft(cardId);
  const patch = usePlanDrafts((state) => state.patch);
  const canAnswer = Boolean(onAnswer);
  const [active, setActive] = useState<string | null>(null);
  /** The comment whose field takes the caret once it is drawn. */
  const [writing, setWriting] = useState<string | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [bubble, setBubble] = useState<{ top: number; left: number } | null>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const railRef = useRef<HTMLDivElement>(null);

  // The text the window opens on: the person's version when they already changed it.
  const session = useRef<DocMarkdown | null>(null);
  session.current ??= new DocMarkdown(draft.plan ?? plan);
  const commentsRef = useRef(draft.comments);
  commentsRef.current = draft.comments;
  const addComment = useRef<() => void>(() => {});

  const extensions = useMemo(
    () => [
      ...docExtensions({ summary: false }),
      PlanComments.configure({ onComment: () => addComment.current() }),
    ],
    [],
  );

  const editor = useEditor({
    extensions,
    content: session.current.doc,
    editable: canAnswer,
    immediatelyRender: true,
    shouldRerenderOnTransaction: false,
    editorProps: {
      attributes: {
        class: "doc-editor-content plan-review-text",
        role: "textbox",
        "aria-multiline": "true",
        "aria-label": t("plan_review.text_label"),
        // A plan is full of paths and names: no red lines under them.
        spellcheck: "false",
        "data-testid": "plan-review-text",
      },
    },
    onUpdate: ({ editor: current }) => {
      const text = session.current!.serialize(current.state.doc);
      // Back at the agent's own words (an undo): nothing is edited any more.
      patch(cardId, { plan: sameText(text, plan) ? null : text });
    },
  });

  // Pair the loaded blocks with the text they were read from, so untouched ones keep it.
  useEffect(() => {
    session.current!.remember(editor.state.doc);
  }, [editor]);

  const view = useEditorState({
    editor,
    selector: ({ editor: current }) => ({
      doc: current.state.doc,
      from: current.state.selection.from,
      to: current.state.selection.to,
      empty: current.state.selection.empty,
      canUndo: current.can().undo(),
      canRedo: current.can().redo(),
      bold: current.isActive("bold"),
      italic: current.isActive("italic"),
      code: current.isActive("code"),
      heading: current.isActive("heading"),
      bullets: current.isActive("bulletList"),
      numbers: current.isActive("orderedList"),
      tasks: current.isActive("taskList"),
    }),
  });

  const map = useMemo(() => planText(view.doc), [view.doc]);
  const ordered = useMemo(() => inReadingOrder(map, draft.comments), [map, draft.comments]);

  // The marks in the text follow the comments and the one in focus.
  useEffect(() => {
    if (editor.isDestroyed) return;
    const storage = commentsOf(editor);
    storage.comments = draft.comments;
    storage.active = active;
    editor.view.dispatch(editor.state.tr.setMeta(planCommentsKey, true));
  }, [editor, draft.comments, active]);

  addComment.current = () => {
    if (!canAnswer || editor.state.selection.empty) return;
    const { from, to } = editor.state.selection;
    const { quote, at } = quoteBetween(planText(editor.state.doc), from, to);
    if (!quote) return;
    const comment: PlanComment = { id: newCommentId(), quote, at, text: "" };
    patch(cardId, { comments: [...commentsRef.current, comment] });
    setActive(comment.id);
    setWriting(comment.id);
    // The passage is marked now; the selection (and its Comment button) has done its work.
    editor.commands.setTextSelection(Math.max(from, to));
  };

  const changeComment = useCallback((id: string, text: string) => {
    patch(cardId, { comments: commentsRef.current.map((comment) => (comment.id === id ? { ...comment, text } : comment)) });
  }, [cardId, patch]);
  const removeComment = useCallback((id: string) => {
    patch(cardId, { comments: commentsRef.current.filter((comment) => comment.id !== id) });
    setActive((was) => (was === id ? null : was));
  }, [cardId, patch]);

  /** Bring a comment's passage into view in the plan. */
  const showPassage = useCallback((comment: PlanComment) => {
    setActive(comment.id);
    const mark = pageRef.current?.querySelector(`[data-plan-comment="${comment.id}"]`);
    mark?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, []);

  // The "Comment" button stands at the end of what is selected, once the mouse is up.
  useLayoutEffect(() => {
    const page = pageRef.current;
    if (!canAnswer || view.empty || selecting || !page) {
      setBubble(null);
      return;
    }
    try {
      const end = editor.view.coordsAtPos(view.to);
      const box = page.getBoundingClientRect();
      const left = Math.max(8, Math.min(end.left - box.left - 44, page.clientWidth - 128));
      setBubble({ top: end.bottom - box.top + page.scrollTop + 6, left });
    } catch {
      // Not laid out (yet): the toolbar's button still comments.
      setBubble(null);
    }
  }, [editor, canAnswer, view.empty, view.to, view.from, selecting]);

  useEffect(() => {
    if (!selecting) return;
    const done = () => setSelecting(false);
    window.addEventListener("pointerup", done);
    window.addEventListener("pointercancel", done);
    return () => {
      window.removeEventListener("pointerup", done);
      window.removeEventListener("pointercancel", done);
    };
  }, [selecting]);

  const resetPlan = () => {
    const fresh = new DocMarkdown(plan);
    session.current = fresh;
    editor.commands.setContent(fresh.doc, { emitUpdate: false });
    fresh.remember(editor.state.doc);
    patch(cardId, { plan: null });
  };

  const written = writtenComments(draft).length;
  const edited = draft.plan !== null;
  const marks = [
    edited ? t("plan_review.edited") : "",
    written ? fill(t(`plan_review.comments_${plural(lang, written)}`), { count: written }) : "",
  ].filter(Boolean).join(" · ");
  const reviewed = edited || written > 0 || Boolean(draft.note.trim());
  const run = () => editor.chain().focus();
  const busy = pending !== null;

  return <>
    <header className="flex items-center gap-3 border-b border-border px-4 py-2">
      {title}
      {canAnswer && <div role="toolbar" aria-label={t("plan_review.tools")} className="flex min-w-0 flex-1 flex-wrap items-center justify-center gap-0.5">
        <Tool label={t("plan_review.undo")} disabled={!view.canUndo} onClick={() => run().undo().run()}><Undo2 aria-hidden /></Tool>
        <Tool label={t("plan_review.redo")} disabled={!view.canRedo} onClick={() => run().redo().run()}><Redo2 aria-hidden /></Tool>
        <Divider />
        <Tool label={t("plan_review.bold")} pressed={view.bold} onClick={() => run().toggleBold().run()}><Bold aria-hidden /></Tool>
        <Tool label={t("plan_review.italic")} pressed={view.italic} onClick={() => run().toggleItalic().run()}><Italic aria-hidden /></Tool>
        <Tool label={t("plan_review.code")} pressed={view.code} onClick={() => run().toggleCode().run()}><Code aria-hidden /></Tool>
        <Divider />
        <Tool label={t("plan_review.heading")} pressed={view.heading} onClick={() => run().toggleHeading({ level: 2 }).run()}><Heading2 aria-hidden /></Tool>
        <Tool label={t("plan_review.bullets")} pressed={view.bullets} onClick={() => run().toggleBulletList().run()}><List aria-hidden /></Tool>
        <Tool label={t("plan_review.numbers")} pressed={view.numbers} onClick={() => run().toggleOrderedList().run()}><ListOrdered aria-hidden /></Tool>
        <Tool label={t("plan_review.tasks")} pressed={view.tasks} onClick={() => run().toggleTaskList().run()}><ListChecks aria-hidden /></Tool>
        <Divider />
        <button type="button" data-testid="plan-review-comment" disabled={view.empty}
          title={view.empty ? t("plan_review.comment_hint") : t("plan_review.comment")}
          onMouseDown={(event) => event.preventDefault()} onClick={() => addComment.current()}
          className="flex h-8 items-center gap-1.5 rounded-md px-2 text-sm text-foreground hover:bg-secondary disabled:text-muted-foreground disabled:hover:bg-transparent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <MessageSquarePlus aria-hidden className="h-4 w-4" />{t("plan_review.comment")}
        </button>
      </div>}
      {!canAnswer && <span className="min-w-0 flex-1" />}
      {close}
    </header>

    <div className="flex min-h-0 flex-1 flex-col md:flex-row">
      <div ref={pageRef} data-testid="plan-review-page"
        className="doc-editor relative min-h-0 min-w-0 flex-1 overflow-y-auto scrollbar-jarvis"
        onPointerDown={() => setSelecting(true)}
        onClick={(event) => {
          const mark = (event.target as HTMLElement).closest<HTMLElement>("[data-plan-comment]");
          const id = mark?.dataset.planComment;
          if (!id) return;
          setActive(id);
          railRef.current?.querySelector(`[data-comment-id="${id}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
        }}>
        <div className="mx-auto w-full max-w-[816px] px-12 pb-32 pt-10">
          <EditorContent editor={editor} />
        </div>
        {bubble && <button type="button" data-testid="plan-review-comment-here"
          style={{ top: bubble.top, left: bubble.left }}
          // Its own press must not count as a new selection being dragged in the plan.
          onPointerDown={(event) => event.stopPropagation()}
          onMouseDown={(event) => event.preventDefault()} onClick={() => addComment.current()}
          className="absolute z-10 flex h-8 items-center gap-1.5 rounded-md border border-border bg-popover px-2.5 text-sm text-popover-foreground shadow-float hover:bg-secondary">
          <MessageSquarePlus aria-hidden className="h-4 w-4 text-accent" />{t("plan_review.comment")}
        </button>}
      </div>

      {canAnswer && <aside ref={railRef} aria-label={t("plan_review.comments")} data-testid="plan-review-rail"
        className="flex max-h-[40%] min-h-0 w-full shrink-0 flex-col border-t border-border bg-card md:max-h-none md:w-[320px] md:border-l md:border-t-0">
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3 scrollbar-jarvis">
          <p className="px-1 text-xs font-medium text-muted-foreground">{t("plan_review.comments")}</p>
          {ordered.length === 0
            ? <p className="mt-2 px-1 text-sm leading-6 text-muted-foreground" data-testid="plan-review-empty">{t("plan_review.comment_hint")}</p>
            : <ul role="list" className="mt-2 flex flex-col gap-2">
              {ordered.map((comment) => <CommentCard key={comment.id} comment={comment}
                lost={findQuote(map, comment) === null}
                active={active === comment.id} focus={writing === comment.id}
                onFocused={() => { setActive(comment.id); setWriting(null); }}
                onShow={() => showPassage(comment)}
                onChange={(text) => changeComment(comment.id, text)}
                onRemove={() => removeComment(comment.id)} />)}
            </ul>}
        </div>
        <label className="block border-t border-border px-3 py-3">
          <span className="px-1 text-xs font-medium text-muted-foreground">{t("plan_review.note_label")}</span>
          <textarea data-testid="plan-review-note" value={draft.note} rows={2}
            onChange={(event) => patch(cardId, { note: event.target.value })}
            placeholder={t("plan_review.note_placeholder")}
            className="mt-1.5 max-h-40 min-h-[3.25rem] w-full resize-none rounded-md border border-border bg-transparent px-2.5 py-1.5 text-sm leading-6 text-foreground [field-sizing:content] placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </label>
      </aside>}
    </div>

    {canAnswer
      ? <footer className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border px-4 py-3" aria-busy={busy}>
        <div className="min-w-0 flex-1 text-xs leading-5 text-muted-foreground">
          {marks && <p className="flex flex-wrap items-center gap-x-2">
            <span className="font-medium text-foreground" data-testid="plan-review-marks">{marks}</span>
            {edited && <button type="button" data-testid="plan-review-reset" onClick={resetPlan} disabled={busy}
              className="underline decoration-border underline-offset-2 hover:text-foreground disabled:opacity-50">{t("plan_review.reset")}</button>}
          </p>}
          <p>{t(reviewed ? "plan_review.sends" : "plan_review.untouched")}</p>
          {error && <p role="alert" className="text-destructive">{error}</p>}
        </div>
        <button type="button" data-testid="plan-review-keep" disabled={busy} onClick={() => onAnswer?.("keep")}
          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {pending === "keep" && <Loader2 aria-hidden className="h-3.5 w-3.5 animate-spin" />}{t("ide_threads.keep_planning")}
        </button>
        <button type="button" data-testid="plan-review-build" disabled={busy} title={buildHint} onClick={() => onAnswer?.("build")}
          className="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-accent-foreground hover:opacity-90 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {pending === "build" && <Loader2 aria-hidden className="h-3.5 w-3.5 animate-spin" />}{t("ide_threads.build_it")}
        </button>
      </footer>
      : <footer className="border-t border-border px-4 py-2.5 text-xs text-muted-foreground">{t("plan_review.read_only")}</footer>}
  </>;
}

function Divider() {
  return <span aria-hidden className="mx-1 h-4 w-px bg-border" />;
}

function Tool({ label, pressed, disabled, onClick, children }: {
  label: string; pressed?: boolean; disabled?: boolean; onClick: () => void; children: ReactNode;
}) {
  return <button type="button" aria-label={label} title={label} aria-pressed={pressed} disabled={disabled}
    // The caret and the selection stay in the plan while a tool is pressed.
    onMouseDown={(event) => event.preventDefault()} onClick={onClick}
    className={cn(
      "flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground [&>svg]:h-4 [&>svg]:w-4",
      "hover:bg-secondary hover:text-foreground disabled:opacity-40 disabled:hover:bg-transparent",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      pressed && "bg-secondary text-foreground",
    )}>{children}</button>;
}

function CommentCard({ comment, lost, active, focus, onFocused, onShow, onChange, onRemove }: {
  comment: PlanComment; lost: boolean; active: boolean; focus: boolean;
  onFocused: () => void; onShow: () => void; onChange: (text: string) => void; onRemove: () => void;
}) {
  const t = useT();
  const field = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (focus) field.current?.focus();
  }, [focus]);
  return <li data-testid="plan-comment" data-comment-id={comment.id} data-active={active || undefined}
    className={cn("rounded-md border bg-background px-2.5 py-2", active ? "border-accent" : "border-border")}>
    <div className="flex items-start gap-1.5">
      <button type="button" onClick={onShow} title={lost ? t("plan_review.comment_lost") : comment.quote}
        className={cn("min-w-0 flex-1 border-l-2 pl-2 text-left text-xs leading-5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          lost ? "border-border text-muted-foreground line-through" : "border-accent text-foreground-secondary")}>
        <span className="line-clamp-2 [overflow-wrap:anywhere]">{comment.quote}</span>
      </button>
      <button type="button" aria-label={t("plan_review.comment_delete")} title={t("plan_review.comment_delete")} onClick={onRemove}
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <X aria-hidden className="h-3.5 w-3.5" />
      </button>
    </div>
    <textarea ref={field} value={comment.text} rows={1} data-testid="plan-comment-text"
      aria-label={t("plan_review.comment_placeholder")} placeholder={t("plan_review.comment_placeholder")}
      onFocus={onFocused}
      onChange={(event) => onChange(event.target.value)}
      // A comment left without a word was never one.
      onBlur={(event) => { if (!event.target.value.trim()) onRemove(); }}
      onKeyDown={(event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) event.currentTarget.blur(); }}
      className="mt-1.5 max-h-48 min-h-[1.75rem] w-full resize-none bg-transparent text-sm leading-6 text-foreground [field-sizing:content] placeholder:text-muted-foreground focus-visible:outline-none" />
  </li>;
}
