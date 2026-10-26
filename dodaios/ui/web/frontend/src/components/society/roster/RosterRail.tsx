/**
 * The roster: the Agents section's navigation. One dense row per agent, each
 * with a corner status mark and a single preview line, plus the groups that
 * keep a long list calm:
 *
 *   - pinned agents as a four-up grid of faces at the top,
 *   - "Needs you" for every agent that waits on the person (it beats unread),
 *   - teams, with a visible "New team" action,
 *   - everyone else, in the person's own drag order.
 *
 * A search box and a filter (all / needs you / unread) narrow the list. The
 * roster can fold to an avatar rail; the frame decides when it must.
 *
 * Reordering is press-and-drag: pressing anywhere on a row and moving it
 * files the agent before or after the row under the pointer. A small
 * movement threshold keeps plain clicks (open chat / profile) working.
 * Holding over another row for a moment makes a team; Alt + Shift + Arrow
 * keys are the keyboard twin of the drag.
 *
 * With `keyboard` on, Alt + Arrow Up / Down steps between agents from
 * anywhere in the section, and Ctrl (Cmd) + 1–9 jumps to the pinned agents,
 * then the rest in list order. Holding the modifier shows the numbers.
 */
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { Eye, PanelLeftClose, PanelLeftOpen, Plus, Search, UsersRound, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useT, useUiLanguage } from "@/i18n";
import { societyDisplayName } from "@/lib/societyDisplayName";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import type { SocietyChatGroup } from "@/lib/societyChatGroups";

import { AgentSwatch } from "../AgentSwatch";
import { agentTint } from "../agentTint";
import type { SocietyAgent } from "../data";
import "../agentSection.css";
import { AgentRosterActions } from "./AgentRosterActions";
import { GroupRosterActions } from "./GroupRosterActions";
import { useRosterUnreadState } from "./useRosterUnread";
import { ChatGroupDialog } from "../chat/ChatGroupDialog";
import { RosterRow, StatusMark } from "./RosterRow";
import { RosterSection } from "./RosterSection";
import { RosterHoverCard, type HoverCardData } from "./RosterHoverCard";
import { formatRelative, needsYou, rosterPreview, rosterStatus, waitingReasonOf } from "./rosterPreview";
import { HIDDEN_AGENTS_KEY, MAX_PINNED, ORDER_KEY, PINNED_KEY, togglePin, usePersistedIds, useRosterFilter, writeIdList, type RosterFilter } from "./rosterPrefs";
import type { RosterActivityMap } from "./useRosterActivity";

/** How far the pointer must travel before a press becomes a drag. */
const PRESS_DRAG_THRESHOLD_PX = 6;
/** A deliberate pause over another row creates a team; a quick drop reorders. */
const GROUP_HOLD_MS = 750;
/** How long the pointer rests on a row before its hover card shows. */
const HOVER_CARD_MS = 550;
/** How long the jump modifier is held before the numbers show. */
const SHORTCUT_HINT_MS = 450;
type GroupDropTarget = { kind: "agent" | "group"; id: string };

const AgentProfileDialog = lazy(() => import("../card/AgentProfileDialog").then((module) => ({ default: module.AgentProfileDialog })));

const NO_ACTIVITY: RosterActivityMap = new Map();

function isMacPlatform(): boolean {
  return typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
}

function isEditable(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));
}

/** A modal over the section owns the keyboard. */
function modalOpen(): boolean {
  return Boolean(document.querySelector('[role="dialog"][aria-modal="true"], [role="alertdialog"]'));
}

function hoverCapable(): boolean {
  try {
    return typeof window.matchMedia !== "function" || window.matchMedia("(hover: hover)").matches;
  } catch {
    return true;
  }
}

export interface RosterRailProps {
  agents: SocietyAgent[];
  groups?: SocietyChatGroup[];
  activeGroupId?: string | null;
  onOpenGroup?: (groupId: string) => void;
  onGroupAgents?: (sourceId: string, targetId: string) => void;
  onAddAgentToGroup?: (agentId: string, groupId: string) => void;
  loading: boolean;
  /** True until the teams have answered: who stands alone in the list is not known before. */
  teamsPending?: boolean;
  /** True while rows come from the sample roster rather than society.db. */
  sample: boolean;
  activeAgentId: string | null;
  onOpen: (agentId: string) => void;
  onCreate: () => void;
  /** Which edge the rail sits on; decides which side carries the divider. */
  side?: "left" | "right";
  /** Replaces the fixed width when the rail is a grid cell rather than a flex sibling. */
  className?: string;
  /** Sits above the title — the way back to the rest of the app. */
  header?: ReactNode;
  /** Team actions stay visible below the scrolling roster. */
  footer?: ReactNode;
  /** Last message, time and draft per agent (from the chat stores). */
  activity?: RosterActivityMap;
  /** Show the avatar rail instead of rows. */
  collapsed?: boolean;
  /** Offers the fold control in the header (and the unfold one on the rail). */
  onToggleCollapsed?: () => void;
  /** Section-wide shortcuts: Alt + Arrow between agents, Ctrl/Cmd + 1–9 to jump. */
  keyboard?: boolean;
}

export function RosterRail({
  agents,
  groups = [],
  activeGroupId = null,
  onOpenGroup,
  onGroupAgents,
  onAddAgentToGroup,
  loading,
  teamsPending = false,
  sample,
  activeAgentId,
  onOpen,
  onCreate,
  side = "right",
  className,
  header,
  footer,
  activity = NO_ACTIVITY,
  collapsed = false,
  onToggleCollapsed,
  keyboard = false,
}: RosterRailProps) {
  const t = useT();
  const language = useUiLanguage();
  const [query, setQuery] = useState("");
  const [chosenFilter, setFilter] = useRosterFilter();
  const [creatingGroup, setCreatingGroup] = useState(false);
  const [profileId, setProfileId] = useState<string | null>(null);
  const [hiddenIds, setHiddenIds] = usePersistedIds(HIDDEN_AGENTS_KEY);
  const [orderIds, setOrderIds] = useState(() => {
    try {
      const value: unknown = JSON.parse(localStorage.getItem(ORDER_KEY) ?? "[]");
      return Array.isArray(value) ? value.filter((id): id is string => typeof id === "string") : [];
    } catch {
      return [];
    }
  });
  const [pinIds, setPinIds] = usePersistedIds(PINNED_KEY);
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropId, setDropId] = useState<string | null>(null);
  const [dropAfter, setDropAfter] = useState(false);
  const [groupHover, setGroupHover] = useState<GroupDropTarget | null>(null);
  const [groupReady, setGroupReady] = useState(false);
  const [showHidden, setShowHidden] = useState(false);
  const [menu, setMenu] = useState<{ agentId: string; x: number; y: number } | null>(null);
  const [groupMenu, setGroupMenu] = useState<{ groupId: string; x: number; y: number } | null>(null);
  const [editingGroupId, setEditingGroupId] = useState<string | null>(null);
  const [hover, setHover] = useState<{ agentId: string; anchor: DOMRect } | null>(null);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const profile = agents.find((agent) => agent.agentId === profileId);
  const menuAgent = agents.find((agent) => agent.agentId === menu?.agentId);
  const menuGroup = groups.find((group) => group.group_id === groupMenu?.groupId);
  const editingGroup = groups.find((group) => group.group_id === editingGroupId);
  const { unread, mark: markUnread } = useRosterUnreadState(agents, activeAgentId);
  const assistantName = useEventStore((state) => state.assistantName);
  const display = useCallback((agent: SocietyAgent) => societyDisplayName(agent, assistantName), [assistantName]);

  // Relative times age while the roster stays open.
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  const setHidden = useCallback((agentId: string, hidden: boolean) => {
    setHiddenIds((current) => (hidden ? [...new Set([...current, agentId])] : current.filter((id) => id !== agentId)));
  }, [setHiddenIds]);
  // A pin left behind by a retired agent must not hold one of the places.
  const livePinCount = pinIds.filter((id) => agents.some((agent) => agent.agentId === id)).length;
  const onTogglePin = useCallback((agentId: string) => setPinIds((current) => {
    const known = loading || agents.length === 0
      ? current
      : current.filter((id) => agents.some((agent) => agent.agentId === id));
    return togglePin(known, agentId);
  }), [agents, loading, setPinIds]);
  const closeMenu = useCallback(() => setMenu(null), []);
  const openMenu = (event: MouseEvent, agentId: string) => {
    event.preventDefault();
    event.stopPropagation();
    setGroupMenu(null);
    setHover(null);
    setMenu({ agentId, x: event.clientX, y: event.clientY });
  };
  const openGroupMenu = (event: MouseEvent, groupId: string) => {
    event.preventDefault();
    event.stopPropagation();
    setMenu(null);
    setGroupMenu({ groupId, x: event.clientX, y: event.clientY });
  };

  const lead = useMemo(() => agents.find((a) => a.tier === "lead") ?? null, [agents]);
  const groupedIds = useMemo(() => new Set(groups.flatMap((group) => group.members)), [groups]);
  // A group may hold the lead, who wears the assistant's chosen name everywhere.
  const memberName = (id: string) => {
    const agent = agents.find((row) => row.agentId === id);
    return agent ? display(agent) : id;
  };
  // The folded rail has no search box or filter on screen, so it lists
  // everyone; the person's choice comes back with the rows.
  const filter: RosterFilter = collapsed ? "all" : chosenFilter;
  const q = collapsed ? "" : query.trim().toLowerCase();
  const browsing = q === "" && filter === "all";
  const visibleGroups = filter === "all"
    ? groups.filter((group) => `${group.name} ${group.members.map(memberName).join(" ")}`.toLowerCase().includes(q))
    : [];

  const { pinned, attention, leadRow, rows } = useMemo(() => {
    const isHidden = (a: SocietyAgent) => !showHidden && hiddenIds.includes(a.agentId);
    const matches = (a: SocietyAgent) => !q || `${a.name} ${display(a)} ${a.title}`.toLowerCase().includes(q);
    const passes = (a: SocietyAgent) => filter === "all" || (filter === "needs-you" ? needsYou(a) : unread.has(a.agentId));
    const shown = (a: SocietyAgent) => !isHidden(a) && matches(a) && passes(a);
    // Pins are an arrangement of the whole list; while a search or filter
    // narrows it, they fold back into the excerpt.
    const pinnedRows = browsing
      ? pinIds.map((id) => agents.find((a) => a.agentId === id)).filter((a): a is SocietyAgent => Boolean(a) && !isHidden(a!))
      : [];
    const pinnedSet = new Set(pinnedRows.map((a) => a.agentId));
    // Team members wait on the person too; they surface here even though
    // their team keeps them out of the plain list.
    const waiting = agents.filter((a) => shown(a) && needsYou(a) && !pinnedSet.has(a.agentId));
    const waitingSet = new Set(waiting.map((a) => a.agentId));
    const leadShown = lead && shown(lead) && !pinnedSet.has(lead.agentId) && !waitingSet.has(lead.agentId) ? lead : null;
    // Until the teams have answered, a member would be listed on its own and
    // jump into its team a moment later; the list waits for the answer instead.
    const rest = teamsPending ? [] : agents.filter((a) => a.agentId !== lead?.agentId && !groupedIds.has(a.agentId)
      && shown(a) && !pinnedSet.has(a.agentId) && !waitingSet.has(a.agentId));
    // Orchestrators, then specialists; stable within a tier. A drag persists
    // the full visible order, so from then on the person's own arrangement
    // wins over the tier grouping. Agents the list never saw settle at the
    // end in tier order until the next drag files them in.
    const rank = { lead: 0, orchestrator: 1, specialist: 2 } as const;
    const position = new Map(orderIds.map((id, index) => [id, index] as const));
    const custom = rest.some((a) => position.has(a.agentId));
    rest.sort((a, b) => {
      if (custom) {
        const ai = position.get(a.agentId);
        const bi = position.get(b.agentId);
        if (ai !== undefined && bi !== undefined) return ai - bi;
        if (ai !== undefined) return -1;
        if (bi !== undefined) return 1;
      }
      return rank[a.tier] - rank[b.tier];
    });
    return { pinned: pinnedRows, attention: waiting, leadRow: leadShown, rows: rest };
  }, [agents, browsing, display, filter, groupedIds, hiddenIds, lead, orderIds, pinIds, q, showHidden, teamsPending, unread]);

  // While searching or filtering, the list is an excerpt — dragging there
  // would file agents by where they happen to sit in it, so rows stay put.
  const reorderable = browsing;

  /** Every agent in the order the person sees them: the keyboard walks this. */
  const navOrder = useMemo(
    () => [...pinned, ...attention, ...(leadRow ? [leadRow] : []), ...rows].map((a) => a.agentId),
    [attention, leadRow, pinned, rows],
  );
  const shortcutIds = navOrder.slice(0, 9);
  const shortcutOf = (agentId: string) => {
    if (!showShortcuts) return null;
    const index = shortcutIds.indexOf(agentId);
    return index === -1 ? null : index + 1;
  };

  /**
   * File `fromId` directly before `toId`, or directly after it when `after`
   * is set. Unlike the native-drop path this can also land behind the last
   * row, which is what moving an agent down needs.
   */
  const moveToPosition = useCallback((fromId: string, toId: string, after: boolean) => {
    if (fromId === toId) return;
    setOrderIds((current) => {
      const base = rows.map((a) => a.agentId);
      const known = new Set(base);
      for (const id of current) if (!known.has(id)) base.push(id);
      const without = base.filter((id) => id !== fromId);
      const at = without.indexOf(toId);
      const insert = at === -1 ? without.length : after ? at + 1 : at;
      const next = [...without.slice(0, insert), fromId, ...without.slice(insert)];
      writeIdList(ORDER_KEY, next);
      return next;
    });
  }, [rows]);

  /** Keyboard twin of the drag: Alt + Shift + Arrow Up / Down steps the row. */
  const moveStep = useCallback((agentId: string, delta: -1 | 1) => {
    setOrderIds((current) => {
      const base = rows.map((a) => a.agentId);
      const known = new Set(base);
      for (const id of current) if (!known.has(id)) base.push(id);
      const at = base.indexOf(agentId);
      const swap = at + delta;
      if (at === -1 || swap < 0 || swap >= base.length) return current;
      const next = [...base];
      [next[at], next[swap]] = [next[swap], next[at]];
      writeIdList(ORDER_KEY, next);
      return next;
    });
  }, [rows]);

  const onRowKeyDown = (event: KeyboardEvent, agentId: string) => {
    if (!reorderable || !event.altKey || !event.shiftKey) return;
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      moveStep(agentId, event.key === "ArrowUp" ? -1 : 1);
    }
  };

  // --- Section-wide keyboard ----------------------------------------------
  const navRef = useRef(navOrder);
  const activeRef = useRef(activeAgentId);
  const onOpenRef = useRef(onOpen);
  navRef.current = navOrder;
  activeRef.current = activeAgentId;
  onOpenRef.current = onOpen;
  useEffect(() => {
    if (!keyboard) return;
    const mac = isMacPlatform();
    let hintTimer: number | null = null;
    const clearHint = () => {
      if (hintTimer !== null) window.clearTimeout(hintTimer);
      hintTimer = null;
      setShowShortcuts(false);
    };
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.defaultPrevented || modalOpen()) return;
      if ((event.key === "Control" || event.key === "Meta") && !event.repeat) {
        if (hintTimer === null) hintTimer = window.setTimeout(() => setShowShortcuts(true), SHORTCUT_HINT_MS);
        return;
      }
      const order = navRef.current;
      if (event.altKey && !event.shiftKey && !event.ctrlKey && !event.metaKey
        && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
        // On a Mac, Option + Arrow moves the caret inside text; leave it there.
        if (mac && isEditable(event.target)) return;
        if (order.length === 0) return;
        const at = order.indexOf(activeRef.current ?? "");
        const step = event.key === "ArrowDown" ? 1 : -1;
        const next = at === -1 ? (step === 1 ? 0 : order.length - 1) : (at + step + order.length) % order.length;
        event.preventDefault();
        if (order[next] !== activeRef.current) onOpenRef.current(order[next]);
        return;
      }
      const jump = mac ? event.metaKey && !event.ctrlKey : event.ctrlKey && !event.metaKey;
      if (!jump || event.altKey || event.shiftKey) return;
      const match = /^(?:Digit|Numpad)([1-9])$/.exec(event.code) ?? /^([1-9])$/.exec(event.key);
      if (!match) return;
      const id = order[Number(match[1]) - 1];
      if (!id) return;
      event.preventDefault();
      clearHint();
      if (id !== activeRef.current) onOpenRef.current(id);
    };
    const onKeyUp = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Control" || event.key === "Meta") clearHint();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", clearHint);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", clearHint);
      if (hintTimer !== null) window.clearTimeout(hintTimer);
    };
  }, [keyboard]);

  // --- Press-and-drag: the whole row is the handle. -----------------------
  // One pointer gesture owns both actions. Native HTML drag competes with
  // pointermove in WebView and can cancel the gesture before release.
  // A quick drop reorders; holding over a row or group makes a team.
  const listRef = useRef<HTMLUListElement | null>(null);
  const railRef = useRef<HTMLElement | null>(null);
  const pendingRef = useRef<{ id: string; startX: number; startY: number; pointerId: number } | null>(null);
  const pointerDragRef = useRef(false);
  const suppressClickRef = useRef(false);
  const dragIdRef = useRef<string | null>(null);
  const dropIdRef = useRef<string | null>(null);
  const dropAfterRef = useRef(false);
  const groupHoverRef = useRef<GroupDropTarget | null>(null);
  const groupReadyRef = useRef(false);
  const holdTimerRef = useRef<number | null>(null);
  const reorderableRef = useRef(reorderable);
  const moveToRef = useRef(moveToPosition);
  const groupAgentsRef = useRef(onGroupAgents);
  const addToGroupRef = useRef(onAddAgentToGroup);
  dragIdRef.current = dragId;
  dropIdRef.current = dropId;
  dropAfterRef.current = dropAfter;
  reorderableRef.current = reorderable;
  moveToRef.current = moveToPosition;
  groupAgentsRef.current = onGroupAgents;
  addToGroupRef.current = onAddAgentToGroup;

  useEffect(() => {
    const rowElements = () => {
      const list = listRef.current;
      if (!list) return [] as HTMLElement[];
      return [...list.querySelectorAll("[data-agent-id]")] as HTMLElement[];
    };
    const hit = (element: HTMLElement, x: number, y: number) => {
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && x >= rect.left && x <= rect.right
        && y >= rect.top && y <= rect.bottom;
    };
    const groupTargetAt = (x: number, y: number, sourceId: string): GroupDropTarget | null => {
      if (groupAgentsRef.current) {
        const agent = rowElements().find((element) =>
          element.dataset.agentId !== sourceId && hit(element, x, y));
        if (agent?.dataset.agentId) return { kind: "agent", id: agent.dataset.agentId };
      }
      if (addToGroupRef.current) {
        const group = [...(railRef.current?.querySelectorAll("[data-group-id]") ?? [])]
          .find((element) => hit(element as HTMLElement, x, y)) as HTMLElement | undefined;
        if (group?.dataset.groupId) return { kind: "group", id: group.dataset.groupId };
      }
      return null;
    };
    const clearHold = () => {
      if (holdTimerRef.current !== null) window.clearTimeout(holdTimerRef.current);
      holdTimerRef.current = null;
      groupHoverRef.current = null;
      groupReadyRef.current = false;
      setGroupHover(null);
      setGroupReady(false);
    };
    const updateHold = (target: GroupDropTarget | null) => {
      const previous = groupHoverRef.current;
      if (previous?.kind === target?.kind && previous?.id === target?.id) return;
      clearHold();
      if (!target) return;
      groupHoverRef.current = target;
      setGroupHover(target);
      holdTimerRef.current = window.setTimeout(() => {
        groupReadyRef.current = true;
        setGroupReady(true);
      }, GROUP_HOLD_MS);
    };
    const onMove = (event: PointerEvent) => {
      if (!reorderableRef.current) return;
      let sourceId = pointerDragRef.current ? dragIdRef.current : null;
      if (!sourceId) {
        const pending = pendingRef.current;
        if (!pending) return;
        if (event.pointerId !== pending.pointerId) return;
        const moved = Math.max(Math.abs(event.clientX - pending.startX), Math.abs(event.clientY - pending.startY));
        if (moved < PRESS_DRAG_THRESHOLD_PX) return;
        pointerDragRef.current = true;
        sourceId = pending.id;
        setDragId(pending.id);
        setDropId(null);
        setDropAfter(false);
        setHover(null);
      }
      if (!sourceId) return;
      const elements = rowElements();
      const sourceEl = elements.find((el) => el.getAttribute("data-agent-id") === sourceId);
      if (sourceEl) {
        const rect = sourceEl.getBoundingClientRect();
        if (rect.height > 0 && event.clientY >= rect.top && event.clientY <= rect.bottom) {
          updateHold(null);
          if (dropIdRef.current !== null) {
            setDropId(null);
            setDropAfter(false);
          }
          return;
        }
      }
      const groupTarget = groupTargetAt(event.clientX, event.clientY, sourceId);
      updateHold(groupTarget);
      if (groupTarget?.kind === "group") {
        if (dropIdRef.current !== null) setDropId(null);
        if (event.cancelable) event.preventDefault();
        return;
      }
      let target: { id: string; after: boolean } | null = null;
      for (const el of elements) {
        const id = el.getAttribute("data-agent-id");
        if (!id || id === sourceId) continue;
        const rect = el.getBoundingClientRect();
        if (rect.height === 0) continue;
        if (event.clientY < rect.top + rect.height / 2) {
          target = { id, after: false };
          break;
        }
      }
      if (!target) {
        const others = elements.filter((el) => el.getAttribute("data-agent-id") !== sourceId);
        const last = others[others.length - 1];
        const lastId = last?.getAttribute("data-agent-id");
        if (lastId) target = { id: lastId, after: true };
      }
      if (target) {
        if (dropIdRef.current !== target.id || dropAfterRef.current !== target.after) {
          setDropId(target.id);
          setDropAfter(target.after);
        }
      } else if (dropIdRef.current !== null) {
        setDropId(null);
        setDropAfter(false);
      }
      if (event.cancelable) event.preventDefault();
    };
    const finish = (commit: boolean, event?: PointerEvent) => {
      if (pointerDragRef.current && dragIdRef.current) {
        const from = dragIdRef.current;
        const toId = dropIdRef.current;
        const after = dropAfterRef.current;
        const held = groupReadyRef.current ? groupHoverRef.current : null;
        const releasedOn = event ? groupTargetAt(event.clientX, event.clientY, from) : null;
        pendingRef.current = null;
        pointerDragRef.current = false;
        setDragId(null);
        setDropId(null);
        setDropAfter(false);
        clearHold();
        if (commit && held && releasedOn?.kind === held.kind && releasedOn.id === held.id) {
          if (held.kind === "agent") groupAgentsRef.current?.(from, held.id);
          else addToGroupRef.current?.(from, held.id);
        } else if (commit && releasedOn?.kind !== "group" && toId && toId !== from) {
          moveToRef.current(from, toId, after);
        }
        suppressClickRef.current = true;
        window.setTimeout(() => {
          suppressClickRef.current = false;
        }, 0);
      } else {
        pendingRef.current = null;
        clearHold();
      }
    };
    const onUp = (event: PointerEvent) => finish(true, event);
    const onCancel = () => finish(false);
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") finish(false);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("keydown", onKey);
      if (holdTimerRef.current !== null) window.clearTimeout(holdTimerRef.current);
    };
  }, []);

  const onRowPointerDown = (event: ReactPointerEvent, agentId: string) => {
    if (!reorderable) return;
    if (event.pointerType === "touch") return;
    if (event.button !== undefined && event.button !== 0) return;
    pendingRef.current = { id: agentId, startX: event.clientX, startY: event.clientY, pointerId: event.pointerId };
  };

  const onRowClickCapture = (event: MouseEvent) => {
    if (suppressClickRef.current) {
      event.preventDefault();
      event.stopPropagation();
    }
  };

  const openAgent = (agentId: string) => {
    if (suppressClickRef.current) return;
    setHover(null);
    onOpen(agentId);
  };

  const openProfile = (agentId: string) => {
    if (suppressClickRef.current) return;
    setHover(null);
    setProfileId(agentId);
  };

  // --- Hover card ----------------------------------------------------------
  const hoverTimer = useRef<number | null>(null);
  const endHover = useCallback(() => {
    if (hoverTimer.current !== null) window.clearTimeout(hoverTimer.current);
    hoverTimer.current = null;
    setHover(null);
  }, []);
  const startHover = (agentId: string, element: HTMLElement) => {
    if (dragIdRef.current || menu || !hoverCapable()) return;
    if (hoverTimer.current !== null) window.clearTimeout(hoverTimer.current);
    hoverTimer.current = window.setTimeout(() => {
      hoverTimer.current = null;
      if (!element.isConnected || dragIdRef.current) return;
      setHover({ agentId, anchor: element.getBoundingClientRect() });
    }, HOVER_CARD_MS);
  };
  useEffect(() => () => {
    if (hoverTimer.current !== null) window.clearTimeout(hoverTimer.current);
  }, []);

  const timeLabel = (agentId: string) => {
    const at = activity.get(agentId)?.lastMs;
    return at ? formatRelative(at, now, language, t("society.shell.time_now")) : undefined;
  };

  const hiddenCount = agents.filter((agent) => hiddenIds.includes(agent.agentId)).length;
  const needsYouCount = agents.filter(needsYou).length;
  const unreadCount = agents.filter((agent) => unread.has(agent.agentId)).length;
  const canCreateTeam = !sample && Boolean(onOpenGroup);

  const renderRow = (agent: SocietyAgent, options: { draggable: boolean }) => {
    const facts = activity.get(agent.agentId);
    const isUnread = unread.has(agent.agentId);
    const isDragging = dragId === agent.agentId;
    const isDropTarget = options.draggable && dropId === agent.agentId && dragId !== agent.agentId;
    return (
      <li key={agent.agentId} className="relative">
        {isDropTarget && !dropAfter && !groupReady ? <div aria-hidden className="as-drop-line top-0 -translate-y-1/2" /> : null}
        <RosterRow
          agent={agent}
          displayName={display(agent)}
          status={rosterStatus(agent, isUnread)}
          preview={rosterPreview({ agent, draft: facts?.draft, lastMessage: facts?.lastMessage })}
          timeLabel={timeLabel(agent.agentId)}
          active={agent.agentId === activeAgentId}
          unread={isUnread}
          hidden={hiddenIds.includes(agent.agentId)}
          reorderable={reorderable && options.draggable}
          dragging={isDragging}
          dropTarget={isDropTarget}
          groupReady={options.draggable && groupHover?.kind === "agent" && groupHover.id === agent.agentId && groupReady}
          menuOpen={menu?.agentId === agent.agentId}
          shortcut={shortcutOf(agent.agentId)}
          onPointerDown={(event) => (options.draggable ? onRowPointerDown(event, agent.agentId) : undefined)}
          onClickCapture={onRowClickCapture}
          onKeyDown={(event) => (options.draggable ? onRowKeyDown(event, agent.agentId) : undefined)}
          onContextMenu={(event) => openMenu(event, agent.agentId)}
          onOpen={() => openAgent(agent.agentId)}
          onOpenProfile={() => openProfile(agent.agentId)}
          onHoverStart={(element) => startHover(agent.agentId, element)}
          onHoverEnd={endHover}
        />
        {options.draggable && groupHover?.kind === "agent" && groupHover.id === agent.agentId && (
          <span data-testid="society-group-drop-hint" className="pointer-events-none absolute right-2 top-1 rounded bg-primary px-1.5 py-0.5 text-[10px] text-primary-foreground">
            {t(groupReady ? "society.groups.release_to_group" : "society.groups.hold_to_group")}
          </span>
        )}
        {isDropTarget && dropAfter && !groupReady ? <div aria-hidden className="as-drop-line bottom-0 translate-y-1/2" /> : null}
      </li>
    );
  };

  const hoverAgent = hover ? agents.find((agent) => agent.agentId === hover.agentId) : undefined;
  const hoverData: HoverCardData | null = hover && hoverAgent ? {
    agent: hoverAgent,
    displayName: display(hoverAgent),
    status: rosterStatus(hoverAgent, unread.has(hoverAgent.agentId)),
    reason: waitingReasonOf(hoverAgent),
    lastMessage: activity.get(hoverAgent.agentId)?.lastMessage,
    draft: activity.get(hoverAgent.agentId)?.draft,
    timeLabel: timeLabel(hoverAgent.agentId),
    anchor: hover.anchor,
  } : null;

  const overlays = (
    <>
      {menu && menuAgent && <AgentRosterActions key={menu.agentId} agent={menuAgent} roster={agents} sample={sample}
        hidden={hiddenIds.includes(menu.agentId)} x={menu.x} y={menu.y} onVisibilityChange={setHidden} onDismiss={closeMenu}
        pinned={pinIds.includes(menu.agentId)} canPin={livePinCount < MAX_PINNED} onTogglePin={onTogglePin}
        unread={unread.has(menu.agentId)} canMarkUnread={menu.agentId !== activeAgentId} onMarkUnread={markUnread} />}
      {groupMenu && menuGroup && <GroupRosterActions key={groupMenu.groupId} group={menuGroup} x={groupMenu.x} y={groupMenu.y}
        onEdit={() => setEditingGroupId(menuGroup.group_id)} onDismiss={() => setGroupMenu(null)} />}
      {profile && <Suspense fallback={null}><AgentProfileDialog key={profile.agentId} agent={profile} sample={sample} onClose={() => setProfileId(null)} /></Suspense>}
      {creatingGroup && <ChatGroupDialog agents={agents} onClose={() => setCreatingGroup(false)} onSaved={(id) => onOpenGroup?.(id)} />}
      {editingGroup && <ChatGroupDialog group={editingGroup} agents={agents} onClose={() => setEditingGroupId(null)} onSaved={(id) => onOpenGroup?.(id)} />}
      {hoverData && !menu && !dragId ? <RosterHoverCard data={hoverData} /> : null}
    </>
  );

  const asideClass = cn(
    "agent-section as-roster flex h-full min-h-0 flex-col border-border",
    side === "left" ? "border-r border-border" : "border-l border-border",
    className ?? (collapsed ? "w-16 shrink-0" : "w-[300px] shrink-0"),
  );

  if (collapsed) {
    const railAgents = [...pinned, ...attention, ...(leadRow ? [leadRow] : []), ...rows];
    return (
      <aside ref={railRef} data-testid="society-roster-rail" data-collapsed="true" aria-label={t("society.roster.title")} className={asideClass}>
        <div className="flex flex-col items-center gap-1.5 px-2 pb-2 pt-3">
          {onToggleCollapsed ? (
            <button type="button" onClick={onToggleCollapsed} aria-label={t("society.shell.roster_expand")} title={t("society.shell.roster_expand")}
              className="as-ghost-button h-8 w-8 px-0" data-testid="roster-expand">
              <PanelLeftOpen className="h-4 w-4" aria-hidden />
            </button>
          ) : null}
          <button type="button" onClick={onCreate} aria-label={t("society.shell.new_agent")} title={t("society.shell.new_agent")}
            className="as-ink-button h-8 w-8 justify-center rounded-full px-0" data-testid="society-create-button">
            <Plus className="h-4 w-4" aria-hidden />
          </button>
        </div>
        <ScrollArea className="min-h-0 flex-1">
          <ul className="flex flex-col items-center gap-1 px-2 pb-3">
            {railAgents.map((agent) => (
              <li key={agent.agentId}>
                <button type="button" onClick={() => openAgent(agent.agentId)} onContextMenu={(event) => openMenu(event, agent.agentId)}
                  aria-label={display(agent)} title={display(agent)} aria-current={agent.agentId === activeAgentId ? "true" : undefined}
                  data-active={agent.agentId === activeAgentId ? "true" : undefined}
                  style={agentTint(agent)}
                  className="as-pin w-12 px-0 py-1.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  <span className="as-avatar">
                    <AgentSwatch agent={agent} size={36} />
                    <StatusMark status={rosterStatus(agent, unread.has(agent.agentId))} />
                    {shortcutOf(agent.agentId) !== null ? <span className="as-shortcut-badge" aria-hidden>{shortcutOf(agent.agentId)}</span> : null}
                  </span>
                </button>
              </li>
            ))}
            {visibleGroups.length > 0 ? <li aria-hidden className="my-1 w-6 border-t border-border" /> : null}
            {visibleGroups.map((group) => (
              <li key={group.group_id}>
                <button type="button" data-group-id={group.group_id} onClick={() => onOpenGroup?.(group.group_id)}
                  aria-label={group.name} title={group.name} aria-current={activeGroupId === group.group_id ? "true" : undefined}
                  data-active={activeGroupId === group.group_id ? "true" : undefined}
                  className="as-pin w-12 px-0 py-1.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  <GroupFaces group={group} agents={agents} size={22} />
                </button>
              </li>
            ))}
          </ul>
        </ScrollArea>
        {overlays}
      </aside>
    );
  }

  const filterButton = (value: RosterFilter, label: string, count?: number) => (
    <button key={value} type="button" aria-pressed={filter === value} onClick={() => setFilter(value)}
      className="as-seg-item" data-testid={`roster-filter-${value}`}>
      <span className="truncate">{label}</span>
      {count ? <span className={value === "needs-you" ? "as-seg-count" : "as-seg-count text-muted-foreground"}>{count}</span> : null}
    </button>
  );

  const nothingListed = !leadRow && rows.length === 0 && attention.length === 0 && pinned.length === 0 && visibleGroups.length === 0;
  const showLoading = (teamsPending && rows.length === 0) || (loading && agents.length === 0);

  return (
    <aside ref={railRef} data-testid="society-roster-rail" className={asideClass}>
      {header}
      <div className="flex h-12 shrink-0 items-center gap-1.5 pl-4 pr-2.5">
        <h2 className="truncate font-display text-[13px] font-semibold tracking-tight text-foreground-strong">
          {t("society.roster.title")}
        </h2>
        {sample ? (
          <Badge variant="outline" className="text-xs">
            {t("society.sample_badge")}
          </Badge>
        ) : null}
        <span className="ml-auto" />
        {onToggleCollapsed ? (
          <button type="button" onClick={onToggleCollapsed} aria-label={t("society.shell.roster_collapse")} title={t("society.shell.roster_collapse")}
            className="as-ghost-button h-7 w-7 px-0" data-testid="roster-collapse">
            <PanelLeftClose className="h-4 w-4" aria-hidden />
          </button>
        ) : null}
        <button type="button" className="as-ink-button" onClick={onCreate} data-testid="society-create-button" title={t("society.shell.new_agent")}>
          <Plus className="h-3.5 w-3.5" aria-hidden />
          {t("society.roster.create")}
        </button>
      </div>
      <div className="flex flex-col gap-2 px-3">
        <label className="relative block">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape" && query) {
                e.preventDefault();
                setQuery("");
              }
            }}
            placeholder={t("society.roster.search")}
            aria-label={t("society.roster.search")}
            className="h-8 w-full rounded-lg border border-border bg-background pl-8 pr-2 text-[13px] text-foreground placeholder:text-muted-foreground focus-visible:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          />
        </label>
        {agents.length > 1 ? (
          <div role="group" aria-label={t("society.shell.filter_label")} className="as-seg">
            {filterButton("all", t("society.shell.filter_all"))}
            {filterButton("needs-you", t("society.shell.filter_needs_you"), needsYouCount)}
            {filterButton("unread", t("society.shell.filter_unread"), unreadCount)}
          </div>
        ) : null}
        {hiddenCount > 0 && <button type="button" onClick={() => setShowHidden((value) => !value)}
          className="-mx-1 flex items-center gap-1.5 rounded-md px-2 py-1 text-left text-xs text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <Eye className="h-3.5 w-3.5" aria-hidden />
          {t(showHidden ? "society.roster.hide_hidden" : "society.roster.show_hidden").replace("{0}", String(hiddenCount))}
        </button>}
      </div>
      <ScrollArea className="mt-2 min-h-0 flex-1">
        <div className="flex flex-col gap-2.5 px-2 pb-3">
          {pinned.length > 0 ? (
            <div className="as-pins" role="list" aria-label={t("society.shell.pinned")} data-testid="roster-pins">
              {pinned.map((agent) => (
                <button key={agent.agentId} type="button" role="listitem" data-pinned-id={agent.agentId}
                  onClick={() => openAgent(agent.agentId)} onContextMenu={(event) => openMenu(event, agent.agentId)}
                  aria-current={agent.agentId === activeAgentId ? "true" : undefined}
                  data-active={agent.agentId === activeAgentId ? "true" : undefined}
                  title={display(agent)} style={agentTint(agent)}
                  className="as-pin focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  <span className="as-avatar">
                    <AgentSwatch agent={agent} size={40} />
                    <StatusMark status={rosterStatus(agent, unread.has(agent.agentId))} />
                    {shortcutOf(agent.agentId) !== null ? <span className="as-shortcut-badge" aria-hidden>{shortcutOf(agent.agentId)}</span> : null}
                  </span>
                  <span className="as-pin-name">{display(agent)}</span>
                </button>
              ))}
            </div>
          ) : null}
          {attention.length > 0 ? (
            <RosterSection id="needs-you" title={t("society.shell.section_needs_you")} count={attention.length} tone="attention">
              <ul className="flex flex-col gap-1" data-testid="roster-needs-you">
                {attention.map((agent) => renderRow(agent, { draggable: false }))}
              </ul>
            </RosterSection>
          ) : null}
          {(visibleGroups.length > 0 || (canCreateTeam && browsing)) ? (
            <RosterSection id="teams" title={t("society.shell.section_teams")} count={visibleGroups.length || undefined}>
              <ul className="flex flex-col gap-1">
                {visibleGroups.map((group) => {
                  const hovered = groupHover?.kind === "group" && groupHover.id === group.group_id;
                  const members = group.members.filter((id) => agents.some((agent) => agent.agentId === id));
                  return (
                    <li key={group.group_id}>
                      <button type="button" data-group-id={group.group_id} onClick={() => onOpenGroup?.(group.group_id)} onContextMenu={(event) => openGroupMenu(event, group.group_id)} aria-current={activeGroupId === group.group_id ? "true" : undefined}
                        data-active={activeGroupId === group.group_id ? "true" : undefined}
                        data-group-ready={hovered && groupReady ? "true" : undefined}
                        data-drop={hovered && !groupReady ? "true" : undefined}
                        className="as-row focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        data-testid={`society-group-${group.group_id}`}>
                        <span className="flex w-9 shrink-0 items-center justify-center">
                          <GroupFaces group={group} agents={agents} size={24} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="as-row-name block">{group.name}</span>
                          <span className="as-row-preview">{hovered
                            ? t(groupReady ? "society.groups.release_to_group" : "society.groups.hold_to_group")
                            : members.length === 0
                              ? t("society.shell.team_empty")
                              : group.lead_agent_id
                                ? `${t("society.lead.rail").replace("{0}", memberName(group.lead_agent_id))} · ${group.members.filter((id) => id !== group.lead_agent_id).map(memberName).join(", ")}`
                                : group.members.map(memberName).join(", ")}</span>
                        </span>
                      </button>
                    </li>
                  );
                })}
                {canCreateTeam && browsing ? (
                  <li>
                    <button type="button" onClick={() => setCreatingGroup(true)} data-testid="society-create-group-button"
                      className="flex h-9 w-full items-center gap-2 rounded-[10px] px-2.5 text-left text-xs text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                      <span className="grid h-6 w-6 place-items-center rounded-full border border-dashed border-border-strong">
                        <UsersRound className="h-3.5 w-3.5" aria-hidden />
                      </span>
                      {t("society.groups.create")}
                    </button>
                  </li>
                ) : null}
              </ul>
            </RosterSection>
          ) : null}
          {(leadRow || rows.length > 0) ? (
            <RosterSection id="agents" title={t("society.shell.section_agents")} count={rows.length + (leadRow ? 1 : 0)}>
              {leadRow ? (
                <ul className="flex flex-col gap-1">
                  {renderRow(leadRow, { draggable: false })}
                </ul>
              ) : null}
              <ul ref={listRef} className={cn("flex flex-col gap-1", leadRow && rows.length > 0 && "mt-1")}>
                {rows.map((agent) => renderRow(agent, { draggable: true }))}
              </ul>
            </RosterSection>
          ) : <ul ref={listRef} className="hidden" />}
          {showLoading ? (
            <p className="px-2 py-3 text-xs text-muted-foreground">{t("society.roster.loading")}</p>
          ) : null}
          {/* Under "All" with no search, an empty list means everyone is
              hidden; the show-hidden control above already says so. */}
          {!showLoading && !loading && nothingListed && (agents.length === 0 || q !== "" || filter !== "all") ? (
            <EmptyState
              filter={filter}
              searching={q !== ""}
              noAgents={agents.length === 0}
              onShowAll={() => setFilter("all")}
              onClearSearch={() => setQuery("")}
              onCreate={onCreate}
            />
          ) : null}
        </div>
      </ScrollArea>
      {footer}
      {overlays}
    </aside>
  );
}

/** Up to three member faces, overlapped. */
function GroupFaces({ group, agents, size }: { group: SocietyChatGroup; agents: SocietyAgent[]; size: number }) {
  const members = group.members
    .map((id) => agents.find((agent) => agent.agentId === id))
    .filter((agent): agent is SocietyAgent => Boolean(agent))
    .slice(0, 3);
  if (members.length === 0) {
    return <span className="grid place-items-center rounded-full border border-dashed border-border-strong text-muted-foreground" style={{ width: size, height: size }}>
      <UsersRound className="h-3 w-3" aria-hidden />
    </span>;
  }
  return (
    <span className="flex items-center">
      {members.map((member, index) => (
        <span key={member.agentId} className={cn("rounded-full ring-2 ring-sidebar", index > 0 && "-ml-2.5")}>
          <AgentSwatch agent={member} size={size} />
        </span>
      ))}
    </span>
  );
}

/** One sentence and one action: what would appear here and how it gets there. */
function EmptyState({ filter, searching, noAgents, onShowAll, onClearSearch, onCreate }: {
  filter: RosterFilter;
  searching: boolean;
  noAgents: boolean;
  onShowAll: () => void;
  onClearSearch: () => void;
  onCreate: () => void;
}) {
  const t = useT();
  if (noAgents) {
    return (
      <div className="as-empty" data-testid="roster-empty">
        <p>{t("society.shell.empty_agents")}</p>
        <button type="button" className="as-ink-button" onClick={onCreate}>
          <Plus className="h-3.5 w-3.5" aria-hidden />{t("society.shell.new_agent")}
        </button>
      </div>
    );
  }
  if (searching) {
    return (
      <div className="as-empty" data-testid="roster-empty">
        <p>{t("society.roster.empty")}</p>
        <button type="button" className="as-ghost-button -ml-2" onClick={onClearSearch}>
          <X className="h-3.5 w-3.5" aria-hidden />{t("society.shell.clear_search")}
        </button>
      </div>
    );
  }
  return (
    <div className="as-empty" data-testid="roster-empty">
      <p>{t(filter === "needs-you" ? "society.shell.empty_needs_you" : "society.shell.empty_unread")}</p>
      <button type="button" className="as-ghost-button -ml-2" onClick={onShowAll}>{t("society.shell.show_all")}</button>
    </div>
  );
}
