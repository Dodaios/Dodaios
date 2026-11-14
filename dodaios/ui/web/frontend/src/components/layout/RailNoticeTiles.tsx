import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Bell, Bot, CalendarDays, ChevronRight, Clock, Hand, Hourglass, KeyRound, Lightbulb, Loader2, Plus, RefreshCw,
  Rocket, ShieldCheck, SquareTerminal, type LucideIcon,
} from "lucide-react";

import { ToolChoiceIcon } from "@/components/agentchat/ToolChoiceChips";
import { serviceIconRow } from "@/components/agentchat/toolChoices";
import { AgentMark } from "@/components/agentic/AgentMark";
import { JARVIS_LOGO_PATH } from "@/components/brand/dodaiosLogoPath";
import { openPaneSession } from "@/components/agentic/openPaneSession";
import { ProviderLogo } from "@/components/providers/ProviderLogo";
import { AgentSwatch } from "@/components/society/AgentSwatch";
import { useSocietyRoster } from "@/components/society/data";
import { HoverCard, type HoverCardHandle } from "@/components/ui/hover-card";
import { QuickTooltip } from "@/components/ui/tooltip";
import { refreshPluginAttention } from "@/hooks/usePluginAttention";
import { useServiceConnect, type ServiceToConnect } from "@/hooks/useServiceConnect";
import { fill, useT, useUiLanguage } from "@/i18n";
import { submitAgentChatCredential } from "@/lib/agentChatApi";
import { requestPluginFocus } from "@/lib/customConnector";
import { openExternalUrl } from "@/lib/openExternal";
import { bundledPluginLogo } from "@/lib/pluginLogos";
import { markReminderDone, snoozeReminder } from "@/lib/remindersApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

import { dropDueReminder, formatDue, refreshDueReminders } from "./dueReminders";
import { NOTICES_SHOWN, type NoticeAsk, type NoticeGlyph, type RailNotice } from "./railNotices";
import { itemPlace, itemTitle, itemWhen, OWN_SOURCE, type ReminderItem } from "./reminderItems";
import { refreshStatusLight } from "./statusLightStore";
import { goToStatusRow, openKeys } from "./statusRows";

/**
 * The rail's notices, drawn: one round tile per notice.
 *
 * A tile shows WHO it is about in its middle (the service's own logo, the
 * coding CLI's mark, the agent's face) and WHAT is asked as a small badge on
 * its corner (reconnect, a question, an approval, a warning). Hovering or
 * focusing it opens a card that says it in a sentence and holds the button
 * for it; a click on the tile does the same as that button. A connection that
 * ended, and a service an agent asks for, are connected right from the tile:
 * the click starts the service's own sign-in and the tile leaves once the
 * service reports connected. Reminders that have come due stand as one tile
 * per source, with that service's own logo (Google Calendar, Dodaios' mark
 * for the person's own); its card lists them and the tile leaves once each is
 * answered.
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
  // A plus reads at this size; a plug drawn in eleven pixels did not.
  connect: Plus,
  approval: ShieldCheck,
  credential: KeyRound,
  proposal: Lightbulb,
  takeover: Hand,
  waiting: Hourglass,
  due: Clock,
};
/** A question and a warning read best as the character itself. */
const ASK_SIGN: Partial<Record<NoticeAsk, string>> = { question: "?", trouble: "!" };

const GLYPH: Record<NoticeGlyph, LucideIcon> = {
  agent: Bot, terminal: SquareTerminal, mission: Rocket, reminder: Bell, appointment: CalendarDays,
};

/**
 * What is asked, on the tile's corner. `busy` turns it into a quiet spinner;
 * a source with several due reminders shows how many.
 */
function AskBadge({ notice, busy = false, small = false }: { notice: RailNotice; busy?: boolean; small?: boolean }) {
  const counted = !busy && notice.target.type === "reminders" && notice.count > 1;
  const Icon = busy ? Loader2 : counted ? undefined : ASK_ICON[notice.ask];
  return (
    <span aria-hidden data-testid="rail-notice-badge" data-ask={notice.ask}
      className={cn(
        "absolute flex items-center justify-center rounded-full ring-2",
        // Set out past the tile's edge, so it sits beside the logo instead of on it.
        small ? "-bottom-1 -right-1 h-4 w-4 ring-popover" : "-bottom-1 -right-1 h-[18px] w-[18px] ring-sidebar",
        BADGE_TONE[notice.tone],
      )}>
      {Icon
        // A stroke measured in pixels: scaled down with the glyph it would thin out to a hairline.
        ? <Icon absoluteStrokeWidth strokeWidth={1.75} className={cn(small ? "h-2.5 w-2.5" : "h-3 w-3", busy && "motion-safe:animate-spin")} />
        : counted
          ? <span className="text-[10px] font-semibold leading-none tabular-nums">{notice.count > 9 ? "9+" : notice.count}</span>
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

/**
 * Where due reminders come from: the service's own logo in its own colours,
 * Dodaios' mark (drawn in the text colour, like a coding CLI's mark) for the
 * person's own, else a plain calendar or bell.
 */
function SourceMark({ id, label, fallback, size }: { id: string; label: string; fallback: NoticeGlyph; size: number }) {
  if (id === OWN_SOURCE) {
    return (
      <svg aria-hidden viewBox="0 0 256 256" data-testid="rail-source-mark" data-source={id}
        style={{ width: size, height: size }} className="text-foreground-strong">
        <path d={JARVIS_LOGO_PATH} fillRule="evenodd" fill="currentColor" />
      </svg>
    );
  }
  if (bundledPluginLogo(id)) {
    return (
      <span data-testid="rail-source-mark" data-source={id} className="flex">
        <ToolChoiceIcon row={serviceIconRow("plugin", id, label)} size={size} />
      </span>
    );
  }
  const Glyph = GLYPH[fallback];
  return <Glyph aria-hidden data-testid="rail-source-mark" data-source={id} strokeWidth={1.75} className="h-5 w-5 text-muted-foreground" />;
}

/** Who the notice is about: a logo kept in its own colours, a face, or a plain sign. */
function SubjectMark({ notice, size }: { notice: RailNotice; size: number }) {
  const { mark, subject } = notice;
  if (mark.type === "source") return <SourceMark id={mark.id} label={subject} fallback={mark.fallback} size={size} />;
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

/** The service a click on this notice connects, or null when the click leads somewhere instead. */
function serviceOf(notice: RailNotice): ServiceToConnect | null {
  const { target } = notice;
  if (target.type === "reconnect") return { kind: "plugin", id: target.pluginId, label: notice.subject };
  if (target.type === "connect") return { kind: target.service, id: target.id, label: notice.subject };
  return null;
}

/**
 * What a click on a notice does, and how far a connect has come.
 *
 * A connection that ended, and a service an agent asks for, are connected
 * right from the notice: the click starts the service's own sign-in, and the
 * notice stays to show it. Once the service reports connected, an agent's
 * Connect card is told so (the agent goes on by itself). Every other notice
 * leads to its place.
 *
 * `note` replaces the notice's second line while a sign-in runs (finish it in
 * the browser, the code to type there) or after it failed.
 */
function useNoticeGo(notice: RailNotice, onDone?: () => void): { go: () => void; busy: boolean; note: string | null } {
  const t = useT();
  const service = serviceOf(notice);
  const { phase, connect } = useServiceConnect(service ?? { kind: "plugin", id: "", label: notice.subject }, async () => {
    const { target } = notice;
    if (target.type === "connect" && target.row.link.session_id && target.row.link.ref_id) {
      // The card's own chat hears it; the backend checks the connection again before the agent does.
      await submitAgentChatCredential(target.row.link.session_id, target.row.link.ref_id, "connected").catch(() => undefined);
    }
    useEventStore.getState().pushToast("success", fill(t("connect_card.connected"), { label: notice.subject }));
    await Promise.all([refreshPluginAttention(), refreshStatusLight()]);
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
    if (service) {
      // The sign-in goes on in the browser; the notice stays to show it.
      if (!busy) connect();
      return;
    }
    if (target.type === "plugin") {
      requestPluginFocus(target.pluginId);
      useEventStore.getState().setActiveSection("plugins");
    } else if (target.type === "keys") {
      openKeys();
    } else if (target.type === "row" && target.row.link.workspace_id && target.row.link.pane) {
      openPaneSession({ workspace_id: target.row.link.workspace_id, name: target.row.link.pane });
    } else if (target.type === "row") {
      goToStatusRow(target.row);
    }
    onDone?.();
  };
  return { go, busy, note };
}

/** The snooze choices a due reminder offers; "tomorrow" is resolved by the backend. */
const SNOOZES: readonly { key: string; minutes?: number; until?: string }[] = [
  { key: "reminders.snooze_15", minutes: 15 },
  { key: "reminders.snooze_1h", minutes: 60 },
  { key: "reminders.snooze_3h", minutes: 180 },
  { key: "reminders.snooze_tomorrow", until: "tomorrow" },
];

/** A word that does something, as the other notices' cards end in one. */
const ACTION =
  "-mx-1 rounded px-1 py-0.5 font-medium text-accent hover:underline disabled:opacity-60 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
/** The quieter second word beside it. */
const QUIET_ACTION =
  "-mx-1 rounded px-1 py-0.5 text-muted-foreground hover:text-foreground disabled:opacity-60 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/**
 * One due item: its own title, when it runs in words, and only what fits it.
 *
 * An appointment opens in its calendar or is dismissed; it is never snoozed,
 * because a meeting that already started does not come back later. A reminder
 * is ticked off, or snoozed once "Later" shows the choices. Either takes the
 * item off the rail at once (with the same item seen on a second calendar); a
 * snooze says in a toast when it comes back, a failure says it went wrong and
 * leaves the item where it was.
 */
function ReminderEntry({ item, service }: { item: ReminderItem; service: string }) {
  const t = useT();
  const locale = useUiLanguage();
  const [busy, setBusy] = useState(false);
  const [later, setLater] = useState(false);
  const { row, ids, appointment } = item;
  const when = itemWhen(row, locale, t);
  const place = itemPlace(row);

  const settle = (work: Promise<string | null>) => {
    setBusy(true);
    void work.then(
      (message) => {
        for (const id of ids) dropDueReminder(id);
        if (message) useEventStore.getState().pushToast("success", message);
        void refreshDueReminders();
      },
      () => {
        setBusy(false);
        useEventStore.getState().pushToast("error", t("reminders.failed"));
      },
    );
  };
  const done = () => settle(Promise.all(ids.map((id) => markReminderDone(id))).then(() => null));
  const snooze = (choice: (typeof SNOOZES)[number]) => settle(
    Promise.all([
      snoozeReminder(row.id, choice.until ? { until: choice.until } : { minutes: choice.minutes }),
      ...ids.filter((id) => id !== row.id).map((id) => markReminderDone(id)),
    ]).then(([moved]) => fill(t("reminders.snoozed_until"), { when: formatDue(moved.due_at, locale) })),
  );

  return (
    <span className="flex flex-col gap-0.5" data-testid="rail-reminder" data-kind={appointment ? "appointment" : "reminder"}>
      <span className="font-medium text-foreground-strong [overflow-wrap:anywhere]" data-testid="rail-reminder-title"
        title={row.busy_only ? t("reminders.busy_hint") : undefined}>
        {itemTitle(row, t)}
      </span>
      {when && <span className="text-xs text-muted-foreground" data-testid="rail-reminder-when">{when}</span>}
      {place && <span className="truncate text-xs text-muted-foreground" title={place} data-testid="rail-reminder-place">{place}</span>}
      <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs" data-testid="rail-reminder-actions">
        {appointment ? (
          <>
            {row.url && (
              <button type="button" onClick={() => void openExternalUrl(row.url ?? "")} data-testid="rail-reminder-open" className={ACTION}>
                {fill(t("reminders.open_in"), { service })}
              </button>
            )}
            <button type="button" onClick={done} disabled={busy} data-testid="rail-reminder-dismiss"
              className={row.url ? QUIET_ACTION : ACTION}>
              {t("reminders.dismiss")}
            </button>
          </>
        ) : (
          <>
            <button type="button" onClick={done} disabled={busy} data-testid="rail-reminder-done" className={ACTION}>
              {t("reminders.done")}
            </button>
            <button type="button" onClick={() => setLater((open) => !open)} disabled={busy} aria-expanded={later}
              data-testid="rail-reminder-later" className={QUIET_ACTION}>
              {t("reminders.snooze")}
            </button>
          </>
        )}
      </span>
      {later && (
        <span role="group" aria-label={t("reminders.snooze_label")} className="mt-1.5 flex flex-col gap-1 text-xs">
          <span className="text-muted-foreground">{t("reminders.snooze_label")}</span>
          <span className="flex flex-wrap gap-1">
            {SNOOZES.map((choice) => (
              <button key={choice.key} type="button" onClick={() => snooze(choice)} disabled={busy} data-testid="rail-reminder-snooze"
                className="rounded-md px-1.5 py-0.5 text-foreground ring-1 ring-inset ring-border hover:bg-secondary disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {t(choice.key)}
              </button>
            ))}
          </span>
        </span>
      )}
    </span>
  );
}

/** The due items of one source, one under the other. */
function ReminderList({ items, service }: { items: ReminderItem[]; service: string }) {
  return (
    <ul className="m-0 flex max-h-[min(60vh,420px)] list-none flex-col gap-2 overflow-y-auto p-0 scrollbar-jarvis">
      {items.map((item, index) => (
        <li key={item.key} className={cn(index > 0 && "border-t border-border pt-2")}>
          <ReminderEntry item={item} service={service} />
        </li>
      ))}
    </ul>
  );
}

/**
 * The notice in words, in the card beside its tile. Its last line is the
 * button that does what the tile's click does, for whoever reads the card
 * first and then goes for the word.
 */
function NoticeWords({ notice, note, go }: { notice: RailNotice; note: string | null; go: () => void }) {
  const second = note ?? notice.detail;
  if (notice.target.type === "reminders") {
    // The source names itself first ("Google Calendar"); each item says what it is called and when.
    return (
      <span className="flex w-[288px] max-w-full flex-col gap-1.5 whitespace-normal py-0.5" data-testid="rail-notice-words">
        <span className="text-xs text-muted-foreground" data-testid="rail-reminder-source">{notice.subject}</span>
        <ReminderList items={notice.target.items} service={notice.subject} />
      </span>
    );
  }
  return (
    <span className="flex max-w-[264px] flex-col gap-0.5 whitespace-normal py-0.5" data-testid="rail-notice-words">
      <span className="font-medium text-foreground-strong">{notice.title}</span>
      {second && <span className="line-clamp-2 text-xs text-muted-foreground [overflow-wrap:anywhere]">{second}</span>}
      {!note && (
        <button type="button" onClick={go} data-testid="rail-notice-action"
          className="-mx-1 mt-0.5 self-start rounded px-1 py-0.5 text-xs font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {notice.action}
        </button>
      )}
    </span>
  );
}

function NoticeTile({ notice }: { notice: RailNotice }) {
  const cardRef = useRef<HoverCardHandle | null>(null);
  // A click that leads somewhere closes the card; a sign-in keeps it, to show how far it is.
  const close = () => cardRef.current?.close();
  const { go, busy, note } = useNoticeGo(notice, close);
  // A reminder is answered in its card: a click on the tile opens it, it never ticks the reminder off.
  const click = notice.target.type === "reminders" ? () => cardRef.current?.open() : go;
  return (
    <HoverCard ref={cardRef} className="flex" label={notice.title}
      content={<NoticeWords notice={notice} note={note} go={go} />}>
      <button type="button" onClick={click} data-testid="rail-notice" data-ask={notice.ask} data-tone={notice.tone} data-key={notice.key}
        aria-busy={busy || undefined} aria-label={[notice.title, note ?? notice.detail, notice.action].filter(Boolean).join(" · ")}
        className={TILE}>
        <span className="flex h-full w-full items-center justify-center overflow-hidden rounded-full">
          <SubjectMark notice={notice} size={22} />
        </span>
        <AskBadge notice={notice} busy={busy} />
      </button>
    </HoverCard>
  );
}

/** One notice as a line of the full list: its mark, its sentence, and what it is about. */
function NoticeRow({ notice, onDone }: { notice: RailNotice; onDone: () => void }) {
  const { go, busy, note } = useNoticeGo(notice, onDone);
  const second = note ?? notice.detail;
  if (notice.target.type === "reminders") {
    // Its buttons are the items' own: each says what fits it, under its text.
    return (
      <div data-testid="rail-notice-row" data-ask={notice.ask} className="flex w-full min-w-0 items-start gap-3 rounded-lg px-2 py-2">
        <span className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-secondary ring-1 ring-inset ring-border">
          <span className="flex h-full w-full items-center justify-center overflow-hidden rounded-full">
            <SubjectMark notice={notice} size={18} />
          </span>
          <AskBadge notice={notice} small />
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-1 text-sm">
          <span className="text-xs text-muted-foreground">{notice.subject}</span>
          <ReminderList items={notice.target.items} service={notice.subject} />
        </span>
      </div>
    );
  }
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
