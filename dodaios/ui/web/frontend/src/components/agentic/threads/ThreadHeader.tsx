import { useMemo, useRef, useState, type ReactNode } from "react";
import { Archive, Check, FileDiff, FolderGit2, GitBranch, GitFork, Maximize2, Minimize2, MoreHorizontal, Pencil, Plus, SquarePlus, X } from "lucide-react";
import { AgentMark } from "@/components/agentic/AgentMark";
import { forkAgentChatSession, patchAgentChatSession, type AgentChatSession } from "@/lib/agentChatApi";
import { cn } from "@/lib/utils";
import { fill, loadLocaleChunk, useT } from "@/i18n";
import { useEventStore } from "@/store/events";
import { useIdeSidePanelStore } from "@/store/ideSidePanel";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { useNavSidebarStore } from "@/store/navSidebar";
import { useThemeValue } from "@/hooks/useTheme";
import { DoneGateLabel } from "../PaneDoneGateBadge";
import { GitHubStatusBadge } from "../SessionGitHubBadge";
import { usePaneDoneGate } from "../usePaneDoneGate";
import { THREAD_ENTRY, useThreadGitHub } from "../useSessionGitHub";
import { PaneChangesDialog } from "../PaneChangesDialog";
import { prefetchPaneChanges } from "../paneChangesApi";
import { ThreadMenuItem, ThreadMenuSeparator, ThreadPopover } from "./ThreadPopover";
import { threadTitle, useThreadChatStore } from "./threadModel";

const ACTION = cn(
  "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors",
  "hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
  "disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent",
);

function Action({ label, onClick, disabled, pressed, testId, onPointerEnter, children }: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  pressed?: boolean;
  testId: string;
  onPointerEnter?: () => void;
  children: ReactNode;
}) {
  return <button type="button" aria-label={label} title={label} onClick={onClick} disabled={disabled} aria-pressed={pressed}
    data-testid={testId} onPointerEnter={onPointerEnter} className={cn(ACTION, pressed && "bg-secondary text-foreground")}>
    {children}
  </button>;
}

/**
 * The open thread's title bar: the same controls a grid pane's header has,
 * for a conversation instead of a terminal. Review the changes in the
 * thread's folder, show them in the Git tab, more actions, make room by
 * folding the sidebar, start another thread, and close this one (it moves to
 * the archive, where the sidebar can bring it back).
 */
export function ThreadHeader({ session, projectId, folder, workspaceId }: {
  session: AgentChatSession;
  projectId: string;
  /** Where the thread's agent works: the project's checkout or the thread's worktree. */
  folder: string;
  /** The IDE's active workspace, which the Git tab shows. */
  workspaceId: string | null;
}) {
  const t = useT();
  const pushToast = useEventStore((state) => state.pushToast);
  const catalog = useThreadChatStore((state) => state.catalog);
  // The thread list carries the name the coding CLI gave the conversation
  // (or the topic title); the open session alone may still hold the first message.
  const listed = useThreadChatStore((state) => state.sessions.find((row) => row.session_id === session.session_id));
  const appearance = useThemeValue();
  const github = useThreadGitHub(session.session_id);
  const gate = usePaneDoneGate(`thread:${session.session_id}`, THREAD_ENTRY);
  const navCollapsed = useNavSidebarStore((state) => state.collapsed);
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [changesOpen, setChangesOpen] = useState(false);
  const moreRef = useRef<HTMLButtonElement | null>(null);
  const title = threadTitle(listed ?? session);
  const mark = useMemo(() => {
    const provider = catalog?.providers.find((row) => row.id === session.provider);
    return provider?.agent ? { agent: provider.agent, label: provider.label } : null;
  }, [catalog, session.provider]);
  // Archiving a thread mid-turn or mid-approval would hide work that needs the person.
  const busy = Boolean((listed ?? session).running) || Boolean((listed ?? session).pending_approvals?.length);
  const target = { workspaceId: workspaceId ?? "", pane: "", folder };

  const rename = async (wanted: string) => {
    const clean = wanted.trim();
    setRenaming(null);
    if (!clean || clean === title) return;
    try {
      await patchAgentChatSession(session.session_id, { title: clean });
      await useThreadChatStore.getState().loadSessions();
    } catch (error) {
      pushToast("error", error instanceof Error ? error.message : String(error));
    }
  };
  const fork = async (worktree: boolean) => {
    try {
      const copy = await forkAgentChatSession(session.session_id, { worktree, title: fill(t("ide_threads.fork_title"), { thread: title }) });
      await useThreadChatStore.getState().loadSessions();
      useIdeThreadsStore.getState().openThread(copy.session_id, projectId);
    } catch (error) {
      pushToast("error", error instanceof Error ? error.message : String(error));
    }
  };
  const reviewChanges = () => setChangesOpen(true);
  const prefetchReview = () => {
    void loadLocaleChunk("pane_review");
    if (folder) prefetchPaneChanges(target);
  };
  const showInGit = () => useIdeSidePanelStore.getState().openTab("git");
  const newThread = () => useIdeThreadsStore.getState().newThread(projectId);
  const close = () => useIdeThreadsStore.getState().archiveThread(session.session_id);
  const toggleRoom = () => useNavSidebarStore.getState().setCollapsed(!navCollapsed);

  return <>
    <header data-testid="thread-header" aria-label={fill(t("ide_threads.header.label"), { thread: title })}
      className="flex h-9 shrink-0 select-none items-center gap-1 border-b border-border pl-3 pr-1.5">
      {renaming === null
        ? <div className="flex min-w-0 flex-1 items-center gap-2" onDoubleClick={() => setRenaming(title)}>
          {mark && <AgentMark agent={mark.agent} label={mark.label} variant="plain" size="sm" />}
          <span data-testid="thread-header-title" className="truncate text-sm font-medium text-foreground" title={title}>{title}</span>
        </div>
        : <form className="flex min-w-0 flex-1 items-center gap-1" onSubmit={(event) => { event.preventDefault(); void rename(renaming); }}>
          <input autoFocus aria-label={fill(t("ide_projects.rename_named"), { target: title })} value={renaming} maxLength={120}
            onChange={(event) => setRenaming(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); setRenaming(null); } }}
            onBlur={() => void rename(renaming)}
            className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-0.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
          <button type="submit" aria-label={t("ide_threads.save_name")} className="rounded p-1 text-muted-foreground hover:text-foreground"><Check className="h-4 w-4" /></button>
        </form>}
      <DoneGateLabel gate={gate} appearance={appearance} name={title} />
      <GitHubStatusBadge status={github.status} pending={github.pending} appearance={appearance} />
      <div className="flex shrink-0 items-center gap-0.5">
        <Action label={t("ide_threads.header.review_changes")} onClick={reviewChanges} disabled={!folder}
          testId="thread-header-review-changes" onPointerEnter={prefetchReview}>
          <FileDiff className="h-[15px] w-[15px]" />
        </Action>
        <Action label={t("ide_threads.header.show_in_git")} onClick={showInGit} testId="thread-header-show-in-git">
          <FolderGit2 className="h-[15px] w-[15px]" />
        </Action>
        <button ref={moreRef} type="button" aria-label={fill(t("ide_threads.header.more"), { thread: title })} title={fill(t("ide_threads.header.more"), { thread: title })}
          aria-haspopup="menu" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)} data-testid="thread-header-more" className={ACTION}>
          <MoreHorizontal className="h-4 w-4" />
        </button>
        <Action label={t(navCollapsed ? "ide_threads.header.restore" : "ide_threads.header.maximize")} onClick={toggleRoom}
          pressed={navCollapsed} testId="thread-header-maximize">
          {navCollapsed ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
        </Action>
        <Action label={t("ide_threads.new_thread_here")} onClick={newThread} testId="thread-header-new">
          <Plus className="h-4 w-4" />
        </Action>
        <Action label={t("ide_threads.header.close")} onClick={close} disabled={busy} testId="thread-header-close">
          <X className="h-4 w-4" />
        </Action>
      </div>
    </header>
    <ThreadPopover anchor={moreRef} open={menuOpen} onClose={() => setMenuOpen(false)} align="end"
      label={fill(t("ide_threads.header.more"), { thread: title })} width={240}>
      <div role="menu">
        <ThreadMenuItem icon={<Pencil className="h-3.5 w-3.5" />} label={t("ide_threads.rename")}
          onSelect={() => { setMenuOpen(false); setRenaming(title); }} />
        <ThreadMenuItem icon={<SquarePlus className="h-3.5 w-3.5" />} label={t("ide_threads.new_thread_here")}
          onSelect={() => { setMenuOpen(false); newThread(); }} />
        <ThreadMenuItem icon={<GitFork className="h-3.5 w-3.5" />} label={t("ide_threads.fork")} disabled={busy}
          onSelect={() => { setMenuOpen(false); void fork(false); }} />
        <ThreadMenuItem icon={<GitBranch className="h-3.5 w-3.5" />} label={t("ide_threads.fork_worktree")} disabled={busy || !folder}
          onSelect={() => { setMenuOpen(false); void fork(true); }} />
        <ThreadMenuSeparator />
        <ThreadMenuItem icon={<FileDiff className="h-3.5 w-3.5" />} label={t("ide_threads.header.review_changes")} disabled={!folder}
          onSelect={() => { setMenuOpen(false); reviewChanges(); }} />
        <ThreadMenuItem icon={<FolderGit2 className="h-3.5 w-3.5" />} label={t("ide_threads.header.show_in_git")}
          onSelect={() => { setMenuOpen(false); showInGit(); }} />
        <ThreadMenuSeparator />
        <ThreadMenuItem icon={<Archive className="h-3.5 w-3.5" />} label={t("ide_threads.archive")} disabled={busy}
          onSelect={() => { setMenuOpen(false); close(); }} />
      </div>
    </ThreadPopover>
    {folder && <PaneChangesDialog open={changesOpen} onOpenChange={setChangesOpen} workspaceId={workspaceId ?? ""} pane=""
      folder={folder} title={title} />}
  </>;
}

