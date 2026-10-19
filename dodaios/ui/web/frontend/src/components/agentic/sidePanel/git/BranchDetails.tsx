import { useEffect, useState, type ReactNode, type SVGProps } from "react";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ChevronRight,
  CirclePlay,
  FolderOpen,
  GitBranch,
  GitPullRequestCreate,
  Globe,
  Laptop,
  Loader2,
  SquareTerminal,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import { fill, useT } from "@/i18n";
import { useRunLocale } from "@/components/runs/format";
import { openExternalUrl } from "@/lib/openExternal";
import { cn } from "@/lib/utils";
import { QuickTooltip } from "@/components/ui/tooltip";
import { useEventStore } from "@/store/events";
import { branchUrl } from "./BranchMenu";
import { DiffView } from "../explorer/DiffView";
import { commitDateLabel, PR_ICON } from "./gitBadges";
import { isMerged, livePr, needsPull, needsPush, syncOf } from "./gitInsights";
import {
  fetchBranchContents,
  fetchBranchFileDiff,
  openBranchCheckout,
  type BranchContents,
  type BranchEditors,
  type BranchFile,
  type BranchFileDiff,
  type BranchRow,
} from "./gitOverviewApi";
import type { GitActions } from "./useGitActions";

function DetailButton({
  icon: Icon,
  label,
  testId,
  primary,
  danger,
  busy,
  disabled,
  onClick,
}: {
  icon: LucideIcon | ((props: SVGProps<SVGSVGElement>) => ReactNode);
  label: string;
  testId: string;
  primary?: boolean;
  danger?: boolean;
  busy?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 max-w-full items-center gap-1.5 rounded-md border px-2 text-[11.5px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
        primary
          ? "border-transparent bg-primary text-primary-foreground hover:bg-primary/90"
          : danger
            ? "border-border/70 text-destructive hover:bg-destructive/10"
            : "border-border/70 text-foreground/90 hover:bg-secondary",
      )}
    >
      {busy ? (
        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden />
      ) : (
        <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
      )}
      <span className="truncate">{label}</span>
    </button>
  );
}

/** A file's change as one coloured letter, like the Explorer's change list. */
const FILE_STATUS: Record<BranchFile["status"], { letter: string; tone: string }> = {
  added: { letter: "A", tone: "text-success" },
  deleted: { letter: "D", tone: "text-destructive" },
  modified: { letter: "M", tone: "text-warning" },
};

function BranchFileRow({
  file,
  workspaceId,
  branch,
  base,
  remote,
}: {
  file: BranchFile;
  workspaceId: string;
  branch: string;
  base: string;
  remote: boolean;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [diff, setDiff] = useState<BranchFileDiff | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open || diff) return;
    let alive = true;
    fetchBranchFileDiff(workspaceId, branch, base, remote, file.path)
      .then((answer) => alive && setDiff(answer))
      .catch((err: Error) => alive && setError(err.message));
    return () => {
      alive = false;
    };
  }, [open, diff, workspaceId, branch, base, remote, file.path]);
  const status = FILE_STATUS[file.status];
  const slash = file.path.lastIndexOf("/");
  return (
    <li data-testid="git-branch-file" data-path={file.path}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full min-w-0 items-center gap-1.5 rounded px-1 py-0.5 text-left hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronRight className={cn("h-3 w-3 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} aria-hidden />
        <span className={cn("w-3 shrink-0 text-center font-mono text-[10.5px] font-semibold", status.tone)}>{status.letter}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-[11px]">
          <span className="text-foreground">{file.path.slice(slash + 1)}</span>
          {slash > 0 && <span className="ml-1.5 text-muted-foreground">{file.path.slice(0, slash)}</span>}
        </span>
        {file.added === null ? (
          <span className="shrink-0 text-[10.5px] text-muted-foreground">{t("ide_side_panel.git.details.binary")}</span>
        ) : (
          <span className="shrink-0 font-mono text-[10.5px] tabular-nums">
            <span className="text-success">+{file.added}</span> <span className="text-destructive">−{file.removed}</span>
          </span>
        )}
      </button>
      {open && (
        <div data-testid="git-branch-file-diff" className="my-1 max-h-96 overflow-auto rounded-md border border-border/60 bg-background">
          {error ? (
            <p className="px-3 py-2 text-[11px] text-destructive">{error}</p>
          ) : !diff ? (
            <p className="flex items-center gap-1.5 px-3 py-2 text-[11px] text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden />
              {t("ide_side_panel.git.details.loading")}
            </p>
          ) : diff.binary ? (
            <p className="px-3 py-2 text-[11px] text-muted-foreground">{t("ide_side_panel.git.details.binary")}</p>
          ) : (
            <DiffView hunks={diff.hunks} />
          )}
        </div>
      )}
    </li>
  );
}

function DetailHeading({ children }: { children: ReactNode }) {
  return <h4 className="text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</h4>;
}

/**
 * What a clicked branch row folds open: what can be done with the branch
 * (switch to it, push it, bring it up to date, open its pull request, delete
 * it), where it lives, and the branch itself — its own commits and the files
 * it changes, each file's diff one click away.
 */
export function BranchDetails({
  row,
  repoUrl,
  defaultBranch,
  baseRef,
  githubReady,
  workspaceId,
  editors,
  actions,
}: {
  row: BranchRow;
  repoUrl: string;
  defaultBranch: string;
  baseRef: string;
  githubReady: boolean;
  workspaceId: string;
  editors: BranchEditors | null;
  actions: GitActions;
}) {
  const t = useT();
  const lang = useRunLocale();
  const pushToast = useEventStore((state) => state.pushToast);
  const [contents, setContents] = useState<BranchContents | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    fetchBranchContents(workspaceId, row.name, defaultBranch, row.remote_only)
      .then((answer) => alive && setContents(answer))
      .catch((err: Error) => alive && setError(err.message));
    return () => {
      alive = false;
    };
    // Re-read when the branch tip moves, not on every overview poll.
  }, [workspaceId, row.name, row.head, row.remote_only, defaultBranch]);

  const url = branchUrl(repoUrl, row);
  const checkedOut = !row.remote_only && (row.current || Boolean(row.worktree));
  const pr = row.pull_requests[0];
  const canOpen = checkedOut && Boolean(editors?.file_manager);
  const isDefault = row.name === defaultBranch;
  const sync = syncOf(row);
  const idle = actions.busy === "";

  const openLocal = (target: string) => {
    void openBranchCheckout(workspaceId, row.name, target)
      .then((result) => {
        if (!result.opened) pushToast("error", t("ide_side_panel.git.details.open_failed"));
      })
      .catch((err: Error) => pushToast("error", err.message || t("ide_side_panel.git.details.open_failed")));
  };

  const where = row.remote_only
    ? t("ide_side_panel.git.details.local_absent")
    : row.current
      ? t("ide_side_panel.git.current")
      : row.worktree
        ? `${t("ide_side_panel.git.details.local_worktree")} ${row.worktree}`
        : t("ide_side_panel.git.details.local_branch_only");
  const dateOf = (seconds: number) =>
    seconds ? new Intl.DateTimeFormat(lang, { dateStyle: "medium", timeStyle: "short" }).format(new Date(seconds * 1000)) : "";
  const showBase = !isDefault && baseRef && row.base_ahead != null && row.base_behind != null;

  return (
    <div data-testid="git-branch-details" className="space-y-3 border-t border-border/50 pb-3 pl-3 pr-3 pt-2.5 text-[11.5px]">
      <div data-testid="git-branch-actions" className="flex flex-wrap gap-1.5">
        {!row.current && !row.worktree && (
          <DetailButton
            icon={GitBranch}
            label={t(row.remote_only ? "ide_side_panel.git.act.check_out" : "ide_side_panel.git.act.switch")}
            testId="git-act-switch"
            busy={actions.busy === `switch:${row.name}`}
            disabled={!idle}
            onClick={() => actions.switchTo(row.name)}
          />
        )}
        {needsPull(row) && row.upstream && !row.upstream_gone && (
          <DetailButton
            icon={ArrowDownToLine}
            label={t(row.unfetched && !row.behind ? "ide_side_panel.git.act.fetch" : "ide_side_panel.git.act.update")}
            testId="git-act-update"
            busy={actions.busy === `update:${row.name}` || actions.busy === "fetch"}
            disabled={!idle}
            onClick={() => (row.unfetched && !row.behind ? void actions.fetch() : actions.update(row.name))}
          />
        )}
        {needsPush(row) && sync !== "diverged" && (
          <DetailButton
            icon={ArrowUpFromLine}
            label={t(sync === "ahead" ? "ide_side_panel.git.act.push" : "ide_side_panel.git.act.publish")}
            testId="git-act-push"
            busy={actions.busy === `push:${row.current ? "" : row.name}`}
            disabled={!idle}
            onClick={() => actions.push(row.current ? "" : row.name)}
          />
        )}
        {githubReady && !row.remote_only && !isDefault && !livePr(row) && !isMerged(row) && (
          <DetailButton
            icon={GitPullRequestCreate}
            label={t("ide_side_panel.git.act.create_pr")}
            testId="git-act-pr"
            busy={actions.busy === `pr:${row.current ? "" : row.name}`}
            disabled={!idle}
            onClick={() => actions.createPullRequest(row.current ? "" : row.name)}
          />
        )}
        {canOpen &&
          editors?.editors.map((editor) => (
            <DetailButton
              key={editor.id}
              icon={SquareTerminal}
              label={fill(t("ide_side_panel.git.details.open_in"), { editor: editor.label })}
              testId={`git-open-${editor.id}`}
              onClick={() => openLocal(editor.id)}
            />
          ))}
        {canOpen && (
          <DetailButton icon={FolderOpen} label={t("ide_side_panel.git.details.open_folder")} testId="git-open-folder" onClick={() => openLocal("folder")} />
        )}
        {url && <DetailButton icon={Globe} label={t("ide_side_panel.git.details.open_github")} testId="git-open-github" onClick={() => void openExternalUrl(url)} />}
        {pr && (
          <DetailButton
            icon={PR_ICON[pr.state]}
            label={fill(t("ide_side_panel.git.menu.open_pr"), { number: pr.number })}
            testId="git-open-pr"
            onClick={() => void openExternalUrl(pr.url)}
          />
        )}
        {row.ci.url && (
          <DetailButton icon={CirclePlay} label={t("ide_side_panel.git.menu.open_ci")} testId="git-open-ci" onClick={() => void openExternalUrl(row.ci.url)} />
        )}
        {!row.remote_only && !row.current && !isDefault && (
          <DetailButton
            icon={Trash2}
            label={t("ide_side_panel.git.act.delete")}
            testId="git-act-delete"
            danger
            busy={actions.busy === `delete:${row.name}`}
            disabled={!idle}
            onClick={() => actions.remove(row)}
          />
        )}
      </div>

      <p className="text-[11px] text-muted-foreground">
        <Laptop className="mr-1 inline h-3 w-3 align-[-2px]" aria-hidden />
        <span className="break-all">{where}</span>
        {row.upstream && (
          <span className="block pl-4">
            {row.upstream_gone
              ? fill(t("ide_side_panel.git.details.upstream_gone"), { upstream: row.upstream })
              : fill(t("ide_side_panel.git.tracks"), { upstream: row.upstream, ahead: row.ahead, behind: row.behind })}
          </span>
        )}
        {showBase && (
          <span data-testid="git-branch-base" className="block pl-4">
            {fill(t("ide_side_panel.git.details.vs_base"), { ahead: row.base_ahead ?? 0, behind: row.base_behind ?? 0, base: baseRef })}
          </span>
        )}
      </p>

      {error ? (
        <p className="text-[11px] text-destructive">{error}</p>
      ) : !contents ? (
        <p data-testid="git-branch-loading" className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden />
          {t("ide_side_panel.git.details.loading")}
        </p>
      ) : !contents.available ? (
        <p className="text-[11px] text-muted-foreground">{contents.reason}</p>
      ) : (
        <>
          <section data-testid="git-branch-commits" className="space-y-1">
            <DetailHeading>
              {contents.base
                ? fill(t("ide_side_panel.git.details.commits_vs"), { n: contents.commits.length, base: contents.base })
                : fill(t("ide_side_panel.git.details.commits_latest"), { n: contents.commits.length })}
            </DetailHeading>
            {contents.commits.length === 0 ? (
              <p className="text-[11px] text-muted-foreground">{fill(t("ide_side_panel.git.details.no_commits"), { base: contents.base })}</p>
            ) : (
              <ol className="space-y-0.5">
                {contents.commits.map((commit) => (
                  <li key={commit.sha} data-testid="git-branch-commit" data-sha={commit.sha} className="flex min-w-0 items-baseline gap-2">
                    {/* Only a commit GitHub has gets a link; one still only here would open a 404. */}
                    {repoUrl && commit.on_github ? (
                      <button
                        type="button"
                        data-testid="git-commit-link"
                        onClick={() => void openExternalUrl(`${repoUrl}/commit/${encodeURIComponent(commit.sha)}`)}
                        className="shrink-0 font-mono text-[10.5px] text-info hover:underline"
                      >
                        {commit.sha.slice(0, 7)}
                      </button>
                    ) : commit.on_github === false ? (
                      <QuickTooltip content={t("ide_side_panel.git.local_only_tip")} side="bottom" className="inline-flex shrink-0">
                        <span data-testid="git-commit-local" className="inline-flex items-center gap-1 font-mono text-[10.5px] text-warning">
                          <Laptop className="h-3 w-3" aria-hidden />
                          {commit.sha.slice(0, 7)}
                        </span>
                      </QuickTooltip>
                    ) : (
                      // An older backend does not say where the commit is: no link, no claim.
                      <span className="shrink-0 font-mono text-[10.5px] text-muted-foreground">{commit.sha.slice(0, 7)}</span>
                    )}
                    <QuickTooltip content={`${commit.subject}\n${commit.author} · ${dateOf(commit.committed_at)}`} side="bottom" className="flex min-w-0 flex-1">
                      <span className="truncate text-foreground">{commit.subject}</span>
                    </QuickTooltip>
                    <span className="shrink-0 text-[10.5px] tabular-nums text-muted-foreground">
                      {commit.committed_at ? commitDateLabel(commit.committed_at, lang) : ""}
                    </span>
                  </li>
                ))}
              </ol>
            )}
            {contents.commits_truncated && <p className="text-[10.5px] text-muted-foreground">{t("ide_side_panel.git.details.more_commits")}</p>}
          </section>
          {contents.base && (
            <section data-testid="git-branch-files" className="space-y-1">
              <DetailHeading>{fill(t("ide_side_panel.git.details.files"), { n: contents.files.length })}</DetailHeading>
              <ul>
                {contents.files.map((file) => (
                  <BranchFileRow key={file.path} file={file} workspaceId={workspaceId} branch={row.name} base={defaultBranch} remote={row.remote_only} />
                ))}
              </ul>
              {contents.files_truncated && <p className="text-[10.5px] text-muted-foreground">{t("ide_side_panel.git.details.more_files")}</p>}
            </section>
          )}
        </>
      )}
    </div>
  );
}
