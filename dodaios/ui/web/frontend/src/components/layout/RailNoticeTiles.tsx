import {
  useEffect, useLayoutEffect, useRef, useState,
  type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import {
  ArrowUpRight, BellOff, ChevronRight, Hand, Hourglass, KeyRound, Lightbulb, ListChecks, ListX, Loader2, Plus, RefreshCw, ShieldCheck,
  SquareTerminal, UserRound, X,
  type LucideIcon,
} from "lucide-react";

import { ToolChoiceIcon } from "@/components/agentchat/ToolChoiceChips";
import { serviceIconRow } from "@/components/agentchat/toolChoices";
import { toolIdentity } from "@/components/agentchat/toolIdentity";
import { AgentMark } from "@/components/agentic/AgentMark";
import { openPaneSession } from "@/components/agentic/openPaneSession";
import { ProviderLogo } from "@/components/providers/ProviderLogo";
import { AgentSwatch } from "@/components/society/AgentSwatch";
import { useSocietyRoster } from "@/components/society/data";
import { HoverCard, type HoverCardHandle } from "@/components/ui/hover-card";
import { QuickTooltip } from "@/components/ui/tooltip";
import { refreshPluginAttention } from "@/hooks/usePluginAttention";
import { useServiceConnect, type ServiceToConnect } from "@/hooks/useServiceConnect";
import { fill, useT } from "@/i18n";
import { submitAgentChatCredential } from "@/lib/agentChatApi";
import { requestPluginFocus } from "@/lib/customConnector";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

import {
  NOTICE_GAP_PX, NOTICE_TILE_PX, NOTICES_SHOWN, noticePlaces, type NoticeAsk,
 type NoticeGlyph, type RailNotice } from "./railNotices";
import { closeNotices, snoozeNotice } from "./railNoticeDismiss";
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
 * service reports connected. Reminders and calendar appointments are never
 * here: the assistant tells them in its chat (`ReminderDueMessage`).
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
};
/** A question and a warning read best as the character itself. */
const ASK_SIGN: Partial<Record<NoticeAsk, string>> = { question: "?", trouble: "!" };

/**
 * Signs for a subject with no logo, no face and no name. Plain, standard
 * symbols only: no robot heads, rockets or sparkles (the person, 2026-11-18).
 */
const GLYPH: Record<NoticeGlyph, LucideIcon> = {
  agent: UserRound, terminal: SquareTerminal, mission: ListChecks,
};

/** What is asked, on the tile's corner. `busy` turns it into a quiet spinner. */
function AskBadge({ notice, busy = false, small = false }: { notice: RailNotice; busy?: boolean; small?: boolean }) {
  const Icon = busy ? Loader2 : ASK_ICON[notice.ask];
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
        : <span className="text-[11px] font-bold leading-none">{ASK_SIGN[notice.ask] ?? "!"}</span>}
    </span>
  );
}

/** A name's first letter, set like the profile's initial: for a subject that has a name but no logo. */
function Monogram({ name, size }: { name: string; size: number }) {
  const letter = Array.from(name.trim())[0]?.toUpperCase() ?? "";
  if (!letter) return <UserRound aria-hidden strokeWidth={1.75} className="h-5 w-5 text-muted-foreground" />;
  return (
    <span aria-hidden data-testid="rail-notice-monogram" className="font-semibold leading-none text-foreground"
      style={{ fontSize: Math.round(size * 0.75) }}>
      {letter}
    </span>
  );
}

/** An agent's own face from the roster; its initial (or a plain person sign) when the roster has none. */
function AgentFace({ agentId, name, size }: { agentId: string; name: string; size: number }) {
  const roster = useSocietyRoster();
  const agent = roster.data?.agents.find((candidate) => candidate.agentId === agentId);
  if (!agent) return <Monogram name={name} size={size / 1.35} />;
  return <AgentSwatch agent={agent} size={size} />;
}

/** A service named only by its name: its own logo when the app knows one, else its initial. */
function ServiceMark({ name, size }: { name: string; size: number }) {
  const row = serviceIconRow("plugin", name, name);
  if (!toolIdentity(row).logo) return <Monogram name={name} size={size} />;
  return <ToolChoiceIcon row={row} size={size} />;
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
  if (mark.type === "service") return <ServiceMark name={mark.name} size={size} />;
  // An agent without a name of its own ("An agent") gets no initial: the person sign says it plainly.
  if (mark.type === "agent") return <AgentFace agentId={mark.id} name={mark.name ?? ""} size={Math.round(size * 1.35)} />;
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

/**
 * The notice in words, in the card beside its tile. Its last line is the
 * button that does what the tile's click does, for whoever reads the card
 * first and then goes for the word.
 */
function NoticeWords({ notice, note, go }: { notice: RailNotice; note: string | null; go: () => void }) {
  const second = note ?? notice.detail;
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

/** Where a notice's menu opens, and which notice it is for. */
interface NoticeMenuAt {
  notice: RailNotice;
  x: number;
  y: number;
  go: () => void;
  returnFocus: HTMLElement | null;
}

/** Opens a notice's menu (a right-click, Shift+F10 or the menu key on its tile or row). */
type OpenMenu = (at: NoticeMenuAt) => void;

const MENU_WIDTH = 220;
const MENU_MARGIN = 8;

function MenuItem({ icon, testId, onClick, children }: { icon: ReactNode; testId: string; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" role="menuitem" data-testid={testId} onClick={onClick}
      className={cn(
        "flex h-8 w-full items-center gap-2.5 rounded-md px-2.5 text-left text-sm text-foreground transition-colors",
        "hover:bg-secondary focus-visible:bg-secondary focus-visible:outline-none",
        "[&_svg]:h-4 [&_svg]:w-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground",
      )}>
      <span aria-hidden className="contents">{icon}</span>
      <span className="min-w-0 flex-1 truncate">{children}</span>
    </button>
  );
}

/**
 * What can be done to a notice besides its click: the menu a right-click on
 * its tile (or on its row in the full list) opens. Do what it asks, put it
 * off for an hour, close it, or close every notice at once. Arrow keys move
 * between the items; Escape, Tab or a click elsewhere leaves.
 */
function NoticeMenu({ at, all, onClose }: { at: NoticeMenuAt; all: RailNotice[]; onClose: () => void }) {
  const t = useT();
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    };
    const onPointer = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) onClose();
    };
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("pointerdown", onPointer, true);
    window.addEventListener("resize", onClose);
    window.addEventListener("blur", onClose);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("pointerdown", onPointer, true);
      window.removeEventListener("resize", onClose);
      window.removeEventListener("blur", onClose);
    };
  }, [onClose]);

  // Focus goes back to the tile when the menu leaves (if the tile is still there).
  const returnTo = useRef(at.returnFocus);
  useLayoutEffect(() => () => {
    const target = returnTo.current;
    if (target && target.isConnected) target.focus({ preventScroll: true });
  }, []);

  useLayoutEffect(() => {
    const node = menuRef.current;
    if (!node) return;
    const { width, height } = node.getBoundingClientRect();
    node.style.left = `${Math.max(MENU_MARGIN, Math.min(at.x, window.innerWidth - width - MENU_MARGIN))}px`;
    node.style.top = `${Math.max(MENU_MARGIN, Math.min(at.y, window.innerHeight - height - MENU_MARGIN))}px`;
    node.style.visibility = "visible";
    node.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true });
  }, [at.x, at.y]);

  const onMenuKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Tab") {
      event.preventDefault();
      onClose();
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>("button") ?? []);
    if (!items.length) return;
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
      : (index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items[next]?.focus();
  };

  const run = (action: () => void) => () => {
    onClose();
    action();
  };
  return createPortal(
    <div ref={menuRef} role="menu" aria-label={fill(t("rail_notice.menu_label"), { who: at.notice.subject })}
      data-testid="rail-notice-menu" onKeyDown={onMenuKey} onContextMenu={(event) => event.preventDefault()}
      style={{ width: MENU_WIDTH, visibility: "hidden" }}
      className="fixed z-[100] rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-float">
      <MenuItem icon={<ArrowUpRight />} testId="rail-notice-menu-go" onClick={run(at.go)}>{at.notice.action}</MenuItem>
      <div role="separator" className="mx-1 my-1 h-px bg-border" />
      <MenuItem icon={<BellOff />} testId="rail-notice-menu-snooze" onClick={run(() => snoozeNotice(at.notice))}>
        {t("rail_notice.menu_snooze")}
      </MenuItem>
      <MenuItem icon={<X />} testId="rail-notice-menu-close" onClick={run(() => closeNotices([at.notice]))}>
        {t("rail_notice.menu_close")}
      </MenuItem>
      {all.length > 1 && (
        <MenuItem icon={<ListX />} testId="rail-notice-menu-close-all" onClick={run(() => closeNotices(all))}>
          {fill(t("rail_notice.menu_close_all"), { count: all.length })}
        </MenuItem>
      )}
    </div>,
    document.body,
  );
}

function menuAt(event: ReactMouseEvent<HTMLElement>, notice: RailNotice, go: () => void): NoticeMenuAt {
  event.preventDefault();
  // Keep the app-wide edit menu (EditContextMenu) from opening on top.
  event.stopPropagation();
  const target = event.currentTarget;
  // A menu opened from the keyboard has no pointer position: it hangs beside the element.
  const rect = target.getBoundingClientRect();
  const keyboard = event.clientX === 0 && event.clientY === 0;
  return {
    notice, go, returnFocus: target,
    x: keyboard ? rect.right + 8 : event.clientX,
    y: keyboard ? rect.top : event.clientY,
  };
}

function NoticeTile({ notice, onMenu }: { notice: RailNotice; onMenu: OpenMenu }) {
  const cardRef = useRef<HoverCardHandle | null>(null);
  // A click that leads somewhere closes the card; a sign-in keeps it, to show how far it is.
  const close = () => cardRef.current?.close();
  const { go, busy, note } = useNoticeGo(notice, close);
  return (
    <HoverCard ref={cardRef} className="flex" label={notice.title}
      content={<NoticeWords notice={notice} note={note} go={go} />}>
      <button type="button" onClick={go} data-testid="rail-notice"
        onContextMenu={(event) => {
          // The menu stands where the card would; the card makes way for it.
          close();
          onMenu(menuAt(event, notice, go));
        }} data-ask={notice.ask} data-tone={notice.tone} data-key={notice.key}
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
function NoticeRow({ notice, onDone, onMenu }: { notice: RailNotice; onDone: () => void; onMenu: OpenMenu }) {
  const { go, busy, note } = useNoticeGo(notice, onDone);
  const second = note ?? notice.detail;
  return (
    <button type="button" onClick={go} data-testid="rail-notice-row"
      onContextMenu={(event) => onMenu(menuAt(event, notice, go))} data-ask={notice.ask} aria-busy={busy || undefined}
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
function NoticesPanel({ anchor, notices, onClose, onMenu }: {
  anchor: HTMLElement; notices: RailNotice[]; onClose: () => void; onMenu: OpenMenu;
}) {
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
      // A notice's own menu, opened from a row of this list, keeps the list open.
      if (target instanceof Element && target.closest("[data-testid='rail-notice-menu']")) return;
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
        {notices.map((notice) => <li key={notice.key}><NoticeRow notice={notice} onDone={onClose} onMenu={onMenu} /></li>)}
      </ul>
    </div>,
    document.body,
  );
}

/**
 * The height the rail has left for its tiles, followed as the window changes.
 * `null` until it could be measured; the rail then keeps `NOTICES_SHOWN` places.
 */
function useFreeHeight(box: HTMLElement | null): number | null {
  const [height, setHeight] = useState<number | null>(null);
  useLayoutEffect(() => {
    if (!box || typeof ResizeObserver === "undefined") return;
    const read = () => setHeight(box.getBoundingClientRect().height);
    read();
    const observer = new ResizeObserver(read);
    observer.observe(box);
    return () => observer.disconnect();
  }, [box]);
  return height;
}

export default function RailNoticeTiles({ notices }: { notices: RailNotice[] }) {
  const t = useT();
  const moreRef = useRef<HTMLButtonElement | null>(null);
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState<NoticeMenuAt | null>(null);
  const height = useFreeHeight(box);
  // The notice the menu is for was closed or went away by itself: so does its menu.
  const menuFor = menu && notices.some((notice) => notice.key === menu.notice.key) ? menu : null;
  if (notices.length === 0) return null;

  // Every notice gets a tile while they fit in the rail's free height; only
  // when they do not, the last place becomes the count tile.
  const unmeasured = NOTICES_SHOWN * NOTICE_TILE_PX + (NOTICES_SHOWN - 1) * NOTICE_GAP_PX;
  const { tiles } = noticePlaces(height ?? unmeasured, notices.length);
  const shown = notices.slice(0, tiles);
  const more = notices.length - shown.length;
  const moreLabel = fill(t("rail_notice.more"), { count: more });
  return (
    // Takes the rail's free height below the shortcuts; the tiles are counted
    // against it, so they never push the rail into a scroll.
    <div ref={setBox} data-testid="rail-notices-tiles" className="flex min-h-0 w-full flex-1 flex-col items-center gap-1.5">
      {shown.map((notice) => <NoticeTile key={notice.key} notice={notice} onMenu={setMenu} />)}
      {more > 0 && (
        <QuickTooltip side="right" className="flex" content={moreLabel}>
          <button ref={moreRef} type="button" data-testid="rail-notices-more" aria-label={moreLabel} aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
            className={cn(TILE, "text-xs font-medium tabular-nums text-muted-foreground")}>
            +{more}
          </button>
        </QuickTooltip>
      )}
      {open && more > 0 && moreRef.current && (
        <NoticesPanel anchor={moreRef.current} notices={notices} onClose={() => setOpen(false)} onMenu={setMenu} />
      )}
      {menuFor && <NoticeMenu at={menuFor} all={notices} onClose={() => setMenu(null)} />}
    </div>
  );
}
