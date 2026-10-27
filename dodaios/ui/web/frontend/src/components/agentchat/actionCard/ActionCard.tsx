import { useEffect, useId, useRef, useState, type ReactNode, type Ref } from "react";
import { Check, ChevronDown, CircleAlert, Copy, Loader2 } from "lucide-react";
import { useT } from "@/i18n";
import { robustCopy } from "@/lib/clipboard";
import { cn } from "@/lib/utils";
import "./ActionCard.css";

/**
 * One card for everything that waits on the person: a tool approval, a
 * secure field, a change an agent proposes. Each kind is a thin skin that
 * maps its data onto these props; the frame, the order of things and the
 * settled one-liner are the same everywhere, so a person learns them once.
 *
 *   source chip ─────────────────────────── trailing (dismiss)
 *   Title, as a question
 *   subtitle lines (where · what · why · context)
 *   ▸ disclosure with the exact command, copyable
 *   free body
 *   failure note / answered note
 *   [primary] [secondary]                 [tertiary]
 *   ⚠ caution caption, under the card
 *
 * Settled, the card folds into one line: source icon, a status dot, the
 * outcome and a quiet detail, with a chevron when there is more to read.
 */

export type ActionTone = "primary" | "secondary" | "tertiary";

export interface ActionSpec {
  id: string;
  label: string;
  tone: ActionTone;
  onSelect: () => void;
  disabled?: boolean;
  /** Why the action is disabled, as its tooltip. */
  reason?: string;
  /** A tooltip for the enabled action. */
  hint?: string;
  icon?: ReactNode;
  keyShortcut?: string;
  testId?: string;
}

export type SettledTone = "success" | "danger" | "muted" | "warning";

export interface SettledSpec {
  tone: SettledTone;
  label: string;
  /** What it was about, after a " · ". */
  detail?: string;
  /** Read when the line is expanded. */
  body?: ReactNode;
  /** Small actions that stay available on the settled line ("Allow every time"). */
  actions?: ActionSpec[];
  /** Shown beside the actions once one of them did its job ("Rule saved"). */
  receipt?: ReactNode;
}

export interface ActionCardProps {
  /** A stable id for this card: remembers whether its settled line is open. */
  id: string;
  source: { icon: ReactNode; label: string; showLabel?: boolean };
  title: ReactNode;
  /** The accessible name, "Needs approval: Run this command?". */
  ariaLabel: string;
  /** Subtitle lines in their fixed order: where, what, why, context. */
  lines?: ReactNode[];
  disclosure?: { text: string; showLabel: string; hideLabel: string; defaultOpen?: boolean };
  children?: ReactNode;
  failure?: string | null;
  note?: ReactNode;
  actions?: ActionSpec[];
  /** The action in flight: it spins, every other one waits. */
  pending?: string | null;
  trailing?: ReactNode;
  /** An already worded caution, shown under the card. */
  caution?: string | null;
  settled?: SettledSpec | null;
  testId?: string;
  state?: string;
  rootRef?: Ref<HTMLDivElement>;
  className?: string;
}

/** Which settled cards the person opened, across remounts (a virtualized list, a fold). */
const openSettled = new Map<string, boolean>();

export function ActionCard(props: ActionCardProps) {
  if (props.settled) return <SettledCard {...props} settled={props.settled} />;
  return <OpenCard {...props} />;
}

function OpenCard({
  source, title, ariaLabel, lines, disclosure, children, failure, note, actions = [], pending = null, trailing, caution,
  testId, state = "open", rootRef, className,
}: ActionCardProps) {
  const titleId = useId();
  const lead = actions.filter((a) => a.tone !== "tertiary");
  const tail = actions.filter((a) => a.tone === "tertiary");
  return <div className={cn("action-card-wrap", className)} data-testid={testId} data-state={state}>
    <div ref={rootRef} role="group" aria-label={ariaLabel} aria-busy={pending !== null || undefined}
      className="action-card" data-action-card="open">
      <div className="flex items-center gap-2">
        <SourceChip icon={source.icon} label={source.label} showLabel={source.showLabel !== false} />
        {trailing ? <div className="-mr-1.5 ml-auto flex shrink-0 items-center">{trailing}</div> : null}
      </div>
      <h3 id={titleId} className="mt-2 text-sm font-semibold leading-5 text-foreground-strong [overflow-wrap:anywhere]">{title}</h3>
      {lines?.filter(Boolean).length ? <div className="mt-0.5 space-y-0.5">
        {lines.filter(Boolean).map((line, i) => <p key={i} className="m-0 text-xs leading-5 text-muted-foreground [overflow-wrap:anywhere]">{line}</p>)}
      </div> : null}
      {disclosure?.text ? <Disclosure {...disclosure} /> : null}
      {children ? <div className="mt-2.5 min-w-0">{children}</div> : null}
      {failure ? <p role="alert" className="mt-2.5 flex items-start gap-1.5 text-xs leading-5 text-destructive">
        <CircleAlert aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span>{failure}</span>
      </p> : null}
      {note ? <p className="mt-2 text-xs leading-5 text-muted-foreground">{note}</p> : null}
      {actions.length ? <div className="mt-3 flex flex-wrap items-center gap-2">
        {lead.map((a) => <ActionButton key={a.id} action={a} pending={pending} />)}
        {tail.length ? <div className="ml-auto flex flex-wrap items-center gap-1">
          {tail.map((a) => <ActionButton key={a.id} action={a} pending={pending} />)}
        </div> : null}
      </div> : null}
    </div>
    {caution ? <p className="action-card-caution" data-testid="action-card-caution">
      <CircleAlert aria-hidden className="h-3.5 w-3.5 shrink-0" /><span>{caution}</span>
    </p> : null}
  </div>;
}

function SettledCard({ id, source, ariaLabel, lines, disclosure, children, settled, testId, state, rootRef, className }:
  ActionCardProps & { settled: SettledSpec }) {
  const t = useT();
  const bodyId = useId();
  const expandable = Boolean(lines?.filter(Boolean).length || disclosure?.text || children || settled.body);
  const [open, setOpen] = useState(() => openSettled.get(id) ?? false);
  const toggle = () => setOpen((was) => {
    openSettled.set(id, !was);
    return !was;
  });
  const sentence = <>
    <span className={cn("action-card-dot")} data-tone={settled.tone} aria-hidden />
    <span className={cn("shrink-0", settled.tone === "danger" ? "text-destructive" : "text-foreground-secondary")}>{settled.label}</span>
    {settled.detail ? <span className="min-w-0 truncate text-muted-foreground">{` · ${settled.detail}`}</span> : null}
  </>;
  const extras = settled.actions?.length || settled.receipt
    ? <div className="flex shrink-0 flex-wrap items-center gap-1">
      {settled.receipt}
      {settled.actions?.map((a) => <ActionButton key={a.id} action={a} pending={null} compact />)}
    </div>
    : null;
  return <div className={cn("action-card-wrap", className)} data-testid={testId} data-state={state} aria-label={ariaLabel}
    role={expandable ? "group" : "status"}>
    <div ref={rootRef} className="action-card-settled" data-action-card="settled" data-tone={settled.tone}>
      <div className="flex min-w-0 items-center gap-2">
        <span className="action-card-tile action-card-tile-sm" aria-hidden>{source.icon}</span>
        {expandable
          ? <button type="button" onClick={toggle} aria-expanded={open} aria-controls={bodyId}
            title={open ? t("action_card.collapse") : t("action_card.expand")}
            className="flex min-w-0 flex-1 items-center gap-2 rounded-md text-left text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            {sentence}
            <ChevronDown aria-hidden className={cn("ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-150", open && "rotate-180")} />
          </button>
          : <p className="m-0 flex min-w-0 flex-1 items-center gap-2 text-xs">{sentence}</p>}
        {extras}
      </div>
      {expandable && open ? <div id={bodyId} className="action-card-settled-body">
        {lines?.filter(Boolean).map((line, i) => <p key={i} className="m-0 text-xs leading-5 text-muted-foreground [overflow-wrap:anywhere]">{line}</p>)}
        {disclosure?.text ? <Disclosure {...disclosure} defaultOpen /> : null}
        {children}
        {settled.body}
      </div> : null}
    </div>
  </div>;
}

export function SourceChip({ icon, label, showLabel = true }: { icon: ReactNode; label: string; showLabel?: boolean }) {
  return <span className="flex min-w-0 items-center gap-1.5" title={showLabel ? undefined : label}>
    <span className="action-card-tile" aria-hidden>{icon}</span>
    {showLabel ? <span className="truncate text-xs font-medium text-muted-foreground">{label}</span> : <span className="sr-only">{label}</span>}
  </span>;
}

function ActionButton({ action, pending, compact = false }: { action: ActionSpec; pending: string | null; compact?: boolean }) {
  const busy = pending === action.id;
  const disabled = Boolean(action.disabled) || (pending !== null && !busy);
  return <button type="button" onClick={action.onSelect} disabled={disabled || busy}
    title={action.disabled ? action.reason : action.hint}
    aria-keyshortcuts={action.keyShortcut}
    data-tone={action.tone}
    data-testid={action.testId}
    className={cn("action-card-button", compact && "action-card-button-compact")}>
    {busy ? <Loader2 aria-hidden className="h-3.5 w-3.5 animate-spin" /> : action.icon}
    <span>{action.label}</span>
  </button>;
}

function Disclosure({ text, showLabel, hideLabel, defaultOpen = false }: NonNullable<ActionCardProps["disclosure"]>) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return <div className="mt-2.5 min-w-0">
    <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-controls={id}
      className="flex items-center gap-1 rounded-md text-xs font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <ChevronDown aria-hidden className={cn("h-3.5 w-3.5 transition-transform duration-150", !open && "-rotate-90")} />
      {open ? hideLabel : showLabel}
    </button>
    {open ? <div id={id} className="action-card-code">
      <pre data-testid="action-card-detail">{text}</pre>
      <CopyText text={text} />
    </div> : null}
  </div>;
}

function CopyText({ text }: { text: string }) {
  const t = useT();
  const [done, setDone] = useState(false);
  const timer = useRef<number | null>(null);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);
  const copy = async () => {
    // The clipboard may be unavailable; the text stays selectable either way.
    if (!(await robustCopy(text))) return;
    setDone(true);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setDone(false), 1400);
  };
  const label = done ? t("action_card.copied") : t("action_card.copy");
  return <button type="button" onClick={() => void copy()} aria-label={label} title={label} className="action-card-copy">
    {done ? <Check aria-hidden className="h-3.5 w-3.5" /> : <Copy aria-hidden className="h-3.5 w-3.5" />}
  </button>;
}
