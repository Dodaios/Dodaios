import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fill, useT } from "@/i18n";
import { prepareGit } from "@/lib/gitApi";
import { useEventStore } from "@/store/events";
import { useIdeChatStore } from "@/store/ideChat";
import { useGitSessionStore } from "@/store/gitSession";
import { useWorkspacePanes } from "@/store/workspacePanes";
import { RepositoryOverview, RestartToConnectCard } from "./RepositoryOverview";
import { ChangesView, IconButton, viewSortMenu, type ListSettings } from "./scm/ChangesView";
import { Codicon } from "./scm/Codicon";
import "./scm/scm.css";
import { DiffDialog, type DiffSource } from "./scm/DiffDialog";
import { GraphView } from "./scm/GraphView";
import { useQuickInput } from "./scm/QuickInput";
import { ScmMenu, menuPointFor, type MenuItem } from "./scm/ScmMenu";
import { ScmViews } from "./scm/ScmViews";
import type { SessionPick } from "./scm/SessionChanges";
import { scmApi, type FollowMain, type GraphScope } from "./scm/scmApi";
import { agoLabel } from "./gitBadges";
import { useRunLocale } from "@/components/runs/format";
import { scmStorage, useChoice, useScmCommands, useScmStatus, type CommitOptions } from "./scm/useScm";

export { resetGitOverviewCache } from "./RepositoryOverview";

type ViewId = "changes" | "graph" | "branches";

function readJson<T>(key: string, fallback: T): T {
  try {
    const text = scmStorage.get(key);
    return text ? { ...fallback, ...(JSON.parse(text) as T) } : fallback;
  } catch {
    return fallback; // a damaged entry falls back to the defaults
  }
}

const VIEWS_KEY = "jarvis.git.scm.views.v1";
const WEIGHTS_KEY = "jarvis.git.scm.weights.v1";
const LIST_KEY = "jarvis.git.scm.list.v1";
const SCOPE_KEY = "jarvis.git.scm.graphScope.v1";
const MESSAGE_KEY = (workspaceId: string) => `jarvis.git.scm.message.${workspaceId}`;

/**
 * The Git tab: source control for the open workspace's repository. Changes
 * lists every staged, unstaged and conflicting file under the commit box;
 * Graph draws the history; Branches & Pull Requests is the repository-wide
 * overview with GitHub's pull requests and CI.
 */
export function GitOverviewTab() {
  const t = useT();
  const workspace = useIdeChatStore((state) => state.workspace);
  const workspaceId = workspace?.id ?? null;
  const pushToast = useEventStore((state) => state.pushToast);
  const quick = useQuickInput();
  const choice = useChoice();
  const { status, error, refresh } = useScmStatus(workspaceId);
  const [bump, setBump] = useState(0);
  const onChanged = useCallback(() => setBump((value) => value + 1), []);
  const { busy, commands } = useScmCommands({ workspaceId: workspaceId ?? "", status, refresh, quick, ask: choice.ask, onChanged });
  const [open, setOpen] = useState<Record<ViewId, boolean>>(() => readJson(VIEWS_KEY, { changes: true, graph: true, branches: false }));
  const [weights, setWeights] = useState<Record<string, number>>(() => readJson(WEIGHTS_KEY, { changes: 1, graph: 1, branches: 1 }));
  const [settings, setSettings] = useState<ListSettings>(() => readJson<ListSettings>(LIST_KEY, { mode: "list", sort: "path" }));
  const [scope, setScope] = useState<GraphScope>(() => (scmStorage.get(SCOPE_KEY) as GraphScope) || "auto");
  const [diff, setDiff] = useState<DiffSource | null>(null);
  const [menu, setMenu] = useState<{ items: MenuItem[]; x: number; y: number } | null>(null);
  const [goHead, setGoHead] = useState(0);
  const [initializing, setInitializing] = useState(false);
  const lang = useRunLocale();
  // Does this app keep itself on the newest main? Read now and then while the tab is open.
  const [follow, setFollow] = useState<FollowMain | null>(null);
  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const read = () => {
      scmApi
        .followMain()
        .then((answer) => alive && setFollow(answer))
        .catch(() => alive && setFollow(null)) // an older backend has no such route: no toggle
        .finally(() => {
          if (alive) timer = window.setTimeout(read, 20_000 + Math.random() * 5_000);
        });
    };
    read();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, []);
  const toggleFollow = useCallback(() => {
    if (!follow) return;
    scmApi
      .setFollowMain(!follow.enabled)
      .then(setFollow)
      .catch((err: Error) => pushToast("error", err.message));
  }, [follow, pushToast]);
  // One agent session the Changes list is narrowed to (its pane's call-sign), per workspace.
  const [sessionPane, setSessionPane] = useState<string | null>(null);
  const panes = useWorkspacePanes(Boolean(workspaceId));
  const workspacePanes = useMemo(() => panes.filter((row) => row.workspace_id === workspaceId), [panes, workspaceId]);
  const session: SessionPick | null = useMemo(() => {
    if (!sessionPane) return null;
    const row = workspacePanes.find((entry) => entry.name === sessionPane);
    return { pane: sessionPane, agentName: row?.display_name || row?.agent || "", title: row?.recap || row?.last_prompt || "" };
  }, [sessionPane, workspacePanes]);
  useEffect(() => setSessionPane(null), [workspaceId]);
  // A pane's "show in Git" button narrows the list to that pane.
  const sessionRequest = useGitSessionStore((state) => state.request);
  useEffect(() => {
    if (!sessionRequest || sessionRequest.workspaceId !== workspaceId) return;
    setSessionPane(sessionRequest.pane);
    setOpen((current) => ({ ...current, changes: true }));
    useGitSessionStore.getState().consume(sessionRequest.nonce);
  }, [sessionRequest, workspaceId]);
  // The commit message is kept per workspace, across restarts, until it is committed.
  const [message, setMessageState] = useState(() => (workspaceId ? scmStorage.get(MESSAGE_KEY(workspaceId)) : ""));
  const [messageError, setMessageError] = useState("");
  const messageRef = useRef<HTMLTextAreaElement>(null);
  const shownWorkspace = useRef(workspaceId);
  useEffect(() => {
    if (shownWorkspace.current === workspaceId) return;
    shownWorkspace.current = workspaceId;
    setMessageState(workspaceId ? scmStorage.get(MESSAGE_KEY(workspaceId)) : "");
    setMessageError("");
  }, [workspaceId]);
  const setMessage = useCallback(
    (next: string) => {
      setMessageState(next);
      setMessageError("");
      if (workspaceId) scmStorage.set(MESSAGE_KEY(workspaceId), next);
    },
    [workspaceId],
  );

  useEffect(() => scmStorage.set(VIEWS_KEY, JSON.stringify(open)), [open]);
  useEffect(() => scmStorage.set(WEIGHTS_KEY, JSON.stringify(weights)), [weights]);
  useEffect(() => scmStorage.set(LIST_KEY, JSON.stringify(settings)), [settings]);
  useEffect(() => scmStorage.set(SCOPE_KEY, scope), [scope]);

  // The graph reads again when the branch, its tip or its upstream moves.
  const revision = status ? [status.branch, status.head, status.upstream, status.ahead, status.behind, bump].join("|") : String(bump);

  const toggleView = (id: ViewId) => setOpen((current) => ({ ...current, [id]: !current[id] }));

  const runCommit = useCallback(
    (options: CommitOptions) => {
      if (!message.trim() && options.kind !== "amend") {
        setOpen((current) => ({ ...current, changes: true }));
        setMessageError(t("ide_side_panel.git.scm.message_required"));
        messageRef.current?.focus();
        return;
      }
      setMessageError("");
      void commands.commit(message, options).then((made) => made && setMessage(""));
    },
    [commands, message, setMessage, t],
  );

  // Undo puts the commit's message back into the box, as long as nothing new was typed there.
  const undoLastCommit = useCallback(async () => {
    const restored = await commands.undoLastCommit();
    if (restored !== undefined && !message.trim()) setMessage(restored);
  }, [commands, message, setMessage]);

  const moreMenu = useCallback((): MenuItem[] => {
    const operation = status?.operation ?? "";
    return [
      viewSortMenu(settings, setSettings, t),
      ...(follow
        ? ([{ id: "follow-main", label: t("ide_side_panel.git.scm.follow_main"), checked: follow.enabled, run: toggleFollow }] as MenuItem[])
        : []),
      { kind: "separator", id: "m0" },
      { id: "pull", label: t("ide_side_panel.git.scm.pull"), run: () => void commands.pull() },
      { id: "push", label: t("ide_side_panel.git.scm.push"), run: () => void commands.push() },
      { id: "checkout", label: t("ide_side_panel.git.scm.checkout_to"), run: () => void commands.checkoutTo() },
      { id: "fetch", label: t("ide_side_panel.git.scm.fetch"), run: () => void commands.fetch() },
      { kind: "separator", id: "m1" },
      {
        kind: "submenu",
        id: "commit-menu",
        label: t("ide_side_panel.git.scm.menu_commit"),
        items: [
          { id: "c-commit", label: t("ide_side_panel.git.scm.commit"), run: () => runCommit({ kind: "commit" }) },
          { id: "c-staged", label: t("ide_side_panel.git.scm.commit_staged"), run: () => runCommit({ kind: "commit", scope: "staged" }) },
          { id: "c-all", label: t("ide_side_panel.git.scm.commit_all"), run: () => runCommit({ kind: "commit", scope: "all" }) },
          { id: "c-undo", label: t("ide_side_panel.git.scm.undo_last_commit"), disabled: !status?.head, run: () => void undoLastCommit() },
          ...(operation === "rebase"
            ? [{ id: "c-abort-rebase", label: t("ide_side_panel.git.scm.abort_rebase"), run: () => void commands.operation("abort") } as MenuItem]
            : []),
          { kind: "separator", id: "c1" },
          { id: "c-amend", label: t("ide_side_panel.git.scm.commit_amend"), run: () => runCommit({ kind: "amend" }) },
          { id: "c-staged-amend", label: t("ide_side_panel.git.scm.commit_staged_amend"), run: () => runCommit({ kind: "amend", scope: "staged" }) },
          { id: "c-all-amend", label: t("ide_side_panel.git.scm.commit_all_amend"), run: () => runCommit({ kind: "amend", scope: "all" }) },
          { kind: "separator", id: "c2" },
          { id: "c-signoff", label: t("ide_side_panel.git.scm.commit_signed_off"), run: () => runCommit({ kind: "commit", signoff: true }) },
          { id: "c-staged-signoff", label: t("ide_side_panel.git.scm.commit_staged_signed_off"), run: () => runCommit({ kind: "commit", scope: "staged", signoff: true }) },
          { id: "c-all-signoff", label: t("ide_side_panel.git.scm.commit_all_signed_off"), run: () => runCommit({ kind: "commit", scope: "all", signoff: true }) },
          { kind: "separator", id: "c3" },
          { id: "c-no-verify", label: t("ide_side_panel.git.scm.commit_no_verify"), run: () => runCommit({ kind: "commit", noVerify: true }) },
        ],
      },
      {
        kind: "submenu",
        id: "changes-menu",
        label: t("ide_side_panel.git.scm.menu_changes"),
        items: [
          { id: "ch-stage-all", label: t("ide_side_panel.git.scm.stage_all"), run: () => void commands.stageAll() },
          { id: "ch-unstage-all", label: t("ide_side_panel.git.scm.unstage_all"), run: () => void commands.unstageAll() },
          { id: "ch-discard-all", label: t("ide_side_panel.git.scm.discard_all"), run: () => void commands.discardAll() },
        ],
      },
      {
        kind: "submenu",
        id: "pull-push-menu",
        label: t("ide_side_panel.git.scm.menu_pull_push"),
        items: [
          { id: "pp-sync", label: t("ide_side_panel.git.scm.sync"), run: () => void commands.sync() },
          { kind: "separator", id: "p1" },
          { id: "pp-pull", label: t("ide_side_panel.git.scm.pull"), run: () => void commands.pull() },
          { id: "pp-pull-rebase", label: t("ide_side_panel.git.scm.pull_rebase"), run: () => void commands.pull(true) },
          { id: "pp-pull-from", label: t("ide_side_panel.git.scm.pull_from"), run: () => void commands.pullFrom() },
          { kind: "separator", id: "p2" },
          { id: "pp-push", label: t("ide_side_panel.git.scm.push"), run: () => void commands.push() },
          { id: "pp-push-to", label: t("ide_side_panel.git.scm.push_to"), run: () => void commands.pushTo() },
          { id: "pp-push-tags", label: t("ide_side_panel.git.scm.push_tags"), run: () => void commands.pushTags() },
          { kind: "separator", id: "p3" },
          { id: "pp-fetch", label: t("ide_side_panel.git.scm.fetch"), run: () => void commands.fetch() },
          { id: "pp-fetch-prune", label: t("ide_side_panel.git.scm.fetch_prune"), run: () => void commands.fetch({ prune: true }) },
          { id: "pp-fetch-all", label: t("ide_side_panel.git.scm.fetch_all"), run: () => void commands.fetch({ all_remotes: true }) },
        ],
      },
      {
        kind: "submenu",
        id: "branch-menu",
        label: t("ide_side_panel.git.scm.menu_branch"),
        items: [
          { id: "b-merge", label: t("ide_side_panel.git.scm.merge_branch"), run: () => void commands.mergeBranch() },
          { id: "b-rebase", label: t("ide_side_panel.git.scm.rebase_branch"), run: () => void commands.rebaseBranch() },
          { kind: "separator", id: "b1" },
          { id: "b-create", label: t("ide_side_panel.git.scm.create_branch"), run: () => void commands.createBranch() },
          { id: "b-create-from", label: t("ide_side_panel.git.scm.create_branch_from"), run: () => void commands.createBranchFrom() },
          { kind: "separator", id: "b2" },
          { id: "b-rename", label: t("ide_side_panel.git.scm.rename_branch"), disabled: !status?.branch, run: () => void commands.renameBranch() },
          { id: "b-delete", label: t("ide_side_panel.git.scm.delete_branch"), run: () => void commands.deleteBranch() },
          { kind: "separator", id: "b3" },
          { id: "b-publish", label: t("ide_side_panel.git.scm.publish_branch"), disabled: !status?.branch || Boolean(status?.upstream), run: () => void commands.publish() },
        ],
      },
      {
        kind: "submenu",
        id: "remote-menu",
        label: t("ide_side_panel.git.scm.menu_remote"),
        items: [
          { id: "r-add", label: t("ide_side_panel.git.scm.add_remote"), run: () => void commands.addRemote() },
          { id: "r-remove", label: t("ide_side_panel.git.scm.remove_remote"), disabled: !status?.remotes.length, run: () => void commands.removeRemote() },
        ],
      },
      {
        kind: "submenu",
        id: "stash-menu",
        label: t("ide_side_panel.git.scm.menu_stash"),
        items: [
          { id: "s-stash", label: t("ide_side_panel.git.scm.stash"), run: () => void commands.stash() },
          { id: "s-stash-untracked", label: t("ide_side_panel.git.scm.stash_untracked"), run: () => void commands.stash({ include_untracked: true }) },
          { id: "s-stash-staged", label: t("ide_side_panel.git.scm.stash_staged"), run: () => void commands.stash({ staged: true }) },
          { kind: "separator", id: "s1" },
          { id: "s-apply-latest", label: t("ide_side_panel.git.scm.apply_latest_stash"), disabled: !status?.stashes, run: () => void commands.applyStash(false, true) },
          { id: "s-apply", label: t("ide_side_panel.git.scm.apply_stash"), disabled: !status?.stashes, run: () => void commands.applyStash(false, false) },
          { kind: "separator", id: "s2" },
          { id: "s-pop-latest", label: t("ide_side_panel.git.scm.pop_latest_stash"), disabled: !status?.stashes, run: () => void commands.applyStash(true, true) },
          { id: "s-pop", label: t("ide_side_panel.git.scm.pop_stash"), disabled: !status?.stashes, run: () => void commands.applyStash(true, false) },
          { kind: "separator", id: "s3" },
          { id: "s-drop", label: t("ide_side_panel.git.scm.drop_stash"), disabled: !status?.stashes, run: () => void commands.dropStash() },
          { id: "s-drop-all", label: t("ide_side_panel.git.scm.drop_all_stashes"), disabled: !status?.stashes, run: () => void commands.dropAllStashes() },
        ],
      },
      {
        kind: "submenu",
        id: "tags-menu",
        label: t("ide_side_panel.git.scm.menu_tags"),
        items: [
          { id: "t-create", label: t("ide_side_panel.git.scm.create_tag"), run: () => void commands.createTag() },
          { id: "t-delete", label: t("ide_side_panel.git.scm.delete_tag"), run: () => void commands.deleteTag() },
        ],
      },
    ];
  }, [status, settings, commands, runCommit, undoLastCommit, follow, toggleFollow, t]);

  const pickSession = async () => {
    type Pick = { pane: string | null };
    const items = [
      { label: t("ide_side_panel.git.scm.all_changes"), icon: <Codicon name="git-compare" />, value: { pane: null } as Pick },
      ...workspacePanes.map((row) => ({
        label: row.display_name || row.agent ? `${row.name} · ${row.display_name || row.agent}` : row.name,
        description: row.recap || row.last_prompt || "",
        icon: <Codicon name={row.name === sessionPane ? "check" : "terminal"} />,
        group: t("ide_side_panel.git.scm.sessions"),
        value: { pane: row.name } as Pick,
      })),
    ];
    const picked = await quick.pick(items, t("ide_side_panel.git.scm.pick_session"));
    if (picked) setSessionPane(picked.pane);
  };

  const scopeMenu = (): MenuItem[] =>
    (["auto", "current", "all"] as GraphScope[]).map((value) => ({
      id: `scope-${value}`,
      label: t(`ide_side_panel.git.scm.scope.${value}`),
      checked: scope === value,
      run: () => setScope(value),
    }));

  const initRepository = async () => {
    if (!workspace?.path || initializing) return;
    setInitializing(true);
    try {
      await prepareGit(workspace.path, { mode: "init", branch: "", base: "" });
    } catch (err) {
      pushToast("error", (err as Error).message);
    } finally {
      setInitializing(false);
      refresh();
    }
  };

  const repoName = useMemo(
    () => ((status?.root || workspace?.path) ?? "").replace(/\\/g, "/").split("/").filter(Boolean).pop() ?? workspace?.name ?? "",
    [status?.root, workspace?.path, workspace?.name],
  );

  if (!workspace) {
    return <p className="px-4 py-6 text-center text-xs text-muted-foreground">{t("ide_side_panel.git.no_workspace")}</p>;
  }

  let changesBody;
  if (!status) {
    changesBody =
      error?.code === "unavailable" ? (
        <RestartToConnectCard />
      ) : error ? (
        <p data-testid="scm-error" className="px-[20px] py-[8px] text-[13px]" style={{ color: "var(--scm-deleted)" }}>
          {error.message}
        </p>
      ) : (
        <div className="flex justify-center py-4">
          <Codicon name="loading" spin />
        </div>
      );
  } else if (!status.available) {
    changesBody = (
      <div data-testid="scm-unavailable" className="space-y-[12px] px-[20px] py-[10px] text-[13px] leading-[1.4em]">
        <p>{t("ide_side_panel.git.scm.no_repository")}</p>
        <button
          type="button"
          data-testid="scm-init"
          disabled={initializing || !workspace.path}
          onClick={() => void initRepository()}
          className="scm-button inline-flex h-[26px] w-full items-center justify-center gap-[4px] rounded-[2px] px-[4px] text-[13px]"
        >
          {initializing && <Codicon name="loading" spin />}
          {t("ide_side_panel.git.scm.init_repository")}
        </button>
      </div>
    );
  } else {
    changesBody = (
      <ChangesView
        key={workspace.id}
        workspaceId={workspace.id}
        repoName={repoName}
        status={status}
        commands={commands}
        busy={busy}
        settings={settings}
        message={message}
        onMessage={setMessage}
        messageError={messageError}
        messageRef={messageRef}
        onCommit={runCommit}
        onDiff={setDiff}
        onRefresh={refresh}
        moreMenu={moreMenu}
        session={session}
        revision={revision}
        onClearSession={() => setSessionPane(null)}
      />
    );
  }

  const repository = status?.available;
  const followTip = (state: FollowMain) =>
    [
      t("ide_side_panel.git.scm.follow_main_on"),
      state.busy
        ? t(`ide_side_panel.git.scm.follow_busy_${state.busy}`)
        : state.restart_pending
          ? t("ide_side_panel.git.scm.follow_restart_pending")
          : state.reason,
      state.last_update ? fill(t("ide_side_panel.git.scm.follow_updated"), { when: agoLabel(state.last_update, lang, t), subject: state.last_subject }) : "",
      t("ide_side_panel.git.scm.follow_click_off"),
    ]
      .filter(Boolean)
      .join("\n");
  return (
    <section data-testid="ide-git-tab" aria-label={t("ide_side_panel.git.aria")} className="scm-root relative flex h-full min-h-0 flex-col">
      <div className="flex h-[35px] shrink-0 items-center pl-[20px] pr-[8px]">
        <span className="min-w-0 flex-1 truncate text-[13px]" style={{ color: "var(--scm-title-fg)" }}>
          {t("ide_side_panel.git.scm.title")}
        </span>
        {follow?.enabled && (
          <IconButton label={followTip(follow)} testId="scm-follow-status" onClick={toggleFollow}>
            <Codicon
              name={follow.busy ? "sync" : follow.restart_pending ? "debug-restart" : follow.reason ? "warning" : "cloud-download"}
              spin={Boolean(follow.busy)}
            />
          </IconButton>
        )}
        {repository && (
          <IconButton label={t("ide_side_panel.git.scm.more_actions")} testId="scm-title-more" onClick={(event) => setMenu({ items: moreMenu(), ...menuPointFor(event.currentTarget) })}>
            <Codicon name="ellipsis" />
          </IconButton>
        )}
      </div>
      <div className="relative h-[2px] shrink-0 overflow-hidden" aria-hidden>
        {busy && <div data-testid="scm-progress" className="scm-progress" />}
      </div>
      <ScmViews
        onWeights={(next) => setWeights((current) => ({ ...current, ...next }))}
        views={[
          {
            id: "changes",
            title: t("ide_side_panel.git.scm.view_changes"),
            open: open.changes,
            onToggle: () => toggleView("changes"),
            weight: weights.changes ?? 1,
            actions: repository ? (
              <>
              <IconButton
                label={session ? fill(t("ide_side_panel.git.scm.filtered_by"), { pane: session.pane }) : t("ide_side_panel.git.scm.filter_session")}
                testId="scm-session-filter"
                onClick={() => void pickSession()}
              >
                <Codicon name={session ? "filter-filled" : "filter"} />
              </IconButton>
              <IconButton
                label={settings.mode === "list" ? t("ide_side_panel.git.scm.view_tree") : t("ide_side_panel.git.scm.view_list")}
                testId="scm-view-mode"
                onClick={() => setSettings((current) => ({ ...current, mode: current.mode === "list" ? "tree" : "list" }))}
              >
                <Codicon name={settings.mode === "list" ? "list-tree" : "list-flat"} />
              </IconButton>
              </>
            ) : undefined,
            body: changesBody,
          },
          {
            id: "graph",
            title: t("ide_side_panel.git.scm.view_graph"),
            open: open.graph,
            onToggle: () => toggleView("graph"),
            weight: weights.graph ?? 1,
            actions: repository ? (
              <>
                <span className="mr-[4px] inline-flex min-w-0 items-center gap-[3px] text-[12px] opacity-80">
                  <Codicon name="repo" />
                  <span className="max-w-[110px] truncate">{repoName}</span>
                </span>
                <button
                  type="button"
                  data-testid="scm-graph-scope"
                  onClick={(event) => setMenu({ items: scopeMenu(), ...menuPointFor(event.currentTarget) })}
                  className="scm-action !w-auto gap-[3px] px-[3px] text-[12px]"
                >
                  <Codicon name="git-branch" />
                  {t(`ide_side_panel.git.scm.scope.${scope}`)}
                </button>
                <IconButton label={t("ide_side_panel.git.scm.go_to_current")} testId="scm-graph-head" onClick={() => setGoHead((value) => value + 1)}>
                  <Codicon name="target" />
                </IconButton>
                <IconButton label={t("ide_side_panel.git.scm.fetch")} testId="scm-graph-fetch" disabled={busy !== ""} onClick={() => void commands.fetch()}>
                  <Codicon name="repo-fetch" />
                </IconButton>
                <IconButton label={t("ide_side_panel.git.scm.pull")} testId="scm-graph-pull" disabled={busy !== ""} onClick={() => void commands.pull()}>
                  <Codicon name="repo-pull" />
                </IconButton>
                <IconButton label={t("ide_side_panel.git.scm.push")} testId="scm-graph-push" disabled={busy !== ""} onClick={() => void commands.push()}>
                  <Codicon name="repo-push" />
                </IconButton>
                <IconButton label={t("ide_side_panel.git.scm.refresh")} testId="scm-graph-refresh" onClick={onChanged}>
                  <Codicon name="refresh" />
                </IconButton>
              </>
            ) : undefined,
            body: repository ? (
              <GraphView workspaceId={workspace.id} revision={revision} scope={scope} commands={commands} onDiff={setDiff} targetHead={goHead} />
            ) : (
              <p className="px-[20px] py-[4px] text-[13px] opacity-70">{t("ide_side_panel.git.scm.no_commits")}</p>
            ),
          },
          {
            id: "branches",
            title: t("ide_side_panel.git.scm.view_branches"),
            open: open.branches,
            onToggle: () => toggleView("branches"),
            weight: weights.branches ?? 1,
            body: <RepositoryOverview onChanged={refresh} />,
          },
        ]}
      />
      {quick.element}
      {choice.element}
      {diff && <DiffDialog source={diff} onClose={() => setDiff(null)} />}
      {menu && <ScmMenu items={menu.items} x={menu.x} y={menu.y} onClose={() => setMenu(null)} />}
    </section>
  );
}
