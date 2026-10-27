/**
 * The roster: the Agents section's navigation, kept quiet on purpose. Two
 * round buttons at the top (search, and "+" for a new agent or team), the
 * lead large and centred under them, then one plain list: a face, a name and
 * one muted preview line per row. Order carries the grouping, without
 * headings:
 *
 *   - pinned agents as a four-up grid of faces,
 *   - every agent that waits on the person (a ring on its face says why),
 *   - teams, as rows with their members' faces stacked,
 *   - everyone else, in the person's own drag order.
 *
 * Search opens from its button and narrows the list. The roster can fold to
 * an avatar rail; the frame decides when it must.
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
import { PanelLeftOpen, Plus, Search } from "lucide-react";

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
import { RosterHoverCard, type HoverCardData } from "./RosterHoverCard";
import { formatRelative, needsYou, rosterPreview, rosterStatus, waitingReasonOf } from "./rosterPreview";
import { HIDDEN_AGENTS_KEY, MAX_PINNED, ORDER_KEY, PINNED_KEY, togglePin, usePersistedIds, writeIdList } from "./rosterPrefs";
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
  const [searchOpen, setSearchOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const addRef = useRef<HTMLDivElement>(null);
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
  // The folded rail has no search box on screen, so it lists everyone; the
  // search comes back with the rows.
  const q = collapsed ? "" : query.trim().toLowerCase();
  const browsing = q === "";
  const visibleGroups = groups.filter((group) => `${group.name} ${group.members.map(memberName).join(" ")}`.toLowerCase().includes(q));

  const { heroLead, pinned, attention, leadRow, rows } = useMemo(() => {
    const isHidden = (a: SocietyAgent) => !showHidden && hiddenIds.includes(a.agentId);
    const matches = (a: SocietyAgent) => !q || `${a.name} ${display(a)} ${a.title}`.toLowerCase().includes(q);
    const shown = (a: SocietyAgent) => !isHidden(a) && matches(a);
    // The lead stands apart, large, above the list while nothing is searched.
    const hero = browsing && lead && !isHidden(lead) ? lead : null;
    // Pins are an arrangement of the whole list; while a search or filter
    // narrows it, they fold back into the excerpt.
    const pinnedRows = browsing
      ? pinIds.map((id) => agents.find((a) => a.agentId === id)).filter((a): a is SocietyAgent => Boolean(a) && !isHidden(a!) && a!.agentId !== hero?.agentId)
      : [];
    const pinnedSet = new Set(pinnedRows.map((a) => a.agentId));
    // Team members wait on the person too; they surface here even though
    // their team keeps them out of the plain list.
    const waiting = agents.filter((a) => shown(a) && needsYou(a) && !pinnedSet.has(a.agentId) && a.agentId !== hero?.agentId);
    const waitingSet = new Set(waiting.map((a) => a.agentId));
    const leadShown = !hero && lead && shown(lead) && !pinnedSet.has(lead.agentId) && !waitingSet.has(lead.agentId) ? lead : null;
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
    return { heroLead: hero, pinned: pinnedRows, attention: waiting, leadRow: leadShown, rows: rest };
  }, [agents, browsing, display, groupedIds, hiddenIds, lead, orderIds, pinIds, q, showHidden, teamsPending]);

  // While searching or filtering, the list is an excerpt — dragging there
  // would file agents by where they happen to sit in it, so rows stay put.
  const reorderable = browsing;

  /** Every agent in the order the person sees them: the keyboard walks this. */
  const navOrder = useMemo(
    () => [...(heroLead ? [heroLead] : []), ...pinned, ...attention, ...(leadRow ? [leadRow] : []), ...rows].map((a) => a.agentId),
    [attention, heroLead, leadRow, pinned, rows],
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
  const canCreateTeam = !sample && Boolean(onOpenGroup);

  // The "+" menu closes on a press outside it or on Escape.
  useEffect(() => {
    if (!addOpen) return;
    const onDown = (event: PointerEvent) => {
      if (!addRef.current?.contains(event.target as Node)) setAddOpen(false);
    };
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setAddOpen(false);
    };
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [addOpen]);

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
          <span data-testid="society-group-drop-hint" className="pointer-events-none absolute right-2 top-1 rounded-full bg-primary px-2 py-0.5 text-[12px] text-primary-foreground">
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
    const railAgents = [...(heroLead ? [heroLead] : []), ...pinned, ...attention, ...(leadRow ? [leadRow] : []), ...rows];
    return (
      <aside ref={railRef} data-testid="society-roster-rail" data-collapsed="true" aria-label={t("society.roster.title")} className={asideClass}>
        <div className="flex flex-col items-center gap-1.5 px-2 pb-2 pt-3">
          {onToggleCollapsed ? (
            <button type="button" onClick={onToggleCollapsed} aria-label={t("society.shell.roster_expand")} title={t("society.shell.roster_expand")}
              className="as-round-button" data-testid="roster-expand">
              <PanelLeftOpen className="h-4 w-4" aria-hidden />
            </button>
          ) : null}
          <button type="button" onClick={onCreate} aria-label={t("society.shell.new_agent")} title={t("society.shell.new_agent")}
            className="as-round-button" data-testid="society-create-button">
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

  const nothingListed = !heroLead && !leadRow && rows.length === 0 && attention.length === 0 && pinned.length === 0 && visibleGroups.length === 0;
  const showLoading = (teamsPending && rows.length === 0) || (loading && agents.length === 0);
  const closeSearch = () => {
    setQuery("");
    setSearchOpen(false);
  };

  return (
    <aside ref={railRef} data-testid="society-roster-rail" aria-label={t("society.roster.title")} className={asideClass}>
      {header}
      <div className="as-roster-top">
        {sample ? (
          <span className="mr-auto pl-1 text-[13px] text-muted-foreground">{t("society.sample_badge")}</span>
        ) : null}
        <button type="button" className="as-round-button" aria-label={t("society.roster.search")} title={t("society.roster.search")}
          aria-pressed={searchOpen} data-testid="roster-search-toggle"
          onClick={() => (searchOpen ? closeSearch() : setSearchOpen(true))}>
          <Search className="h-4 w-4" aria-hidden />
        </button>
        <div ref={addRef} className="relative">
          <button type="button" className="as-round-button" data-testid="society-create-button"
            aria-label={t("society.shell.new_agent")} title={t("society.shell.new_agent")}
            aria-haspopup={canCreateTeam ? "menu" : undefined} aria-expanded={canCreateTeam ? addOpen : undefined}
            onClick={() => (canCreateTeam ? setAddOpen((value) => !value) : onCreate())}>
            <Plus className={cn("h-4 w-4 transition-transform duration-200 motion-reduce:transition-none", addOpen && "rotate-45")} aria-hidden />
          </button>
          {addOpen ? (
            <div role="menu" aria-label={t("society.shell.new_agent")} className="as-menu absolute right-0 top-full z-40 mt-2 w-52">
              <button type="button" role="menuitem" className="as-menu-row" data-testid="roster-new-agent"
                onClick={() => { setAddOpen(false); onCreate(); }}>
                {t("society.shell.new_agent")}
              </button>
              <button type="button" role="menuitem" className="as-menu-row" data-testid="society-create-group-button"
                onClick={() => { setAddOpen(false); setCreatingGroup(true); }}>
                {t("society.groups.create")}
              </button>
            </div>
          ) : null}
        </div>
      </div>
      {searchOpen ? (
        <div className="px-3 pb-2">
          <input
            type="search"
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Escape") return;
              e.preventDefault();
              if (query) setQuery("");
              else closeSearch();
            }}
            placeholder={t("society.roster.search")}
            aria-label={t("society.roster.search")}
            className="as-search"
            data-testid="roster-search"
          />
        </div>
      ) : null}
      {heroLead ? (
        <div className="flex justify-center px-3 pb-3 pt-1">
          <button type="button" className="as-hero" style={agentTint(heroLead)}
            onClick={() => openAgent(heroLead.agentId)} onContextMenu={(event) => openMenu(event, heroLead.agentId)}
            aria-current={heroLead.agentId === activeAgentId ? "true" : undefined}
            data-active={heroLead.agentId === activeAgentId ? "true" : undefined}
            data-testid="roster-lead">
            <span className="as-avatar as-hero-face">
              <AgentSwatch agent={heroLead} size={60} />
              <StatusMark status={rosterStatus(heroLead, unread.has(heroLead.agentId))} />
              {shortcutOf(heroLead.agentId) !== null ? <span className="as-shortcut-badge" aria-hidden>{shortcutOf(heroLead.agentId)}</span> : null}
            </span>
            <span className="as-hero-name">{display(heroLead)}</span>
          </button>
        </div>
      ) : null}
      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-0.5 px-2 pb-3">
          {pinned.length > 0 ? (
            <div className="as-pins mb-1" role="list" aria-label={t("society.shell.pinned")} data-testid="roster-pins">
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
            <ul className="flex flex-col gap-0.5" data-testid="roster-needs-you" aria-label={t("society.shell.section_needs_you")}>
              {attention.map((agent) => renderRow(agent, { draggable: false }))}
            </ul>
          ) : null}
          {visibleGroups.length > 0 ? (
            <ul className="flex flex-col gap-0.5" aria-label={t("society.shell.section_teams")} data-testid="roster-teams">
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
                      <span className="flex w-10 shrink-0 items-center justify-center">
                        <GroupFaces group={group} agents={agents} size={24} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="as-row-name block">{group.name}</span>
                        <span className="as-row-preview">{hovered
                          ? t(groupReady ? "society.groups.release_to_group" : "society.groups.hold_to_group")
                          : members.length === 0
                            ? t("society.shell.team_empty")
                            : members.map(memberName).join(", ")}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : null}
          {leadRow ? (
            <ul className="flex flex-col gap-0.5">
              {renderRow(leadRow, { draggable: false })}
            </ul>
          ) : null}
          <ul ref={listRef} className="flex flex-col gap-0.5" aria-label={t("society.shell.section_agents")} data-testid="roster-agents">
            {rows.map((agent) => renderRow(agent, { draggable: true }))}
          </ul>
          {hiddenCount > 0 ? (
            <button type="button" onClick={() => setShowHidden((value) => !value)} className="as-quiet-link mt-2 self-start">
              {t(showHidden ? "society.roster.hide_hidden" : "society.roster.show_hidden").replace("{0}", String(hiddenCount))}
            </button>
          ) : null}
          {showLoading ? (
            <p className="px-3 py-3 text-[13px] text-muted-foreground">{t("society.roster.loading")}</p>
          ) : null}
          {/* With no search, an empty list means everyone is hidden; the
              show-hidden link above already says so. */}
          {!showLoading && !loading && nothingListed && (agents.length === 0 || q !== "") ? (
            <EmptyState noAgents={agents.length === 0} onClearSearch={closeSearch} onCreate={onCreate} />
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
    return <span className="rounded-full border border-dashed border-border-strong" style={{ width: size, height: size }} aria-hidden />;
  }
  return (
    <span className="flex items-center">
      {members.map((member, index) => (
        <span key={member.agentId} className={cn("rounded-full ring-2 ring-sidebar", index > 0 && "-ml-4")}>
          <AgentSwatch agent={member} size={size} />
        </span>
      ))}
    </span>
  );
}

/** One sentence and one action: what would appear here and how it gets there. */
function EmptyState({ noAgents, onClearSearch, onCreate }: {
  noAgents: boolean;
  onClearSearch: () => void;
  onCreate: () => void;
}) {
  const t = useT();
  if (noAgents) {
    return (
      <div className="as-empty" data-testid="roster-empty">
        <p>{t("society.shell.empty_agents")}</p>
        <button type="button" className="as-pill-button" data-tone="ink" onClick={onCreate}>{t("society.shell.new_agent")}</button>
      </div>
    );
  }
  return (
    <div className="as-empty" data-testid="roster-empty">
      <p>{t("society.roster.empty")}</p>
      <button type="button" className="as-pill-button" onClick={onClearSearch}>{t("society.shell.clear_search")}</button>
    </div>
  );
}
