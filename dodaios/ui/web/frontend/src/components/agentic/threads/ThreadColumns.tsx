import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { X } from "lucide-react";
import { fill, useT } from "@/i18n";
import { useTeamThreads } from "@/lib/teamThreadsApi";
import { cn } from "@/lib/utils";
import { createAgentChatStore } from "@/store/agentChat";
import { MAX_THREAD_COLUMNS, threadColumns, useIdeThreadsStore, type SplitThread, type ThreadColumn } from "@/store/ideThreads";
import { ThreadView } from "./ThreadView";
import {
  THREAD_DRAG_MIME, THREAD_PROJECT_DRAG_MIME, ThreadChatContext, draggedThread, setDraggedThread, threadTitle, useThreadChatStore,
} from "./threadModel";

/** Where a dragged thread would land: over which column, and on which side of it. */
interface DropSpot {
  cell: number;
  side: "left" | "right" | "all";
}

/**
 * The thread layout's columns. The main one shows what the sidebar picked; a
 * thread dragged from the sidebar onto it opens in its own column next to it,
 * left or right of the column it is dropped on. Each side column has its own
 * chat store, so every column holds its own live conversation and composer.
 */
export function ThreadColumns({ onScreen }: { onScreen: boolean }) {
  const t = useT();
  const split = useIdeThreadsStore((state) => state.split);
  const mainAt = useIdeThreadsStore((state) => state.mainAt);
  const selection = useIdeThreadsStore((state) => state.selection);
  const placeColumn = useIdeThreadsStore((state) => state.placeColumn);
  const columns = useMemo(() => threadColumns(split, mainAt), [split, mainAt]);
  const [spot, setSpot] = useState<DropSpot | null>(null);
  const box = useRef<HTMLDivElement | null>(null);
  const multi = columns.length > 1;

  const spotFor = (event: DragEvent<HTMLDivElement>): DropSpot | null => {
    const dragged = draggedThread();
    // The main column's own thread is on screen already.
    if (dragged !== null && dragged === selection.sessionId) return null;
    const cells = Array.from(box.current?.querySelectorAll<HTMLElement>(":scope > [data-thread-column]") ?? []);
    const cell = cells.findIndex((element) => {
      const rect = element.getBoundingClientRect();
      return event.clientX >= rect.left && event.clientX < rect.right;
    });
    if (cell < 0) return null;
    const moving = dragged !== null && split.some((thread) => thread.sessionId === dragged);
    // Every column taken: a new thread replaces the one it is dropped on.
    if (!moving && columns.length >= MAX_THREAD_COLUMNS) return { cell, side: "all" };
    const rect = cells[cell].getBoundingClientRect();
    return { cell, side: event.clientX < rect.left + rect.width / 2 ? "left" : "right" };
  };

  const isThreadDrag = (event: DragEvent<HTMLDivElement>) => event.dataTransfer.types.includes(THREAD_DRAG_MIME);

  return <div ref={box} className="flex h-full min-h-0 overflow-x-auto" data-testid="thread-columns"
    // Capture phase: the composer below takes dropped files, and must not see a thread.
    onDragOverCapture={(event) => {
      if (!isThreadDrag(event)) return;
      event.preventDefault();
      event.stopPropagation();
      const next = spotFor(event);
      event.dataTransfer.dropEffect = next ? "move" : "none";
      setSpot((current) => (current?.cell === next?.cell && current?.side === next?.side ? current : next));
    }}
    onDragLeave={(event) => {
      const next = event.relatedTarget as Node | null;
      if (next && event.currentTarget.contains(next)) return;
      setSpot(null);
    }}
    onDropCapture={(event) => {
      if (!isThreadDrag(event)) return;
      event.preventDefault();
      event.stopPropagation();
      const at = spotFor(event);
      setSpot(null);
      setDraggedThread(null);
      const sessionId = event.dataTransfer.getData(THREAD_DRAG_MIME);
      if (!at || !sessionId) return;
      const projectId = event.dataTransfer.getData(THREAD_PROJECT_DRAG_MIME)
        || split.find((thread) => thread.sessionId === sessionId)?.projectId || selection.projectId;
      placeColumn({ sessionId, projectId }, at.side === "right" ? at.cell + 1 : at.cell, at.side === "all");
    }}>
    {columns.map((column, index) => <div key={column?.sessionId ?? "main"} data-thread-column
      data-testid={column ? `thread-column-${column.sessionId}` : "thread-column-main"}
      className={cn("relative flex h-full min-w-[300px] flex-1 basis-0 flex-col", index > 0 && "border-l border-border")}>
      {multi && <ColumnHeader column={column} />}
      <div className="min-h-0 flex-1">
        {column ? <SideColumn thread={column} onScreen={onScreen} /> : <ThreadView onScreen={onScreen} />}
      </div>
      {spot?.cell === index && <div aria-hidden className={cn(
        "pointer-events-none absolute inset-y-1 z-30 flex items-center justify-center rounded-lg border-2 border-primary/60 bg-primary/10",
        spot.side === "left" && "left-1 w-1/2",
        spot.side === "right" && "right-1 w-1/2",
        spot.side === "all" && "inset-x-1",
      )}>
        <span className="rounded-md bg-background/90 px-2 py-1 text-xs text-foreground shadow-sm">
          {t(spot.side === "all" ? "ide_threads.drop_replace" : "ide_threads.drop_side_by_side")}
        </span>
      </div>}
    </div>)}
  </div>;
}

/** A column's name and its close button, shown while more than one column is open. */
function ColumnHeader({ column }: { column: ThreadColumn }) {
  const t = useT();
  const selection = useIdeThreadsStore((state) => state.selection);
  const sessionId = column ? column.sessionId : selection.sessionId;
  const session = useThreadChatStore((state) => (sessionId ? state.sessions.find((row) => row.session_id === sessionId) : undefined));
  const teamTitle = useTeamThreads(Boolean(selection.team) && !column).data?.find((row) => row.team_id === selection.team)?.title;
  const title = selection.team && !column ? teamTitle || t("team_threads.new") : threadTitle(session);
  const close = () => {
    const store = useIdeThreadsStore.getState();
    if (column) store.closeColumn(column.sessionId);
    else store.closeMainColumn();
  };
  return <div className="flex h-9 shrink-0 items-center gap-1 border-b border-border pl-3 pr-1"
    // A side column's header drags it to another place among the columns.
    draggable={Boolean(column)}
    onDragStart={(event) => {
      if (!column) return;
      event.dataTransfer.setData(THREAD_DRAG_MIME, column.sessionId);
      event.dataTransfer.setData(THREAD_PROJECT_DRAG_MIME, column.projectId);
      event.dataTransfer.effectAllowed = "move";
      setDraggedThread(column.sessionId);
    }}
    onDragEnd={() => setDraggedThread(null)}>
    <span className={cn("min-w-0 flex-1 truncate text-sm", column ? "cursor-grab text-muted-foreground" : "text-foreground")} title={title}>{title}</span>
    <button type="button" onClick={close} aria-label={fill(t("ide_threads.close_column"), { target: title })} title={t("common.close")}
      data-testid={column ? `thread-column-close-${column.sessionId}` : "thread-column-close-main"}
      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <X className="h-3.5 w-3.5" />
    </button>
  </div>;
}

/** A side column: its own chat store, so its conversation runs next to the main one's. */
function SideColumn({ thread, onScreen }: { thread: SplitThread; onScreen: boolean }) {
  const [store] = useState(() => {
    const created = createAgentChatStore("agent", "threads-side");
    // The thread list paints the title and agent at once, before the socket's first frame.
    created.setState({ sessions: useThreadChatStore.getState().sessions, catalog: useThreadChatStore.getState().catalog });
    return created;
  });
  useEffect(() => {
    // Back after a remount (StrictMode runs effects twice): the socket closed below opens again.
    const state = store.getState();
    if (state.activeSessionId && state.socketState === "idle") state.openSession(state.activeSessionId);
    return () => store.getState().disconnect();
  }, [store]);
  return <ThreadChatContext.Provider value={store}>
    <ThreadView onScreen={onScreen} column={thread} />
  </ThreadChatContext.Provider>;
}
