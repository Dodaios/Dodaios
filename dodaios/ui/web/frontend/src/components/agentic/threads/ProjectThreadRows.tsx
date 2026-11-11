import { useEffect, useMemo } from "react";
import { Loader2, MessageSquare, SquarePen } from "lucide-react";
import type { IdeProject } from "@/lib/agenticIdeApi";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { threadTitle, threadsByProject, useThreadChatStore } from "./threadModel";

/** How many of a folder's threads the grid's list names before "Show more". */
const SHOWN = 5;
const POLL_MS = 8000;
const ROW =
  "flex min-h-7 w-full min-w-0 items-center gap-2 rounded-md pl-[30px] pr-2 text-left text-[13px] transition-colors " +
  "hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** Load the coding threads and keep them fresh while a list of them is on screen. */
export function useThreadSessionsPoll(): void {
  useEffect(() => {
    void useThreadChatStore.getState().loadSessions();
    const timer = window.setInterval(() => { void useThreadChatStore.getState().loadSessions(); }, POLL_MS);
    return () => window.clearInterval(timer);
  }, []);
}

/**
 * A folder's newest threads, inside the terminal grid's folder list.
 *
 * The grid's list and the thread list name the same folders; each also names
 * what the other one holds, so there is one list to move through and no
 * separate switch between the two faces. A thread row turns the IDE to its
 * thread face and opens that thread. Renaming, archiving and ordering stay
 * with the thread list itself.
 */
export function ProjectThreadRows({ project, projects }: { project: IdeProject; projects: readonly IdeProject[] }) {
  const t = useT();
  const sessions = useThreadChatStore((state) => state.sessions);
  const projectOf = useIdeThreadsStore((state) => state.projectOf);
  const archived = useIdeThreadsStore((state) => state.archived);
  const threads = useMemo(
    () => (threadsByProject(sessions.filter((session) => !session.team_id), projects, projectOf).get(project.id) ?? [])
      .filter((thread) => !(thread.session_id in archived)),
    [sessions, projects, projectOf, archived, project.id],
  );

  const show = (sessionId: string | null | undefined) => {
    const store = useIdeThreadsStore.getState();
    store.setLayout("threads");
    if (sessionId) store.openThread(sessionId, project.id);
    else if (sessionId === null) store.newThread(project.id);
  };

  return (
    <div className="mb-1 flex flex-col gap-px" data-testid={`ide-project-threads-${project.id}`}>
      {threads.slice(0, SHOWN).map((thread) => (
        <button key={thread.session_id} type="button" data-testid={`ide-project-thread-${thread.session_id}`}
          onClick={() => show(thread.session_id)} className={cn(ROW, "text-foreground-secondary")}>
          <MessageSquare aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={1.75} />
          <span className="min-w-0 flex-1 truncate">{threadTitle(thread)}</span>
          {thread.running && <Loader2 aria-hidden className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" />}
        </button>
      ))}
      {threads.length > SHOWN && (
        <button type="button" data-testid={`ide-project-threads-more-${project.id}`}
          onClick={() => show(undefined)} className={cn(ROW, "text-muted-foreground")}>
          {fill(t("ide_threads.show_more"), { count: threads.length - SHOWN })}
        </button>
      )}
      <button type="button" data-testid={`ide-project-thread-new-${project.id}`}
        onClick={() => show(null)} className={cn(ROW, "text-muted-foreground")}>
        <SquarePen aria-hidden className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
        <span className="truncate">{t("ide_threads.new_thread")}</span>
      </button>
    </div>
  );
}
