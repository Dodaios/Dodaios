import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Bot, ChevronRight, Hand, Hourglass, KeyRound, Lightbulb, Loader2, Plug, RefreshCw, Rocket, ShieldCheck, SquareTerminal,
  type LucideIcon,
} from "lucide-react";

import { ToolChoiceIcon } from "@/components/agentchat/ToolChoiceChips";
import { serviceIconRow } from "@/components/agentchat/toolChoices";
import { AgentMark } from "@/components/agentic/AgentMark";
import { openPaneSession } from "@/components/agentic/openPaneSession";
import { ProviderLogo } from "@/components/providers/ProviderLogo";
import { AgentSwatch } from "@/components/society/AgentSwatch";
import { useSocietyRoster } from "@/components/society/data";
import { QuickTooltip } from "@/components/ui/tooltip";
import { refreshPluginAttention } from "@/hooks/usePluginAttention";
import { useSignIn } from "@/hooks/useSignIn";
import { fill, useT } from "@/i18n";
import { requestPluginFocus } from "@/lib/customConnector";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

import { NOTICES_SHOWN, type NoticeAsk, type RailNotice } from "./railNotices";
import { goToStatusRow, openKeys } from "./statusRows";

/**
 * The rail's notices, drawn: one round tile per notice.
 *
 * A tile shows WHO it is about in its middle (the service's own logo, the
 * coding CLI's mark, the agent's face) and WHAT is asked as a small badge on
 * its corner (reconnect, a question, an approval, a warning). Hovering says it
 * in a sentence, with what a click does; the click does it. A connection that
 * ended is reconnected right from its tile: the click starts the service's own
 * sign-in and the tile leaves once the service reports connected.
 *
 * Loaded only when there is a notice: the logos and the sign-in stay out of
 * the start of the app for the usual case of a quiet rail.
 */

const TILE =
  "relative flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-secondary ring-1 ring-inset ring-border " +
  "transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** The badge's fill: `primary` when someone waits for the person, `warning` when something stopped working. */
const BADGE_TONE: Record<RailNotice["tone"], string> = {
  needs: "bg-primary text-primary-foreground",
  trouble: "bg-warning text-background",
};

const ASK_ICON: Partial<Record<NoticeAsk, LucideIcon>> = {
  reconnect: RefreshCw,
  connect: Plug,
  approval: ShieldCheck,
  credential: KeyRound,
  proposal: Lightbulb,
  takeover: Hand,
  waiting: Hourglass,
};
/** A question and a warning read best as the character itself. */
const ASK_SIGN: Partial<Record<NoticeAsk, string>> = { question: "?", trouble: "!" };

const GLYPH: Record<"agent" | "terminal" | "mission", LucideIcon> = { agent: Bot, terminal: SquareTerminal, mission: Rocket };

/** What is asked, on the tile's corner. `busy` turns it into a quiet spinner. */
function AskBadge({ notice, busy = false, small = false }: { notice: RailNotice; busy?: boolean; small?: boolean }) {
  const Icon = busy ? Loader2 : ASK_ICON[notice.ask];
  return (
    <span aria-hidden data-testid="rail-notice-badge" data-ask={notice.ask}
      className={cn(
        "absolute flex items-center justify-center rounded-full ring-2",
        small ? "-bottom-1 -right-1 h-4 w-4 ring-popover" : "-bottom-0.5 -right-0.5 h-[18px] w-[18px] ring-sidebar",
        BADGE_TONE[notice.tone],
      )}>
      {Icon
        ? <Icon strokeWidth={2.4} className={cn(small ? "h-2.5 w-2.5" : "h-[11px] w-[11px]", busy && "motion-safe:animate-spin")} />
        : <span className="text-[11px] font-bold leading-none">{ASK_SIGN[notice.ask] ?? "!"}</span>}
    </span>
  );
}

/** An agent's own face from the roster; a plain sign until the roster has answered. */
function AgentFace({ agentId, size }: { agentId: string; size: number }) {
  const roster = useSocietyRoster();
  const agent = roster.data?.agents.find((candidate) => candidate.agentId === agentId);
  if (!agent) return <Bot aria-hidden strokeWidth={1.75} className="h-5 w-5 text-muted-foreground" />;
  return <AgentSwatch agent={agent} size={size} />;
}

/** Who the notice is about: a logo kept in its own colours, a face, or a plain sign. */
function SubjectMark({ notice, size }: { notice: RailNotice; size: number }) {
  const { mark, subject } = notice;
  if (mark.type === "plugin" || mark.type === "tool") {
    return <ToolChoiceIcon row={serviceIconRow(mark.type === "tool" ? "cli" : "plugin", mark.id, subject)} size={size} />;
  }
  if (mark.type === "provider") {
    return <ProviderLogo providerId={mark.id} label={subject} className="h-full w-full rounded-full bg-transparent" />;
  }
  if (mark.type === "cli") {
    return <span className="flex" style={{ width: size, height: size }}>
      <AgentMark agent={mark.id} label={subject} variant="plain" className="h-full w-full opacity-100" />
    </span>;
  }
  if (mark.type === "agent") return <AgentFace agentId={mark.id} size={Math.round(size * 1.35)} />;
  const Glyph = GLYPH[mark.glyph];
  return <Glyph aria-hidden strokeWidth={1.75} className="h-5 w-5 text-muted-foreground" />;
}

/**
 * What a click on a notice does, and how far a reconnect has come.
 *
 * `note` replaces the notice's second line while a sign-in runs (finish it in
 * the browser, the code to type there) or after it failed.
 */
function useNoticeGo(notice: RailNotice, onDone?: () => void): { go: () => void; busy: boolean; note: string | null } {
  const t = useT();
  const { phase, connectPlugin, start } = useSignIn(notice.subject, () => {
    useEventStore.getState().pushToast("success", fill(t("connect_card.connected"), { label: notice.subject }));
    return refreshPluginAttention();
  });
  const failure = phase.kind === "failed" ? phase.message : null;
  // A sign-in that failed says so where the person is looking, not only on hover.
  useEffect(() => {
    if (failure) useEventStore.getState().pushToast("error", failure);
  }, [failure]);

  const busy = phase.kind === "waiting";
  const note = phase.kind === "waiting"
    ? phase.code ? fill(t("plugin_reconnect.code"), { code: phase.code }) : t("plugin_reconnect.waiting")
    : failure;

  const go = () => {
    const { target } = notice;
    if (target.type === "reconnect") {
      if (!busy) start(() => connectPlugin(target.pluginId));
      // The sign-in goes on in the browser; the tile stays to show it.
      return;
    }
    if (target.type === "plugin") {
      requestPluginFocus(target.pluginId);
      useEventStore.getState().setActiveSection("plugins");
    } else if (target.type === "keys") {
      openKeys();
    } else if (target.row.link.workspace_id && target.row.link.pane) {
      openPaneSession({ workspace_id: target.row.link.workspace_id, name: target.row.link.pane });
    } else {
      goToStatusRow(target.row);
    }
    onDone?.();
  };
  return { go, busy, note };
}

/** The notice in words, in the bubble beside its tile. */
function NoticeWords({ notice, note }: { notice: RailNotice; note: string | null }) {
  const second = note ?? notice.detail;
  return (
    <span className="flex max-w-[264px] flex-col gap-0.5 whitespace-normal py-0.5" data-testid="rail-notice-words">
      <span className="font-medium text-foreground-strong">{notice.title}</span>
      {second && <span className="line-clamp-2 text-xs text-muted-foreground [overflow-wrap:anywhere]">{second}</span>}
      {!note && <span className="pt-1 text-xs font-medium text-accent">{notice.action}</span>}
    </span>
  );
}

function NoticeTile({ notice }: { notice: RailNotice }) {
  const { go, busy, note } = useNoticeGo(notice);
  return (
    <QuickTooltip side="right" className="flex" content={<NoticeWords notice={notice} note={note} />}>
      <button type="button" onClick={go} data-testid="rail-notice" data-ask={notice.ask} data-tone={notice.tone} data-key={notice.key}
        aria-busy={busy || undefined} aria-label={[notice.title, note ?? notice.detail, notice.action].filter(Boolean).join(" · ")}
        className={TILE}>
        <span className="flex h-full w-full items-center justify-center overflow-hidden rounded-full">
          <SubjectMark notice={notice} size={22} />
        </span>
        <AskBadge notice={notice} busy={busy} />
      </button>
    </QuickTooltip>
  );
}

/** One notice as a line of the full list: its mark, its sentence, and what it is about. */
function NoticeRow({ notice, onDone }: { notice: RailNotice; onDone: () => void }) {
  const { go, busy, note } = useNoticeGo(notice, onDone);
  const second = note ?? notice.detail;
  return (
    <button type="button" onClick={go} data-testid="rail-notice-row" data-ask={notice.ask} aria-busy={busy || undefined}
      className="group flex w-full min-w-0 items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <span className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-secondary ring-1 ring-inset ring-border group-hover:bg-muted">
        <span className="flex h-full w-full items-center justify-center overflow-hidden rounded-full">
          <SubjectMark notice={notice} size={18} />
        </span>
        <AskBadge notice={notice} busy={busy} small />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-foreground">{notice.title}</span>
        {second && <span className="block truncate text-xs text-muted-foreground">{second}</span>}
      </span>
      <ChevronRight aria-hidden strokeWidth={1.75}
        className="h-4 w-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
    </button>
  );
}

/**
 * Every notice as a list: opened from the count tile when there are more than
 * the rail shows. It stands beside the rail and closes on a click elsewhere,
 * on Escape, or once a row took the person somewhere.
 */
function NoticesPanel({ anchor, notices, onClose }: { anchor: HTMLElement; notices: RailNotice[]; onClose: () => void }) {
  const t = useT();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [place, setPlace] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    const rect = anchor.getBoundingClientRect();
    const height = panelRef.current?.getBoundingClientRect().height ?? 0;
    setPlace({ left: rect.right + 12, top: Math.max(8, Math.min(rect.top, window.innerHeight - height - 8)) });
  }, [anchor, notices.length]);

  useEffect(() => {
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (panelRef.current?.contains(target) || anchor.contains(target)) return;
      onClose();
    };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [anchor, onClose]);

  return createPortal(
    <div ref={panelRef} role="dialog" aria-label={t("rail_notice.title")} data-testid="rail-notices-panel"
      style={{ left: place?.left ?? 0, top: place?.top ?? 0, visibility: place ? "visible" : "hidden" }}
      className="fixed z-[60] max-h-[calc(100vh-16px)] w-80 overflow-y-auto rounded-xl border border-border-strong bg-popover p-2 shadow-float scrollbar-jarvis">
      <h3 className="m-0 px-2 pb-1 pt-0.5 text-xs font-medium text-muted-foreground">{t("rail_notice.title")}</h3>
      <ul className="m-0 flex list-none flex-col gap-px p-0">
        {notices.map((notice) => <li key={notice.key}><NoticeRow notice={notice} onDone={onClose} /></li>)}
      </ul>
    </div>,
    document.body,
  );
}

export default function RailNoticeTiles({ notices }: { notices: RailNotice[] }) {
  const t = useT();
  const moreRef = useRef<HTMLButtonElement | null>(null);
  const [open, setOpen] = useState(false);
  if (notices.length === 0) return null;

  // The count tile takes one of the places, so the rail never grows past its limit.
  const shown = notices.length > NOTICES_SHOWN ? notices.slice(0, NOTICES_SHOWN - 1) : notices;
  const more = notices.length - shown.length;
  const moreLabel = fill(t("rail_notice.more"), { count: more });
  return (
    <>
      {shown.map((notice) => <NoticeTile key={notice.key} notice={notice} />)}
      {more > 0 && (
        <QuickTooltip side="right" className="flex" content={moreLabel}>
          <button ref={moreRef} type="button" data-testid="rail-notices-more" aria-label={moreLabel} aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
            className={cn(TILE, "text-xs font-medium tabular-nums text-muted-foreground")}>
            +{more}
          </button>
        </QuickTooltip>
      )}
      {open && more > 0 && moreRef.current && <NoticesPanel anchor={moreRef.current} notices={notices} onClose={() => setOpen(false)} />}
    </>
  );
}
