import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Download, Folder, FolderGit2, FolderPlus, Github, Loader2, Lock } from "lucide-react";
import { fetchIdeProjects, type IdeProject } from "@/lib/agenticIdeApi";
import { openProject } from "@/lib/chatLibraryApi";
import { cloneGitHubRepo, fetchLinkedRepos, type GitRepoInfo } from "@/lib/gitApi";
import { fetchGitHubRepos, type GitHubRepoList } from "@/components/agentic/sidePanel/git/gitOverviewApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { useIdeProjectsStore } from "@/store/ideProjects";
import { fill, useT } from "@/i18n";
import { ThreadMenuHeading, ThreadMenuItem, ThreadMenuSearch, ThreadMenuSeparator, ThreadPopover } from "./ThreadPopover";
import { folderLabel } from "./threadModel";

/** GitHub repositories listed before the person types: the newest pushes. */
const REPO_ROWS = 12;

/** What the chip says: the folder's own name, with the worktree's when the thread runs in one. */
export function folderChipLabel(folder: string, project: IdeProject | null, info: GitRepoInfo | null): string {
  if (!info?.is_worktree) return project && samePath(project.path, folder) ? project.name : folderLabel(folder);
  const main = project?.name ?? folderLabel(info.main_root || folder);
  return `${main} · ${folderLabel(folder)}`;
}

function samePath(a: string, b: string): boolean {
  const clean = (path: string) => path.replace(/[\\/]+$/, "").replace(/\\/g, "/").toLowerCase();
  return clean(a) === clean(b);
}

/**
 * The folder a thread works in. A running thread names it; a new thread picks
 * it — one of the connected folders, or a GitHub repository, which is
 * downloaded once and connected. The pick moves the draft to that project, so
 * the sidebar shows the new thread under it.
 */
export function ThreadFolderChip({
  folder,
  project,
  projects,
  info,
  draft,
  onProject,
  onConnect,
  className,
}: {
  folder: string;
  project: IdeProject | null;
  /** The connected folders the sidebar lists. */
  projects: IdeProject[];
  info: GitRepoInfo | null;
  draft: boolean;
  onProject: (projectId: string) => void;
  onConnect: () => void;
  className: string;
}) {
  const t = useT();
  const pushToast = useEventStore((state) => state.pushToast);
  const setActiveSection = useEventStore((state) => state.setActiveSection);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [github, setGithub] = useState<GitHubRepoList | null>(null);
  const [linked, setLinked] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [cloning, setCloning] = useState("");
  const anchor = useRef<HTMLButtonElement | null>(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  // Whether the person is still on the draft the download was started from.
  const stillDraft = useRef(draft);
  stillDraft.current = draft;

  useEffect(() => {
    if (!open) { setQuery(""); return; }
    const controller = new AbortController();
    setLoading(true);
    // Each list stands on its own: without GitHub the folders still show.
    void Promise.allSettled([fetchGitHubRepos(), fetchLinkedRepos(controller.signal)]).then(([repos, links]) => {
      if (controller.signal.aborted) return;
      if (repos.status === "fulfilled") setGithub(repos.value);
      if (links.status === "fulfilled") setLinked(links.value);
      setLoading(false);
    });
    return () => controller.abort();
  }, [open]);

  const needle = query.trim().toLowerCase();
  const folders = useMemo(() => projects.filter((entry) => !needle
    || entry.name.toLowerCase().includes(needle) || entry.path.toLowerCase().includes(needle)
    || (linked[entry.id] ?? "").toLowerCase().includes(needle)), [projects, linked, needle]);
  // A repository that is a connected folder already shows as that folder.
  const remote = useMemo(() => {
    const here = new Set(Object.values(linked).map((name) => name.toLowerCase()));
    return (github?.repos ?? []).filter((repo) => !here.has(repo.name.toLowerCase())
      && (!needle || repo.name.toLowerCase().includes(needle) || repo.description.toLowerCase().includes(needle)));
  }, [github, linked, needle]);
  const shown = needle ? remote.slice(0, 50) : remote.slice(0, REPO_ROWS);

  const pickRepo = async (repo: string) => {
    setOpen(false);
    setCloning(repo);
    try {
      const clone = await cloneGitHubRepo(repo);
      const connected = await openProject(clone.folder, folderLabel(clone.folder));
      const listing = await fetchIdeProjects();
      const store = useIdeProjectsStore.getState();
      store.publish(listing.projects, listing.active_workspace_id);
      store.requestRefresh();
      if (clone.created) pushToast("success", fill(t("ide_threads.cloned"), { repo, folder: clone.folder }));
      // The person moved on while it downloaded: the folder waits in the sidebar.
      if (alive.current && stillDraft.current) onProject(connected.id);
    } catch (error) {
      pushToast("error", error instanceof Error ? error.message : String(error));
    } finally {
      if (alive.current) setCloning("");
    }
  };

  const worktree = Boolean(info?.is_worktree);
  const Icon = worktree ? FolderGit2 : Folder;
  const label = cloning ? fill(t("ide_threads.cloning"), { repo: cloning }) : folderChipLabel(folder, project, info);

  if (!draft) {
    return <span className={cn(className, "hover:bg-transparent hover:text-muted-foreground")} title={folder} data-testid="thread-folder">
      <Icon aria-hidden className="h-3.5 w-3.5 shrink-0" />
      <span className="max-w-[240px] truncate">{label}</span>
    </span>;
  }

  return <>
    <button ref={anchor} type="button" className={className} disabled={Boolean(cloning)} aria-haspopup="menu" aria-expanded={open}
      data-testid="thread-folder" title={folder || t("ide_threads.where_agent_works")} onClick={() => setOpen(!open)}>
      {cloning ? <Loader2 aria-hidden className="h-3.5 w-3.5 shrink-0 animate-spin" /> : <Icon aria-hidden className="h-3.5 w-3.5 shrink-0" />}
      <span className="max-w-[240px] truncate">{label}</span>
      <ChevronDown aria-hidden className="h-3 w-3 shrink-0" />
    </button>
    <ThreadPopover anchor={anchor} open={open} onClose={() => setOpen(false)} label={t("ide_threads.where_agent_works")} side="top" width={340}>
      <ThreadMenuSearch value={query} onChange={setQuery} placeholder={t("ide_threads.search_folders")} busy={loading} testId="thread-folder-search" />
      <div role="menu">
        {folders.length > 0 && <ThreadMenuHeading>{t("ide_threads.folders")}</ThreadMenuHeading>}
        {folders.map((entry) => <ThreadMenuItem key={entry.id} icon={<Folder className="h-3.5 w-3.5" />} selected={entry.id === project?.id}
          label={<span title={entry.path}>{entry.name}</span>}
          hint={entry.id === project?.id ? <Check className="h-3.5 w-3.5" /> : linked[entry.id]
            ? <span className="inline-block max-w-[130px] truncate align-bottom">{linked[entry.id]}</span> : undefined}
          onSelect={() => { setOpen(false); if (entry.id !== project?.id) onProject(entry.id); }} />)}

        {github?.connected && shown.length > 0 && <ThreadMenuHeading>{t("ide_threads.from_github")}</ThreadMenuHeading>}
        {github?.connected && shown.map((repo) => <ThreadMenuItem key={repo.name} icon={<Github className="h-3.5 w-3.5" />}
          label={<span title={fill(t("ide_threads.clone_title"), { repo: repo.name })}>{repo.name}</span>}
          hint={<span className="flex items-center gap-1.5">
            {repo.private && <Lock aria-label={t("ide_threads.private_repo")} className="h-3 w-3" />}
            <Download aria-hidden className="h-3.5 w-3.5" />
          </span>}
          onSelect={() => void pickRepo(repo.name)} />)}
        {github?.connected && remote.length > shown.length
          && <p className="px-2 py-1.5 text-xs text-muted-foreground">{fill(t("ide_threads.more_repos"), { count: remote.length - shown.length })}</p>}
        {github?.connected && github.reason && <p className="px-2 py-1.5 text-xs text-muted-foreground">{github.reason}</p>}
        {github && !github.connected && <ThreadMenuItem icon={<Github className="h-3.5 w-3.5" />} label={t("ide_threads.connect_github")}
          onSelect={() => { setOpen(false); setActiveSection("plugins"); }} />}
        {needle && folders.length === 0 && shown.length === 0
          && <p className="px-2 py-2 text-xs text-muted-foreground">{t("ide_threads.no_matches")}</p>}

        <ThreadMenuSeparator />
        <ThreadMenuItem icon={<FolderPlus className="h-3.5 w-3.5" />} label={t("ide_threads.connect_another")}
          onSelect={() => { setOpen(false); onConnect(); }} />
      </div>
    </ThreadPopover>
  </>;
}
