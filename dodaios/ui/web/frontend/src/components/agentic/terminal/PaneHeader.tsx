import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { BookOpenText, Check, FileDiff, FolderGit2, GripVertical, Loader2, Maximize2, MessageSquare, Minimize2, Pencil, X } from "lucide-react";
import { SplitBelowIcon, SplitRightIcon } from "../splitIcons";
import { cn } from "@/lib/utils";
import { PANE_BRAND, PANE_CHROME, type TerminalAppearance } from "../terminalThemes";
import { AgentPickerMenu, offersAgentChoice, type SplitAgentChoice } from "../AgentPicker";
import { PaneActivityPill } from "../PaneActivityPill";
import { PaneRecap } from "../PaneRecap";
import { PromptHistoryButton } from "../PromptHistoryButton";
import { PaneDoneGateBadge } from "../PaneDoneGateBadge";
import { SessionGitHubBadge } from "../SessionGitHubBadge";
import { fill, useT } from "@/i18n";
import { MAX_TERMINAL_NAME, PaneStatus, SplitDirection, PaneRecapMeta, PaneRecapActions } from "./paneShared";

export function PaneHeader({
  workspaceId,
  githubStatusEnabled,
  name,
  displayName,
  recap,
  recapDetail,
  recapMeta,
  recapActions,
  accountLabel,
  promptCount,
  appearance,
  focused,
  maximized,
  onToggleMaximize,
  onSplit,
  agents,
  onAgentsChanged,
  onRename,
  onClose,
  splitDisabled,
  status,
  statusDetail,
  onArrangeStart,
  showArrangeHandle = false,
  arranging = false,
  onOpenConversation,
  onOpenChat,
  onReviewChanges,
  onReviewChangesPrefetch,
  onShowInGit,
}: {
  workspaceId?: string;
  githubStatusEnabled: boolean;
  name: string;
  displayName: string;
  recap?: string;
  recapDetail?: string;
  recapMeta?: PaneRecapMeta;
  recapActions?: PaneRecapActions;
  accountLabel?: string | null;
  promptCount: number;
  appearance: TerminalAppearance;
  focused: boolean;
  maximized: boolean;
  onToggleMaximize?: () => void;
  onSplit?: (direction: SplitDirection, agent?: string) => void;
  agents?: SplitAgentChoice[];
  onAgentsChanged?: () => void;
  onRename?: (name: string) => Promise<boolean>;
  onClose?: () => void;
  splitDisabled: boolean;
  /** The socket's own view of this pane — the badge beside the call-sign. */
  status: PaneStatus;
  /** Whatever the socket said about that status, read in the badge's tooltip. */
  statusDetail?: string;
  /** Press on the header picks the pane up; absent leaves it undraggable. */
  onArrangeStart?: (event: React.PointerEvent) => void;
  showArrangeHandle?: boolean;
  arranging?: boolean;
  /** Opens the pane's recorded conversation — the mode-proof scroll history. */
  onOpenConversation?: () => void;
  /** Puts this pane on the chat stage, read with the agent chat's timeline. */
  onOpenChat?: () => void;
  /** Opens the review of every uncommitted change this pane's agent made. */
  onReviewChanges?: () => void;
  /** Starts reading the review the moment the pointer reaches its button. */
  onReviewChangesPrefetch?: () => void;
  /** Opens the Git tab showing only what this pane's agent session changed. */
  onShowInGit?: () => void;
}) {
  const t = useT();
  const light = appearance === "light";
  // The title bar's brand voice, keyed to the PANE's ground rather than the
  // app theme — see PANE_BRAND in ./terminalThemes for why the two differ.
  const brand = PANE_BRAND[appearance];
  // What the split menu hangs off. The pane clips everything inside it, so the
  // menu is measured against this bar and drawn in front of the window — see
  // `anchorTo` in ./AgentPicker.
  const headerRef = useRef<HTMLElement | null>(null);
  // Which split button opened the CLI picker, if any.
  const [picking, setPicking] = useState<SplitDirection | null>(null);
  // The call-sign editor: null while the badge is just a badge, otherwise the
  // text being typed. Empty string is a real state (the field was cleared), so
  // "is it open" cannot be read off the text — hence null rather than "".
  const [draft, setDraft] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const commitRename = async () => {
    const wanted = (draft ?? "").trim();
    if (!wanted || wanted === name) {
      setDraft(null);
      return;
    }
    setSaving(true);
    // Kept open on a refusal — a duplicate call-sign is a name to CHANGE, and
    // throwing the typing away would make the user retype the part that was
    // fine. The grid says what went wrong.
    const accepted = await onRename?.(wanted);
    setSaving(false);
    if (accepted !== false) setDraft(null);
  };

  // With one installed CLI there is nothing to pick, so the button splits
  // straight away — a menu with a single entry is a click tax, not a choice.
  const choices = agents ?? [];
  const offersChoice = offersAgentChoice(choices);

  const startSplit = (direction: SplitDirection) => {
    if (offersChoice)
      setPicking((current) => (current === direction ? null : direction));
    else onSplit?.(direction);
  };

  /*
   * The bar's gesture explainer — our own card, not the browser's `title`.
   *
   * It used to be a native tooltip, and a native tooltip is drawn by the OS:
   * always the same white-and-black system box, square-cornered, blind to
   * the app's theme and to the brand. The explainer is the one piece of
   * teaching UI on the bar — it deserves the same design language as the bar
   * it explains. So it is a portal card now (the pane clips its children,
   * the same reason the recap card portals) carrying the SAME single
   * sentence, keyed to the PANE's own appearance so it reads in light and
   * dark alike.
   *
   * It stays strictly a tooltip: pointer-events: none, opened by a settled
   * hover on the bar itself (never over one of the bar's own controls, which
   * keep their small native labels), and dismissed by leaving, pressing, or
   * anything that moves the ground under it (scroll, resize).
   */
  const [tip, setTip] = useState<{
    left: number;
    top?: number;
    bottom?: number;
  } | null>(null);
  const tipTimer = useRef<number | undefined>(undefined);

  const cancelTip = () => {
    if (tipTimer.current !== undefined) {
      window.clearTimeout(tipTimer.current);
      tipTimer.current = undefined;
    }
  };
  const hideTip = () => {
    cancelTip();
    setTip(null);
  };
  const scheduleTip = () => {
    if (tip || tipTimer.current !== undefined) return;
    tipTimer.current = window.setTimeout(() => {
      tipTimer.current = undefined;
      const rect = headerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const left = Math.max(
        8,
        Math.min(rect.left + 8, window.innerWidth - 308),
      );
      const below = window.innerHeight - rect.bottom;
      // Flips above the bar when the pane sits at the bottom of the window —
      // an explainer that opens off-screen explains nothing.
      setTip(
        below < 150 && rect.top > below
          ? { left, bottom: window.innerHeight - rect.top + 6 }
          : { left, top: rect.bottom + 6 },
      );
    }, 500);
  };

  // The timer must not outlive the pane, and an open tip is positioned in
  // viewport coordinates — anything that moves the pane retires it.
  useEffect(() => cancelTip, []);
  useEffect(() => {
    if (!tip) return;
    const hide = () => setTip(null);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    return () => {
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
    };
  }, [tip]);

  // The explainer's words: ONE plain sentence, the same one the native
  // tooltip carried — by the maintainer's explicit choice. A first redesign
  // broke it into chip-led rows, and that was more furniture than the answer
  // needed; the card is branded, not busy. Only wired gestures make it in —
  // a maximized pane cannot be dragged, so its sentence never claims it can.
  const tipText = [
    onArrangeStart
      ? fill(t("agentic_grid.pane.tip_drag"), { pane: name })
      : "",
    onToggleMaximize
      ? onArrangeStart
        ? maximized
          ? t("agentic_grid.pane.tip_restore")
          : t("agentic_grid.pane.tip_fill")
        : maximized
          ? fill(t("agentic_grid.pane.tip_restore_named"), { pane: name })
          : fill(t("agentic_grid.pane.tip_fill_named"), { pane: name })
      : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <header
      ref={headerRef}
      data-testid={`pane-header-${name}`}
      // The grip. It is the header itself rather than a separate handle icon,
      // because that is where the gesture is already expected — every window on
      // every desktop is dragged by its title bar.
      //
      // The press is ignored when it lands on one of the header's own controls:
      // the buttons stop `mousedown`, which says nothing about `pointerdown`, so
      // without this check pressing Close would also pick the pane up and a
      // twitchy hand would move a pane it meant to shut.
      onPointerDown={(event) => {
        // A press is an answer, not a question — the explainer leaves.
        hideTip();
        if (!onArrangeStart) return;
        const target = event.target as HTMLElement | null;
        if (target?.closest("button, a, input, [role='menuitem']")) return;
        onArrangeStart(event);
      }}
      // A settled hover on the bar asks what the bar can do. The card yields
      // only to controls that carry their OWN native label (`[title]` — the
      // action cluster, the pencil, the seat chip), so two explanations never
      // stack. Everything else on the bar belongs to the bar — including the
      // recap line, which is a button but spans nearly the whole width: the
      // first version suppressed the card there, and "hover the title" is
      // exactly where people ask.
      onPointerOver={(event) => {
        const target = event.target as HTMLElement | null;
        if (target?.closest("[title], input, [role='menuitem']")) hideTip();
        else if (tipText) scheduleTip();
      }}
      onPointerLeave={hideTip}
      /*
       * Double-click the title bar to fill the workspace, and again to go back.
       *
       * The same gesture every window manager on every desktop already binds,
       * and the pane header is already the title bar — it is dragged like one.
       * The button beside it stays, because a gesture nothing on screen
       * advertises cannot be the only way in (the same rule the rename pencil
       * follows); this is the way people who never look for a button get there.
       *
       * Safe beside the drag above: `paneArrange` only lifts a pane once the
       * pointer has travelled `DRAG_THRESHOLD_PX`, so two clicks in one place
       * are two clicks and never a move. The control check is the same one — a
       * double-click on Close is a close, twice, not a maximize — and the
       * call-sign stops the event itself, because a double-click there already
       * means rename.
       */
      onDoubleClick={
        onToggleMaximize
          ? (event) => {
              hideTip();
              const target = event.target as HTMLElement | null;
              if (target?.closest("button, a, input, [role='menuitem']"))
                return;
              onToggleMaximize();
            }
          : undefined
      }
      className={cn(
        // No tinted strip of its own: the header shares the terminal's ground
        // and the border underneath is enough to say where the output begins.
        // Twelve tinted bands across the workspace were twelve horizontal
        // stripes the eye had to skip on the way to the text that matters.
        //
        // `min-h-7` rather than height by content: the bar holds a 24 px action
        // cluster, a 20 px rename field and a 16 px badge, and each of them
        // comes and goes on its own schedule (hover, rename, a status change).
        // Sized by whatever is in it, the header grew and shrank by a couple of
        // pixels under the pointer — and every one of those pixels is a row the
        // terminal underneath has to be refitted for. A floor holds it still.
        //
        // `overflow-hidden` is the other half of that promise: the left group
        // truncates and the action cluster keeps its width, so a narrow pane
        // ends in an ellipsis rather than pushing its own buttons off the edge.
        "group/header relative flex min-h-7 items-center justify-between gap-1.5 overflow-hidden border-b px-2 py-0.5",
        onArrangeStart && (arranging ? "cursor-grabbing" : "cursor-grab"),
      )}
      style={
        {
          borderColor: PANE_CHROME[appearance].border,
          // Claims the touch gesture for the drag. Without it a touch that
          // starts on the header scrolls the workspace instead of lifting the
          // pane, and the drag never begins at all.
          touchAction: onArrangeStart ? "none" : undefined,
          // The bar's ladder, published as variables so hover/focus states can
          // be CLASSES. An inline `color` beats every class (see PaneAction's
          // note), so anything that changes on interaction reads these instead
          // of receiving an inline style.
          "--pane-accent": brand.accent,
          "--pane-accent-soft": brand.accentSoft,
          "--pane-ink": brand.ink,
          "--pane-ink-muted": brand.inkMuted,
          "--pane-ink-faint": brand.inkFaint,
          "--pane-chip": brand.chip,
        } as React.CSSProperties
      }
    >
      {/* The brand hairline: a signal-yellow (gold, on paper) rule that sweeps
          from under the call-sign of THE focused pane. It is the workspace's
          "you are here" mark — drawn on one pane at a time, so it stays a mark
          rather than a uniform. Opacity, not mounting, so focus changes glide. */}
      <span
        aria-hidden="true"
        data-testid={`pane-header-accent-${name}`}
        className={cn(
          "pointer-events-none absolute inset-x-0 bottom-0 h-[2px] transition-opacity duration-200",
          focused ? "opacity-100" : "opacity-0",
        )}
        style={{
          background: `linear-gradient(90deg, ${brand.accent}, ${brand.accentSoft} 55%, transparent 92%)`,
        }}
      />
      <div className="flex min-w-0 flex-1 items-center gap-2">
        {showArrangeHandle && onArrangeStart && (
          <button type="button" aria-label={fill(t("agentic_grid.pane.move"), { pane: name })} title={fill(t("agentic_grid.pane.move"), { pane: name })}
            data-ide-drag-handle="true"
            data-testid={`pane-move-${name}`}
            onPointerDown={(event) => {
              hideTip();
              event.stopPropagation();
              onArrangeStart(event);
            }}
            onClick={(event) => event.stopPropagation()}
            className="flex h-5 w-5 shrink-0 cursor-grab items-center justify-center rounded text-[color:var(--pane-ink-muted)] hover:bg-[color:var(--pane-chip)] hover:text-[color:var(--pane-ink)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color:var(--pane-accent)] active:cursor-grabbing"
            style={{ touchAction: "none" }}>
            <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        )}
        {draft !== null ? (
          /*
           * The call-sign, being typed.
           *
           * A form rather than a bare input so Enter saves the way it does in
           * every other name field in the app, and Escape closes it — the two
           * keys somebody renaming a pane will reach for without looking.
           *
           * It SHRINKS. A fixed 128 px field plus its two buttons is wider than
           * a pane in a twelve-pane wall has to spare, and beside an action
           * cluster that keeps its own width the surplus went somewhere: the
           * save and cancel buttons were pushed under the cluster, so the one
           * control the user needed next was the one they could not reach.
           */
          <form
            className="flex min-w-0 flex-1 items-center gap-1"
            onSubmit={(event) => {
              event.preventDefault();
              void commitRename();
            }}
          >
            <input
              autoFocus
              value={draft}
              maxLength={MAX_TERMINAL_NAME}
              disabled={saving}
              aria-label={fill(t("agentic_grid.pane.rename"), { pane: name })}
              data-testid={`pane-rename-input-${name}`}
              onFocus={(event) => event.currentTarget.select()}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape") setDraft(null);
                // The pane underneath is a live terminal listening for keys.
                // Without this, typing a name also types into the agent.
                event.stopPropagation();
              }}
              className={cn(
                "w-full min-w-0 max-w-[9rem] rounded-md px-2 py-0.5 font-display text-meta font-semibold tracking-tight outline-none",
                // A field is a LIFT surface, and a surface with a real fill
                // needs no rim: the chip ground is what says "you can type
                // here". Focus answers with a ring rather than a second fill
                // or a brighter edge. Both come from the pane's own ladder
                // (the `--pane-*` variables the header publishes), so a light
                // pane inside a dark app still edits on its own ground.
                "transition-shadow focus:ring-2 focus:ring-[color:var(--pane-accent-soft)] disabled:opacity-60",
              )}
              style={{ color: brand.ink, background: brand.chip }}
            />
            <button
              type="submit"
              disabled={saving || !draft.trim()}
              aria-label={fill(t("agentic_grid.pane.rename_save"), { pane: name })}
              data-testid={`pane-rename-save-${name}`}
              className={cn(
                "flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[color:var(--pane-ink)]",
                "transition-colors duration-150 hover:bg-[color:var(--pane-chip)] disabled:opacity-40",
                "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color:var(--pane-accent)]",
              )}
            >
              {saving ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Check className="h-3 w-3" />
              )}
            </button>
            <button
              type="button"
              disabled={saving}
              aria-label={fill(t("agentic_grid.pane.rename_cancel"), { pane: name })}
              onClick={() => setDraft(null)}
              className={cn(
                "flex h-5 w-5 shrink-0 items-center justify-center rounded-md",
                "transition-colors duration-150",
                "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color:var(--pane-accent)]",
                // On the pane's ground, so the pane's ink — not the app's
                // muted-foreground, which disagrees exactly in mixed mode.
                // Read from the `--pane-*` variables the header publishes
                // rather than from a hex per appearance: the ladder lives in
                // ONE table (./terminalThemes) and every reader of it agrees.
                "text-[color:var(--pane-ink-muted)] hover:bg-[color:var(--pane-chip)]",
                "hover:text-[color:var(--pane-ink)]",
              )}
            >
              <X className="h-3 w-3" />
            </button>
          </form>
        ) : (
          <>
            <span
              // Double-click is the gesture every tab strip and file manager
              // already uses for "rename this", so it is offered here too — but
              // it is never the only way in, because nothing on screen advertises
              // it. The pencil beside it is what makes the feature findable.
              //
              // The event stops here: the bar underneath reads a double-click as
              // "fill the workspace", and one gesture must not do two things.
              // The call-sign is the more specific target, so it wins.
              onDoubleClick={
                onRename
                  ? (event) => {
                      event.stopPropagation();
                      setDraft(name);
                    }
                  : undefined
              }
              // No native `title` here: the rename gesture is a row in the
              // bar's own explainer card, which replaced the system tooltip.
              // The focused pane's call-sign wears the FILL — white type-holes
              // on a dark pane, warm near-black on a light one. Every other
              // name sits on a quiet chip (the pane's lift step) so the plate
              // stays the workspace's one standing mark: a filled badge on all
              // twelve panes marked nothing, because a marker everyone wears
              // is a uniform. The colours come from PANE_BRAND (the pane's own
              // ground), never the app theme.
              //
              // No shadow under the plate any more. Depth on this ground is
              // carried by the fill; a soft glow around a 40px badge was a
              // bloom standing in for the contrast the fill already has.
              className="shrink-0 rounded-md px-1.5 py-0.5 font-display text-meta font-semibold leading-none tracking-tight transition-[background-color,color] duration-150"
              style={
                focused
                  ? { background: brand.accent, color: brand.onAccent }
                  : { background: brand.chip, color: brand.ink }
              }
            >
              {name}
            </span>
            {onRename && (
              <button
                type="button"
                aria-label={fill(t("agentic_grid.pane.rename"), { pane: name })}
                title={fill(t("agentic_grid.pane.rename"), { pane: name })}
                data-testid={`pane-rename-${name}`}
                onClick={() => setDraft(name)}
                onMouseDown={(event) => event.stopPropagation()}
                className={cn(
                  // Ink and hover ground come from the pane's own ladder
                  // (`--pane-*`, published on the header), not from a literal
                  // per-appearance hex and not from the app's tokens: a light
                  // pane can sit inside a dark app, and this button has to read
                  // on the ground it is actually drawn on.
                  "flex h-5 w-5 shrink-0 items-center justify-center rounded-md transition-opacity",
                  "text-[color:var(--pane-ink-muted)] hover:bg-[color:var(--pane-chip)]",
                  "opacity-0 focus-visible:opacity-100 group-hover/header:opacity-100",
                )}
              >
                <Pencil className="h-3 w-3" />
              </button>
            )}
          </>
        )}
        {/*
          The pane's own state, in the colour language the rest of the section
          already speaks (see ./PaneActivityPill, which owns the vocabulary and
          is the same badge the chat rail shows).

          Only three of the four states are news. `live` is a property of the
          PIPE — true for nearly every pane nearly all the time — so a standing
          dot on all twelve headers would mark nothing, which is exactly the
          badge the activity pill was written to replace. It is kept in the DOM
          and fades in with the rest of the header's controls, so the answer is
          one hover away for anyone who wants it, while `connecting`, `exited`
          and `error` announce themselves whether or not anyone is pointing.
        */}
        <span
          data-testid={`pane-status-${name}`}
          data-status={status}
          className={cn(
            "flex shrink-0 items-center transition-opacity duration-200",
            status === "live"
              ? "opacity-0 group-hover/header:opacity-60"
              : "opacity-100",
          )}
        >
          <PaneActivityPill status={status} detail={statusDetail} />
        </span>
        <PaneRecap
          name={name}
          displayName={displayName}
          recap={recap}
          detail={recapDetail}
          source={recapMeta?.source}
          reason={recapMeta?.reason}
          writer={recapMeta?.writer}
          note={recapMeta?.note}
          generatedAt={recapMeta?.generatedAt}
          light={light}
          onSave={recapActions?.onSave}
          onClear={recapActions?.onClear}
          onRefresh={recapActions?.onRefresh}
        />
        {/* Which of several subscriptions this pane is spending. Only rendered
            when the user actually has more than one, so the header stays quiet
            for everybody else — but with two seats open side by side, knowing
            which pane bills which plan is the whole point. */}
        {accountLabel && (
          <span
            // Allowed to give way (`min-w-0`, no `shrink-0`): which seat a pane
            // bills is worth a badge, but never worth pushing the call-sign or
            // the pane's own state off a narrow header to say it.
            // 11px is the type floor, and this badge sat below it. It also
            // wore the placeholder ink, which is reserved for text that is NOT
            // information — which seat a pane bills plainly is. Meta ink, on
            // the lift chip, with no rim: the fill already separates it.
            className="min-w-0 max-w-[8rem] truncate rounded-full px-2 py-px font-display text-micro font-medium tracking-wide"
            style={{ color: brand.inkMuted, backgroundColor: brand.chip }}
            title={fill(t("agentic_grid.pane.running_on_account"), { account: accountLabel })}
            data-testid={`pane-account-${name}`}
          >
            {accountLabel}
          </span>
        )}
      </div>

      <PaneDoneGateBadge workspaceId={githubStatusEnabled ? workspaceId : undefined} name={name} appearance={appearance} />
      <SessionGitHubBadge workspaceId={githubStatusEnabled ? workspaceId : undefined} name={name} appearance={appearance} />
      {/* Pane actions appear where the eye already is: on the pane under the
          pointer, on the focused pane, and while one of their menus is open.
          Five buttons on every header of a twelve-pane wall were sixty
          controls nobody was using at once — the redesign shows each pane's
          five exactly when that pane is the one being worked. They stay in
          the DOM throughout (opacity, not display), so keyboard focus and
          tests reach them regardless. */}
      <div
        className={cn(
          "flex shrink-0 items-center gap-0.5 transition-opacity",
          focused || maximized || picking !== null
            ? "opacity-100"
            : "opacity-0 focus-within:opacity-100 group-hover/header:opacity-100",
        )}
      >
        <PromptHistoryButton
          terminal={name}
          workspaceId={workspaceId}
          count={promptCount}
          light={light}
        />
        {/* One click from a terminal to the same conversation read as a chat
            — the timeline the front page's chat draws, with this pane's
            thinking, tool calls and answers in it (maintainer, 2026-08-26). */}
        {onOpenChat && (
          <PaneAction
            label={t("agentic_grid.pane_chat.open").replace("{0}", name)}
            testId={`pane-open-chat-${name}`}
            onClick={onOpenChat}
          >
            <MessageSquare className="h-3.5 w-3.5" aria-hidden="true" />
          </PaneAction>
        )}
        {/* The one scroll-history entry point that cannot flicker away: the
            CLI may flip its scroll-owner mode mid-session (Claude Code does),
            but the pane's recorded conversation is always openable. */}
        <PaneAction
          label={t("agentic_grid.conversation.open").replace("{0}", name)}
          testId={`pane-conversation-${name}`}
          onClick={onOpenConversation}
        >
          <BookOpenText className="h-3.5 w-3.5" aria-hidden="true" />
        </PaneAction>
        {onReviewChanges && (
          <PaneAction
            label={fill(t("agentic_grid.pane.review_changes"), { pane: name })}
            testId={`pane-review-changes-${name}`}
            onClick={onReviewChanges}
            onHover={onReviewChangesPrefetch}
          >
            <FileDiff className="h-3.5 w-3.5" aria-hidden="true" />
          </PaneAction>
        )}
        {onShowInGit && (
          <PaneAction
            label={fill(t("agentic_grid.pane.show_in_git"), { pane: name })}
            testId={`pane-show-in-git-${name}`}
            onClick={onShowInGit}
          >
            <FolderGit2 className="h-3.5 w-3.5" aria-hidden="true" />
          </PaneAction>
        )}
        <PaneAction
          label={fill(
            t(maximized ? "agentic_grid.pane.restore" : "agentic_grid.pane.maximize"),
            { pane: name },
          )}
          testId={`pane-maximize-${name}`}
          onClick={onToggleMaximize}
        >
          {maximized ? (
            <Minimize2 className="h-3.5 w-3.5" />
          ) : (
            <Maximize2 className="h-3.5 w-3.5" />
          )}
        </PaneAction>
        <PaneAction
          label={fill(t("agentic_grid.pane.split_right"), { pane: name })}
          testId={`pane-split-right-${name}`}
          disabled={splitDisabled}
          expanded={offersChoice ? picking === "right" : undefined}
          onClick={onSplit ? () => startSplit("right") : undefined}
        >
          <SplitRightIcon className="h-3.5 w-3.5" />
        </PaneAction>
        <PaneAction
          label={fill(t("agentic_grid.pane.split_down"), { pane: name })}
          testId={`pane-split-down-${name}`}
          disabled={splitDisabled}
          expanded={offersChoice ? picking === "down" : undefined}
          onClick={onSplit ? () => startSplit("down") : undefined}
        >
          <SplitBelowIcon className="h-3.5 w-3.5" />
        </PaneAction>
        <PaneAction
          label={fill(t("agentic_grid.close_pane.aria"), { pane: name })}
          testId={`pane-close-${name}`}
          danger
          onClick={onClose}
        >
          <X className="h-3.5 w-3.5" />
        </PaneAction>
      </div>

      {picking && (
        <AgentPickerMenu
          title={
            picking === "right"
              ? t("agentic_grid.pane.split_right_picker")
              : t("agentic_grid.pane.split_down_picker")
          }
          ariaLabel={fill(
            t(
              picking === "right"
                ? "agentic_grid.pane.split_right_picker_aria"
                : "agentic_grid.pane.split_down_picker_aria",
            ),
            { pane: name },
          )}
          agents={choices}
          testId={`pane-split-menu-${picking}-${name}`}
          itemTestId={(agent) => `pane-split-${picking}-${name}-${agent}`}
          className="right-2 top-full mt-1"
          // Measured against this bar and drawn in front of the window. A pane
          // is `overflow-hidden` by necessity, so a menu positioned inside one
          // is cut off at its edge — in a twelve-pane wall that left a sliver
          // of the first entry and nothing to pick from. It also flips above
          // the header when the pane sits at the bottom of the screen.
          anchorTo={headerRef.current}
          onDismiss={() => setPicking(null)}
          onInstalled={() => onAgentsChanged?.()}
          onPick={(agent) => {
            setPicking(null);
            onSplit?.(picking, agent);
          }}
        />
      )}

      {/* Suppressed while the bar is doing something else: mid-drag, with the
          split menu open, or while the call-sign is being renamed — a card
          that teaches gestures must never sit on top of one in progress. */}
      {tip &&
        tipText !== "" &&
        !arranging &&
        picking === null &&
        draft === null &&
        typeof document !== "undefined" &&
        createPortal(
          <PaneHeaderTip
            name={name}
            appearance={appearance}
            pos={tip}
            text={tipText}
          />,
          document.body,
        )}
    </header>
  );
}

/**
 * The title bar's gesture explainer — the branded card that replaced the
 * native `title` tooltip (see the long note in PaneHeader for why).
 *
 * Deliberately the SAME one sentence the system tooltip carried, redressed:
 * the maintainer liked the words and rejected a chip-and-row redesign of
 * them — the ask was brand, not furniture. So the card is exactly a rounded
 * corner, the brand hairline, and the sentence, coloured off PANE_BRAND /
 * PANE_CHROME — the PANE's own ground — so it reads in light mode, dark
 * mode, and the mixed configurations. `pointer-events: none` keeps it a
 * label, never a thing the pointer can land on.
 */
function PaneHeaderTip({
  name,
  appearance,
  pos,
  text,
}: {
  name: string;
  appearance: TerminalAppearance;
  pos: { left: number; top?: number; bottom?: number };
  text: string;
}) {
  const brand = PANE_BRAND[appearance];
  const chrome = PANE_CHROME[appearance];
  return (
    <div
      role="tooltip"
      data-testid={`pane-header-tip-${name}`}
      className={cn(
        // `rounded-lg` — the one radius a floating surface takes. It used to be
        // `rounded-xl`, a fourth radius in a section that already has three.
        "pointer-events-none fixed z-[70] w-max max-w-[360px] overflow-hidden rounded-lg border",
        "animate-in fade-in-0 duration-150",
        pos.top !== undefined ? "slide-in-from-top-1" : "slide-in-from-bottom-1",
      )}
      style={{
        left: pos.left,
        ...(pos.top !== undefined ? { top: pos.top } : { bottom: pos.bottom }),
        // Opaque, unlike the pane's glass: the card can land on top of another
        // pane's text, and an explainer must not be read THROUGH. This is the
        // pane's own float step — the one surface here that is genuinely off
        // the plane, so the one that gets a real shadow.
        background: chrome.float,
        borderColor: chrome.border,
        boxShadow: "0 12px 32px -8px rgb(var(--scrim-rgb) / 0.55)",
      }}
    >
      {/* The same hairline the focused pane wears under its bar. */}
      <span
        aria-hidden="true"
        className="block h-[2px]"
        style={{
          background: `linear-gradient(90deg, ${brand.accent}, ${brand.accentSoft} 60%, transparent 95%)`,
        }}
      />
      <p
        className="px-3.5 py-2.5 text-sm leading-relaxed"
        style={{ color: brand.ink }}
      >
        {text}
      </p>
    </div>
  );
}

/*
 * A header button.
 *
 * It no longer takes the pane's appearance: every colour it wears is read from
 * the `--pane-*` variables the header publishes, which resolve against the
 * PANE's ground whatever the app theme is doing. The prop used to pick between
 * two hard-coded hexes per state — the same ladder written a second time, and
 * the copy that drifted.
 */
function PaneAction({
  label,
  testId,
  danger = false,
  disabled = false,
  expanded,
  onClick,
  onHover,
  children,
}: {
  label: string;
  testId: string;
  danger?: boolean;
  disabled?: boolean;
  /** Set when this button opens a menu — announces its state to a screen reader. */
  expanded?: boolean;
  onClick?: () => void;
  /** The pointer reached the button: a chance to start work its click will need. */
  onHover?: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onPointerEnter={onHover}
      aria-label={label}
      title={label}
      data-testid={testId}
      aria-haspopup={expanded === undefined ? undefined : "menu"}
      aria-expanded={expanded}
      disabled={disabled || !onClick}
      onClick={(e) => {
        // The pane's own mousedown selects it as the prompt target; an action
        // click must not also count as "typing here".
        e.stopPropagation();
        onClick?.();
      }}
      onMouseDown={(e) => e.stopPropagation()}
      className={cn(
        "flex h-6 w-6 shrink-0 items-center justify-center rounded",
        // Colour AND background, over the same 150 ms: hovering used to change
        // only the ground behind the glyph, which on a translucent pane is a
        // very small amount of contrast to confirm the pointer is on target.
        "transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-30",
        // Reachable by keyboard and visibly so. The cluster is revealed by
        // `focus-within`, which is worth nothing if the focused button then
        // looks identical to its four neighbours. The ring reads the header's
        // own fill variable, so it lands on the PANE's ground rather than the
        // app's — a light pane inside a dark app is a supported combination.
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color:var(--pane-accent)]",
        // The resting colour is a CLASS rather than an inline style, and that is
        // load-bearing rather than tidiness: an inline `color` beats every
        // class, so the hover colour below would simply never take effect.
        // Both steps come from the header's `--pane-*` ladder; they used to be
        // a hex per appearance, which is the same ladder written twice.
        "text-[color:var(--pane-ink-muted)]",
        danger
          ? "hover:bg-destructive/20 hover:text-destructive"
          : "hover:bg-[color:var(--pane-chip)] hover:text-[color:var(--pane-ink)]",
      )}
    >
      {children}
    </button>
  );
}

/**
 * The two tones a pane notice comes in, resolved against the PANE's own ground.
 *
 * Not read from the app's `--warning` / `--destructive` variables, and that is
 * the whole reason this table exists rather than a call to the section's shared
 * `Notice`: the terminal appearance is a separate setting from the app theme
 * (plenty of people run dark panes in a light app, and the reverse — see the
 * appearance note in ./AgenticGrid), so a value resolved from the app's `.dark`
 * block lands on the wrong ground in exactly those two configurations.
 *
 * The values ARE those tokens, re-derived per appearance: `#D6A94A` / `#A57A1D`
 * is the degraded hue, `#E8574C` / `#C72E23` the fault hue. An earlier version
 * dropped the hue entirely and separated the two tones by weight, using the
 * pane's full ink for an error — which puts a status in the ink ramp, makes the
 * loudest thing on a dead pane indistinguishable from its brightest heading,
 * and leaves colour with nothing to say. Fault and degraded are two of the
 * three jobs colour has in this product; a pane notice is exactly where they
 * are spent.
 */
