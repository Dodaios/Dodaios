import { useCallback, useEffect, useRef, useState } from "react";
import { Check, ChevronDown, FolderGit2, GitBranch, Loader2 } from "lucide-react";
import type { IdeProject } from "@/lib/agenticIdeApi";
import { inspectGit, prepareGit, type GitRepoInfo } from "@/lib/gitApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import { fill, useT } from "@/i18n";
import { ThreadFolderChip } from "./ThreadFolderChip";
import { ThreadMachineChip } from "./ThreadMachineChip";
import { ThreadMenuHeading, ThreadMenuItem, ThreadMenuSearch, ThreadPopover } from "./ThreadPopover";

/** Where a new thread's agent works: the project's own checkout, or a worktree of its own. */
export type ThreadCheckout = "current" | "worktree";

const BUTTON = "flex h-6 min-w-0 items-center gap-1.5 rounded-md px-1.5 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

/** The repository state behind a folder, refreshed when the folder changes and on demand. */
export function useGitInfo(folder: string): { info: GitRepoInfo | null; loading: boolean; refresh: () => void } {
  const [info, setInfo] = useState<GitRepoInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (!folder) { setInfo(null); return; }
    const controller = new AbortController();
    setLoading(true);
    inspectGit(folder, controller.signal)
      .then((next) => { if (!controller.signal.aborted) setInfo(next); })
      .catch(() => { if (!controller.signal.aborted) setInfo(null); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [folder, nonce]);
  const refresh = useCallback(() => setNonce((value) => value + 1), []);
  return { info, loading, refresh };
}

/**
 * The strip under the composer: where the thread works, read left to right —
 * the machine, the folder, the branch. A new thread chooses all three, and
 * whether it gets a worktree of its own (the branch is then the one the
 * worktree starts from). A running thread names its folder and leaves the
 * branch alone while the agent works.
 */
export function ThreadBranchBar({
  folder,
  project,
  projects,
  onProject,
  onConnect,
  computerId,
  onComputer,
  draft,
  checkout,
  onCheckout,
  base,
  onBase,
  locked,
}: {
  /** The thread's folder — the project's for a new thread. */
  folder: string;
  project: IdeProject | null;
  /** The connected folders a new thread can move to. */
  projects: IdeProject[];
  onProject: (projectId: string) => void;
  onConnect: () => void;
  /** The machine the turns run on; "" = this computer. */
  computerId: string;
  onComputer: (computerId: string) => void;
  draft: boolean;
  checkout: ThreadCheckout;
  onCheckout: (next: ThreadCheckout) => void;
  /** The branch a new worktree starts from; "" = the current branch. */
  base: string;
  onBase: (branch: string) => void;
  /** The agent is working: switching its branch now would pull files from under it. */
  locked: boolean;
}) {
  const t = useT();
  const pushToast = useEventStore((state) => state.pushToast);
  const { info, loading, refresh } = useGitInfo(folder);
  const [menu, setMenu] = useState<"branch" | null>(null);
  const [switching, setSwitching] = useState(false);
  const [branchQuery, setBranchQuery] = useState("");
  const branchAnchor = useRef<HTMLButtonElement | null>(null);

  const repo = Boolean(info?.is_repo);
  const worktreeDraft = draft && checkout === "worktree";
  const shownBranch = worktreeDraft ? base || info?.branch || "" : info?.branch || "";
  const allBranches = info?.branches ?? [];
  const branchNeedle = branchQuery.trim().toLowerCase();
  const branches = branchNeedle ? allBranches.filter((branch) => branch.name.toLowerCase().includes(branchNeedle)) : allBranches;
  useEffect(() => { if (menu !== "branch") setBranchQuery(""); }, [menu]);

  const pickBranch = async (name: string) => {
    setMenu(null);
    if (worktreeDraft) { onBase(name === info?.branch ? "" : name); return; }
    if (!info || name === info.branch) return;
    setSwitching(true);
    try {
      const result = await prepareGit(folder, { mode: "switch_branch", branch: name, base: "" });
      if (result.message) pushToast("success", result.message);
    } catch (error) {
      pushToast("error", error instanceof Error ? error.message : String(error));
    } finally {
      setSwitching(false);
      refresh();
    }
  };

  // Hangs under the composer card: tucked 16 px beneath it, narrower by the
  // card's corner radius on each side, its own corners rounded at the bottom.
  return <div className="relative mx-auto -mt-4 flex w-[calc(100%-2.75rem)] items-center gap-2 rounded-b-2xl border border-t-0 border-border bg-sidebar pb-1 pe-2 ps-1 pt-5" data-testid="thread-branch-bar">
    <div className="flex min-w-0 flex-1 items-center gap-0.5">
      <ThreadMachineChip computerId={computerId} onChange={onComputer} draft={draft} locked={locked} className={BUTTON} />
      <ThreadFolderChip folder={folder} project={project} projects={projects} info={info} draft={draft}
        onProject={onProject} onConnect={onConnect} className={BUTTON} />
      {repo && <button ref={branchAnchor} type="button" className={BUTTON} disabled={switching || (!draft && locked)}
        aria-haspopup="menu" aria-expanded={menu === "branch"} data-testid="thread-branch"
        title={worktreeDraft ? t("ide_threads.worktree_base_title") : locked ? t("ide_threads.agent_on_branch") : t("ide_threads.switch_branch")}
        onClick={() => { refresh(); setMenu(menu === "branch" ? null : "branch"); }}>
        {switching || loading ? <Loader2 aria-hidden className="h-3.5 w-3.5 shrink-0 animate-spin" /> : <GitBranch aria-hidden className="h-3.5 w-3.5 shrink-0" />}
        <span className="max-w-[220px] truncate font-mono">{worktreeDraft ? fill(t("ide_threads.from_branch"), { branch: shownBranch || "HEAD" }) : shownBranch || t("ide_git.detached")}</span>
        {info && info.dirty && !worktreeDraft && <span className="text-warning" title={t("ide_threads.uncommitted_changes")}>•</span>}
        <ChevronDown aria-hidden className="h-3 w-3 shrink-0" />
      </button>}
    </div>
    {draft && repo && <button type="button" aria-pressed={checkout === "worktree"} data-testid="thread-worktree-toggle"
      className={cn(BUTTON, "shrink-0", checkout === "worktree" && "bg-secondary text-foreground")}
      title={t("ide_threads.worktree_toggle_title")}
      onClick={() => onCheckout(checkout === "worktree" ? "current" : "worktree")}>
      <FolderGit2 aria-hidden className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{t("ide_git.new_worktree")}</span>
      {checkout === "worktree" && <Check aria-hidden className="h-3 w-3 shrink-0" />}
    </button>}

    <ThreadPopover anchor={branchAnchor} open={menu === "branch"} onClose={() => setMenu(null)} label={t("ide_threads.branches")} side="top" width={300}>
      {allBranches.length > 8 && <ThreadMenuSearch value={branchQuery} onChange={setBranchQuery} placeholder={t("ide_threads.search_branches")} testId="thread-branch-search" />}
      <div role="menu">
        <ThreadMenuHeading>{worktreeDraft ? t("ide_threads.start_worktree_from") : t("ide_threads.switch_to")}</ThreadMenuHeading>
        {branches.map((branch) => {
          const busyElsewhere = !worktreeDraft && Boolean(branch.worktree) && !branch.current;
          return <ThreadMenuItem key={branch.name} icon={<GitBranch className="h-3.5 w-3.5" />}
            label={<span className="font-mono text-xs">{branch.name}</span>}
            selected={branch.name === shownBranch}
            hint={branch.name === shownBranch ? <Check className="h-3.5 w-3.5" /> : busyElsewhere ? t("ide_threads.in_a_worktree") : branch.name === info?.default_branch ? t("ide_git.hint_default") : undefined}
            disabled={busyElsewhere}
            onSelect={() => void pickBranch(branch.name)} />;
        })}
        {info && allBranches.length === 0 && <p className="px-2 py-2 text-xs text-muted-foreground">{t("ide_threads.no_local_branches")}</p>}
        {allBranches.length > 0 && branches.length === 0 && <p className="px-2 py-2 text-xs text-muted-foreground">{t("ide_threads.no_matches")}</p>}
      </div>
    </ThreadPopover>
  </div>;
}
