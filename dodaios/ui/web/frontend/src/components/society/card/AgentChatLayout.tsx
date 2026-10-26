/**
 * The Agents section's frame: roster | chat | details, as one grid.
 *
 * The roster is the navigation, the chat is the stage, and the details pane
 * belongs to the open agent. The roster and the pane are resizable within
 * fixed bounds and remember their width and open state; the chat always
 * keeps `CHAT_MIN` pixels. When the window narrows, the pane shrinks, then
 * closes, then the roster folds to its avatar rail (`resolveShellLayout`).
 * Opening a region the window had to close shows it as a sheet over the chat
 * instead, so nothing is ever out of reach.
 *
 * Every region stays mounted: folding the pane must not reset a browser
 * stream, a routine draft or the chat's unsent text.
 */
import { useCallback, useEffect, useId, useLayoutEffect, useReducer, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode, type RefObject } from "react";
import { PanelRightClose, PanelRightOpen } from "lucide-react";

import { useLocaleChunk, useT } from "@/i18n";
import { cn } from "@/lib/utils";

import "../agentSection.css";
import "./agentChatLayout.css";
import {
  CHAT_MIN,
  PANE_DEFAULT,
  PANE_MAX,
  PANE_MIN,
  ROSTER_DEFAULT,
  ROSTER_MAX,
  ROSTER_MIN,
  ROSTER_RAIL,
  readShellPrefs,
  resolveShellLayout,
  shellPrefsReducer,
  writeShellPrefs,
} from "./shellLayout";

export interface RosterSlotState {
  /** Show the avatar rail instead of rows. */
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

export interface AgentChatLayoutProps {
  /** The chat column. */
  children: ReactNode;
  /** The details pane's content (`OptionsRail`). */
  options: ReactNode;
  /** The roster column; without it the frame is chat | details only. */
  roster?: (state: RosterSlotState) => ReactNode;
  /** The chat header, handed the details toggle to place. Without it a slim bar carries the toggle. */
  header?: (detailsToggle: ReactNode) => ReactNode;
  /** Closes the sheets when it changes (the open agent's id). */
  resetKey?: string;
}

const KEY_STEP = 16;

function useMeasuredWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    setWidth(element.getBoundingClientRect().width);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const next = entries[0]?.contentRect.width;
      if (typeof next === "number") setWidth(next);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

export function AgentChatLayout({ children, options, roster, header, resetKey }: AgentChatLayoutProps) {
  const t = useT();
  useLocaleChunk("society");
  const rootRef = useRef<HTMLDivElement>(null);
  const rosterRef = useRef<HTMLDivElement>(null);
  const paneRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const [prefs, dispatch] = useReducer(shellPrefsReducer, undefined, readShellPrefs);
  const [paneSheet, setPaneSheet] = useState(false);
  const [rosterSheet, setRosterSheet] = useState(false);
  const [resizing, setResizing] = useState<"roster" | "pane" | null>(null);
  const measured = useMeasuredWidth(rootRef);
  // Before the first measurement (and in a test DOM) nothing has to give way.
  const available = measured > 0 ? measured : Number.POSITIVE_INFINITY;
  // Without a roster the frame is chat | details; the resolver always counts
  // a roster column, so hand it the rail's width back.
  const layout = roster
    ? resolveShellLayout(available, prefs, true)
    : resolveShellLayout(available + ROSTER_RAIL, { ...prefs, rosterCollapsed: true }, true);
  const rosterWidth = roster ? layout.rosterWidth : 0;

  useEffect(() => {
    writeShellPrefs(prefs);
  }, [prefs]);

  // A sheet is for a region the window closed; once it fits again it docks.
  useEffect(() => {
    if (!layout.paneForced) setPaneSheet(false);
  }, [layout.paneForced]);
  useEffect(() => {
    if (!layout.rosterForced) setRosterSheet(false);
  }, [layout.rosterForced]);
  useEffect(() => {
    setRosterSheet(false);
    setPaneSheet(false);
  }, [resetKey]);

  // Sheets close on Escape and on a press outside them.
  useEffect(() => {
    if (!paneSheet && !rosterSheet) return;
    const onDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (target instanceof Element && target.closest('[role="menu"], [role="dialog"], [role="listbox"]')) return;
      if (rosterSheet && !rosterRef.current?.contains(target)) setRosterSheet(false);
      if (paneSheet && !paneRef.current?.contains(target) && !toggleRef.current?.contains(target)) setPaneSheet(false);
    };
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      setRosterSheet(false);
      setPaneSheet(false);
    };
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [paneSheet, rosterSheet]);

  const paneVisible = layout.paneOpen || paneSheet;
  const toggleLabel = t(paneVisible ? "society.card.options_collapse" : "society.card.options_expand");
  const ToggleIcon = paneVisible ? PanelRightClose : PanelRightOpen;
  const togglePane = useCallback(() => {
    if (layout.paneForced) setPaneSheet((value) => !value);
    else {
      setPaneSheet(false);
      dispatch({ type: "toggle-pane" });
    }
  }, [layout.paneForced]);
  const toggleRoster = useCallback(() => {
    if (layout.rosterForced) setRosterSheet((value) => !value);
    else {
      setRosterSheet(false);
      dispatch({ type: "toggle-roster" });
    }
  }, [layout.rosterForced]);

  // --- resizing -------------------------------------------------------------
  const drag = useRef<{ edge: "roster" | "pane"; startX: number; startWidth: number; pointerId: number } | null>(null);
  const maxFor = (edge: "roster" | "pane") => {
    if (!Number.isFinite(available)) return edge === "roster" ? ROSTER_MAX : PANE_MAX;
    const others = edge === "roster" ? layout.paneWidth : rosterWidth;
    const room = available - others - CHAT_MIN;
    return edge === "roster" ? Math.max(ROSTER_MIN, Math.min(ROSTER_MAX, room)) : Math.max(PANE_MIN, Math.min(PANE_MAX, room));
  };
  const resizeTo = (edge: "roster" | "pane", width: number) => {
    const bounded = Math.min(maxFor(edge), width);
    dispatch(edge === "roster" ? { type: "resize-roster", width: bounded } : { type: "resize-pane", width: bounded });
  };
  const onResizeDown = (edge: "roster" | "pane") => (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    drag.current = {
      edge,
      startX: event.clientX,
      startWidth: edge === "roster" ? rosterWidth : layout.paneWidth,
      pointerId: event.pointerId,
    };
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // A synthetic or already-released pointer: window listeners still follow it.
    }
    setResizing(edge);
  };
  const onResizeMove = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    const delta = event.clientX - current.startX;
    resizeTo(current.edge, current.edge === "roster" ? current.startWidth + delta : current.startWidth - delta);
  };
  const onResizeEnd = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return;
    drag.current = null;
    setResizing(null);
  };
  const onResizeKey = (edge: "roster" | "pane") => (event: KeyboardEvent<HTMLButtonElement>) => {
    const width = edge === "roster" ? rosterWidth : layout.paneWidth;
    const grow = edge === "roster" ? "ArrowRight" : "ArrowLeft";
    const shrink = edge === "roster" ? "ArrowLeft" : "ArrowRight";
    if (event.key === grow || event.key === shrink) {
      event.preventDefault();
      resizeTo(edge, width + (event.key === grow ? KEY_STEP : -KEY_STEP));
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      resizeTo(edge, event.key === "Home" ? (edge === "roster" ? ROSTER_MIN : PANE_MIN) : maxFor(edge));
    }
  };

  const separator = (edge: "roster" | "pane", width: number) => (
    <button
      type="button"
      role="separator"
      aria-orientation="vertical"
      aria-label={t(edge === "roster" ? "society.shell.resize_roster" : "society.shell.resize_details")}
      aria-valuemin={edge === "roster" ? ROSTER_MIN : PANE_MIN}
      aria-valuemax={maxFor(edge)}
      aria-valuenow={width}
      data-edge={edge === "roster" ? "right" : "left"}
      data-active={resizing === edge ? "true" : undefined}
      data-testid={`shell-resize-${edge}`}
      className="as-resizer"
      onPointerDown={onResizeDown(edge)}
      onPointerMove={onResizeMove}
      onPointerUp={onResizeEnd}
      onPointerCancel={onResizeEnd}
      onKeyDown={onResizeKey(edge)}
      onDoubleClick={() => resizeTo(edge, edge === "roster" ? ROSTER_DEFAULT : PANE_DEFAULT)}
    />
  );

  const detailsToggle = (
    <button
      ref={toggleRef}
      type="button"
      onClick={togglePane}
      title={toggleLabel}
      aria-label={toggleLabel}
      aria-expanded={paneVisible}
      aria-controls={panelId}
      data-testid="shell-details-toggle"
      className="as-header-control"
    >
      <ToggleIcon aria-hidden className="h-4 w-4" />
      {header ? null : <span>{t("society.card.options")}</span>}
    </button>
  );

  const columns = roster
    ? `${rosterWidth}px minmax(0, 1fr) ${layout.paneWidth}px`
    : `minmax(0, 1fr) ${layout.paneWidth}px`;
  const rosterCollapsed = layout.roster === "rail" && !rosterSheet;

  return (
    <div
      ref={rootRef}
      className="agent-chat-layout agent-section as-shell"
      data-resizing={resizing ? "true" : undefined}
      data-roster={roster ? layout.roster : undefined}
      data-options-open={paneVisible}
      data-testid="agent-shell"
      style={{ gridTemplateColumns: columns, "--agent-pane-width": `${layout.paneWidth || PANE_MIN}px` } as CSSProperties}
    >
      {roster ? (
        <div className="as-region" style={{ zIndex: rosterSheet ? 30 : undefined }}>
          <div ref={rosterRef} className={cn("flex min-h-0 flex-1 flex-col", rosterSheet && "as-roster-overlay")}
            style={rosterSheet ? { width: ROSTER_DEFAULT } : undefined} data-testid="shell-roster">
            {roster({ collapsed: rosterCollapsed, onToggleCollapsed: toggleRoster })}
          </div>
          {layout.roster === "full" ? separator("roster", rosterWidth) : null}
        </div>
      ) : null}
      <div className={cn("as-region as-stage", roster && "border-l border-border")} data-testid="shell-stage">
        {header ? header(detailsToggle) : (
          <div className="flex shrink-0 justify-end border-b border-border px-2 py-1">{detailsToggle}</div>
        )}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">{children}</div>
      </div>
      <div
        ref={paneRef}
        id={panelId}
        hidden={!paneVisible}
        className="agent-chat-layout-options as-region as-pane"
        data-overlay={paneSheet ? "true" : undefined}
        style={paneSheet ? { width: Math.min(PANE_DEFAULT, Math.max(PANE_MIN, available - 48)) } : undefined}
        data-testid="shell-details"
      >
        {layout.paneOpen && !paneSheet ? separator("pane", layout.paneWidth) : null}
        {options}
      </div>
    </div>
  );
}
