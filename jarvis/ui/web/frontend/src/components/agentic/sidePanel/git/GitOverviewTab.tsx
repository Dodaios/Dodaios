import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, FolderGit2, Loader2, RefreshCw } from "lucide-react";
import { fill, useT } from "@/i18n";
import { useRunLocale } from "@/components/runs/format";
import { openExternalUrl } from "@/lib/openExternal";
import { cn } from "@/lib/utils";
import { QuickTooltip } from "@/components/ui/tooltip";
import { useEventStore } from "@/store/events";
import { useIdeChatStore } from "@/store/ideChat";
import { useIdeSidePanelStore } from "@/store/ideSidePanel";
import { AttentionList } from "./AttentionList";
import { BranchList } from "./BranchList";
import { BranchMenu } from "./BranchMenu";
import { CleanupDialog } from "./CleanupDialog";
import { ConfirmDialog } from "./ConfirmDialog";
import { agoLabel, LinkIcon } from "./gitBadges";
import { ConnectGitHubCard, GitHubRepoPicker } from "./GitHubRepoPicker";
import { attention, canCleanUp, checkoutOf, openPullRequests, type AttentionItem, type BranchFilter } from "./gitInsights";
import { fetchBranchEditors, fetchGitOverview, GitOverviewError, type BranchEditors, type BranchRow, type RepoOverview } from "./gitOverviewApi";
import { PullRequestList } from "./PullRequestList";
import { Section } from "./Section";
import { StatusPanel } from "./StatusPanel";
import { useGitActions } from "./useGitActions";

/**
 * An unchanged repository answers a poll with one `git status`; GitHub is
 * cached per repository on the backend (shorter while a check runs), so this
 * cadence never turns into one GitHub call per tick.
 */
const POLL_MS = 15_000;
const POLL_JITTER_MS = 3_000;
/** While GitHub is being read (the first time, or again after an action), the local state is already shown and this re-asks soon. */
const POLL_LOADING_MS = 1_500;

/**
 * The last overview per workspace. Reopening the tab paints it at once and
 * refreshes behind it, instead of starting from a spinner every time.
 */
const LAST_OVERVIEW = new Map<string, RepoOverview>();

/** Forget every remembered overview (tests start from an empty tab). */
export function resetGitOverviewCache(): void {
  LAST_OVERVIEW.clear();
}

function useGitOverview(workspaceId: string | null) {
  const [data, setData] = useState<RepoOverview | null>(() => (workspaceId ? (LAST_OVERVIEW.get(workspaceId) ?? null) : null));
  const [error, setError] = useState("");
  const [routeMissing, setRouteMissing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [round, setRound] = useState(0);
  // Set by refresh(), used up by the next read: a later workspace switch is an ordinary read again.
  const forceNext = useRef(false);
  const shown = useRef(workspaceId);
  useEffect(() => {
    if (shown.current === workspaceId) return;
    shown.current = workspaceId;
    setData(workspaceId ? (LAST_OVERVIEW.get(workspaceId) ?? null) : null);
    setError("");
  }, [workspaceId]);
  useEffect(() => {
    if (!workspaceId) return;
    let alive = true;
    let timer: number | undefined;
    let refresh = forceNext.current;
    forceNext.current = false;
    let githubLoading = false;
    const tick = async () => {
      if (useEventStore.getState().activeSection === "agentic-ide") {
        setLoading(true);
        try {
          const next = await fetchGitOverview(workspaceId, refresh);
          refresh = false;
          githubLoading = next.github?.code === "loading" || Boolean(next.github?.refreshing);
          LAST_OVERVIEW.set(workspaceId, next);
          if (alive) {
            setData(next);
            setError("");
            setRouteMissing(false);
          }
        } catch (err) {
          // Keep the last answer on screen; the next tick tries again.
          if (alive) {
            setError((err as Error).message);
            setRouteMissing(err instanceof GitOverviewError && err.routeMissing);
          }
        } finally {
          if (alive) setLoading(false);
        }
      }
      const delay = githubLoading ? POLL_LOADING_MS + Math.random() * 500 : POLL_MS + Math.random() * POLL_JITTER_MS;
      if (alive) timer = window.setTimeout(tick, delay);
    };
    void tick();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [workspaceId, round]);
  const refresh = useCallback(() => {
    forceNext.current = true;
    setRound((value) => value + 1);
  }, []);
  return { data, error, routeMissing, loading, refresh };
}

async function restartApp(pushToast: (kind: "warning" | "error", text: string) => void, t: (key: string) => string): Promise<boolean> {
  try {
    const response = await fetch("/api/settings/restart-app", { method: "POST" });
    if (response.status === 409) {
      pushToast("warning", t("topbar.restart_missions_running"));
      return false;
    }
    if (!response.ok) throw new Error(`restart-failed:${response.status}`);
    // The window closes and relaunches; the button stays busy until then.
    return true;
  } catch {
    pushToast("error", t("permissions.restart_failed"));
    return false;
  }
}

/**
 * The running backend predates this tab: the one thing to do is restart, so
 * the card says what the tab is for and restarts on a click. A click in the
 * app is the person asking; control clients can never restart it.
 */
function RestartToConnectCard() {
  const t = useT();
  const pushToast = useEventStore((state) => state.pushToast);
  const [restarting, setRestarting] = useState(false);
  const restart = async () => {
    if (restarting) return;
    setRestarting(true);
    if (!(await restartApp(pushToast, t))) setRestarting(false);
  };
  return (
    <div data-testid="git-error" className="mx-3 my-3 space-y-2 rounded-lg border border-border/60 bg-muted/30 p-3">
      <p className="text-[12.5px] font-medium text-foreground">{t("ide_side_panel.git.connect_repo_title")}</p>
      <p className="text-[11.5px] text-muted-foreground">{t("ide_side_panel.git.needs_restart")}</p>
      <button
        type="button"
        data-testid="git-restart"
        disabled={restarting}
        onClick={() => void restart()}
        className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
      >
        {restarting ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <RefreshCw className="h-3.5 w-3.5" aria-hidden />}
        {t("ide_side_panel.git.restart_button")}
      </button>
    </div>
  );
}

/** The backend answers, but is older than the control center: say so in one line. */
function OlderBackendNote() {
  const t = useT();
  const pushToast = useEventStore((state) => state.pushToast);
  const [restarting, setRestarting] = useState(false);
  return (
    <p data-testid="git-older-backend" className="flex items-center gap-2 border-b border-border/60 px-3 py-2 text-[11px] text-muted-foreground">
      <span className="min-w-0 flex-1">{t("ide_side_panel.git.older_backend")}</span>
      <button
        type="button"
        disabled={restarting}
        onClick={() => {
          setRestarting(true);
          void restartApp(pushToast, t).then((ok) => !ok && setRestarting(false));
        }}
        className="shrink-0 rounded text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
      >
        {t("ide_side_panel.git.restart_button")}
      </button>
    </p>
  );
}

/** Quiet placeholder blocks in the shape of the tab, while the first answer loads. */
function LoadingShape() {
  const t = useT();
  const bar = "rounded bg-secondary motion-safe:animate-pulse";
  return (
    <div data-testid="git-loading" role="status" aria-label={t("ide_side_panel.git.loading")} className="space-y-3 px-3 py-3">
      <div className={cn(bar, "h-4 w-40")} />
      <div className={cn(bar, "h-11 w-full")} />
      <div className={cn(bar, "h-12 w-full")} />
      {[0, 1, 2, 3].map((index) => (
        <div key={index} className="space-y-1.5 pt-1">
          <div className={cn(bar, "h-3 w-3/5")} />
          <div className={cn(bar, "h-2.5 w-2/5")} />
        </div>
      ))}
    </div>
  );
}

/**
 * The Git tab: the state of the open workspace's repository at a glance. On
 * top, the checkout the person is in — who is ahead, what is uncommitted, the
 * one next step. Below it what needs a look across the repository, every open
 * pull request with its CI, and every branch. What matters can be done here.
 */
export function GitOverviewTab() {
  const t = useT();
  const lang = useRunLocale();
  const workspace = useIdeChatStore((state) => state.workspace);
  const workspaceId = workspace?.id ?? null;
  const { data, error, routeMissing, loading, refresh } = useGitOverview(workspaceId);
  const actions = useGitActions(data?.root || workspace?.path || "", data?.branch ?? "", refresh);
  const [filter, setFilter] = useState<BranchFilter>("all");
  const [open, setOpen] = useState({ prs: true, branches: true });
  const [menu, setMenu] = useState<{ row: BranchRow; x: number; y: number } | null>(null);
  const [cleaning, setCleaning] = useState<BranchRow[] | null>(null);
  const [alsoRemote, setAlsoRemote] = useState(false);
  const [editors, setEditors] = useState<BranchEditors | null>(null);
  const prsRef = useRef<HTMLDivElement>(null);
  const branchesRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let alive = true;
    fetchBranchEditors()
      .then((answer) => alive && setEditors(answer))
      // An older backend has no such route: rows then offer GitHub and copy only.
      .catch(() => alive && setEditors({ file_manager: false, editors: [] }));
    return () => {
      alive = false;
    };
  }, []);
  const openMenu = useCallback((row: BranchRow, x: number, y: number) => {
    setMenu((current) => (current?.row.name === row.name && current.row.remote_only === row.remote_only ? null : { row, x, y }));
  }, []);
  const closeMenu = useCallback(() => setMenu(null), []);
  // Reopened from the repository chip to change an earlier choice.
  const [changing, setChanging] = useState(false);
  // The repository just picked. The pick is saved at once, but the GitHub
  // read it starts takes seconds (up to the request timeout); until that
  // answer lands the tab shows the choice and the local branches, never the
  // picker again — a picker that stays put reads as "the click did nothing".
  const [pickedRepo, setPickedRepo] = useState("");
  useEffect(() => setChanging(false), [workspaceId]);
  useEffect(() => setPickedRepo(""), [data, workspaceId]);
  useEffect(() => {
    setFilter("all");
    setMenu(null);
    setCleaning(null);
  }, [workspaceId]);
  useEffect(() => setAlsoRemote(false), [actions.confirmation]);

  const items = useMemo(() => (data?.available ? attention(data) : []), [data]);
  const prs = useMemo(() => (data?.available ? openPullRequests(data) : []), [data]);

  if (!workspace) {
    return <p className="px-4 py-6 text-center text-xs text-muted-foreground">{t("ide_side_panel.git.no_workspace")}</p>;
  }
  const github = data?.github;
  const picking = Boolean(
    data && workspaceId && !pickedRepo && (github?.code === "needs_repo" || (changing && github?.code !== "not_connected")),
  );
  const boundRepo = pickedRepo || github?.repo || "";
  const repoName = (data?.root || workspace.path).replace(/\\/g, "/").split("/").filter(Boolean).pop() ?? workspace.name;
  const checkout = data?.available ? checkoutOf(data) : null;
  const fetching = actions.busy === "fetch";

  const reveal = (section: "prs" | "branches") => {
    setOpen((current) => ({ ...current, [section]: true }));
    const target = section === "prs" ? prsRef : branchesRef;
    // After the section has opened.
    window.setTimeout(() => target.current?.scrollIntoView?.({ block: "start", behavior: "smooth" }), 0);
  };
  const onAttention = (item: AttentionItem) => {
    if (!data) return;
    const fallback = data.branches.find((row) => row.name === data.default_branch);
    if (item.kind === "cleanup") return setCleaning(data.branches.filter((row) => canCleanUp(row, data.default_branch)));
    if (item.kind === "default_ci") return void (fallback?.ci.url && openExternalUrl(fallback.ci.url));
    if (item.kind === "default_behind") {
      return fallback && fallback.behind > 0 ? actions.update(fallback.name) : void actions.fetch();
    }
    if (item.kind === "unpushed" || item.kind === "behind") {
      setFilter(item.kind);
      return reveal("branches");
    }
    return reveal("prs");
  };
  const syncNow = () => {
    // Fetch first, so "to pull" counts what the remote has now; a repository without a remote just re-reads.
    if (checkout?.has_remote && data?.checkout) void actions.fetch();
    else refresh();
  };
  const fetched = checkout?.last_fetch ? fill(t("ide_side_panel.git.fetched"), { when: agoLabel(checkout.last_fetch, lang, t) }) : "";
  const refreshTip = [
    t("ide_side_panel.git.refresh"),
    github?.available ? fill(t("ide_side_panel.git.github_updated"), { when: agoLabel(github.fetched_at, lang, t) }) : "",
  ]
    .filter(Boolean)
    .join("\n");

  return (
    <section data-testid="ide-git-tab" aria-label={t("ide_side_panel.git.aria")} className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-border/60 px-3 pb-2 pt-2.5">
        <div className="flex items-center gap-2">
          <FolderGit2 className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="min-w-0 truncate text-sm font-semibold text-foreground">{repoName}</span>
          <span className="ml-auto flex shrink-0 items-center">
            {github?.repo_url && (
              <LinkIcon url={github.repo_url} tip={t("ide_side_panel.git.open_repo")} label={t("ide_side_panel.git.open_repo")} testId="git-open-repo">
                <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
              </LinkIcon>
            )}
            <QuickTooltip content={refreshTip} side="bottom" className="inline-flex">
              <button
                type="button"
                data-testid="git-refresh"
                aria-label={t("ide_side_panel.git.refresh")}
                disabled={actions.busy !== ""}
                onClick={syncNow}
                className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
              >
                <RefreshCw className={cn("h-3.5 w-3.5", (loading || fetching || github?.refreshing) && "animate-spin motion-reduce:animate-none")} aria-hidden />
              </button>
            </QuickTooltip>
          </span>
        </div>
        {(boundRepo || fetched) && (
          <p data-testid="git-github-state" className="flex min-w-0 items-center gap-1.5 text-[10.5px] text-muted-foreground">
            {boundRepo && (
              <QuickTooltip content={t("ide_side_panel.git.change_repo")} side="bottom" className="inline-flex min-w-0">
                <button
                  type="button"
                  data-testid="git-bound-repo"
                  onClick={() => setChanging(true)}
                  className="inline-flex min-w-0 items-center gap-1 rounded px-0.5 font-mono text-foreground/80 hover:bg-secondary hover:text-foreground"
                >
                  <span className="truncate">{boundRepo}</span>
                </button>
              </QuickTooltip>
            )}
            {boundRepo && <span aria-hidden>·</span>}
            <span className="min-w-0 truncate">
              {fetching
                ? t("ide_side_panel.git.fetching")
                : pickedRepo || github?.code === "loading"
                  ? t("ide_side_panel.git.github_reading")
                  : boundRepo && github && !github.available
                    ? github.reason
                    : fetched || t("ide_side_panel.git.never_fetched")}
            </span>
          </p>
        )}
      </div>

      {picking && data && workspaceId ? (
        <GitHubRepoPicker
          key={workspaceId}
          workspaceId={workspaceId}
          current={github?.repo ?? ""}
          suggested={github?.suggested_repo ?? ""}
          onPicked={(repo) => {
            setPickedRepo(repo);
            setChanging(false);
            refresh();
          }}
          onCancel={github?.repo ? () => setChanging(false) : undefined}
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          {!data ? (
            error ? (
              routeMissing ? (
                <RestartToConnectCard />
              ) : (
                <p data-testid="git-error" className="px-4 py-6 text-center text-xs text-destructive">
                  {error}
                </p>
              )
            ) : (
              <LoadingShape />
            )
          ) : !data.available ? (
            <p data-testid="git-unavailable" className="px-4 py-6 text-center text-xs text-muted-foreground">
              {data.reason}
            </p>
          ) : (
            <>
              {!data.checkout && <OlderBackendNote />}
              <StatusPanel key={workspace.id} overview={data} actions={actions} onOpenChanges={() => useIdeSidePanelStore.getState().openTab("changes")} />
              {github?.code === "not_connected" && <ConnectGitHubCard />}
              <AttentionList items={items} onAct={onAttention} />
              {github?.available && (
                <div ref={prsRef}>
                  <Section
                    id="prs"
                    title={t("ide_side_panel.git.prs.title")}
                    count={prs.length}
                    open={open.prs}
                    onToggle={() => setOpen((current) => ({ ...current, prs: !current.prs }))}
                  >
                    <PullRequestList prs={prs} defaultBranch={data.default_branch} />
                  </Section>
                </div>
              )}
              <div ref={branchesRef}>
                <Section
                  id="branches"
                  title={t("ide_side_panel.git.branches")}
                  count={data.branches.length}
                  open={open.branches}
                  onToggle={() => setOpen((current) => ({ ...current, branches: !current.branches }))}
                >
                  <BranchList
                    overview={data}
                    workspaceId={workspace.id}
                    editors={editors}
                    actions={actions}
                    filter={filter}
                    onFilter={setFilter}
                    menuBranch={menu ? `${menu.row.remote_only ? "remote:" : ""}${menu.row.name}` : ""}
                    onMenu={openMenu}
                  />
                </Section>
              </div>
              {error && <p className="px-3 py-2 text-[11px] text-destructive">{error}</p>}
            </>
          )}
        </div>
      )}

      {menu && data && (
        <BranchMenu
          row={menu.row}
          repoUrl={github?.repo_url ?? ""}
          defaultBranch={data.default_branch}
          x={menu.x}
          y={menu.y}
          actions={data.checkout ? actions : undefined}
          onDismiss={closeMenu}
        />
      )}
      {actions.confirmation && (
        <ConfirmDialog
          title={actions.confirmation.title}
          body={actions.confirmation.body}
          confirmLabel={actions.confirmation.confirmLabel}
          busy={actions.busy !== ""}
          onCancel={actions.dismiss}
          onConfirm={() => {
            const pending = actions.confirmation;
            actions.dismiss();
            void pending?.run({ remote: alsoRemote });
          }}
        >
          {actions.confirmation.remoteOption && (
            <label className="mt-3 flex cursor-pointer items-center gap-2 text-xs text-foreground">
              <input
                type="checkbox"
                data-testid="git-confirm-remote"
                checked={alsoRemote}
                onChange={(event) => setAlsoRemote(event.target.checked)}
                className="h-3.5 w-3.5 accent-[hsl(var(--accent))]"
              />
              {t("ide_side_panel.git.confirm.delete_remote")}
            </label>
          )}
        </ConfirmDialog>
      )}
      {cleaning && data && (
        <CleanupDialog
          rows={cleaning}
          folder={data.root}
          onClose={(changed) => {
            setCleaning(null);
            if (changed) refresh();
          }}
        />
      )}
    </section>
  );
}
