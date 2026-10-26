import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode, type RefObject } from "react";
import { Check, Columns2, Maximize2, Minimize2, MoveHorizontal, Plus, SquareTerminal, X } from "lucide-react";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useResizablePane } from "@/hooks/useResizablePane";
import { PaneResizer } from "@/components/layout/PaneResizer";
import { DEFAULT_SPLIT_RATIO, MAX_TERMINAL_TABS, useIdeSidePanelStore, type SidePanelColumn, type SidePanelTabId } from "@/store/ideSidePanel";
import { useIdeChatStore } from "@/store/ideChat";
import { WorkspaceTerminal } from "@/components/workspace/WorkspaceTerminal";
import type { TerminalAppearance } from "../terminalThemes";
import { useExplorerPathRouting } from "@/store/ideExplorer";
import { usePaneReviewTracking } from "@/store/paneReviews";
import { SIDE_PANEL_TABS, sidePanelTab } from "./sidePanelTabs";
import { SurfaceKbd, SurfaceLauncher, surfaceActionForKey, type SurfaceAction } from "./SurfaceLauncher";
import { SIDE_PANEL_ID } from "./sidePanelIds";

const WIDTH_KEY = "jarvis.agenticIde.sidePanelWidth.v1";
const DEFAULT_PX = 340;
const MIN_PX = 260;
/**
 * Ceiling before the frame has been measured. The real limit is the frame
 * minus `GRID_RESERVED_PX`: a fixed cap here stopped the drag halfway across a
 * wide window, and it must stay high so the first, unmeasured render does not
 * clip a wider stored width.
 */
const UNMEASURED_MAX_PX = 4096;
/** The office map needs room to walk around in: its tab opens the panel at least this wide. */
const OFFICE_MIN_PX = 520;
/** Two tabs side by side need room for both: splitting widens a narrower panel to this once. */
const SPLIT_MIN_PX = 720;
/** How far a pressed tab must travel before it counts as dragged rather than clicked. */
const TAB_DRAG_SLOP_PX = 6;
/** Strip of terminal grid kept beside the panel, so its grip always stays reachable. */
const GRID_RESERVED_PX = 120;
/** Dragging the grip toward the right edge past this width and letting go closes the panel. */
const COLLAPSE_BELOW_PX = 160;

// Preserve the existing public export without coupling caption chrome to the panel.
export { SIDE_PANEL_ID } from "./sidePanelIds";

const HEADER_BTN =
  "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors " +
  "hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent";

/**
 * The Agentic IDE's workspace with its right-hand side panel.
 *
 * `children` (the terminal grid) takes the free width; the panel host on the
 * right is ALWAYS mounted and only its width moves between 0 and the stored
 * size, so opening or closing it never changes the sibling identity of a live
 * terminal or its PTY socket — the same trick the legacy explorer used.
 */
/**
 * `markInUse`: frame the panel in the signal blue while the reader works in it,
 * the way a focused terminal tile is framed (the minimal pane style).
 */
export function IdeSidePanelFrame({ children, markInUse = false, appearance, onScreen = true }: {
  children: ReactNode; markInUse?: boolean; appearance?: TerminalAppearance; onScreen?: boolean;
}) {
  const t = useT();
  const open = useIdeSidePanelStore((state) => state.open);
  const inUse = useIdeSidePanelStore((state) => state.inUse);
  const setInUse = useIdeSidePanelStore((state) => state.setInUse);
  const setOpen = useIdeSidePanelStore((state) => state.setOpen);
  const active = useIdeSidePanelStore((state) => state.active);
  const split = useIdeSidePanelStore((state) => state.split);
  const maximized = useIdeSidePanelStore((state) => state.maximized);
  const hasTerminals = useIdeSidePanelStore((state) => state.terminals.length > 0);
  // Ctrl+click on a path in any terminal opens it in the Explorer tab.
  useExplorerPathRouting();
  // A click on a pane in the grid counts as reviewing that agent.
  usePaneReviewTracking();
  const frame = useRef<HTMLDivElement>(null);
  const [frameWidth, setFrameWidth] = useState(0);

  useEffect(() => {
    const node = frame.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setFrameWidth(Math.round(entry.contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const max = Math.max(MIN_PX, frameWidth ? frameWidth - GRID_RESERVED_PX : UNMEASURED_MAX_PX);
  const pane = useResizablePane({
    storageKey: WIDTH_KEY,
    defaultSize: DEFAULT_PX,
    min: MIN_PX,
    max,
    axis: "x",
    // The panel sits on the right, so its grip is its LEFT edge.
    handle: "start",
    // Push the grip against the right edge to close the panel; it reopens at
    // the width it had before the drag.
    collapseBelow: COLLAPSE_BELOW_PX,
    onCollapse: () => setOpen(false),
  });
  // Past this point a release closes the panel: fade it as the hint.
  const closing = pane.isResizing && pane.size < COLLAPSE_BELOW_PX;
  // Keep a wider stored preference intact while the window is narrow.
  const width = Math.min(pane.size, max);

  // Bringing the office forward widens a narrow panel once; the user can drag
  // it back and it stays where they left it until the office is picked again.
  const officeInFront = open && (active === "office" || split === "office");
  const paneRef = useRef(pane);
  paneRef.current = pane;
  useEffect(() => {
    if (officeInFront && paneRef.current.size < OFFICE_MIN_PX) paneRef.current.resize(OFFICE_MIN_PX);
  }, [officeInFront]);
  // Same for a split: two tabs in a 340px panel would both be cramped.
  const splitShown = open && !!split;
  const maxRef = useRef(max);
  maxRef.current = max;
  useEffect(() => {
    const target = Math.min(SPLIT_MIN_PX, maxRef.current);
    if (splitShown && paneRef.current.size < target) paneRef.current.resize(target);
  }, [splitShown]);

  return (
    <div ref={frame} className="relative flex h-full min-h-0 w-full">
      {/* Hidden, not removed, under a maximized panel: the glass theme's panel is
          see-through, and the live terminals keep their size and sockets. */}
      <div data-testid="ide-side-panel-grid" className={cn("h-full min-h-0 min-w-0 flex-1", maximized && "invisible")}>{children}</div>
      {/* Maximized, the host keeps its width in the row so the terminals behind
          it never resize, and stops being the positioning box: the panel then
          anchors to the frame and covers the whole view. */}
      <div
        data-testid="ide-side-panel-host"
        className={cn(
          "h-full shrink-0",
          !maximized && "relative",
          !pane.isResizing && "transition-[width] duration-200 motion-reduce:transition-none",
        )}
        style={{ width: open ? width : 0 }}
        aria-hidden={!open}
      >
        {(open || hasTerminals) && (
          <>
            {open && !maximized && (
              <div className="group absolute inset-y-0 left-0 z-20 flex -translate-x-1/2">
                <PaneResizer
                  testId="ide-side-panel-resizer"
                  orientation="vertical"
                  active={pane.isResizing}
                  title={t("ide_side_panel.resize")}
                  onPointerDown={pane.startResize}
                  onDoubleClick={pane.reset}
                  // A start-edge grip: Left grows the panel, so the delta flips.
                  onNudge={(delta) => pane.nudge(-delta)}
                  valueNow={width}
                  valueMin={MIN_PX}
                  valueMax={max}
                  controls={SIDE_PANEL_ID}
                  className="h-full"
                  showLine={false}
                />
                <MoveHorizontal
                  aria-hidden
                  className={cn(
                    "pointer-events-none absolute left-1/2 top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-secondary p-0.5 text-foreground transition-opacity",
                    pane.isResizing ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100",
                  )}
                />
              </div>
            )}
            {/* Same element either way, so the live office scene is never remounted.
                A press anywhere in it (capture phase: the office canvas and the
                terminals in it stop their own events) makes it the area in use. */}
            <div hidden={!open} data-testid="ide-side-panel-body" data-closing={closing ? "true" : undefined}
              className={cn(maximized ? "absolute inset-0 z-30" : "relative h-full", closing && "opacity-40")}
              onPointerDownCapture={() => setInUse(true)}>
              <IdeSidePanel appearance={appearance} onScreen={onScreen} />
              {/* The "you are here" frame, drawn over everything in the panel so
                  no tab header or scene can cover part of it. */}
              {markInUse && inUse && (
                <div aria-hidden="true" data-testid="ide-side-panel-in-use"
                  className="pointer-events-none absolute inset-0 z-40 ring-2 ring-inset ring-accent" />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/**
 * The panel itself: tab header ("+" and maximize) over the active tab's content,
 * or the "Open a surface" launcher while no tab is open.
 * It opens and closes from the window caption (`IdeSidePanelToggle`) only;
 * a shut panel leaves no rail behind, so the grid or thread gets the full width.
 */
export function IdeSidePanel({ appearance, onScreen = true }: { appearance?: TerminalAppearance; onScreen?: boolean }) {
  const t = useT();
  const allTabs = useIdeSidePanelStore((state) => state.tabs);
  const storedActive = useIdeSidePanelStore((state) => state.active);
  const open = useIdeSidePanelStore((state) => state.open);
  const terminals = useIdeSidePanelStore((state) => state.terminals);
  const addTerminalTab = useIdeSidePanelStore((state) => state.addTerminalTab);
  const workspace = useIdeChatStore((state) => state.workspace);
  const tabs = allTabs.filter((id) => !id.startsWith("terminal:") || terminals.some((terminal) => terminal.id === id && terminal.workspaceId === workspace?.id));
  const active = tabs.includes(storedActive) ? storedActive : tabs[0];
  const terminalCount = terminals.filter((terminal) => terminal.workspaceId === workspace?.id).length;
  const select = useIdeSidePanelStore((state) => state.select);
  const openTab = useIdeSidePanelStore((state) => state.openTab);
  const closeTab = useIdeSidePanelStore((state) => state.closeTab);
  const maximized = useIdeSidePanelStore((state) => state.maximized);
  const setMaximized = useIdeSidePanelStore((state) => state.setMaximized);
  const storedSplit = useIdeSidePanelStore((state) => state.split);
  const splitRatio = useIdeSidePanelStore((state) => state.splitRatio);
  const focusedColumn = useIdeSidePanelStore((state) => state.focusedColumn);
  const setFocusedColumn = useIdeSidePanelStore((state) => state.setFocusedColumn);
  const setSplitRatio = useIdeSidePanelStore((state) => state.setSplitRatio);
  const splitWith = useIdeSidePanelStore((state) => state.splitWith);
  const toggleSplit = useIdeSidePanelStore((state) => state.toggleSplit);
  // A split onto a shell of another workspace shows this workspace's tab alone.
  const split = storedSplit && storedSplit !== active && tabs.includes(storedSplit) ? storedSplit : null;
  const content = useRef<HTMLDivElement>(null);
  const tabDrag = useTabDrag(content, split ? splitRatio : DEFAULT_SPLIT_RATIO, splitWith);
  const [resizingSplit, setResizingSplit] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  const current = sidePanelTab(active);
  const canAddTerminal = !!workspace && terminalCount < MAX_TERMINAL_TABS;
  const tabLabel = (id: SidePanelTabId) => {
    const terminal = terminals.find((entry) => entry.id === id);
    return terminal ? `${t("ide_side_panel.terminal_label")} ${terminal.number}` : t(sidePanelTab(id)?.labelKey ?? "");
  };
  /** Where a tab's content sits: the whole area, one of the two columns, or nowhere. */
  const columnOf = (id: SidePanelTabId): SidePanelColumn | null => (id === active ? 0 : id === split ? 1 : null);
  const percent = `${splitRatio * 100}%`;
  const columnStyle = (column: SidePanelColumn | null): CSSProperties | undefined => {
    if (column === null || !split) return undefined;
    return column === 0 ? { left: 0, width: `calc(${percent} - 1px)` } : { left: `calc(${percent} + 1px)`, right: 0 };
  };
  const startSplitResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    const box = content.current?.getBoundingClientRect();
    if (!box || event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setResizingSplit(true);
    const move = (e: PointerEvent) => setSplitRatio((e.clientX - box.left) / box.width);
    const end = () => {
      setResizingSplit(false);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  };
  const registryAction = (tab: (typeof SIDE_PANEL_TABS)[number]): SurfaceAction => ({
    id: tab.id, label: t(tab.labelKey), icon: tab.icon, shortcut: tab.shortcut, available: true,
    isOpen: tabs.includes(tab.id), run: () => openTab(tab.id),
  });
  // Launcher and "+" menu list the same surfaces: the browser, a plain
  // terminal, then every other registry tab.
  const [browserTab, ...otherTabs] = SIDE_PANEL_TABS;
  const actions: SurfaceAction[] = [
    registryAction(browserTab),
    {
      id: "terminal", label: t("ide_side_panel.terminal_label"), icon: SquareTerminal, shortcut: "T",
      available: canAddTerminal,
      reason: t(!workspace ? "ide_side_panel.terminal_workspace_required" : "ide_side_panel.terminal_limit"),
      run: () => { if (workspace) addTerminalTab(workspace.id, workspace.name); },
    },
    ...otherTabs.map(registryAction),
  ];
  const onMenuKey = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!menuOpen) return;
    const action = surfaceActionForKey(actions, event.nativeEvent);
    if (!action) return;
    event.preventDefault();
    setMenuOpen(false);
    action.run();
  };

  useEffect(() => {
    if (!menuOpen) return;
    const onPointer = (event: MouseEvent) => {
      if (menu.current && !menu.current.contains(event.target as Node)) setMenuOpen(false);
    };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setMenuOpen(false); };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  return (
    <aside
      id={SIDE_PANEL_ID}
      data-testid="ide-side-panel"
      aria-label={t("ide_side_panel.aria")}
      className="flex h-full min-h-0 flex-col overflow-hidden border-l border-border bg-card/40"
    >
      <div className="flex h-11 shrink-0 items-center gap-1 border-b border-border/60 px-2">
        <div role="tablist" aria-label={t("ide_side_panel.tabs_aria")} className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {tabs.map((id) => {
            const tab = sidePanelTab(id);
            const terminal = terminals.find((entry) => entry.id === id);
            if (!tab && !terminal) return null;
            const label = tabLabel(id);
            const Icon = tab?.icon ?? SquareTerminal;
            const column = columnOf(id);
            const selected = column !== null;
            // Split: both visible tabs are lit; the one a click would replace is lit fully.
            const focused = selected && (!split || column === focusedColumn);
            return (
              <div
                key={id}
                data-column={split && selected ? column : undefined}
                className={cn(
                  "group/tab flex h-8 min-w-0 shrink-0 touch-none select-none items-center gap-1 rounded-lg pl-2.5 pr-1 text-sm transition-colors",
                  focused ? "bg-secondary text-foreground"
                    : selected ? "bg-secondary/50 text-foreground"
                      : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                  tabDrag.dragging === id && "opacity-50",
                )}
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  aria-controls={`${SIDE_PANEL_ID}-content`}
                  data-testid={`ide-side-panel-tab-${id}`}
                  title={tabs.length > 1 ? t("ide_side_panel.drag_hint") : undefined}
                  onPointerDown={(event) => tabDrag.start(event, id)}
                  onClick={() => { if (!tabDrag.consumeClick()) select(id); }}
                  className="flex min-w-0 items-center gap-1.5 focus-visible:outline-none"
                >
                  <Icon className="h-4 w-4 shrink-0" aria-hidden />
                  <span className="truncate font-medium">{label}</span>
                </button>
                <button
                  type="button"
                  aria-label={`${t("ide_side_panel.close_tab")}: ${label}`}
                  title={t("ide_side_panel.close_tab")}
                  data-testid={`ide-side-panel-close-${id}`}
                  onClick={() => closeTab(id)}
                  className="inline-flex h-5 w-5 items-center justify-center rounded text-muted-foreground hover:bg-background/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <X className="h-3.5 w-3.5" aria-hidden />
                </button>
              </div>
            );
          })}
        </div>
        <div ref={menu} className="relative" onKeyDown={onMenuKey}>
          <button
            type="button"
            data-testid="ide-side-panel-add"
            aria-label={t("ide_side_panel.add_tab")}
            title={t("ide_side_panel.add_tab")}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((value) => !value)}
            className={HEADER_BTN}
          >
            <Plus className="h-4 w-4" aria-hidden />
          </button>
          {/* Every surface the panel can hold, always, with its letter: an open
              tab is ticked and picking it brings it forward, a closed one is added. */}
          {menuOpen && (
            <div role="menu" aria-label={t("ide_side_panel.add_tab")} className="absolute right-0 top-full z-30 mt-1 min-w-52 rounded-lg border border-border bg-popover p-1 shadow-float">
              {actions.map((action) => (
                <button
                  key={action.id}
                  type="button"
                  role={action.id === "terminal" ? "menuitem" : "menuitemcheckbox"}
                  aria-checked={action.id === "terminal" ? undefined : !!action.isOpen}
                  aria-keyshortcuts={action.shortcut}
                  data-testid={`ide-side-panel-add-${action.id}`}
                  disabled={!action.available}
                  title={action.available ? undefined : action.reason}
                  onClick={() => { action.run(); setMenuOpen(false); }}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-foreground hover:bg-secondary disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent"
                >
                  <action.icon className="h-4 w-4 text-muted-foreground" aria-hidden />
                  <span className="flex-1">{action.label}</span>
                  {action.isOpen && <Check className="h-3.5 w-3.5 text-accent" aria-hidden />}
                  <SurfaceKbd>{action.shortcut}</SurfaceKbd>
                </button>
              ))}
            </div>
          )}
        </div>
        <button
          type="button"
          data-testid="ide-side-panel-split"
          aria-label={t(split ? "ide_side_panel.unsplit" : "ide_side_panel.split")}
          title={t(split ? "ide_side_panel.unsplit" : tabs.length > 1 ? "ide_side_panel.split" : "ide_side_panel.split_needs_two")}
          aria-pressed={!!split}
          disabled={!split && tabs.length < 2}
          onClick={toggleSplit}
          className={cn(HEADER_BTN, split && "bg-secondary text-foreground")}
        >
          <Columns2 className="h-4 w-4" aria-hidden />
        </button>
        <button
          type="button"
          data-testid="ide-side-panel-maximize"
          aria-label={t(maximized ? "ide_side_panel.restore" : "ide_side_panel.maximize")}
          title={t(maximized ? "ide_side_panel.restore" : "ide_side_panel.maximize")}
          aria-pressed={maximized}
          onClick={() => setMaximized(!maximized)}
          className={HEADER_BTN}
        >
          {maximized ? <Minimize2 className="h-4 w-4" aria-hidden /> : <Maximize2 className="h-4 w-4" aria-hidden />}
        </button>
      </div>
      {/* Keyed by tab: Changes and Folder share one component and must not share its state. */}
      {/* Split, every tab sits in the column it was put in; the same element moves
          between whole area and column, so a browser page or a chat never reloads. */}
      <div ref={content} id={`${SIDE_PANEL_ID}-content`} role="tabpanel" data-testid="ide-side-panel-content"
        data-split={split ? "true" : undefined}
        className={cn("relative min-h-0 flex-1", resizingSplit && "cursor-col-resize select-none")}
        onPointerDownCapture={(event) => {
          const box = content.current?.getBoundingClientRect();
          if (!split || !box || !box.width) return;
          setFocusedColumn((event.clientX - box.left) / box.width < splitRatio ? 0 : 1);
        }}>
        {open && tabs.length === 0 && <SurfaceLauncher actions={actions} keysEnabled={onScreen} />}
        {open && current && !current.keepAlive && (
          <div key={active} data-testid={`ide-side-panel-column-${active}`} className={split ? "absolute inset-y-0 min-h-0" : "h-full min-h-0"}
            style={columnStyle(0)}>{current.render()}</div>
        )}
        {open && split && sidePanelTab(split) && !sidePanelTab(split)!.keepAlive && (
          <div key={split} data-testid={`ide-side-panel-column-${split}`} className="absolute inset-y-0 min-h-0" style={columnStyle(1)}>
            {sidePanelTab(split)!.render()}
          </div>
        )}
        {SIDE_PANEL_TABS.filter((tab) => tab.keepAlive && tabs.includes(tab.id)).map((tab) => (
          <div key={tab.id} hidden={!open || columnOf(tab.id) === null} data-testid={`ide-side-panel-column-${tab.id}`}
            className={split ? "absolute inset-y-0" : "absolute inset-0"} style={columnStyle(columnOf(tab.id))}>{tab.render()}</div>
        ))}
        {terminals.map((terminal) => <div key={terminal.id} hidden={!open || columnOf(terminal.id) === null}
          className={split ? "absolute inset-y-0" : "absolute inset-0"} style={columnStyle(columnOf(terminal.id))}
          data-testid={`ide-side-panel-terminal-${terminal.id}`}>
          {/* A terminal opened on a folder of the tree starts there; `folder` only
              counts when no workspace id is named. */}
          <WorkspaceTerminal paneKey={terminal.id} agentName="shell"
            workspaceId={terminal.folder ? undefined : terminal.workspaceId} folder={terminal.folder}
            title={`${t("ide_side_panel.terminal_label")} ${terminal.number} · ${terminal.workspaceName}`}
            active={onScreen && open && columnOf(terminal.id) !== null} appearance={appearance} />
        </div>)}
        {open && split && (
          <>
            {/* Which column a tab click fills: a thin line over the focused one. */}
            <div aria-hidden className="pointer-events-none absolute top-0 z-10 h-0.5 bg-accent/70" style={columnStyle(focusedColumn)} />
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label={t("ide_side_panel.split_resize")}
              aria-valuenow={Math.round(splitRatio * 100)}
              aria-valuemin={20}
              aria-valuemax={80}
              tabIndex={0}
              title={t("ide_side_panel.split_resize")}
              data-testid="ide-side-panel-split-resizer"
              onPointerDown={startSplitResize}
              onDoubleClick={() => setSplitRatio(DEFAULT_SPLIT_RATIO)}
              onKeyDown={(event) => {
                if (event.key === "ArrowLeft") setSplitRatio(splitRatio - 0.05);
                else if (event.key === "ArrowRight") setSplitRatio(splitRatio + 0.05);
                else return;
                event.preventDefault();
              }}
              className="group absolute inset-y-0 z-20 flex w-3 -translate-x-1/2 cursor-col-resize justify-center focus-visible:outline-none"
              style={{ left: percent }}
            >
              <div className={cn("h-full w-px bg-border transition-colors group-hover:bg-accent group-focus-visible:bg-accent",
                resizingSplit && "bg-accent")} />
            </div>
          </>
        )}
        {tabDrag.dragging && <TabDropZones column={tabDrag.target} ratio={split ? splitRatio : DEFAULT_SPLIT_RATIO} />}
      </div>
      {tabDrag.dragging && tabDrag.pointer && (
        <div aria-hidden className="pointer-events-none fixed z-50 rounded-md border border-border bg-popover px-2 py-1 text-xs font-medium text-foreground shadow-float"
          style={{ left: tabDrag.pointer.x + 12, top: tabDrag.pointer.y + 12 }}>
          {tabLabel(tabDrag.dragging)}
        </div>
      )}
    </aside>
  );
}

/**
 * The two halves a dragged tab can land on. Marked so the native browser window
 * steps aside while they show: it is drawn above the page and would hide them.
 */
function TabDropZones({ column, ratio }: { column: SidePanelColumn | null; ratio: number }) {
  const t = useT();
  const zone = (which: SidePanelColumn) => (
    <div
      data-testid={`ide-side-panel-drop-${which === 0 ? "left" : "right"}`}
      data-over={column === which ? "true" : undefined}
      className={cn(
        "absolute inset-y-0 flex items-center justify-center p-2 transition-colors",
        column === which ? "bg-accent/15" : "bg-background/40",
      )}
      style={which === 0 ? { left: 0, width: `${ratio * 100}%` } : { left: `${ratio * 100}%`, right: 0 }}
    >
      <div className={cn(
        "flex h-full w-full items-center justify-center rounded-lg border-2 border-dashed text-sm font-medium transition-colors",
        column === which ? "border-accent text-foreground" : "border-border text-muted-foreground",
      )}>
        {t(which === 0 ? "ide_side_panel.drop_left" : "ide_side_panel.drop_right")}
      </div>
    </div>
  );
  return (
    <div data-hides-native-browser="" data-testid="ide-side-panel-drop-zones" className="pointer-events-none absolute inset-0 z-30 backdrop-blur-[1px]">
      {zone(0)}
      {zone(1)}
    </div>
  );
}

/**
 * Drag a tab out of the strip onto the left or right half of the panel to see
 * it beside another one. Pointer events rather than HTML drag and drop: those
 * would arm the file drop targets of the terminals, and a release outside the
 * window would never be heard.
 */
function useTabDrag(
  content: RefObject<HTMLDivElement | null>,
  ratio: number,
  onDrop: (id: SidePanelTabId, column: SidePanelColumn) => void,
) {
  const [dragging, setDragging] = useState<SidePanelTabId | null>(null);
  const [target, setTarget] = useState<SidePanelColumn | null>(null);
  const [pointer, setPointer] = useState<{ x: number; y: number } | null>(null);
  const swallowClick = useRef(false);
  const cleanupRef = useRef<(() => void) | null>(null);
  const ratioRef = useRef(ratio);
  ratioRef.current = ratio;
  const dropRef = useRef(onDrop);
  dropRef.current = onDrop;

  useEffect(() => () => cleanupRef.current?.(), []);

  const start = (event: ReactPointerEvent<HTMLElement>, id: SidePanelTabId) => {
    if (event.button !== 0) return;
    cleanupRef.current?.();
    const origin = { x: event.clientX, y: event.clientY };
    let active = false;
    let over: SidePanelColumn | null = null;
    const columnAt = (x: number, y: number): SidePanelColumn | null => {
      const box = content.current?.getBoundingClientRect();
      if (!box || x < box.left || x > box.right || y < box.top || y > box.bottom || !box.width) return null;
      return (x - box.left) / box.width < ratioRef.current ? 0 : 1;
    };
    const move = (e: PointerEvent) => {
      if (!active) {
        if (Math.hypot(e.clientX - origin.x, e.clientY - origin.y) < TAB_DRAG_SLOP_PX) return;
        active = true;
        setDragging(id);
      }
      over = columnAt(e.clientX, e.clientY);
      setTarget(over);
      setPointer({ x: e.clientX, y: e.clientY });
    };
    const finish = (drop: boolean) => {
      cleanupRef.current?.();
      if (!active) return;
      swallowClick.current = true;
      // The click that follows a drag must not also select the tab.
      window.setTimeout(() => { swallowClick.current = false; }, 0);
      setDragging(null);
      setTarget(null);
      setPointer(null);
      if (drop && over !== null) dropRef.current(id, over);
    };
    const up = () => finish(true);
    const cancel = () => finish(false);
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") finish(false); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
    window.addEventListener("keydown", key);
    cleanupRef.current = () => {
      cleanupRef.current = null;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);
      window.removeEventListener("keydown", key);
    };
  };

  return {
    dragging,
    target,
    pointer,
    start,
    /** True once for the click a finished drag leaves behind. */
    consumeClick: () => {
      const swallow = swallowClick.current;
      swallowClick.current = false;
      return swallow;
    },
  };
}
